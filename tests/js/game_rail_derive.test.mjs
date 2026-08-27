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
function slice(fromMarker, toMarker) {
  const a = html.indexOf(fromMarker);
  const b = html.indexOf(toMarker, a + 1);
  if (a < 0 || b < 0 || b <= a) {
    throw new Error(`slice ${fromMarker} .. ${toMarker} not found in ` + template);
  }
  return html.slice(a, b);
}
// `chipForGame` IS EXTRACTED, NOT RESTATED. It used to be hand-copied into
// this harness as a two-line stub reading `gameChipsById` then
// `gameChipsByMatchup`, and that stub silently diverged from the real one --
// it knew nothing of the canonical or normalized indexes, and it keyed the
// text lookup on `group.sport`, which is the field the 2026-08-27 soccer
// defect is ABOUT. A fixture that cannot express the defect cannot fail on it,
// so every assertion below was being made against a function the page does not
// run. Extracting it makes the join under test the real one, and is why
// `normalizeClubName`/`CLUB_AFFIXES` are pulled in too -- `chipForGame` calls
// them.
const src = [
  slice('const CLUB_AFFIXES', '// `layer2-board-chip-race`. The FIRST call to `renderGameCards`'),
  slice('function chipForGame', 'function chipTeamRow'),
  slice('function deriveGameCards', 'function renderGameCards'),
].join(String.fromCharCode(10));

// Minimal stand-ins for the page globals deriveGameCards reads.
let state = { sport: 'all', date: '2026-08-16' };
let gameChipsById = new Map();
let gameChipsByMatchup = new Map();
let gameChipsByCanonical = new Map();
let gameChipsByMatchupLoose = new Map();
let gameKeyMergeMap = new Map();
const gameKey = (i) => `${i.sport_slug || i.sport}|${i.event_id}`;
const displayMatchup = (i) => i.matchup || '';
const recommendationState = (i) => i.market_state || 'pregame';
// `deriveGameCards` REASSIGNS gameKeyMergeMap (`gameKeyMergeMap = new Map()`),
// and here that name is a Function PARAMETER -- so the assignment rebinds the
// parameter and the outer `let` above keeps pointing at the original, forever
// empty, Map. Reading the outer one makes the merge map look like it was never
// populated. `getMergeMap` closes over the parameter binding, so it sees what
// the function actually built.
const fn = new Function('state','gameChipsById','gameChipsByMatchup','gameChipsByCanonical','gameChipsByMatchupLoose','gameKeyMergeMap','gameKey','displayMatchup','recommendationState',
  src + '; return { deriveGameCards, chipForGame, getMergeMap: () => gameKeyMergeMap };');
const built = fn(state,gameChipsById,gameChipsByMatchup,gameChipsByCanonical,gameChipsByMatchupLoose,gameKeyMergeMap,gameKey,displayMatchup,recommendationState);
const deriveGameCards = built.deriveGameCards;
const chipForGame = built.chipForGame;
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
gameChipsById.clear(); gameChipsByMatchup.clear();
gameChipsByCanonical.clear(); gameChipsByMatchupLoose.clear();
gameKeyMergeMap.clear();
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
  gameChipsByCanonical.clear();
  gameChipsByMatchupLoose.clear();
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


// --------------------------------------------------------------------------
// `#583`: THE RAIL'S DATE FILTER MUST APPLY TO CANDIDATE-BACKED GAMES TOO.
//
// Production defect, 2026-08-26, user report: "all NFL games that are not today
// are also showing up" -- on the Today tab. `railDate` appeared exactly ONCE in
// the template, inside the loop that seats cards from UNCLAIMED CHIPS. A group
// derived from board CANDIDATES was never date-filtered, so any game with rows
// seated a card whatever the day tab said. Measured the same minute:
// /api/board/game-chips?sports=nfl returned 16 chips dated Aug 27 (1), Aug 28
// (8), Aug 29 (7) -- zero today -- and all 16 have board rows.
//
// THIS SECTION DISCRIMINATES: case A fails against the pre-change function
// (2 cards, not 1). B and C must pass in BOTH states -- B is the boundary the
// filter must not cross (the chip's date wins over the candidate's, `#165`
// follow-up #3), C is the undated-is-kept rule shared with the chip loop.
// --------------------------------------------------------------------------
resetChips();
state.date = '2026-08-26';
state.sport = 'all';

// 2026-08-27T00:30Z is 7:30P CT on the TWENTY-SIXTH -- today. The Thursday game
// at 2026-08-27T23:00Z is 6:00P CT on the twenty-seventh -- not today.
const todayChip  = mkChip('nfl','g-today','AAA','BBB','pregame','2026-08-27T00:30:00Z');
const futureChip = mkChip('nfl','g-thu','PIT','BUF','pregame','2026-08-27T23:00:00Z');
for (const c of [todayChip, futureChip]) {
  gameChipsById.set(`nfl|${c.game_key}`, c);
  gameChipsByMatchup.set(`nfl|${c.matchup.toLowerCase()}`, c);
}
const outD = deriveGameCards([
  {sport:'nfl',sport_slug:'nfl',event_id:'g-today',matchup:'AAA @ BBB',market_state:'pregame'},
  {sport:'nfl',sport_slug:'nfl',event_id:'g-thu',  matchup:'PIT @ BUF',market_state:'pregame'},
]);
const nD = outD.map(g=>g.matchup);
console.log();
console.log('candidate-backed, mixed dates ->', outD.length, 'card(s):', nD.join(' | ') || '(none)');
console.log('ASSERT a NON-today CANDIDATE game is out:', !nD.includes('PIT @ BUF') ? 'PASS' : 'FAIL');
console.log('ASSERT the today CANDIDATE game is kept :', nD.includes('AAA @ BBB') ? 'PASS' : 'FAIL');

// --- CASE B: the chip's date beats the candidate's, which can be WRONG. -----
// `#165` follow-up #3 measured gamePk 824892 stamped 2026-07-31 while showing
// the same live score and inning as 824894, dated 2026-07-30. A row whose own
// game_date says yesterday, but whose chip says today, is TODAY.
resetChips();
const misdatedChip = mkChip('mlb','g-misdated','SSS','TTT','live','2026-08-27T00:30:00Z'); // today CT
gameChipsById.set('mlb|g-misdated', misdatedChip);
gameChipsByMatchup.set(`mlb|${misdatedChip.matchup.toLowerCase()}`, misdatedChip);
const outE = deriveGameCards([
  {sport:'mlb',sport_slug:'mlb',event_id:'g-misdated',matchup:'SSS @ TTT',
   market_state:'live',game_date:'2026-08-25'},
]);
console.log('ASSERT chip date beats a wrong row date :',
  outE.map(g=>g.matchup).includes('SSS @ TTT') ? 'PASS' : 'FAIL');

// --- CASE C: an undated group is KEPT, same rule as the chip loop. ----------
// No chip resolves and the row carries no date at all. Absent evidence is not
// evidence of a different day; dropping it would hide the game entirely.
resetChips();
const outF = deriveGameCards([
  {sport:'soccer',sport_slug:'soccer',event_id:'g-undated',matchup:'UUU @ VVV',market_state:'pregame'},
]);
console.log('ASSERT an UNDATED group is still kept   :',
  outF.map(g=>g.matchup).includes('UUU @ VVV') ? 'PASS' : 'FAIL');

// --------------------------------------------------------------------------
// THE CHIP JOIN MUST USE THE SPORT SLUG, NOT THE DISPLAY LABEL.
//
// Production defect, 2026-08-27, user report: soccer games duplicated on the
// rail. Measured the same hour on /api/intelligence/query and
// /api/board/game-chips, and the shape is exact:
//
//   sport="la liga" sport_slug="soccer"  "ATH @ BAR"              26 rows
//       steam + shortlist, source la_liga/api/odds/game_odds_current.csv
//   sport="la liga" sport_slug="soccer"  "OSA @ CEL"               3 rows
//   sport="la liga" sport_slug="soccer"  "Osasuna @ Celta Vigo"    2 rows
//       ESPN id 401882924 -- the one id that DID resolve a chip
//
// Every chip index in `loadGameChips` is keyed on `chip.sport` == "soccer".
// `chipForGame` keyed its three TEXT lookups on `group.sport`, which is built
// `item.sport || item.sport_slug` and for these pipelines is the LEAGUE -- so
// it asked for `la liga|ath @ bar` against an index holding only
// `soccer|ath @ bar`. 2 of 131 groups went chip-less that should not have, and
// each duplicated its game in a DIFFERENT way: ATH @ BAR left its chip
// UNCLAIMED, which the count-0 seeding loop then seated as a second card;
// OSA @ CEL sat beside the ESPN-id group that did resolve. Both kinds are
// visible in the reported screenshot, one of each.
//
// THIS IS THE BEHAVIOURAL READ THIS LANE HAS OWED SINCE 2026-08-20 -- a LIVE
// board carrying BOTH row families for one game, which the NFL slate stopped
// reproducing before it could be observed. It is also why the harness now
// extracts the real `chipForGame` (see the top of this file): against the
// hand-copied stub these assertions could not have failed, because the stub
// had no canonical or normalized index and the defect is in which FIELD the
// lookup keys on.
//
// THIS SECTION DISCRIMINATES, and it reproduces the screenshot exactly. Run
// against the pre-change function, all three cases fail:
//
//   A  2 cards: "ATH @ BAR | ATH @ BAR"            <- chip twin, one of each
//                                                     shape, as reported
//   B  2 cards: "OSA @ CEL | Osasuna @ Celta Vigo" <- the other reported pair
//   C  4 cards                                     <- both defects at once
//
// C is the NARROWNESS guard, so read its failure carefully: it fails pre-change
// for the seeding defect, not for over-merging, and its job is what it asserts
// post-change -- that widening the join to the slug did NOT start collapsing
// two real fixtures into one. A guard that only ever passed would prove nothing
// either way; this one has to land on exactly 2.
// --------------------------------------------------------------------------

// The harness cannot call the extracted `normalizeClubName` -- it lives inside
// the Function scope -- and only needs it to build the loose index the way
// loadGameChips does. Lower-casing is enough here BECAUSE the fixtures below
// deliberately carry no accent and no club affix: the loose index therefore
// cannot be what rescues the join, so it cannot mask a slug fix that did
// nothing.
function normalizeClubNameLocal(v) { return String(v).toLowerCase(); }

function seatSoccerChip(chip, awayName, homeName, awayKey, homeKey) {
  gameChipsById.set(`${chip.sport}|${chip.game_key}`, chip);
  gameChipsByMatchup.set(`${chip.sport}|${chip.matchup.toLowerCase()}`, chip);
  gameChipsByMatchup.set(`${chip.sport}|${awayName.toLowerCase()} @ ${homeName.toLowerCase()}`, chip);
  gameChipsByCanonical.set(`${chip.sport}|${awayKey} @ ${homeKey}`, chip);
  gameChipsByMatchupLoose.set(
    `${chip.sport}|${normalizeClubNameLocal(awayName)} @ ${normalizeClubNameLocal(homeName)}`, chip);
}

state.date = '2026-08-27';
state.sport = 'all';

// 401882921 ATH @ BAR, kickoff 19:00Z = 2:00P CT on the 27th.
const barChip = {sport:'soccer', game_key:'401882921', matchup:'ATH @ BAR', state:'live',
                 start_time_utc:'2026-08-27T19:00:00Z',
                 away:{abbr:'ATH',name:'Athletic Club',key:'athletic club'},
                 home:{abbr:'BAR',name:'Barcelona',key:'barcelona'}};
// 401882924 OSA @ CEL, kickoff 18:30Z = 1:30P CT on the 27th.
const celChip = {sport:'soccer', game_key:'401882924', matchup:'OSA @ CEL', state:'live',
                 start_time_utc:'2026-08-27T18:30:00Z',
                 away:{abbr:'OSA',name:'Osasuna',key:'osasuna'},
                 home:{abbr:'CEL',name:'Celta Vigo',key:'celta vigo'}};

// --- CASE A: league-labelled rows leave the chip UNCLAIMED -> a count-0 twin.
// The steam row is FIRST on purpose: a group takes `sport` from whichever row
// it sees first, and that is what puts "la liga" on the group at all.
resetChips();
seatSoccerChip(barChip, 'Athletic Club', 'Barcelona', 'athletic club', 'barcelona');
const outG = deriveGameCards([
  {sport:'la liga',sport_slug:'soccer',event_id:'4e67f40bc51c915154f04559a7ab692c',
   matchup:'ATH @ BAR',market_state:'live',game_date:'2026-08-27'},
  {sport:'soccer',sport_slug:'soccer',event_id:'4e67f40bc51c915154f04559a7ab692c',
   matchup:'Athletic Bilbao @ Barcelona',market_state:'live',game_date:'2026-08-27',
   away_key:'athletic club',home_key:'barcelona'},
]);
console.log();
console.log('league-labelled rows + chip ->', outG.length, 'card(s):', outG.map(g=>g.matchup).join(' | '));
console.log('ASSERT no count-0 chip twin is seated   :', outG.length === 1 ? 'PASS' : 'FAIL');
console.log('ASSERT the one card KEEPS its rows      :', outG[0] && outG[0].count === 2 ? 'PASS' : 'FAIL');
// It must be the CHIP-BACKED card that survives, or the game renders as plain
// matchup text with no score while it is live -- the reported symptom.
console.log('ASSERT that card resolves the chip      :', outG[0] && chipForGame(outG[0]) === barChip ? 'PASS' : 'FAIL');

// --- CASE B: two id spaces for one game, both league-labelled. --------------
// OddsAPI event id and ESPN id, two text forms, both `sport: "la liga"`. Once
// the join uses the slug BOTH resolve chip 401882924 and the existing
// chip-identity merge collapses them; before it, only the ESPN one resolved and
// the merge pass had nothing to compare.
resetChips();
seatSoccerChip(celChip, 'Osasuna', 'Celta Vigo', 'osasuna', 'celta vigo');
const outH = deriveGameCards([
  {sport:'la liga',sport_slug:'soccer',event_id:'0b765da573acccbad3b07923f279c567',
   matchup:'OSA @ CEL',market_state:'live',game_date:'2026-08-27'},
  {sport:'la liga',sport_slug:'soccer',event_id:'401882924',
   matchup:'Osasuna @ Celta Vigo',market_state:'live',game_date:'2026-08-27'},
]);
console.log();
console.log('two id spaces, one league game ->', outH.length, 'card(s):', outH.map(g=>g.matchup).join(' | '));
console.log('ASSERT the two id spaces merge          :', outH.length === 1 ? 'PASS' : 'FAIL');
console.log('ASSERT the merged card keeps both rows  :', outH[0] && outH[0].count === 2 ? 'PASS' : 'FAIL');

// --- CASE C: the narrowness guard. Two DIFFERENT La Liga games. ------------
// Keying on the slug widens what the text indexes can REACH, so it must not
// start joining games that merely share a sport. Two real fixtures, same day,
// both league-labelled: still two cards.
resetChips();
seatSoccerChip(barChip, 'Athletic Club', 'Barcelona', 'athletic club', 'barcelona');
seatSoccerChip(celChip, 'Osasuna', 'Celta Vigo', 'osasuna', 'celta vigo');
const outI = deriveGameCards([
  {sport:'la liga',sport_slug:'soccer',event_id:'4e67f40bc51c915154f04559a7ab692c',
   matchup:'ATH @ BAR',market_state:'live',game_date:'2026-08-27'},
  {sport:'la liga',sport_slug:'soccer',event_id:'0b765da573acccbad3b07923f279c567',
   matchup:'OSA @ CEL',market_state:'live',game_date:'2026-08-27'},
]);
console.log();
console.log('two DIFFERENT La Liga games ->', outI.length, 'card(s):', outI.map(g=>g.matchup).join(' | '));
console.log('ASSERT different games stay separate    :', outI.length === 2 ? 'PASS' : 'FAIL');
