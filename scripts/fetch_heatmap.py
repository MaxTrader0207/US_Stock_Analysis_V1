#!/usr/bin/env python3
"""
抓取美股大型股報價，輸出 data/heatmap.json 供前端熱力圖使用。
用法：python scripts/fetch_heatmap.py
需求：pip install yfinance

設計說明：
- Yahoo Finance 官方查詢端點在瀏覽器端會被 CORS 擋下，因此改由
  GitHub Actions 排程在伺服器端執行本腳本，產生靜態 JSON，
  前端頁面單純 fetch 這份 JSON（沿用你之前 NVDA/TSM dashboard 的作法）。
- SECTOR_TICKERS 是精簡過的權值股清單（依板塊分組），
  可自行增減成分股；若要涵蓋完整 S&P 500，可改讀外部成分股清單。
"""
import json
import sys
from datetime import datetime, timezone

import yfinance as yf

SECTOR_TICKERS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "IBM"],
    "Communication": ["GOOGL", "META", "NFLX", "TMUS", "DIS", "CMCSA"],
    "Consumer": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX"],
    "Financials": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS"],
    "Healthcare": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO"],
    "Energy": ["XOM", "CVX", "COP", "SLB"],
    "Industrials": ["GE", "CAT", "BA", "HON", "UPS", "RTX"],
}


def fetch_sector(name, tickers):
    children = []
    data = yf.Tickers(" ".join(tickers))
    for t in tickers:
        try:
            info = data.tickers[t].fast_info
            price = float(info.get("last_price") or 0)
            prev_close = float(info.get("previous_close") or 0)
            market_cap = float(info.get("market_cap") or 0) / 1e9  # billions
            chg_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0
            symbol_display = t.replace("-", ".")
            children.append({
                "symbol": symbol_display,
                "name": t,
                "price": round(price, 2),
                "changePercent": round(chg_pct, 2),
                "marketCap": round(market_cap, 1),
            })
        except Exception as e:
            print(f"[warn] {t}: {e}", file=sys.stderr)
    return {"name": name, "children": children}


def main():
    sectors = [fetch_sector(name, tickers) for name, tickers in SECTOR_TICKERS.items()]
    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "sectors": [s for s in sectors if s["children"]],
    }
    with open("data/heatmap.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote data/heatmap.json")


if __name__ == "__main__":
    main()
