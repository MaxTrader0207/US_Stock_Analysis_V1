#!/usr/bin/env python3
"""
抓取 6 種熱力圖資料，輸出到 data/heatmap_<id>.json 供前端切換顯示。
對應 finviz.com/map 的 6 個 t 參數：
  sec_dji  -> data/heatmap_dji.json     道瓊工業平均（依板塊分組）
  sec_ndx  -> data/heatmap_ndx.json     那斯達克100（依板塊分組，精簡清單）
  sec      -> data/heatmap_sp500.json   S&P 500（依板塊分組，精簡權值股清單）
  etf      -> data/heatmap_etf.json     ETF（依類別分組）
  futures  -> data/heatmap_futures.json 期貨（依資產類別分組）
  crypto   -> data/heatmap_crypto.json  加密貨幣（依市值分層分組）

用法：python scripts/fetch_heatmap.py
需求：pip install yfinance

設計說明：
- Yahoo Finance 官方查詢端點在瀏覽器端會被 CORS 擋下，因此改由
  GitHub Actions 排程在伺服器端執行本腳本，產生靜態 JSON，
  前端頁面單純 fetch 這份 JSON。
- 每個清單都是精簡過的代表性成分股，可自行增減。
- futures / crypto 沒有市值概念，用成交量或固定權重當方塊大小。
"""
import json
import sys
from datetime import datetime, timezone

import yfinance as yf

# ---------- 各市場成分股清單（依分組） ----------

# 道瓊工業平均 30 檔成分股（依板塊分組，2026年中版本，含 Alphabet 取代 Walgreens 後名單）
DJI_GROUPS = {
    "Technology": ["AAPL", "CSCO", "IBM", "MSFT", "NVDA", "CRM"],
    "Financials": ["AXP", "GS", "JPM", "TRV", "V"],
    "Healthcare": ["AMGN", "JNJ", "MRK", "UNH"],
    "Consumer": ["AMZN", "HD", "MCD", "NKE"],
    "Industrials": ["MMM", "BA", "CAT", "HON"],
    "Communication": ["GOOGL", "DIS"],
    "Staples": ["KO", "PG", "WMT"],
    "Energy": ["CVX"],
    "Materials": ["SHW"],
}

# 那斯達克100 核心／權重最高成分股（依板塊分組，2026年中版本）
NDX_GROUPS = {
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AVGO", "AMD", "ASML", "AMAT", "QCOM", "TXN",
        "NXPI", "MU", "ARM", "LRCX", "ADI", "MCHP", "ADBE", "INTU", "CRWD",
        "PANW", "DDOG", "WDAY", "TEAM", "CDNS", "SNPS",
    ],
    "Communication": ["GOOGL", "GOOG", "META", "NFLX"],
    "Consumer": ["AMZN", "TSLA", "COST", "SBUX", "PEP", "BKNG", "ABNB", "MAR", "LULU", "KHC", "ORLY", "CTAS"],
    "Healthcare": ["VRTX", "GILD", "ISRG", "REGN", "MRNA", "AZN", "GEHC"],
}

# S&P 500 精簡權值股清單（依板塊分組）
SP500_GROUPS = {
    "Technology": ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "CRM", "ADBE", "AMD", "CSCO", "IBM"],
    "Communication": ["GOOGL", "META", "NFLX", "TMUS", "DIS", "CMCSA"],
    "Consumer": ["AMZN", "TSLA", "HD", "MCD", "NKE", "SBUX", "LOW", "TJX"],
    "Financials": ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS"],
    "Healthcare": ["LLY", "UNH", "JNJ", "ABBV", "MRK", "PFE", "TMO"],
    "Energy": ["XOM", "CVX", "COP", "SLB"],
    "Industrials": ["GE", "CAT", "BA", "HON", "UPS", "RTX"],
}

# ETF（依類別分組）
ETF_GROUPS = {
    "Broad Market": ["SPY", "QQQ", "DIA", "IWM", "VTI"],
    "Sector": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLI"],
    "Bond": ["TLT", "AGG", "LQD", "HYG"],
    "Commodity": ["GLD", "SLV", "USO"],
    "International": ["EFA", "EEM", "FXI"],
}

# 期貨（依資產類別分組，yfinance 代碼格式為 XX=F）
FUTURES_GROUPS = {
    "Indices": ["ES=F", "NQ=F", "YM=F", "RTY=F"],
    "Energy": ["CL=F", "NG=F", "RB=F"],
    "Metals": ["GC=F", "SI=F", "HG=F"],
    "Agriculture": ["ZC=F", "ZS=F", "ZW=F"],
    "Currencies": ["6E=F", "6J=F", "6B=F"],
    "Bonds": ["ZB=F", "ZN=F"],
}

# 加密貨幣（依市值分層分組，yfinance 代碼格式為 XXX-USD）
# 註：Yahoo Finance 部分幣種代碼格式較特殊，若抓取時出現 warning，
#     請至 finance.yahoo.com 搜尋該幣種確認正確代碼後修正。
CRYPTO_GROUPS = {
    "Major": ["BTC-USD", "ETH-USD"],
    "Large Cap": ["BNB-USD", "XRP-USD", "SOL-USD", "TRX-USD", "DOGE-USD", "ADA-USD"],
    "Mid Cap": [
        "LINK-USD", "TON-USD", "BCH-USD", "LTC-USD", "AVAX-USD",
        "XLM-USD", "HBAR-USD", "SUI-USD", "NEAR-USD", "ZEC-USD", "SHIB-USD",
    ],
}

MAPS = [
    ("data/heatmap_dji.json", DJI_GROUPS),
    ("data/heatmap_ndx.json", NDX_GROUPS),
    ("data/heatmap_sp500.json", SP500_GROUPS),
    ("data/heatmap_etf.json", ETF_GROUPS),
    ("data/heatmap_futures.json", FUTURES_GROUPS),
    ("data/heatmap_crypto.json", CRYPTO_GROUPS),
]


def fetch_group(name, tickers):
    """
    抓取單一分組的報價。改用 history() 抓最近幾個交易日的收盤價來算漲跌幅，
    而不是用 fast_info 的 last_price / previous_close ——
    fast_info 在非交易時段（例如週末、假日剛跑排程時）容易把兩者算成同一天，
    導致漲跌幅全部顯示 0%。用 history() 抓「最近兩個真正有成交的交易日」比較穩。
    """
    children = []
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            hist = tk.history(period="5d", interval="1d", auto_adjust=True)
            if hist.empty:
                print(f"[warn] {t}: no history data", file=sys.stderr)
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 1:
                continue
            price = float(closes.iloc[-1])
            prev_close = float(closes.iloc[-2]) if len(closes) >= 2 else price
            chg_pct = ((price - prev_close) / prev_close * 100) if prev_close else 0

            # 市值優先用 fast_info；期貨/部分商品沒有市值，退而求其次用成交量
            size = 1.0
            try:
                info = tk.fast_info
                market_cap = info.get("market_cap")
                if market_cap:
                    size = float(market_cap) / 1e9  # billions
                else:
                    volume = float(hist["Volume"].dropna().iloc[-1]) if "Volume" in hist else 0
                    size = volume / 1e6 if volume else 1.0
            except Exception:
                pass

            symbol_display = t.replace("=F", "").replace("-USD", "")
            children.append({
                "symbol": symbol_display,
                "name": t,
                "price": round(price, 2),
                "changePercent": round(chg_pct, 2),
                "marketCap": round(size, 2),
            })
        except Exception as e:
            print(f"[warn] {t}: {e}", file=sys.stderr)
    return {"name": name, "children": children}


def build_map(groups):
    sectors = [fetch_group(name, tickers) for name, tickers in groups.items()]
    return {
        "updated": datetime.now(timezone.utc).isoformat(),
        "sectors": [s for s in sectors if s["children"]],
    }


def main():
    for path, groups in MAPS:
        out = build_map(groups)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(f"Wrote {path} ({sum(len(s['children']) for s in out['sectors'])} tickers)")


if __name__ == "__main__":
    main()
