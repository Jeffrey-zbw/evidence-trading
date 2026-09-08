// Vercel Serverless — Evidence-Trading API (方案 A: 静态快照 + 实时报价)
// - 复盘/计划/持仓: 读 git 提交的 data/*.json (每天 14:45 由本机解析后 push, Vercel 自动部署)
// - 实时报价: 直接调腾讯财经 API (serverless, 不经 Mac)
// - 回测: 返回 mock (K线本身即模拟, 与本地一致)
const https = require('https');

// ---- 方案 A 核心: 数据在【构建期】打包进 serverless 函数 ----
// 本机 14:45 解析生成 data/*.json 并 git push, Vercel 构建时把 JSON 内容打进函数,
// 运行时不依赖文件系统。静态字符串 require 写在模块顶层, 打包器才能把内容 bundle 进去;
// 缺文件 (本地刚 clone 还没生成) 则置 null, 接口走 pending fallback。
let market_summary = null;
try { market_summary = require('../data/market_summary.json'); } catch (e) { /* pending */ }
let daily_picks = null;
try { daily_picks = require('../data/daily_picks.json'); } catch (e) { /* pending */ }
let trading_plan = null;
try { trading_plan = require('../data/trading_plan.json'); } catch (e) { /* pending */ }
let risk_check = null;
try { risk_check = require('../data/risk_check.json'); } catch (e) { /* pending */ }
const DATA = { market_summary, daily_picks, trading_plan, risk_check };
// 调用方传 'xxx.json', DATA 键无后缀; 去掉 .json 再查, 命中不了走 fallback。
function readData(name, fallback) {
  const key = name.replace(/\.json$/, '');
  return DATA[key] != null ? DATA[key] : fallback;
}

function send(res, status, obj) {
  res.statusCode = status;
  res.setHeader('Content-Type', 'application/json; charset=utf-8');
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.end(JSON.stringify(obj));
}

function codePrefix(code) {
  return code.startsWith('6') ? 'sh' : 'sz';
}

function liveQuote(code) {
  return new Promise((resolve) => {
    const sym = codePrefix(code) + code.replace(/^sh|^sz/, '');
    const url = `https://qt.gtimg.cn/q=${sym}`;
    https.get(url, (r) => {
      let buf = '';
      r.on('data', (d) => (buf += d));
      r.on('end', () => {
        try {
          const text = Buffer.from(buf, 'latin1').toString('utf8');
          const parts = text.split('~');
          if (parts.length < 45) return resolve(null);
          resolve({
            code: parts[2], name: parts[1],
            price: parseFloat(parts[3]) || 0,
            change_pct: parseFloat(parts[32]) || 0,
            volume: parseFloat(parts[36]) * 100 || 0,
            amount: parseFloat(parts[37]) || 0,
            pe_ratio: parts[39] && parts[39] !== '-' ? parseFloat(parts[39]) : null,
            total_mv_yi: parts[44] && parts[44] !== '-' ? parseFloat(parts[44]) : 0,
            source: 'tencent-live',
          });
        } catch (e) { resolve(null); }
      });
    }).on('error', () => resolve(null));
  });
}

// 从已生成的候选里选一只拿实时价 (候选是当日筛选, 实时价补充)
async function dailyPicks(n) {
  const d = await readData('daily_picks.json', { picks: [] });
  const picks = Array.isArray(d.picks) ? d.picks.slice(0, n) : [];
  for (const p of picks) {
    if (p.code) {
      const q = await liveQuote(p.code);
      if (q) {
        p.price = q.price;
        p.change_pct = q.change_pct;
        p.live = true;
      }
    }
  }
  if (d.report_file) picks.forEach((p) => (p.report_file = d.report_file));
  return {
    date: d.date || new Date().toISOString().split('T')[0],
    picks,
    data_source: 'market 日报 + 腾讯实时价',
    note: d.note || '仅为技术推演，非投资建议',
  };
}

const MOCK_BACKTEST = {
  strategy: 'MA交叉(20/50)',
  metrics: { total_return: 0.124, final_value: 112400, benchmark_return: 0.08, total_trades: 6 },
  data_source: 'mock',
  note: 'K线数据为模拟，回测结果仅供参考',
};

module.exports = async (req, res) => {
  const url = new URL(req.url, 'http://' + (req.headers.host || 'localhost'));
  const path = url.pathname;
  const n = parseInt(url.searchParams.get('n') || '10', 10);

  res.setHeader('Access-Control-Allow-Origin', '*');
  if (req.method === 'OPTIONS') { res.statusCode = 204; res.end(); return; }

  try {
    if (path === '/api/health') {
      send(res, 200, { status: 'ok', service: 'Evidence-Trading (Vercel 快照)' });
    } else if (path === '/api/picks') {
      send(res, 200, await dailyPicks(n));
    } else if (path === '/api/quote') {
      const code = url.searchParams.get('code');
      const q = code ? await liveQuote(code) : null;
      q ? send(res, 200, q) : send(res, 404, { error: 'quote unavailable' });
    } else if (path.startsWith('/api/quote/')) {
      const code = path.split('/').pop();
      const q = await liveQuote(code);
      q ? send(res, 200, q) : send(res, 404, { error: 'quote unavailable' });
    } else if (path === '/api/market/summary') {
      const d = await readData('market_summary.json', {});
      send(res, 200, d.overview ? d : {
        date: new Date().toISOString().split('T')[0], overview: '', hot_sectors: [],
        sentiment: '', data_source: 'pending', note: '今日日报复盘尚未生成。',
      });
    } else if (path === '/api/trading/plan') {
      const d = await readData('trading_plan.json', {});
      send(res, 200, d.plans ? d : { date: new Date().toISOString().split('T')[0], plans: [], data_source: 'pending', note: '今日日报交易计划尚未生成。' });
    } else if (path === '/api/risk/check') {
      const d = await readData('risk_check.json', {});
      send(res, 200, d.positions ? d : { positions: [], total_pnl: 0, total_pnl_pct: 0, risk_score: 0, risk_level: 'N/A', data_source: 'pending', note: '今日持仓快照尚未生成。' });
    } else if (path === '/api/risk/alert') {
      const d = await readData('risk_check.json', { alerts: [] });
      send(res, 200, { alerts: d.alerts || [], data_source: 'snapshot', note: '价格预警快照（14:45 生成）' });
    } else if (path === '/api/backtest') {
      // 回测用模拟 K 线 (本地/云端一致), 读 query 里的 symbol, 不依赖 request body
      const symbol = url.searchParams.get('symbol') || '';
      send(res, 200, { ...MOCK_BACKTEST, symbol });
    } else {
      send(res, 404, { error: 'Not found', path });
    }
  } catch (e) {
    send(res, 500, { error: String(e.message || e) });
  }
};
