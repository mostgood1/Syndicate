// Shared watchlist + alerts mechanism, added 2026-08-03 (Phase 3). Lets a
// reader star any board candidate -- steam or not -- and get a browser
// notification the next time that candidate's board entry becomes a steam
// move. Mirrors syndicate/static/shared/bet_slip.js: operates generically on
// the same data-syndicate-* attributes any board card/row already carries
// (added 2026-07-24 for the bet slip), so no new markup fields were needed.
// No service worker, no push infra -- this is foreground Notification API
// only, fired from the existing 60s board poll while the tab is open.
window.SyndicateWatchlist = (function () {
  "use strict";

  const WATCHLIST_STORAGE_KEY = "syndicate_watchlist_v1";
  const ALERTS_ENABLED_STORAGE_KEY = "syndicate_watchlist_alerts_enabled_v1";
  const ALERT_STATE_STORAGE_KEY = "syndicate_watchlist_alert_state_v1";

  let watchlist = loadWatchlist();
  let alertsEnabled = loadAlertsEnabled();
  // Per watched key, the movement "signature" (timestamp + delta) that was
  // last notified on -- so a steam move that's still live 60s later doesn't
  // re-notify every poll, only when it actually moves again.
  let alertState = loadAlertState();
  let watchlistPanelWired = false;

  function escapeHtml(value) {
    return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char] || char));
  }

  function loadWatchlist() {
    try {
      const raw = window.localStorage.getItem(WATCHLIST_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function saveWatchlist() {
    try {
      window.localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify(watchlist));
    } catch (error) {
      // Storage unavailable (private browsing, quota) -- watchlist still
      // works for this page load, just won't survive a refresh.
    }
  }

  function loadAlertsEnabled() {
    try {
      return window.localStorage.getItem(ALERTS_ENABLED_STORAGE_KEY) === "true";
    } catch (error) {
      return false;
    }
  }

  function saveAlertsEnabled() {
    try {
      window.localStorage.setItem(ALERTS_ENABLED_STORAGE_KEY, alertsEnabled ? "true" : "false");
    } catch (error) {
      // Storage unavailable -- setting still works for this page load.
    }
  }

  function loadAlertState() {
    try {
      const raw = window.localStorage.getItem(ALERT_STATE_STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function saveAlertState() {
    try {
      window.localStorage.setItem(ALERT_STATE_STORAGE_KEY, JSON.stringify(alertState));
    } catch (error) {
      // Storage unavailable -- dedupe still works for this page load.
    }
  }

  // Same five fields on both a rendered card/row (data-syndicate-*, set from
  // these exact raw fields with no display-text transform) and a raw board
  // item from the API -- so a DOM-derived key and an item-derived key always
  // agree for the same candidate.
  function watchKey(fields) {
    return [
      fields.predictionId || "",
      fields.recommendationId || "",
      fields.eventId || "",
      fields.selection || "",
      fields.market || "",
    ].join("|");
  }

  function keyFromCard(card) {
    return watchKey({
      predictionId: card.getAttribute("data-syndicate-prediction-id") || "",
      recommendationId: card.getAttribute("data-syndicate-recommendation-id") || "",
      eventId: card.getAttribute("data-syndicate-event-id") || "",
      selection: card.getAttribute("data-syndicate-selection") || "",
      market: card.getAttribute("data-syndicate-market") || "",
    });
  }

  function keyFromItem(item) {
    return watchKey({
      predictionId: item.prediction_id || "",
      recommendationId: item.recommendation_id || "",
      eventId: String(item.event_id || item.game_id || ""),
      selection: item.selection || item.pick || "",
      market: String(item.market || item.market_label || "").trim(),
    });
  }

  function isWatched(key) {
    return watchlist.some((entry) => entry.key === key);
  }

  function addToWatchlist(card) {
    const key = keyFromCard(card);
    if (isWatched(key)) return;
    watchlist.push({
      key,
      name: card.getAttribute("data-syndicate-name") || "",
      market: card.getAttribute("data-syndicate-market") || "",
      selection: card.getAttribute("data-syndicate-selection") || "",
      sport: card.getAttribute("data-syndicate-sport") || "",
      addedAt: card.getAttribute("data-syndicate-game-date") || "",
    });
    saveWatchlist();
    renderWatchlistPanel();
    syncWatchButtonStates();
  }

  function removeFromWatchlist(key) {
    watchlist = watchlist.filter((entry) => entry.key !== key);
    delete alertState[key];
    saveWatchlist();
    saveAlertState();
    renderWatchlistPanel();
    syncWatchButtonStates();
  }

  function syncWatchButtonStates() {
    document.querySelectorAll("[data-watch-action='toggle']").forEach((button) => {
      const card = button.closest("[data-syndicate-name]");
      if (!card) return;
      const watched = isWatched(keyFromCard(card));
      button.setAttribute("data-watched", watched ? "true" : "false");
      button.textContent = watched ? "★ Watching" : "☆ Watch";
    });
  }

  function wireWatchButtons(container) {
    const scope = container || document;
    scope.querySelectorAll("[data-watch-action='toggle']").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const card = button.closest("[data-syndicate-name]");
        if (!card) return;
        const key = keyFromCard(card);
        if (isWatched(key)) removeFromWatchlist(key);
        else addToWatchlist(card);
      });
    });
    syncWatchButtonStates();
  }

  function notificationsSupported() {
    return typeof window !== "undefined" && "Notification" in window;
  }

  // Must run from a user gesture (the alerts-toggle click) -- browsers
  // reject a permission prompt triggered any other way.
  async function requestAlerts() {
    if (!notificationsSupported()) return false;
    if (Notification.permission === "granted") {
      alertsEnabled = true;
      saveAlertsEnabled();
      renderWatchlistPanel();
      return true;
    }
    if (Notification.permission === "denied") {
      alertsEnabled = false;
      saveAlertsEnabled();
      renderWatchlistPanel();
      return false;
    }
    const permission = await Notification.requestPermission();
    alertsEnabled = permission === "granted";
    saveAlertsEnabled();
    renderWatchlistPanel();
    return alertsEnabled;
  }

  function disableAlerts() {
    alertsEnabled = false;
    saveAlertsEnabled();
    renderWatchlistPanel();
  }

  function candidateTypeOf(item) {
    return String(item.candidate_type || item.type || "").trim().toLowerCase();
  }

  // A steam candidate's movement signature -- changes whenever the market
  // actually moves again, stays constant while the same move is just still
  // being reported. Used purely to dedupe repeat notifications across polls,
  // not displayed anywhere.
  function movementSignature(item) {
    const steam = item.steam && typeof item.steam === "object" ? item.steam : null;
    const movement = item.line_odds_movement && typeof item.line_odds_movement === "object" ? item.line_odds_movement : null;
    const lineDelta = steam ? steam.line_delta : (movement ? movement.line_delta : null);
    const priceDelta = steam ? steam.odds_delta : (movement ? movement.price_delta : null);
    return [item.timestamp || item.last_updated || "", lineDelta ?? "", priceDelta ?? ""].join("|");
  }

  function fireNotification(entry, item) {
    try {
      const pick = item.selection || item.pick || entry.selection || "";
      const market = String(item.market || item.market_label || entry.market || "").trim();
      const notification = new Notification(`⚡ Steam move: ${entry.name || "Watchlist pick"}`, {
        body: [market, pick].filter(Boolean).join(" · ") || "Line is moving — check the board.",
        tag: `syndicate-watch-${entry.key}`,
      });
      notification.onclick = () => {
        window.focus();
        notification.close();
      };
    } catch (error) {
      // Notification construction can throw in some contexts (e.g. denied
      // mid-session, unsupported browser) -- degrade silently, this is a
      // best-effort alert, not a critical path.
    }
  }

  // Called after every board render (poll or filter change) with the same
  // date-filtered item list the board itself just drew from, regardless of
  // which UI filters are currently narrowing the visible cards -- a watched
  // pick should alert even while the reader has a different sport tab open.
  function checkForAlerts(items) {
    if (!alertsEnabled || !notificationsSupported() || Notification.permission !== "granted") return;
    if (!watchlist.length || !Array.isArray(items) || !items.length) return;
    const byKey = new Map();
    items.forEach((item) => byKey.set(keyFromItem(item), item));
    let stateChanged = false;
    watchlist.forEach((entry) => {
      const item = byKey.get(entry.key);
      if (!item || candidateTypeOf(item) !== "steam") return;
      const signature = movementSignature(item);
      const previous = alertState[entry.key];
      if (previous && previous.signature === signature) return;
      alertState[entry.key] = { signature };
      stateChanged = true;
      fireNotification(entry, item);
    });
    if (stateChanged) saveAlertState();
  }

  function ensureWatchlistPanel() {
    const panel = document.getElementById("watchlist-panel");
    if (panel && !watchlistPanelWired) {
      watchlistPanelWired = true;
      panel.addEventListener("click", (event) => {
        const removeButton = event.target.closest("[data-watchlist-remove]");
        if (removeButton) {
          removeFromWatchlist(removeButton.getAttribute("data-watchlist-remove"));
          return;
        }
        const alertsButton = event.target.closest("[data-watchlist-alerts]");
        if (alertsButton) {
          if (alertsEnabled) disableAlerts();
          else void requestAlerts();
        }
      });
    }
    return panel;
  }

  function alertsStatusLabel() {
    if (!notificationsSupported()) return "Alerts unsupported in this browser";
    if (Notification.permission === "denied") return "Alerts blocked — check browser settings";
    return alertsEnabled ? "🔔 Alerts on" : "🔕 Alerts off";
  }

  function renderWatchlistPanel() {
    const panel = ensureWatchlistPanel();
    if (!panel) return;
    panel.setAttribute("data-empty", watchlist.length ? "false" : "true");
    const alertsButton = `<button type="button" class="watchlist__alerts-toggle" data-watchlist-alerts="1" data-alerts-enabled="${alertsEnabled ? "true" : "false"}">${escapeHtml(alertsStatusLabel())}</button>`;
    if (!watchlist.length) {
      panel.innerHTML = `
        <div class="watchlist__header">
          <div class="watchlist__title">Nothing watched yet</div>
          ${alertsButton}
        </div>
        <div class="watchlist__empty">Tap ☆ Watch on any pick to track it here.</div>
      `;
      return;
    }
    const rows = watchlist.map((entry) => `
      <div class="watchlist__item" data-watchlist-key="${escapeHtml(entry.key)}">
        <div class="watchlist__item-main">
          <div class="watchlist__item-name">${escapeHtml(entry.name || "Untitled pick")}</div>
          <div class="watchlist__item-meta">${escapeHtml([entry.market, entry.selection].filter(Boolean).join(" · "))}</div>
        </div>
        <button type="button" class="watchlist__item-remove" data-watchlist-remove="${escapeHtml(entry.key)}" aria-label="Stop watching">&times;</button>
      </div>
    `).join("");
    panel.innerHTML = `
      <div class="watchlist__header">
        <div class="watchlist__title"><span class="watchlist__count">${watchlist.length}</span> watched</div>
        ${alertsButton}
      </div>
      <div class="watchlist__items">${rows}</div>
    `;
  }

  function init() {
    renderWatchlistPanel();
  }

  return {
    init,
    wireWatchButtons,
    syncWatchButtonStates,
    renderWatchlistPanel,
    checkForAlerts,
  };
})();
