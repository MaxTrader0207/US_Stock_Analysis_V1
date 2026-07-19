# Market Dashboard

手機優先（RWD）的三頁籤股市儀表板，資料來源為 Yahoo Finance。

## 頁籤結構

| 頁籤 | 檔案 | 說明 |
|---|---|---|
| 1. 熱力圖 | `index.html` + `js/heatmap.js` | 仿 finviz.com/map 的 D3 squarified treemap，方塊大小＝市值（或成交量），顏色＝漲跌幅。頂部頁籤可切換 6 種市場 |
| 2. 強勢股選股 | `screener.html` + `js/screener.js` | 多組選股條件（頁籤切換），已實作條件一，條件二、三為預留擴充 |
| 3. 基本面選股（巴菲特選股法） | `fundamentals.html` | 目前為規劃草案頁，之後補上實際篩選邏輯 |

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

- [ ] `US_LARGE_CAP_TICKERS`（`scripts/fetch_screener.py`）目前是手動維護清單，建議之後改成自動抓取最新 S&P 500 / Nasdaq 100 成分股
- [ ] 選股條件二、三：在 `fetch_screener.py` 的 `main()` 內比照 `build_condition_1()` 新增函式即可，前端不需改動
- [ ] `fundamentals.html`：補上巴菲特式基本面篩選的實際抓取與計算邏輯（ROE、負債比、自由現金流等）
- [ ] 道瓊（30檔，完整）、那斯達克100（47檔核心權值股，非完整100檔）已依你提供的清單核對；S&P 500 / ETF / 期貨 / 加密貨幣目前仍是精簡代表清單（`scripts/fetch_heatmap.py` 裡的 `*_GROUPS`），如需涵蓋完整成分股，需另外取得成分股＋分類對照表
