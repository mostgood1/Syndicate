// Win%, Projected, and the sim-dissent badge: the three cells that render a
// number attributed to the simulation.
//
// WHY A NODE HARNESS IN A PYTEST REPO. Same reason as
// `game_rail_derive.test.mjs`: these live inside an IIFE in
// `syndicate/templates/intelligence.html`, so they are not importable from
// Python. `tests/test_layer2_sim_view_sides.py` covers the BACKEND half (what
// values are published); this covers the DISPLAY half (what a reader sees).
// Both halves were wrong at once on 2026-08-21 and each looked correct alone,
// which is exactly why they are tested on both sides of the boundary.
//
// Run it directly:   node tests/js/board_sim_view_display.test.mjs
// NOT wired into pytest or the migration gate -- a manual check kept beside the
// change it verifies, matching the existing harness in this directory.
//
// WHAT WAS WRONG, and what each assertion below pins:
//
//   Win%       rendered `score["book_confidence"]` -- the books-quoting ladder
//              ((1,0.5),(2,0.7),(4,0.85), else 1.0). "Win% 100%" meant "5+ books
//              quote this". Confirmed 5/5 against a served-board screenshot.
//   Projected  on h2h rows rendered `model_probability`, which the backend
//              published as the projection's OVER/HOME framing regardless of
//              the row's own side -- so away rows showed the home number.
//   Badge      said "sim disagrees" whether the verdict came from the pregame
//              model or from the live re-sim watching the game.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const template = path.resolve(here, '../../syndicate/templates/intelligence.html');
const html = fs.readFileSync(template, 'utf8');

// Extract AT RUN TIME, brace-balanced. Reading the template is the only version
// that cannot go stale -- the sibling harness records a run that silently tested
// a dumped copy and reported failures against passing code.
function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in ${template}`);
  let depth = 0;
  let seen = false;
  for (let i = start; i < html.length; i += 1) {
    if (html[i] === '{') { depth += 1; seen = true; }
    else if (html[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) return html.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced braces extracting ${name}`);
}

const { confidenceValue, displayProjection } = (new Function(
  `${extract('confidenceValue')}\n${extract('displayProjection')}\n` +
  'return { confidenceValue, displayProjection };'
))();

// The badge decision, lifted verbatim from the blotter row renderer. Kept as a
// copy deliberately: it is an inline ternary inside a template literal, so it
// cannot be extracted the way a named function can. If the renderer changes,
// this must change with it -- which is why the two conditions are written here
// in exactly the form they appear there.
function simBadgeText(item) {
  const simDissents = item.sim_view === 'disagrees' || item.sim_view === 'live_disagrees';
  const simIsLive = item.sim_view === 'live_disagrees' || item.sim_basis === 'live_resim';
  if (!simDissents) return null;
  return simIsLive ? 'live sim disagrees' : 'sim disagrees';
}

let failures = 0;
function eq(label, got, want) {
  // Numbers compare with a tolerance: `confidenceValue` divides a 0-100 input
  // by 100, so 78.3 comes back as 0.7829999999999999 -- correct arithmetic that
  // a string comparison would call a failure.
  const ok = (typeof got === 'number' && typeof want === 'number')
    ? Math.abs(got - want) < 1e-9
    : String(got) === String(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}\n        got=${got}  want=${want}`);
}

console.log('--- Win% is a win probability, or nothing ---');
eq('a real probability renders', confidenceValue({ confidence: 0.38 }), 0.38);
eq('a percent-string tier still parses', confidenceValue({ confidence: '78.3%' }), 0.783);
eq('absent stays blank rather than becoming a book count', confidenceValue({}), null);

console.log('\n--- Projected on a moneyline uses the row\'s OWN side ---');
eq('away side', displayProjection({ market: 'h2h', model_probability: 0.38 }), '38.0%');
eq('home side', displayProjection({ market: 'h2h', model_probability: 0.62 }), '62.0%');
eq('three-way draw leg', displayProjection({ market: 'h2h_3_way', model_probability: 0.27 }), '27.0%');

console.log('\n--- Projected on a prop uses the projected NUMBER, never the probability ---');
eq('prop with a projection',
  displayProjection({ market: 'batter_runs_scored', sim_projection: 0.8, model_probability: 0.62 }), '0.8');
eq('prop without one stays blank (the h2h fallback must not leak)',
  displayProjection({ market: 'batter_runs_scored', model_probability: 0.62 }), null);
eq('a real zero renders as zero, not as blank',
  displayProjection({ market: 'batter_runs_scored', sim_projection: 0 }), '0');

console.log('\n--- The badge says WHICH sim dissented ---');
eq('live re-sim', simBadgeText({ sim_view: 'live_disagrees', sim_basis: 'live_resim' }), 'live sim disagrees');
eq('pregame model', simBadgeText({ sim_view: 'disagrees' }), 'sim disagrees');
eq('agreement is not badged (a chip on every row is a chip nobody reads)',
  simBadgeText({ sim_view: 'live_agrees', sim_basis: 'live_resim' }), null);
eq('exactly-zero edge is neutral, not endorsement', simBadgeText({ sim_view: 'neutral' }), null);
eq('no model at all is never typeset as approval', simBadgeText({ sim_view: 'none' }), null);

// --- the odds range filter ----------------------------------------------
//
// The board ranks on EV, and EV alone cannot pick a side -- so a longshot with
// a fat nominal edge sorts to the top. `_SCORE_DEVIG_ABS_ERROR_FLOOR` already
// stops the worst of that in the SCORE (a +6000 soccer h2h reached #1 on the
// first production shortlist); this is the reader's own control over what
// reaches their eyes.
const ladderSrc = html.match(/const ODDS_LADDER = \[([\s\S]*?)\];/);
if (!ladderSrc) throw new Error('ODDS_LADDER not found in ' + template);
const LADDER = ladderSrc[1].split(',').map((s) => s.trim()).filter(Boolean).map(Number);

const impliedProbability = (american) =>
  american > 0 ? 100 / (american + 100) : -american / (-american + 100);

console.log('\n--- the odds ladder is monotonic, which is what makes min/max mean anything ---');
let monotonic = true;
for (let i = 1; i < LADDER.length; i += 1) {
  if (!(impliedProbability(LADDER[i]) < impliedProbability(LADDER[i - 1]))) monotonic = false;
}
eq('ascending odds == strictly descending implied probability', monotonic, true);
eq('the ladder spans the decision band with real stops', LADDER.length >= 20, true);
eq('both ends are open sentinels', LADDER[0] <= -100000 && LADDER[LADDER.length - 1] >= 100000, true);

// Mirror of matchesOddsRange's core, over the REAL ladder read from the file.
function inRange(price, minIdx, maxIdx) {
  if (minIdx === 0 && maxIdx === LADDER.length - 1) return true;
  if (!Number.isFinite(price)) return true;
  return !(price < LADDER[minIdx] || price > LADDER[maxIdx]);
}
const LONGSHOT_CAP = LADDER.indexOf(300);
const FULL = LADDER.length - 1;

console.log('\n--- it removes longshots and keeps the decision band ---');
eq('+6000 longshot is hidden at a +300 cap', inRange(6000, 0, LONGSHOT_CAP), false);
eq('+250 survives a +300 cap', inRange(250, 0, LONGSHOT_CAP), true);
eq('-110 survives a +300 cap', inRange(-110, 0, LONGSHOT_CAP), true);
eq('a heavy -1000 favourite is hidden by a -300 floor',
  inRange(-1000, LADDER.indexOf(-300), FULL), false);
eq('nothing is hidden at the default full range', inRange(6000, 0, FULL), true);

console.log('\n--- and it never hides an absence ---');
eq('a row with no price survives a narrowed filter', inRange(NaN, 0, LONGSHOT_CAP), true);
eq('null price survives too', inRange(Number(null ?? undefined), 0, LONGSHOT_CAP), true);

// --- the default position must show EVERYTHING ---------------------------
//
// SHIPPED BROKEN, and this is the regression test for it. `clampOddsIndex`
// guarded with `Number.isFinite`, but `urlParams.get("odds_max")` returns
// `null` when the parameter is absent and `Number(null)` is `0` -- finite --
// so the fallback never ran. On every normal visit (no URL params) oddsMax
// came out 0 instead of 29, both handles pinned to the low sentinel, the
// visible range collapsed to [-100000, -100000], and THE BOARD RENDERED BLANK.
const clampSrc = extract('clampOddsIndex');
const clampOddsIndex = (new Function(
  `const ODDS_LADDER_MAX_DEFAULT = ${LADDER.length - 1};\n${clampSrc}\nreturn clampOddsIndex;`
))();

console.log('\n--- an ABSENT url param falls back, it does not read as index 0 ---');
const noParams = new URLSearchParams('');
eq('absent odds_max falls back to the open end',
  clampOddsIndex(noParams.get('odds_max'), LADDER.length - 1), LADDER.length - 1);
eq('absent odds_min falls back to the open end',
  clampOddsIndex(noParams.get('odds_min'), 0), 0);
eq('an EMPTY param falls back too (Number("") is also 0)',
  clampOddsIndex(new URLSearchParams('odds_max=').get('odds_max'), LADDER.length - 1), LADDER.length - 1);
eq('a real value is still honoured', clampOddsIndex('11', 0), 11);
eq('garbage falls back rather than clamping to 0', clampOddsIndex('abc', LADDER.length - 1), LADDER.length - 1);
eq('out-of-range clamps into the ladder', clampOddsIndex('999', 0), LADDER.length - 1);

console.log('\n--- and the default position hides NOTHING ---');
const defMin = clampOddsIndex(noParams.get('odds_min'), 0);
const defMax = clampOddsIndex(noParams.get('odds_max'), LADDER.length - 1);
eq('default range is the full ladder', `${defMin}..${defMax}`, `0..${LADDER.length - 1}`);
for (const price of [-1000, -110, 100, 250, 6000]) {
  eq(`a ${price > 0 ? '+' : ''}${price} row survives the default`, inRange(price, defMin, defMax), true);
}

// --- the alt-line filter -------------------------------------------------
//
// The feed quotes `totals_alt` / `spreads_alt` beside the main number, so one
// game can put a whole ladder on the board. This is the reader's control over
// how much of it shows -- and, like the odds range, its DEFAULT must hide
// nothing.
// `isAltLine` now depends on a per-render group map, so it cannot be extracted
// alone -- the whole trio comes out together and the tests drive it the way the
// renderer does (rebuild groups, then classify).
const altApi = (new Function(
  `let altPrimaryByGroup = new Map();
   const numericValue = (v) => (v === null || v === undefined || v === '' || Number.isNaN(Number(v)) ? null : Number(v));
   ${[extract('altGroupKey'), extract('rebuildAltGroups'), extract('isAltLine')].join('\n')}
   return { rebuildAltGroups, isAltLine, groups: () => altPrimaryByGroup };`
))();
// Single-line inputs: no group has more than one line, so nothing is classified
// alt by GROUP and these assertions isolate the market-name rule.
altApi.rebuildAltGroups([]);
const isAltLine = (item) => altApi.isAltLine(item);

console.log('\n--- an alt line is named by its MARKET, not guessed from its number ---');
eq('totals_alt is alt', isAltLine({ market: 'totals_alt' }), true);
eq('spreads_alt is alt', isAltLine({ market: 'spreads_alt' }), true);
// The trap `layer2_board._movement_is_tracked` documents from the other side:
// `totals_alt` STARTS WITH `totals`, so a prefix test sweeps the main market in
// with the alts and "Main lines only" would show nothing at all.
eq('totals is NOT alt (a prefix test would get this wrong)', isAltLine({ market: 'totals' }), false);
eq('spreads is NOT alt', isAltLine({ market: 'spreads' }), false);
eq('h2h is NOT alt', isAltLine({ market: 'h2h' }), false);
eq('a prop is NOT alt', isAltLine({ market: 'batter_runs_scored' }), false);
eq('market_key is honoured when market is absent', isAltLine({ market_key: 'totals_alt' }), true);
eq('a row with no market is not alt (absence is never a classification)', isAltLine({}), false);
eq('case does not decide it', isAltLine({ market: 'TOTALS_ALT' }), true);

// Mirror of matchesClientFilters' alt branch.
function altAllows(mode, item) {
  if (mode === 'all') return true;
  const alt = isAltLine(item);
  if (mode === 'main' && alt) return false;
  if (mode === 'alt' && !alt) return false;
  return true;
}

console.log('\n--- the three modes ---');
eq('default shows the main line', altAllows('all', { market: 'totals' }), true);
eq('default shows the alt line too', altAllows('all', { market: 'totals_alt' }), true);
eq('main-only keeps the main line', altAllows('main', { market: 'totals' }), true);
eq('main-only drops the alt ladder', altAllows('main', { market: 'totals_alt' }), false);
eq('alt-only keeps the alt line', altAllows('alt', { market: 'totals_alt' }), true);
eq('alt-only drops the main line', altAllows('alt', { market: 'totals' }), false);
eq('main-only keeps props (they are not an alt ladder)',
  altAllows('main', { market: 'player_shots' }), true);

// THE DEFAULT IS NOW "main" -- alt lines hidden until asked for
// `[user decision, 2026-08-22]`. This REVERSES the assertion this file
// originally carried, and the reversal is deliberate rather than a regression:
//
//   the odds range must default to showing everything, because its broken
//   default hid EVERY row and the board rendered blank.
//   the alt filter may default to hiding, because hiding alt lines leaves the
//   MAIN line of every market standing -- the board is still populated and the
//   omission is a named, recoverable subset.
//
// A default that hides a known subset is a product choice. A default that can
// empty the board is a bug. Both rules are asserted here so a later change
// cannot quietly swap which one applies to which control.
console.log('\n--- the DEFAULT hides alt lines, and nothing else ---');
const readAlt = (qs) => (['main', 'alt', 'all'].includes(String(new URLSearchParams(qs).get('alt_lines') || ''))
  ? new URLSearchParams(qs).get('alt_lines')
  : 'main');
eq('an absent url param resolves to "main"', readAlt(''), 'main');
eq('an empty param resolves to "main"', readAlt('alt_lines='), 'main');
eq('garbage resolves to "main"', readAlt('alt_lines=banana'), 'main');
eq('"all" is honoured -- the reader can still ask for everything', readAlt('alt_lines=all'), 'all');
eq('"alt" is honoured', readAlt('alt_lines=alt'), 'alt');

const defaultAlt = readAlt('');
for (const market of ['h2h', 'h2h_3_way', 'totals', 'spreads', 'player_shots', 'batter_runs_scored']) {
  eq(`a ${market} row survives the default`, altAllows(defaultAlt, { market }), true);
}
for (const market of ['totals_alt', 'spreads_alt']) {
  eq(`a ${market} row is hidden by the default`, altAllows(defaultAlt, { market }), false);
}
// The load-bearing property: the default must never remove a MAIN market.
eq('every main game market survives the default',
  ['h2h', 'totals', 'spreads'].every((m) => altAllows(defaultAlt, { market: m })), true);

// --- bet type -------------------------------------------------------------
//
// Distinct from the game/prop family selector that already existed: this picks
// ONE market. Its options are built from the rows actually present, so it can
// never offer a slice that is empty for a reason the reader cannot see.
const betTypeLabel = (new Function(
  `${extract('betTypeLabel')}\n${html.match(/const BET_TYPE_LABELS = \{[\s\S]*?\};/)[0]}\nreturn betTypeLabel;`
))();

console.log('\n--- bet-type labels are readable, and an unknown market still appears ---');
eq('h2h reads as Moneyline', betTypeLabel('h2h'), 'Moneyline');
eq('totals_alt names itself as alt', betTypeLabel('totals_alt'), 'Total (alt)');
eq('a prop drops its sport prefix', betTypeLabel('player_shots_on_target'), 'Shots On Target');
eq('a batter prop drops its prefix too', betTypeLabel('batter_runs_scored'), 'Runs Scored');
// The rule that matters for a feed that adds markets: never hide what you
// cannot label. A hardcoded list would drop this row from the selector
// entirely, and the reader would have no way to reach those bets.
eq('an unmapped market is title-cased, not dropped',
  betTypeLabel('corner_kicks_asian'), 'Corner Kicks Asian');
eq('an empty market yields an empty label, not "Undefined"', betTypeLabel(''), '');
eq('null is safe', betTypeLabel(null), '');

// Mirror of the matcher's bet-type branch.
const betAllows = (sel, item) => (sel === 'all'
  ? true
  : String(item.market || item.market_key || '').trim().toLowerCase() === sel);

console.log('\n--- selecting a bet type keeps exactly that market ---');
eq('all keeps everything', betAllows('all', { market: 'h2h' }), true);
eq('h2h keeps h2h', betAllows('h2h', { market: 'h2h' }), true);
eq('h2h drops totals', betAllows('h2h', { market: 'totals' }), false);
// The pairing that would be wrong if this used a prefix test, exactly as the
// alt filter would have been: `totals` must not select `totals_alt`.
eq('totals does NOT select totals_alt', betAllows('totals', { market: 'totals_alt' }), false);
eq('totals_alt selects only itself', betAllows('totals_alt', { market: 'totals_alt' }), true);
eq('market_key is honoured when market is absent', betAllows('h2h', { market_key: 'h2h' }), true);
eq('a row with no market is dropped by a specific selection',
  betAllows('h2h', {}), false);

// --- alt lines, v2: the multi-line group -----------------------------------
//
// V1 SHIPPED WRONG AND THE USER FOUND IT. It tested the MARKET NAME for a
// `_alt` suffix, which is how MLB and NFL quote alternates. **Soccer has no
// such market** -- `fetch_soccer_oddsapi_odds_local.DEFAULT_GAME_MARKETS` is
// exactly ["h2h","totals","spreads"] -- so soccer expresses the same concept as
// SEVERAL ROWS OF ONE MARKET at different lines. The suffix test matched
// nothing, and "Main lines only" left every soccer alt line on the board.
//
// The lesson, and it is the same one this file already records for
// `totals`/`totals_alt`: a rule written from ONE sport's vocabulary is a rule
// about that sport, not about the concept.
const row = (market, line, books, extra) => Object.assign(
  { event_id: 'E1', market, line, segment: 'full', quote: { books_quoting: books } },
  extra || {},
);

console.log('\n--- a soccer totals ladder: only the primary line is "main" ---');
// The real shape: one `totals` market, several lines, the main one quoted by
// the most books.
const ladder = [row('totals', 1.5, 2), row('totals', 2.5, 11), row('totals', 3.5, 3)];
altApi.rebuildAltGroups(ladder);
eq('the most-quoted line is NOT alt', altApi.isAltLine(row('totals', 2.5, 11)), false);
eq('a thinner line IS alt', altApi.isAltLine(row('totals', 1.5, 2)), true);
eq('the other thin line is alt too', altApi.isAltLine(row('totals', 3.5, 3)), true);

console.log('\n--- a single-line market is never alt ---');
altApi.rebuildAltGroups([row('h2h', null, 9), row('spreads', -0.5, 8)]);
eq('the only spread is main', altApi.isAltLine(row('spreads', -0.5, 8)), false);
eq('a moneyline with no line is main', altApi.isAltLine(row('h2h', null, 9)), false);

console.log('\n--- the v1 rule still holds where it was right ---');
altApi.rebuildAltGroups([row('totals_alt', 8.5, 4)]);
eq('an explicit _alt market is alt even as a lone line',
  altApi.isAltLine(row('totals_alt', 8.5, 4)), true);

console.log('\n--- groups do not bleed across event, market or player ---');
altApi.rebuildAltGroups([
  row('totals', 2.5, 9), row('totals', 3.5, 1),
  Object.assign(row('totals', 3.5, 9), { event_id: 'E2' }),
  Object.assign(row('player_shots', 0.5, 9), { player_name: 'A' }),
  Object.assign(row('player_shots', 1.5, 1), { player_name: 'A' }),
  Object.assign(row('player_shots', 1.5, 9), { player_name: 'B' }),
]);
eq('another EVENT\'s 3.5 is its own primary',
  altApi.isAltLine(Object.assign(row('totals', 3.5, 9), { event_id: 'E2' })), false);
eq('player B\'s only line is primary even though A\'s 1.5 is alt',
  altApi.isAltLine(Object.assign(row('player_shots', 1.5, 9), { player_name: 'B' })), false);
eq('player A\'s thin 1.5 is alt',
  altApi.isAltLine(Object.assign(row('player_shots', 1.5, 1), { player_name: 'A' })), true);

console.log('\n--- the primary is DETERMINISTIC, or rows flicker between renders ---');
// Equal book counts: the tie must break the same way every time. Without a
// stable rule the "main" line changes on each refresh and rows appear and
// disappear at random.
const tied = [row('totals', 1.5, 5), row('totals', 2.5, 5), row('totals', 3.5, 5)];
altApi.rebuildAltGroups(tied);
const firstPass = tied.map((r) => altApi.isAltLine(r));
altApi.rebuildAltGroups([...tied].reverse());
const secondPass = tied.map((r) => altApi.isAltLine(r));
eq('input order does not change the answer', JSON.stringify(firstPass), JSON.stringify(secondPass));
eq('exactly one line of a tied group is primary',
  firstPass.filter((v) => v === false).length, 1);
eq('the tie resolves to the MEDIAN line, not the first seen',
  altApi.isAltLine(row('totals', 2.5, 5)), false);

// --- the LIVE column -------------------------------------------------------
//
// Reported by the user: "all the projections (sim pregame, sim live, actual
// live) are blank", then "livedata is the major blank". Two defects, and the
// second was worse than the blank it caused:
//
//   1. A GAME LINE'S `live_projected` IS A PROBABILITY. `_apply_verdict` is
//      called with `live_projected=verdict["model_prob"]` for h2h AND totals
//      AND spreads (`live_gameline_join.py:876`), and
//      `_live_projection_columns` copied it into `live_projection` AND
//      `live_total`. `toFixed(1)` then rendered a 19% live win probability as
//      **"0.2"**, and a totals row as a live projected total of 0.2 goals.
//   2. With that removed the cell goes blank — because this function only ever
//      read `live_projection`/`live_total`, while the backend publishes
//      `live_model_probability` for exactly these rows.
//
// `displayProjection` closed the identical gap for the PREGAME column on
// 2026-08-20 ("109 of 114 h2h rows were blank here for exactly that reason").
// The live column never got it. Same bug, same shape, one column over.
const displayLiveProjection = (new Function(`${extract('displayLiveProjection')}\nreturn displayLiveProjection;`))();

console.log('\n--- a live PROP shows its live count ---');
eq('a prop count renders', displayLiveProjection({ candidate_type: 'prop', live_projection: 2.4 }), '2.4');
eq('a real live zero renders as 0, not blank',
  displayLiveProjection({ candidate_type: 'prop', live_projection: 0 }), '0');
// A prop's live number is a COUNT. If we do not have one, we do not invent one
// from a probability -- that is the "invented projection" the backend forbids.
eq('a prop with only a probability stays blank',
  displayLiveProjection({ candidate_type: 'prop', live_model_probability: 0.62 }), null);
eq('player_name alone marks it a prop',
  displayLiveProjection({ player_name: 'A. Player', live_model_probability: 0.62 }), null);

console.log('\n--- a live GAME LINE shows the live PROBABILITY, not a fake count ---');
eq('a live moneyline renders its probability',
  displayLiveProjection({ market: 'h2h', live_model_probability: 0.19 }), '19.0%');
eq('a live spread does too',
  displayLiveProjection({ market: 'spreads', live_model_probability: 0.55 }), '55.0%');
eq('no live number at all stays blank',
  displayLiveProjection({ market: 'h2h' }), null);

console.log('\n--- and it never typesets a probability as a count ---');
// The exact regression: 0.19 must NOT come back as "0.2".
const shown = displayLiveProjection({ market: 'h2h', live_model_probability: 0.19 });
eq('19% is not rendered as "0.2"', shown === '0.2', false);
eq('19% is rendered as a percentage', shown, '19.0%');
// Out-of-range guards: a value that is not a probability is refused rather
// than multiplied by 100 into nonsense.
eq('a probability of 0 is refused (nothing to claim)',
  displayLiveProjection({ market: 'h2h', live_model_probability: 0 }), null);
eq('a value above 1 is refused',
  displayLiveProjection({ market: 'h2h', live_model_probability: 62 }), null);
eq('garbage is refused',
  displayLiveProjection({ market: 'h2h', live_model_probability: 'soon' }), null);

console.log('\n--- a real live TOTAL still wins over the probability ---');
// `live_total` now carries `total_mean` from the gameline block, which IS a
// count. It must take precedence: a projected 2.7 goals is more informative
// than the cover probability.
eq('a game row prefers its live total', displayLiveProjection({ market: 'totals', live_total: 2.7, live_model_probability: 0.55 }), '2.7');

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
