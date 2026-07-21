/* ============================================================
   強勢股選股 — 多組選股條件（頁籤式）
   資料來源：data/screener.json (由 scripts/fetch_screener.py 產生)
   結構刻意設計成 conditionSets 陣列，未來新增條件只需在
   JSON / fetch script 中新增一組，前端不需改動。
   ============================================================ */
(function () {
  const tabsEl = document.getElementById("condition-tabs");
  const descEl = document.getElementById("condition-desc");
  const listEl = document.getElementById("stock-list");
  const emptyEl = document.getElementById("empty");
  const updatedEl = document.getElementById("updated-meta");

  let conditionSets = [];
  let activeIdx = 0;

  function fmtPct(p) {
    const v = p || 0;
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }

  function renderTabs() {
    tabsEl.innerHTML = "";
    conditionSets.forEach((cs, i) => {
      const el = document.createElement("div");
      el.className = "pill" + (i === activeIdx ? " active" : "");
      el.textContent = cs.name + (cs.results && cs.results.length ? ` (${cs.results.length})` : "");
      el.addEventListener("click", () => { activeIdx = i; renderTabs(); renderList(); });
      tabsEl.appendChild(el);
    });
  }

  function renderList() {
    const cs = conditionSets[activeIdx];
    descEl.textContent = cs.description || "";
    listEl.innerHTML = "";

    if (!cs.results || !cs.results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = `<strong>${cs.status === "coming-soon" ? "規劃中" : "目前無符合標的"}</strong>${cs.status === "coming-soon" ? "此組選股條件尚在開發，敬請期待。" : "今日沒有股票符合此篩選條件。"}`;
      listEl.appendChild(empty);
      return;
    }

    cs.results.forEach((s, i) => {
      const card = document.createElement("div");
      card.className = "stock-card";
      const fmt = v => v != null ? v.toFixed(2) : "—";
      const fmtRevenue = v => {
        if (v == null) return "—";
        const abs = Math.abs(v);
        if (abs >= 1e9) return (v / 1e9).toFixed(2) + "B";
        if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
        return v.toLocaleString();
      };
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
        </div>`;
      listEl.appendChild(card);
    });
  }

  function formatUpdated(iso) {
    try {
      return "更新於 " + new Date(iso).toLocaleString("zh-TW", { hour12: false });
    } catch (e) { return ""; }
  }

  fetch("data/screener.json", { cache: "no-store" })
    .then(r => { if (!r.ok) throw new Error("no data"); return r.json(); })
    .then(data => {
      if (!data.conditionSets || !data.conditionSets.length) throw new Error("empty");
      conditionSets = data.conditionSets;
      updatedEl.textContent = formatUpdated(data.updated);
      renderTabs();
      renderList();
    })
    .catch(() => {
      updatedEl.textContent = "";
      emptyEl.style.display = "block";
    });
})();
