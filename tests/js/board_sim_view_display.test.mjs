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

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
