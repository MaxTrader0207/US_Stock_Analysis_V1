#!/usr/bin/env python3
"""
抓取股票日線／週線資料，計算技術指標並輸出 data/screener.json。
用法：python scripts/fetch_screener.py
需求：pip install yfinance pandas

選股母體：scripts/tickers.py 裡的 SCREENER_UNIVERSE
（道瓊工業平均 + S&P 500精簡清單 + 那斯達克100核心清單 + 費城半導體指數，去重合併）

七組選股條件：

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

【多頭股B】
  1. 日線 30MA 黃金交叉 100MA（近5個交易日內發生交叉，且目前 30MA > 100MA）
  2. 100MA 呈上揚
  3. RSI 指標（參數6） > 30

【拉回轉強】
  1. 日線收盤價黃金交叉 60MA（近5個交易日內發生交叉，且目前收盤價 > 60MA）
  2. 60MA 呈上揚
  3. RSI 指標（參數6） > 30

【突破區間】
  1. 近20個交易日（不含今日）最高價 < 最低價 × 1.15（區間窄幅盤整）
  2. 今日開盤跳空開高（開盤價 > 昨日最高價）
  3. 今日收紅K（收盤價 > 開盤價）

【轉機股】
  1. 近3日內，日線收盤價黃金交叉布林通道(Bollinger Band)下緣（20日、2倍標準差）
  2. 布林通道下緣呈上揚

【低檔轉折股】
  1. 前日日線最低價，創近20個交易日新低
  2. 前日日線收紅K（前日收盤價 > 前日開盤價）
  3. 昨日日線收盤價 > 前日日線收盤價

「黃金交叉」判定為近 N 個交易日內曾經處於「不高於」狀態、且最新一天已經轉為「高於」，
用意是抓「剛翻多不久」的標的，而不是只抓「交叉當天」（否則每天符合的標的會很少）。
N 可透過 CROSS_LOOKBACK 調整。

RSI 採用 Wilder's 平滑法（三竹股市、XQ全球贏家等台灣主流看盤軟體的標準算法），
細節見 rsi() 函式內註解。

效能設計：每檔股票的歷史資料只抓一次（1年日線），7組條件共用同一份資料再各自判斷，
不會每組條件都重新打一次 API——選股母體變大之後這點特別重要，避免 API 呼叫量倍增。

每筆選股結果除了代號、公司名、價格、漲跌幅、badges 之外，還會附上：
  - ma10 / ma30：10日、30日均線
  - bias30：目前收盤價與30日均線的乖離率（%）
  - comment：呼叫 Gemini API 產生的一句不超過20字繁體中文短評

Gemini 短評需求：
  - 環境變數 GEMINI_API_KEY（GitHub Actions 請設成 repo secret）
  - 沒有設定的話，comment 欄位一律是 null，選股邏輯本身完全不受影響
  - 同一檔股票如果同時符合好幾組條件，只會呼叫一次 Gemini，結果套用到所有出現的卡片，
    避免同一檔股票重複打 API 浪費額度
  - 細節見 scripts/gemini.py

前端 screener.html / screener.js 是資料驅動的，之後如果要再新增第8組選股條件，
只要在 evaluate_all_conditions() 裡比照既有寫法新增一段判斷、在 main() 的
condition_meta 裡加一筆設定即可，不需要修改前端。
"""
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from tickers import SCREENER_UNIVERSE
from gemini import get_short_comment

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


def safe_round(v, digits=2):
    return round(float(v), digits) if v is not None and not pd.isna(v) else None


def base_result(symbol, name, hist):
    close, high, low = hist["Close"], hist["High"], hist["Low"]
    price = float(close.iloc[-1])

    ma10 = safe_round(close.rolling(10).mean().iloc[-1])
    ma30 = safe_round(close.rolling(30).mean().iloc[-1])
    ma60 = safe_round(close.rolling(60).mean().iloc[-1])
    ma100 = safe_round(close.rolling(100).mean().iloc[-1])
    bias30 = round((price - ma30) / ma30 * 100, 2) if ma30 else None

    # 52週高低：用最近1年的日High/Low（不是收盤價），資料不足52週時就用實際能抓到的天數
    window = min(len(high), 252)
    high52w = safe_round(high.iloc[-window:].max()) if window > 0 else None
    low52w = safe_round(low.iloc[-window:].min()) if window > 0 else None

    rsi6 = safe_round(rsi(close, 6).iloc[-1])

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "changePercent": round(float(pct_change(close)), 2),
        "ma10": ma10,
        "ma30": ma30,
        "ma60": ma60,
        "ma100": ma100,
        "bias30": bias30,
        "high52w": high52w,
        "low52w": low52w,
        "rsi6": rsi6,
    }


# ---------- 對同一份 hist 資料，依序判斷 5 組條件 ----------

def check_strength_a(close):
    if len(close) < 60:
        return None
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

    if above_ma30 and ma30_rising and macd_daily_positive and macd_weekly_red:
        return ["站上30MA", "30MA上揚", "日MACD>0", "週MACD紅柱"]
    return None


def check_bullish_a(close, volume):
    if len(close) < 40:
        return None
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

    if golden_cross and ma30_rising and rsi_strong and volume_up:
        return ["10MA黃金交叉30MA", "30MA上揚", "RSI6>60", "量增"]
    return None


def check_bullish_b(close):
    if len(close) < 110:
        return None
    ma30 = close.rolling(30).mean()
    ma100 = close.rolling(100).mean()
    if pd.isna(ma100.iloc[-6]):
        return None

    golden_cross = crossed_above(ma30, ma100)
    ma100_rising = ma100.iloc[-1] > ma100.iloc[-6]

    r = rsi(close, 6)
    if pd.isna(r.iloc[-1]):
        return None
    rsi_ok = r.iloc[-1] > 30

    if golden_cross and ma100_rising and rsi_ok:
        return ["30MA黃金交叉100MA", "100MA上揚", "RSI6>30"]
    return None


def check_pullback_strength(close):
    if len(close) < 70:
        return None
    ma60 = close.rolling(60).mean()
    if pd.isna(ma60.iloc[-6]):
        return None

    golden_cross = crossed_above(close, ma60)
    ma60_rising = ma60.iloc[-1] > ma60.iloc[-6]

    r = rsi(close, 6)
    if pd.isna(r.iloc[-1]):
        return None
    rsi_ok = r.iloc[-1] > 30

    if golden_cross and ma60_rising and rsi_ok:
        return ["收盤黃金交叉60MA", "60MA上揚", "RSI6>30"]
    return None


def check_breakout_range(o, h, l, c):
    if len(c) < 25:
        return None
    window_high = h.iloc[-21:-1]
    window_low = l.iloc[-21:-1]
    if len(window_high) < 20:
        return None
    range_high = window_high.max()
    range_low = window_low.min()
    if pd.isna(range_high) or pd.isna(range_low) or range_low <= 0:
        return None
    tight_range = range_high < range_low * 1.15

    today_open = o.iloc[-1]
    today_close = c.iloc[-1]
    prev_high = h.iloc[-2]
    gap_up = today_open > prev_high
    red_candle = today_close > today_open

    if tight_range and gap_up and red_candle:
        return ["20日區間<15%", "跳空開高", "收紅K"]
    return None


def check_turnaround(close):
    """轉機股：近3日內，日線收盤價黃金交叉布林通道下緣，且下緣上揚。"""
    if len(close) < 30:
        return None
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    lower_band = ma20 - 2 * std20
    if pd.isna(lower_band.iloc[-1]) or pd.isna(lower_band.iloc[-6]):
        return None

    golden_cross = crossed_above(close, lower_band, lookback=3)
    band_rising = lower_band.iloc[-1] > lower_band.iloc[-6]

    if golden_cross and band_rising:
        return ["近3日黃金交叉BB下緣", "BB下緣上揚"]
    return None


def check_bottom_reversal(o, h, l, c, lookback=20):
    """低檔轉折股：前日最低價創近期新低、前日收紅K、昨日收盤價>前日收盤價。
    刻意不使用「今日」的資料——今日盤中還沒收盤，這組訊號完全以已經走完的
    前日、昨日兩根K棒來判斷，避免用到還在跳動、尚未定案的當日數字。"""
    if len(c) < lookback + 2:
        return None
    window_low = l.iloc[-(lookback + 2):-2]  # 近 lookback 個交易日，以「前日」為最後一天
    if len(window_low) < lookback:
        return None

    day_before_yesterday_low = l.iloc[-3]
    is_recent_low = day_before_yesterday_low <= window_low.min()

    day_before_yesterday_red = c.iloc[-3] > o.iloc[-3]
    yesterday_up = c.iloc[-2] > c.iloc[-3]

    if is_recent_low and day_before_yesterday_red and yesterday_up:
        return [f"前日創近{lookback}日新低", "前日收紅K", "昨日收盤>前日收盤"]
    return None


CONDITION_CHECKS = {
    "strength-a": lambda hist: check_strength_a(hist["Close"]),
    "bullish-a": lambda hist: check_bullish_a(hist["Close"], hist["Volume"]),
    "bullish-b": lambda hist: check_bullish_b(hist["Close"]),
    "pullback-strength": lambda hist: check_pullback_strength(hist["Close"]),
    "breakout-range": lambda hist: check_breakout_range(hist["Open"], hist["High"], hist["Low"], hist["Close"]),
    "turnaround": lambda hist: check_turnaround(hist["Close"]),
    "bottom-reversal": lambda hist: check_bottom_reversal(hist["Open"], hist["High"], hist["Low"], hist["Close"]),
}

CONDITION_META = {
    "strength-a": {
        "name": "強勢股A",
        "description": "日線收盤價 > 日線30MA，且30MA上揚；日線MACD在0軸之上；週線MACD柱狀體翻紅（多頭動能）。",
    },
    "bullish-a": {
        "name": "多頭股A",
        "description": "日線10MA近期黃金交叉30MA，且30MA上揚；RSI指標（參數6）>60；今日成交量>昨日成交量。",
    },
    "bullish-b": {
        "name": "多頭股B",
        "description": "日線30MA近期黃金交叉100MA，且100MA上揚；RSI指標（參數6）>30。",
    },
    "pullback-strength": {
        "name": "拉回轉強",
        "description": "日線收盤價近期黃金交叉60MA，且60MA上揚；RSI指標（參數6）>30。",
    },
    "breakout-range": {
        "name": "突破區間",
        "description": "近20個交易日（不含今日）最高價 < 最低價 × 1.15，屬窄幅盤整；今日開盤跳空開高（開盤 > 昨日最高）且收紅K（收盤 > 開盤），視為區間突破確認。",
    },
    "turnaround": {
        "name": "轉機股",
        "description": "近3日內，日線收盤價黃金交叉布林通道(20日,2倍標準差)下緣，且下緣呈上揚，視為由弱轉強的轉機訊號。",
    },
    "bottom-reversal": {
        "name": "低檔轉折股",
        "description": "前日最低價創近20個交易日新低；前日收紅K；昨日收盤價>前日收盤價，視為低檔止跌轉折訊號（不使用當日尚未收盤的數字）。",
    },
}

UNIVERSE_NOTE = "母體：道瓊工業平均(30檔) + S&P 500依權重前71檔 + 那斯達克100完整清單(101檔) + 費城半導體指數SOX(30檔)，去重合併共159檔。"


def main():
    results_by_condition = {cid: [] for cid in CONDITION_CHECKS}

    for symbol, name in SCREENER_UNIVERSE.items():
        try:
            hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
            if hist.empty:
                print(f"[warn] {symbol}: no history data", file=sys.stderr)
                continue
            close = hist["Close"]

            for cid, check_fn in CONDITION_CHECKS.items():
                try:
                    badges = check_fn(hist)
                except Exception as e:
                    print(f"[warn] {symbol} [{cid}]: {e}", file=sys.stderr)
                    continue
                if badges:
                    entry = base_result(symbol, name, hist)
                    entry["badges"] = badges
                    results_by_condition[cid].append(entry)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)

    # ---- Gemini 短評：同一檔股票可能出現在好幾組條件裡，只呼叫一次 Gemini，
    #      結果套用到該股票在所有條件組裡的卡片，避免重複呼叫浪費額度 ----
    comment_cache = {}
    for cid, results in results_by_condition.items():
        for entry in results:
            symbol = entry["symbol"]
            if symbol not in comment_cache:
                comment_cache[symbol] = get_short_comment(
                    symbol=symbol,
                    name=entry["name"],
                    price=entry["price"],
                    change_pct=entry["changePercent"],
                    ma10=entry["ma10"],
                    ma30=entry["ma30"],
                    ma60=entry["ma60"],
                    ma100=entry["ma100"],
                    bias30=entry["bias30"],
                    high52w=entry["high52w"],
                    low52w=entry["low52w"],
                    rsi6=entry["rsi6"],
                    badges=entry["badges"],
                )
            entry["comment"] = comment_cache[symbol]

    condition_sets = []
    for cid, meta in CONDITION_META.items():
        results = sorted(results_by_condition[cid], key=lambda r: r["changePercent"], reverse=True)
        condition_sets.append({
            "id": cid,
            "name": meta["name"],
            "description": meta["description"] + UNIVERSE_NOTE,
            "status": "active",
            "results": results,
        })

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "conditionSets": condition_sets,
    }
    with open("data/screener.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote data/screener.json")


if __name__ == "__main__":
    main()
