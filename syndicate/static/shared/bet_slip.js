// Shared bet-slip / portfolio-commit mechanism, extracted 2026-07-24 from
// intelligence.html (the curated Betting Board) so any board -- Layer 2's
// curated picks or Layer 1's full market inventory -- can offer the exact
// same "add to slip, then log to portfolio" flow instead of each page
// reinventing it. Entirely generic: operates on data-syndicate-* attributes
// on any element (a card, a table row) carrying a slip toggle button, plus
// a #bet-slip-panel element to render into. No coupling to any one page's
// data shape.
//
// Two-step flow, unchanged from the original: (1) clicking a
// [data-slip-action="toggle"] button stages a leg into a client-side array
// persisted to localStorage -- no network call. (2) The panel's "Log to
// portfolio" button POSTs each staged leg (or one combined parlay) to
// /api/portfolio/bets, which persists into prediction_ledger.json, tagged with
// the manual portfolio picked below -- read back by /portfolio/books/<id>.
window.SyndicateBetSlip = (function () {
  "use strict";

  const BET_SLIP_STORAGE_KEY = "syndicate_bet_slip_v1";
  const BET_SLIP_MODE_STORAGE_KEY = "syndicate_bet_slip_mode_v1";
  const BET_SLIP_COLLAPSED_STORAGE_KEY = "syndicate_bet_slip_collapsed_v1";
  const DEFAULT_SLIP_STAKE = 10;

  let betSlip = loadBetSlip();
  // MINIMIZED BY DEFAULT `[user decision, 2026-08-22]`. The slip is a
  // companion to the board, not the subject of it -- opening expanded costs
  // vertical space on every visit to show a panel that is usually empty.
  //
  // Persisted like `betSlipMode` rather than reset each load: a reader who
  // expands it is making a choice about how they work, and re-collapsing it on
  // the next page load would silently undo that every time. Default-collapsed
  // and remembered-if-changed are different claims, and only the first was
  // asked for -- so the DEFAULT is collapsed and the OVERRIDE sticks.
  let betSlipCollapsed = loadBetSlipCollapsed();
  // "straight" (default) or "parlay" -- a slip-level toggle, matching how
  // sportsbook slips typically work: a mixed slip either stays straight or
  // becomes one combined parlay ticket.
  let betSlipMode = loadBetSlipMode();
  let parlayStake = DEFAULT_SLIP_STAKE;
  let betSlipPanelWired = false;
  // WHICH PORTFOLIO the slip logs into `[2026-09-10]`. The manual portfolios
  // (/portfolio/books/<id>) come from /api/portfolio/books, which sits behind
  // the portfolio sign-in -- so "signed_out" is a real state, and the slip says
  // so up front instead of failing at the moment of logging.
  const BET_SLIP_PORTFOLIO_STORAGE_KEY = "syndicate_bet_slip_portfolio_v1";
  let portfolioOptions = null;
  let portfolioLoadState = "idle";
  let selectedPortfolioId = loadSelectedPortfolio();

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  function setRefreshStatus(message, tone) {
    const element = document.getElementById("board-refresh-status");
    if (!element) return;
    element.textContent = message;
    element.setAttribute("aria-busy", tone === "loading" || tone === "refreshing" ? "true" : "false");
  }

  function loadSelectedPortfolio() {
    try {
      return window.localStorage.getItem(BET_SLIP_PORTFOLIO_STORAGE_KEY) || "";
    } catch (error) {
      return "";
    }
  }

  function saveSelectedPortfolio() {
    try {
      window.localStorage.setItem(BET_SLIP_PORTFOLIO_STORAGE_KEY, selectedPortfolioId || "");
    } catch (error) {
      /* a remembered choice is a convenience, not a requirement */
    }
  }

  async function loadPortfolioOptions() {
    if (portfolioLoadState === "loading") return;
    portfolioLoadState = "loading";
    try {
      const response = await fetch("/api/portfolio/books", {
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      });
      if (response.status === 401) {
        portfolioLoadState = "signed_out";
      } else if (!response.ok) {
        portfolioLoadState = "error";
      } else {
        const data = await response.json();
        portfolioOptions = Array.isArray(data.books) ? data.books : [];
        if (!portfolioOptions.some((book) => book.id === selectedPortfolioId)) {
          selectedPortfolioId = data.default || (portfolioOptions[0] && portfolioOptions[0].id) || "";
        }
        portfolioLoadState = "ready";
      }
    } catch (error) {
      portfolioLoadState = "error";
    }
    renderBetSlip();
  }

  function portfolioPickerHtml() {
    if (portfolioLoadState === "signed_out") {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      return `<div class="bet-slip__portfolio" style="font-size:11px;margin:6px 0 2px;"><a href="/portfolio/login?next=${next}">Sign in</a> to log bets to your portfolio.</div>`;
    }
    // One manual portfolio means there is nothing to choose.
    if (!Array.isArray(portfolioOptions) || portfolioOptions.length < 2) return "";
    const options = portfolioOptions
      .map((book) => `<option value="${escapeHtml(book.id)}"${book.id === selectedPortfolioId ? " selected" : ""}>${escapeHtml(book.name)}</option>`)
      .join("");
    return `
      <label class="bet-slip__portfolio" style="display:flex;align-items:center;gap:6px;font-size:11px;margin:6px 0 2px;">
        Log to
        <select id="bet-slip-portfolio" style="font:inherit;font-size:11px;color:inherit;background:transparent;border:1px solid rgba(132,166,196,0.3);border-radius:6px;padding:2px 4px;color-scheme:dark;">${options}</select>
      </label>
    `;
  }

  function loadBetSlip() {
    try {
      const raw = window.localStorage.getItem(BET_SLIP_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function saveBetSlip() {
    try {
      window.localStorage.setItem(BET_SLIP_STORAGE_KEY, JSON.stringify(betSlip));
    } catch (error) {
      // Storage unavailable (private browsing, quota) -- slip still works
      // for this page load, just won't survive a refresh.
    }
  }

  function loadBetSlipCollapsed() {
    try {
      // Only an explicit "false" opens it. An absent key, a storage failure and
      // a garbage value all mean collapsed, which is the default being asked
      // for -- the inverse (treating anything non-"true" as expanded) is how a
      // default silently stops applying the moment storage misbehaves.
      return window.localStorage.getItem(BET_SLIP_COLLAPSED_STORAGE_KEY) !== "false";
    } catch (error) {
      return true;
    }
  }

  function saveBetSlipCollapsed() {
    try {
      window.localStorage.setItem(BET_SLIP_COLLAPSED_STORAGE_KEY, betSlipCollapsed ? "true" : "false");
    } catch (error) {
      // Storage unavailable -- the toggle still works for this page load.
    }
  }

  function loadBetSlipMode() {
    try {
      const raw = window.localStorage.getItem(BET_SLIP_MODE_STORAGE_KEY);
      return raw === "parlay" ? "parlay" : "straight";
    } catch (error) {
      return "straight";
    }
  }

  function saveBetSlipMode() {
    try {
      window.localStorage.setItem(BET_SLIP_MODE_STORAGE_KEY, betSlipMode);
    } catch (error) {
      // Storage unavailable -- mode still works for this page load.
    }
  }

  function slipLegKey(leg) {
    return [leg.predictionId, leg.recommendationId, leg.name, leg.market].join("|");
  }

  // American odds -> decimal odds -> payout for a given stake. Standard
  // sportsbook convention: +150 means $100 wins $150 (decimal 2.5); -150
  // means $150 wins $100 (decimal 1.667). Odds of 0/blank/non-numeric can't
  // be priced, so those legs show "--" rather than a fabricated number.
  function decimalOddsFromAmerican(odds) {
    const numeric = Number(odds);
    if (!Number.isFinite(numeric) || numeric === 0) return null;
    return numeric > 0 ? 1 + numeric / 100 : 1 + 100 / Math.abs(numeric);
  }

  function legPayout(leg) {
    const decimal = decimalOddsFromAmerican(leg.odds);
    const stake = Number(leg.stake);
    if (decimal === null || !Number.isFinite(stake) || stake <= 0) return null;
    return stake * decimal;
  }

  // Decimal odds -> American odds, the inverse of decimalOddsFromAmerican.
  function americanOddsFromDecimal(decimal) {
    if (!Number.isFinite(decimal) || decimal <= 1) return null;
    return decimal >= 2 ? Math.round((decimal - 1) * 100) : Math.round(-100 / (decimal - 1));
  }

  // Combined parlay odds are the product of each leg's decimal odds --
  // standard sportsbook parlay pricing. If any leg is unpriced (odds
  // missing/zero), the combined price can't be honestly computed, so this
  // returns null rather than silently pricing the parlay off fewer legs
  // than it actually has.
  function combinedDecimalOdds(legs) {
    let product = 1;
    for (const leg of legs) {
      const decimal = decimalOddsFromAmerican(leg.odds);
      if (decimal === null) return null;
      product *= decimal;
    }
    return product;
  }

  function formatUsd(value) {
    if (value === null || !Number.isFinite(value)) return "--";
    return `$${value.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }

  function isInSlip(key) {
    return betSlip.some((leg) => slipLegKey(leg) === key);
  }

  function addToSlip(card) {
    const leg = {
      name: card.getAttribute("data-syndicate-name") || "",
      market: card.getAttribute("data-syndicate-market") || "",
      // The wagered side (Over/Under), distinct from `name` -- for a player
      // prop `name` is the player's display title, never the pick itself.
      // Without this, the ledger has no way to grade a settled prop: it can
      // know the final stat total and the line, but not which side of that
      // line was actually bet.
      pick: card.getAttribute("data-syndicate-selection") || "",
      propLine: card.getAttribute("data-syndicate-prop-line") || "",
      odds: card.getAttribute("data-syndicate-odds") || "",
      sport: card.getAttribute("data-syndicate-sport") || "",
      predictionId: card.getAttribute("data-syndicate-prediction-id") || "",
      recommendationId: card.getAttribute("data-syndicate-recommendation-id") || "",
      eventId: card.getAttribute("data-syndicate-event-id") || "",
      gameDate: card.getAttribute("data-syndicate-game-date") || "",
      stake: DEFAULT_SLIP_STAKE,
    };
    const key = slipLegKey(leg);
    if (isInSlip(key)) return;
    betSlip.push(leg);
    saveBetSlip();
    renderBetSlip();
    syncSlipButtonStates();
  }

  function removeFromSlip(key) {
    betSlip = betSlip.filter((leg) => slipLegKey(leg) !== key);
    saveBetSlip();
    renderBetSlip();
    syncSlipButtonStates();
  }

  function setLegStake(key, value) {
    const leg = betSlip.find((item) => slipLegKey(item) === key);
    if (!leg) return;
    const numeric = Number(value);
    leg.stake = Number.isFinite(numeric) && numeric >= 0 ? numeric : 0;
    saveBetSlip();
    renderBetSlip();
  }

  function syncSlipButtonStates() {
    document.querySelectorAll("[data-slip-action='toggle']").forEach((button) => {
      const card = button.closest("[data-syndicate-name]");
      if (!card) return;
      const key = [
        card.getAttribute("data-syndicate-prediction-id") || "",
        card.getAttribute("data-syndicate-recommendation-id") || "",
        card.getAttribute("data-syndicate-name") || "",
        card.getAttribute("data-syndicate-market") || "",
      ].join("|");
      const inSlip = isInSlip(key);
      button.setAttribute("data-in-slip", inSlip ? "true" : "false");
      const fullLabel = button.getAttribute("data-slip-label-full") === "true";
      button.textContent = fullLabel ? (inSlip ? "🎫 In slip" : "🎫 Slip") : (inSlip ? "🎫✓" : "🎫");
    });
  }

  function wireSlipButtons(container) {
    const scope = container || document;
    scope.querySelectorAll("[data-slip-action='toggle']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const card = button.closest("[data-syndicate-name]");
        if (!card) return;
        addToSlip(card);
      });
    });
    syncSlipButtonStates();
  }

  async function postPortfolioBet(bet) {
    const response = await fetch("/api/portfolio/bets", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(bet),
    });
    if (!response.ok) {
      const error = new Error(`portfolio bet failed: ${response.status}`);
      error.status = response.status;
      throw error;
    }
    return response.json();
  }

  async function commitBetSlip() {
    if (!betSlip.length) return;
    const commitButton = document.getElementById("bet-slip-commit");
    if (commitButton) commitButton.disabled = true;
    try {
      if (betSlipMode === "parlay") {
        const legs = betSlip.map((leg) => ({
          sport: leg.sport,
          market: leg.market,
          selection: leg.name,
          odds: Number(leg.odds) || null,
          prediction_id: leg.predictionId || undefined,
          recommendation_id: leg.recommendationId || undefined,
          pick: leg.pick || undefined,
          line: leg.propLine || undefined,
          event_id: leg.eventId || undefined,
          game_date: leg.gameDate || undefined,
        }));
        const combinedDecimal = combinedDecimalOdds(betSlip);
        const combinedAmerican = combinedDecimal === null ? null : americanOddsFromDecimal(combinedDecimal);
        await postPortfolioBet({
          bet_type: "parlay",
          legs,
          odds: combinedAmerican,
          stake: Number(parlayStake) || 0,
          portfolio_id: selectedPortfolioId || undefined,
        });
      } else {
        for (const leg of betSlip.slice()) {
          await postPortfolioBet({
            sport: leg.sport,
            market: leg.market,
            selection: leg.name,
            odds: Number(leg.odds) || null,
            stake: Number(leg.stake) || 0,
            prediction_id: leg.predictionId || undefined,
            recommendation_id: leg.recommendationId || undefined,
            pick: leg.pick || undefined,
            line: leg.propLine || undefined,
            event_id: leg.eventId || undefined,
            game_date: leg.gameDate || undefined,
            portfolio_id: selectedPortfolioId || undefined,
          });
        }
      }
      betSlip = [];
      saveBetSlip();
      renderBetSlip();
      syncSlipButtonStates();
      setRefreshStatus("Slip logged to portfolio", "idle");
    } catch (error) {
      if (error && error.status === 401) {
        portfolioLoadState = "signed_out";
        renderBetSlip();
        setRefreshStatus("Sign in to the portfolio to log bets", "error");
      } else {
        if (error && error.status === 400) portfolioLoadState = "idle"; // a stale portfolio id; re-list
        setRefreshStatus("Failed to log slip to portfolio", "error");
      }
    } finally {
      if (commitButton) commitButton.disabled = false;
    }
  }

  function ensureBetSlipPanel() {
    const panel = document.getElementById("bet-slip-panel");
    if (panel && !betSlipPanelWired) {
      betSlipPanelWired = true;
      panel.addEventListener("click", (event) => {
        if (event.target.closest(".bet-slip__header") && !betSlip.length) return;
        if (event.target.closest(".bet-slip__header")) {
          betSlipCollapsed = !betSlipCollapsed;
          saveBetSlipCollapsed();
          renderBetSlip();
        }
      });
    }
    return panel;
  }

  // Mirror the staged-pick count onto the rail's collapse handle.
  //
  // When the rail is collapsed to its 36px strip the whole slip is
  // hidden, so without this a slip holding six picks and an empty one
  // look identical -- which is the reason the old collapse was reported
  // as losing the slip rather than hiding it. Written to the HANDLE
  // (not the rail) because board_cards.css renders the badge with
  // `content: attr(data-slip-count)`, and attr() reads only the
  // pseudo-element's own host.
  //
  // Fails silently and independently of the slip render: the handle is
  // created by board_rail_toggle.js, which may not have run yet (or at
  // all, on a page with no rail). A missing badge must never take the
  // slip down with it.
  function syncRailSlipCount(count) {
    try {
      const handle = document.querySelector(".board-rail .board-rail-handle");
      if (handle) handle.setAttribute("data-slip-count", String(count));
    } catch (e) {
      /* the badge is decoration; the slip is not */
    }
  }

  function renderBetSlip() {
    const panel = ensureBetSlipPanel();
    if (!panel) return;
    const legs = betSlip;
    panel.setAttribute("data-empty", legs.length ? "false" : "true");
    panel.setAttribute("data-collapsed", betSlipCollapsed ? "true" : "false");
    syncRailSlipCount(legs.length);
    if (!legs.length) {
      panel.innerHTML = `
        <div class="bet-slip__header">
          <div class="bet-slip__title">Your slip is empty</div>
        </div>
        <div class="bet-slip__empty">Tap 🎫 Slip on any pick to add it here.</div>
      `;
      return;
    }
    if (portfolioLoadState === "idle") void loadPortfolioOptions();
    const modeToggle = `
      <div class="bet-slip__mode" role="group" aria-label="Slip mode">
        <button type="button" class="bet-slip__mode-btn" data-slip-mode="straight" aria-pressed="${betSlipMode === "straight"}">Straight bets</button>
        <button type="button" class="bet-slip__mode-btn" data-slip-mode="parlay" aria-pressed="${betSlipMode === "parlay"}">Combine into parlay</button>
      </div>
    `;
    let bodyHtml;
    if (betSlipMode === "parlay") {
      const combinedDecimal = combinedDecimalOdds(legs);
      const combinedAmerican = combinedDecimal === null ? null : americanOddsFromDecimal(combinedDecimal);
      const oddsLabel = combinedAmerican === null ? "--" : (combinedAmerican > 0 ? `+${combinedAmerican}` : `${combinedAmerican}`);
      const stakeNum = Number(parlayStake) || 0;
      const payout = combinedDecimal === null || stakeNum <= 0 ? null : stakeNum * combinedDecimal;
      const legRows = legs.map((leg) => {
        const key = slipLegKey(leg);
        const legOddsLabel = leg.odds && Number(leg.odds) ? (Number(leg.odds) > 0 ? `+${Number(leg.odds)}` : `${Number(leg.odds)}`) : "--";
        return `
          <div class="bet-slip__leg bet-slip__leg--parlay" data-slip-key="${escapeHtml(key)}">
            <div class="bet-slip__leg-name">${escapeHtml(leg.name)}</div>
            <button type="button" class="bet-slip__leg-remove" data-slip-remove="${escapeHtml(key)}" aria-label="Remove">&times;</button>
            <div class="bet-slip__leg-meta">${escapeHtml(leg.propLine || leg.market || "")} &middot; ${escapeHtml(legOddsLabel)}</div>
          </div>
        `;
      }).join("");
      bodyHtml = `
        <div class="bet-slip__legs">${legRows}</div>
        <div class="bet-slip__parlay-summary">
          <div class="bet-slip__parlay-odds">Combined odds: <strong>${escapeHtml(oddsLabel)}</strong></div>
          <label for="slip-parlay-stake">Stake $</label>
          <input type="number" min="0" step="1" id="slip-parlay-stake" data-slip-parlay-stake="1" value="${escapeHtml(String(parlayStake))}" />
        </div>
        <div class="bet-slip__totals">
          <div class="bet-slip__totals-label">Total stake</div>
          <div class="bet-slip__totals-label">Potential payout</div>
          <div class="bet-slip__totals-value">${formatUsd(stakeNum)}</div>
          <div class="bet-slip__totals-value">${payout === null ? "--" : formatUsd(payout)}</div>
        </div>
      `;
    } else {
      let totalStake = 0;
      let totalPayout = 0;
      let hasUnpriced = false;
      const legRows = legs.map((leg) => {
        const key = slipLegKey(leg);
        const payout = legPayout(leg);
        const stakeNum = Number(leg.stake) || 0;
        totalStake += stakeNum;
        if (payout === null) hasUnpriced = true;
        else totalPayout += payout;
        const oddsLabel = leg.odds && Number(leg.odds) ? (Number(leg.odds) > 0 ? `+${Number(leg.odds)}` : `${Number(leg.odds)}`) : "--";
        return `
          <div class="bet-slip__leg" data-slip-key="${escapeHtml(key)}">
            <div class="bet-slip__leg-name">${escapeHtml(leg.name)}</div>
            <button type="button" class="bet-slip__leg-remove" data-slip-remove="${escapeHtml(key)}" aria-label="Remove">&times;</button>
            <div class="bet-slip__leg-meta">${escapeHtml(leg.propLine || leg.market || "")} &middot; ${escapeHtml(oddsLabel)}</div>
            <div class="bet-slip__leg-stake">
              <label for="slip-stake-${escapeHtml(key)}">Stake $</label>
              <input type="number" min="0" step="1" id="slip-stake-${escapeHtml(key)}" data-slip-stake="${escapeHtml(key)}" value="${escapeHtml(String(leg.stake))}" />
              <span class="bet-slip__leg-payout">${payout === null ? "--" : `to win ${formatUsd(payout - stakeNum)}`}</span>
            </div>
          </div>
        `;
      }).join("");
      bodyHtml = `
        <div class="bet-slip__legs">${legRows}</div>
        <div class="bet-slip__totals">
          <div class="bet-slip__totals-label">Total stake</div>
          <div class="bet-slip__totals-label">Potential payout</div>
          <div class="bet-slip__totals-value">${formatUsd(totalStake)}</div>
          <div class="bet-slip__totals-value">${hasUnpriced ? `${formatUsd(totalPayout)}+` : formatUsd(totalPayout)}</div>
        </div>
      `;
    }
    panel.innerHTML = `
      <div class="bet-slip__header">
        <div class="bet-slip__title"><span class="bet-slip__count">${legs.length}</span> pick${legs.length === 1 ? "" : "s"} staged</div>
        <div class="bet-slip__toggle">▾</div>
      </div>
      <div class="bet-slip__body">
        ${modeToggle}
        ${bodyHtml}
        ${portfolioPickerHtml()}
        <div class="bet-slip__actions">
          <button type="button" class="bet-slip__clear" id="bet-slip-clear">Clear</button>
          <button type="button" class="bet-slip__commit" id="bet-slip-commit">Log to portfolio</button>
        </div>
      </div>
    `;
    panel.querySelectorAll("[data-slip-mode]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        const mode = button.getAttribute("data-slip-mode");
        if (mode === betSlipMode) return;
        betSlipMode = mode === "parlay" ? "parlay" : "straight";
        saveBetSlipMode();
        renderBetSlip();
      });
    });
    panel.querySelectorAll("[data-slip-remove]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        removeFromSlip(button.getAttribute("data-slip-remove"));
      });
    });
    panel.querySelectorAll("[data-slip-stake]").forEach((input) => {
      input.addEventListener("click", (event) => event.stopPropagation());
      input.addEventListener("change", () => setLegStake(input.getAttribute("data-slip-stake"), input.value));
    });
    const parlayStakeInput = panel.querySelector("[data-slip-parlay-stake]");
    if (parlayStakeInput) {
      parlayStakeInput.addEventListener("click", (event) => event.stopPropagation());
      parlayStakeInput.addEventListener("change", () => {
        const numeric = Number(parlayStakeInput.value);
        parlayStake = Number.isFinite(numeric) && numeric >= 0 ? numeric : 0;
        renderBetSlip();
      });
    }
    const clearButton = document.getElementById("bet-slip-clear");
    if (clearButton) clearButton.addEventListener("click", (event) => {
      event.stopPropagation();
      betSlip = [];
      saveBetSlip();
      renderBetSlip();
      syncSlipButtonStates();
    });
    const portfolioSelect = document.getElementById("bet-slip-portfolio");
    if (portfolioSelect) portfolioSelect.addEventListener("change", (event) => {
      event.stopPropagation();
      selectedPortfolioId = portfolioSelect.value;
      saveSelectedPortfolio();
    });
    const commitButton = document.getElementById("bet-slip-commit");
    if (commitButton) commitButton.addEventListener("click", (event) => {
      event.stopPropagation();
      void commitBetSlip();
    });
  }

  function init() {
    renderBetSlip();
  }

  return { init, wireSlipButtons, renderBetSlip, syncSlipButtonStates };
})();
