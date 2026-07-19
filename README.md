# Market Dashboard

手機優先（RWD）的三頁籤股市儀表板，資料來源為 Yahoo Finance。

## 頁籤結構

| 頁籤 | 檔案 | 說明 |
|---|---|---|
| 1. 熱力圖 | `index.html` + `js/heatmap.js` | 仿 finviz.com/map 的 D3 squarified treemap，方塊大小＝市值（或成交量），顏色＝漲跌幅。頂部頁籤可切換 6 種市場 |
| 2. 強勢股選股 | `screener.html` + `js/screener.js` | 多組選股條件（頁籤切換），目前已實作 5 組：強勢股A、多頭股A、多頭股B、拉回轉強、突破區間 |
| 3. 基本面選股 | `fundamentals.html` + `js/fundamentals.js` | 5 位傳奇投資大師的量化選股條件（頁籤切換），目前只有「巴菲特」已實作，其餘 4 位為規劃中佔位 |

### 熱力圖的 6 種市場（對應 finviz.com/map 的 t 參數）

| finviz t 參數 | 顯示名稱 | 資料檔 |
|---|---|---|
| `sec_dji` | 道瓊 | `data/heatmap_dji.json` |
| `sec_ndx` | 那斯達克100 | `data/heatmap_ndx.json` |
| `sec` | S&P 500（預設） | `data/heatmap_sp500.json` |
| `etf` | ETF | `data/heatmap_etf.json` |
| `futures` | 期貨 | `data/heatmap_futures.json` |
| `crypto` | 加密貨幣 | `data/heatmap_crypto.json` |

`scripts/fetch_heatmap.py` 一次執行會產生全部 6 個 JSON。期貨、加密貨幣沒有市值概念，方塊大小改用成交量或固定權重。

### 強勢股選股 / 基本面選股的股票母體

這兩個頁籤共用同一份股票清單，定義在 `scripts/tickers.py`，由 4 個指數的成分股去重合併而成：

| 指數 | 檔數 | 完整度 |
|---|---|---|
| 道瓊工業平均 (DJI) | 30 | 完整名單 |
| S&P 500 | 50 | 精簡代表清單，非完整500檔 |
| 那斯達克100 (NDX) | 47 | 核心權值清單，非完整100檔 |
| 費城半導體指數 (SOX) | 30 | 完整名單 |
| **去重合併後** | **102** | — |

`fetch_screener.py` 跟 `fetch_fundamentals.py` 都是 `from tickers import SCREENER_UNIVERSE` 讀這份清單，兩邊不會各存一份、之後改一個忘了改另一個。`fetch_screener.py` 也做了效能優化：每檔股票的1年日線資料只抓一次，5組選股條件共用同一份資料各自判斷，不會每組條件各打一次 API。

三個頁面各自獨立、共用 `css/style.css` 與底部 tabbar，方便日後單獨優化或擴充其中一頁而不影響其他頁。

## 為什麼資料不是瀏覽器直接呼叫 Yahoo Finance API？

Yahoo Finance 的查詢端點在瀏覽器端會被 CORS 政策擋下，無法穩定地從前端直接 fetch。
因此採用你原本的架構模式：**GitHub Actions 定期執行 Python 腳本 → 產生靜態 JSON → 前端頁面 fetch 這份 JSON**（與 NVDA/TSM ADR dashboard、個股期貨動能排行頁相同做法）。

```
scripts/fetch_heatmap.py   → data/heatmap.json
scripts/fetch_screener.py  → data/screener.json
```

## 本機測試

```bash
pip install -r requirements.txt
python scripts/fetch_heatmap.py
python scripts/fetch_screener.py

# 啟動本機伺服器預覽（fetch() 需要 http(s) 協定，不能直接開檔案）
python -m http.server 8000
# 瀏覽器開啟 http://localhost:8000
```

## 部署到 GitHub Pages

1. 建立 repo（例如 `market-dashboard`），把整個資料夾內容 push 上去。
2. Settings → Pages → Source 選擇 `main` branch / root。
3. `.github/workflows/update-data.yml` 會依排程（美股盤中每小時、台股收盤後）自動重新抓資料並 commit，Pages 會自動重新部署。
4. 也可以到 Actions 頁籤手動觸發 `workflow_dispatch` 立即更新一次。

## 待辦 / 擴充方向

- [ ] `scripts/tickers.py`（強勢股選股／基本面選股共用的股票清單）目前是手動維護清單，S&P 500 / 那斯達克100 都只有精簡代表清單非完整版；道瓊、費城半導體指數(SOX) 則是完整名單。建議之後改成自動抓取最新成分股
- [ ] 之後要再新增第 6 組選股條件：在 `fetch_screener.py` 的 `main()` 內比照 `build_breakout_range()` 新增函式即可，前端不需改動
- [ ] 基本面選股目前只有「巴菲特」實作，其餘 4 位大師的選股條件待補充；補上後在 `fetch_fundamentals.py` 的 `main()` 內比照 `build_buffett()` 新增函式、取代對應的 `stub_master(...)` 即可，前端不需改動
- [ ] `fetch_fundamentals.py` 的基本面計算依賴 yfinance 免費財報資料，年度財報通常只有近4年（非精確5年）、「5年均值本益比」為簡化算法（假設EPS不變），細節見腳本開頭註解；如果需要更精確的歷史數據，可能要考慮串接付費財報 API
- [ ] 道瓊（30檔，完整）、那斯達克100（47檔核心權值股，非完整100檔）已依你提供的清單核對；S&P 500 / ETF / 期貨 / 加密貨幣目前仍是精簡代表清單（`scripts/fetch_heatmap.py` 裡的 `*_GROUPS`），如需涵蓋完整成分股，需另外取得成分股＋分類對照表
