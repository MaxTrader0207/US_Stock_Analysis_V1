#!/usr/bin/env python3
"""
呼叫 Gemini API，針對選股結果裡的個股產生「健檢分析」：
  - 基本面短評（<=50字，語意完整）+ 基本面健檢分數(0-50)
  - 技術面短評（<=50字，語意完整）+ 技術面健檢分數(0-50)
  - 綜合短評（<=50字，語意完整）
給 fetch_screener.py 使用（也可以給之後其他腳本共用）。

需求：
  - pip install requests
  - 環境變數 GEMINI_API_KEY：你自己的 Gemini API Key（去 Google AI Studio 免費申請）
  - 環境變數 GEMINI_MODEL（可選）：預設用 gemini-3.1-flash-lite
    （Google 的模型名稱／別名會定期汰換，如果之後這個模型名稱過期回傳 404，
    去 https://ai.google.dev/gemini-api/docs/models 查目前建議用的輕量模型名稱替換即可）

⚠️ 沒有設定 GEMINI_API_KEY 時，get_stock_health_check() 一律回傳 None，
不會讓整個抓取流程失敗——健檢分析只是錦上添花的附加資訊，不是選股邏輯的一部分。

呼叫遇到 429（限流）或 5xx（伺服器暫時性錯誤）會自動退避重試（預設最多3次，
間隔 5s → 10s → 20s，或優先採用 Google 回傳的 Retry-After 秒數）；
其餘錯誤（Key 無效、模型名稱過期、回應不是合法JSON等重試也沒用的狀況）會直接放棄並印警告，
同樣不會中斷抓取。可透過環境變數 GEMINI_MAX_RETRIES / GEMINI_BACKOFF_BASE_SECONDS 調整。

分數設計：
  - 基本面分數(fundamentalScore) 0-50、技術面分數(technicalScore) 0-50，
    總分(totalScore) = 兩者相加，範圍 1-100，由這支程式加總計算（不信任模型自己算的總分），
    確保數字一定一致，不會有模型算錯的風險。
"""
import json
import os
import sys
import time

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
MAX_COMMENT_CHARS = 50

# 允許稍微超出上限的緩衝：模型偶爾會多寫幾個字才收尾，只要落在這個範圍內就不裁切，
# 保留完整語意；真的超出太多才觸發下面的「找標點裁切」保底機制。
COMMENT_SOFT_OVERFLOW = 15

# 判斷「語意完整結束點」用的標點（句號、驚嘆號、問號視為完整句子；逗號、頓號次之）
SENTENCE_END_PUNCT = "。！？"
CLAUSE_END_PUNCT = "，、"

# 重試設定：只針對「可能重試就會成功」的錯誤重打，429(限流)/5xx(伺服器暫時性錯誤)/連線逾時都算，
# 400(格式錯誤)/403(Key無效)這種重試也沒用的錯誤不會重試，直接放棄避免浪費時間。
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES") or 3)
GEMINI_BACKOFF_BASE_SECONDS = float(os.environ.get("GEMINI_BACKOFF_BASE_SECONDS") or 5)

# 開機時就印一行明確的狀態訊息（不會洩漏完整 Key），
# 之後排查「健檢分析到底有沒有跑」時，Actions log 一眼就能看到，不用再靠猜的。
if GEMINI_API_KEY:
    _masked = GEMINI_API_KEY[:4] + "..." + GEMINI_API_KEY[-4:] if len(GEMINI_API_KEY) > 8 else "***"
    print(f"[info] GEMINI_API_KEY 已偵測到（{_masked}），model={GEMINI_MODEL}，將呼叫 Gemini 產生健檢分析", file=sys.stderr)
else:
    print("[info] 未偵測到 GEMINI_API_KEY 環境變數，本次不會呼叫 Gemini，健檢分析相關欄位全部會是 null", file=sys.stderr)


def _finish_at_natural_end(text, limit):
    """把文字收在一個語意完整的地方，而不是硬切在字中間。
    規則：
      1. 在 limit 之內（含 COMMENT_SOFT_OVERFLOW 緩衝）就完整保留，不裁切
      2. 超出太多的話，往回找最後一個句號/驚嘆號/問號，從那裡結束（保留標點）
      3. 找不到完整句子標點，退而找逗號/頓號，從那裡結束
      4. 都找不到，才硬裁到 limit 並加上「…」表示這是被截斷的
    """
    if not text:
        return text
    if len(text) <= limit + COMMENT_SOFT_OVERFLOW:
        return text

    window = text[: limit + COMMENT_SOFT_OVERFLOW]

    last_sentence_end = max((window.rfind(p) for p in SENTENCE_END_PUNCT), default=-1)
    if last_sentence_end >= int(limit * 0.4):
        return window[: last_sentence_end + 1]

    last_clause_end = max((window.rfind(p) for p in CLAUSE_END_PUNCT), default=-1)
    if last_clause_end >= int(limit * 0.4):
        return window[: last_clause_end + 1]

    return text[:limit].rstrip("，、") + "…"


def _clamp_score(v, lo=0, hi=50, default=None):
    """把模型給的分數壓進合理範圍，模型偶爾會給超出範圍或非數字的值，這裡做保底防呆。"""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return int(round(min(max(v, lo), hi)))


def _call_gemini_with_retry(prompt, symbol):
    """打 Gemini API，內建限流/暫時性錯誤重試。成功回傳模型輸出的原始文字，失敗回傳 None。"""
    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                GEMINI_ENDPOINT,
                params={"key": GEMINI_API_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=20,
            )
        except requests.exceptions.RequestException as e:
            # 連線層級的錯誤（逾時、DNS、連線中斷等）一律視為可重試
            if attempt < GEMINI_MAX_RETRIES:
                wait = GEMINI_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(f"[warn] Gemini health-check for {symbol}: 連線錯誤 {e}，{wait:.0f}秒後重試（第{attempt}/{GEMINI_MAX_RETRIES}次）", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[warn] Gemini health-check for {symbol}: 連線錯誤 {e}，已重試{GEMINI_MAX_RETRIES}次仍失敗，放棄", file=sys.stderr)
            return None

        if resp.ok:
            try:
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as e:
                print(f"[warn] Gemini health-check for {symbol}: 回應格式異常 {e} - {resp.text[:300]}", file=sys.stderr)
                return None

        # HTTP 429（限流）與 5xx（伺服器暫時性錯誤）視為可重試；其餘（400/403等）直接放棄
        retryable = resp.status_code == 429 or resp.status_code >= 500
        err_detail = f"HTTP {resp.status_code} - {resp.text[:300]}"

        if retryable and attempt < GEMINI_MAX_RETRIES:
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else GEMINI_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"[warn] Gemini health-check for {symbol}: {err_detail}，{wait:.0f}秒後重試（第{attempt}/{GEMINI_MAX_RETRIES}次）", file=sys.stderr)
            time.sleep(wait)
            continue

        suffix = f"，已重試{attempt}次仍失敗" if attempt > 1 else ""
        print(f"[warn] Gemini health-check for {symbol}: {err_detail}{suffix}", file=sys.stderr)
        return None

    return None


def get_stock_health_check(
    symbol, name, price, change_pct,
    eps, roe, pe, dividend_yield, revenue, gross_margin,
    ma30, ma60, ma100, bias30,
    above30, ma30_rising, above60, ma60_rising, above100, ma100_rising,
    badges,
):
    """回傳健檢分析 dict，失敗或沒有 API key 回傳 None：
    {
      "fundamentalComment": str,   # <=50字左右，語意完整
      "fundamentalScore": int,     # 0-50
      "technicalComment": str,     # <=50字左右，語意完整
      "technicalScore": int,       # 0-50
      "overallComment": str,       # <=50字左右，綜合基本面+技術面
      "totalScore": int,           # fundamentalScore + technicalScore，1-100
    }
    """
    if not GEMINI_API_KEY:
        return None

    def fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "無資料"

    def fmt_revenue(v):
        if v is None:
            return "無資料"
        abs_v = abs(v)
        if abs_v >= 1e9:
            return f"{v / 1e9:.2f}B"
        if abs_v >= 1e6:
            return f"{v / 1e6:.1f}M"
        return f"{v:,.0f}"

    def fmt_ma_status(above, rising, label):
        if above is None or rising is None:
            return f"{label}：無資料"
        pos = "站上" if above else "跌破"
        trend = "上揚" if rising else "下彎"
        return f"{label}：{pos}、{trend}"

    prompt = (
        "你是專業證券分析師，請針對以下這檔股票同時給出「基本面」「技術面」兩個構面的短評與健檢分數，"
        "再給一段綜合兩者的短評。務必只輸出下面指定格式的純JSON，不要加任何前言、markdown code fence、"
        "或JSON以外的文字。\n\n"
        "評分標準（務必依此標準給分，不要自創標準）：\n"
        "【基本面分數，0-50分】EPS為正且合理：加分，為負：大幅扣分；"
        "ROE>20%優異(接近滿分)、10-20%普通(中段)、<10%偏弱(低分)；"
        "本益比(P/E)落在合理區間(不過高不過低)酌情加分，明顯過高或財報虧損導致本益比失真則扣分；"
        "股息殖利率穩定可加分，成長股沒有股息不必扣分。\n"
        "【技術面分數，0-50分】站上30/60/100MA且三條均線都呈上揚(多頭排列)：高分(接近滿分)；"
        "站上均線但均線走平或下彎：中等分數；跌破均線且均線下彎：低分；"
        "30日乖離率過大(例如超過±15%)代表短線過熱或超跌，酌情扣分。\n\n"
        "請輸出以下JSON格式（分數必須是整數）：\n"
        "{\n"
        '  "fundamentalComment": "一段不超過50個繁體中文字、語意完整結束的基本面短評",\n'
        '  "fundamentalScore": 0到50之間的整數,\n'
        '  "technicalComment": "一段不超過50個繁體中文字、語意完整結束的技術面短評",\n'
        '  "technicalScore": 0到50之間的整數,\n'
        '  "overallComment": "一段不超過50個繁體中文字、語意完整結束、綜合基本面與技術面的短評"\n'
        "}\n\n"
        f"股票代號：{symbol}（{name}）\n"
        f"目前收盤價：{price}，今日漲跌幅：{change_pct}%\n"
        "--- 基本面數據 ---\n"
        f"EPS(TTM)：{fmt(eps)}\n"
        f"ROE：{fmt(roe, '%')}\n"
        f"本益比(P/E, TTM)：{fmt(pe)}\n"
        f"股息殖利率：{fmt(dividend_yield, '%')}\n"
        f"近一季營收：{fmt_revenue(revenue)}\n"
        f"近一季毛利率：{fmt(gross_margin, '%')}\n"
        "--- 技術面數據 ---\n"
        f"{fmt_ma_status(above30, ma30_rising, '30MA')}，30MA數值：{fmt(ma30)}，收盤價與30MA乖離率：{fmt(bias30, '%')}\n"
        f"{fmt_ma_status(above60, ma60_rising, '60MA')}，60MA數值：{fmt(ma60)}\n"
        f"{fmt_ma_status(above100, ma100_rising, '100MA')}，100MA數值：{fmt(ma100)}\n"
        f"本次符合的選股訊號：{'、'.join(badges) if badges else '無'}"
    )

    raw_text = _call_gemini_with_retry(prompt, symbol)
    if raw_text is None:
        return None

    cleaned = raw_text.strip()
    cleaned = cleaned.replace("```json", "").replace("```", "").strip()

    try:
        parsed = json.loads(cleaned)
    except Exception as e:
        print(f"[warn] Gemini health-check for {symbol}: 回傳內容不是合法JSON {e} - {cleaned[:300]}", file=sys.stderr)
        return None

    fundamental_score = _clamp_score(parsed.get("fundamentalScore"), 0, 50)
    technical_score = _clamp_score(parsed.get("technicalScore"), 0, 50)

    if fundamental_score is None or technical_score is None:
        print(f"[warn] Gemini health-check for {symbol}: 分數欄位缺漏或無法解析 - {cleaned[:300]}", file=sys.stderr)
        return None

    total_score = max(1, min(100, fundamental_score + technical_score))

    return {
        "fundamentalComment": _finish_at_natural_end(str(parsed.get("fundamentalComment") or "").strip(), MAX_COMMENT_CHARS),
        "fundamentalScore": fundamental_score,
        "technicalComment": _finish_at_natural_end(str(parsed.get("technicalComment") or "").strip(), MAX_COMMENT_CHARS),
        "technicalScore": technical_score,
        "overallComment": _finish_at_natural_end(str(parsed.get("overallComment") or "").strip(), MAX_COMMENT_CHARS),
        "totalScore": total_score,
    }
