// Live price age on the board card (lane layer2-live-scorecard-gate).
//
// WHY THIS EXISTS. 2026-09-12, a user live-betting NCAAF: "feels like odds are
// delayed in the layer 2 board". Measured the same afternoon: live NCAAF quotes
// were built 351-1,013s old and served another 267-562s later, while the card
// showed only "Book Xm ago" -- the time since the price last MOVED, which reads
// young on a number nobody has re-checked. After the observation gate shipped,
// the prices that survived were built 353s old and served ~74s later. The user's
// decision: show each live price's actual age on the card.
//
// Run it directly:   node tests/js/board_live_price_age.test.mjs
// Not wired into pytest -- same convention as the tests beside it.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
// CRLF-tolerant: a Windows checkout with `core.autocrlf=true` writes the template
// with \r\n, and the extraction patterns below end on `\n  }\n`.
const html = fs.readFileSync(path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html'), 'utf8').replace(/\r\n/g, '\n');

function extract(pattern, label) {
  const m = html.match(pattern);
  if (!m) throw new Error(`could not extract ${label} from intelligence.html`);
  return m[0].replace(/^ {2}/gm, '');
}

const src = [
  extract(/ {2}function formatAge\(seconds\)[\s\S]*?\n {2}}\n/, 'formatAge'),
  extract(/ {2}const LIVE_PRICE_STALE_AFTER_SECONDS = \d+;/, 'LIVE_PRICE_STALE_AFTER_SECONDS'),
  extract(/ {2}function boardBuildEpochMs\(response\)[\s\S]*?\n {2}}\n/, 'boardBuildEpochMs'),
  extract(/ {2}function itemIsLiveForPriceAge\(item\)[\s\S]*?\n {2}}\n/, 'itemIsLiveForPriceAge'),
  extract(/ {2}function liveServedPriceAgeSeconds\(item, response, nowMs\)[\s\S]*?\n {2}}\n/, 'liveServedPriceAgeSeconds'),
  extract(/ {2}function renderFreshness\(item\)[\s\S]*?\n {2}}\n/, 'renderFreshness'),
].join('\n');

// `escapeHtml` and `recommendationState` are the page's own and not under test;
// `lastResponseForActions` is the module-scope response the renderer reads.
const harness = `
  let lastResponseForActions = null;
  function escapeHtml(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function recommendationState(item) { return (item && item.__state) || 'unknown'; }
  function __setResponse(v) { lastResponseForActions = v; }
`;

const api = new Function(
  `${harness}\n${src}; return { renderFreshness, liveServedPriceAgeSeconds, boardBuildEpochMs, itemIsLiveForPriceAge, __setResponse, LIVE_PRICE_STALE_AFTER_SECONDS };`,
)();

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

const now = Date.now();
const iso = (secondsAgo) => new Date(now - secondsAgo * 1000).toISOString();
const liveCard = (quote) => ({ market_state: 'live', quote });

check('the stale threshold is the gate ceiling', api.LIVE_PRICE_STALE_AFTER_SECONDS, 300);

// THE BUILD TIME IS THE FRESHEST ARTIFACT, NOT THE OLDEST.
const bothStamps = { state_meta: { read_at: iso(60), newest_age_seconds: 14 }, state_last_updated: iso(7200) };
check('freshest artifact wins over state_last_updated', Math.round((now - api.boardBuildEpochMs(bothStamps)) / 1000), 74);
check('state_last_updated is only the fallback', Math.round((now - api.boardBuildEpochMs({ state_last_updated: iso(500) })) / 1000), 500);
check('a null newest age falls back rather than reading as zero',
  Math.round((now - api.boardBuildEpochMs({ state_meta: { read_at: iso(10), newest_age_seconds: null }, state_last_updated: iso(900) })) / 1000), 900);
check('no stamp at all is null, not now', api.boardBuildEpochMs({}), null);

// 2026-09-12 20:38Z: a Polymarket-repriced NCAAF price published 353s old, read 74s later.
check('served age = seen age + time since build',
  Math.round(api.liveServedPriceAgeSeconds(liveCard({ quote_seen_age_seconds: 353, book_age_seconds: 256 }), bothStamps, now)), 427);
check('book age stands in only when there is no seen age',
  Math.round(api.liveServedPriceAgeSeconds(liveCard({ book_age_seconds: 120 }), bothStamps, now)), 194);
check('no quote ages -> null', api.liveServedPriceAgeSeconds(liveCard({ price: -110 }), bothStamps, now), null);
check('no build stamp -> null, never just the seen age',
  api.liveServedPriceAgeSeconds(liveCard({ quote_seen_age_seconds: 30 }), {}, now), null);

// RENDERING.
api.__setResponse(bothStamps);
const stale = api.renderFreshness(liveCard({ quote_seen_age_seconds: 353, book_age_seconds: 256, price: -120 }));
check('a 427s live price renders its age', stale.includes('Price seen ≈7m ago'), true);
check('a 427s live price is styled stale', stale.includes('board-card__clock--price board-card__clock--stale'), true);
check('a stale live price tells the bettor what to do', stale.includes('check the book before betting'), true);
check('book age is still shown beside it', stale.includes('Book 4m ago'), true);

// WF @ PUR, Q4 10:32: built 1,013s old and served 267s after the build.
api.__setResponse({ state_meta: { read_at: iso(0), newest_age_seconds: 267 } });
check('the WF @ PUR row reads 21 minutes old',
  api.renderFreshness(liveCard({ quote_seen_age_seconds: 1013.2, book_age_seconds: 618 })).includes('Price seen ≈21m ago'), true);

api.__setResponse({ state_meta: { read_at: iso(0), newest_age_seconds: 30 } });
// 40s seen + 30s since build = 70s: under formatAge's 90s switch to minutes.
const fresh = api.renderFreshness(liveCard({ quote_seen_age_seconds: 40, book_age_seconds: 40 }));
check('a fresh live price renders its age', fresh.includes('Price seen ≈70s ago'), true);
check('a fresh live price is not styled stale', fresh.includes('board-card__clock--price board-card__clock--stale'), false);
check('a fresh live price carries no warning', fresh.includes('check the book'), false);

check('live detection also reads the page state, not only market_state',
  api.itemIsLiveForPriceAge({ __state: 'live', quote: {} }), true);

api.__setResponse({});
check('a live price with no build stamp reads unknown, never fresh',
  api.renderFreshness(liveCard({ quote_seen_age_seconds: 20 })).includes('Price age unknown'), true);

// PREGAME IS UNCHANGED: book clock only, no price-age chip.
api.__setResponse(bothStamps);
const pregame = api.renderFreshness({ market_state: 'pregame', __state: 'pregame', quote: { quote_seen_age_seconds: 5000, book_age_seconds: 4000 } });
check('pregame renders no price-age chip', pregame.includes('Price seen'), false);
check('pregame still renders the book clock', pregame.includes('Book 67m ago'), true);
check('pregame book clock keeps its 1h stale rule', pregame.includes('board-card__clock--stale'), true);
check('pregame with no clocks at all still renders nothing',
  api.renderFreshness({ market_state: 'pregame', quote: { price: 150 } }), '');

if (failures) {
  console.error(`\n${failures} check(s) failed`);
  process.exit(1);
}
console.log('\nall checks passed');
