#!/usr/bin/env python3
"""
共用股票清單，給強勢股選股 (fetch_screener.py) 與基本面選股 (fetch_fundamentals.py) 共用，
避免同一份清單在兩個檔案裡各放一份、之後改一個忘了改另一個。

依你的需求，選股母體改為合併「道瓊工業平均」「S&P 500」「那斯達克100」「費城半導體指數(SOX)」
四個指數的成分股（去重後合併成一份清單）。

各清單的資料來源與限制：
- DJI_TICKERS：道瓊 30 檔，完整名單（依你上傳文件核對過）。
- NDX_CORE_TICKERS：那斯達克100，101 檔完整名單（依你上傳的「那斯達克100指數.xlsx」核對，
  完整版含 GOOGL/GOOG 兩種股票類別，故是101檔而非100檔）。
- SP500_CORE_TICKERS：S&P 500 依權重排序前 71 檔（依你上傳的「s_P_500.xlsx」核對，
  該檔案本身只列到權重前70名，其中 WDC/SNDK 為同一列的兩檔股票分拆列出，故為71檔），
  不是完整 500 檔——若要涵蓋完整 500 檔，需要額外的成分股清單資料源。
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
    "AAPL": "Apple Inc.", "ABNB": "Airbnb, Inc.", "ADBE": "Adobe Inc.",
    "ADI": "Analog Devices", "ADP": "Automatic Data Processing", "ADSK": "Autodesk",
    "AEP": "American Electric Power", "ALAB": "Astera Labs", "ALNY": "Alnylam Pharmaceuticals",
    "AMAT": "Applied Materials", "AMD": "Advanced Micro Devices", "AMGN": "Amgen",
    "AMZN": "Amazon.com Inc.", "APP": "AppLovin Corp.", "ARM": "Arm Holdings plc",
    "ASML": "ASML Holding N.V.", "AVGO": "Broadcom Inc.", "AXON": "Axon Enterprise",
    "BKNG": "Booking Holdings", "BKR": "Baker Hughes", "CCEP": "Coca-Cola Europacific Partners",
    "CDNS": "Cadence Design Systems", "CEG": "Constellation Energy", "CMCSA": "Comcast Corp.",
    "COST": "Costco Wholesale", "CPRT": "Copart, Inc.", "CRWD": "CrowdStrike Holdings",
    "CRWV": "CoreWeave, Inc.", "CSCO": "Cisco Systems", "CSX": "CSX Corporation",
    "CTAS": "Cintas Corp.", "DASH": "DoorDash, Inc.", "DDOG": "Datadog Inc.",
    "DXCM": "DexCom", "EA": "Electronic Arts", "EXC": "Exelon Corp.",
    "FANG": "Diamondback Energy", "FAST": "Fastenal Co.", "FER": "Ferrovial N.V.",
    "FTNT": "Fortinet, Inc.", "GEHC": "GE HealthCare", "GILD": "Gilead Sciences",
    "GOOG": "Alphabet Inc.", "GOOGL": "Alphabet Inc.", "HON": "Honeywell International",
    "IDXX": "IDEXX Laboratories", "INTC": "Intel Corp.", "INTU": "Intuit Inc.",
    "ISRG": "Intuitive Surgical", "KDP": "Keurig Dr Pepper", "KHC": "Kraft Heinz Co.",
    "KLAC": "KLA Corporation", "LIN": "Linde plc", "LITE": "Lumentum Holdings",
    "LRCX": "Lam Research", "MAR": "Marriott International", "MCHP": "Microchip Technology",
    "MDLZ": "Mondelez International", "MELI": "MercadoLibre, Inc.", "META": "Meta Platforms",
    "MNST": "Monster Beverage", "MPWR": "Monolithic Power Systems", "MRVL": "Marvell Technology",
    "MSFT": "Microsoft Corp.", "MSTR": "MicroStrategy", "MU": "Micron Technology",
    "NBIS": "Nebius Group N.V.", "NFLX": "Netflix, Inc.", "NVDA": "NVIDIA Corporation",
    "NXPI": "NXP Semiconductors", "ODFL": "Old Dominion Freight Line", "ORLY": "O'Reilly Automotive",
    "PANW": "Palo Alto Networks", "PAYX": "Paychex, Inc.", "PCAR": "PACCAR Inc.",
    "PDD": "PDD Holdings", "PEP": "PepsiCo Inc.", "PLTR": "Palantir Technologies",
    "PYPL": "PayPal Holdings", "QCOM": "QUALCOMM Inc.", "REGN": "Regeneron Pharmaceuticals",
    "RKLB": "Rocket Lab", "ROP": "Roper Technologies", "ROST": "Ross Stores",
    "SBUX": "Starbucks Corp.", "SHOP": "Shopify, Inc.", "SNPS": "Synopsys, Inc.",
    "STX": "Seagate Technology", "TEAM": "Atlassian", "TER": "Teradyne, Inc.",
    "TMUS": "T-Mobile US", "TRI": "Thomson Reuters", "TSLA": "Tesla, Inc.",
    "TTWO": "Take-Two Interactive", "TXN": "Texas Instruments", "VRTX": "Vertex Pharmaceuticals",
    "WBD": "Warner Bros. Discovery", "WDAY": "Workday, Inc.", "WDC": "Western Digital",
    "WMT": "Walmart Inc.", "XEL": "Xcel Energy",
}

SP500_CORE_TICKERS = {
    "NVDA": "NVIDIA", "AAPL": "Apple", "MSFT": "Microsoft",
    "AMZN": "Amazon", "GOOGL": "Alphabet", "GOOG": "Alphabet",
    "AVGO": "Broadcom", "META": "Meta Platforms", "TSLA": "Tesla",
    "BRK-B": "Berkshire Hathaway", "LLY": "Eli Lilly", "MU": "Micron Technology",
    "WMT": "Walmart", "JPM": "JPMorgan Chase", "AMD": "Advanced Micro Devices",
    "V": "Visa", "XOM": "Exxon Mobil", "JNJ": "Johnson & Johnson",
    "MA": "Mastercard", "INTC": "Intel", "ABBV": "AbbVie",
    "CSCO": "Cisco Systems", "BAC": "Bank of America", "AMAT": "Applied Materials",
    "COST": "Costco Wholesale", "CAT": "Caterpillar", "LRCX": "Lam Research",
    "UNH": "UnitedHealth Group", "CVX": "Chevron", "ORCL": "Oracle",
    "GE": "GE Aerospace", "KO": "Coca-Cola", "PG": "Procter & Gamble",
    "MS": "Morgan Stanley", "HD": "Home Depot", "PLTR": "Palantir Technologies",
    "MRK": "Merck & Co", "GS": "Goldman Sachs", "PM": "Philip Morris",
    "PANW": "Palo Alto Networks", "NFLX": "Netflix", "GEV": "GE Vernova",
    "KLAC": "KLA Corp", "WFC": "Wells Fargo", "RTX": "RTX Corp",
    "TXN": "Texas Instruments", "DELL": "Dell Technologies", "AXP": "American Express",
    "LIN": "Linde", "C": "Citigroup", "ANET": "Arista Networks",
    "TMUS": "T-Mobile US", "CRWD": "Crowdstrike Holdings", "WDC": "Western Digital",
    "SNDK": "SanDisk", "IBM": "IBM", "TMO": "Thermo Fisher Scientific",
    "AMGN": "Amgen", "MCD": "McDonald's", "PEP": "PepsiCo",
    "APH": "Amphenol", "NEE": "NextEra Energy", "ADI": "Analog Devices",
    "VZ": "Verizon", "QCOM": "QUALCOMM", "UNP": "Union Pacific",
    "STX": "Seagate Technology", "SCHW": "Charles Schwab", "ABT": "Abbott Laboratories",
    "WELL": "Welltower", "TJX": "TJX Companies",
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
