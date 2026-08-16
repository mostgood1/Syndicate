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
const fn = new Function('state','gameChipsById','gameChipsByMatchup','gameKeyMergeMap','gameKey','displayMatchup','recommendationState','chipForGame',
  src + '; return deriveGameCards;');
const deriveGameCards = fn(state,gameChipsById,gameChipsByMatchup,gameKeyMergeMap,gameKey,displayMatchup,recommendationState,chipForGame);

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
  mkChip('soccer','g-soc','MMM','NNN','pregame','2026-08-16T23:00:00Z'),    // today, but no board rows
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
console.log('ASSERT a no-coverage SPORT is excluded  :', !n2.includes('MMM @ NNN') ? 'PASS' : 'FAIL');
console.log('ASSERT a today chip in-sport is kept    :', n2.includes('III @ JJJ') ? 'PASS' : 'FAIL');
console.log('ASSERT 00:30Z is yesterday CT, excluded :', !n2.includes('OOO @ PPP') ? 'PASS' : 'FAIL');
