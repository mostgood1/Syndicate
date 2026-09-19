// Board freshness chip: today's own stamp first, then each later window date.
//
// WHY (lane `board-today-freshness`). The chip rendered "as of
// `state_last_updated`", which is the window's OLDEST input -- on 2026-09-17
// 17:05Z that was tomorrow's 48-minute-old shortlist while today's was 13
// minutes old. The server now serves `state_meta.dates{date: {written_at}}`.
//
// "TODAY" COMES FROM THE BROWSER'S CLOCK IN CENTRAL, NOT FROM THE PAYLOAD. The
// combined response is cached, so a "today" frozen into it outlives midnight
// (learnings 2026-09-15). This harness pins that the helper labels by the
// clock, and that a payload `today_date` is ignored.
//
// Run it directly:   node tests/js/board_today_freshness_chip.test.mjs
// Not wired into pytest or the migration gate; a manual check beside the change.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

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

const src = slice('function boardDateFreshnessParts(', 'function renderLoadingState(');
// `formatTimestamp` is unrelated to what is under test; echo the raw stamp so
// assertions can name it exactly. `document` serves one chip element.
const harness = `
  const chip = { hidden: true, textContent: "" };
  const document = { getElementById: () => chip };
  function formatTimestamp(v) { return String(v || "").trim(); }
  function numericValue(v) { const n = Number(v); return Number.isFinite(n) ? n : null; }
`;
const { boardDateFreshnessParts, renderFreshnessChip, chip } = new Function(
  `${harness}\n${src}; return { boardDateFreshnessParts, renderFreshnessChip, chip };`,
)();

let failures = 0;
function check(label, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

const centralToday = new Date().toLocaleDateString('en-CA', { timeZone: 'America/Chicago' });
const plusDays = (iso, n) => {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};
const tomorrow = plusDays(centralToday, 1);
const yesterday = plusDays(centralToday, -1);
const weekday = (iso) => new Intl.DateTimeFormat(undefined, { weekday: 'short' }).format(new Date(`${iso}T12:00:00`));

// The production shape: tomorrow is the oldest, and today still reads first.
const meta = {
  computed_at: 'T-tomorrow',
  dates: { [tomorrow]: { written_at: 'T-tomorrow' }, [centralToday]: { written_at: 'T-today' } },
};
check('today first, then the next date by weekday',
  boardDateFreshnessParts({ state_meta: meta }),
  ['Today as of T-today', `${weekday(tomorrow)} as of T-tomorrow`]);
check('the nested response shape is read the same way',
  boardDateFreshnessParts({ response: { state_meta: meta } }),
  ['Today as of T-today', `${weekday(tomorrow)} as of T-tomorrow`]);

// A frozen payload "today" must not win over the clock.
check('a payload today_date is ignored',
  boardDateFreshnessParts({ state_meta: { ...meta, today_date: yesterday } })[0],
  'Today as of T-today');

check('no per-date map means no parts (old payloads)', boardDateFreshnessParts({ state_meta: { computed_at: 'x' } }), []);
check('a date with no written_at is skipped',
  boardDateFreshnessParts({ state_meta: { dates: { [centralToday]: {}, [tomorrow]: { written_at: 'T2' } } } }),
  [`${weekday(tomorrow)} as of T2`]);

// BOTH STAMPS WHEN THEY DIFFER (lane `live-inplay-board-cadence`, 2026-09-19).
// Production that day: plays rewritten 11:05 CDT, full build still 10:49 (a
// restart discarded the build that would have moved it), and the chip said only
// "as of 10:49". The plays' stamp now leads; the full build stays beside it.
const twoSources = {
  dates: {
    [centralToday]: { written_at: 'T-full', sources: { state: 'T-full', layer2_shortlist: 'T-plays' } },
    [tomorrow]: { written_at: 'T-tom', sources: { state: 'T-tom', layer2_shortlist: 'T-tom' } },
  },
};
check('differing sources show the plays stamp first and the full board beside it',
  boardDateFreshnessParts({ state_meta: twoSources }),
  ['Today: plays as of T-plays · full board T-full', `${weekday(tomorrow)} as of T-tom`]);
check('a single source keeps the old form',
  boardDateFreshnessParts({ state_meta: { dates: { [centralToday]: { written_at: 'T1', sources: { layer2_shortlist: 'T1' } } } } }),
  ['Today as of T1']);

// The chip itself: per-date parts replace the single oldest stamp.
renderFreshnessChip({ execution_source: 'worker', state_last_updated: 'T-tomorrow', candidate_count: 12, state_meta: meta });
check('chip text', chip.textContent, `Worker-refreshed · Today as of T-today · ${weekday(tomorrow)} as of T-tomorrow · 12 candidates`);
renderFreshnessChip({ execution_source: 'worker', state_last_updated: 'T-old', candidate_count: 3 });
check('chip falls back to the single stamp without dates', chip.textContent, 'Worker-refreshed · as of T-old · 3 candidates');

if (failures) {
  console.log(`\n${failures} FAILED`);
  process.exit(1);
}
console.log('\nall passed');
