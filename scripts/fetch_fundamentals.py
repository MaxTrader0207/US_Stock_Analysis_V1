#!/usr/bin/env python3
"""
抓取股票的基本面資料，依「傳奇投資大師」的量化選股條件篩選，
輸出 data/fundamentals.json 供前端「基本面選股」頁籤使用。

用法：python scripts/fetch_fundamentals.py
需求：pip install yfinance pandas requests

5 位大師：巴菲特、馬克約克奇、麥克墨菲、彼得林區、班哲明格拉罕，條件詳見各
evaluate_xxx() 函式前的註解。

效能設計：每檔股票只抓一次完整的財報／股利／股價資料包（fetch_ticker_bundle），
5 位大師共用同一包資料各自判斷，不會每位大師都重新打一次 API——
母體有 159 檔，若不做這個優化，API 呼叫量會直接乘以 5。

卡片內容（比照強勢股選股頁的三色區塊格式，欄位命名也完全一致）：
  - A.基本面：EPS/ROE/P/E/殖利率，這些欄位其實已經包含在 fetch_ticker_bundle 抓的
    tk.info 裡（5位大師的篩選條件本來就要用到），不需要額外多打API
  - B.技術面：30/60/100MA 站上/上揚狀態＋30MA乖離率，需要把 price_hist 從原本的
    5天改成抓1年，才夠算出這幾條均線（詳見 fetch_ticker_bundle）
  - C.健檢分數：呼叫 Gemini API 產生基本面/技術面/綜合三段短評＋兩個分數，
    為了控制額度消耗，只對每位大師「依當日漲跌幅排序」的前 FUNDAMENTALS_GEMINI_TOP_N
    名呼叫（預設5名，比強勢股頁的10名更保守——因為這裡是5位大師各自算一次，
    加總後對 Gemini 的呼叫量本來就會是強勢股頁的好幾倍）

⚠️ 資料來源限制（務必留意，這些是 yfinance 免費資料的先天限制，不是程式bug）：
  - 「近12季」：yfinance 免費版的季報通常只給「最近4~8季」，抓不滿12季。
    程式一律「抓到幾季算幾季」，並在 badge 上老實標註實際使用的季數。
  - 「近5年」「近3年」等年度指標：yfinance 免費年報通常只有「最近4個會計年度」，
    同樣是抓到幾年算幾年，badge 會標註實際年數。
  - 「董監事持股比例」「質押比例」：這是台股公開資訊觀測站特有的揭露項目，
    美股沒有對應的公開免費資料源。程式用 Yahoo 的 heldPercentInsiders（廣義的
    「內部人持股比例」，範圍比「董監事持股」更廣）當替代指標，且完全沒有質押比例
    這個維度可用，彼得林區條件3只檢查內部人持股比例，質押比例的部分無法檢核。
  - 「近12月營收於該產業排名前40%」：只能在「本專案掃描的159檔母體」內依 Yahoo
    的 industry 分類做相對排名，不是跟該產業「全市場」所有公司比較。如果某產業
    在母體裡剛好只有1~2檔，排名幾乎沒有意義，這點請知悉。
  - 部分股票缺少特定欄位時，程式一律直接跳過該檔，不會用假設值硬湊。
  - 股息殖利率(dividendYield)：這個 repo 目前用的 yfinance 版本回傳的就已經是
    百分比數字本身（例如0.36代表0.36%），不需要再乘以100（強勢股頁那邊踩過這個坑，
    這裡直接用修正後的寫法）。
"""
import json
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from tickers import SCREENER_UNIVERSE
from common import (
    safe_round, get_row, pct_change, ma_status, extract_fundamentals_from_info,
    yf_call_with_retry, load_gemini_cache, save_gemini_cache, run_gemini_health_check_pass,
    CROSS_LOOKBACK,
)

UNIVERSE_NOTE = "母體：道瓊工業平均(30檔) + S&P 500依權重前71檔 + 那斯達克100完整清單(101檔) + 費城半導體指數SOX(30檔)，去重合併共159檔。"

FUNDAMENTALS_GEMINI_TOP_N = int(os.environ.get("FUNDAMENTALS_GEMINI_TOP_N") or 5)


def latest_quarter_revenue_and_margin(qfin):
    """近一季營收、毛利率。qfin 是 fetch_ticker_bundle 已經抓好的季報，不需要額外打API。"""
    rev_row = get_row(qfin, ["Total Revenue", "TotalRevenue"])
    gp_row = get_row(qfin, ["Gross Profit", "GrossProfit"])
    if rev_row is None or rev_row.empty:
        return None, None
    revenue = rev_row.iloc[0]
    if revenue is None or pd.isna(revenue) or revenue == 0:
        return None, None
    revenue = float(revenue)
    gross_margin = None
    if gp_row is not None and not gp_row.empty:
        gp = gp_row.iloc[0]
        if gp is not None and pd.notna(gp):
            gross_margin = round(float(gp) / revenue * 100, 2)
    return revenue, gross_margin


def avg_ratio(numerator_row, denominator_row, max_periods=None):
    """對同一組(分子,分母)逐期取比率再平均。回傳 (平均值或None, 實際採用的期數)。"""
    if numerator_row is None or denominator_row is None:
        return None, 0
    n = min(len(numerator_row), len(denominator_row))
    if max_periods:
        n = min(n, max_periods)
    ratios = []
    for i in range(n):
        d = denominator_row.iloc[i]
        nu = numerator_row.iloc[i]
        if d is not None and pd.notna(d) and pd.notna(nu) and d != 0:
            ratios.append(nu / d)
    if not ratios:
        return None, 0
    return sum(ratios) / len(ratios), len(ratios)


def avg_growth_rate(row, max_periods=3):
    """逐期年增率（(本期-上期)/|上期|）再平均。row 由新到舊排列。"""
    if row is None:
        return None, 0
    vals = row.dropna()
    n = min(len(vals), max_periods + 1)
    if n < 2:
        return None, 0
    growths = []
    for i in range(n - 1):
        newer, older = vals.iloc[i], vals.iloc[i + 1]
        if older and pd.notna(older) and older != 0:
            growths.append((newer - older) / abs(older))
    if not growths:
        return None, 0
    return sum(growths) / len(growths), len(growths)


def avg_roe(net_income, equity, max_years=5):
    if net_income is None or equity is None:
        return None, 0
    n = min(len(net_income), len(equity), max_years)
    vals = []
    for i in range(n):
        eq, ni = equity.iloc[i], net_income.iloc[i]
        if eq and pd.notna(eq) and pd.notna(ni) and eq != 0:
            vals.append(ni / eq)
    if not vals:
        return None, 0
    return sum(vals) / len(vals), len(vals)


def current_ratio_all_years(bs, years=3):
    """回傳最近N年的流動比率清單；資料不足N年時回傳 None（保守判定為不通過）。"""
    ca = get_row(bs, ["Current Assets", "CurrentAssets", "Total Current Assets"])
    cl = get_row(bs, ["Current Liabilities", "CurrentLiabilities", "Total Current Liabilities"])
    if ca is None or cl is None:
        return None
    n = min(len(ca), len(cl))
    if n < years:
        return None
    ratios = []
    for i in range(years):
        a, c = ca.iloc[i], cl.iloc[i]
        if c is None or pd.isna(c) or pd.isna(a) or c == 0:
            return None
        ratios.append(a / c)
    return ratios


def eps_recent_years(fin, years=5):
    eps_row = get_row(fin, ["Diluted EPS", "Basic EPS", "DilutedEPS", "BasicEPS"])
    if eps_row is None:
        return None
    vals = eps_row.dropna()
    if len(vals) < 1:
        return None
    return list(vals.iloc[:min(len(vals), years)])


def avg_annual_dividend(dividends, years=5):
    if dividends is None or dividends.empty:
        return None, 0
    yearly = dividends.groupby(dividends.index.year).sum().sort_index(ascending=False)
    n = min(len(yearly), years)
    if n < 1:
        return None, 0
    vals = yearly.iloc[:n]
    return float(vals.mean()), n


# ============================================================
# 每檔股票的資料包（5位大師共用，只抓一次）
# ============================================================

def fetch_ticker_bundle(symbol):
    tk = yf.Ticker(symbol)
    # 原本只抓5天（只夠算漲跌幅），現在改抓1年，用來計算30/60/100MA
    # （B區塊技術面）。跟財報/股利資料是各自獨立的請求，不影響原本5位大師的判斷邏輯。
    #
    # history() 跟 info 是這包資料裡最關鍵、也最容易撞到 Yahoo 限流的兩個請求
    # （這個腳本一檔股票要打將近9次請求，159檔就是1400+次，比 fetch_screener.py
    # 更容易被限流），所以這兩個加上重試機制；其餘財報類請求(financials/balance_sheet/
    # cashflow/dividends)目前維持原樣，個別失敗時整批 bundle 會被外層 try/except 捕捉、
    # 跳過該檔股票——如果之後發現財報這幾個也常失敗，可以再比照加上重試。
    price_hist = yf_call_with_retry(
        lambda: tk.history(period="1y", interval="1d", auto_adjust=True),
        f"{symbol} 歷史股價",
    )
    if price_hist is None or price_hist.empty:
        return None

    info = yf_call_with_retry(lambda: tk.info, f"{symbol} info") or {}

    return {
        "info": info,
        "fin": tk.financials,
        "qfin": tk.quarterly_financials,
        "bs": tk.balance_sheet,
        "qbs": tk.quarterly_balance_sheet,
        "cf": tk.cashflow,
        "dividends": tk.dividends,
        "price_hist": price_hist,
        "pe_hist": None,  # 延遲抓取（只有巴菲特條件用得到，避免其他大師也多打一次5年月線）
    }


def base_result(symbol, name, bundle):
    close = bundle["price_hist"]["Close"]
    price = float(close.iloc[-1])

    ma30_series = close.rolling(30).mean()
    ma60_series = close.rolling(60).mean()
    ma100_series = close.rolling(100).mean()
    ma30 = safe_round(ma30_series.iloc[-1]) if len(ma30_series) else None
    ma60 = safe_round(ma60_series.iloc[-1]) if len(ma60_series) else None
    ma100 = safe_round(ma100_series.iloc[-1]) if len(ma100_series) else None
    bias30 = round((price - ma30) / ma30 * 100, 2) if ma30 else None

    above30, ma30_rising = ma_status(price, ma30_series)
    above60, ma60_rising = ma_status(price, ma60_series)
    above100, ma100_rising = ma_status(price, ma100_series)

    info = bundle["info"]
    eps, roe, pe, dividend_yield = extract_fundamentals_from_info(info)

    revenue, gross_margin = latest_quarter_revenue_and_margin(bundle["qfin"])

    return {
        "symbol": symbol,
        "name": name,
        "price": round(price, 2),
        "changePercent": round(float(pct_change(close)), 2),
        "ma30": ma30, "ma60": ma60, "ma100": ma100, "bias30": bias30,
        "above30": above30, "ma30Rising": ma30_rising,
        "above60": above60, "ma60Rising": ma60_rising,
        "above100": above100, "ma100Rising": ma100_rising,
        "eps": eps, "roe": roe, "pe": pe, "dividendYield": dividend_yield,
        "revenueLatestQ": revenue, "grossMarginLatestQ": gross_margin,
    }


# ============================================================
# 【巴菲特】
#   1. 近5年平均ROE>15%　2. 最新年度毛利率>40%　3. 負債權益比<50%
#   4. 連續5年自由現金流>0　5. 本益比<15或低於其5年均值
# ============================================================

def check_buffett(symbol, bundle):
    fin, bs, cf, info = bundle["fin"], bundle["bs"], bundle["cf"], bundle["info"]

    net_income = get_row(fin, ["Net Income", "Net Income Common Stockholders", "NetIncome"])
    total_revenue = get_row(fin, ["Total Revenue", "TotalRevenue"])
    gross_profit = get_row(fin, ["Gross Profit", "GrossProfit"])
    equity = get_row(bs, ["Total Stockholder Equity", "Stockholders Equity", "Common Stock Equity"])
    total_debt = get_row(bs, ["Total Debt", "TotalDebt"])
    op_cf = get_row(cf, ["Operating Cash Flow", "Total Cash From Operating Activities"])
    capex = get_row(cf, ["Capital Expenditure", "CapitalExpenditure", "Purchase Of PPE"])
    fcf_direct = get_row(cf, ["Free Cash Flow", "FreeCashFlow"])

    if net_income is None or equity is None or total_revenue is None or gross_profit is None:
        return None

    roe, roe_years = avg_roe(net_income, equity, 5)
    if roe is None or roe <= 0.15:
        return None

    latest_revenue, latest_gp = total_revenue.iloc[0], gross_profit.iloc[0]
    if not latest_revenue:
        return None
    gross_margin = latest_gp / latest_revenue
    if gross_margin <= 0.40:
        return None

    latest_equity = equity.iloc[0]
    if total_debt is not None and len(total_debt) > 0 and pd.notna(total_debt.iloc[0]) and latest_equity:
        dte = total_debt.iloc[0] / latest_equity
    else:
        dte_info = info.get("debtToEquity")
        dte = (dte_info / 100) if dte_info is not None else None
    if dte is None or dte >= 0.50:
        return None

    if fcf_direct is not None and len(fcf_direct) > 0:
        fcf_series = fcf_direct.dropna()
    elif op_cf is not None and capex is not None:
        n = min(len(op_cf), len(capex))
        fcf_series = op_cf.iloc[:n] + capex.iloc[:n]
    else:
        return None
    if len(fcf_series) < 2 or not bool((fcf_series > 0).all()):
        return None
    fcf_years = len(fcf_series)

    trailing_pe = info.get("trailingPE")
    trailing_eps = info.get("trailingEps")
    if trailing_pe is None:
        return None
    pe_pass_abs = trailing_pe < 15
    pe_pass_avg = False
    try:
        pe_hist = yf.Ticker(symbol).history(period="5y", interval="1mo", auto_adjust=True)
        if not pe_hist.empty and trailing_eps and trailing_eps > 0:
            avg_pe_5y = (pe_hist["Close"] / trailing_eps).mean()
            pe_pass_avg = trailing_pe < avg_pe_5y
    except Exception:
        pass
    if not (pe_pass_abs or pe_pass_avg):
        return None

    return [
        f"近{roe_years}年均ROE {roe*100:.1f}%",
        f"毛利率 {gross_margin*100:.1f}%",
        f"負債權益比 {dte*100:.0f}%",
        f"FCF連{fcf_years}年為正",
        "本益比<15" if pe_pass_abs else "本益比低於5年均值",
    ]


# ============================================================
# 【馬克約克奇】
#   1. 近12季毛利率平均>20%　2. 近3年平均稅前純益成長率>3%
# ============================================================

def check_yockey(bundle):
    qfin, fin = bundle["qfin"], bundle["fin"]

    gp_q = get_row(qfin, ["Gross Profit", "GrossProfit"])
    rev_q = get_row(qfin, ["Total Revenue", "TotalRevenue"])
    margin, margin_q = avg_ratio(gp_q, rev_q, max_periods=12)
    if margin is None or margin <= 0.20:
        return None

    pretax = get_row(fin, ["Pretax Income", "Income Before Tax", "PretaxIncome"])
    growth, growth_y = avg_growth_rate(pretax, max_periods=3)
    if growth is None or growth <= 0.03:
        return None

    return [
        f"近{margin_q}季毛利率均 {margin*100:.1f}%",
        f"近{growth_y}年稅前純益成長率均 {growth*100:.1f}%",
    ]


# ============================================================
# 【麥克墨菲】
#   1. 近12季營業利益率平均>10%　2. 近5年平均ROE>8%
#   3. 近3年平均營收成長率>10%　4. 近4季研發費用占營業額比率>5%
# ============================================================

def check_murphy(bundle):
    qfin, fin, bs = bundle["qfin"], bundle["fin"], bundle["bs"]

    op_income_q = get_row(qfin, ["Operating Income", "OperatingIncome"])
    rev_q = get_row(qfin, ["Total Revenue", "TotalRevenue"])
    op_margin, op_margin_q = avg_ratio(op_income_q, rev_q, max_periods=12)
    if op_margin is None or op_margin <= 0.10:
        return None

    net_income = get_row(fin, ["Net Income", "Net Income Common Stockholders", "NetIncome"])
    equity = get_row(bs, ["Total Stockholder Equity", "Stockholders Equity", "Common Stock Equity"])
    roe, roe_y = avg_roe(net_income, equity, 5)
    if roe is None or roe <= 0.08:
        return None

    total_revenue = get_row(fin, ["Total Revenue", "TotalRevenue"])
    rev_growth, rev_growth_y = avg_growth_rate(total_revenue, max_periods=3)
    if rev_growth is None or rev_growth <= 0.10:
        return None

    rd_q = get_row(qfin, ["Research And Development", "ResearchAndDevelopment", "Research Development"])
    rd_ratio, rd_q_count = avg_ratio(rd_q, rev_q, max_periods=4)
    if rd_ratio is None or rd_ratio <= 0.05:
        return None

    return [
        f"近{op_margin_q}季營業利益率均 {op_margin*100:.1f}%",
        f"近{roe_y}年均ROE {roe*100:.1f}%",
        f"近{rev_growth_y}年營收成長率均 {rev_growth*100:.1f}%",
        f"近{rd_q_count}季研發費用占比均 {rd_ratio*100:.1f}%",
    ]


# ============================================================
# 【彼得林區】
#   1. 近5年平均負債比<30%　2. 本益比<15倍
#   3. 內部人持股比例>30%（美股無法比對「質押比例」，見檔頭說明）
#   4. 近3年平均營收成長率>10%　5. 近3年平均稅前純益成長率>3%
# ============================================================

def check_lynch(bundle):
    bs, fin, info = bundle["bs"], bundle["fin"], bundle["info"]

    total_liab = get_row(bs, ["Total Liabilities Net Minority Interest", "Total Liab", "TotalLiabilitiesNetMinorityInterest"])
    total_assets = get_row(bs, ["Total Assets", "TotalAssets"])
    debt_ratio, debt_ratio_y = avg_ratio(total_liab, total_assets, max_periods=5)
    if debt_ratio is None or debt_ratio >= 0.30:
        return None

    trailing_pe = info.get("trailingPE")
    if trailing_pe is None or trailing_pe >= 15:
        return None

    insider_pct = info.get("heldPercentInsiders")
    if insider_pct is None or insider_pct <= 0.30:
        return None

    total_revenue = get_row(fin, ["Total Revenue", "TotalRevenue"])
    rev_growth, rev_growth_y = avg_growth_rate(total_revenue, max_periods=3)
    if rev_growth is None or rev_growth <= 0.10:
        return None

    pretax = get_row(fin, ["Pretax Income", "Income Before Tax", "PretaxIncome"])
    pretax_growth, pretax_growth_y = avg_growth_rate(pretax, max_periods=3)
    if pretax_growth is None or pretax_growth <= 0.03:
        return None

    return [
        f"近{debt_ratio_y}年均負債比 {debt_ratio*100:.1f}%",
        f"本益比 {trailing_pe:.1f}",
        f"內部人持股 {insider_pct*100:.1f}%",
        f"近{rev_growth_y}年營收成長率均 {rev_growth*100:.1f}%",
        f"近{pretax_growth_y}年稅前純益成長率均 {pretax_growth*100:.1f}%",
    ]


# ============================================================
# 【班哲明格拉罕】
#   1. 近5年EPS皆>1元　2. 近3年流動比率皆>100%　3. 本益比<15倍
#   4. 近5年平均現金股利>3元　5. 近3年平均稅前純益成長率>3%
#   6. 近12月營收於母體同產業排名前40%
# ============================================================

def check_graham(bundle, revenue_percentile):
    fin, bs, info, dividends = bundle["fin"], bundle["bs"], bundle["info"], bundle["dividends"]

    eps_list = eps_recent_years(fin, 5)
    if eps_list is None or len(eps_list) < 3 or not all(e is not None and e > 1 for e in eps_list):
        return None

    cr_list = current_ratio_all_years(bs, 3)
    if cr_list is None or not all(r > 1.0 for r in cr_list):
        return None

    trailing_pe = info.get("trailingPE")
    if trailing_pe is None or trailing_pe >= 15:
        return None

    avg_div, div_years = avg_annual_dividend(dividends, 5)
    if avg_div is None or avg_div <= 3:
        return None

    pretax = get_row(fin, ["Pretax Income", "Income Before Tax", "PretaxIncome"])
    pretax_growth, pretax_growth_y = avg_growth_rate(pretax, max_periods=3)
    if pretax_growth is None or pretax_growth <= 0.03:
        return None

    if revenue_percentile is None or revenue_percentile < 0.60:  # 前40% <=> 百分位排名前60%以上
        return None

    return [
        f"近{len(eps_list)}年EPS皆>1",
        f"近{len(cr_list)}年流動比率皆>100%",
        f"本益比 {trailing_pe:.1f}",
        f"近{div_years}年均現金股利 {avg_div:.2f}",
        f"近{pretax_growth_y}年稅前純益成長率均 {pretax_growth*100:.1f}%",
        f"產業營收前{int((1-revenue_percentile)*100)+1}%",
    ]


def compute_ttm_revenue(bundle):
    """近12月營收：優先用近4季合計，抓不到就退回最新年度營收。"""
    qfin, fin = bundle["qfin"], bundle["fin"]
    rev_q = get_row(qfin, ["Total Revenue", "TotalRevenue"])
    if rev_q is not None and len(rev_q.dropna()) >= 4:
        return float(rev_q.dropna().iloc[:4].sum())
    total_revenue = get_row(fin, ["Total Revenue", "TotalRevenue"])
    if total_revenue is not None and len(total_revenue.dropna()) >= 1:
        return float(total_revenue.dropna().iloc[0])
    return None


def main():
    bundles = {}
    ttm_revenue = {}
    industry = {}

    print(f"Fetching bundles for {len(SCREENER_UNIVERSE)} tickers...", file=sys.stderr)
    for symbol, name in SCREENER_UNIVERSE.items():
        try:
            bundle = fetch_ticker_bundle(symbol)
            if bundle is None:
                print(f"[warn] {symbol}: no price data", file=sys.stderr)
                continue
            bundles[symbol] = bundle
            ttm_revenue[symbol] = compute_ttm_revenue(bundle)
            industry[symbol] = bundle["info"].get("industry")
        except Exception as e:
            print(f"[warn] {symbol}: {e}", file=sys.stderr)

    # ---- 產業營收百分位（只在本專案母體內排名，見檔頭說明）----
    industry_df = pd.DataFrame({
        "symbol": list(ttm_revenue.keys()),
        "revenue": list(ttm_revenue.values()),
        "industry": [industry.get(s) for s in ttm_revenue.keys()],
    }).dropna()
    percentile_by_symbol = {}
    if not industry_df.empty:
        industry_df["pct"] = industry_df.groupby("industry")["revenue"].rank(pct=True, ascending=True)
        for _, row in industry_df.iterrows():
            percentile_by_symbol[row["symbol"]] = row["pct"]

    results = {"buffett": [], "yockey": [], "murphy": [], "lynch": [], "graham": []}

    for symbol, name in SCREENER_UNIVERSE.items():
        bundle = bundles.get(symbol)
        if bundle is None:
            continue
        try:
            badges = check_buffett(symbol, bundle)
            if badges:
                r = base_result(symbol, name, bundle); r["badges"] = badges
                results["buffett"].append(r)
        except Exception as e:
            print(f"[warn] {symbol} [buffett]: {e}", file=sys.stderr)
        try:
            badges = check_yockey(bundle)
            if badges:
                r = base_result(symbol, name, bundle); r["badges"] = badges
                results["yockey"].append(r)
        except Exception as e:
            print(f"[warn] {symbol} [yockey]: {e}", file=sys.stderr)
        try:
            badges = check_murphy(bundle)
            if badges:
                r = base_result(symbol, name, bundle); r["badges"] = badges
                results["murphy"].append(r)
        except Exception as e:
            print(f"[warn] {symbol} [murphy]: {e}", file=sys.stderr)
        try:
            badges = check_lynch(bundle)
            if badges:
                r = base_result(symbol, name, bundle); r["badges"] = badges
                results["lynch"].append(r)
        except Exception as e:
            print(f"[warn] {symbol} [lynch]: {e}", file=sys.stderr)
        try:
            badges = check_graham(bundle, percentile_by_symbol.get(symbol))
            if badges:
                r = base_result(symbol, name, bundle); r["badges"] = badges
                results["graham"].append(r)
        except Exception as e:
            print(f"[warn] {symbol} [graham]: {e}", file=sys.stderr)

    total_matched = sum(len(v) for v in results.values())
    per_master_counts = ", ".join(f"{k}={len(v)}" for k, v in results.items())
    print(
        f"[info] 5位大師篩選完成：母體 {len(SCREENER_UNIVERSE)} 檔，"
        f"成功取得資料包 {len(bundles)} 檔，各大師符合檔數合計 {total_matched}（{per_master_counts}，"
        f"注意同一檔股票可能同時符合多位大師條件，此數字未去重）",
        file=sys.stderr,
    )

    # 健檢分析：用 common.py 裡共用的流程，依漲跌幅排序取每位大師前
    # FUNDAMENTALS_GEMINI_TOP_N 名才分析，並透過跨腳本共用的 data/gemini_cache.json 快取——
    # 如果 fetch_screener.py 今天稍早已經分析過同一檔股票，這裡會直接複用，不重打 Gemini。
    gemini_cache, cache_date = load_gemini_cache()
    run_gemini_health_check_pass(results, FUNDAMENTALS_GEMINI_TOP_N, gemini_cache)
    save_gemini_cache(gemini_cache, cache_date)

    master_sets = [
        {
            "id": "buffett", "name": "巴菲特", "status": "active",
            "description": "近5年平均ROE>15%；最新年度毛利率>40%；負債權益比<50%；連續5年自由現金流>0；本益比<15或低於其5年均值。（yfinance財報年限所限，實際檢核年數可能少於5年）" + UNIVERSE_NOTE,
            "results": results["buffett"],
        },
        {
            "id": "yockey", "name": "馬克約克奇", "status": "active",
            "description": "近12季毛利率平均>20%；近3年平均稅前純益成長率>3%。（yfinance免費季報通常抓不滿12季，實際採用季數見各標的badge標註）" + UNIVERSE_NOTE,
            "results": results["yockey"],
        },
        {
            "id": "murphy", "name": "麥克墨菲", "status": "active",
            "description": "近12季營業利益率平均>10%；近5年平均ROE>8%；近3年平均營收成長率>10%；近4季研發費用占營業額比率>5%。" + UNIVERSE_NOTE,
            "results": results["murphy"],
        },
        {
            "id": "lynch", "name": "彼得林區", "status": "active",
            "description": "近5年平均負債比<30%；本益比<15倍；內部人持股比例>30%（美股無質押比例公開資料，此項僅檢核持股比例）；近3年平均營收成長率>10%；近3年平均稅前純益成長率>3%。" + UNIVERSE_NOTE,
            "results": results["lynch"],
        },
        {
            "id": "graham", "name": "班哲明格拉罕", "status": "active",
            "description": "近5年EPS皆>1元；近3年流動比率皆>100%；本益比<15倍；近5年平均現金股利>3元；近3年平均稅前純益成長率>3%；近12月營收於母體同產業排名前40%（僅在本專案159檔母體內相對排名，非全市場排名）。" + UNIVERSE_NOTE,
            "results": results["graham"],
        },
    ]

    out = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "masterSets": master_sets,
    }
    with open("data/fundamentals.json", "w", encoding="utf-8") as f:
        # allow_nan=False：故意設成不允許 NaN，只要有任何欄位是 NaN 沒被 safe_round() 擋掉，
        # 這裡會直接丟例外讓這次 Action 執行失敗、在 log 看到明確錯誤，而不是安靜地寫出一份
        # 瀏覽器 JSON.parse() 解析不了的「無效但Python讀得懂」的檔案——那種問題會讓 Actions
        # log 顯示成功、實際上網頁整頁壞掉，非常難排查，寧可讓它在這裡就直接爆炸。
        json.dump(out, f, ensure_ascii=False, indent=2, allow_nan=False)
    print("Wrote data/fundamentals.json")


if __name__ == "__main__":
    main()
