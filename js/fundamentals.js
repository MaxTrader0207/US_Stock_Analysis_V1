/* ============================================================
   基本面選股 — 5 位傳奇投資大師的量化選股條件（頁籤式）
   資料來源：data/fundamentals.json (由 scripts/fetch_fundamentals.py 產生)
   卡片版型跟強勢股選股（screener.js）完全同一套三色區塊格式
   （A基本面藍色/B技術面琥珀色/C健檢分數紫色），欄位命名也完全一致，
   兩個頁面共用同一份 style.css，不需要另外加樣式。
   ============================================================ */
(function () {
  const tabsEl = document.getElementById("master-tabs");
  const descEl = document.getElementById("condition-desc");
  const listEl = document.getElementById("stock-list");
  const emptyEl = document.getElementById("empty");
  const updatedEl = document.getElementById("updated-meta");

  let masterSets = [];
  let activeIdx = 0;
  let searchTerm = "";

  // 搜尋框是用 JS 動態插入的（不需要改 HTML），插在 tabs 跟條件說明中間
  const searchWrap = document.createElement("div");
  searchWrap.className = "search-box-wrap";
  searchWrap.innerHTML = `
    <div class="search-box">
      <input type="text" id="stock-search-input" placeholder="搜尋代號或公司名稱..." autocomplete="off" />
      <button type="button" class="clear-btn" aria-label="清除搜尋">✕</button>
    </div>
    <div class="search-result-count" id="stock-search-count"></div>
  `;
  tabsEl.insertAdjacentElement("afterend", searchWrap);
  const searchInput = searchWrap.querySelector("input");
  const searchBoxEl = searchWrap.querySelector(".search-box");
  const clearBtn = searchWrap.querySelector(".clear-btn");
  const searchCountEl = searchWrap.querySelector("#stock-search-count");

  searchInput.addEventListener("input", () => {
    searchTerm = searchInput.value.trim().toUpperCase();
    searchBoxEl.classList.toggle("has-value", searchTerm.length > 0);
    renderList();
  });
  clearBtn.addEventListener("click", () => {
    searchInput.value = "";
    searchTerm = "";
    searchBoxEl.classList.remove("has-value");
    renderList();
    searchInput.focus();
  });

  function matchesSearch(s) {
    if (!searchTerm) return true;
    const sym = (s.symbol || "").toUpperCase();
    const name = (s.name || "").toUpperCase();
    return sym.includes(searchTerm) || name.includes(searchTerm);
  }

  function fmtPct(p) {
    const v = p || 0;
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    masterSets.forEach((ms, i) => {
      const el = document.createElement("div");
      el.className = "pill" + (i === activeIdx ? " active" : "");
      el.textContent = ms.name + (ms.results && ms.results.length ? ` (${ms.results.length})` : "");
      el.addEventListener("click", () => { activeIdx = i; renderTabs(); renderList(); });
      tabsEl.appendChild(el);
    });
  }

  function renderList() {
    const ms = masterSets[activeIdx];
    descEl.textContent = ms.description || "";
    listEl.innerHTML = "";

    const allResults = ms.results || [];
    const results = allResults.filter(matchesSearch);

    if (searchTerm) {
      searchCountEl.textContent = `符合「${searchInput.value.trim()}」：${results.length} / ${allResults.length} 檔`;
    } else {
      searchCountEl.textContent = "";
    }

    if (!allResults.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = `<strong>${ms.status === "coming-soon" ? "規劃中" : "目前無符合標的"}</strong>${ms.status === "coming-soon" ? "這位大師的選股條件尚在開發，敬請期待。" : "目前沒有股票符合這套基本面篩選條件。"}`;
      listEl.appendChild(empty);
      return;
    }

    if (!results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = `<strong>找不到符合的股票</strong>試試其他代號或公司名稱關鍵字。`;
      listEl.appendChild(empty);
      return;
    }

    results.forEach((s, i) => {
      const card = document.createElement("div");
      card.className = "stock-card";
      const fmt = v => v != null ? v.toFixed(2) : "—";
      const fmtPct2 = v => v != null ? (v >= 0 ? "+" : "") + v.toFixed(2) + "%" : "—";

      // ---- A. 基本面 ----
      const fundMetrics = `EPS ${fmt(s.eps)} · ROE ${s.roe != null ? s.roe.toFixed(2) + "%" : "—"} · P/E ${fmt(s.pe)} · 殖利率 ${s.dividendYield != null ? s.dividendYield.toFixed(2) + "%" : "—"}`;
      const fundComment = s.fundamentalComment ? `<div class="sec-comment">${s.fundamentalComment}</div>` : "";

      // ---- B. 技術面：站上/跌破 + 上揚/下彎箭頭 ----
      const maLine = (label, above, rising, extra) => {
        if (above == null || rising == null) return `<div class="ma-row">${label}：無資料</div>`;
        const posCls = above ? "ma-above" : "ma-below";
        const posText = above ? "站上" : "跌破";
        const arrow = rising ? "▲" : "▼";
        const trendCls = rising ? "ma-up" : "ma-down";
        return `<div class="ma-row"><span class="ma-label">${label}</span><span class="${posCls}">${posText}</span><span class="${trendCls}">${arrow}</span>${extra || ""}</div>`;
      };
      const ma30Line = maLine("30MA", s.above30, s.ma30Rising, ` <span class="ma-bias">乖離 ${fmtPct2(s.bias30)}</span>`);
      const ma60Line = maLine("60MA", s.above60, s.ma60Rising);
      const ma100Line = maLine("100MA", s.above100, s.ma100Rising);
      const techComment = s.technicalComment ? `<div class="sec-comment">${s.technicalComment}</div>` : "";

      // ---- C. 健檢分數 ----
      const total = s.totalScore;
      const scoreTierCls = total == null ? "" : (total >= 70 ? "score-high" : total >= 40 ? "score-mid" : "score-low");
      const overallComment = s.overallComment ? `<div class="sec-comment">${s.overallComment}</div>` : "";
      const scoreRow = total != null
        ? `<div class="score-row"><span class="score-value ${scoreTierCls}">${total}</span><span class="score-max">/100</span></div>`
        : `<div class="score-row"><span class="score-value">—</span></div>`;
      // totalScore是null時，區分「本來就沒排進分析名單」跟「有排進去但AI分析失敗」，
      // 不然使用者看到的都只是一個「—」，分不出來是正常還是壞掉，容易誤以為故障來詢問
      let statusNote = "";
      if (total == null) {
        if (s.analysisStatus === "not_targeted") {
          statusNote = `<div class="status-note">未進入分析名單（僅前段排名股票會有AI健檢）</div>`;
        } else if (s.analysisStatus === "failed") {
          statusNote = `<div class="status-note status-note-warn">AI分析暫時失敗，下次更新會再嘗試</div>`;
        }
      }

      card.innerHTML = `
        <span class="rank">${i + 1}</span>
        <div class="card-header">
          <div class="head-left">
            <div class="sym-row"><span class="sym">${s.symbol}</span><span class="name">${s.name || ""}</span></div>
          </div>
          <div class="head-right">
            <div class="price">${s.price != null ? s.price.toFixed(2) : "—"}</div>
            <div class="chg ${(s.changePercent || 0) >= 0 ? "up" : "down"}">${fmtPct(s.changePercent)}</div>
          </div>
        </div>

        <div class="sec sec-fundamental">
          <div class="sec-title">A. 基本面</div>
          <div class="sec-metrics">${fundMetrics}</div>
          ${fundComment}
        </div>

        <div class="sec sec-technical">
          <div class="sec-title">B. 技術面</div>
          ${ma30Line}
          ${ma60Line}
          ${ma100Line}
          ${techComment}
        </div>

        <div class="sec sec-score">
          <div class="sec-title">C. 健檢分數</div>
          ${overallComment}
          ${scoreRow}
          ${statusNote}
        </div>`;
      listEl.appendChild(card);
    });
  }

  function formatUpdated(iso) {
    try {
      return "更新於 " + new Date(iso).toLocaleString("zh-TW", { hour12: false });
    } catch (e) { return ""; }
  }

  fetch("data/fundamentals.json", { cache: "no-store" })
    .then(r => { if (!r.ok) throw new Error("no data"); return r.json(); })
    .then(data => {
      if (!data.masterSets || !data.masterSets.length) throw new Error("empty");
      masterSets = data.masterSets;
      updatedEl.textContent = formatUpdated(data.updated);
      renderTabs();
      renderList();
    })
    .catch(() => {
      updatedEl.textContent = "";
      emptyEl.style.display = "block";
    });
})();
