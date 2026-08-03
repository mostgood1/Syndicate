// Portfolio live pulse, added 2026-08-03 (Phase 3). /portfolio was 100%
// server-rendered with zero client-side JS (see the comment on
// portfolio_bet_delete in syndicate/blueprints/intelligence.py) -- correct
// for a page with no interactive actions, but it meant a bet settling or a
// new position being logged never showed up without a manual reload. This
// polls the /api/portfolio/summary endpoint the page's own initial render
// already uses and re-renders the same sections in place.
//
// Every render function below reproduces one block of portfolio.html's
// Jinja template exactly (same number formatting, same conditional
// show/hide) so a live-refreshed page is indistinguishable from a freshly
// server-rendered one. The delete form stays a plain HTML POST -- a rare,
// deliberate action, not worth an AJAX round trip for this pass.
window.SyndicatePortfolioPulse = (function () {
  "use strict";

  const SUMMARY_ENDPOINT = "/api/portfolio/summary?limit=100";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  function isNum(value) {
    return typeof value === "number" && Number.isFinite(value);
  }

  // Mirrors Jinja "%.1f%%"|format(value * 100) -- no sign.
  function pct1(value) {
    return isNum(value) ? `${(value * 100).toFixed(1)}%` : "—";
  }

  // Mirrors Jinja "%.0f%%"|format(value * 100) -- no sign.
  function pct0(value) {
    return isNum(value) ? `${Math.round(value * 100)}%` : "—";
  }

  // Mirrors Jinja "%+.1f%%"|format(value * 100) -- explicit sign, including +0.0.
  function pctSigned1(value) {
    if (!isNum(value)) return "—";
    const scaled = value * 100;
    return `${scaled >= 0 ? "+" : ""}${scaled.toFixed(1)}%`;
  }

  // Mirrors Jinja "%+.2f"|format(value) -- explicit sign.
  function signed2(value) {
    return isNum(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(2)}` : "—";
  }

  function usd(value) {
    return isNum(value) ? `$${value.toFixed(2)}` : "—";
  }

  function num0(value) {
    return isNum(value) ? `${Math.round(value)}` : "—";
  }

  function roiClass(value) {
    if (!isNum(value) || value === 0) return "";
    return value > 0 ? " pos" : " neg";
  }

  function renderNote(summary) {
    const el = document.getElementById("portfolio-note");
    if (!el) return;
    const settledCount = summary.settled_count || 0;
    if (settledCount > 0) {
      el.hidden = true;
      return;
    }
    const tracked = summary.total_tracked || 0;
    el.hidden = false;
    el.textContent = `Awaiting grading -- ${tracked} tracked play${tracked === 1 ? "" : "s"}, 0 settled yet. Win rate, ROI, and CLV populate once reconciliation grades results.`;
  }

  function renderTiles(summary) {
    const container = document.getElementById("portfolio-tiles");
    if (!container) return;
    const tiles = [
      { label: "Tracked plays", value: String(summary.total_tracked || 0), meta: `${summary.today_count || 0} today` },
      { label: "Open / pending", value: String(summary.pending_count || 0), meta: "awaiting settlement" },
      { label: "Settled", value: String(summary.settled_count || 0), meta: `${summary.decisive_count || 0} decisive (win/loss)` },
      { label: "Win rate", value: pct1(summary.win_rate), meta: "of decisive settled plays" },
      { label: "ROI", value: pctSigned1(summary.roi), meta: "settled P/L per unit staked", valueClass: roiClass(summary.roi) },
      { label: "Avg edge (open)", value: pct1(summary.avg_edge), meta: "across all tracked plays" },
      { label: "Avg CLV", value: signed2(summary.avg_clv), meta: "closing line value, settled" },
    ];
    container.innerHTML = tiles.map((tile) => `
      <div class="portfolio-tile">
        <div class="portfolio-tile__label">${escapeHtml(tile.label)}</div>
        <div class="portfolio-tile__value${tile.valueClass || ""}">${escapeHtml(tile.value)}</div>
        <div class="portfolio-tile__meta">${escapeHtml(tile.meta)}</div>
      </div>
    `).join("");
  }

  function renderSportSection(summary) {
    const section = document.getElementById("portfolio-sport-section");
    const grid = document.getElementById("portfolio-sport-grid");
    if (!section || !grid) return;
    const rows = Array.isArray(summary.by_sport) ? summary.by_sport : [];
    section.hidden = rows.length === 0;
    if (!rows.length) return;
    grid.innerHTML = rows.map((row) => `
      <div class="portfolio-sport-card">
        <div class="portfolio-sport-card__name">${escapeHtml(row.sport)}</div>
        <div class="portfolio-sport-card__row"><span>Tracked</span><span>${escapeHtml(String(row.predictions ?? 0))}</span></div>
        <div class="portfolio-sport-card__row"><span>Settled</span><span>${escapeHtml(String(row.settled ?? 0))}</span></div>
        <div class="portfolio-sport-card__row"><span>Win rate</span><span>${pct0(row.win_rate)}</span></div>
      </div>
    `).join("");
  }

  function renderExposureSection(summary) {
    const section = document.getElementById("portfolio-exposure-section");
    const list = document.getElementById("portfolio-exposure");
    if (!section || !list) return;
    const rows = Array.isArray(summary.exposure_by_sport) ? summary.exposure_by_sport : [];
    section.hidden = rows.length === 0;
    if (!rows.length) return;
    list.innerHTML = rows.map((row) => `
      <div class="portfolio-exposure-row">
        <div class="portfolio-exposure-row__sport">${escapeHtml(row.sport)}</div>
        <div class="portfolio-exposure-row__bar-wrap">
          <div class="portfolio-exposure-row__bar" style="width: ${isNum(row.pct) ? row.pct : 0}%;"></div>
        </div>
        <div class="portfolio-exposure-row__stake">${usd(row.stake)}</div>
      </div>
    `).join("");
  }

  function renderLegs(legs) {
    if (!Array.isArray(legs) || !legs.length) return "";
    const items = legs.map((leg) => {
      const selection = escapeHtml(leg.selection || leg.name || "—");
      const market = leg.market ? ` (${escapeHtml(leg.market)})` : "";
      const sport = leg.sport ? ` — ${escapeHtml(leg.sport)}` : "";
      return `<li>${selection}${market}${sport}</li>`;
    }).join("");
    return `
      <details class="portfolio-legs">
        <summary>${legs.length} legs</summary>
        <ul>${items}</ul>
      </details>
    `;
  }

  function renderPositions(summary) {
    const wrap = document.getElementById("portfolio-positions");
    if (!wrap) return;
    const rows = Array.isArray(summary.positions) ? summary.positions : [];
    if (!rows.length) {
      wrap.innerHTML = `<div class="portfolio-empty">No tracked plays yet.</div>`;
      return;
    }
    const body = rows.map((row) => {
      const matchup = row.matchup ? ` <span style="color:var(--cards-text-dim);">· ${escapeHtml(row.matchup)}</span>` : "";
      const status = String(row.status || "").trim();
      return `
        <tr>
          <td>${escapeHtml(row.timestamp || "—")}</td>
          <td class="portfolio-table__primary">${escapeHtml(row.sport || "—")}</td>
          <td class="portfolio-table__primary">
            ${escapeHtml(row.placed_bet || "—")}${matchup}
            ${renderLegs(row.legs)}
          </td>
          <td>${isNum(row.stake) ? usd(row.stake) : "—"}</td>
          <td>${row.odds != null ? escapeHtml(String(row.odds)) : "—"}</td>
          <td>${pct1(row.edge)}</td>
          <td>${num0(row.confidence)}</td>
          <td><span class="status-pill-inline status-pill-inline--${escapeHtml(status)}">${escapeHtml(status)}</span></td>
          <td>${signed2(row.pnl)}</td>
          <td>
            <form method="post" action="/portfolio/bets/${escapeHtml(row.id)}/delete" onsubmit="return confirm('Delete this bet?');">
              <button type="submit" class="portfolio-delete-btn">Delete</button>
            </form>
          </td>
        </tr>
      `;
    }).join("");
    wrap.innerHTML = `
      <table class="portfolio-table">
        <thead>
          <tr>
            <th>Recorded</th>
            <th>Sport</th>
            <th>Placed bet</th>
            <th>Stake</th>
            <th>Odds</th>
            <th>Edge</th>
            <th>Confidence</th>
            <th>Status</th>
            <th>P/L</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    `;
  }

  function renderAll(summary) {
    renderNote(summary);
    renderTiles(summary);
    renderSportSection(summary);
    renderExposureSection(summary);
    renderPositions(summary);
  }

  let lastSuccessAt = null;
  let tickerHandle = null;

  function formatRelativeTime(ms) {
    const seconds = Math.max(0, Math.round(ms / 1000));
    if (seconds < 5) return "just now";
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.round(minutes / 60);
    return `${hours}h ago`;
  }

  function setPulseState(state, text) {
    const chip = document.getElementById("portfolio-pulse");
    const label = document.getElementById("portfolio-pulse-text");
    if (chip) chip.setAttribute("data-state", state);
    if (label) label.textContent = text;
  }

  function updatePulseLabel() {
    if (lastSuccessAt === null) return;
    setPulseState("ok", `Updated ${formatRelativeTime(Date.now() - lastSuccessAt)}`);
  }

  async function fetchAndRender() {
    try {
      const response = await fetch(SUMMARY_ENDPOINT, { headers: { Accept: "application/json" } });
      if (!response.ok) throw new Error(`portfolio summary fetch failed: ${response.status}`);
      const data = await response.json();
      if (!data || data.ok === false) throw new Error("portfolio summary response not ok");
      renderAll(data);
      lastSuccessAt = Date.now();
      updatePulseLabel();
    } catch (error) {
      // Degrade honestly rather than silently: the page keeps showing
      // whatever it last had (server-rendered or last successful poll),
      // but the pulse chip says so instead of quietly going stale forever.
      if (lastSuccessAt === null) {
        setPulseState("error", "Live updates unavailable");
      } else {
        setPulseState("error", `Stale — last updated ${formatRelativeTime(Date.now() - lastSuccessAt)}`);
      }
    }
  }

  function init() {
    if (tickerHandle) return;
    setPulseState("ok", "Live");
    tickerHandle = window.setInterval(updatePulseLabel, 15000);
    // Server already rendered a snapshot for first paint -- this first tick
    // just proves the pulse is live rather than waiting a full interval to
    // find out fetchAndRender works at all.
    void fetchAndRender();
    window.SyndicatePolling.startFromPolicy(
      {},
      { onTick: fetchAndRender },
      { enabled: true, intervalMs: 60000, refreshOnVisible: true, refreshOnFocus: true, skipWhenHidden: true, preventOverlap: true }
    );
  }

  return { init, fetchAndRender, renderAll };
})();
