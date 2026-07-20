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
      const badges = (s.badges || []).map(b => `<span class="badge">${b}</span>`).join("");
      const fmt = v => v != null ? v.toFixed(2) : "—";
      const metricsLine1 = `10MA ${fmt(s.ma10)} · 30MA ${fmt(s.ma30)} · 乖離 ${s.bias30 != null ? (s.bias30 >= 0 ? "+" : "") + s.bias30.toFixed(2) + "%" : "—"}`;
      const metricsLine2 = `60MA ${fmt(s.ma60)} · 100MA ${fmt(s.ma100)}`;
      const metricsLine3 = `52週高 ${fmt(s.high52w)} · 52週低 ${fmt(s.low52w)} · RSI6 ${fmt(s.rsi6)}`;
      const commentHtml = s.comment ? `<div class="ai-comment"><span class="ai-tag">Gemini</span>${s.comment}</div>` : "";
      card.innerHTML = `
        <span class="rank">${i + 1}</span>
        <div class="left">
          <div class="sym-row"><span class="sym">${s.symbol}</span><span class="name">${s.name || ""}</span></div>
          <div class="badges">${badges}</div>
          <div class="metrics">${metricsLine1}</div>
          <div class="metrics">${metricsLine2}</div>
          <div class="metrics">${metricsLine3}</div>
          ${commentHtml}
        </div>
        <div class="right">
          <div class="price">${s.price != null ? s.price.toFixed(2) : "—"}</div>
          <div class="chg ${(s.changePercent || 0) >= 0 ? "up" : "down"}">${fmtPct(s.changePercent)}</div>
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
