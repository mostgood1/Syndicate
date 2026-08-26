// `#562`. The compact scoreboard must SAY SO when it has stopped moving.
//
// WHY THIS EXISTS. Reported 2026-08-25: "it was sitting with stale compact
// cards and even the odds refresh times were frozen for about 20 mins". Nothing
// on the page said anything, because nothing could: `/api/board/game-chips` has
// always returned `published_at` and this page always threw it away. The 60s
// poll keeps succeeding, the response keeps being byte-identical, and a frozen
// scoreboard renders exactly like a live one.
//
// Root cause was upstream -- refresh-worker took 15 deploys in 6h15m, median
// instance uptime 1202 s against a 21-minute boot-to-first-publish, so the chip
// artifact went 20-54 minutes without moving. That is fixed separately. This is
// the half that makes the NEXT such freeze visible in one poll instead of
// needing a person to notice timestamps not changing.
//
// Run it directly:   node tests/js/board_chip_freshness_badge.test.mjs
// Not wired into pytest -- same convention as the tests beside it.

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
  extract(/ {2}function formatAge\(seconds\)[\s\S]*?\n {2}}\n/, 'formatAge'),
  extract(/ {2}const CHIP_STALE_AFTER_SECONDS = \d+;/, 'CHIP_STALE_AFTER_SECONDS'),
  extract(/ {2}function chipPublishedAgeSeconds\(\)[\s\S]*?\n {2}}\n/, 'chipPublishedAgeSeconds'),
  extract(/ {2}function renderChipFreshness\(\)[\s\S]*?\n {2}}\n/, 'renderChipFreshness'),
].join('\n');

// `escapeHtml` and the module-scope `gameChipsPublishedAt` are supplied by the
// harness: the first is unrelated to what is under test, the second is the
// input we are varying.
const harness = `
  let gameChipsPublishedAt = null;
  function escapeHtml(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
    ));
  }
  function __setPublishedAt(v) { gameChipsPublishedAt = v; }
`;

const { renderChipFreshness, chipPublishedAgeSeconds, __setPublishedAt, CHIP_STALE_AFTER_SECONDS } =
  new Function(
    `${harness}\n${src}; return { renderChipFreshness, chipPublishedAgeSeconds, __setPublishedAt, CHIP_STALE_AFTER_SECONDS };`,
  )();

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

const agoIso = (seconds) => new Date(Date.now() - seconds * 1000).toISOString();

// SILENT WHEN HEALTHY. A badge that is always on is furniture, and the reader
// stops seeing it well before it matters.
__setPublishedAt(agoIso(30));
check('fresh artifact renders nothing', renderChipFreshness(), '');
__setPublishedAt(agoIso(CHIP_STALE_AFTER_SECONDS - 60));
check('just inside the threshold renders nothing', renderChipFreshness(), '');

// LOUD WHEN FROZEN. This is the 2026-08-25 shape: a ~20 minute freeze.
__setPublishedAt(agoIso(1260));
const stale = renderChipFreshness();
check('a 21-minute-old artifact renders a badge', stale.includes('board-stale-badge'), true);
check('the badge names the age', stale.includes('21m'), true);
check('the badge says what is stale', stale.includes('scoreboard'), true);
// The title must name the PRODUCER, not just the symptom -- "scores may be out
// of date" tells a reader nothing they can act on.
check('the tooltip names refresh-worker', stale.includes('refresh-worker'), true);

// The 54-minute gap measured the same evening.
__setPublishedAt(agoIso(3240));
check('a 54-minute freeze reads in hours-or-minutes, not seconds', renderChipFreshness().includes('54m'), true);

// DEGRADES TO SILENCE, NEVER TO A GUESS. Painting "stale" on missing evidence
// would be the same error as the asserted `is_fresh: true` this replaces,
// pointed the other way.
__setPublishedAt(null);
check('no stamp renders nothing', renderChipFreshness(), '');
check('no stamp has no age', chipPublishedAgeSeconds(), null);
__setPublishedAt('not a date');
check('an unparseable stamp renders nothing', renderChipFreshness(), '');
check('an unparseable stamp has no age', chipPublishedAgeSeconds(), null);
__setPublishedAt('');
check('an empty stamp renders nothing', renderChipFreshness(), '');

// CLOCK SKEW IS NOT STALENESS. The worker and the browser are different clocks.
__setPublishedAt(new Date(Date.now() + 30_000).toISOString());
check('a stamp in the future clamps to zero', chipPublishedAgeSeconds(), 0);
check('a stamp in the future renders nothing', renderChipFreshness(), '');

// The stamp is attacker-irrelevant but user-visible; it must not break markup.
__setPublishedAt(agoIso(1800));
check('the badge is a single span', (renderChipFreshness().match(/<span/g) || []).length, 1);

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
