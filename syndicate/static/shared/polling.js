(function () {
  const DEFAULT_INTERVAL_MS = 30000;

  function reloadCurrentPage(queryKey) {
    const url = new URL(window.location.href);
    url.searchParams.set(queryKey || '_poll_ts', String(Date.now()));
    window.location.replace(url.toString());
  }

  function start(options) {
    const settings = options || {};
    const intervalMs = Number(settings.intervalMs) > 0 ? Number(settings.intervalMs) : DEFAULT_INTERVAL_MS;
    const onTick = typeof settings.onTick === 'function' ? settings.onTick : function () {};
    const onFocus = typeof settings.onFocus === 'function' ? settings.onFocus : null;
    const skipWhenHidden = settings.skipWhenHidden !== false;
    const refreshOnVisible = settings.refreshOnVisible === true;
    const refreshOnFocus = settings.refreshOnFocus === true;
    const stopOnPageHide = settings.stopOnPageHide !== false;
    const preventOverlap = settings.preventOverlap !== false;
    let handle = null;
    let inFlight = false;

    async function tick() {
      if (skipWhenHidden && document.hidden) {
        return;
      }
      if (preventOverlap && inFlight) {
        return;
      }
      inFlight = true;
      try {
        await onTick();
      } finally {
        inFlight = false;
      }
    }

    function stop() {
      if (handle) {
        window.clearInterval(handle);
        handle = null;
      }
      if (refreshOnVisible) {
        document.removeEventListener('visibilitychange', visibilityListener);
      }
      if (refreshOnFocus) {
        window.removeEventListener('focus', focusListener);
      }
      if (stopOnPageHide) {
        window.removeEventListener('pagehide', pageHideListener);
      }
    }

    function visibilityListener() {
      if (!document.hidden) {
        void tick();
      }
    }

    function focusListener() {
      if (skipWhenHidden && document.hidden) {
        return;
      }
      if (onFocus) {
        void onFocus();
        return;
      }
      void tick();
    }

    function pageHideListener() {
      stop();
    }

    handle = window.setInterval(function () {
      void tick();
    }, intervalMs);

    if (refreshOnVisible) {
      document.addEventListener('visibilitychange', visibilityListener);
    }
    if (refreshOnFocus) {
      window.addEventListener('focus', focusListener);
    }
    if (stopOnPageHide) {
      window.addEventListener('pagehide', pageHideListener, { once: true });
    }

    return {
      stop: stop,
      tick: tick,
      intervalMs: intervalMs,
    };
  }

  window.SyndicatePolling = {
    DEFAULT_INTERVAL_MS: DEFAULT_INTERVAL_MS,
    reloadCurrentPage: reloadCurrentPage,
    start: start,
  };
})();