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
    const height = Math.max(420, Math.round(window.innerHeight * 0.62));
    svg.attr("viewBox", `0 0 ${width} ${height}`).attr("width", width).attr("height", height);
    svg.selectAll("*").remove();

    const root = d3.hierarchy({ name: "root", children: data.sectors })
      .sum(d => d.marketCap || d.value || 1)
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
      if (w < 30 || h < 22) return;
      const g = d3.select(this);
      const fill = textColorFor(d.data.changePercent || 0);
      g.append("text")
        .attr("class", "sym")
        .attr("x", 6).attr("y", 16)
        .attr("font-size", Math.min(13, w / 5))
        .attr("fill", fill)
        .text(d.data.symbol);
      if (h > 36) {
        const pct = d.data.changePercent || 0;
        g.append("text")
          .attr("x", 6).attr("y", 30)
          .attr("font-size", Math.min(11, w / 6))
          .attr("fill", fill)
          .text((pct >= 0 ? "+" : "") + pct.toFixed(2) + "%");
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
