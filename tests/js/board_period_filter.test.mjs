// Full game vs game intervals `[user 2026-10-08, lane layer2-board-ui-redesign]`.
//
// `isIntervalRow` lives inside the board's IIFE, so it is extracted from the
// template at run time (same pattern as board_sim_view_display.test.mjs).
// A row names its period in one of TWO places -- `segment`, or a market-key
// suffix on rows with no segment -- and a filter reading only one would file
// the other as "full game".
//
// Run: node tests/js/board_period_filter.test.mjs   (also run by
// tests/test_layer2_board_ui_redesign.py when node is on PATH)

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.resolve(here, '../../syndicate/templates/intelligence.html'), 'utf8');

function grab(re, what) {
  const m = html.match(re);
  if (!m) throw new Error(`${what} not found`);
  return m[0];
}
function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  let depth = 0; let seen = false;
  for (let i = start; i < html.length; i += 1) {
    if (html[i] === '{') { depth += 1; seen = true; } else if (html[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) return html.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced ${name}`);
}

// PERIOD_TABS / INTERVAL_LABELS are multi-line literals: grabbed up to `];` / `};`.
const lib = (new Function(
  `${grab(/const FULL_GAME_SEGMENTS = [^\n]+/, 'FULL_GAME_SEGMENTS')}\n`
  + `${grab(/const SEGMENT_SUFFIX_RE = [^\n]+/, 'SEGMENT_SUFFIX_RE')}\n`
  + `${grab(/const PERIOD_TABS = \[[\s\S]*?\];/, 'PERIOD_TABS')}\n`
  + `${grab(/const INTERVAL_ORDER = [^\n]+/, 'INTERVAL_ORDER')}\n`
  + `${grab(/const INTERVAL_LABELS = \{[\s\S]*?\};/, 'INTERVAL_LABELS')}\n`
  + `${extract('canonicalInterval')}\n${extract('intervalKey')}\n${extract('isIntervalRow')}\n`
  + `${extract('intervalLabel')}\n${extract('periodLabel')}\n`
  + `const state = { period: "all" };\n${extract('matchesPeriod')}\n`
  + 'return { isIntervalRow, intervalKey, intervalLabel, periodLabel, canonicalInterval,'
  + ' matchesPeriod: (item, period) => { state.period = period; return matchesPeriod(item); } };'
))();
const { isIntervalRow, intervalKey, intervalLabel, periodLabel, canonicalInterval, matchesPeriod } = lib;

let failures = 0;
function eq(label, got, want) {
  const ok = got === want;
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `  got=${got} want=${want}`}`);
}

eq('no segment, plain market is full game', isIntervalRow({ market: 'h2h' }), false);
eq('segment "full" is full game', isIntervalRow({ segment: 'full', market: 'totals' }), false);
eq('segment "full_game" is full game', isIntervalRow({ segment: 'full_game' }), false);
eq('segment first5 is an interval', isIntervalRow({ segment: 'first5', market: 'totals' }), true);
eq('segment first1 is an interval', isIntervalRow({ segment: 'first1', market: 'h2h_3_way' }), true);
eq('segment q3 is an interval', isIntervalRow({ segment: 'q3' }), true);
eq('segment h1 is an interval', isIntervalRow({ segment: 'h1' }), true);
eq('segment p2 is an interval', isIntervalRow({ segment: 'p2' }), true);
eq('suffix _1st_5_innings with no segment', isIntervalRow({ market: 'totals_1st_5_innings' }), true);
eq('suffix _q1 with no segment', isIntervalRow({ market: 'spreads_q1' }), true);
eq('suffix _h1 with no segment', isIntervalRow({ market: 'h2h_h1' }), true);
eq('suffix _1h with no segment', isIntervalRow({ market: 'h2h_1h' }), true);
eq('suffix _p3 with no segment', isIntervalRow({ market: 'totals_p3' }), true);
eq('an alt market is not an interval', isIntervalRow({ market: 'totals_alt' }), false);
eq('a player prop is not an interval', isIntervalRow({ market: 'player_pass_tds', segment: 'full' }), false);
eq('batter_hits is not an interval', isIntervalRow({ market: 'batter_hits' }), false);

// SPECIFIC INTERVALS `[user 2026-10-24, lane layer2-interval-selector]`: one
// canonical token per slice, whichever vocabulary the row used.
eq('segment h1 -> h1', intervalKey({ segment: 'h1' }), 'h1');
eq('suffix _1h folds into h1', intervalKey({ market: 'h2h_1h' }), 'h1');
eq('segment "1h" folds into h1', intervalKey({ segment: '1h' }), 'h1');
eq('suffix _h2 -> h2', intervalKey({ market: 'totals_h2' }), 'h2');
eq('suffix _2h folds into h2', intervalKey({ market: 'spreads_2h' }), 'h2');
eq('suffix _1st_5_innings -> first5', intervalKey({ market: 'totals_1st_5_innings' }), 'first5');
eq('segment first5 -> first5', intervalKey({ segment: 'first5', market: 'totals' }), 'first5');
eq('suffix _1st_1_innings -> first1', intervalKey({ market: 'h2h_1st_1_innings' }), 'first1');
eq('suffix _1st_inning -> first1', intervalKey({ market: 'totals_1st_inning' }), 'first1');
eq('suffix _q3 -> q3', intervalKey({ market: 'spreads_q3' }), 'q3');
eq('suffix _p2 -> p2', intervalKey({ market: 'totals_p2' }), 'p2');
eq('explicit segment wins over the market suffix', intervalKey({ segment: 'q2', market: 'totals_h1' }), 'q2');
eq('full game is ""', intervalKey({ market: 'totals' }), '');
eq('unknown segment kept, not swallowed', intervalKey({ segment: 'ot' }), 'ot');
eq('label first5', intervalLabel('first5'), '1st 5 innings');
eq('label q1', intervalLabel('q1'), '1st quarter');
eq('label unknown is upper-cased', intervalLabel('ot'), 'OT');
eq('periodLabel fixed tab', periodLabel('intervals'), 'Game intervals');
eq('periodLabel interval', periodLabel('h2'), '2nd half');
eq('URL ?period=1h canonicalises', canonicalInterval('1h'), 'h1');
eq('URL ?period=full_game is full game', canonicalInterval('full_game'), '');
eq('period h1 keeps a _1h suffix row', matchesPeriod({ market: 'h2h_1h' }, 'h1'), true);
eq('period h1 keeps a segment h1 row', matchesPeriod({ segment: 'h1', market: 'totals' }, 'h1'), true);
eq('period h1 drops a q1 row', matchesPeriod({ market: 'spreads_q1' }, 'h1'), false);
eq('period h1 drops a full-game row', matchesPeriod({ market: 'totals' }, 'h1'), false);
eq('period full keeps full game', matchesPeriod({ market: 'totals' }, 'full'), true);
eq('period full drops an interval', matchesPeriod({ segment: 'first5' }, 'full'), false);
eq('period intervals keeps any interval', matchesPeriod({ segment: 'p3' }, 'intervals'), true);
eq('period all keeps everything', matchesPeriod({ segment: 'p3' }, 'all'), true);
eq('a prop never matches an interval', matchesPeriod({ market: 'player_points', segment: 'full' }, 'q1'), false);

console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
