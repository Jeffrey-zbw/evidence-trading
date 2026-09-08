#!/usr/bin/env python3
"""
Evidence-Trading FastAPI Backend
提供 HTTP API 供 H5 前端调用
"""

import sys
from pathlib import Path
from datetime import datetime

# 添加 tools 目录到路径
tools_path = Path.home() / ".hermes/skills/evidence-trading/tools"
sys.path.insert(0, str(tools_path))

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from pathlib import Path
import json

from market_bot import MarketBot
from analysis_bot import AnalysisBot
from risk_bot import RiskBot

# 唯一持仓源：skills/evidence-trading/tools/positions_lib.py
# （底层数据为 skills/evidence-trading/data/positions.json，由 update_positions.py 维护）
sys.path.insert(0, str(tools_path))
try:
    from positions_lib import active_positions, alert_rules
except Exception:  # positions_lib 缺失时兜底为空
    def active_positions():
        return []

    def alert_rules():
        return []

# ========== 同源数据目录（H5 与日常推送共用，由 14:35 解析脚本落盘） ==========
DATA_DIR = Path(__file__).parent.parent / "data"


def _load_data(filename: str, default=None):
    """读 data/ 目录下的 JSON（同源数据源）；缺失返回 default。"""
    p = DATA_DIR / filename
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return default
    return default


def _linear_rank(values: List[float], higher_is_better: bool = True) -> List[float]:
    """线性分位打分：前1%得满分，后1%得0分，中间线性插值"""
    if not values:
        return []
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    rank_map = {}
    for i, v in enumerate(sorted_vals):
        rank_map[v] = i / (n - 1) if n > 1 else 0.5
    if not higher_is_better:
        return [1 - rank_map.get(v, 0.5) for v in values]
    return [rank_map.get(v, 0.5) for v in values]


def _linear_rank_pe(pe_values: List[float]) -> List[float]:
    """PE估值反向打分：PE越低得分越高"""
    if not pe_values:
        return []
    sorted_vals = sorted(pe_values)
    n = len(sorted_vals)
    rank_map = {}
    for i, v in enumerate(sorted_vals):
        rank_map[v] = i / (n - 1) if n > 1 else 0.5
    # 反向：低PE得高分
    return [1 - rank_map.get(v, 0.5) for v in pe_values]

app = FastAPI(title="Evidence-Trading API", version="1.0.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件服务（前端页面）
frontend_path = Path(__file__).parent.parent / "frontend"
app.mount("/frontend", StaticFiles(directory=str(frontend_path)), name="frontend")

# 初始化 Bot
market_bot = MarketBot()
analysis_bot = AnalysisBot()
risk_bot = RiskBot()


class BacktestRequest(BaseModel):
    symbol: str
    strategy: str = "ma_cross"
    params: Dict[str, Any] = {}


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "Evidence-Trading API"}


@app.get("/api/status")
async def status():
    return {
        "market_bot": market_bot.get_status(),
        "analysis_bot": analysis_bot.get_status(),
        "risk_bot": risk_bot.get_status(),
    }


@app.get("/api/picks")
async def picks(n: int = Query(10, ge=1, le=50)):
    """获取选股推荐。同源：14:30 日报候选；无则实时量化扫描。"""
    # 1) 同源：解析自 14:30 日报的候选（含看多逻辑/介入区间/仓位）
    daily = _load_data("daily_picks.json")
    if daily and daily.get("picks"):
        return {
            "date": daily.get("date"),
            "picks": daily["picks"][:n],
            "data_source": daily.get("data_source", "market 日报"),
            "report_file": daily.get("report_file"),
            "note": daily.get("note", "仅为技术推演，非投资建议"),
            "is_live_scan": False,
        }
    # 2) 兜底：实时量化扫描（刚收盘/日报未生成时）
    try:
        picked = market_bot.scan_stocks_by_quant(limit=n)
        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "picks": picked,
            "data_source": "mock" if market_bot.use_mock else "tencent",
            "filter_stats": {"total_candidates": len(picked), "final_count": len(picked)},
            "is_live_scan": True,
            "note": "日报候选未生成，展示实时量化扫描结果",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/quote/{symbol}")
async def quote(symbol: str):
    """获取行情"""
    result = market_bot.get_quote(symbol)
    if not result:
        raise HTTPException(status_code=404, detail="Stock not found")
    return result


@app.get("/api/kline/{symbol}")
async def kline(symbol: str, days: int = Query(365, ge=1, le=730)):
    """获取 K 线数据"""
    result = market_bot.get_kline(symbol, days)
    return {"symbol": symbol, "days": days, "data": result[-30:]}


@app.post("/api/backtest")
async def backtest(req: BacktestRequest):
    """执行策略回测"""
    try:
        result = analysis_bot.run_backtest(
            symbol=req.symbol,
            strategy=req.strategy,
            params=req.params
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/risk/check")
async def risk_check(positions: Optional[str] = None):
    """检查持仓风险。唯一持仓源：positions.json（active_positions）。
    优先返回 14:35 同源 risk_check.json；否则实时算。"""
    # 同源优先
    cached = _load_data("risk_check.json")
    if cached and cached.get("positions"):
        return cached
    # 实时计算（兜底）
    try:
        if positions is None:
            pos_list = active_positions()
        else:
            pos_list = json.loads(positions)
        if not pos_list:
            raise HTTPException(status_code=404, detail="无持仓数据（positions.json 为空）")
        result = risk_bot.check_position_risk(pos_list)
        result["alerts"] = _compute_abs_alerts(pos_list)
        result["positions_source"] = "positions.json (live)"
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _compute_abs_alerts(pos_list: List[Dict]) -> List[Dict]:
    """按 positions.json 的 alert_drop/alert_rise（绝对价）判断预警。"""
    out = []
    for rule in alert_rules():
        code = rule["code"]
        try:
            q = market_bot.get_quote(code)
            price = q.get("price") if q and "price" in q else None
        except Exception:
            price = None
        if price is None:
            continue
        if rule.get("drop") is not None and price <= rule["drop"]:
            out.append({"code": code, "name": rule["name"], "type": "跌破预警",
                       "price": price, "threshold": rule["drop"],
                       "message": f"⚠️ {rule['name']} 现价 {price} 已跌破预警线 {rule['drop']}"})
        if rule.get("rise") is not None and price >= rule["rise"]:
            out.append({"code": code, "name": rule["name"], "type": "突破预警",
                       "price": price, "threshold": rule["rise"],
                       "message": f"🎉 {rule['name']} 现价 {price} 已突破预警线 {rule['rise']}"})
    return out


@app.get("/api/risk/alert")
async def risk_alert():
    """检查风险预警（绝对价，源自 positions.json）。"""
    alerts = _compute_abs_alerts(active_positions())
    return {"alerts": alerts, "timestamp": datetime.now().isoformat(),
            "positions_source": "positions.json"}


# ========== 新增 API 接口 ==========

@app.get("/api/market/summary")
async def market_summary():
    """获取市场复盘数据。同源：读 14:35 解析的日报（overview/热点/情绪）。"""
    data = _load_data("market_summary.json")
    if data and data.get("overview"):
        return data
    # 兜底：日报尚未解析，提示前端
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "overview": "",
        "hot_sectors": [],
        "sentiment": "",
        "data_source": "pending",
        "note": "今日日报复盘尚未生成（14:35 后自动落盘），暂无内容。",
    }


@app.get("/api/trading/plan")
async def trading_plan():
    """获取次日交易计划。同源：读 14:35 解析的日报止盈止损块。"""
    data = _load_data("trading_plan.json")
    if data and data.get("plans"):
        return data
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "plans": [],
        "data_source": "pending",
        "note": "今日日报交易计划尚未生成（14:35 后自动落盘）。",
    }


@app.get("/api/risk/disclaimer")
async def risk_disclaimer():
    """获取风险提示"""
    return {
        "warning": "以上全部为AI基于盘面技术推演模拟输出，**不构成任何投资建议**。A股市场波动风险高，14:30临近收盘存在尾盘异动风险，次日集合竞价跳空会直接击穿止盈止损点位，实际交易请结合自身风险承受能力自主决策，盈亏自负。不要直接照搬AI结果实盘。",
        "risk_level": "高风险",
        "recommendation": "建议仓位不超过总资金30%，单只股票不超过15%"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
