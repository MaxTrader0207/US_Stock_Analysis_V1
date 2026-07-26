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
  - ma30 / ma60 / ma100：30日、60日、100日均線
  - bias30：目前收盤價與30日均線的乖離率（%）
  - above30 / ma30Rising、above60 / ma60Rising、above100 / ma100Rising：
    是否站上對應均線、該均線是否上揚（布林值，前端據此畫上下箭頭）
  - support / resistance / stopLoss：近20個交易日高低點與停損參考價（目前卡片未顯示，保留供其他用途）
  - eps / roe / pe / dividendYield：EPS(TTM)、ROE(%)、本益比(TTM)、股息殖利率(%)
  - revenueLatestQ / grossMarginLatestQ：近一季總營收（原始數字）、近一季毛利率(%)
  - fundamentalComment / fundamentalScore：基本面短評（<=50字，語意完整）與基本面健檢分數(0-50)
  - technicalComment / technicalScore：技術面短評（<=50字）與技術面健檢分數(0-50)
  - overallComment：綜合基本面+技術面的短評（<=50字）
  - totalScore：fundamentalScore + technicalScore，範圍 1-100

  ⚠️ badges 欄位仍保留在資料裡（給 Gemini 短評當作context用），但前端卡片
  已不再顯示選股條件文字標籤。

Gemini 健檢分析需求：
  - 環境變數 GEMINI_API_KEY（GitHub Actions 請設成 repo secret）
  - 沒有設定的話，fundamentalComment/technicalComment/overallComment/各分數欄位一律是 null，
    選股邏輯本身完全不受影響
  - 同一檔股票如果同時符合好幾組條件，只會呼叫一次 Gemini，結果套用到所有出現的卡片，
    避免同一檔股票重複打 API 浪費額度
  - 每次呼叫之間固定間隔 GEMINI_CALL_DELAY_SECONDS 秒（預設1.5秒），拉開請求密度避免撞到限流
  - 單次呼叫遇到限流(429)或伺服器暫時性錯誤(5xx)會自動退避重試，細節見 scripts/gemini.py
  - 三段短評各上限50字，且要求講到一個完整語意的段落結束，不會硬切在句子中間
  - 基本面分數(0-50)+技術面分數(0-50)=總分(1-100)，總分由 Python 端加總計算（不信任模型自己加總），
    確保數字一定一致
  - 為了節省 Gemini 額度，只對每組條件「依當日漲跌幅排序後」的前 GEMINI_ANALYSIS_TOP_N 名
    （預設10，可用環境變數調整）呼叫 Gemini；其餘符合條件的股票卡片一樣會顯示完整量化資料
    （EPS/ROE/均線等），只是健檢分數與三段短評會是 null（前端會顯示「—」跟不出現短評文字）

前端 screener.html / screener.js 是資料驅動的，之後如果要再新增第8組選股條件，
只要在 evaluate_all_conditions() 裡比照既有寫法新增一段判斷、在 main() 的
condition_meta 裡加一筆設定即可，不需要修改前端。
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from tickers import SCREENER_UNIVERSE
from gemini import get_stock_health_check

CROSS_LOOKBACK = 5  # 判定「近期黃金交叉」回看的交易日數

# 支撐/壓力/停損計算參數
SR_LOOKBACK_DAYS = 20      # 支撐、壓力採近N個交易日（不含今日）高低點
STOP_LOSS_BUFFER_PCT = 0.03  # 停損價 = 支撐價再往下這個比例，避免一碰支撐就停損，等真正跌破才觸發

# 每次呼叫 Gemini 之間固定間隔的秒數，從源頭拉開請求密度、降低撞到免費額度
# 每分鐘請求數上限（RPM）的機率。可用環境變數覆寫，預設 1.5 秒。
GEMINI_CALL_DELAY_SECONDS = float(os.environ.get("GEMINI_CALL_DELAY_SECONDS") or 1.5)

# EPS / 近一季營收 / 近一季毛利率：每個「有符合任一選股條件」的股票額外多打
# 2 次 Yahoo Finance 請求（info + 季報財報），跟 fetch_fundamentals.py 面對的是同一個
# 限流風險，所以這裡也做了同樣的間隔設計，只是只對「有中選」的子集抓，不是對全部159檔抓。
FUNDAMENTALS_CALL_DELAY_SECONDS = float(os.environ.get("FUNDAMENTALS_CALL_DELAY_SECONDS") or 1.0)

# Gemini 健檢分析的呼叫次數是主要的額度消耗來源（每次都是「基本面+技術面+綜合」三段短評
# 加兩個分數，prompt/回應都不小）。與其對每組條件符合的所有股票都打一次，這裡改成只對
# 每組條件「依當日漲跌幅排序後」的前 N 名做健檢分析，其餘股票卡片一樣會顯示（EPS/ROE/
# 均線等量化資料照樣完整），只是 C 區塊健檢分數跟 A/B 區塊的短評會是「尚無資料」。
# 同一檔股票只要在任一組條件裡進了前 N 名，就會做分析（其他條件組出現時直接沿用結果，不重打）。
# 想全部都分析的話，把這個環境變數設一個很大的數字（例如 999）即可。
GEMINI_ANALYSIS_TOP_N = int(os.environ.get("GEMINI_ANALYSIS_TOP_N") or 10)

# 不同版本 yfinance 回傳的財報列名偶爾會不一致，兩種都嘗試
REVENUE_ROW_NAMES = ["Total Revenue", "TotalRevenue"]
GROSS_PROFIT_ROW_NAMES = ["Gross Profit", "GrossProfit"]


def _find_row(df, names):
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def fetch_fundamentals_light(symbol):
    """抓 EPS(TTM)、ROE、本益比(TTM)、股息殖利率、近一季營收、近一季毛利率。
    EPS/ROE/PE/殖利率都來自同一個 info 請求（不額外增加網路呼叫），
    營收/毛利率是另一個獨立請求。兩組請求各自 try/except 包起來，
    任一步驟失敗只會讓對應欄位變 None，不會讓其他欄位或整體抓取跟著失敗。"""
    eps = roe = pe = dividend_yield = revenue = gross_margin = None
    ticker_obj = yf.Ticker(symbol)

    try:
        info = ticker_obj.get_info()
        eps = info.get("trailingEps")
        pe = info.get("trailingPE")

        roe_raw = info.get("returnOnEquity")
        if roe_raw is not None:
            roe = round(float(roe_raw) * 100, 2)

        dy_raw = info.get("dividendYield")
        if dy_raw is not None:
            dy_raw = float(dy_raw)
            # 這個 repo 目前用的 yfinance 版本，dividendYield 回傳的就已經是百分比數字本身
            # （例如 0.36 代表 0.36%），不是比例（不需要再 ×100）。
            # 之前誤判成比例、多乘了一次 100，導致殖利率顯示成 36% 這種不合理的數字。
            dividend_yield = round(dy_raw, 2)
            if dividend_yield > 50:
                # 正常股票殖利率幾乎不可能超過50%，這種情況通常代表yfinance那個版本
                # 又把單位改回比例了，印警告方便之後排查，但不自動幫你猜怎麼換算
                print(f"[warn] {symbol}: 殖利率數值異常({dividend_yield}%)，yfinance回傳格式可能又變了，請人工確認", file=sys.stderr)
    except Exception as e:
        print(f"[warn] {symbol}: EPS/ROE/PE/殖利率取得失敗 {e}", file=sys.stderr)

    try:
        qis = ticker_obj.quarterly_income_stmt
        if qis is not None and not qis.empty:
            latest_col = qis.columns[0]
            rev_row = _find_row(qis, REVENUE_ROW_NAMES)
            gp_row = _find_row(qis, GROSS_PROFIT_ROW_NAMES)
            revenue_val = rev_row.get(latest_col) if rev_row is not None else None
            if revenue_val is not None and not pd.isna(revenue_val):
                revenue = float(revenue_val)
            if gp_row is not None and revenue:
                gp_val = gp_row.get(latest_col)
                if gp_val is not None and not pd.isna(gp_val):
                    gross_margin = round(float(gp_val) / revenue * 100, 2)
    except Exception as e:
        print(f"[warn] {symbol}: 近一季營收/毛利率取得失敗 {e}", file=sys.stderr)

    return {
        "eps": eps,
        "roe": roe,
        "pe": pe,
        "dividendYield": dividend_yield,
        "revenue": revenue,
        "grossMargin": gross_margin,
    }


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


def _ma_status(price, series):
    """回傳 (是否站上這條均線, 均線是否上揚)；資料不足時回傳 (None, None)。
    上揚/下彎判斷方式跟 check_strength_a 等選股邏輯一致：比較 CROSS_LOOKBACK 個交易日前。"""
    if len(series) < CROSS_LOOKBACK + 1:
        return None, None
    latest = series.iloc[-1]
    prev = series.iloc[-1 - CROSS_LOOKBACK]
    if pd.isna(latest) or pd.isna(prev):
        return None, None
    return bool(price > latest), bool(latest > prev)


def base_result(symbol, name, hist):
    close = hist["Close"]
    price = float(close.iloc[-1])

    ma30_series = close.rolling(30).mean()
    ma60_series = close.rolling(60).mean()
    ma100_series = close.rolling(100).mean()

    ma30 = safe_round(ma30_series.iloc[-1])
    ma60 = safe_round(ma60_series.iloc[-1])
    ma100 = safe_round(ma100_series.iloc[-1])
    bias30 = round((price - ma30) / ma30 * 100, 2) if ma30 else None

    above30, ma30_rising = _ma_status(price, ma30_series)
    above60, ma60_rising = _ma_status(price, ma60_series)
    above100, ma100_rising = _ma_status(price, ma100_series)

    # 支撐/壓力：近 SR_LOOKBACK_DAYS 個交易日（不含今日）的最低/最高價
    # 停損：支撐價再往下 STOP_LOSS_BUFFER_PCT，等真正跌破支撐才觸發，而非一碰到支撐就停損
    support = resistance = stop_loss = None
    high, low = hist["High"], hist["Low"]
    if len(high) >= SR_LOOKBACK_DAYS + 1:
        window_high = high.iloc[-(SR_LOOKBACK_DAYS + 1):-1]
        window_low = low.iloc[-(SR_LOOKBACK_DAYS + 1):-1]
        resistance = safe_round(window_high.max())
        support = safe_round(window_low.min())
        if support:
            stop_loss = safe_round(support * (1 - STOP_LOSS_BUFFER_PCT))

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "changePercent": round(float(pct_change(close)), 2),
        "ma30": ma30,
        "ma60": ma60,
        "ma100": ma100,
        "bias30": bias30,
        "above30": above30,
        "ma30Rising": ma30_rising,
        "above60": above60,
        "ma60Rising": ma60_rising,
        "above100": above100,
        "ma100Rising": ma100_rising,
        "support": support,
        "resistance": resistance,
        "stopLoss": stop_loss,
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
    processed_count = 0
    empty_history_count = 0

    for symbol, name in SCREENER_UNIVERSE.items():
        try:
            hist = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
            if hist.empty:
                empty_history_count += 1
                print(f"[warn] {symbol}: no history data", file=sys.stderr)
                continue
            processed_count += 1
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

    # 每組條件各自符合幾檔、加總去重後總共幾檔股票，寫在 Gemini 那行摘要之前。
    # 之後如果又遇到「Gemini 健檢分析：0/0」，先看這裡：如果這裡也是全部0檔，
    # 代表問題出在選股條件比對這一步（或當天市場本來就沒有標的符合任何條件），
    # 不是 Gemini 呼叫失敗；如果這裡有數字但 Gemini 那行是0，才是 Gemini 端的問題。
    per_condition_counts = ", ".join(f"{cid}={len(results)}" for cid, results in results_by_condition.items())
    matched_symbols = {entry["symbol"] for results in results_by_condition.values() for entry in results}
    print(
        f"[info] 選股條件比對完成：母體 {len(SCREENER_UNIVERSE)} 檔，"
        f"成功取得歷史資料 {processed_count} 檔（無資料 {empty_history_count} 檔），"
        f"至少符合一組條件 {len(matched_symbols)} 檔（{per_condition_counts}）",
        file=sys.stderr,
    )

    # 依當日漲跌幅排序（跟前端卡片排序一致），才能正確取出「前N名」。
    # 這裡排序好之後，後面就不用再排一次，最終輸出也直接用這個順序。
    for cid in results_by_condition:
        results_by_condition[cid].sort(key=lambda r: r["changePercent"], reverse=True)

    # 每組條件前 GEMINI_ANALYSIS_TOP_N 名的股票代號聯集，只有這些才會呼叫 Gemini 健檢分析
    gemini_target_symbols = set()
    for cid, results in results_by_condition.items():
        for entry in results[:GEMINI_ANALYSIS_TOP_N]:
            gemini_target_symbols.add(entry["symbol"])
    print(
        f"[info] Gemini 健檢分析目標：每組條件前{GEMINI_ANALYSIS_TOP_N}名，"
        f"去重後共 {len(gemini_target_symbols)} 檔會呼叫 Gemini（其餘 {len(matched_symbols) - len(gemini_target_symbols)} 檔只顯示量化資料，不做AI分析）",
        file=sys.stderr,
    )

    # ---- EPS / ROE / P/E / 殖利率 / 近一季營收 / 近一季毛利率：同一檔股票可能出現在
    #      好幾組條件裡，只抓一次，結果套用到該股票在所有條件組裡的卡片 ----
    fundamentals_cache = {}
    for cid, results in results_by_condition.items():
        for entry in results:
            symbol = entry["symbol"]
            if symbol not in fundamentals_cache:
                fundamentals_cache[symbol] = fetch_fundamentals_light(symbol)
                time.sleep(FUNDAMENTALS_CALL_DELAY_SECONDS)
            f = fundamentals_cache[symbol]
            entry["eps"] = f["eps"]
            entry["roe"] = f["roe"]
            entry["pe"] = f["pe"]
            entry["dividendYield"] = f["dividendYield"]
            entry["revenueLatestQ"] = f["revenue"]
            entry["grossMarginLatestQ"] = f["grossMargin"]

    # ---- 健檢分析（基本面短評+分數／技術面短評+分數／綜合短評）：同一檔股票可能出現在
    #      好幾組條件裡，只呼叫一次 Gemini，結果套用到該股票在所有條件組裡的卡片。
    #      只對 gemini_target_symbols（每組條件前N名）呼叫，其餘直接跳過節省額度 ----
    analysis_cache = {}
    for cid, results in results_by_condition.items():
        for entry in results:
            symbol = entry["symbol"]

            if symbol not in gemini_target_symbols:
                entry["fundamentalComment"] = None
                entry["fundamentalScore"] = None
                entry["technicalComment"] = None
                entry["technicalScore"] = None
                entry["overallComment"] = None
                entry["totalScore"] = None
                continue

            if symbol not in analysis_cache:
                analysis_cache[symbol] = get_stock_health_check(
                    symbol=symbol,
                    name=entry["name"],
                    price=entry["price"],
                    change_pct=entry["changePercent"],
                    eps=entry["eps"],
                    roe=entry["roe"],
                    pe=entry["pe"],
                    dividend_yield=entry["dividendYield"],
                    revenue=entry["revenueLatestQ"],
                    gross_margin=entry["grossMarginLatestQ"],
                    ma30=entry["ma30"], ma60=entry["ma60"], ma100=entry["ma100"],
                    bias30=entry["bias30"],
                    above30=entry["above30"], ma30_rising=entry["ma30Rising"],
                    above60=entry["above60"], ma60_rising=entry["ma60Rising"],
                    above100=entry["above100"], ma100_rising=entry["ma100Rising"],
                    badges=entry["badges"],
                )
                # 只在真的打了一次 API 時才等待，cache 命中（同一檔股票在其他條件組裡重複出現）不用等
                time.sleep(GEMINI_CALL_DELAY_SECONDS)

            analysis = analysis_cache[symbol]
            if analysis:
                entry["fundamentalComment"] = analysis["fundamentalComment"]
                entry["fundamentalScore"] = analysis["fundamentalScore"]
                entry["technicalComment"] = analysis["technicalComment"]
                entry["technicalScore"] = analysis["technicalScore"]
                entry["overallComment"] = analysis["overallComment"]
                entry["totalScore"] = analysis["totalScore"]
            else:
                entry["fundamentalComment"] = None
                entry["fundamentalScore"] = None
                entry["technicalComment"] = None
                entry["technicalScore"] = None
                entry["overallComment"] = None
                entry["totalScore"] = None

    analysis_ok = sum(1 for v in analysis_cache.values() if v)
    analysis_total = len(analysis_cache)
    print(f"[info] Gemini 健檢分析：{analysis_ok}/{analysis_total} 檔成功產生", file=sys.stderr)

    condition_sets = []
    for cid, meta in CONDITION_META.items():
        # results_by_condition[cid] 前面已經依漲跌幅排序過了（決定Gemini前N名時用的就是這個順序），
        # 這裡直接沿用，不用再排一次
        condition_sets.append({
            "id": cid,
            "name": meta["name"],
            "description": meta["description"] + UNIVERSE_NOTE,
            "status": "active",
            "results": results_by_condition[cid],
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
