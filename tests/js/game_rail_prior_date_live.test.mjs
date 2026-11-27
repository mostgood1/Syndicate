// After midnight CT the Today rail keeps a game from the evening before that is STILL LIVE.
//
// Measured by the rail monitor (findings 2026-11-26, R-L): at the 12:03 AM CST reading 11-27, Baylor @ Gonzaga
// and Texas Tech @ Oregon (11-26, tips 10:53 / 10:57 PM CST) had no card on Today, after 15 rows each at 11:43 PM.
// The server now carries such a chip onto today's chip list, tagged `carried_onto` (`/api/board/game-chips
// ?carry_prior_live=1`). This checks the page's half: the rail's two date filters keep a LIVE chip whose
// `carried_onto` is the rail's own date, and nothing else from another day.
//
// Run:  node tests/js/game_rail_prior_date_live.test.mjs
// Discrimination: RAIL_TEMPLATE=<pre-change intelligence.html> node tests/js/game_rail_prior_date_live.test.mjs
// must FAIL (the carried game has no card there).

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const template = process.env.RAIL_TEMPLATE || path.resolve(here, '../../syndicate/templates/intelligence.html');
const html = fs.readFileSync(template, 'utf8');
function slice(fromMarker, toMarker) {
  const a = html.indexOf(fromMarker);
  const b = html.indexOf(toMarker, a + 1);
  if (a < 0 || b < 0 || b <= a) throw new Error(`slice ${fromMarker} .. ${toMarker} not found in ` + template);
  return html.slice(a, b);
}
// The same three slices as game_rail_derive.test.mjs: the real chip join and the real rail derivation.
const src = [
  slice('const CLUB_AFFIXES', '// `layer2-board-chip-race`. The FIRST call to `renderGameCards`'),
  slice('function chipForGame', 'function chipTeamRow'),
  slice('function deriveGameCards', 'function renderGameCards'),
].join(String.fromCharCode(10));

let state = { sport: 'all', date: '2026-11-27' };
let gameChipsById = new Map();
let gameChipsByMatchup = new Map();
let gameChipsByCanonical = new Map();
let gameChipsByMatchupLoose = new Map();
let gameKeyMergeMap = new Map();
const gameKey = (i) => `${i.sport_slug || i.sport}|${i.event_id}`;
const displayMatchup = (i) => i.matchup || '';
const recommendationState = (i) => i.market_state || 'pregame';
const fn = new Function('state','gameChipsById','gameChipsByMatchup','gameChipsByCanonical','gameChipsByMatchupLoose','gameKeyMergeMap','gameKey','displayMatchup','recommendationState',
  src + '; return { deriveGameCards };');
const { deriveGameCards } = fn(state,gameChipsById,gameChipsByMatchup,gameChipsByCanonical,gameChipsByMatchupLoose,gameKeyMergeMap,gameKey,displayMatchup,recommendationState);

function mkChip(sport, key, away, home, st, start, extra) {
  return Object.assign({ sport, game_key: key, matchup: `${away} @ ${home}`, state: st, start_time_utc: start,
    away: { abbr: away, name: away }, home: { abbr: home, name: home } }, extra || {});
}
const CARRY = { carried_from_date: '2026-11-26', carried_onto: '2026-11-27' };
const chips = [
  // Today's own games (Central 11-27).
  mkChip('ncaab', 'today-pre', 'AAA', 'BBB', 'pregame', '2026-11-27T18:00:00Z'),
  // 11-26's late games, carried by the server while live.
  mkChip('ncaab', 'bay-gonz', 'BAY', 'GONZ', 'live', '2026-11-27T04:53:00Z', CARRY),
  mkChip('ncaab', 'ttu-ore', 'TTU', 'ORE', 'live', '2026-11-27T04:57:00Z', CARRY),
  // A prior-day LIVE chip WITHOUT the tag (a multi-day feed's own entry): still another day's game.
  mkChip('nfl', 'untagged', 'CCC', 'DDD', 'live', '2026-11-27T01:20:00Z'),
  // A carried chip whose game has since ended: the tag alone does not hold a card.
  mkChip('ncaab', 'carried-final', 'EEE', 'FFF', 'final', '2026-11-27T03:00:00Z', CARRY),
  // An older day's chip (soccer's multi-day feed).
  mkChip('soccer', 'older', 'GGG', 'HHH', 'final', '2026-11-25T20:00:00Z'),
];
function seat(list) {
  gameChipsById.clear(); gameChipsByMatchup.clear(); gameChipsByCanonical.clear(); gameChipsByMatchupLoose.clear();
  for (const c of list) {
    gameChipsById.set(`${c.sport}|${c.game_key}`, c);
    gameChipsByMatchup.set(`${c.sport}|${c.matchup.toLowerCase()}`, [c]);
  }
}
seat(chips);

let failures = 0;
function check(label, ok, detail) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${detail ? ' -- ' + detail : ''}`);
  if (!ok) failures += 1;
}
const keysOf = (cards) => cards.map((g) => g.ownGameKey || g.key).sort();

// 1. Today tab, chip-seeded cards only (the 11-26 case: the board held no rows for either game).
state.date = '2026-11-27';
const today = deriveGameCards([]);
const todayKeys = keysOf(today);
check('carried live game Baylor @ Gonzaga keeps a card on Today', todayKeys.includes('bay-gonz'), todayKeys.join(','));
check('carried live game Texas Tech @ Oregon keeps a card on Today', todayKeys.includes('ttu-ore'), todayKeys.join(','));
check("today's own game is still there", todayKeys.includes('today-pre'), todayKeys.join(','));
check('an untagged prior-day live chip stays off Today', !todayKeys.includes('untagged'), todayKeys.join(','));
check('a carried chip that is no longer live stays off Today', !todayKeys.includes('carried-final'), todayKeys.join(','));
check("an older day's chip stays off Today", !todayKeys.includes('older'), todayKeys.join(','));
const gonz = today.find((g) => (g.ownGameKey || g.key) === 'bay-gonz');
check('the carried card reads live', Boolean(gonz && gonz.hasLive), gonz ? `hasLive=${gonz.hasLive}` : 'no card');

// 2. A candidate-backed group joined to a carried chip (rows on the board) keeps its card too.
const withRows = deriveGameCards([
  { sport: 'ncaab', sport_slug: 'ncaab', event_id: 'ttu-ore', matchup: 'TTU @ ORE', market_state: 'live', game_date: '2026-11-26' },
]);
const rowCard = withRows.find((g) => g.count > 0);
check('a carried game with board rows keeps its card, with its rows', Boolean(rowCard), keysOf(withRows).join(','));

// 3. Tomorrow tab: the tag names the day it was carried ONTO, so it never matches tomorrow.
state.date = '2026-11-28';
const tomorrowKeys = keysOf(deriveGameCards([]));
check('a carried chip never shows on the Tomorrow tab', !tomorrowKeys.includes('bay-gonz') && !tomorrowKeys.includes('ttu-ore'), tomorrowKeys.join(','));

// 4. The prior day's own tab (a page loaded before midnight keeps that date): its games are its own.
state.date = '2026-11-26';
const priorKeys = keysOf(deriveGameCards([]));
check("the prior day's own tab still shows its games", priorKeys.includes('bay-gonz') && priorKeys.includes('carried-final'), priorKeys.join(','));
check("the prior day's own tab does not take today's games", !priorKeys.includes('today-pre'), priorKeys.join(','));

console.log(failures ? `\n${failures} FAILED` : '\nall passed');
process.exit(failures ? 1 : 0);
