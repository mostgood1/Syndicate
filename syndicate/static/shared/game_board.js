(function () {
  function hydrateBars(root) {
    const scope = root || document;
    scope.querySelectorAll('.cards-prob-bar[data-away-pct]').forEach(function (bar) {
      const awayPct = Number(bar.getAttribute('data-away-pct') || '0');
      const homePct = Number(bar.getAttribute('data-home-pct') || '0');
      bar.style.setProperty('--away-pct', String(awayPct) + '%');
      bar.style.setProperty('--home-pct', String(homePct) + '%');
    });
    scope.querySelectorAll('.cards-run-dist-bin[data-bin-width]').forEach(function (bin) {
      const width = Number(bin.getAttribute('data-bin-width') || '0');
      bin.style.width = String(width) + '%';
    });
  }

  function activateTab(cardNode, panelId) {
    if (!cardNode || !panelId) return;
    cardNode.querySelectorAll('.cards-tab').forEach(function (button) {
      const active = button.getAttribute('data-tab-target') === panelId;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
    });
    cardNode.querySelectorAll('.cards-panel').forEach(function (panel) {
      panel.classList.toggle('is-active', panel.getAttribute('data-panel-id') === panelId);
    });
  }

  document.addEventListener('click', function (event) {
    const tabButton = event.target.closest('.cards-tab[data-tab-target]');
    if (!tabButton) return;
    const cardNode = tabButton.closest('.cards-game-card');
    if (!cardNode) return;
    activateTab(cardNode, tabButton.getAttribute('data-tab-target'));
  });

  document.addEventListener('keydown', function (event) {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const tabButton = event.target.closest('.cards-tab[data-tab-target]');
    if (!tabButton) return;
    const cardNode = tabButton.closest('.cards-game-card');
    if (!cardNode) return;
    event.preventDefault();
    activateTab(cardNode, tabButton.getAttribute('data-tab-target'));
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      hydrateBars(document);
    });
  } else {
    hydrateBars(document);
  }

  // Single-game detail pages (/<sport>/game/<id>) render through this same
  // shared template for every sport (MLB/NBA/NCAAB/NCAAF/NFL/WNBA -- NHL
  // redirects to its cards board instead), but unlike each sport's cards
  // listing page, no JS ever ran here to keep it live: it was a pure
  // one-shot server render with zero rehydration, so anyone watching a live
  // game on its detail page never saw updated numbers without a manual
  // reload. This re-fetches the page's own URL in the background (not a
  // navigation/reload) and swaps in the freshly rendered content containers,
  // matching the ~30s silent-rehydration behavior already used on cards
  // listing pages (see shared/polling.js, static/mlb/cards_source.js).
  //
  // Deliberately scoped to /game/ paths only: cards listing pages that
  // already run their own JSON-driven refresh (MLB/NBA/WNBA) would otherwise
  // get double-refreshed by two competing mechanisms.
  function installGameDetailAutoRefresh() {
    if (!/\/game\//.test(window.location.pathname)) return;
    if (!window.SyndicatePolling || typeof window.SyndicatePolling.start !== 'function') return;

    const SWAP_CONTAINER_IDS = ['cardsHeaderMeta', 'cardsScoreboard', 'cardsGrid', 'cardsHrTargets'];

    async function refreshFromServer() {
      const controller = typeof AbortController === 'function' ? new AbortController() : null;
      const timeoutHandle = controller ? window.setTimeout(function () { controller.abort(); }, 15000) : null;
      let html;
      try {
        const response = await fetch(window.location.href, {
          credentials: 'same-origin',
          signal: controller ? controller.signal : undefined,
          headers: { 'X-Requested-With': 'game-board-auto-refresh' },
        });
        if (!response.ok) return;
        html = await response.text();
      } catch (err) {
        return;
      } finally {
        if (timeoutHandle) window.clearTimeout(timeoutHandle);
      }
      if (!html) return;

      let freshDoc;
      try {
        freshDoc = new DOMParser().parseFromString(html, 'text/html');
      } catch (err) {
        return;
      }

      SWAP_CONTAINER_IDS.forEach(function (id) {
        const current = document.getElementById(id);
        const fresh = freshDoc.getElementById(id);
        if (!current || !fresh) return;
        if (current.innerHTML === fresh.innerHTML) return;
        current.innerHTML = fresh.innerHTML;
        if (id === 'cardsGrid') hydrateBars(current);
      });
    }

    window.SyndicatePolling.start({
      intervalMs: 30000,
      skipWhenHidden: false,
      refreshOnVisible: true,
      refreshOnFocus: true,
      stopOnPageHide: true,
      preventOverlap: true,
      onTick: refreshFromServer,
      onFocus: refreshFromServer,
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', installGameDetailAutoRefresh);
  } else {
    installGameDetailAutoRefresh();
  }
})();