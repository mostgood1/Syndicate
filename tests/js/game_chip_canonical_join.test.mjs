// La Liga compact cards showed team names that did not match the rest of the
// board. The join again -- but a class of miss that normalisation cannot fix.
//
// WHY THIS EXISTS. Reported 2026-08-24: "we have some la liga compact game
// card mismatched team names for today". `#365`'s normalised index had already
// closed the MLS case (accents, punctuation, club-type affixes). Measured on
// the real chips for the La Liga week, 2026-08-24: 9 of 13 fixtures joined and
// 4 did not, and every one of the 4 was one of two clubs --
//
//     odds feed "Athletic Bilbao"                vs chip "Athletic Club"
//     odds feed "Real Racing Club de Santander"  vs chip "Racing Santander"
//
// Those cards printed the odds-feed spelling verbatim, beside cards showing
// tri-codes. That is not a spelling difference: they are two different NAMES
// for one club, and normalising until they meet means dropping a city
// qualifier -- precisely what collapses Manchester United into Manchester
// City. So the fix is a LOOKUP, not a wider approximation: the server stamps
// `canonical_team`'s answer on the chip AND on the board row, and the browser
// joins on it.
//
// Run it directly:   node tests/js/game_chip_canonical_join.test.mjs
// Not wired into pytest -- same convention as the tests beside it.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html'), 'utf8');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

// ---------------------------------------------------------------- structure
// These assert the WIRING, because the whole defect class here is "a value is
// produced and nothing consults it". A canonical key on the chip that
// `chipForGame` never reads would leave the cards exactly as broken while
// every unit test passed.
check('the canonical index is declared', /let gameChipsByCanonical = new Map\(\);/.test(html), true);
check('the canonical index is populated from chip.key', /const awayKey = String\(\(chip\.away \|\| \{\}\)\.key \|\| ""\)/.test(html), true);
check('the canonical index is committed', /gameChipsByCanonical = byCanonical;/.test(html), true);
check('collisions are removed, not resolved arbitrarily', /for \(const key of canonicalCollisions\) byCanonical\.delete\(key\);/.test(html), true);
check('chipForGame consults it', /gameChipsByCanonical\.get\(/.test(html), true);
check('the group carries the row keys', /awayKey: String\(item\.away_key \|\| ""\)/.test(html), true);

// ORDER IS A CONTRACT. The canonical index is authoritative and the normalised
// one is an approximation, so canonical must be consulted FIRST. If they ever
// disagree, the lookup has to win.
const fn = html.match(/ {2}function chipForGame\(group\)[\s\S]*?\n {2}}\n/);
check('chipForGame was found', Boolean(fn), true);
if (fn) {
  const body = fn[0];
  const canonicalAt = body.indexOf('gameChipsByCanonical');
  const looseAt = body.indexOf('gameChipsByMatchupLoose');
  const exactAt = body.indexOf('gameChipsByMatchup.get');
  check('canonical is consulted before the normalised index', canonicalAt > -1 && looseAt > -1 && canonicalAt < looseAt, true);
  check('both exact lookups still come first', exactAt > -1 && exactAt < canonicalAt, true);
}

// ---------------------------------------------------------------- behaviour
// The real join, rebuilt from the page's own source, over the two clubs that
// actually failed. Chip names are the artifact spellings; row keys are what
// `canonical_team` returns for the ODDS FEED spellings (verified server-side:
// "Athletic Bilbao" -> "athletic club", "Real Racing Club de Santander" ->
// "racing santander").
function extract(pattern, label) {
  const m = html.match(pattern);
  if (!m) throw new Error(`could not extract ${label}`);
  return m[0].replace(/^ {2}/gm, '');
}
const { normalizeClubName } = new Function(
  `${extract(/const CLUB_AFFIXES = new Set\(\[[\s\S]*?\]\);/, 'CLUB_AFFIXES')}
   ${extract(/ {2}function normalizeClubName\(value\)[\s\S]*?\n {2}}\n/, 'normalizeClubName')}
   ; return { normalizeClubName };`,
)();

const chips = [
  { matchup: 'SEV @ ATH', away: { name: 'Sevilla', key: 'sevilla' }, home: { name: 'Athletic Club', key: 'athletic club' } },
  { matchup: 'ELC @ RAC', away: { name: 'Elche', key: 'elche' }, home: { name: 'Racing Santander', key: 'racing santander' } },
];
const byMatchup = new Map(), byLoose = new Map(), byCanonical = new Map();
for (const chip of chips) {
  const a = chip.away.name.toLowerCase(), h = chip.home.name.toLowerCase();
  byMatchup.set(`soccer|${chip.matchup.toLowerCase()}`, chip);
  byMatchup.set(`soccer|${a} @ ${h}`, chip);
  byLoose.set(`soccer|${normalizeClubName(a)} @ ${normalizeClubName(h)}`, chip);
  byCanonical.set(`soccer|${chip.away.key} @ ${chip.home.key}`, chip);
}
function join(matchup, awayKey, homeKey) {
  const m = matchup.trim().toLowerCase();
  if (byMatchup.has(`soccer|${m}`)) return byMatchup.get(`soccer|${m}`).matchup;
  if (awayKey && homeKey && byCanonical.has(`soccer|${awayKey} @ ${homeKey}`)) {
    return byCanonical.get(`soccer|${awayKey} @ ${homeKey}`).matchup;
  }
  const sides = m.split(' @ ');
  if (sides.length !== 2) return null;
  const c = byLoose.get(`soccer|${normalizeClubName(sides[0])} @ ${normalizeClubName(sides[1])}`);
  return c ? c.matchup : null;
}

// THE REGRESSION ITSELF: without keys these two still miss, which is what the
// user saw. Asserting the miss pins WHY the keys are load-bearing -- if this
// ever starts passing without them, normalisation has been widened and the
// Manchester hazard is back.
check('Athletic Bilbao misses on names alone', join('Sevilla @ Athletic Bilbao', '', ''), null);
check('Racing Santander misses on names alone', join('Elche @ Real Racing Club de Santander', '', ''), null);

check('Athletic Bilbao joins on the canonical key', join('Sevilla @ Athletic Bilbao', 'sevilla', 'athletic club'), 'SEV @ ATH');
check('Racing Santander joins on the canonical key', join('Elche @ Real Racing Club de Santander', 'elche', 'racing santander'), 'ELC @ RAC');

// A club the alias map cannot resolve must degrade to the old behaviour, not
// break the ones that can.
check('an unresolvable club still falls through', join('Someone FC @ Nobody United', '', ''), null);
// And a row that predates the stamp keeps working through the exact index.
check('a keyless row still joins when the names match', join('Sevilla @ Athletic Club', '', ''), 'SEV @ ATH');

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
