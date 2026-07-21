#!/usr/bin/env python3
"""
呼叫 Gemini API，針對選股結果裡的個股產生一句不超過20字的短評。
給 fetch_screener.py 使用（也可以給之後其他腳本共用）。

需求：
  - pip install requests
  - 環境變數 GEMINI_API_KEY：你自己的 Gemini API Key（去 Google AI Studio 免費申請）
  - 環境變數 GEMINI_MODEL（可選）：預設用 gemini-3.1-flash-lite
    （Google 的模型名稱／別名會定期汰換，如果之後這個模型名稱過期回傳 404，
    去 https://ai.google.dev/gemini-api/docs/models 查目前建議用的輕量模型名稱替換即可）

⚠️ 沒有設定 GEMINI_API_KEY 時，get_short_comment() 一律回傳 None，
不會讓整個抓取流程失敗——短評只是錦上添花的附加資訊，不是選股邏輯的一部分。

呼叫遇到 429（限流）或 5xx（伺服器暫時性錯誤）會自動退避重試（預設最多3次，
間隔 5s → 10s → 20s，或優先採用 Google 回傳的 Retry-After 秒數）；
其餘錯誤（Key 無效、模型名稱過期等重試也沒用的狀況）會直接放棄並印警告，
同樣不會中斷抓取。可透過環境變數 GEMINI_MAX_RETRIES / GEMINI_BACKOFF_BASE_SECONDS 調整。
"""
import os
import sys
import time

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
MAX_COMMENT_CHARS = 20

# 重試設定：只針對「可能重試就會成功」的錯誤重打，429(限流)/5xx(伺服器暫時性錯誤)/連線逾時都算，
# 400(格式錯誤)/403(Key無效)這種重試也沒用的錯誤不會重試，直接放棄避免浪費時間。
GEMINI_MAX_RETRIES = int(os.environ.get("GEMINI_MAX_RETRIES") or 3)
GEMINI_BACKOFF_BASE_SECONDS = float(os.environ.get("GEMINI_BACKOFF_BASE_SECONDS") or 5)

# 開機時就印一行明確的狀態訊息（不會洩漏完整 Key），
# 之後排查「短評到底有沒有跑」時，Actions log 一眼就能看到，不用再靠猜的。
if GEMINI_API_KEY:
    _masked = GEMINI_API_KEY[:4] + "..." + GEMINI_API_KEY[-4:] if len(GEMINI_API_KEY) > 8 else "***"
    print(f"[info] GEMINI_API_KEY 已偵測到（{_masked}），model={GEMINI_MODEL}，將呼叫 Gemini 產生短評", file=sys.stderr)
else:
    print("[info] 未偵測到 GEMINI_API_KEY 環境變數，本次不會呼叫 Gemini，comment 欄位全部會是 null", file=sys.stderr)


def get_short_comment(symbol, name, price, change_pct, ma30, ma60, ma100, bias30, badges):
    """回傳一句 <=20字的繁體中文短評字串；沒有 API key 或呼叫失敗回傳 None。"""
    if not GEMINI_API_KEY:
        return None

    def fmt(v, suffix=""):
        return f"{v}{suffix}" if v is not None else "無資料"

    prompt = (
        "你是證券分析師，請針對以下這檔股票的技術面現況，"
        f"給一句不超過{MAX_COMMENT_CHARS}個繁體中文字的精簡短評，"
        "只能輸出短評本身，不要加任何前言、標點以外的說明、也不要加引號。\n\n"
        f"股票代號：{symbol}（{name}）\n"
        f"目前收盤價：{price}，今日漲跌幅：{change_pct}%\n"
        f"30日均線：{fmt(ma30)}，60日均線：{fmt(ma60)}，100日均線：{fmt(ma100)}\n"
        f"收盤價與30日均線乖離率：{fmt(bias30, '%')}\n"
        f"本次符合的選股訊號：{'、'.join(badges) if badges else '無'}"
    )

    for attempt in range(1, GEMINI_MAX_RETRIES + 1):
        try:
            resp = requests.post(
                GEMINI_ENDPOINT,
                params={"key": GEMINI_API_KEY},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=15,
            )
        except requests.exceptions.RequestException as e:
            # 連線層級的錯誤（逾時、DNS、連線中斷等）一律視為可重試
            if attempt < GEMINI_MAX_RETRIES:
                wait = GEMINI_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
                print(f"[warn] Gemini comment for {symbol}: 連線錯誤 {e}，{wait:.0f}秒後重試（第{attempt}/{GEMINI_MAX_RETRIES}次）", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"[warn] Gemini comment for {symbol}: 連線錯誤 {e}，已重試{GEMINI_MAX_RETRIES}次仍失敗，放棄", file=sys.stderr)
            return None

        if resp.ok:
            try:
                data = resp.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                text = text.strip().strip('「」"\'')
                # 保底裁切：模型偶爾不會嚴格遵守字數限制，這裡強制裁到上限避免卡片被撐爆
                return text[:MAX_COMMENT_CHARS]
            except Exception as e:
                # 回應格式跟預期不符（例如被安全過濾擋掉、回傳結構改變），重試也沒用，直接放棄
                print(f"[warn] Gemini comment for {symbol}: 回應格式異常 {e} - {resp.text[:300]}", file=sys.stderr)
                return None

        # HTTP 429（限流）與 5xx（伺服器暫時性錯誤）視為可重試；其餘（400/403等）直接放棄
        retryable = resp.status_code == 429 or resp.status_code >= 500
        err_detail = f"HTTP {resp.status_code} - {resp.text[:300]}"

        if retryable and attempt < GEMINI_MAX_RETRIES:
            # 優先用 Google 回傳的 Retry-After 秒數，沒有的話用指數退避（5s → 10s → 20s...）
            retry_after = resp.headers.get("Retry-After")
            wait = float(retry_after) if retry_after else GEMINI_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            print(f"[warn] Gemini comment for {symbol}: {err_detail}，{wait:.0f}秒後重試（第{attempt}/{GEMINI_MAX_RETRIES}次）", file=sys.stderr)
            time.sleep(wait)
            continue

        suffix = f"，已重試{attempt}次仍失敗" if attempt > 1 else ""
        print(f"[warn] Gemini comment for {symbol}: {err_detail}{suffix}", file=sys.stderr)
        return None

    return None
