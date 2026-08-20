// Game-rail derivation: every scheduled game appears, and finals sort last.
//
// WHY A NODE HARNESS IN A PYTEST REPO. `deriveGameCards` lives inside an IIFE
// in `syndicate/templates/intelligence.html`, so it is not importable and not
// reachable from Python. The alternative -- driving the real page -- needs the
// combined-board hydration path, which on local mirror data takes minutes and
// exercises eight sports to test one comparator.
//
// Run it directly:   node tests/js/game_rail_derive.test.mjs
// It is NOT wired into pytest or the migration gate; it is a manual check kept
// beside the change it verifies.
//
// MEASURED 2026-08-16, and the test DISCRIMINATES -- run against the pre-change
// function it fails 4 of 5 assertions:
//
//     pre-change   3 cards   live, FINAL, pregame     <- final second, no-opp game absent
//     post-change  4 cards   live, pregame(0), pregame, FINAL
//
// The fixture is deliberately adversarial on the sort: the FINAL game has the
// EARLIEST start time, which is what made finals collect at the head of the
// rail (earliest games finish first).

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

// Extract the function from the template AT RUN TIME. An earlier version of
// this harness read a copy that had been dumped to a temp file, and silently
// tested a stale one -- it reported 4 failures against code that passes.
// Reading the template is the only version that cannot go stale.
const here = path.dirname(fileURLToPath(import.meta.url));
const template = path.resolve(here, '../../syndicate/templates/intelligence.html');
const html = fs.readFileSync(template, 'utf8');
const start = html.indexOf('function deriveGameCards');
const end = html.indexOf('function renderGameCards');
if (start < 0 || end < 0 || end <= start) {
  throw new Error('deriveGameCards / renderGameCards not found in ' + template);
}
const src = html.slice(start, end);

// Minimal stand-ins for the page globals deriveGameCards reads.
let state = { sport: 'all', date: '2026-08-16' };
let gameChipsById = new Map();
let gameChipsByMatchup = new Map();
let gameKeyMergeMap = new Map();
const gameKey = (i) => `${i.sport}|${i.event_id}`;
const displayMatchup = (i) => i.matchup || '';
const recommendationState = (i) => i.market_state || 'pregame';
function chipForGame(group) {
  if (gameChipsById.has(group.key)) return gameChipsById.get(group.key);
  const sport = String(group.sport||'').toLowerCase();
  const matchup = String(group.matchup||'').trim().toLowerCase();
  return gameChipsByMatchup.get(`${sport}|${matchup}`) || null;
}
// `deriveGameCards` REASSIGNS gameKeyMergeMap (`gameKeyMergeMap = new Map()`),
// and here that name is a Function PARAMETER -- so the assignment rebinds the
// parameter and the outer `let` above keeps pointing at the original, forever
// empty, Map. Reading the outer one makes the merge map look like it was never
// populated. `getMergeMap` closes over the parameter binding, so it sees what
// the function actually built.
const fn = new Function('state','gameChipsById','gameChipsByMatchup','gameKeyMergeMap','gameKey','displayMatchup','recommendationState','chipForGame',
  src + '; return { deriveGameCards, getMergeMap: () => gameKeyMergeMap };');
const built = fn(state,gameChipsById,gameChipsByMatchup,gameKeyMergeMap,gameKey,displayMatchup,recommendationState,chipForGame);
const deriveGameCards = built.deriveGameCards;
const getMergeMap = built.getMergeMap;

function mkChip(sport,key,away,home,st,start){
  return {sport,game_key:key,matchup:`${away} @ ${home}`,state:st,start_time_utc:start,
          away:{abbr:away,name:away},home:{abbr:home,name:home}};
}
// three games: one FINAL (earliest start), one LIVE, one PREGAME (latest)
const chips = [
  mkChip('mlb','g-final','AAA','BBB','final','2026-08-16T16:00:00Z'),
  mkChip('mlb','g-live','CCC','DDD','live','2026-08-16T18:00:00Z'),
  mkChip('mlb','g-pre','EEE','FFF','pregame','2026-08-16T23:00:00Z'),
  mkChip('mlb','g-noopp','GGG','HHH','pregame','2026-08-16T20:00:00Z'), // NO board rows
];
for (const c of chips) {
  gameChipsById.set(`mlb|${c.game_key}`, c);
  gameChipsByMatchup.set(`mlb|${c.matchup.toLowerCase()}`, c);
}
// board rows for only 3 of the 4 games
const items = [
  {sport:'mlb',sport_slug:'mlb',event_id:'g-final',matchup:'AAA @ BBB',market_state:'final'},
  {sport:'mlb',sport_slug:'mlb',event_id:'g-live', matchup:'CCC @ DDD',market_state:'live'},
  {sport:'mlb',sport_slug:'mlb',event_id:'g-pre',  matchup:'EEE @ FFF',market_state:'pregame'},
];
const out = deriveGameCards(items);
console.log('rail cards:', out.length, '(expect 4 — the 4th has NO board rows)');
console.log('order:');
for (const g of out) {
  const chip = chipForGame(g);
  console.log(`   ${g.matchup.padEnd(12)} state=${(chip?chip.state:'?').padEnd(8)} count=${g.count}`);
}
const names = out.map(g=>g.matchup);
console.log();
console.log('ASSERT every scheduled game present     :', out.length === 4 ? 'PASS' : 'FAIL');
console.log('ASSERT the no-opportunity game appears  :', names.includes('GGG @ HHH') ? 'PASS' : 'FAIL');
console.log('ASSERT it carries count 0               :', (out.find(g=>g.matchup==='GGG @ HHH')||{}).count === 0 ? 'PASS' : 'FAIL');
console.log('ASSERT live game is FIRST               :', names[0] === 'CCC @ DDD' ? 'PASS' : 'FAIL');
console.log('ASSERT final game is LAST               :', names[names.length-1] === 'AAA @ BBB' ? 'PASS' : 'FAIL');

// --------------------------------------------------------------------------
// The two seeding filters, from the production defect on 2026-08-16: an
// unfiltered seed put 108 cards on the rail against 18, because
// /api/board/game-chips is deliberately MULTI-DAY (90 soccer chips across 10
// Central dates, only 21 of them today) and because soccer has no board
// coverage at all.
// --------------------------------------------------------------------------
gameChipsById.clear(); gameChipsByMatchup.clear(); gameKeyMergeMap.clear();
const mixed = [
  mkChip('mlb','g-today','III','JJJ','pregame','2026-08-16T23:00:00Z'),     // today CT, board sport
  mkChip('mlb','g-nextwk','KKK','LLL','pregame','2026-08-22T23:00:00Z'),    // NOT today
  mkChip('soccer','g-soc','MMM','NNN','pregame','2026-08-16T23:00:00Z'),    // today, no board rows -> count-0 card
  // 00:30Z on the 16th is 7:30P CT on the FIFTEENTH -- the exact shape that
  // makes UTC-date bucketing file yesterday's game under today.
  mkChip('mlb','g-utctrap','OOO','PPP','pregame','2026-08-16T00:30:00Z'),
];
for (const c of mixed) {
  gameChipsById.set(`${c.sport}|${c.game_key}`, c);
  gameChipsByMatchup.set(`${c.sport}|${c.matchup.toLowerCase()}`, c);
}
const out2 = deriveGameCards([
  {sport:'mlb',sport_slug:'mlb',event_id:'g-seed',matchup:'QQQ @ RRR',market_state:'pregame'},
]);
const n2 = out2.map(g=>g.matchup);
console.log();
console.log('rail with mixed chips:', n2.join(' | ') || '(none)');
console.log('ASSERT a NON-today chip is excluded     :', !n2.includes('KKK @ LLL') ? 'PASS' : 'FAIL');
// REVERSED 2026-08-16, and the reversal is the point. An earlier version also
// required the chip's sport to appear in the board rows. That took the rail
// from 108 cards to 18 and DELETED SOCCER, which had 21 real games that day --
// reported live. The rail is a SCHEDULE: a sport with no priced opportunity is
// precisely the count-0 case, not a reason to hide its games.
console.log('ASSERT a today game with NO rows appears:', n2.includes('MMM @ NNN') ? 'PASS' : 'FAIL');
console.log('ASSERT ...and it is a count-0 card       :', (out2.find(g=>g.matchup==='MMM @ NNN')||{}).count === 0 ? 'PASS' : 'FAIL');
console.log('ASSERT a today chip in-sport is kept    :', n2.includes('III @ JJJ') ? 'PASS' : 'FAIL');
console.log('ASSERT 00:30Z is yesterday CT, excluded :', !n2.includes('OOO @ PPP') ? 'PASS' : 'FAIL');

// --------------------------------------------------------------------------
// ONE CARD PER REAL GAME WHEN THE SAME GAME ARRIVES IN TWO TEXT FORMS.
//
// Production defect, 2026-08-20: the Layer 2 rail listed today's NFL preseason
// games TWICE. Two pipelines seat rows for the same game with different ids AND
// different matchup text --
//
//   nfl|401873286                        "LV @ HOU"                             1 row
//     ESPN id, candidate_type=game, board_lane=watchlist
//   nfl|a697012ab3bb18d3549ff1bce61ed4da  "Las Vegas Raiders @ Houston Texans"  10 rows
//     OddsAPI event id, source=layer2_shortlist, board_lane=opportunity
//
// -- and BOTH resolved to the same chip (one by id, one via the #365 full-name
// index). The merge pass could not see it, because it bucketed on matchup TEXT
// before ever comparing chips.
//
// THIS SECTION DISCRIMINATES. Against the pre-change function, case A fails
// (2 cards, not 1). Cases B and C pass before and after: B is the guard that
// keeps the fix from over-merging, C is #165 follow-up #3, which the fix must
// not regress. A test where all three pass on both versions would prove nothing.
// --------------------------------------------------------------------------
function resetChips() {
  gameChipsById.clear();
  gameChipsByMatchup.clear();
  // No gameKeyMergeMap.clear() here: deriveGameCards replaces that map on every
  // call, and the binding visible at THIS scope is not the one it replaces
  // (see getMergeMap above). Clearing it would be theatre.
}
// Indexed the way loadGameChips() does it: by id, by ABBR matchup, and by FULL
// NAMES (#365). The full-name index is what the OddsAPI-form group joins on.
function seatChip(chip, awayName, homeName) {
  gameChipsById.set(`${chip.sport}|${chip.game_key}`, chip);
  gameChipsByMatchup.set(`${chip.sport}|${chip.matchup.toLowerCase()}`, chip);
  gameChipsByMatchup.set(`${chip.sport}|${awayName.toLowerCase()} @ ${homeName.toLowerCase()}`, chip);
}
// 2026-08-21T00:00Z is 7:00P CT on the TWENTIETH -- the real LV @ HOU kickoff,
// and a date the UTC clock would file under the wrong day.
const nflChip = mkChip('nfl', '401873286', 'LV', 'HOU', 'pregame', '2026-08-21T00:00:00Z');
const ESPN_ROW = {sport:'nfl',sport_slug:'nfl',event_id:'401873286',
                  matchup:'LV @ HOU',market_state:'pregame',game_date:'2026-08-20'};
const ODDS_ROW = {sport:'nfl',sport_slug:'nfl',event_id:'a697012ab3bb18d3549ff1bce61ed4da',
                  matchup:'Las Vegas Raiders @ Houston Texans',market_state:'pregame',game_date:'2026-08-20'};

state.date = '2026-08-20';
state.sport = 'all';

// --- CASE A: the reported defect. Same game, same day, two text forms. ------
resetChips();
seatChip(nflChip, 'Las Vegas Raiders', 'Houston Texans');
const outA = deriveGameCards([ESPN_ROW, ODDS_ROW]);
console.log();
console.log('two text forms of ONE game ->', outA.length, 'card(s):', outA.map(g=>g.matchup).join(' | '));
console.log('ASSERT abbr + full-name forms merge     :', outA.length === 1 ? 'PASS' : 'FAIL');
// The rows must not be lost in the merge: 1 + 1, and BOTH keys resolve to the
// surviving card, or clicking it would filter the board to one family's rows.
console.log('ASSERT the merged card keeps both rows  :', outA[0] && outA[0].count === 2 ? 'PASS' : 'FAIL');
const canonical = outA[0] ? outA[0].key : null;
const mergeMap = getMergeMap();
const bothResolve = mergeMap.get('nfl|401873286') === canonical
                 && mergeMap.get('nfl|a697012ab3bb18d3549ff1bce61ed4da') === canonical;
console.log('ASSERT both ids resolve to that card    :', bothResolve ? 'PASS' : 'FAIL');

// --- CASE B: the guard. Same TEAMS, different DAYS, must stay two cards. ----
// gameChipsByMatchup is keyed on the team pair with NO date, so a LATER game
// between the same two teams text-resolves to TODAY's chip. Merging on that
// would silently delete a real game from the schedule -- #165 follow-up #1,
// which cost two genuinely different games their card.
resetChips();
seatChip(nflChip, 'Las Vegas Raiders', 'Houston Texans');
state.date = null; // the combined multi-day window, where both days are in play
const outB = deriveGameCards([ESPN_ROW, {...ODDS_ROW, game_date:'2026-08-27'}]);
console.log();
console.log('same teams on TWO days ->', outB.length, 'card(s):', outB.map(g=>g.matchup).join(' | '));
console.log('ASSERT a later game is NOT merged away  :', outB.length === 2 ? 'PASS' : 'FAIL');

// --- CASE C: #165 follow-up #3 must not regress. ----------------------------
// Same matchup TEXT, and the stray duplicate carries its own RESOLVABLE BUT
// WRONG date (824892 stamped 07-31 while showing the same live score as 824894,
// dated 07-30). Same-text groups therefore merge UNCONDITIONALLY -- the date
// guard in case B applies only ACROSS text forms, and adding it here would
// stop merging exactly the case that motivated the merge pass.
resetChips();
const mlbChip = mkChip('mlb','824894','WSH','ATL','live','2026-08-20T23:00:00Z');
seatChip(mlbChip, 'Washington Nationals', 'Atlanta Braves');
const outC = deriveGameCards([
  {sport:'mlb',sport_slug:'mlb',event_id:'824894',matchup:'WSH @ ATL',market_state:'live',game_date:'2026-08-20'},
  {sport:'mlb',sport_slug:'mlb',event_id:'824892',matchup:'WSH @ ATL',market_state:'live',game_date:'2026-07-31'},
]);
console.log();
console.log('same text, duplicate has a WRONG date ->', outC.length, 'card(s)');
console.log('ASSERT #165 follow-up #3 still merges   :', outC.length === 1 ? 'PASS' : 'FAIL');
