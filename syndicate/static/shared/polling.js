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
      idleTimeoutMs: Math.max(0, Number(source.idleTimeoutMs ?? source.idle_timeout_ms ?? defaults.idleTimeoutMs ?? defaults.idle_timeout_ms) || 0),
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
    // Interaction-idle gate, off unless a page opts in. `skipWhenHidden` is not
    // enough on its own: a Claude desktop browser pane reported the page visible
    // with nobody looking and polled /intelligence (~6 MB a tick) every minute
    // for 11 hours on 2026-09-17 (lane intelligence-idle-poll).
    const idleTimeoutMs = Number(settings.idleTimeoutMs) > 0 ? Number(settings.idleTimeoutMs) : 0;
    const onIdle = typeof settings.onIdle === 'function' ? settings.onIdle : null;
    const onResume = typeof settings.onResume === 'function' ? settings.onResume : null;
    const ACTIVITY_EVENTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'scroll'];
    let handle = null;
    let inFlight = false;
    let lastActivityAt = Date.now();
    let idlePaused = false;

    function markActive() {
      lastActivityAt = Date.now();
      if (!idlePaused) {
        return;
      }
      idlePaused = false;
      if (onResume) {
        onResume();
      }
      void tick();
    }

    async function tick() {
      if (skipWhenHidden && document.hidden) {
        return;
      }
      if (idleTimeoutMs && Date.now() - lastActivityAt >= idleTimeoutMs) {
        if (!idlePaused) {
          idlePaused = true;
          if (onIdle) {
            onIdle();
          }
        }
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
      if (idleTimeoutMs) {
        ACTIVITY_EVENTS.forEach(function (name) {
          window.removeEventListener(name, markActive, true);
        });
      }
    }

    function visibilityListener() {
      if (!document.hidden) {
        if (idlePaused) {
          markActive();
          return;
        }
        void tick();
      }
    }

    function focusListener() {
      if (skipWhenHidden && document.hidden) {
        return;
      }
      if (idlePaused) {
        markActive();
        return;
      }
      lastActivityAt = Date.now();
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
    if (idleTimeoutMs) {
      ACTIVITY_EVENTS.forEach(function (name) {
        window.addEventListener(name, markActive, { capture: true, passive: true });
      });
    }

    return {
      stop: stop,
      tick: tick,
      intervalMs: intervalMs,
      isIdlePaused: function () { return idlePaused; },
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
      idleTimeoutMs: policy.idleTimeoutMs,
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