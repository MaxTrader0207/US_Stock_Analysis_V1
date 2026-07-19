#!/usr/bin/env python3
"""
抓取美股大型權值股日線／週線資料，計算技術指標並輸出 data/screener.json。
用法：python scripts/fetch_screener.py
需求：pip install yfinance pandas

選股條件一（多頭排列強勢股）：
  1. 日線收盤價 > 日線 30MA
  2. 日線 30MA 呈上揚（近5個交易日 30MA 上升）
  3. 日線 MACD (DIF) 在 0 軸之上
  4. 週線 MACD 柱狀體 (OSC) 翻紅（> 0）

條件二、三為預留擴充位，之後把邏輯加進 CONDITION_SETS 即可，
前端 screener.html / screener.js 不需要修改。
"""
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

# TODO: 可依需求增減成分股，或改為自動抓取 S&P 500 / Nasdaq 100 成分股清單
US_LARGE_CAP_TICKERS = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet",
    "AMZN": "Amazon", "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom",
    "BRK-B": "Berkshire Hathaway", "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard",
    "LLY": "Eli Lilly", "UNH": "UnitedHealth", "JNJ": "Johnson & Johnson", "XOM": "Exxon Mobil",
    "CVX": "Chevron", "HD": "Home Depot", "PG": "Procter & Gamble", "COST": "Costco",
    "ORCL": "Oracle", "ABBV": "AbbVie", "MRK": "Merck", "KO": "Coca-Cola", "PEP": "PepsiCo",
    "ADBE": "Adobe", "CRM": "Salesforce", "NFLX": "Netflix", "AMD": "AMD", "CSCO": "Cisco",
    "TMO": "Thermo Fisher", "MCD": "McDonald's", "ABT": "Abbott Labs", "WMT": "Walmart",
    "BAC": "Bank of America", "PFE": "Pfizer", "DIS": "Disney", "NKE": "Nike",
    "TMUS": "T-Mobile", "CAT": "Caterpillar", "GE": "GE Aerospace", "IBM": "IBM",
    "QCOM": "Qualcomm", "TXN": "Texas Instruments", "INTC": "Intel", "NOW": "ServiceNow",
    "AMAT": "Applied Materials", "INTU": "Intuit", "BA": "Boeing", "HON": "Honeywell",
}


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    osc = (dif - dea) * 2
    return dif, dea, osc


def evaluate_condition_1(symbol, name):
    hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty or len(hist) < 60:
        return None
    close = hist["Close"]

    ma30 = close.rolling(30).mean()
    if pd.isna(ma30.iloc[-1]) or pd.isna(ma30.iloc[-6]):
        return None
    above_ma30 = close.iloc[-1] > ma30.iloc[-1]
    ma30_rising = ma30.iloc[-1] > ma30.iloc[-6]

    dif_d, _, _ = macd(close)
    macd_daily_positive = dif_d.iloc[-1] > 0

    weekly_close = close.resample("W-FRI").last().dropna()
    if len(weekly_close) < 35:
        return None
    _, _, osc_w = macd(weekly_close)
    macd_weekly_red = osc_w.iloc[-1] > 0

    if not (above_ma30 and ma30_rising and macd_daily_positive and macd_weekly_red):
        return None

    prev_close = close.iloc[-2] if len(close) > 1 else close.iloc[-1]
    chg_pct = (close.iloc[-1] - prev_close) / prev_close * 100

    return {
        "symbol": symbol,
        "name": name,
        "price": round(float(close.iloc[-1]), 2),
        "changePercent": round(float(chg_pct), 2),
        "badges": ["站上30MA", "30MA上揚", "日MACD>0", "週MACD紅柱"],
    }


def build_condition_1():
    results = []
    for symbol, name in US_LARGE_CAP_TICKERS.items():
        try:
            r = evaluate_condition_1(symbol, name)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)
    results.sort(key=lambda r: r["changePercent"], reverse=True)
    return {
        "id": "trend-strength",
        "name": "多頭排列強勢股",
        "description": "日線收盤價 > 日線30MA，且30MA上揚；日線MACD在0軸之上；週線MACD柱狀體翻紅（多頭動能）。母體：美股大型權值股。",
        "status": "active",
        "results": results,
    }


def main():
    condition_sets = [
        build_condition_1(),
        {
            "id": "condition-2",
            "name": "選股條件二",
            "description": "規劃中，將於後續版本補上。",
            "status": "coming-soon",
            "results": [],
        },
        {
            "id": "condition-3",
            "name": "選股條件三",
            "description": "規劃中，將於後續版本補上。",
            "status": "coming-soon",
            "results": [],
        },
    ]
    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "conditionSets": condition_sets,
    }
    with open("data/screener.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote data/screener.json")


if __name__ == "__main__":
    main()
