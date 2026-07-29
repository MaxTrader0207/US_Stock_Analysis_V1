/* ============================================================
   AI特選股 — 綜合「強勢股選股」與「基本面選股」兩邊已完成AI健檢分析的股票，
   依健檢總分由高到低排序，最多顯示前10名。
   資料來源：data/ai_picks.json (由 scripts/fetch_fundamentals.py 的
   build_ai_picks() 產生，在該腳本 main() 最後一步整合兩邊資料寫出)。

   跟 screener.js / fundamentals.js 不同的地方：這裡沒有分頁籤（只有一個
   排序好的清單，不是「依條件分組」），所以沒有 renderTabs()、沒有搜尋框
   （名單本來就只有最多10檔，搜尋意義不大），卡片內容格式（A基本面/B技術面/
   C健檢分數三色區塊）則完全比照另外兩頁，欄位命名也完全一致。
   ============================================================ */
(function () {
  const descEl = document.getElementById("condition-desc");
  const listEl = document.getElementById("stock-list");
  const emptyEl = document.getElementById("empty");
  const updatedEl = document.getElementById("updated-meta");

  function fmtPct(p) {
    const v = p || 0;
    return (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
  }

  function renderList(results) {
    listEl.innerHTML = "";

    if (!results || !results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = `<strong>目前無資料</strong>強勢股選股／基本面選股兩邊目前都還沒有股票通過AI健檢分析，稍後再回來看看。`;
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

      // ---- C. 健檢分數（這頁的核心：能上榜代表分數一定不是null，不用處理analysisStatus）----
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

  fetch("data/ai_picks.json", { cache: "no-store" })
    .then(r => { if (!r.ok) throw new Error("no data"); return r.json(); })
    .then(data => {
      descEl.textContent = data.description || "";
      updatedEl.textContent = formatUpdated(data.updated);
      renderList(data.results || []);
    })
    .catch(() => {
      updatedEl.textContent = "";
      emptyEl.style.display = "block";
    });
})();
