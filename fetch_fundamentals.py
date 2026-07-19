#!/usr/bin/env python3
"""
抓取股票的基本面資料，依「傳奇投資大師」的量化選股條件篩選，
輸出 data/fundamentals.json 供前端「基本面選股」頁籤使用。

用法：python scripts/fetch_fundamentals.py
需求：pip install yfinance pandas

目前規劃 5 位大師，只有【巴菲特】的條件已經明確、已實作；
其餘 4 位先以「規劃中」佔位，之後補上條件後比照 build_buffett() 寫一個函式即可，
前端 fundamentals.html / fundamentals.js 不需要修改。

【巴菲特】
  1. 近5年平均 ROE > 15%
  2. 最新年度毛利率 > 40%
  3. 負債權益比 < 50%
  4. 連續5年自由現金流 > 0
  5. 本益比 < 15，或本益比低於其5年均值

⚠️ 資料來源限制（務必留意）：
  - yfinance 免費抓到的年度財報（financials / balance_sheet / cashflow）
    通常只有「最近 4 個會計年度」，不一定真的有 5 年。程式會盡量抓到幾年算幾年，
    並在結果的 badges 裡標註實際使用的年數，避免誤以為一定是精算過5年的結果。
  - 「5年均值本益比」用「近5年月收盤價 ÷ 目前TTM每股盈餘」概算，
    等於假設過去5年EPS大致不變，是簡化算法，不是精確的歷史本益比序列，
    只能當作粗略的估值水位參考。
  - 部分股票（尤其是最近才上市、或財報揭露方式特殊的公司）可能缺少某些欄位，
    程式會直接跳過該檔，不會強行猜測數字。
"""
import json
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from tickers import SCREENER_UNIVERSE

UNIVERSE_NOTE = "母體：道瓊工業平均 + S&P 500精簡清單 + 那斯達克100核心清單 + 費城半導體指數(SOX)，去重合併共102檔。"


def get_row(df, candidates):
    """從財報 DataFrame 裡找第一個存在的列名，回傳該列（index為年度日期）。找不到回傳 None。
    yfinance 不同版本對同一個科目的列名不一致（例如「Total Stockholder Equity」vs
    「Stockholders Equity」），所以用候選清單依序嘗試。"""
    if df is None or df.empty:
        return None
    for name in candidates:
        if name in df.index:
            return df.loc[name]
    return None


def pct_change(close):
    prev_close = close.iloc[-2] if len(close) > 1 else close.iloc[-1]
    return (close.iloc[-1] - prev_close) / prev_close * 100 if prev_close else 0


def evaluate_buffett(symbol, name):
    tk = yf.Ticker(symbol)

    fin = tk.financials          # 年度損益表（欄位由新到舊排列）
    bs = tk.balance_sheet        # 年度資產負債表
    cf = tk.cashflow             # 年度現金流量表
    info = tk.info or {}

    net_income = get_row(fin, ["Net Income", "Net Income Common Stockholders", "NetIncome"])
    total_revenue = get_row(fin, ["Total Revenue", "TotalRevenue"])
    gross_profit = get_row(fin, ["Gross Profit", "GrossProfit"])
    equity = get_row(bs, ["Total Stockholder Equity", "Stockholders Equity", "Common Stock Equity"])
    total_debt = get_row(bs, ["Total Debt", "TotalDebt"])
    op_cash_flow = get_row(cf, ["Operating Cash Flow", "Total Cash From Operating Activities", "Cash Flow From Continuing Operating Activities"])
    capex = get_row(cf, ["Capital Expenditure", "CapitalExpenditure", "Purchase Of PPE"])
    free_cash_flow = get_row(cf, ["Free Cash Flow", "FreeCashFlow"])

    if net_income is None or equity is None or total_revenue is None or gross_profit is None:
        return None

    # ---- 1. 近幾年平均 ROE（yfinance 通常只有近4年年報，能抓幾年算幾年）----
    years_available = min(len(net_income), len(equity))
    if years_available < 2:
        return None
    roe_list = []
    for i in range(years_available):
        eq = equity.iloc[i]
        ni = net_income.iloc[i]
        if eq and eq != 0 and pd.notna(eq) and pd.notna(ni):
            roe_list.append(ni / eq)
    if not roe_list:
        return None
    avg_roe = sum(roe_list) / len(roe_list)
    roe_pass = avg_roe > 0.15

    # ---- 2. 最新年度毛利率 ----
    latest_revenue = total_revenue.iloc[0]
    latest_gross_profit = gross_profit.iloc[0]
    if not latest_revenue:
        return None
    gross_margin = latest_gross_profit / latest_revenue
    margin_pass = gross_margin > 0.40

    # ---- 3. 負債權益比 ----
    latest_equity = equity.iloc[0]
    if total_debt is not None and len(total_debt) > 0 and pd.notna(total_debt.iloc[0]) and latest_equity:
        debt_to_equity = total_debt.iloc[0] / latest_equity
    else:
        # 財報抓不到 Total Debt 時，退而求其次用 Yahoo 自己算好的 debtToEquity（單位是百分比）
        dte_info = info.get("debtToEquity")
        debt_to_equity = (dte_info / 100) if dte_info is not None else None
    if debt_to_equity is None:
        return None
    debt_pass = debt_to_equity < 0.50

    # ---- 4. 連續自由現金流 > 0（能抓到幾年就檢查幾年）----
    if free_cash_flow is not None and len(free_cash_flow) > 0:
        fcf_series = free_cash_flow.dropna()
    elif op_cash_flow is not None and capex is not None:
        n = min(len(op_cash_flow), len(capex))
        fcf_series = (op_cash_flow.iloc[:n] + capex.iloc[:n])  # capex 在財報裡通常已是負值
    else:
        return None
    if len(fcf_series) < 2:
        return None
    fcf_years_checked = len(fcf_series)
    fcf_pass = bool((fcf_series > 0).all())

    # ---- 5. 本益比 < 15，或低於5年均值 ----
    trailing_pe = info.get("trailingPE")
    trailing_eps = info.get("trailingEps")
    if trailing_pe is None:
        return None
    pe_pass_absolute = trailing_pe < 15

    pe_pass_vs_avg = False
    try:
        hist = tk.history(period="5y", interval="1mo", auto_adjust=True)
        if not hist.empty and trailing_eps and trailing_eps > 0:
            approx_pe_series = hist["Close"] / trailing_eps
            avg_pe_5y = approx_pe_series.mean()
            pe_pass_vs_avg = trailing_pe < avg_pe_5y
    except Exception:
        pass

    pe_pass = pe_pass_absolute or pe_pass_vs_avg

    if not (roe_pass and margin_pass and debt_pass and fcf_pass and pe_pass):
        return None

    price_hist = tk.history(period="5d", interval="1d", auto_adjust=True)
    if price_hist.empty:
        return None
    price = float(price_hist["Close"].iloc[-1])
    chg = round(float(pct_change(price_hist["Close"])), 2)

    badges = [
        f"近{years_available}年均ROE {avg_roe*100:.1f}%",
        f"毛利率 {gross_margin*100:.1f}%",
        f"負債權益比 {debt_to_equity*100:.0f}%",
        f"FCF連{fcf_years_checked}年為正",
        "本益比<15" if pe_pass_absolute else "本益比低於5年均值",
    ]

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "changePercent": chg,
        "badges": badges,
    }


def build_buffett():
    results = []
    for symbol, name in SCREENER_UNIVERSE.items():
        try:
            r = evaluate_buffett(symbol, name)
            if r:
                results.append(r)
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)
    results.sort(key=lambda r: r["changePercent"], reverse=True)
    return {
        "id": "buffett",
        "name": "巴菲特",
        "description": "近5年平均ROE>15%；最新年度毛利率>40%；負債權益比<50%；連續5年自由現金流>0；本益比<15或低於其5年均值。（yfinance財報年限所限，實際檢核年數可能少於5年，詳見各標的badge標註）" + UNIVERSE_NOTE,
        "status": "active",
        "results": results,
    }


def stub_master(id_, name):
    """尚未提供選股條件的大師，先以規劃中佔位。"""
    return {
        "id": id_,
        "name": name,
        "description": "選股條件規劃中，待補充後上線。",
        "status": "coming-soon",
        "results": [],
    }


def main():
    master_sets = [
        build_buffett(),
        stub_master("master-2", "大師二"),
        stub_master("master-3", "大師三"),
        stub_master("master-4", "大師四"),
        stub_master("master-5", "大師五"),
    ]
    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "masterSets": master_sets,
    }
    with open("data/fundamentals.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("Wrote data/fundamentals.json")


if __name__ == "__main__":
    main()
