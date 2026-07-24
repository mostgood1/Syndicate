// Layer 1 market board renderer, shared by MLB/NBA/WNBA (syndicate/templates/
// shared/market_board.html). Fetches the sport's /api/market-board endpoint
// and renders board-card-styled rows -- the same visual language and the
// same bet-slip mechanism (window.SyndicateBetSlip, shared/bet_slip.js) as
// the curated Betting Board (Layer 2), so both boards feel like one product.
(function () {
  "use strict";

  // Must read data-* attributes synchronously off document.currentScript --
  // it's only valid while this script is the one actively executing, not
  // inside any later callback/async continuation.
  const scriptEl = document.currentScript;
  const apiEndpoint = scriptEl ? scriptEl.getAttribute("data-api-endpoint") : "";
  const sportSlug = scriptEl ? (scriptEl.getAttribute("data-sport-slug") || "").toUpperCase() : "";

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  // Layer 1's join_status is a directly-observed data fact (does the odds
  // row have current sim coverage for its own entity?), not a computed
  // betting edge -- reuses the same tier-coloring CSS as Layer 2's edge
  // tiers, but keyed off join_status instead.
  function tierForJoinStatus(status) {
    if (status === "matched") return "high";
    if (status === "unmatched_needs_resim") return "alert";
    return "low";
  }

  function badgeForJoinStatus(status, note) {
    if (status === "matched") return '<span class="board-badge board-badge--matched">Model view</span>';
    if (status === "unmatched_needs_resim") {
      return `<span class="board-badge board-badge--alert" title="${escapeHtml(note || "")}">Stale &mdash; resim pending</span>`;
    }
    return '<span class="board-badge board-badge--no-coverage">No model view</span>';
  }

  // Every current sim_projection source (moneyline/spread win-or-cover
  // probability, total over/under probability, prop model confidence/edge)
  // is a 0-1 fraction -- format as a percent consistently rather than
  // guessing per market.
  function formatModelValue(row) {
    if (row.sim_projection === null || row.sim_projection === undefined) return null;
    const numeric = Number(row.sim_projection);
    if (!Number.isFinite(numeric)) return String(row.sim_projection);
    return `${(numeric * 100).toFixed(1)}%`;
  }

  function titleCase(value) {
    const text = String(value || "");
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  function renderRowCard(row, matchup) {
    const tier = tierForJoinStatus(row.join_status);
    const title = row.entity || row.market || "Market";
    const sideLabel = titleCase(row.side);
    const lineText = row.line !== null && row.line !== undefined ? String(row.line) : "";
    const oddsText = row.odds !== null && row.odds !== undefined ? String(row.odds) : "";
    const modelValue = formatModelValue(row);
    // For a prop row the title is already the player's name, so the prop
    // line needs the market too ("Over 17.5 · Pitcher Outs"); for a
    // game-level row (entity=None) the title already IS the market
    // ("Moneyline"), so the prop line only needs the side/line.
    const propLine = row.entity
      ? [[sideLabel, lineText].filter(Boolean).join(" "), row.market].filter(Boolean).join(" · ")
      : [sideLabel, lineText].filter(Boolean).join(" ");
    const slipName = [title, sideLabel, lineText].filter(Boolean).join(" ");

    return `
      <article class="board-card board-card--tier-${tier}" data-syndicate-name="${escapeHtml(slipName)}" data-syndicate-market="${escapeHtml(row.market || "")}" data-syndicate-sport="${escapeHtml(sportSlug)}" data-syndicate-odds="${escapeHtml(oddsText)}" data-syndicate-prop-line="${escapeHtml(propLine)}">
        <div class="board-card__head">
          <div>
            <div class="board-card__title">${escapeHtml(title)}</div>
            <div class="board-card__subtitle">${escapeHtml(matchup)}</div>
          </div>
          <div class="board-card__edge">${modelValue ? escapeHtml(modelValue) : "&mdash;"}</div>
        </div>
        <div class="board-card__prop-line">${propLine ? escapeHtml(propLine) : "No market detail available."}</div>
        <div class="board-card__facts">
          <div><div class="board-card__fact-label">Odds</div><div class="board-card__fact-value">${oddsText ? escapeHtml(oddsText) : "&mdash;"}</div></div>
        </div>
        <div class="board-card__badges">${badgeForJoinStatus(row.join_status, row.join_note)}</div>
        ${row.join_status === "unmatched_needs_resim" && row.join_note ? `
          <details class="board-card__reasoning">
            <summary>Why this status</summary>
            <p>${escapeHtml(row.join_note)}</p>
          </details>
        ` : ""}
        <div class="board-card__footer">
          <div class="board-card__actions">
            <button type="button" class="board-action-button board-action-button--slip" data-slip-action="toggle" data-slip-label-full="true">&#127917; Slip</button>
          </div>
        </div>
      </article>
    `;
  }

  function gameStateBadge(gameState) {
    if (gameState === "live") return '<span class="board-badge board-badge--live">Live</span>';
    if (gameState === "final") return '<span class="board-badge board-badge--no-coverage">Final</span>';
    return '<span class="board-badge board-badge--pregame">Pregame</span>';
  }

  function renderGame(game) {
    const rows = Array.isArray(game.rows) ? game.rows : [];
    return `
      <section class="board-game-group">
        <div class="board-card__head" style="margin-bottom:10px;">
          <div class="board-card__title">${escapeHtml(game.matchup || "")}</div>
          ${gameStateBadge(game.game_state)}
        </div>
        ${rows.length
          ? `<div class="board-grid">${rows.map((row) => renderRowCard(row, game.matchup || "")).join("")}</div>`
          : '<div class="board-empty">No moneyline, total, or prop lines available for this game yet.</div>'}
      </section>
    `;
  }

  async function loadBoard() {
    const container = document.getElementById("board-game-groups");
    const statusEl = document.getElementById("board-refresh-status");
    if (!container || !apiEndpoint) return;
    container.innerHTML = `<div class="board-grid">${Array.from({ length: 3 }).map(() => '<div class="board-skeleton-card"></div>').join("")}</div>`;
    if (statusEl) statusEl.textContent = "Loading board…";
    try {
      const res = await fetch(apiEndpoint, { cache: "no-store" });
      if (!res.ok) throw new Error(`status ${res.status}`);
      const data = await res.json();
      const games = Array.isArray(data.games) ? data.games : [];
      if (!games.length) {
        container.innerHTML = `<div class="board-empty">No games found for this date.</div>`;
      } else {
        container.innerHTML = games.map(renderGame).join("");
      }
      window.SyndicateBetSlip.wireSlipButtons(container);
      if (statusEl) statusEl.textContent = "Updated";
    } catch (error) {
      container.innerHTML = `<div class="board-error">Failed to load market board.</div>`;
      if (statusEl) statusEl.textContent = "Failed to load";
    }
  }

  window.SyndicateBetSlip.init();
  void loadBoard();
})();
