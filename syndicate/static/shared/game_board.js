(function () {
  function hydrateBars(root) {
    const scope = root || document;
    scope.querySelectorAll('.cards-prob-bar[data-away-pct]').forEach(function (bar) {
      const awayPct = Number(bar.getAttribute('data-away-pct') || '0');
      const homePct = Number(bar.getAttribute('data-home-pct') || '0');
      bar.style.setProperty('--away-pct', String(awayPct) + '%');
      bar.style.setProperty('--home-pct', String(homePct) + '%');
      // Three-way markets carry a draw segment. Absent on two-way sports, in
      // which case the variable stays unset and the segment is not rendered.
      const drawAttr = bar.getAttribute('data-draw-pct');
      if (drawAttr !== null && drawAttr !== '') {
        bar.style.setProperty('--draw-pct', String(Number(drawAttr)) + '%');
      }
    });
    scope.querySelectorAll('.cards-run-dist-bin[data-bin-width]').forEach(function (bin) {
      const width = Number(bin.getAttribute('data-bin-width') || '0');
      bin.style.width = String(width) + '%';
    });
  }

  function activateTab(cardNode, panelId, options) {
    if (!cardNode || !panelId) return;
    const moveFocus = Boolean(options && options.focus);
    cardNode.querySelectorAll('.cards-tab').forEach(function (button) {
      const active = button.getAttribute('data-tab-target') === panelId;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-selected', active ? 'true' : 'false');
      // Roving tabindex, per the WAI-ARIA tab pattern: exactly one tab of a
      // set sits in the page's tab order and the arrow keys move within the
      // set. Only applied to elements the template actually marked up as
      // tabs, so a sport whose rail has not been converted yet keeps its
      // plain-button keyboard behaviour instead of becoming unreachable.
      if (button.getAttribute('role') === 'tab') {
        button.setAttribute('tabindex', active ? '0' : '-1');
      }
      if (active && moveFocus) button.focus();
    });
    cardNode.querySelectorAll('.cards-panel').forEach(function (panel) {
      panel.classList.toggle('is-active', panel.getAttribute('data-panel-id') === panelId);
    });
  }

  function tabsIn(cardNode) {
    return Array.prototype.slice.call(cardNode.querySelectorAll('.cards-tab[data-tab-target]'));
  }

  function captureTabSelection(root) {
    const selection = [];
    if (!root) return selection;
    root.querySelectorAll('.cards-game-card').forEach(function (card) {
      if (!card.id) return;
      const activePanel = card.querySelector('.cards-panel.is-active');
      const panelId = activePanel && activePanel.getAttribute('data-panel-id');
      if (panelId) selection.push([card.id, panelId]);
    });
    return selection;
  }

  function restoreTabSelection(root, selection) {
    if (!root || !selection || !selection.length) return;
    selection.forEach(function (entry) {
      const card = root.querySelector('.cards-game-card[id="' + entry[0] + '"]');
      if (!card) return;
      if (!card.querySelector('.cards-panel[data-panel-id="' + entry[1] + '"]')) return;
      activateTab(card, entry[1]);
    });
  }

  document.addEventListener('click', function (event) {
    const tabButton = event.target.closest('.cards-tab[data-tab-target]');
    if (!tabButton) return;
    const cardNode = tabButton.closest('.cards-game-card');
    if (!cardNode) return;
    activateTab(cardNode, tabButton.getAttribute('data-tab-target'));
  });

  // Arrow/Home/End navigation. The handler this replaced re-implemented
  // Enter and Space, which a <button> already fires as a click -- so every
  // keyboard activation ran activateTab twice (idempotent, but it meant the
  // one keyboard behaviour the pattern actually requires was the missing one).
  document.addEventListener('keydown', function (event) {
    const KEYS = ['ArrowRight', 'ArrowLeft', 'ArrowDown', 'ArrowUp', 'Home', 'End'];
    if (KEYS.indexOf(event.key) === -1) return;
    const tabButton = event.target.closest('.cards-tab[data-tab-target]');
    if (!tabButton || tabButton.getAttribute('role') !== 'tab') return;
    const cardNode = tabButton.closest('.cards-game-card');
    if (!cardNode) return;
    const tabs = tabsIn(cardNode);
    const current = tabs.indexOf(tabButton);
    if (current === -1 || tabs.length < 2) return;
    let next = current;
    if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = tabs.length - 1;
    else if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (current + 1) % tabs.length;
    else next = (current - 1 + tabs.length) % tabs.length;
    event.preventDefault();
    activateTab(cardNode, tabs[next].getAttribute('data-tab-target'), { focus: true });
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      hydrateBars(document);
    });
  } else {
    hydrateBars(document);
  }

  // Single-game detail pages (/<sport>/game/<id>) render through this same
  // shared template for every sport (MLB/NBA/NCAAB/NCAAF/NFL/WNBA -- NHL's
  // /game/ route redirects to its cards board instead), and NCAAB/NCAAF/NFL's
  // /cards listing pages ALSO render through it with no sport-specific script
  // at all (MLB/NBA/WNBA/NHL each have a separate, bespoke primary cards
  // experience with its own polling; game_cards_board.html is only their
  // `?client=board` fallback variant). Every one of these pages was a pure
  // one-shot server render with zero rehydration: a live game on its detail
  // page, or an entire NCAAB/NCAAF/NFL slate, never showed updated numbers
  // without a manual reload no matter how fresh the backend data was.
  //
  // This re-fetches the page's own URL in the background (not a
  // navigation/reload) and swaps in the freshly rendered content containers,
  // matching the ~30s silent-rehydration behavior already used by MLB/NBA/
  // WNBA/NHL's bespoke cards scripts (see shared/polling.js).
  //
  // Skips pages that already loaded one of those bespoke scripts (relevant
  // when MLB/NBA/WNBA are viewed with ?client=board, which also renders this
  // shared template but WITH their own script tag) so two refresh
  // mechanisms never compete over the same DOM.
  const BESPOKE_CARDS_SCRIPT_SELECTOR = [
    'mlb/cards_source.js',
    'nba/cards_source.js',
    'wnba/cards-parity.js',
  ].map(function (name) { return 'script[src*="' + name + '"]'; }).join(', ');

  function pageHasBespokeCardsRefresh() {
    return Boolean(document.querySelector(BESPOKE_CARDS_SCRIPT_SELECTOR));
  }

  function installSharedBoardAutoRefresh() {
    const pathname = window.location.pathname;
    const isGameDetail = /\/game\//.test(pathname);
    const isCardsListing = /\/cards\/?$/.test(pathname);
    if (!isGameDetail && !isCardsListing) return;
    if (pageHasBespokeCardsRefresh()) return;
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
        // Measured 2026-08-14 on NCAAF: select "Details", wait 40s, and the
        // card is back on the server's default tab -- innerHTML replacement
        // destroys every client-side class, and tab selection lives only in
        // the DOM. Carry it across the swap, keyed on the card's own element
        // id, and only re-apply where the fresh markup still has that panel
        // (a game whose card changed shape falls back to the server default
        // rather than to a panel that no longer exists).
        const selectedTabs = id === 'cardsGrid' ? captureTabSelection(current) : null;
        current.innerHTML = fresh.innerHTML;
        if (id === 'cardsGrid') {
          hydrateBars(current);
          restoreTabSelection(current, selectedTabs);
        }
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
    document.addEventListener('DOMContentLoaded', installSharedBoardAutoRefresh);
  } else {
    installSharedBoardAutoRefresh();
  }
})();