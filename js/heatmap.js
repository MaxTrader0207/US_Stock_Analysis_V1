/* ============================================================
   熱力圖 — D3 squarified treemap，支援 6 種市場切換
   對應 finviz.com/map 的 6 個 t 參數：
     sec_dji  道瓊工業平均
     sec_ndx  那斯達克100
     sec      S&P 500（全市場，依板塊分組）
     etf      ETF
     futures  期貨
     crypto   加密貨幣
   資料來源：data/heatmap_<id>.json (由 scripts/fetch_heatmap.py 產生)
   ============================================================ */
(function () {
  const MAPS = [
    { id: "sec_dji", label: "道瓊", file: "data/heatmap_dji.json", title: "道瓊工業平均熱力圖" },
    { id: "sec_ndx", label: "那斯達克100", file: "data/heatmap_ndx.json", title: "那斯達克100熱力圖" },
    { id: "sec", label: "S&P 500", file: "data/heatmap_sp500.json", title: "S&P 500 熱力圖" },
    { id: "etf", label: "ETF", file: "data/heatmap_etf.json", title: "ETF 熱力圖" },
    { id: "futures", label: "期貨", file: "data/heatmap_futures.json", title: "期貨熱力圖" },
    { id: "crypto", label: "加密貨幣", file: "data/heatmap_crypto.json", title: "加密貨幣熱力圖" },
  ];

  const svg = d3.select("#treemap");
  const wrap = document.getElementById("heatmap-wrap");
  const sheet = document.getElementById("detail-sheet");
  const emptyEl = document.getElementById("empty");
  const updatedEl = document.getElementById("updated-meta");
  const tabsEl = document.getElementById("map-tabs");
  const titleEl = document.getElementById("map-title");

  let hideTimer = null;
  let activeIdx = 2; // 預設 S&P 500
  let currentData = null;
  let resizeT = null;

  function colorForChange(pct) {
    const clamped = Math.max(-3, Math.min(3, pct));
    const t = (clamped + 3) / 6; // 0..1
    const stops = [
      [255, 77, 106],   // red
      [58, 65, 80],      // neutral
      [0, 229, 160]       // green
    ];
    let seg = t < 0.5 ? 0 : 1;
    let localT = t < 0.5 ? t / 0.5 : (t - 0.5) / 0.5;
    const a = stops[seg], b = stops[seg + 1];
    const r = Math.round(a[0] + (b[0] - a[0]) * localT);
    const g = Math.round(a[1] + (b[1] - a[1]) * localT);
    const bch = Math.round(a[2] + (b[2] - a[2]) * localT);
    return `rgb(${r},${g},${bch})`;
  }

  function textColorFor(pct) {
    return Math.abs(pct) < 0.8 ? "#dbe2ec" : "#0a0e14";
  }

  function showDetail(d) {
    document.getElementById("d-sym").textContent = d.symbol;
    document.getElementById("d-name").textContent = d.name || d.symbol;
    document.getElementById("d-price").textContent = d.price != null ? d.price.toFixed(2) : "—";
    const chgEl = document.getElementById("d-chg");
    const pct = d.changePercent || 0;
    chgEl.textContent = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
    chgEl.className = "chg " + (pct >= 0 ? "up" : "down");
    sheet.classList.add("show");
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => sheet.classList.remove("show"), 4000);
  }

  function render(data) {
    const width = wrap.clientWidth;

    // 統計總格數，動態拉高畫布高度，確保平均每格有足夠空間顯示文字
    // （手機寬度有限，格數一多、市值差距一大，固定高度會讓小市值標的擠成無文字色塊）
    const leafCount = (data.sectors || []).reduce((n, s) => n + (s.children ? s.children.length : 0), 0);
    const minCellArea = 2200; // 約可容納「代號 + 漲跌幅」兩行文字的最小格子面積
    const areaBasedHeight = Math.ceil((leafCount * minCellArea) / Math.max(width, 1));
    const baseHeight = Math.max(420, Math.round(window.innerHeight * 0.62));
    const height = Math.max(baseHeight, areaBasedHeight);

    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("height", height);
    svg.selectAll("*").remove();

    // 用平方根壓縮市值差異：像加密貨幣這種頭部標的（BTC/ETH）市值是長尾標的的數百倍，
    // 直接按市值分配面積會讓長尾標的完全擠不出可顯示文字的空間；開根號後大小差距會
    // 大幅收斂，讓每個標的至少保有可辨識的區塊，同時仍保留「越大市值方塊越大」的排序感。
    const root = d3.hierarchy({ name: "root", children: data.sectors })
      .sum(d => Math.sqrt(Math.max(d.marketCap || d.value || 1, 0.01)))
      .sort((a, b) => b.value - a.value);

    d3.treemap()
      .tile(d3.treemapSquarify)
      .size([width, height])
      .paddingOuter(4)
      .paddingTop(18)
      .paddingInner(2)
      .round(true)(root);

    const sectors = svg.selectAll("g.sector")
      .data(root.children)
      .join("g")
      .attr("class", "sector");

    sectors.append("text")
      .attr("class", "sector-label")
      .attr("x", d => d.x0 + 4)
      .attr("y", d => d.y0 + 12)
      .attr("font-size", 10)
      .text(d => d.data.name);

    const leaves = root.leaves();
    const cell = svg.selectAll("g.cell")
      .data(leaves)
      .join("g")
      .attr("class", "cell")
      .attr("transform", d => `translate(${d.x0},${d.y0})`)
      .on("click", (event, d) => showDetail(d.data))
      .on("touchstart", (event, d) => showDetail(d.data), { passive: true });

    cell.append("rect")
      .attr("width", d => Math.max(0, d.x1 - d.x0))
      .attr("height", d => Math.max(0, d.y1 - d.y0))
      .attr("fill", d => colorForChange(d.data.changePercent || 0))
      .attr("rx", 3);

    cell.each(function (d) {
      const w = d.x1 - d.x0, h = d.y1 - d.y0;
      const g = d3.select(this);
      const fill = textColorFor(d.data.changePercent || 0);
      if (w < 14 || h < 10) return; // 小到連一個字都放不下才整格留白

      const symbol = d.data.symbol || "";
      const pct = d.data.changePercent || 0;
      const pctText = (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
      const symLen = Math.max(2, symbol.length);

      // 方案一：格子夠高，代號跟漲跌幅分兩行顯示（原本的排版，字比較大、最好讀）
      const twoLineSymSize = Math.max(6.5, Math.min(13, (w - 4) / (symLen * 0.62), h / 2.6));
      const twoLineNeedH = twoLineSymSize * 2 + 10;
      if (h >= twoLineNeedH && w >= 22) {
        const pctSize = Math.max(6.5, Math.min(11, w / 6, twoLineSymSize - 1));
        g.append("text").attr("class", "sym")
          .attr("x", 4).attr("y", twoLineSymSize + 2)
          .attr("font-size", twoLineSymSize).attr("fill", fill)
          .text(symbol);
        g.append("text")
          .attr("x", 4).attr("y", twoLineSymSize + pctSize + 6)
          .attr("font-size", pctSize).attr("fill", fill)
          .text(pctText);
        return;
      }

      // 方案二：格子矮但不算窄（常見於同一列擠了很多格子時），
      // 改成同一行顯示「代號 漲跌幅」，寧可字小一點也要讓漲跌幅露出來。
      // 空間真的很緊時，漲跌幅先降成 1 位小數，省字元換取塞進去的機會。
      const pctTextShort = (pct >= 0 ? "+" : "") + pct.toFixed(1) + "%";
      let combined = symbol + " " + pctText;
      let oneLineSize = Math.max(5.5, Math.min(11, (w - 4) / (combined.length * 0.58), h - 3));
      if (oneLineSize < 6.2) {
        // 完整兩位小數塞不太下，改用縮短版再試一次
        combined = symbol + " " + pctTextShort;
        oneLineSize = Math.max(5.5, Math.min(11, (w - 4) / (combined.length * 0.58), h - 3));
      }
      if (oneLineSize >= 5.5 && w >= 20 && h >= 10) {
        g.append("text")
          .attr("x", 3).attr("y", Math.min(h - 2, oneLineSize + 1))
          .attr("font-size", oneLineSize).attr("fill", fill)
          .text(combined);
        return;
      }

      // 方案三：真的太小，只放代號（不縮寫、不加漲跌幅）
      const symOnlySize = Math.max(5.5, Math.min(11, (w - 3) / (symLen * 0.6), h - 3));
      if (symOnlySize >= 5.5) {
        g.append("text")
          .attr("x", 3).attr("y", Math.min(h - 3, symOnlySize + 1))
          .attr("font-size", symOnlySize).attr("fill", fill)
          .text(symbol);
      }
    });
  }


  function formatUpdated(iso) {
    try {
      return "更新於 " + new Date(iso).toLocaleString("zh-TW", { hour12: false });
    } catch (e) { return ""; }
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    MAPS.forEach((m, i) => {
      const el = document.createElement("div");
      el.className = "pill" + (i === activeIdx ? " active" : "");
      el.textContent = m.label;
      el.addEventListener("click", () => {
        if (i === activeIdx) return;
        activeIdx = i;
        renderTabs();
        loadMap();
      });
      tabsEl.appendChild(el);
    });
  }

  function loadMap() {
    const m = MAPS[activeIdx];
    titleEl.textContent = m.title;
    emptyEl.style.display = "none";
    updatedEl.textContent = "載入中…";
    svg.selectAll("*").remove();
    currentData = null;

    fetch(m.file, { cache: "no-store" })
      .then(r => { if (!r.ok) throw new Error("no data"); return r.json(); })
      .then(data => {
        if (!data.sectors || !data.sectors.length) throw new Error("empty");
        currentData = data;
        updatedEl.textContent = formatUpdated(data.updated);
        render(data);
      })
      .catch(() => {
        updatedEl.textContent = "";
        emptyEl.style.display = "block";
      });
  }

  window.addEventListener("resize", () => {
    clearTimeout(resizeT);
    resizeT = setTimeout(() => { if (currentData) render(currentData); }, 150);
  });

  renderTabs();
  loadMap();
})();
