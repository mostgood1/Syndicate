// Layer 1 market board renderer, shared by MLB/NBA/WNBA (syndicate/templates/
// shared/market_board.html). Fetches the sport's /api/market-board endpoint
// and renders board-card-styled rows -- the same visual language, the same
// toolbar/filter/mini-game-card layout, and the same bet-slip mechanism
// (window.SyndicateBetSlip, shared/bet_slip.js) as the curated Betting Board
// (Layer 2), so both boards feel like one product.
(function () {
  "use strict";

  // Must read data-* attributes synchronously off document.currentScript --
  // it's only valid while this script is the one actively executing, not
  // inside any later callback/async continuation.
  const scriptEl = document.currentScript;
  const apiEndpoint = scriptEl ? scriptEl.getAttribute("data-api-endpoint") : "";
  const sportSlug = scriptEl ? (scriptEl.getAttribute("data-sport-slug") || "").toLowerCase() : "";
  const selectedDate = scriptEl ? (scriptEl.getAttribute("data-selected-date") || "") : "";

  const SPORT_TABS = [
    { value: "mlb", label: "MLB" },
    { value: "nba", label: "NBA" },
    { value: "wnba", label: "WNBA" },
  ];
  const STATE_TABS = [
    { value: "all", label: "All states" },
    { value: "live", label: "Live" },
    { value: "pregame", label: "Pregame" },
    { value: "final", label: "Final" },
  ];
  const MARKET_TABS = [
    { value: "all", label: "All markets" },
    { value: "game", label: "Game markets" },
    { value: "prop", label: "Player props" },
  ];
  const VIEW_TABS = [
    { value: "cards", label: "Cards" },
    { value: "blotter", label: "Blotter" },
  ];

  const state = {
    gameState: "all",
    marketFamily: "all",
    propTypes: new Set(), // empty == no filter (show every market type)
    game: "all",
    view: "cards",
  };

  let boardGames = [];

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  function titleCase(value) {
    const text = String(value || "");
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
  }

  // MLB's game_state comes from a different upstream vocabulary than NBA/
  // WNBA's (e.g. "preview" vs "pregame") -- normalize both to the same
  // filter bucket rather than requiring the backend shapes to match.
  function normalizeGameState(rawState) {
    const value = String(rawState || "").trim().toLowerCase();
    if (value === "live") return "live";
    if (value === "final" || value === "completed") return "final";
    return "pregame";
  }

  function gameStateLabel(normalized) {
    if (normalized === "live") return "Live";
    if (normalized === "final") return "Final";
    return "Pregame";
  }

  function gameStateBadgeClass(normalized) {
    if (normalized === "live") return "live";
    if (normalized === "final") return "no-coverage";
    return "pregame";
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

  function gameKeyFor(game) {
    return String(game.gamePk == null ? "" : game.gamePk);
  }

  function renderTabs(containerId, tabs, activeValue, onSelect) {
    const container = document.getElementById(containerId);
    if (!container) return;
    container.innerHTML = tabs.map((tab) => `
      <button type="button" class="cards-tab${tab.value === activeValue ? " is-active" : ""}" data-tab-value="${escapeHtml(tab.value)}">${escapeHtml(tab.label)}</button>
    `).join("");
    container.querySelectorAll("[data-tab-value]").forEach((button) => {
      button.addEventListener("click", () => onSelect(button.getAttribute("data-tab-value")));
    });
  }

  // Unlike renderTabs (mutually-exclusive single select), every button here
  // toggles independently -- an empty activeSet means "no filter, show
  // every prop type," matching how the market-family/state tabs default to
  // "all" rather than requiring at least one selection.
  function renderMultiTabs(containerId, tabs, activeSet, onToggle) {
    const container = document.getElementById(containerId);
    if (!container) return;
    if (!tabs.length) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = tabs.map((tab) => `
      <button type="button" class="cards-tab${activeSet.has(tab) ? " is-active" : ""}" data-prop-type="${escapeHtml(tab)}" aria-pressed="${activeSet.has(tab)}">${escapeHtml(tab)}</button>
    `).join("");
    container.querySelectorAll("[data-prop-type]").forEach((button) => {
      button.addEventListener("click", () => onToggle(button.getAttribute("data-prop-type")));
    });
  }

  // The full set of distinct market labels actually present today (e.g.
  // "Moneyline", "Total", "Pitcher Outs", "Hitter Home Runs") -- derived
  // from the data itself rather than a hardcoded stat list, so it adapts
  // per sport/slate automatically.
  function derivePropTypes(games) {
    const seen = new Set();
    games.forEach((game) => {
      (Array.isArray(game.rows) ? game.rows : []).forEach((row) => {
        if (row && row.market) seen.add(row.market);
      });
    });
    return Array.from(seen).sort((a, b) => a.localeCompare(b));
  }

  function matchesFilters(row, game) {
    if (state.gameState !== "all" && normalizeGameState(game.game_state) !== state.gameState) return false;
    if (state.marketFamily !== "all" && row.market_type !== state.marketFamily) return false;
    if (state.propTypes.size > 0 && !state.propTypes.has(row.market)) return false;
    if (state.game !== "all" && gameKeyFor(game) !== state.game) return false;
    return true;
  }

  // Every tab group re-renders itself (via renderFilterTabs) after a click,
  // not just the board body -- a single-select tab's onSelect used to only
  // update state and re-filter the results, so a clicked tab (e.g. "Live"
  // or "Player props") correctly filtered the board but never visually
  // showed as selected, since renderTabs/renderMultiTabs were only invoked
  // once at initial render. Real bug reported against the shipped page.
  function renderFilterTabs() {
    renderTabs("board-sport-tabs", SPORT_TABS, sportSlug, (value) => {
      if (value === sportSlug) return;
      const query = selectedDate ? `?date=${encodeURIComponent(selectedDate)}` : "";
      window.location.href = `/${value}/market-board${query}`;
    });
    renderTabs("board-state-tabs", STATE_TABS, state.gameState, (value) => {
      state.gameState = value;
      renderFilterTabs();
      renderGameCards();
      renderBoardBody();
    });
    renderTabs("board-market-tabs", MARKET_TABS, state.marketFamily, (value) => {
      state.marketFamily = value;
      renderFilterTabs();
      renderBoardBody();
    });
    renderTabs("board-view-tabs", VIEW_TABS, state.view, (value) => {
      state.view = value;
      renderFilterTabs();
      renderBoardBody();
    });
    renderPropTypeTabs();
  }

  function renderPropTypeTabs() {
    // Scoped to the active market-family tab so the prop-type list doesn't
    // offer "Moneyline"/"Total" while "Player props" is selected (and vice
    // versa) -- a selection that's no longer offered is dropped rather than
    // silently kept applied.
    const relevantGames = boardGames;
    const allTypes = derivePropTypes(relevantGames);
    const scopedTypes = state.marketFamily === "all"
      ? allTypes
      : allTypes.filter((market) => relevantGames.some((game) =>
          (game.rows || []).some((row) => row.market === market && row.market_type === state.marketFamily)
        ));
    let changed = false;
    state.propTypes.forEach((value) => {
      if (!scopedTypes.includes(value)) {
        state.propTypes.delete(value);
        changed = true;
      }
    });
    renderMultiTabs("board-prop-type-tabs", scopedTypes, state.propTypes, (value) => {
      if (state.propTypes.has(value)) state.propTypes.delete(value);
      else state.propTypes.add(value);
      // Re-render the pills themselves (not just the filtered board) --
      // otherwise a clicked pill filters correctly but never visually
      // shows as selected, since renderMultiTabs was only called once at
      // initial render.
      renderPropTypeTabs();
      renderBoardBody();
    });
    if (changed) renderBoardBody();
  }

  function renderGameCards() {
    const container = document.getElementById("board-game-cards");
    if (!container) return;
    if (!boardGames.length) {
      container.innerHTML = "";
      return;
    }
    const filtered = state.gameState === "all"
      ? boardGames
      : boardGames.filter((game) => normalizeGameState(game.game_state) === state.gameState);
    if (!filtered.length) {
      container.innerHTML = "";
      return;
    }
    container.innerHTML = `
      <h2 class="board-section-title">Games</h2>
      <div class="game-card-strip">
        ${filtered.map((game) => {
          const key = gameKeyFor(game);
          const normalized = normalizeGameState(game.game_state);
          const isSelected = state.game === key;
          const rowCount = Array.isArray(game.rows) ? game.rows.length : 0;
          const stateLabel = normalized === "live" ? '<span class="live-dot">&#9679; live</span>' : gameStateLabel(normalized).toLowerCase();
          return `
            <button type="button" class="game-mini-card" data-game-key="${escapeHtml(key)}" aria-pressed="${isSelected}">
              <div class="game-mini-card__head"><span>${escapeHtml(sportSlug.toUpperCase())}</span><span>${stateLabel}</span></div>
              <div class="game-mini-card__matchup">${escapeHtml(game.matchup || "")}</div>
              <div class="game-mini-card__meta">${rowCount} line${rowCount === 1 ? "" : "s"}</div>
            </button>
          `;
        }).join("")}
      </div>
    `;
    container.querySelectorAll("[data-game-key]").forEach((button) => {
      button.addEventListener("click", () => {
        const key = button.getAttribute("data-game-key");
        state.game = state.game === key ? "all" : key;
        renderGameCards();
        renderBoardBody();
      });
    });
  }

  function renderSummaryStrip() {
    const container = document.getElementById("board-summary-strip");
    if (!container) return;
    const liveCount = boardGames.filter((game) => normalizeGameState(game.game_state) === "live").length;
    const pregameCount = boardGames.filter((game) => normalizeGameState(game.game_state) === "pregame").length;
    const totalRows = boardGames.reduce((sum, game) => sum + (Array.isArray(game.rows) ? game.rows.length : 0), 0);
    const parts = [`${boardGames.length} game${boardGames.length === 1 ? "" : "s"}`];
    if (liveCount) parts.push(`${liveCount} live`);
    if (pregameCount) parts.push(`${pregameCount} pregame`);
    parts.push(`${totalRows} line${totalRows === 1 ? "" : "s"}`);
    container.hidden = false;
    container.innerHTML = parts.map((part) => `<span class="board-chip">${escapeHtml(part)}</span>`).join("");
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
      <article class="board-card board-card--tier-${tier}" data-syndicate-name="${escapeHtml(slipName)}" data-syndicate-market="${escapeHtml(row.market || "")}" data-syndicate-sport="${escapeHtml(sportSlug.toUpperCase())}" data-syndicate-odds="${escapeHtml(oddsText)}" data-syndicate-prop-line="${escapeHtml(propLine)}">
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

  function renderGameSection(game) {
    const rows = (Array.isArray(game.rows) ? game.rows : []).filter((row) => matchesFilters(row, game));
    if (!rows.length) return "";
    const normalized = normalizeGameState(game.game_state);
    return `
      <section class="board-game-group">
        <div class="board-card__head" style="margin-bottom:10px;">
          <div class="board-card__title">${escapeHtml(game.matchup || "")}</div>
          <span class="board-badge board-badge--${gameStateBadgeClass(normalized)}">${escapeHtml(gameStateLabel(normalized))}</span>
        </div>
        <div class="board-grid">${rows.map((row) => renderRowCard(row, game.matchup || "")).join("")}</div>
      </section>
    `;
  }

  function renderBlotterRow(row, game) {
    const normalized = normalizeGameState(game.game_state);
    const oddsText = row.odds !== null && row.odds !== undefined ? String(row.odds) : "";
    const lineText = row.line !== null && row.line !== undefined ? String(row.line) : "";
    const modelValue = formatModelValue(row);
    const title = row.entity || row.market || "Market";
    const sideLabel = titleCase(row.side);
    const propLine = row.entity
      ? [[sideLabel, lineText].filter(Boolean).join(" "), row.market].filter(Boolean).join(" · ")
      : [sideLabel, lineText].filter(Boolean).join(" ");
    const slipName = [title, sideLabel, lineText].filter(Boolean).join(" ");
    const rowAttrs = `data-syndicate-name="${escapeHtml(slipName)}" data-syndicate-market="${escapeHtml(row.market || "")}" data-syndicate-sport="${escapeHtml(sportSlug.toUpperCase())}" data-syndicate-odds="${escapeHtml(oddsText)}" data-syndicate-prop-line="${escapeHtml(propLine)}"`;
    return `
      <tr ${rowAttrs}>
        <td><span class="board-badge board-badge--${gameStateBadgeClass(normalized)}">${escapeHtml(gameStateLabel(normalized))}</span></td>
        <td>
          <div class="board-blotter__primary">${escapeHtml(title)}</div>
          <div class="board-blotter__meta">${escapeHtml(game.matchup || "")}</div>
        </td>
        <td>${escapeHtml(propLine || "-")}</td>
        <td>${oddsText ? escapeHtml(oddsText) : "&mdash;"}</td>
        <td>${modelValue ? escapeHtml(modelValue) : "&mdash;"}</td>
        <td>${badgeForJoinStatus(row.join_status, row.join_note)}</td>
        <td>
          <button type="button" class="board-action-button board-action-button--slip" data-slip-action="toggle">&#127917;</button>
        </td>
      </tr>
    `;
  }

  function renderCardsView(container) {
    const sections = boardGames.map(renderGameSection).filter(Boolean);
    container.innerHTML = sections.length
      ? sections.join("")
      : '<div class="board-empty">No lines match the current filters.</div>';
  }

  function renderBlotterView(container) {
    const rows = [];
    boardGames.forEach((game) => {
      (Array.isArray(game.rows) ? game.rows : []).forEach((row) => {
        if (matchesFilters(row, game)) rows.push(renderBlotterRow(row, game));
      });
    });
    if (!rows.length) {
      container.innerHTML = '<div class="board-empty">No lines match the current filters.</div>';
      return;
    }
    container.innerHTML = `
      <div class="board-blotter-wrap">
        <table class="board-blotter">
          <thead>
            <tr><th>State</th><th>Player / Market</th><th>Pick</th><th>Odds</th><th>Model</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>${rows.join("")}</tbody>
        </table>
      </div>
    `;
  }

  function renderBoardBody() {
    const container = document.getElementById("board-game-groups");
    if (!container) return;
    if (state.view === "blotter") {
      renderBlotterView(container);
    } else {
      renderCardsView(container);
    }
    window.SyndicateBetSlip.wireSlipButtons(container);
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
      boardGames = Array.isArray(data.games) ? data.games : [];
      renderFilterTabs();
      renderGameCards();
      renderSummaryStrip();
      renderBoardBody();
      if (statusEl) statusEl.textContent = "Updated";
    } catch (error) {
      container.innerHTML = `<div class="board-error">Failed to load market board.</div>`;
      if (statusEl) statusEl.textContent = "Failed to load";
    }
  }

  window.SyndicateBetSlip.init();
  void loadBoard();
})();
