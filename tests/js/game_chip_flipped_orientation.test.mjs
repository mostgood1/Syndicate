// A neutral-site game whose home/away the odds feed changed mid-day must still
// find its chip on the Games rail (lane wncaab-module, 2026-11-07).
//
// WHY THIS EXISTS. User, 2026-11-07: "we have some games on the game rail that
// are not matched". One of them was "Nebraska Cornhuskers @ Providence Friars".
// The chip (ESPN) is Providence @ Nebraska. OddsAPI listed the event one way at
// 12:07Z and the other way from 16:53Z, and the board kept pregame rows from
// both pulls. After the book-grid fix (34ac35df3) the served board still held 6
// rows in the old orientation (measured 20:00Z), and their group missed every
// chip index: the matchup text, the canonical pair and the loose names are all
// orientation-exact.
//
// `chipForGame` IS EXTRACTED from the page, not restated (see the note at the
// top of game_rail_derive.test.mjs for why a restated copy is worthless).
//
// Run it directly:   node tests/js/game_chip_flipped_orientation.test.mjs
// Discrimination:    TEMPLATE=<path to the pre-change intelligence.html> node tests/js/game_chip_flipped_orientation.test.mjs
//                    must FAIL the flipped-pair assertion.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const template = process.env.TEMPLATE || path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html');
const html = fs.readFileSync(template, 'utf8').split('\r\n').join('\n');

function slice(fromMarker, toMarker) {
  const a = html.indexOf(fromMarker);
  const b = html.indexOf(toMarker, a + 1);
  if (a < 0 || b < 0 || b <= a) throw new Error(`slice ${fromMarker} .. ${toMarker} not found in ${template}`);
  return html.slice(a, b);
}

const src = [
  slice('const CLUB_AFFIXES', '// `layer2-board-chip-race`. The FIRST call to `renderGameCards`'),
  slice('function chipForGame', 'function chipTeamRow'),
].join('\n');

const gameChipsById = new Map();
const gameChipsByMatchup = new Map();
const gameChipsByCanonical = new Map();
const gameChipsByMatchupLoose = new Map();
const { chipForGame } = new Function(
  'gameChipsById', 'gameChipsByMatchup', 'gameChipsByCanonical', 'gameChipsByMatchupLoose',
  `${src}; return { chipForGame };`,
)(gameChipsById, gameChipsByMatchup, gameChipsByCanonical, gameChipsByMatchupLoose);

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

function addChip(sport, gameKey, away, home, start) {
  const chip = {
    sport, game_key: gameKey, matchup: `${away.name} @ ${home.name}`, start_time_utc: start,
    away: { name: away.name, key: away.key }, home: { name: home.name, key: home.key },
  };
  gameChipsById.set(`${sport}|${gameKey}`, chip);
  gameChipsByMatchup.set(`${sport}|${chip.matchup.toLowerCase()}`, chip);
  gameChipsByCanonical.set(`${sport}|${away.key} @ ${home.key}`, chip);
  return chip;
}

function group(sport, matchup, awayKey, homeKey, commenceTime) {
  return { key: `${sport}|odds-event-hash`, sport, sportSlug: sport, matchup, awayKey, homeKey, commenceTime, ownGameKey: null };
}

const NEB = { name: 'Nebraska Cornhuskers', key: 'nebraska' };
const PROV = { name: 'Providence Friars', key: 'providence' };
// The real chip: ESPN 401909532, Providence @ Nebraska, tip 00:00Z 11-08 = 6:00 PM Central 11-07.
const provAtNeb = addChip('ncaab', '401909532', PROV, NEB, '2026-11-08T00:00:00Z');

// THE REGRESSION: a group in the feed's old orientation, same game, same start.
check('the flipped pair finds its chip on the same Central day',
  chipForGame(group('ncaab', 'Nebraska Cornhuskers @ Providence Friars', 'nebraska', 'providence', '2026-11-08T00:00:00Z')),
  provAtNeb);

// The same orientation is still the exact route.
check('the chip orientation still joins exactly',
  chipForGame(group('ncaab', 'Providence Friars @ Nebraska Cornhuskers', 'providence', 'nebraska', '2026-11-08T00:00:00Z')),
  provAtNeb);

// A start missing on the group refuses: nothing says which day it is.
check('a group with no start does not take the flipped chip',
  chipForGame(group('ncaab', 'Nebraska Cornhuskers @ Providence Friars', 'nebraska', 'providence', null)),
  null);

// NHL home-and-home: A @ B tonight, B @ A tomorrow. Tomorrow's rows must not take tonight's chip.
const BOS = { name: 'Boston Bruins', key: 'boston bruins' };
const BUF = { name: 'Buffalo Sabres', key: 'buffalo sabres' };
addChip('nhl', '2025020999', BOS, BUF, '2026-11-08T00:00:00Z');
check('the next day\'s reversed meeting is not joined to tonight\'s chip',
  chipForGame(group('nhl', 'Buffalo Sabres @ Boston Bruins', 'buffalo sabres', 'boston bruins', '2026-11-09T00:00:00Z')),
  null);

// When the reversed pair has its OWN chip, the exact lookup wins over the flip.
const bufAtBos = addChip('nhl', '2025021000', BUF, BOS, '2026-11-09T00:00:00Z');
check('the exact pair wins when both orientations have chips',
  chipForGame(group('nhl', 'Buffalo Sabres @ Boston Bruins', 'buffalo sabres', 'boston bruins', '2026-11-09T00:00:00Z')),
  bufAtBos);

// Another sport's chip with the same keys is never taken.
check('the flip stays inside the sport',
  chipForGame(group('ncaaf', 'Nebraska Cornhuskers @ Providence Friars', 'nebraska', 'providence', '2026-11-08T00:00:00Z')),
  null);

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
