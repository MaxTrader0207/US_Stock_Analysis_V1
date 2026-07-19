#!/usr/bin/env python3
"""
抓取美股大型權值股日線／週線資料，計算技術指標並輸出 data/screener.json。
用法：python scripts/fetch_screener.py
需求：pip install yfinance pandas

三組選股條件：

【強勢股A】
  1. 日線收盤價 > 日線 30MA
  2. 日線 30MA 呈上揚（近5個交易日 30MA 上升）
  3. 日線 MACD (DIF) 在 0 軸之上
  4. 週線 MACD 柱狀體 (OSC) 翻紅（> 0）

【多頭股A】
  1. 日線 10MA 黃金交叉 30MA（近5個交易日內發生交叉，且目前 10MA > 30MA）
  2. 30MA 呈上揚
  3. RSI 指標（參數6） > 60
  4. 今日成交量 > 昨日成交量

【拉回轉強】
  1. 日線收盤價黃金交叉 60MA（近5個交易日內發生交叉，且目前收盤價 > 60MA）
  2. 60MA 呈上揚
  3. RSI 指標（參數6） > 30

「黃金交叉」判定為近 N 個交易日內曾經處於「不高於」狀態、且最新一天已經轉為「高於」，
用意是抓「剛翻多不久」的標的，而不是只抓「交叉當天」（否則每天符合的標的會很少）。
N 可透過 CROSS_LOOKBACK 調整。

RSI 採用 Wilder's 平滑法（三竹股市、XQ全球贏家等台灣主流看盤軟體的標準算法），
細節見 rsi() 函式內註解。

前端 screener.html / screener.js 是資料驅動的，之後如果要再新增第4組選股條件，
只要在 main() 裡比照 build_condition_2() 新增一個函式、加進 condition_sets 陣列即可，
不需要修改前端。
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

CROSS_LOOKBACK = 5  # 判定「近期黃金交叉」回看的交易日數


def macd(series, fast=12, slow=26, signal=9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    osc = (dif - dea) * 2
    return dif, dea, osc


def rsi(series, period=6):
    """
    RSI 採用 Wilder's 平滑法（三竹股市、XQ全球贏家等台灣主流看盤軟體的標準算法），
    而非單純的簡單移動平均。做法等同 Wilder 原始公式：
    第一根之後的平均漲跌用「前一日平均值 * (N-1) / N + 當日漲跌 / N」遞迴平滑，
    這裡用 pandas 的 ewm(alpha=1/period) 達到相同效果。
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def crossed_above(a, b, lookback=CROSS_LOOKBACK):
    """判斷數列 a 是否「近期黃金交叉」數列 b：目前 a > b，且回看區間內曾經 a <= b。"""
    if len(a) < lookback + 1 or len(b) < lookback + 1:
        return False
    if pd.isna(a.iloc[-1]) or pd.isna(b.iloc[-1]) or a.iloc[-1] <= b.iloc[-1]:
        return False
    window_a = a.iloc[-(lookback + 1):-1]
    window_b = b.iloc[-(lookback + 1):-1]
    return bool((window_a <= window_b).any())


def pct_change(close):
    prev_close = close.iloc[-2] if len(close) > 1 else close.iloc[-1]
    return (close.iloc[-1] - prev_close) / prev_close * 100 if prev_close else 0


# ---------- 選股條件一：強勢股A ----------

def evaluate_strength_a(symbol, name):
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

    return {
        "symbol": symbol,
        "name": name,
        "price": round(float(close.iloc[-1]), 2),
        "changePercent": round(float(pct_change(close)), 2),
        "badges": ["站上30MA", "30MA上揚", "日MACD>0", "週MACD紅柱"],
    }


def build_strength_a():
    results = []
    for symbol, name in US_LARGE_CAP_TICKERS.items():
        try:
            r = evaluate_strength_a(symbol, name)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)
    results.sort(key=lambda r: r["changePercent"], reverse=True)
    return {
        "id": "strength-a",
        "name": "強勢股A",
        "description": "日線收盤價 > 日線30MA，且30MA上揚；日線MACD在0軸之上；週線MACD柱狀體翻紅（多頭動能）。母體：美股大型權值股。",
        "status": "active",
        "results": results,
    }


# ---------- 選股條件二：多頭股A ----------

def evaluate_bullish_a(symbol, name):
    hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty or len(hist) < 40:
        return None
    close = hist["Close"]
    volume = hist["Volume"]

    ma10 = close.rolling(10).mean()
    ma30 = close.rolling(30).mean()
    if pd.isna(ma30.iloc[-6]):
        return None

    golden_cross = crossed_above(ma10, ma30)
    ma30_rising = ma30.iloc[-1] > ma30.iloc[-6]

    r = rsi(close, 6)
    if pd.isna(r.iloc[-1]):
        return None
    rsi_strong = r.iloc[-1] > 60

    volume_up = len(volume) > 1 and volume.iloc[-1] > volume.iloc[-2]

    if not (golden_cross and ma30_rising and rsi_strong and volume_up):
        return None

    return {
        "symbol": symbol,
        "name": name,
        "price": round(float(close.iloc[-1]), 2),
        "changePercent": round(float(pct_change(close)), 2),
        "badges": ["10MA黃金交叉30MA", "30MA上揚", "RSI6>60", "量增"],
    }


def build_bullish_a():
    results = []
    for symbol, name in US_LARGE_CAP_TICKERS.items():
        try:
            r = evaluate_bullish_a(symbol, name)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)
    results.sort(key=lambda r: r["changePercent"], reverse=True)
    return {
        "id": "bullish-a",
        "name": "多頭股A",
        "description": "日線10MA近期黃金交叉30MA，且30MA上揚；RSI指標（參數6）>60；今日成交量>昨日成交量。母體：美股大型權值股。",
        "status": "active",
        "results": results,
    }


# ---------- 選股條件三：拉回轉強 ----------

def evaluate_pullback_strength(symbol, name):
    hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty or len(hist) < 70:
        return None
    close = hist["Close"]

    ma60 = close.rolling(60).mean()
    if pd.isna(ma60.iloc[-6]):
        return None

    golden_cross = crossed_above(close, ma60)
    ma60_rising = ma60.iloc[-1] > ma60.iloc[-6]

    r = rsi(close, 6)
    if pd.isna(r.iloc[-1]):
        return None
    rsi_ok = r.iloc[-1] > 30

    if not (golden_cross and ma60_rising and rsi_ok):
        return None

    return {
        "symbol": symbol,
        "name": name,
        "price": round(float(close.iloc[-1]), 2),
        "changePercent": round(float(pct_change(close)), 2),
        "badges": ["收盤黃金交叉60MA", "60MA上揚", "RSI6>30"],
    }


def build_pullback_strength():
    results = []
    for symbol, name in US_LARGE_CAP_TICKERS.items():
        try:
            r = evaluate_pullback_strength(symbol, name)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)
    results.sort(key=lambda r: r["changePercent"], reverse=True)
    return {
        "id": "pullback-strength",
        "name": "拉回轉強",
        "description": "日線收盤價近期黃金交叉60MA，且60MA上揚；RSI指標（參數6）>30。母體：美股大型權值股。",
        "status": "active",
        "results": results,
    }


def main():
    condition_sets = [
        build_strength_a(),
        build_bullish_a(),
        build_pullback_strength(),
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
