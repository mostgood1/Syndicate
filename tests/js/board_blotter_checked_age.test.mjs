// The blotter's Age column: pregame = when WE last checked, live = the book clock.
//
// WHY THIS EXISTS (lane `layer2-freshness-1h`, user decision 2026-10-02 "Last
// polled <=1h"). The blotter is the default view on any viewport over 900px, and
// its Age column was red on the BOOK clock -- how long since the book changed its
// number. On the fleet board that day 1,125 of 1,667 NFL rows were >= 1h on that
// clock, against 129 we had not polled for an hour: an unmoved DraftKings prop we
// had checked minutes earlier read as stale. The card view was fixed first and the
// blotter was missed, which is why this pins the column on its own.
//
// Run it directly:   node tests/js/board_blotter_checked_age.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs
  .readFileSync(path.resolve(here, '../../syndicate/templates/intelligence.html'), 'utf8')
  .split('\r\n').join('\n');

function extract(name, signature) {
  const pattern = new RegExp(` {2}function ${name}\\(${signature}\\)[\\s\\S]*?\\n {2}}\\n`);
  const m = html.match(pattern);
  if (!m) throw new Error(`could not extract ${name} from intelligence.html`);
  return m[0];
}

const src = [
  extract('formatAge', 'seconds'),
  extract('boardBuildEpochMs', 'response'),
  extract('itemIsLiveForPriceAge', 'item'),
  extract('pregameCheckedAgeSeconds', 'item'),
  extract('bookAgeValue', 'item'),
  extract('itemMarketState', 'item'),
  extract('renderBlotterAge', 'item'),
].join('\n');

// The page's own helpers that are not under test.
const harness = `
  let lastResponseForActions = null;
  function escapeHtml(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function recommendationState(item) { return (item && item.__state) || 'pregame'; }
  function itemQuote(item) { return (item && item.quote) || {}; }
  function firstNumeric(...values) {
    for (const v of values) { if (v !== null && v !== undefined && v !== '' && Number.isFinite(Number(v))) return Number(v); }
    return null;
  }
  function __setResponse(v) { lastResponseForActions = v; }
`;

const api = new Function(`${harness}\n${src}; return { renderBlotterAge, pregameCheckedAgeSeconds, __setResponse };`)();

let failures = 0;
function check(label, ok, detail) {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `\n        ${detail}`}`);
}

// A board built "just now", so the served age is the stamped age.
api.__setResponse({ state_meta: { read_at: new Date().toISOString(), newest_age_seconds: 0 } });
const pregame = (quote) => ({ market_state: 'pregame', __state: 'pregame', quote });

console.log('--- pregame: the poll clock decides ---');
{
  const unmoved = api.renderBlotterAge(pregame({ quote_seen_age_seconds: 120, book_age_seconds: 48000 }));
  check('an unmoved price checked 2m ago is NOT red', !unmoved.includes('board-blotter__age--stale'), unmoved);
  check('it shows the poll age', />2m</.test(unmoved), unmoved);
  check('the book clock moves to the tooltip', unmoved.includes('book last moved the number 13h ago'), unmoved);

  const unpolled = api.renderBlotterAge(pregame({ quote_seen_age_seconds: 5400, book_age_seconds: 60 }));
  check('a price not polled for 90m IS red, however recently the book moved', unpolled.includes('board-blotter__age--stale'), unpolled);
  check('and says what to do', unpolled.includes('check the book before betting'), unpolled);
}

console.log('\n--- no poll stamp: the old book-clock rule, unchanged ---');
{
  const bookOnly = api.renderBlotterAge(pregame({ book_age_seconds: 7200 }));
  check('falls back to the book clock', bookOnly.includes('Since this book last moved the number'), bookOnly);
  check('and keeps its 1h red', bookOnly.includes('board-blotter__age--stale'), bookOnly);
  const nothing = api.renderBlotterAge(pregame({}));
  check('no clocks at all reads unknown, never fresh', nothing.includes('&mdash;'), nothing);
}

console.log('\n--- live rows keep the book clock (an unmoved in-play number IS the signal) ---');
{
  const live = { market_state: 'live', __state: 'live', quote: { quote_seen_age_seconds: 30, book_age_seconds: 5000 } };
  check('pregameCheckedAgeSeconds is null for a live row', api.pregameCheckedAgeSeconds(live) === null, String(api.pregameCheckedAgeSeconds(live)));
  const out = api.renderBlotterAge(live);
  check('live judged on the book clock: red at 83m unmoved', out.includes('board-blotter__age--stale') && out.includes('Since this book last moved'), out);
  const dead = api.renderBlotterAge({ market_state: 'dead', __state: 'live', quote: { quote_seen_age_seconds: 30, book_age_seconds: 5000 } });
  check('a dead market still reads dead', dead.includes('board-blotter__age--dead'), dead);
}

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
