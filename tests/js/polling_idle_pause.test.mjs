// `SyndicatePolling` pauses after `idleTimeoutMs` with no interaction, and the
// next interaction resumes it with an immediate tick.
//
// WHY THIS EXISTS. `/intelligence` re-sends its whole board query (~5-6 MB
// compressed) every 60 s. It already passed `skipWhenHidden: true`, and a Claude
// desktop browser pane still polled it at exactly 60/h from 2026-09-17T17:56:59Z
// to 2026-09-18T04:53:47Z -- roughly 4 GB of web egress from a tab nobody was
// reading. That pane reports `document.hidden === false`, so a visibility gate
// cannot stop it. This measures the interaction-idle gate that can (lane
// intelligence-idle-poll).
//
// Run it directly:   node tests/js/polling_idle_pause.test.mjs
// Not wired into pytest -- same convention as the tests beside it.
//
// IT DISCRIMINATES: point it at the pre-change file and the idle assertions fail,
//   POLLING_JS=<path to old polling.js> node tests/js/polling_idle_pause.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourcePath = process.env.POLLING_JS
  || path.join(here, '..', '..', 'syndicate', 'static', 'shared', 'polling.js');
const source = fs.readFileSync(sourcePath, 'utf8');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

const MINUTE = 60 * 1000;
const realNow = Date.now;

// A fresh window/document/clock per scenario. The IIFE only touches what is
// modelled here: setInterval/clearInterval, add/removeEventListener, document.hidden.
function harness() {
  let now = 1_000_000;
  Date.now = () => now;
  const listeners = new Map();
  const intervals = new Map();
  let nextId = 1;
  const win = {
    location: { href: 'https://example.test/intelligence' },
    setInterval(fn, ms) { const id = nextId++; intervals.set(id, { fn, ms, due: now + ms }); return id; },
    clearInterval(id) { intervals.delete(id); },
    addEventListener(name, fn) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(fn); },
    removeEventListener(name, fn) { listeners.get(name)?.delete(fn); },
  };
  const doc = {
    hidden: false,
    addEventListener(name, fn) { win.addEventListener(`doc:${name}`, fn); },
    removeEventListener(name, fn) { win.removeEventListener(`doc:${name}`, fn); },
  };
  new Function('window', 'document', source)(win, doc);
  const flush = async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); };
  return {
    polling: win.SyndicatePolling,
    doc,
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

// 1. Idle pause: ticks run until the timeout, then stop, and onIdle fires once.
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

// 4. off != on: without idleTimeoutMs the poller never pauses (unchanged pages).
{
  const h = harness();
  let ticks = 0;
  h.polling.start({ intervalMs: MINUTE, onTick: () => { ticks += 1; } });
  await h.advance(60 * MINUTE);
  check('no idleTimeoutMs: 60 ticks in 60 min, never pauses', ticks, 60);
  check('no idleTimeoutMs: no activity listeners added', h.listenerCount('pointermove'), 0);
}

// 5. startFromPolicy carries idleTimeoutMs through (the path intelligence.html uses).
{
  const h = harness();
  let ticks = 0;
  h.polling.startFromPolicy(
    {},
    { onTick: () => { ticks += 1; } },
    { enabled: true, intervalMs: MINUTE, skipWhenHidden: true, preventOverlap: true, idleTimeoutMs: 15 * MINUTE },
  );
  await h.advance(60 * MINUTE);
  check('startFromPolicy honours idleTimeoutMs', ticks, 14);
}

// 6. The page actually opts in (the production caller, not just the library).
{
  const template = fs.readFileSync(
    path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html'), 'utf8');
  check('intelligence.html passes idleTimeoutMs to its poller', /idleTimeoutMs:\s*15 \* 60 \* 1000/.test(template), true);
}

Date.now = realNow;
console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
