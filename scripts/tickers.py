#!/usr/bin/env python3
"""
共用股票清單，給強勢股選股 (fetch_screener.py) 與基本面選股 (fetch_fundamentals.py) 共用，
避免同一份清單在兩個檔案裡各放一份、之後改一個忘了改另一個。

依你的需求，選股母體改為合併「道瓊工業平均」「S&P 500」「那斯達克100」「費城半導體指數(SOX)」
四個指數的成分股（去重後合併成一份清單）。

各清單的資料來源與限制：
- DJI_TICKERS：道瓊 30 檔，完整名單（依你上傳文件核對過）。
- NDX_CORE_TICKERS：那斯達克100 的核心／權重最高成分股（47檔），不是完整 100 檔
  （依你上傳文件核對過，文件本身也說明是核心清單，非完整版）。
- SP500_CORE_TICKERS：S&P 500 精簡代表清單（50檔），不是完整 500 檔——
  抓完整 500 檔成分股需要額外的成分股清單資料源，目前用大型權值股當代表。
- SOX_TICKERS：費城半導體指數 30 檔，完整名單（2026/5/1 Nasdaq 官方公告權重表）。

SCREENER_UNIVERSE 是以上四份清單去重合併後的結果，是強勢股選股／基本面選股
兩個頁籤實際掃描的股票母體。
"""

DJI_TICKERS = {
    "AAPL": "Apple", "CSCO": "Cisco", "IBM": "IBM", "MSFT": "Microsoft", "NVDA": "NVIDIA",
    "CRM": "Salesforce", "AXP": "American Express", "GS": "Goldman Sachs", "JPM": "JPMorgan Chase",
    "TRV": "Travelers", "V": "Visa", "AMGN": "Amgen", "JNJ": "Johnson & Johnson", "MRK": "Merck",
    "UNH": "UnitedHealth", "AMZN": "Amazon", "HD": "Home Depot", "MCD": "McDonald's", "NKE": "Nike",
    "MMM": "3M", "BA": "Boeing", "CAT": "Caterpillar", "HON": "Honeywell", "GOOGL": "Alphabet",
    "DIS": "Disney", "KO": "Coca-Cola", "PG": "Procter & Gamble", "WMT": "Walmart",
    "CVX": "Chevron", "SHW": "Sherwin-Williams",
}

NDX_CORE_TICKERS = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "AVGO": "Broadcom", "AMD": "AMD",
    "ASML": "ASML", "AMAT": "Applied Materials", "QCOM": "Qualcomm", "TXN": "Texas Instruments",
    "NXPI": "NXP Semiconductors", "MU": "Micron", "ARM": "Arm Holdings", "LRCX": "Lam Research",
    "ADI": "Analog Devices", "MCHP": "Microchip Technology", "ADBE": "Adobe", "INTU": "Intuit",
    "CRWD": "CrowdStrike", "PANW": "Palo Alto Networks", "DDOG": "Datadog", "WDAY": "Workday",
    "TEAM": "Atlassian", "CDNS": "Cadence", "SNPS": "Synopsys", "GOOGL": "Alphabet A",
    "GOOG": "Alphabet C", "META": "Meta Platforms", "NFLX": "Netflix", "AMZN": "Amazon",
    "TSLA": "Tesla", "COST": "Costco", "SBUX": "Starbucks", "PEP": "PepsiCo", "BKNG": "Booking Holdings",
    "ABNB": "Airbnb", "MAR": "Marriott", "LULU": "Lululemon", "KHC": "Kraft Heinz",
    "ORLY": "O'Reilly Auto", "CTAS": "Cintas", "VRTX": "Vertex", "GILD": "Gilead",
    "ISRG": "Intuitive Surgical", "REGN": "Regeneron", "MRNA": "Moderna", "AZN": "AstraZeneca",
    "GEHC": "GE HealthCare",
}

SP500_CORE_TICKERS = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "NVIDIA", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom", "BRK-B": "Berkshire Hathaway",
    "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard", "LLY": "Eli Lilly", "UNH": "UnitedHealth",
    "JNJ": "Johnson & Johnson", "XOM": "Exxon Mobil", "CVX": "Chevron", "HD": "Home Depot",
    "PG": "Procter & Gamble", "COST": "Costco", "ORCL": "Oracle", "ABBV": "AbbVie", "MRK": "Merck",
    "KO": "Coca-Cola", "PEP": "PepsiCo", "ADBE": "Adobe", "CRM": "Salesforce", "NFLX": "Netflix",
    "AMD": "AMD", "CSCO": "Cisco", "TMO": "Thermo Fisher", "MCD": "McDonald's", "ABT": "Abbott Labs",
    "WMT": "Walmart", "BAC": "Bank of America", "PFE": "Pfizer", "DIS": "Disney", "NKE": "Nike",
    "TMUS": "T-Mobile", "CAT": "Caterpillar", "GE": "GE Aerospace", "IBM": "IBM", "QCOM": "Qualcomm",
    "TXN": "Texas Instruments", "INTC": "Intel", "NOW": "ServiceNow", "AMAT": "Applied Materials",
    "INTU": "Intuit", "BA": "Boeing", "HON": "Honeywell",
}

SOX_TICKERS = {
    "AMD": "Advanced Micro Devices", "ADI": "Analog Devices", "AMAT": "Applied Materials",
    "ARM": "Arm Holdings", "ASML": "ASML Holding", "ALAB": "Astera Labs", "AVGO": "Broadcom",
    "COHR": "Coherent", "CRDO": "Credo Technology", "ENTG": "Entegris", "GFS": "GlobalFoundries",
    "INTC": "Intel", "KLAC": "KLA Corporation", "LRCX": "Lam Research", "MTSI": "MACOM Technology",
    "MRVL": "Marvell Technology", "MCHP": "Microchip Technology", "MU": "Micron Technology",
    "MPWR": "Monolithic Power Systems", "NVMI": "Nova Ltd", "NVDA": "NVIDIA",
    "NXPI": "NXP Semiconductors", "ON": "ON Semiconductor", "QRVO": "Qorvo", "QCOM": "Qualcomm",
    "RMBS": "Rambus", "SWKS": "Skyworks Solutions", "TSM": "Taiwan Semiconductor", "TER": "Teradyne",
    "TXN": "Texas Instruments",
}

# 四份清單去重合併，後面的字典若有重複 key 會覆蓋前面的（名稱基本一致，不影響）
SCREENER_UNIVERSE = {}
for _table in (DJI_TICKERS, NDX_CORE_TICKERS, SP500_CORE_TICKERS, SOX_TICKERS):
    SCREENER_UNIVERSE.update(_table)
