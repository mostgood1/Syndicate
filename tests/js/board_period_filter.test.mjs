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

const isIntervalRow = (new Function(
  `${grab(/const FULL_GAME_SEGMENTS = [^\n]+/, 'FULL_GAME_SEGMENTS')}\n`
  + `${grab(/const SEGMENT_SUFFIX_RE = [^\n]+/, 'SEGMENT_SUFFIX_RE')}\n`
  + `${extract('isIntervalRow')}\nreturn isIntervalRow;`
))();

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

console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
