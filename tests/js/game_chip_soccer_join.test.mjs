// MLS compact cards showed FULL club names. The join, not the renderer.
//
// WHY THIS EXISTS. Reported 2026-08-22: "the compact game cards on the main
// layer 2 board for MLS are showing full team names". Every other sport's card
// shows a tri-code, because `chipTeamRow` renders `chip.abbr` -- so a full name
// means `chipForGame` returned null and the card fell through to the chip-less
// branch, which printed `game.matchup` verbatim.
//
// The chips are not the problem: `build_game_chips` for MLS returns clean
// abbreviations (measured: LA, MIA, SKC, MIN, SD, STL, POR, PHI). Both chip
// indexes are EXACT, and soccer is the sport where exact never holds -- chip
// names come from the league's card builder ("CF Montréal", "Atlanta United
// FC") while a Layer 2 row's matchup comes from OddsAPI, which spells the same
// clubs without the accent and without the club-type suffix.
//
// Run it directly:   node tests/js/game_chip_soccer_join.test.mjs
// Not wired into pytest -- same convention as the tests beside it.
//
// The normalisation is deliberately NARROW. Dropping a token like "united" or
// "city" would collapse Manchester United into Manchester City, so only
// affix-style club-type tokens are removed and only from the ends of the name.
// Those two clubs are pinned below precisely because they are what a careless
// slugifier breaks.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html'), 'utf8');

function extract(pattern, label) {
  const m = html.match(pattern);
  if (!m) throw new Error(`could not extract ${label} from intelligence.html`);
  return m[0].replace(/^ {2}/gm, '');
}

const src = [
  extract(/const CLUB_AFFIXES = new Set\(\[[\s\S]*?\]\);/, 'CLUB_AFFIXES'),
  extract(/ {2}function normalizeClubName\(value\)[\s\S]*?\n {2}}\n/, 'normalizeClubName'),
  extract(/ {2}function trimClubAffixes\(name\)[\s\S]*?\n {2}}\n/, 'trimClubAffixes'),
  extract(/ {2}function compactMatchup\(matchup\)[\s\S]*?\n {2}}\n/, 'compactMatchup'),
].join('\n');
const { normalizeClubName, trimClubAffixes, compactMatchup } = new Function(
  `${src}; return { normalizeClubName, trimClubAffixes, compactMatchup };`,
)();

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

// THE JOIN. Chip-side spelling vs board-side spelling must land on one key.
check('accent is not a difference', normalizeClubName('CF Montréal'), normalizeClubName('Montreal'));
check('trailing club suffix is not a difference', normalizeClubName('Atlanta United FC'), normalizeClubName('Atlanta United'));
check('leading club prefix is not a difference', normalizeClubName('FC Cincinnati'), normalizeClubName('Cincinnati'));
check('punctuation is not a difference', normalizeClubName('St. Louis CITY SC'), normalizeClubName('St Louis CITY'));
check('case is not a difference', normalizeClubName('LA Galaxy'), normalizeClubName('la galaxy'));

// THE GUARD. Normalisation must not merge two real clubs -- a collision would
// attach one game's live score to another game's card, which is worse than the
// full name it replaces.
check('Man Utd and Man City stay distinct', normalizeClubName('Manchester United') === normalizeClubName('Manchester City'), false);
check('a bare affix name is not emptied', normalizeClubName('FC'), 'fc');
check('United alone is not stripped to nothing', normalizeClubName('United'), 'united');

// THE FALLBACK. When no chip exists at all the card must still be compact, and
// must not invent a tri-code.
check('suffix dropped, nothing invented', compactMatchup('Inter Miami CF @ Minnesota United FC'), 'Inter Miami @ Minnesota United');
check('a name with no affix is untouched', compactMatchup('LA Galaxy @ Portland Timbers'), 'LA Galaxy @ Portland Timbers');
check('a matchup that is not "a @ b" passes through', compactMatchup('Some Cup Final'), 'Some Cup Final');
check('empty input is safe', compactMatchup(''), '');
check('accents are PRESERVED for display', trimClubAffixes('CF Montréal'), 'Montréal');

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
