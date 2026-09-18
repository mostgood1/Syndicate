(function () {
  const DEFAULT_INTERVAL_MS = 30000;
  // Every poller pauses after this long with no interaction, unless a page
  // passes `idleTimeoutMs: 0`. `skipWhenHidden` is not enough on its own: a
  // Claude desktop browser pane reported /intelligence visible with nobody
  // looking and polled it (~6 MB a tick) every minute for 11 hours on
  // 2026-09-17 (lanes intelligence-idle-poll, polling-idle-pause-all).
  const DEFAULT_IDLE_TIMEOUT_MS = 15 * 60 * 1000;
  const ACTIVITY_EVENTS = ['pointerdown', 'pointermove', 'keydown', 'wheel', 'touchstart', 'scroll'];
  // `reloadCurrentPage` replaces the document, which would restart the idle
  // clock on every tick and so never go idle. The last-activity time rides
  // across those reloads in sessionStorage (per tab); a reload the poller did
  // not cause starts a fresh clock, because a navigation is activity.
  const ACTIVITY_STORAGE_KEY = 'syndicate.polling.lastActivityAt';
  const POLL_RELOAD_STORAGE_KEY = 'syndicate.polling.pollReload';
  const PAUSED_PILL_ID = 'syndicate-poll-paused';
  const PAUSED_MESSAGE = 'Auto-refresh paused while idle. Move the mouse or press a key to resume.';

  function readStorage(key) {
    try {
      return window.sessionStorage ? window.sessionStorage.getItem(key) : null;
    } catch (err) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      if (!window.sessionStorage) return;
      if (value === null) {
        window.sessionStorage.removeItem(key);
      } else {
        window.sessionStorage.setItem(key, value);
      }
    } catch (err) {
      // Storage blocked: the idle clock simply restarts on a poll reload.
    }
  }

  function resolveIdleTimeout(value) {
    if (value === undefined || value === null || value === '') {
      return DEFAULT_IDLE_TIMEOUT_MS;
    }
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
  }

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
      idleTimeoutMs: resolveIdleTimeout(source.idleTimeoutMs ?? source.idle_timeout_ms ?? defaults.idleTimeoutMs ?? defaults.idle_timeout_ms),
      poller: String(source.poller || defaults.poller || 'shared.polling'),
    };
  }

  function reloadCurrentPage(queryKey) {
    writeStorage(POLL_RELOAD_STORAGE_KEY, '1');
    const url = new URL(window.location.href);
    url.searchParams.set(queryKey || '_poll_ts', String(Date.now()));
    window.location.replace(url.toString());
  }

  function showPausedPill() {
    if (!document.body || document.getElementById(PAUSED_PILL_ID)) return;
    const pill = document.createElement('div');
    pill.id = PAUSED_PILL_ID;
    pill.setAttribute('role', 'status');
    pill.textContent = PAUSED_MESSAGE;
    pill.style.cssText = [
      'position:fixed', 'left:16px', 'bottom:16px', 'z-index:9999', 'max-width:calc(100vw - 32px)',
      'padding:8px 12px', 'border-radius:8px', 'font:13px/1.35 system-ui,sans-serif',
      'background:rgba(20,20,24,0.88)', 'color:#fff', 'box-shadow:0 2px 8px rgba(0,0,0,0.25)',
      'pointer-events:none',
    ].join(';');
    document.body.appendChild(pill);
  }

  function hidePausedPill() {
    const pill = document.getElementById(PAUSED_PILL_ID);
    if (pill && pill.parentNode) pill.parentNode.removeChild(pill);
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
    const idleTimeoutMs = resolveIdleTimeout(settings.idleTimeoutMs);
    // A page with its own status line passes onIdle; everyone else gets the pill.
    const onIdle = typeof settings.onIdle === 'function' ? settings.onIdle : showPausedPill;
    const onResume = typeof settings.onResume === 'function' ? settings.onResume : hidePausedPill;
    let handle = null;
    let inFlight = false;
    let idlePaused = false;
    let lastActivityAt = Date.now();
    let lastStoredAt = 0;

    if (idleTimeoutMs) {
      const pollReload = readStorage(POLL_RELOAD_STORAGE_KEY) === '1';
      writeStorage(POLL_RELOAD_STORAGE_KEY, null);
      const stored = Number(readStorage(ACTIVITY_STORAGE_KEY));
      if (pollReload && Number.isFinite(stored) && stored > 0 && stored <= lastActivityAt) {
        lastActivityAt = stored;
      } else {
        writeStorage(ACTIVITY_STORAGE_KEY, String(lastActivityAt));
        lastStoredAt = lastActivityAt;
      }
    }

    function recordActivity() {
      lastActivityAt = Date.now();
      if (lastActivityAt - lastStoredAt >= 5000) {
        lastStoredAt = lastActivityAt;
        writeStorage(ACTIVITY_STORAGE_KEY, String(lastActivityAt));
      }
    }

    function markActive() {
      recordActivity();
      if (!idlePaused) {
        return;
      }
      idlePaused = false;
      onResume();
      void tick();
    }

    async function tick() {
      if (skipWhenHidden && document.hidden) {
        return;
      }
      if (idleTimeoutMs && Date.now() - lastActivityAt >= idleTimeoutMs) {
        if (!idlePaused) {
          idlePaused = true;
          onIdle();
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
      recordActivity();
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
    DEFAULT_IDLE_TIMEOUT_MS: DEFAULT_IDLE_TIMEOUT_MS,
    normalizePolicy: normalizePolicy,
    reloadCurrentPage: reloadCurrentPage,
    resolvePolicy: resolvePolicy,
    start: start,
    startFromPolicy: startFromPolicy,
  };
})();
