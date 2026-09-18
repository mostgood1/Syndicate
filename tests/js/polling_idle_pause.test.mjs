// `SyndicatePolling` pauses after 15 min with no interaction -- by DEFAULT, for
// every page -- and the next interaction resumes it with an immediate tick.
//
// WHY THIS EXISTS. `/intelligence` re-sends its whole board query (~5-6 MB
// compressed) every 60 s. It already passed `skipWhenHidden: true`, and a Claude
// desktop browser pane still polled it at exactly 60/h from 2026-09-17T17:56:59Z
// to 2026-09-18T04:53:47Z -- roughly 4 GB of web egress from a tab nobody was
// reading. That pane reports `document.hidden === false`, so a visibility gate
// cannot stop it. Lane intelligence-idle-poll added the idle gate for that page;
// lane polling-idle-pause-all made it the default for every poller, carried the
// idle clock across `reloadCurrentPage` reloads, and gave pages without their
// own status line a "paused" pill.
//
// Run it directly:   node tests/js/polling_idle_pause.test.mjs
// Not wired into pytest -- same convention as the tests beside it.
//
// IT DISCRIMINATES: point it at an older file and the relevant assertions fail,
//   POLLING_JS=<path to old polling.js> node tests/js/polling_idle_pause.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const repo = path.join(here, '..', '..');
const sourcePath = process.env.POLLING_JS
  || path.join(repo, 'syndicate', 'static', 'shared', 'polling.js');
const source = fs.readFileSync(sourcePath, 'utf8');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

const MINUTE = 60 * 1000;
const realNow = Date.now;
let now = 1_000_000;
Date.now = () => now;

function memoryStorage() {
  const map = new Map();
  return {
    getItem: (k) => (map.has(k) ? map.get(k) : null),
    setItem: (k, v) => { map.set(k, String(v)); },
    removeItem: (k) => { map.delete(k); },
  };
}

// A fresh window/document per page load. The clock and (optionally) the
// sessionStorage are shared, so a second harness models a reload of the same tab.
function harness(storage = memoryStorage()) {
  const listeners = new Map();
  const intervals = new Map();
  const elements = new Map();
  let nextId = 1;
  const replaced = [];
  const win = {
    sessionStorage: storage,
    location: {
      href: 'https://example.test/nba/live-lens',
      replace(url) { replaced.push(url); },
    },
    setInterval(fn, ms) { const id = nextId++; intervals.set(id, { fn, ms, due: now + ms }); return id; },
    clearInterval(id) { intervals.delete(id); },
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
  };
  const body = {
    appendChild(el) { el.parentNode = body; elements.set(el.id, el); },
    removeChild(el) { el.parentNode = null; elements.delete(el.id); },
  };
  const doc = {
    hidden: false,
    body,
    createElement() { return { style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } }; },
    getElementById(id) { return elements.get(id) || null; },
    addEventListener(name, fn) { win.addEventListener(`doc:${name}`, fn); },
    removeEventListener(name, fn) { win.removeEventListener(`doc:${name}`, fn); },
  };
  new Function('window', 'document', 'URL', source)(win, doc, URL);
  const flush = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
  return {
    polling: win.SyndicatePolling,
    storage,
    replaced,
    pill() { return elements.get('syndicate-poll-paused') || null; },
    listenerCount(name) { return listeners.get(name)?.size || 0; },
    async fire(name) { for (const fn of [...(listeners.get(name) || [])]) fn({ type: name }); await flush(); },
    async advance(ms) {
      const end = now + ms;
      for (;;) {
        const next = [...intervals.values()].filter((t) => t.due <= end).sort((a, b) => a.due - b.due)[0];
        if (!next) break;
        now = next.due;
        next.due += next.ms;
        next.fn();
        await flush();
      }
      now = end;
    },
  };
}

// 1. Explicit timeout: ticks run until it, then stop, and onIdle fires once.
{
  const h = harness();
  let ticks = 0; let idles = 0; let resumes = 0;
  const handle = h.polling.start({
    intervalMs: MINUTE, idleTimeoutMs: 15 * MINUTE, skipWhenHidden: true,
    onTick: () => { ticks += 1; }, onIdle: () => { idles += 1; }, onResume: () => { resumes += 1; },
  });
  await h.advance(14 * MINUTE);
  check('ticks run while active (14 in 14 min)', ticks, 14);
  await h.advance(46 * MINUTE);
  check('no ticks once idle (still 14 at 60 min)', ticks, 14);
  check('onIdle fired exactly once', idles, 1);
  check('handle reports paused', typeof handle.isIdlePaused === 'function' && handle.isIdlePaused(), true);
  check('a page with its own onIdle gets no pill', h.pill(), null);

  // 2. Any interaction resumes with an immediate tick, then the cadence continues.
  await h.fire('pointermove');
  check('interaction resumes with an immediate tick', ticks, 15);
  check('onResume fired once', resumes, 1);
  await h.advance(3 * MINUTE);
  check('cadence resumes after interaction', ticks, 18);

  // A second interaction while active does not add a tick.
  await h.fire('keydown');
  check('interaction while active adds no tick', ticks, 18);
  handle.stop();
  check('stop removes activity listeners', h.listenerCount('pointermove') + h.listenerCount('keydown'), 0);
}

// 3. Focus and becoming visible also resume a paused poller.
{
  const h = harness();
  let ticks = 0;
  h.polling.start({ intervalMs: MINUTE, idleTimeoutMs: 5 * MINUTE, onTick: () => { ticks += 1; } });
  await h.advance(20 * MINUTE);
  const before = ticks;
  await h.fire('focus');
  check('focus resumes a paused poller', ticks, before + 1);
  await h.advance(20 * MINUTE);
  const paused = ticks;
  await h.fire('doc:visibilitychange');
  check('becoming visible resumes a paused poller', ticks, paused + 1);
}

// 4. THE DEFAULT: a caller that says nothing about idling still pauses at 15 min.
//    This is every page other than /intelligence (cards, live lens, accuracy
//    pages, rank board, game board, layer1 board, portfolio pulse).
{
  const h = harness();
  let ticks = 0;
  h.polling.start({ intervalMs: MINUTE, onTick: () => { ticks += 1; } });
  await h.advance(60 * MINUTE);
  check('default: pauses at 15 min with no option passed (14 ticks)', ticks, 14);
  check('default: exposes DEFAULT_IDLE_TIMEOUT_MS = 15 min', h.polling.DEFAULT_IDLE_TIMEOUT_MS, 15 * MINUTE);
}

// 5. The pill: shown on pause when the page has no onIdle, removed on resume.
{
  const h = harness();
  h.polling.start({ intervalMs: MINUTE, onTick: () => {} });
  await h.advance(16 * MINUTE);
  const pill = h.pill();
  check('pill shown when paused', Boolean(pill), true);
  check('pill announces itself (role=status)', pill && pill.attrs.role, 'status');
  check('pill says how to resume', Boolean(pill && /move the mouse or press a key/i.test(pill.textContent)), true);
  await h.fire('pointerdown');
  check('pill removed on resume', h.pill(), null);
}

// 6. Opt-out: idleTimeoutMs 0 keeps the old never-pause behaviour.
{
  const h = harness();
  let ticks = 0;
  h.polling.start({ intervalMs: MINUTE, idleTimeoutMs: 0, onTick: () => { ticks += 1; } });
  await h.advance(60 * MINUTE);
  check('idleTimeoutMs 0: 60 ticks in 60 min, never pauses', ticks, 60);
  check('idleTimeoutMs 0: no activity listeners added', h.listenerCount('pointermove'), 0);
}

// 7. startFromPolicy: an empty server policy gets the default; a stated one wins.
{
  const h = harness();
  let ticks = 0;
  h.polling.startFromPolicy({ refreshPolicy: { intervalMs: MINUTE } }, { onTick: () => { ticks += 1; } });
  await h.advance(60 * MINUTE);
  check('startFromPolicy: default applies to a policy that does not name it', ticks, 14);
  const h2 = harness();
  let ticks2 = 0;
  h2.polling.startFromPolicy(
    {},
    { onTick: () => { ticks2 += 1; } },
    { enabled: true, intervalMs: MINUTE, skipWhenHidden: true, preventOverlap: true, idleTimeoutMs: 15 * MINUTE },
  );
  await h2.advance(60 * MINUTE);
  check('startFromPolicy honours an explicit idleTimeoutMs', ticks2, 14);
}

// 8. A page that reloads itself every tick (rank_board live-lens) still goes
//    idle: the clock rides across poll reloads, and a real navigation resets it.
{
  const storage = memoryStorage();
  let reloads = 0;
  let h = harness(storage);
  h.polling.start({ intervalMs: MINUTE, onTick: () => { reloads += 1; h.polling.reloadCurrentPage(); } });
  for (let i = 0; i < 40; i += 1) {
    await h.advance(MINUTE);
    if (h.replaced.length) {
      // the browser loads the replacement document; the old one's timers die
      h = harness(storage);
      h.polling.start({ intervalMs: MINUTE, onTick: () => { reloads += 1; h.polling.reloadCurrentPage(); } });
    }
  }
  check('poll-reload page stops reloading at 15 min (14 reloads in 40 min)', reloads, 14);
  check('poll-reload page shows the pill once idle', Boolean(h.pill()), true);

  // A reload the poller did NOT cause (the user pressed F5) starts a fresh clock.
  const fresh = harness(storage);
  let ticks = 0;
  fresh.polling.start({ intervalMs: MINUTE, onTick: () => { ticks += 1; } });
  await fresh.advance(5 * MINUTE);
  check('a user navigation resets the idle clock', ticks, 5);
}

// 9. The production callers actually use the shared poller (not bare timers).
{
  const read = (...p) => fs.readFileSync(path.join(repo, ...p), 'utf8');
  check('intelligence.html keeps its 15-min idle timeout',
    /idleTimeoutMs:\s*15 \* 60 \* 1000/.test(read('syndicate', 'templates', 'intelligence.html')), true);
  check('market_board.js polls chips through SyndicatePolling.start',
    /SyndicatePolling\.start\(\{[\s\S]{0,200}loadGameChips/.test(read('syndicate', 'static', 'shared', 'market_board.js')), true);
  check('layer1_board.html polls the board through SyndicatePolling.start',
    /SyndicatePolling\.start\(\{[\s\S]{0,200}fetchBoard/.test(read('syndicate', 'templates', 'shared', 'layer1_board.html')), true);
}

Date.now = realNow;
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
