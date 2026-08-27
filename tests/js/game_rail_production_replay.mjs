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

// SYNDICATE_TEMPLATE_HTML points this at the SERVED page instead of the local
// checkout -- which is the only way to verify a deploy rather than a file:
//
//   curl -s https://<web>/intelligence -o served.html
//   SYNDICATE_TEMPLATE_HTML=served.html node tests/js/game_rail_production_replay.mjs <dir>
//
// The rendered page carries these functions verbatim (they sit in a static
// <script> block, no Jinja inside them), so the extraction below is identical.
const here = path.dirname(fileURLToPath(import.meta.url));
const template = process.env.SYNDICATE_TEMPLATE_HTML
  ? path.resolve(process.env.SYNDICATE_TEMPLATE_HTML)
  : path.resolve(here, '../../syndicate/templates/intelligence.html');
const html = fs.readFileSync(template, 'utf8').split('\r\n').join('\n');
console.log(`template: ${template}`);
function slice(a, b) {
  const i = html.indexOf(a), j = html.indexOf(b, i + 1);
  if (i < 0 || j < 0 || j <= i) throw new Error(`slice ${a} .. ${b} not found`);
  return html.slice(i, j);
}
const src = [
  slice('const CLUB_AFFIXES', '// `layer2-board-chip-race`. The FIRST call to `renderGameCards`'),
  // One slice spanning chipForGame AND `cardSportLabel`, which sits between it
  // and `chipTeamRow`. A separate slice would throw on a pre-change template,
  // and running against one is the entire point of this script.
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
  src + '; return { deriveGameCards, chipForGame, cardSportLabel: typeof cardSportLabel === "function" ? cardSportLabel : null, rowSportLabel: typeof rowSportLabel === "function" ? rowSportLabel : null, normalizeClubName };');
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

// THE CARD-HEAD LABEL, per sport. The reported symptom was not a count -- it
// was two different labels on one slate -- so the reading has to be the SET of
// labels, not a total. A sport showing more than one label is the defect;
// `soccer` showing `SOCCER` alongside a league is the exact report.
//
// `cardSportLabel` may not exist on an older template (this is how the control
// run is possible at all), so fall back to what that version rendered:
// `game.sport`, verbatim from `renderGameCards`.
const labelOf = built.cardSportLabel
  ? (c) => built.cardSportLabel(c, resolveChip(c))
  : (c) => String(c.sport || '');
console.log();
console.log(`head labels per sport (${built.cardSportLabel ? 'via cardSportLabel' : 'via game.sport -- PRE-CHANGE template'}):`);
let mixedLabelSports = 0;
for (const [sport, list] of [...bySport].sort()) {
  const counts = new Map();
  for (const c of list) {
    const l = labelOf(c) || '(blank)';
    counts.set(l, (counts.get(l) || 0) + 1);
  }
  const shown = [...counts].sort((a, b) => b[1] - a[1]).map(([l, n]) => `${l}=${n}`).join(' ');
  // "More than one label" is not by itself wrong -- soccer legitimately spans
  // ten leagues. What is wrong is a BARE SPORT label sitting beside a league,
  // which is the "SOCCER next to LA LIGA" report.
  const bare = [...counts.keys()].filter((l) => l.toLowerCase() === sport);
  const mixedHere = bare.length > 0 && counts.size > 1;
  if (mixedHere) mixedLabelSports += 1;
  console.log(`  ${sport.padEnd(8)} ${counts.size} label(s)${mixedHere ? '  <-- BARE SPORT beside a league' : ''}: ${shown}`);
}
console.log(`  sports showing a bare sport label beside a league: ${mixedLabelSports}`);

// THE ABOVE FLAG CANNOT READ UNHEALTHY ON EVERY PAYLOAD, AND THAT IS MEASURED,
// NOT FEARED. It needs TWO labels present at once. On the 19:5xZ payload the
// pre-change template read `SOCCER=211 LA LIGA=2` and the flag fired; by 20:0xZ
// the league-labelled steam/prop rows had drained off the board and the SAME
// pre-change template read a uniform `SOCCER=213` -- flag 0, defect untouched.
// That is `learnings.md` 2026-08-20 exactly: a census whose test case the slate
// can retire.
//
// So the invariant that actually holds is anchored on the SOURCE, not on the
// spread of rendered labels: if a card's chip CARRIES a league, the card must
// not be rendering the bare sport. That reads unhealthy on any payload where a
// league-carrying chip exists at all, whatever the rows happen to be doing.
let leagueAvailableButUnused = 0;
let leagueCarryingChips = 0;
for (const c of cards) {
  const chip = resolveChip(c);
  const league = chip ? String(chip.league_display || '').trim() : '';
  if (!league) continue;
  leagueCarryingChips += 1;
  if ((labelOf(c) || '').toLowerCase() === slugOfCard(c)) leagueAvailableButUnused += 1;
}
console.log(`  cards whose chip CARRIES a league: ${leagueCarryingChips}`);
console.log(`  ...of those, still showing the BARE SPORT: ${leagueAvailableButUnused}`);

// THE BOARD CARD SUBTITLE, which is a per-ROW label, not a per-card one.
// Same defect one surface down; see `rowSportLabel` in the template.
//
// THE RESOLVE COUNT IS THE FALSIFICATION GUARD, and it is not decoration. The
// fix works by joining a ROW to a chip. If that join silently failed -- wrong id
// space, missing `away_key`/`home_key` -- every row would fall back to
// `item.sport` and the fix would be INERT, while a "no bare label" check still
// read clean, because the league-labelled rows drain off the board within
// minutes anyway. "0 bare labels" is only meaningful next to "and N rows
// actually resolved a chip that carries a league".
const rowLabelOf = built.rowSportLabel
  ? (it) => built.rowSportLabel(it)
  : (it) => String((it && (it.sport || it.sport_slug)) || '').trim().toUpperCase();
const rowLabels = new Map();
let rowsJoinedToLeague = 0;
let rowsBareDespiteLeague = 0;
for (const it of items) {
  const slug = String((it.sport_slug || it.sport) || '').trim().toLowerCase();
  if (!rowLabels.has(slug)) rowLabels.set(slug, new Map());
  const l = rowLabelOf(it) || '(blank)';
  const m = rowLabels.get(slug);
  m.set(l, (m.get(l) || 0) + 1);
  // Did THIS row reach a league-carrying chip? Uses the script's own join, not
  // the template's, for the same reason the duplicate detector does.
  const key = (() => {
    for (const f of ['game_id', 'gamePk', 'event_id']) {
      const v = it[f];
      if (v !== undefined && v !== null && String(v).trim() && String(v).trim() !== '-') return `${slug}|${String(v).trim()}`;
    }
    const mu = String(it.matchup || it.event_matchup || '').trim();
    return mu ? `${slug}|${mu}` : null;
  })();
  if (!key) continue;
  const chip = resolveChip({key, sport: slug, matchup: String(it.matchup || it.event_matchup || ''),
                            awayKey: it.away_key, homeKey: it.home_key});
  const league = chip ? String(chip.league_display || '').trim() : '';
  if (!league) continue;
  rowsJoinedToLeague += 1;
  if (l.toLowerCase() === slug) rowsBareDespiteLeague += 1;
}
console.log();
console.log(`board-card SUBTITLE labels per sport (${built.rowSportLabel ? 'via rowSportLabel' : 'via item.sport -- PRE-CHANGE template'}):`);
for (const [slug, m] of [...rowLabels].sort()) {
  const shown = [...m].sort((a, b) => b[1] - a[1]).map(([l, n]) => `${l}=${n}`).join(' ');
  const bare = [...m.keys()].filter((l) => l.toLowerCase() === slug);
  console.log(`  ${slug.padEnd(8)} ${m.size} label(s)${bare.length && m.size > 1 ? '  <-- MIXED' : ''}: ${shown}`);
}
console.log(`  rows that JOIN a league-carrying chip: ${rowsJoinedToLeague}   <-- 0 here means the fix is INERT, not that it worked`);
console.log(`  ...of those, still labelled the BARE SPORT: ${rowsBareDespiteLeague}`);

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
