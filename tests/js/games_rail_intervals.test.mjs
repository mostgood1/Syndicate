// Interval projections on the Games-rail cards (lane basketball-interval-projections, 2026-11-07).
//
// User: "need the game rail cards to indicate the interval projections", then
// "we need college qtr/half projections back". The server puts an `intervals`
// block on each basketball chip (`game_chip_intervals.py`); this pins how the
// card shows it, against the page's OWN `chipIntervals` (extracted, not
// restated), and that the card template calls it.
//
// Run it directly:   node tests/js/games_rail_intervals.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const template = process.env.TEMPLATE || path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html');
const html = fs.readFileSync(template, 'utf8').split('\r\n').join('\n');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

// ---------------------------------------------------------------- wiring
const fnMatch = html.match(/ {2}function chipIntervals\(chip\)[\s\S]*?\n {2}}\n/);
check('chipIntervals exists', Boolean(fnMatch), true);
check('the card template calls it for non-final chips', /chip\.state !== "final" \? chipIntervals\(chip\) : ""/.test(html), true);
if (!fnMatch) { console.log(`\n${failures} assertion(s) failed`); process.exit(1); }

const escapeHtml = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const { chipIntervals } = new Function('escapeHtml', `${fnMatch[0]}; return { chipIntervals };`)(escapeHtml);

const text = (out) => out.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- behaviour
// Men's college pregame: halves + T, spread named for the favourite, total, no win% (the block carries none).
const pre = {
  sport: 'ncaab', state: 'pregame', away: { abbr: 'PROV' }, home: { abbr: 'NEB' },
  intervals: {
    source: 'pregame_sim', sims: 2000, as_of: '2026-11-07T12:00:00Z',
    periods: [
      { key: 'h1', label: '1H', away: 34.4, home: 36.1, state: 'ahead' },
      { key: 'h2', label: '2H', away: 38.6, home: 40.9, state: 'ahead' },
    ],
    final: { away: 73.0, home: 77.0, total: 150.0, home_margin: 4.0, home_win_prob: null },
  },
};
const preOut = chipIntervals(pre);
check('pregame box carries the PROJ tag and both halves', /PROJ 1H 2H T/.test(text(preOut)), true);
check('pregame rows are rounded projected points + projected final', /PROV 34 39 73 NEB 36 41 77/.test(text(preOut)), true);
check('pregame line: favourite spread and total', /Proj NEB −4\.0 · O\/U 150\.0$/.test(text(preOut)), true);
check('no win % when the block has none', /%/.test(text(preOut)), false);

// Live: settled periods are left to the real line score; the period in progress is marked; win% shown.
const live = {
  sport: 'wncaab', state: 'live', away: { abbr: 'SOU' }, home: { abbr: 'ILL' },
  intervals: {
    source: 'live_resim', sims: 200, as_of: '2026-11-07T20:02:30+00:00',
    periods: [
      { key: 'q1', label: 'Q1', away: 3, home: 30, state: 'settled' },
      { key: 'q2', label: 'Q2', away: 12.6, home: 20.2, state: 'in_progress' },
      { key: 'q3', label: 'Q3', away: 12.4, home: 20.8, state: 'ahead' },
      { key: 'q4', label: 'Q4', away: 12.2, home: 20.6, state: 'ahead' },
    ],
    final: { away: 48.6, home: 81.8, total: 130.4, home_margin: 33.3, home_win_prob: 0.99 },
  },
};
const liveOut = chipIntervals(live);
check('live box drops the settled quarter', /PROJ Q2\* Q3 Q4 T/.test(text(liveOut)), true);
check('live in-progress cell is marked current', /is-current/.test(liveOut), true);
check('live line: projected final with win %', /Proj final ILL −33\.3 · O\/U 130\.4 · ILL 99%$/.test(text(liveOut)), true);

// An away favourite, and a pick'em.
const awayFav = JSON.parse(JSON.stringify(pre));
awayFav.intervals.final.home_margin = -2.5;
awayFav.intervals.final.home_win_prob = 0.31;
check('away favourite is named with its own spread and win %', /Proj PROV −2\.5 · O\/U 150\.0 · PROV 69%$/.test(text(chipIntervals(awayFav))), true);
const pk = JSON.parse(JSON.stringify(pre));
pk.intervals.final.home_margin = 0;
check('a zero margin reads PK', /Proj PK ·/.test(text(chipIntervals(pk))), true);

// No block, no box -- the card is exactly as before.
check('no intervals renders nothing', chipIntervals({ sport: 'ncaab', state: 'pregame' }), '');
check('empty periods render nothing', chipIntervals({ intervals: { periods: [] } }), '');

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
