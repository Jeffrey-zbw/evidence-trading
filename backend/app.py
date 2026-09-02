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

        # 筛选中小市值 50-300亿，排除涨停股
        filtered_stocks = []
        for stock in stocks:
            mv = stock.get('total_mv_yi', 0)
            change_pct = stock.get('change_pct', 0)
            # 市值 50-300亿 + 排除涨停股（涨幅≥9.5%）
            if 50 <= mv <= 300 and change_pct < 9.5:
                filtered_stocks.append(stock)

        # 添加评分
        for stock in filtered_stocks:
            score = 0
            change_pct = stock.get('change_pct', 0)
            # 涨跌幅因子：温和波动优先
            if -3 <= change_pct <= 3:
                score += 40
            elif 3 < change_pct < 9.5:
                score += max(0, 40 - (change_pct - 3) * 5)
            elif change_pct < -3:
                score += max(0, 20 + change_pct)

            # PE估值因子
            pe = stock.get('pe_ratio')
            if pe and 0 < pe < 50:
                score += min(30, max(0, 50 - pe))
            elif pe and pe >= 50:
                score += 10

            # 成交量因子
            volume = stock.get('volume', 0)
            score += min(30, volume / 500000)

            stock["total_score"] = round(score, 1)

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


# ========== 新增 API 接口 ==========

@app.get("/api/market/summary")
async def market_summary():
    """获取市场复盘数据"""
    return {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "indices": {
            "shanghai": {"price": 3981.12, "change_pct": 0.73},
            "shenzhen": {"price": 14004.00, "change_pct": 0.37},
            "chinext": {"price": 3435.82, "change_pct": 0.33}
        },
        "hot_sectors": ["AI算力", "半导体", "高股息红利", "华为算力链"],
        "cool_sectors": ["锂电池", "人形机器人"],
        "sentiment": "偏谨慎但具韧性，资金向业绩确定性方向切换",
        "data_source": "mock"
    }


@app.get("/api/trading/plan")
async def trading_plan():
    """获取次日交易计划"""
    return {
        "date": (datetime.now()).strftime("%Y-%m-%d"),
        "plans": [
            {
                "code": "002283",
                "name": "天润工业",
                "stop_profit": 9.20,
                "stop_loss": 8.00,
                "rules": [
                    "开盘高于8.64且放量，持有看9.00",
                    "开盘低于8.40且10分钟未收复，减半仓",
                    "触及止盈9.20自动卖出",
                    "跌破止损8.00无条件离场"
                ]
            },
            {
                "code": "600221",
                "name": "海航控股",
                "stop_profit": 1.50,
                "stop_loss": 1.20,
                "rules": [
                    "深套-83%，除非重大利好不建议割肉",
                    "反弹至1.35以上可减仓1/3降成本",
                    "底部震荡为主，耐心等待"
                ]
            },
            {
                "code": "603993",
                "name": "洛阳钼业",
                "stop_profit": 20.50,
                "stop_loss": 18.00,
                "rules": [
                    "若低开低走破18.50坚决止损",
                    "企稳19.00上方可持有等反弹至20.00减仓",
                    "突破20.50分批止盈"
                ]
            }
        ],
        "data_source": "mock"
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
