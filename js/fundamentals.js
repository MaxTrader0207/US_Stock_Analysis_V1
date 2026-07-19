/* ============================================================
   基本面選股 — 5 位傳奇投資大師的量化選股條件（頁籤式）
   資料來源：data/fundamentals.json (由 scripts/fetch_fundamentals.py 產生)
   結構跟強勢股選股（screener.js）完全同一套模式：masterSets 陣列，
   之後新增大師只要在 JSON / fetch script 加一組，前端不需改動。
   ============================================================ */
(function () {
  const tabsEl = document.getElementById("master-tabs");
  const descEl = document.getElementById("condition-desc");
  const listEl = document.getElementById("stock-list");
  const emptyEl = document.getElementById("empty");
  const updatedEl = document.getElementById("updated-meta");

  let masterSets = [];
  let activeIdx = 0;

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

    if (!ms.results || !ms.results.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      empty.innerHTML = `<strong>${ms.status === "coming-soon" ? "規劃中" : "目前無符合標的"}</strong>${ms.status === "coming-soon" ? "這位大師的選股條件尚在開發，敬請期待。" : "目前沒有股票符合這套基本面篩選條件。"}`;
      listEl.appendChild(empty);
      return;
    }

    ms.results.forEach((s, i) => {
      const card = document.createElement("div");
      card.className = "stock-card";
      const badges = (s.badges || []).map(b => `<span class="badge">${b}</span>`).join("");
      card.innerHTML = `
        <span class="rank">${i + 1}</span>
        <div class="left">
          <div class="sym-row"><span class="sym">${s.symbol}</span><span class="name">${s.name || ""}</span></div>
          <div class="badges">${badges}</div>
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
