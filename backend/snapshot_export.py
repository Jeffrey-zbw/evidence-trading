#!/usr/bin/env python3
"""stockquant API → 4 个 data/*.json 快照导出（卡片⑤）。铁律：全部取数成功后才原子替换旧文件；
失败一律非零退出并打印原因，绝不写旧数据/半套数据。输出带「不构成投资建议」。"""
import json, os, re, sys, tempfile, urllib.request
from datetime import date, datetime
from pathlib import Path

BASE = os.environ.get("BASE_OVERRIDE", "http://127.0.0.1:8787")
REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
ENV_FILE = Path.home() / "stockquant" / ".env"
DISCLAIMER = "不构成投资建议"

def die(code, msg):
    print(f"[snapshot_export] FAIL: {msg}", file=sys.stderr)
    sys.exit(code)

def get_json(url, token=None, timeout=15):
    headers = {"X-Auth": token} if token else {}
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def post_json(url, obj, timeout=15):
    req = urllib.request.Request(url, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))

def read_access_code():
    if not ENV_FILE.exists():
        die(5, f"找不到 {ENV_FILE}（stockquant 仓库 .env 缺失，AI盘未挂载？）")
    m = re.search(r"^ACCESS_CODE=(.+)$", ENV_FILE.read_text(), re.M)
    if not m:
        die(5, ".env 中无 ACCESS_CODE")
    return m.group(1).strip().strip('"\'')

def main():
    today = date.today().isoformat()
    try:                                   # 0) 探活（免鉴权）
        get_json(BASE + "/api/health", timeout=5)
    except Exception as e:
        die(2, f"stockquant 服务不可达 {BASE}/api/health: {e}")
    try:                                   # 1) 鉴权
        token = post_json(BASE + "/api/auth", {"code": read_access_code()}).get("token")
        if not token:
            die(3, "auth 未返回 token（ACCESS_CODE 失效？）")
    except SystemExit:
        raise
    except Exception as e:
        die(3, f"auth 失败: {e}")
    try:                                   # 2) 取数
        report = get_json(BASE + f"/api/daily_report?date={today}", token=token, timeout=60)  # 冷调用实测 ~30s，放宽到 60s
        if not isinstance(report, dict) or not report.get("summary"):
            die(4, f"daily_report {today} 返回空/缺 summary（当日报告尚未生成？）")
        picks = get_json(BASE + "/api/picks", token=token)
    except SystemExit:
        raise
    except Exception as e:
        die(4, f"取数失败: {e}")
    items = (picks or {}).get("items") or []
    s = report.get("summary") or {}
    market, sentiment, signal = s.get("market") or {}, s.get("sentiment") or {}, s.get("signal") or {}
    win, hsum = signal.get("win_rate"), s.get("holdings") or {}
    gate, holdings = report.get("gate") or {}, report.get("holdings") or []

    market_summary = {                     # ← summary（大盘/情绪/信号胜率）
        "date": today,
        "overview": (f"指数 {market.get('index_state') or 'N/A'}"
                     f"（涨跌 {format(market.get('index_pct') or 0, '+.2%')}）"
                     f"；当日信号 {signal.get('count') or 0} 只"
                     + (f"，历史胜率 {format(win, '.1%')}" if win is not None else "")
                     + f"；{DISCLAIMER}"),
        "hot_sectors": [],                  # stockquant 无板块数据，留空
        "sentiment": (f"情绪分 {sentiment.get('score')}" if sentiment.get("score") is not None
                      else "情绪数据缺失") + f"；{DISCLAIMER}",
        "data_source": "stockquant-snapshot",
        "report_file": "",
    }
    daily_picks = {                        # ← picks.items（code/name/strategy + gate 字段）
        "date": (picks or {}).get("trade_date") or today,
        "picks": [
            {"code": it.get("code"), "name": it.get("name"), "strategy": it.get("strategy"),
             "total_score": it.get("score"),
             "entry_zone": (f"{it.get('buy_low')}~{it.get('buy_high')}"
                            if it.get("buy_low") is not None else None),
             "price": it.get("open_ref"),
             "logic": "；".join(it.get("reasons") or [])
                      + ("；" + it.get("guard_note") if it.get("guard_note") else ""),
             "guard_state": it.get("guard_state"), "observation_only": it.get("observation_only")}
            for it in items
        ],
        "data_source": "stockquant-snapshot",
        "note": f"观察性信号，{DISCLAIMER}",
        "report_file": "",
    }
    advice = report.get("advice") or []
    trading_plan = {                       # ← advice（list[str] → 模板兼容对象）
        "date": today,
        "plans": [{"name": "规则化提示", "code": "", "stop_profit": None, "stop_loss": None,
                   "rules": a} for a in advice],
        "data_source": "stockquant-snapshot", "risk_levels": [], "report_file": "",
    }
    risk_check = {                         # ← holdings + gate + day_alerts（稳健结论在 risks）
        "total_value": 0, "total_pnl": 0,
        "total_pnl_pct": round((hsum.get("total_pnl_pct") or 0) * 100, 2),
        "risk_score": None,
        "risk_level": "开放（双门槛开启）" if gate.get("open") else "防守（双门槛关闭）",
        "positions": [
            {"code": h.get("code"), "name": h.get("name"), "shares": None, "cost": None,
             "current_price": h.get("price"),
             "profit_pct": round((h.get("pnl_pct") or 0) * 100, 2), "weight": None}
            for h in holdings],
        "risks": gate.get("reasons") or [],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "alerts": report.get("day_alerts") or [],
        "positions_source": report.get("holdings_source") or "unknown",
        "note": DISCLAIMER,
        "data_source": "stockquant-snapshot",
    }
    files = {"market_summary.json": market_summary, "daily_picks.json": daily_picks,
             "trading_plan.json": trading_plan, "risk_check.json": risk_check}
    tmp = tempfile.mkdtemp(dir=DATA)       # 同盘原子替换：先全量写 tmp，再逐个 replace
    try:
        for name, obj in files.items():
            with open(os.path.join(tmp, name), "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
        for name in files:
            Path(tmp, name).replace(DATA / name)   # 同盘原子替换：tmp 文件 → data/<name>
        os.rmdir(tmp)
    except Exception:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    print(f"[snapshot_export] OK: 4 文件已更新（data_source=stockquant-snapshot，{DISCLAIMER}）")

if __name__ == "__main__":
    main()
