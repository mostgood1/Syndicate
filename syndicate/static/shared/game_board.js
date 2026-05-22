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
})();