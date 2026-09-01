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
    """获取选股推荐（中小市值 50-300亿）"""
    try:
        # 获取全市场股票
        stocks = market_bot.get_all_stocks()

        # 筛选中小市值 50-300亿
        filtered_stocks = []
        for stock in stocks:
            mv = stock.get('total_mv_yi', 0)
            if 50 <= mv <= 300:
                filtered_stocks.append(stock)

        # 添加评分
        for stock in filtered_stocks:
            stock["total_score"] = analysis_bot.score_stock(stock) if hasattr(analysis_bot, 'score_stock') else 50
        filtered_stocks.sort(key=lambda x: x.get("total_score", 0), reverse=True)

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "picks": filtered_stocks[:n],
            "data_source": "mock" if market_bot.use_mock else "eastmoney"
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
    """检查持仓风险"""
    try:
        # 使用默认持仓
        if positions is None:
            positions = [
                {"code": "002283", "name": "天润工业", "shares": 100, "cost": 4.615},
                {"code": "600221", "name": "海航控股", "shares": 500, "cost": 8.0047},
                {"code": "603993", "name": "洛阳钼业", "shares": 300, "cost": 20.58},
                {"code": "002181", "name": "粤传媒", "shares": 100, "cost": 22.97},
                {"code": "601618", "name": "中国中冶", "shares": 100, "cost": 3.39},
            ]
        else:
            positions = json.loads(positions)

        result = risk_bot.check_position_risk(positions)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/risk/alert")
async def risk_alert():
    """检查风险预警"""
    try:
        positions = [
            {"code": "002283", "name": "天润工业", "shares": 100, "cost": 4.615},
            {"code": "600221", "name": "海航控股", "shares": 500, "cost": 8.0047},
            {"code": "603993", "name": "洛阳钼业", "shares": 300, "cost": 20.58},
            {"code": "002181", "name": "粤传媒", "shares": 100, "cost": 22.97},
            {"code": "601618", "name": "中国中冶", "shares": 100, "cost": 3.39},
        ]
        alerts = risk_bot.check_alerts(positions)
        return {"alerts": alerts, "timestamp": risk_bot._get_timestamp()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
