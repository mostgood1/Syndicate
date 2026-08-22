// The board rail defaults COLLAPSED at every width, and an override sticks.
//
// WHY THIS EXISTS. `bet_slip.js` was changed on 2026-08-22 to open its panel
// minimized, and that was reported back as not having worked. It had -- on the
// SLIP. There are two independent defaults: the slip's own collapsed state, and
// `.board-rail`, the column that contains it (plus watchlist, portfolio and
// parlays). `board_rail_toggle.js` computed its own default and returned
// "expanded" for anything wider than 1080px, so the reader still saw a full
// second column open beside the board.
//
// I verified the first fix by reading `data-collapsed="true"` off the slip
// element. That assertion was true and it was not the question: the measurement
// matched the change instead of the complaint. This file measures the thing the
// complaint named.
//
// Run it directly:   node tests/js/board_rail_default_state.test.mjs
// Not wired into pytest -- same convention as the two tests beside it.
//
// IT DISCRIMINATES: against the pre-change `defaultState` the first assertion
// fails, because desktop returned "expanded" unconditionally.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const source = fs.readFileSync(
  path.join(here, '..', '..', 'syndicate', 'static', 'shared', 'board_rail_toggle.js'),
  'utf8',
);

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

// Minimal DOM/storage doubles. The script is an IIFE that runs on load and
// touches only what is modelled here.
function run({ width, stored, throwOnStorage = false }) {
  const store = new Map(Object.entries(stored || {}));
  const attrs = new Map();
  const el = (name) => ({
    _name: name,
    setAttribute: (k, v) => attrs.set(`${name}.${k}`, v),
    getAttribute: (k) => (attrs.has(`${name}.${k}`) ? attrs.get(`${name}.${k}`) : null),
    querySelector: () => null,
    closest: () => layout,
    insertBefore: () => {},
    get firstChild() { return null; },
    addEventListener: (_e, fn) => { handlers.push(fn); },
  });
  const handlers = [];
  const layout = el('layout');
  const rail = el('rail');
  const created = [];

  global.window = {
    matchMedia: (q) => ({ matches: width <= 1080 && q.includes('1080') }),
    localStorage: {
      getItem: (k) => { if (throwOnStorage) throw new Error('blocked'); return store.has(k) ? store.get(k) : null; },
      setItem: (k, v) => { if (throwOnStorage) throw new Error('blocked'); store.set(k, v); },
    },
  };
  global.document = {
    readyState: 'complete',
    querySelector: (sel) => (sel === '.board-rail' ? rail : null),
    createElement: () => { const h = el('handle'); h.textContent = ''; created.push(h); return h; },
    addEventListener: () => {},
  };

  // Fresh module instance each run: the IIFE captures nothing across calls.
  new Function(source)();
  return {
    rail: rail.getAttribute('data-rail-state'),
    layout: layout.getAttribute('data-rail-state'),
    store,
    click: () => handlers.forEach((fn) => fn()),
  };
}

// THE REGRESSION: desktop, nothing stored.
const desktop = run({ width: 1440 });
check('desktop (1440px) rail defaults collapsed', desktop.rail, 'collapsed');
check('desktop layout mirrors it, so the board reclaims the column', desktop.layout, 'collapsed');

// Mobile was already collapsed and must stay that way.
check('mobile (390px) rail stays collapsed', run({ width: 390 }).rail, 'collapsed');

// The override sticks -- default-collapsed and reset-every-load are different
// claims, and only the first was asked for.
const toggled = run({ width: 1440 });
toggled.click();
check('opening the rail records the choice', toggled.store.get('syndicate_board_rail_state_v1'), 'expanded');
check('a stored "expanded" reopens it', run({ width: 1440, stored: { syndicate_board_rail_state_v1: 'expanded' } }).rail, 'expanded');
check('a stored "collapsed" keeps it shut', run({ width: 1440, stored: { syndicate_board_rail_state_v1: 'collapsed' } }).rail, 'collapsed');

// Only an explicit "expanded" opens it: absent, garbage and a throwing store
// all land on the default, rather than the default silently ceasing to apply.
check('a garbage stored value falls back to collapsed', run({ width: 1440, stored: { syndicate_board_rail_state_v1: 'yes' } }).rail, 'collapsed');
check('a throwing localStorage falls back to collapsed', run({ width: 1440, throwOnStorage: true }).rail, 'collapsed');

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
