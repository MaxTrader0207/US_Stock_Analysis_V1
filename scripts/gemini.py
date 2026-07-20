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
呼叫失敗（額度用完、網路問題、模型名稱過期等）也是回傳 None 並印警告，同樣不會中斷抓取。
"""
import os
import sys

import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or None
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.1-flash-lite"
GEMINI_ENDPOINT = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
MAX_COMMENT_CHARS = 20


def get_short_comment(symbol, name, price, change_pct, ma10, ma30, ma60, ma100,
                       bias30, high52w, low52w, rsi6, badges):
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
        f"10日均線：{fmt(ma10)}，30日均線：{fmt(ma30)}，"
        f"60日均線：{fmt(ma60)}，100日均線：{fmt(ma100)}\n"
        f"收盤價與30日均線乖離率：{fmt(bias30, '%')}\n"
        f"52週最高：{fmt(high52w)}，52週最低：{fmt(low52w)}\n"
        f"RSI(6)：{fmt(rsi6)}\n"
        f"本次符合的選股訊號：{'、'.join(badges) if badges else '無'}"
    )

    try:
        resp = requests.post(
            GEMINI_ENDPOINT,
            params={"key": GEMINI_API_KEY},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().strip('「」"\'')
        # 保底裁切：模型偶爾不會嚴格遵守字數限制，這裡強制裁到上限避免卡片被撐爆
        return text[:MAX_COMMENT_CHARS]
    except Exception as e:
        print(f"[warn] Gemini comment for {symbol}: {e}", file=sys.stderr)
        return None
