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
const isAltLine = (new Function(`${extract('isAltLine')}\nreturn isAltLine;`))();

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

console.log('\n--- and the DEFAULT hides nothing, same rule the odds range shipped broken ---');
const defaultAlt = ['main', 'alt'].includes(String(new URLSearchParams('').get('alt_lines') || ''))
  ? new URLSearchParams('').get('alt_lines')
  : 'all';
eq('an absent url param resolves to "all", not to a mode', defaultAlt, 'all');
for (const market of ['h2h', 'totals', 'totals_alt', 'spreads', 'spreads_alt', 'player_shots']) {
  eq(`a ${market} row survives the default`, altAllows(defaultAlt, { market }), true);
}

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
