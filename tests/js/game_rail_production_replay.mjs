// Replay the REAL rail derivation over a REAL production payload pair.
//
// The fixture-based harness beside this file (`game_rail_derive.test.mjs`)
// proves the logic; this proves the logic against what production actually
// served, which is the thing the lane owes and the thing a fixture can always
// be accused of having been shaped to fit.
//
// Usage:
//   node tests/js/game_rail_production_replay.mjs <dir>
//     <dir>/chips2.json  <- GET  /api/board/game-chips?sports=<all eight>
//     <dir>/board.json   <- POST /api/intelligence/query
//                           {"question":"top edges today","mode":"recommendation",
//                            "timing":"all","background":false,"force_refresh":false}
//
// Point it at a checkout with the fix and at one without it to get the A/B.
// It prints, per sport: groups, how many resolved a chip, and every card the
// rail would seat -- so a duplicate is visible as two cards naming one game.
//
// `recommendationState` is stubbed to "pregame". It feeds only `hasLive` and
// `allFinal`, which are DISPLAY fields; it cannot move a row between groups or
// change how many cards are seated, which is all this script measures.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const dir = process.argv[2];
if (!dir) { console.error('usage: node game_rail_production_replay.mjs <payload-dir>'); process.exit(2); }

const here = path.dirname(fileURLToPath(import.meta.url));
const template = path.resolve(here, '../../syndicate/templates/intelligence.html');
const html = fs.readFileSync(template, 'utf8');
function slice(a, b) {
  const i = html.indexOf(a), j = html.indexOf(b, i + 1);
  if (i < 0 || j < 0 || j <= i) throw new Error(`slice ${a} .. ${b} not found`);
  return html.slice(i, j);
}
const src = [
  slice('const CLUB_AFFIXES', '// `layer2-board-chip-race`. The FIRST call to `renderGameCards`'),
  slice('function chipForGame', 'function chipTeamRow'),
  slice('function displayMatchup', 'function gameKey'),
  slice('function gameKey', '// A whole-numbered line must keep its decimal'),
  slice('function deriveGameCards', 'function renderGameCards'),
].join(String.fromCharCode(10));

let state = { sport: 'all', date: null };
let gameChipsById = new Map();
let gameChipsByMatchup = new Map();
let gameChipsByCanonical = new Map();
let gameChipsByMatchupLoose = new Map();
let gameKeyMergeMap = new Map();
const recommendationState = () => 'pregame';

const fn = new Function('state','gameChipsById','gameChipsByMatchup','gameChipsByCanonical','gameChipsByMatchupLoose','gameKeyMergeMap','recommendationState',
  src + '; return { deriveGameCards, chipForGame, normalizeClubName };');
const built = fn(state,gameChipsById,gameChipsByMatchup,gameChipsByCanonical,gameChipsByMatchupLoose,gameKeyMergeMap,recommendationState);

// Index the chips exactly as loadGameChips() does, collision removal included.
const chips = JSON.parse(fs.readFileSync(path.join(dir, 'chips2.json'), 'utf8')).chips || [];
const looseCollisions = new Set(), canonicalCollisions = new Set();
// The REAL normalizeClubName, handed back out of the Function scope rather
// than re-evaluated here -- it closes over CLUB_AFFIXES, and a second copy
// would be free to drift from the one the page runs.
const norm = built.normalizeClubName;
for (const chip of chips) {
  const sport = String(chip.sport || '').toLowerCase();
  const key = String(chip.game_key || '').trim();
  if (key) gameChipsById.set(`${sport}|${key}`, chip);
  const matchup = String(chip.matchup || '').trim().toLowerCase();
  if (matchup) gameChipsByMatchup.set(`${sport}|${matchup}`, chip);
  const awayName = String((chip.away || {}).name || '').trim().toLowerCase();
  const homeName = String((chip.home || {}).name || '').trim().toLowerCase();
  if (awayName && homeName) gameChipsByMatchup.set(`${sport}|${awayName} @ ${homeName}`, chip);
  const awayKey = String((chip.away || {}).key || '').trim().toLowerCase();
  const homeKey = String((chip.home || {}).key || '').trim().toLowerCase();
  if (awayKey && homeKey) {
    const c = `${sport}|${awayKey} @ ${homeKey}`;
    if (gameChipsByCanonical.has(c)) canonicalCollisions.add(c); else gameChipsByCanonical.set(c, chip);
  }
  if (awayName && homeName) {
    const l = `${sport}|${norm(awayName)} @ ${norm(homeName)}`;
    if (gameChipsByMatchupLoose.has(l)) looseCollisions.add(l); else gameChipsByMatchupLoose.set(l, chip);
  }
}
for (const k of looseCollisions) gameChipsByMatchupLoose.delete(k);
for (const k of canonicalCollisions) gameChipsByCanonical.delete(k);

const board = JSON.parse(fs.readFileSync(path.join(dir, 'board.json'), 'utf8'));
const resp = board.response || board;
const items = (resp.top_opportunities && resp.top_opportunities.length)
  ? resp.top_opportunities : (resp.recommendations || []);

state.date = process.argv[3] || null; // null = the combined multi-day window
const cards = built.deriveGameCards(items);

const bySport = new Map();
for (const c of cards) {
  const s = (c.sportSlug || c.sport || '?').toLowerCase();
  if (!bySport.has(s)) bySport.set(s, []);
  bySport.get(s).push(c);
}
console.log(`chips=${chips.length} rows=${items.length} state.date=${state.date} -> ${cards.length} card(s)`);
let chipless = 0;
for (const [sport, list] of [...bySport].sort()) {
  const noChip = list.filter((c) => !built.chipForGame(c)).length;
  chipless += noChip;
  console.log(`  ${sport.padEnd(8)} cards=${String(list.length).padStart(3)}  chip-less=${noChip}`);
}
console.log(`  TOTAL chip-less cards: ${chipless}`);

// A duplicate is two cards naming one real game.
//
// THE DETECTOR MUST NOT REUSE `chipForGame`, and the first version of this
// script did. `chipForGame` IS the code under test: in the control it returns
// null for exactly the cards that are duplicated, so grouping cards by the chip
// IT resolves reported "0 chips seating more than one card" in BOTH states --
// a clean bill of health produced by the defect itself. That is the instrument
// reading healthy because it cannot read unhealthy.
//
// So the join here is the script's OWN, and it takes the sport from a field
// the defect cannot touch: `group.key`, which `gameKey` builds as
// `${sport_slug}|${id}` (or `chip|${slug}|...` for a seeded card) in BOTH
// versions. Same four indexes, slug-keyed, always.
function slugOfCard(c) {
  const parts = String(c.key || '').split('|');
  return (parts[0] === 'chip' ? parts[1] : parts[0] || '').toLowerCase();
}
function resolveChip(c) {
  const sport = slugOfCard(c);
  if (gameChipsById.has(c.key)) return gameChipsById.get(c.key);
  const matchup = String(c.matchup || '').trim().toLowerCase();
  const exact = gameChipsByMatchup.get(`${sport}|${matchup}`);
  if (exact) return exact;
  const ak = String(c.awayKey || '').trim().toLowerCase();
  const hk = String(c.homeKey || '').trim().toLowerCase();
  if (ak && hk) {
    const canonical = gameChipsByCanonical.get(`${sport}|${ak} @ ${hk}`);
    if (canonical) return canonical;
  }
  const sides = matchup.split(' @ ');
  if (sides.length !== 2) return null;
  return gameChipsByMatchupLoose.get(`${sport}|${norm(sides[0])} @ ${norm(sides[1])}`) || null;
}
const perChip = new Map();
for (const c of cards) {
  const chip = resolveChip(c);
  if (!chip) continue;
  if (!perChip.has(chip)) perChip.set(chip, []);
  perChip.get(chip).push(c);
}
const chipDupes = [...perChip].filter(([, l]) => l.length > 1);
// Second detector, for the shape the first cannot see: two cards for a game
// with NO chip at all. Sport comes from the key here too, for the same reason.
const pairIndex = new Map();
for (const c of cards) {
  const sides = String(c.matchup || '').toLowerCase().split(' @ ');
  if (sides.length !== 2) continue;
  const k = `${slugOfCard(c)}|${norm(sides[0])} @ ${norm(sides[1])}`;
  if (!pairIndex.has(k)) pairIndex.set(k, []);
  pairIndex.get(k).push(c);
}
const pairDupes = [...pairIndex].filter(([, l]) => l.length > 1);

console.log();
console.log(`chips seating MORE THAN ONE card: ${chipDupes.length}`);
for (const [chip, l] of chipDupes) {
  console.log(`   ${chip.sport} ${chip.matchup} (${chip.game_key}) -> ` +
    l.map((c) => `[${c.sport} "${c.matchup}" n=${c.count}]`).join(' + '));
}
console.log(`normalized team pairs seating MORE THAN ONE card: ${pairDupes.length}`);
for (const [k, l] of pairDupes) {
  console.log(`   ${k} -> ` + l.map((c) => `[${c.sport} "${c.matchup}" n=${c.count}]`).join(' + '));
}
process.exitCode = (chipDupes.length || pairDupes.length) ? 1 : 0;
