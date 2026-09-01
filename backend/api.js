#!/usr/bin/env node
/**
 * Vercel Serverless Function - Evidence-Trading API
 * 适配 Vercel 的 HTTP handler 格式
 */

const { createServer } = require('http');
const { serve } = require('@vercel/node');
const { join } = require('path');

// 模拟 FastAPI 路由逻辑
module.exports = (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host}`);
  const path = url.pathname;
  
  // CORS
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  
  if (req.method === 'OPTIONS') {
    res.writeHead(200);
    res.end();
    return;
  }
  
  // 路由分发
  if (path === '/api/health') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', service: 'Evidence-Trading API (Vercel)' }));
  } else if (path === '/api/picks') {
    // 返回模拟数据（Vercel 无法直接调用 Python）
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      date: new Date().toISOString().split('T')[0],
      picks: [
        { code: '002594', name: '比亚迪', sector: '汽车', price: 303.03, change_pct: 2.29, total_score: 71.5, total_mv_yi: 8200 },
        { code: '000858', name: '五粮液', sector: '白酒', price: 178.50, change_pct: 1.15, total_score: 68.2, total_mv_yi: 7100 },
        { code: '601012', name: '隆基绿能', sector: '光伏', price: 35.80, change_pct: -0.56, total_score: 65.0, total_mv_yi: 1800 },
      ],
      data_source: 'mock'
    }));
  } else if (path === '/api/risk/check') {
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      total_value: 13553.72,
      total_pnl: 279.87,
      total_pnl_pct: 2.06,
      risk_score: 2.1,
      risk_level: '🟢 低风险',
      positions: [
        { code: '002283', name: '天润工业', shares: 100, cost: 4.615, current_price: 8.49, profit_pct: 83.9, weight: 10.0 },
        { code: '600221', name: '海航控股', shares: 500, cost: 8.0047, current_price: 1.31, profit_pct: -83.6, weight: 4.8 },
        { code: '603993', name: '洛阳钼业', shares: 300, cost: 20.58, current_price: 19.03, profit_pct: -7.5, weight: 41.3 },
        { code: '002181', name: '粤传媒', shares: 100, cost: 22.97, current_price: 8.70, profit_pct: -62.1, weight: 6.2 },
        { code: '601618', name: '中国中冶', shares: 100, cost: 3.39, current_price: 2.56, profit_pct: -24.5, weight: 1.9 },
      ]
    }));
  } else {
    res.writeHead(404, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ error: 'Not found' }));
  }
};
