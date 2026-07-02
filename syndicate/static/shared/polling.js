(function () {
  const DEFAULT_INTERVAL_MS = 30000;

  function normalizePolicy(policy, fallback) {
    const source = policy && typeof policy === 'object' ? policy : {};
    const defaults = fallback && typeof fallback === 'object' ? fallback : {};
    const intervalMs = Number(source.intervalMs ?? source.interval_ms ?? defaults.intervalMs ?? defaults.interval_ms);
    return {
      enabled: source.enabled !== undefined ? Boolean(source.enabled) : (defaults.enabled !== undefined ? Boolean(defaults.enabled) : true),
      intervalMs: Number.isFinite(intervalMs) && intervalMs > 0 ? intervalMs : DEFAULT_INTERVAL_MS,
      refreshOnVisible: source.refreshOnVisible !== undefined ? Boolean(source.refreshOnVisible) : (defaults.refreshOnVisible !== undefined ? Boolean(defaults.refreshOnVisible) : true),
      refreshOnFocus: source.refreshOnFocus !== undefined ? Boolean(source.refreshOnFocus) : (defaults.refreshOnFocus !== undefined ? Boolean(defaults.refreshOnFocus) : true),
      stopOnPageHide: source.stopOnPageHide !== undefined ? Boolean(source.stopOnPageHide) : (defaults.stopOnPageHide !== undefined ? Boolean(defaults.stopOnPageHide) : true),
      preventOverlap: source.preventOverlap !== undefined ? Boolean(source.preventOverlap) : (defaults.preventOverlap !== undefined ? Boolean(defaults.preventOverlap) : true),
      skipWhenHidden: source.skipWhenHidden !== undefined ? Boolean(source.skipWhenHidden) : Boolean(defaults.skipWhenHidden),
      poller: String(source.poller || defaults.poller || 'shared.polling'),
    };
  }

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
    const skipWhenHidden = settings.skipWhenHidden === true;
    const refreshOnVisible = settings.refreshOnVisible !== false;
    const refreshOnFocus = settings.refreshOnFocus !== false;
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

  function resolvePolicy(bootstrap, fallbackPolicy) {
    const source = bootstrap && typeof bootstrap === 'object'
      ? (bootstrap.refreshPolicy || bootstrap.refresh_policy || bootstrap.refresh || null)
      : null;
    return normalizePolicy(source, fallbackPolicy);
  }

  function startFromPolicy(bootstrap, handlers, fallbackPolicy) {
    const policy = resolvePolicy(bootstrap, fallbackPolicy);
    if (!policy.enabled) {
      return {
        stop: function () {},
        tick: function () {},
        intervalMs: policy.intervalMs,
      };
    }
    const settings = Object.assign({}, handlers || {}, {
      intervalMs: policy.intervalMs,
      skipWhenHidden: policy.skipWhenHidden,
      refreshOnVisible: policy.refreshOnVisible,
      refreshOnFocus: policy.refreshOnFocus,
      stopOnPageHide: policy.stopOnPageHide,
      preventOverlap: policy.preventOverlap,
    });
    return start(settings);
  }

  window.SyndicatePolling = {
    DEFAULT_INTERVAL_MS: DEFAULT_INTERVAL_MS,
    normalizePolicy: normalizePolicy,
    reloadCurrentPage: reloadCurrentPage,
    resolvePolicy: resolvePolicy,
    start: start,
    startFromPolicy: startFromPolicy,
  };
})();