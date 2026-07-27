#!/usr/bin/env python3
"""
scripts/common.py
------------------
fetch_screener.py 和 fetch_fundamentals.py 共用的工具函式。

抽出來的原因：殖利率單位換算、均線站上/上揚判斷、「排序→取TOP N→呼叫Gemini→
其餘設None」這整套邏輯，原本兩個檔案各自維護一份幾乎一樣的程式碼，容易改一邊
忘了改另一邊（殖利率那個 bug 就是活生生的例子）。

這個檔案也負責兩件事：
  1. Yahoo Finance 呼叫的重試機制（yf_call_with_retry）
  2. 跨腳本共用的 Gemini 分析快取（load_gemini_cache / save_gemini_cache）——
     同一天內，如果 fetch_screener.py 已經分析過 AAPL，fetch_fundamentals.py
     不會重打一次 Gemini，直接複用同一份分析結果，省下重複的額度消耗。
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from gemini import get_stock_health_check

CROSS_LOOKBACK = 5  # 判定均線上揚/下彎回看的交易日數

GEMINI_CALL_DELAY_SECONDS = float(os.environ.get("GEMINI_CALL_DELAY_SECONDS") or 1.5)

GEMINI_CACHE_PATH = "data/gemini_cache.json"

YAHOO_MAX_RETRIES = int(os.environ.get("YAHOO_MAX_RETRIES") or 3)
YAHOO_BACKOFF_BASE_SECONDS = float(os.environ.get("YAHOO_BACKOFF_BASE_SECONDS") or 3)


# ============================================================
# 基礎小工具
# ============================================================

def safe_round(v, d=2):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return round(float(v), d)


def get_row(df, candidates):
    """從財報 DataFrame 裡找第一個存在的列名，回傳該列。找不到回傳 None。
    yfinance 不同版本對同一個科目的列名不一致，所以用候選清單依序嘗試。"""
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def pct_change(close):
    prev_close = close.iloc[-2] if len(close) > 1 else close.iloc[-1]
    return (close.iloc[-1] - prev_close) / prev_close * 100 if prev_close else 0


def ma_status(price, series):
    """回傳 (是否站上這條均線, 均線是否上揚)；資料不足時回傳 (None, None)。"""
    if series is None or len(series) < CROSS_LOOKBACK + 1:
        return None, None
    latest = series.iloc[-1]
    prev = series.iloc[-1 - CROSS_LOOKBACK]
    if pd.isna(latest) or pd.isna(prev):
        return None, None
    return bool(price > latest), bool(latest > prev)


def extract_fundamentals_from_info(info):
    """從 yfinance 的 info dict 統一抽出 EPS/ROE/PE/殖利率，回傳 (eps, roe, pe, dividend_yield)。
    殖利率單位換算只在這裡處理一次，避免兩個腳本各自寫一份、容易一邊改一邊忘了改。

    ⚠️ 這個 repo 目前用的 yfinance 版本，dividendYield 回傳的就已經是百分比數字本身
    （例如 0.36 代表 0.36%），不是比例，不需要再 ×100。之前誤判成比例多乘了一次100，
    導致殖利率顯示成 36% 這種不合理的數字，這裡是修正後的版本。

    ⚠️ 這裡每個數值都會經過 safe_round()，不是只為了四捨五入──yfinance 對虧損公司這類
    情況，有時候 trailingPE/trailingEps 回傳的是真正的浮點數 NaN（不是 None）。
    Python 的 json.dump() 預設會把 NaN 直接寫成 JSON 裡不合法的 `NaN` 字面值，
    這種「Python讀得回來、瀏覽器JSON.parse()會整份炸掉」的狀況非常隱蔽——Actions log
    會顯示成功、檔案也真的寫出來了，但前端完全解析不了，只會顯示「找不到資料檔」
    這種容易誤導排查方向的訊息。safe_round() 內部有做 pd.isna() 檢查，NaN 一律轉成
    None（也就是合法 JSON 的 null），從源頭避免這個問題。
    """
    eps = safe_round(info.get("trailingEps"))
    pe = safe_round(info.get("trailingPE"))

    roe_raw = info.get("returnOnEquity")
    roe = safe_round(float(roe_raw) * 100) if roe_raw is not None else None

    dy_raw = info.get("dividendYield")
    dividend_yield = None
    if dy_raw is not None:
        dividend_yield = safe_round(float(dy_raw))
        if dividend_yield is not None and dividend_yield > 50:
            # 正常股票殖利率幾乎不可能超過50%，這種情況通常代表yfinance那個版本
            # 又把單位改回比例了，印警告方便之後排查，但不自動幫你猜怎麼換算
            print(f"[warn] 殖利率數值異常({dividend_yield}%)，yfinance回傳格式可能又變了，請人工確認", file=sys.stderr)

    return eps, roe, pe, dividend_yield


# ============================================================
# Yahoo Finance 呼叫重試機制
# ============================================================

def yf_call_with_retry(fn, description, max_retries=None, backoff_base=None):
    """對任何 yfinance 呼叫包一層重試。fn 是一個 no-arg callable（用 lambda 包起來），
    例如 yf_call_with_retry(lambda: yf.Ticker(symbol).history(period="1y"), f"{symbol} 歷史股價")。

    yfinance 底層把 requests 的各種錯誤（逾時、連線中斷、HTTP錯誤）包成不同的例外類型，
    沒辦法像 gemini.py 那樣精準分流 429/5xx，所以這裡對所有例外一律視為可重試，
    用指數退避（預設 3秒→6秒→12秒）重打，重試次數用完就放棄回傳 None，
    呼叫端要自行處理 None 的情況（通常是跳過該檔股票、印warn，不中斷整體流程）。
    """
    max_retries = max_retries or YAHOO_MAX_RETRIES
    backoff_base = backoff_base or YAHOO_BACKOFF_BASE_SECONDS
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as e:
            if attempt < max_retries:
                wait = backoff_base * (2 ** (attempt - 1))
                print(f"[warn] {description}: {e}，{wait:.0f}秒後重試（第{attempt}/{max_retries}次）", file=sys.stderr)
                time.sleep(wait)
            else:
                print(f"[warn] {description}: {e}，已重試{max_retries}次仍失敗，放棄", file=sys.stderr)
    return None


# ============================================================
# 跨腳本共用的 Gemini 分析快取
# ============================================================

def load_gemini_cache():
    """讀取當天的 Gemini 分析快取。用日期當有效性判斷：日期對不上（例如昨天留下來的檔案）
    就視為沒有快取，全部重新分析，避免用到過期的分析內容。
    回傳 (cache_dict, today_str)。"""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if not os.path.exists(GEMINI_CACHE_PATH):
        return {}, today
    try:
        with open(GEMINI_CACHE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if data.get("date") != today:
            print(f"[info] Gemini 快取日期({data.get('date')})不是今天({today})，視為沒有快取", file=sys.stderr)
            return {}, today
        entries = data.get("entries", {})
        print(f"[info] 讀到今天的 Gemini 快取，共 {len(entries)} 檔已分析過", file=sys.stderr)
        return entries, today
    except Exception as e:
        print(f"[warn] 讀取 Gemini 快取失敗，視為沒有快取：{e}", file=sys.stderr)
        return {}, today


def save_gemini_cache(cache, today):
    os.makedirs(os.path.dirname(GEMINI_CACHE_PATH) or ".", exist_ok=True)
    with open(GEMINI_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump({"date": today, "entries": cache}, f, ensure_ascii=False, indent=2, allow_nan=False)
    print(f"[info] 已寫入 Gemini 快取，共 {len(cache)} 檔", file=sys.stderr)


# ============================================================
# 「排序 → 取TOP N聯集 → 呼叫Gemini(含快取) → 其餘設None」共用流程
# ============================================================

def _clear_analysis_fields(entry):
    entry["fundamentalComment"] = None
    entry["fundamentalScore"] = None
    entry["technicalComment"] = None
    entry["technicalScore"] = None
    entry["overallComment"] = None
    entry["totalScore"] = None


def run_gemini_health_check_pass(grouped_results, top_n, cache):
    """grouped_results 是 {分組id: [entry, ...]}，每個 entry 至少要有以下欄位：
    symbol/name/price/changePercent/eps/roe/pe/dividendYield/revenueLatestQ/
    grossMarginLatestQ/ma30/ma60/ma100/bias30/above30/ma30Rising/above60/ma60Rising/
    above100/ma100Rising/badges

    流程：
      1. 每組依 changePercent 排序（由高到低）
      2. 取每組前 top_n 名的股票代號聯集，只有這些會被分析
      3. 依序處理，優先查 cache（可能是這次執行內已經分析過、也可能是另一個腳本
         今天稍早已經寫入磁碟的結果），cache 沒有才真的呼叫 Gemini
      4. 不在前 top_n 名的股票，健檢分析欄位一律設 None（前端會顯示「—」）

    回傳 (target_symbols, new_calls)：這次分析的目標股票集合、實際新呼叫 Gemini 的次數
    （用來跟 cache 命中次數對照，方便看快取省了多少次呼叫）。
    """
    for key in grouped_results:
        grouped_results[key].sort(key=lambda r: r["changePercent"], reverse=True)

    target_symbols = set()
    for key, entries in grouped_results.items():
        for entry in entries[:top_n]:
            target_symbols.add(entry["symbol"])

    new_calls = 0
    cache_hits = 0
    for key, entries in grouped_results.items():
        for entry in entries:
            symbol = entry["symbol"]

            if symbol not in target_symbols:
                _clear_analysis_fields(entry)
                continue

            if symbol in cache:
                cache_hits += 1
            else:
                cache[symbol] = get_stock_health_check(
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
                new_calls += 1
                time.sleep(GEMINI_CALL_DELAY_SECONDS)

            analysis = cache[symbol]
            if analysis:
                entry["fundamentalComment"] = analysis["fundamentalComment"]
                entry["fundamentalScore"] = analysis["fundamentalScore"]
                entry["technicalComment"] = analysis["technicalComment"]
                entry["technicalScore"] = analysis["technicalScore"]
                entry["overallComment"] = analysis["overallComment"]
                entry["totalScore"] = analysis["totalScore"]
            else:
                _clear_analysis_fields(entry)

    print(
        f"[info] Gemini 健檢分析：目標 {len(target_symbols)} 檔，"
        f"快取命中 {cache_hits} 檔，實際新呼叫 {new_calls} 次，"
        f"成功 {sum(1 for s in target_symbols if cache.get(s))} 檔",
        file=sys.stderr,
    )
    return target_symbols, new_calls
