// The Movement cell on the Layer 2 board: arrow, label, sparkline, tooltip.
//
// WHY THIS EXISTS. The cell used two conventions at once. "toward" meant a price
// that PAYS MORE, the sparkline plotted decimal odds (which also rise as a price
// lengthens), and the label printed `movement_price_delta` -- a raw difference
// of American numbers, so -104 -> +104 read "Odds +208". The user's decision
// (2026-09-15): GREEN = THE MARKET MOVED TOWARD THE PICK, i.e. it now prices
// this side as more likely (-117 -> -131, +150 -> +120, or the line moved the
// pick's way). Every assertion below pins one half of "the label and the
// sparkline say the same thing".
//
// Run it directly:   node tests/js/board_movement_display.test.mjs
// Not wired into pytest -- same convention as the harnesses beside it.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const template = path.resolve(here, '../../syndicate/templates/intelligence.html');
const html = fs.readFileSync(template, 'utf8');

// Extract AT RUN TIME, brace-balanced -- the approach of
// `board_sim_view_display.test.mjs`. A dumped copy of these functions would go
// stale the first time the template changed and keep passing.
function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found in ${template}`);
  let depth = 0;
  let seen = false;
  for (let i = start; i < html.length; i += 1) {
    if (html[i] === '{') { depth += 1; seen = true; }
    else if (html[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) return html.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced braces extracting ${name}`);
}

// Every helper is the page's own, extracted -- nothing is stubbed, so a change
// to any of them is exercised here rather than masked by a copy.
const names = [
  'escapeHtml', 'numericValue', 'formatRelativeTime',
  '_movementArrow', '_movementArrowClass', '_formatMovementSegment',
  '_signedAmerican', '_movementLineText', '_americanToImpliedProbability',
  '_impliedDirection', '_movementNotTrackedHtml', '_movementClock',
  '_movementSeries', '_movementSeriesCaption', '_movementSparkline', '_movementMarketVerdict', 'renderMovement',
];
const api = (new Function(
  `${names.map(extract).join('\n')}\nreturn { renderMovement, _movementSparkline, _movementSeries };`
))();

let failures = 0;
function check(label, ok, detail) {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `\n        ${detail}`}`);
}
const has = (label, out, needle) => check(label, String(out).includes(needle), `missing ${JSON.stringify(needle)} in ${out}`);
const lacks = (label, out, needle) => check(label, !String(out).includes(needle), `found ${JSON.stringify(needle)} in ${out}`);
const text = (out) => String(out).replace(/<title>[\s\S]*?<\/title>/g, '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const polylineXs = (svg) => {
  const m = String(svg).match(/points="([^"]+)"/);
  return m ? m[1].split(' ').map((pt) => Number(pt.split(',')[0])) : [];
};

const layer2 = (extra) => Object.assign({ source: 'layer2_shortlist', movement_state: 'tracked' }, extra);
const minutesAgo = (m) => new Date(Date.now() - m * 60000).toISOString();

console.log('--- 1. THE MARKET, NOT ONE BOOK (user 2026-10-02: "NOTHING should reference just a single book") ---');
{
  // The label is the no-vig consensus before and after; no book's price or name.
  const toward = api.renderMovement(layer2({
    movement_vs_pick: 'toward', movement_fair_delta_pp: 1.9, movement_fair_from: 0.52, movement_fair_to: 0.539,
    movement_price_from: 100, movement_price_to: 106, movement_basis: 'same_book', movement_book: 'novig',
  }));
  has('consensus toward: up arrow', toward, 'board-card__movement-arrow--up');
  has('up arrow glyph', toward, '▲');
  has('labelled with the consensus before and after', text(toward), 'Market toward pick · 52.0% → 53.9%');
  lacks('no book price in the label', text(toward), 'Odds');
  lacks('no book name anywhere, tooltip included', toward, 'novig');
  lacks('no "same book" wording', toward, 'Same book');
  lacks('no per-book price story', toward, 'Better price');
  has('tooltip carries the consensus move', toward, 'Market consensus (no-vig) +1.9 pts since publish');

  const against = api.renderMovement(layer2({
    movement_vs_pick: 'away', movement_fair_delta_pp: -1.2, movement_fair_from: 0.5, movement_fair_to: 0.488,
    movement_price_from: -117, movement_price_to: -131,
  }));
  has('consensus against: down arrow', against, 'board-card__movement-arrow--down');
  has('down arrow glyph', against, '▼');
  has('says the market disagrees', text(against), 'Market against pick · 50.0% → 48.8%');
  lacks('a book shortening does not leak in', text(against), '-131');

  const held = api.renderMovement(layer2({
    movement_state: 'flat', movement_vs_pick: 'flat', movement_fair_delta_pp: 0.1, movement_fair_from: 0.5, movement_fair_to: 0.501,
    movement_price_from: 100, movement_price_to: 115,
  }));
  check('consensus held: exactly "→ Market unchanged"', text(held) === '→ Market unchanged', `got ${JSON.stringify(text(held))}`);
  has('flat arrow', held, 'board-card__movement-arrow--flat');
  const tiny = api.renderMovement(layer2({ movement_fair_delta_pp: -0.2 }));
  has('a consensus move under 0.25 pp is unchanged', tiny, 'board-card__movement-arrow--flat');
  const ago = api.renderMovement(layer2({ movement_fair_delta_pp: 0, movement_opened_at: minutesAgo(5) }));
  has('the opened-at suffix survives', ago, 'Market unchanged · 5m ago');
}

console.log('\n--- 2. no consensus: says so, never falls back to one book ---');
{
  const out = api.renderMovement(layer2({ movement_vs_pick: 'away', movement_price_from: 100, movement_price_to: 106 }));
  has('Market move unavailable', out, 'Market move unavailable');
  lacks('no arrow claims a direction', out, 'movement-arrow--down');
  lacks('no book price', out, 'Odds');
}

console.log('\n--- 3. a line move is labelled in displayLine format, signed by the server ---');
{
  const out = api.renderMovement(layer2({ movement_vs_pick: 'toward', movement_line_from: 8.5, movement_line_to: 9 }));
  has('Line 8.5 → 9.0', out, 'Market toward pick · Line 8.5 → 9.0');
  has('up arrow', out, 'board-card__movement-arrow--up');
  const whole = api.renderMovement(layer2({ movement_vs_pick: 'away', movement_line_from: 8, movement_line_to: 8.5 }));
  has('a whole-number opening keeps one decimal', whole, 'Market against pick · Line 8.0 → 8.5');
  const unknown = api.renderMovement(layer2({ movement_vs_pick: 'unknown', movement_line_from: 8.5, movement_line_to: 9 }));
  has('unknown direction is the flat arrow', unknown, 'board-card__movement-arrow--flat');
}


console.log('\n--- 6. the sparkline is movement_series: rising green, falling red, flat nothing ---');
{
  const rising = api._movementSparkline(layer2({ movement_series: [[0, 4390], [30, 4500], [90, 4710]] }));
  has('rising series draws up', rising, 'board-sparkline--up');
  const falling = api._movementSparkline(layer2({ movement_series: [[0, 4710], [30, 4500], [90, 4390]] }));
  has('falling series draws down', falling, 'board-sparkline--down');
  const flat = api._movementSparkline(layer2({ movement_series: [[0, 5000], [45, 5000]] }));
  check('flat series draws nothing', flat === '', `got ${flat}`);
  const single = api._movementSparkline(layer2({ movement_series: [[0, 5000]] }));
  check('single point draws nothing', single === '', `got ${single}`);
  const synth = api._movementSparkline(layer2({ movement_price_from: -117, movement_price_to: -131 }));
  check('no series -> nothing, never synthesised from from/to', synth === '', `got ${synth}`);
  const shuffled = api._movementSparkline(layer2({ movement_series: [[90, 4710], [0, 4390], [30, 4500]] }));
  has('out-of-order points are time-sorted before first/last decide the colour', shuffled, 'board-sparkline--up');


  // The arrow and the line agree on one row: both read the consensus.
  const row = layer2({
    movement_vs_pick: 'toward', movement_fair_delta_pp: 2.8, movement_fair_from: 0.539, movement_fair_to: 0.567,
    movement_price_from: -117, movement_price_to: -131,
    movement_series: [[0, 5390], [42, 5500], [120, 5670]],
    movement_series_start: minutesAgo(120), movement_series_basis: 'consensus',
  });
  const cell = api.renderMovement(row);
  has('toward arrow', cell, 'board-card__movement-arrow--up');
  has('and a green sparkline in the same cell', cell, 'board-sparkline--up');
  has('sparkline caption: the consensus window', cell, '53.9% → 56.7%');
  has('sparkline caption is an svg <title> naming the market', cell, '<title>Market consensus (no-vig) for this side since ');
  lacks('the caption names no book', cell, '&#39;s price');

}

console.log('\n--- 7. the x axis is TIME-scaled ---');
{
  const width = 58;
  const svg = api._movementSparkline(layer2({ movement_series: [[0, 4000], [10, 4100], [600, 4200]] }));
  const xs = polylineXs(svg);
  check('three points drawn', xs.length === 3, `xs=${xs}`);
  check(`minute 10 of 600 sits near the left (x=${xs[1]} < ${width * 0.25})`, xs[1] < width * 0.25, `xs=${xs}`);
  const same = polylineXs(api._movementSparkline(layer2({ movement_series: [[5, 4000], [5, 4100], [5, 4200]] })));
  check(`every point at one minute falls back to index spacing (middle x=${same[1]})`, Math.abs(same[1] - width / 2) < 0.5, `xs=${same}`);
  check('the svg keeps its 58x16 size', svg.includes('width="58" height="16"'), svg);
}

console.log('\n--- 8. a legacy not-tracked row still says so, neutrally ---');
{
  const out = api.renderMovement({ movement_state: 'not_tracked' });
  has('Not tracked', out, 'Not tracked');
  has('neutral tooltip', out, 'No price history is recorded for this row');
  lacks('no stale cause in the tooltip', out, 'h2h, totals and spreads');
  has('the boolean legacy flag too', api.renderMovement({ movement_not_tracked: true }), 'Not tracked');
}

console.log('\n--- 9. legacy history: the colour means the same thing ---');
{
  const history = (a, b) => ({ movement: { trend: 'flat', history: [{ odds: a, current_line: 8.5 }, { odds: b, current_line: 8.5 }] } });
  const shortening = api.renderMovement(history(-110, -130));
  has('-110 -> -130 draws green', shortening, 'board-sparkline--up');
  has('and the text arrow follows the price, not a flat →', shortening, 'board-card__movement-arrow--up');
  const lengthening = api.renderMovement(history(-130, -110));
  has('-130 -> -110 draws red', lengthening, 'board-sparkline--down');
  has('with a red arrow', lengthening, 'board-card__movement-arrow--down');
  const crossing = api._movementSeries({ movement: { history: [{ odds: -105 }, { odds: 105 }] } });
  check('a crossing legacy price is continuous (not a 210-unit spike)',
    Math.abs(crossing.points[0].v - crossing.points[1].v) < 0.03, JSON.stringify(crossing));

  const structured = api.renderMovement({ line_odds_movement: {
    opening_price: -117, latest_price: -131, price_delta: -14, price_direction: 'negative',
  } });
  has('structured: a shortening price is an UP arrow despite price_direction "negative"', structured, 'board-card__movement-arrow--up');
  has('structured: and a green sparkline', structured, 'board-sparkline--up');
  has('structured: labelled as the two prices', structured, 'Odds -117 → -131');
  lacks('structured: no raw delta', text(structured), '-14');

  const lineOnly = api._movementSparkline({ line_odds_movement: { opening_line: 8.5, latest_line: 9, line_delta: 0.5, line_direction: 'up' } });
  has('a legacy LINE-only series makes no colour claim', lineOnly, 'board-sparkline--flat');
}

console.log('\n--- 10. the sparkline is never redrawn neutral against its arrow: both are the market ---');
{
  const against = api.renderMovement(layer2({
    movement_vs_pick: 'away', movement_fair_delta_pp: -0.8, movement_fair_from: 0.5, movement_fair_to: 0.492,
    movement_series: [[0, 5000], [60, 4950], [120, 4920]], movement_series_basis: 'consensus',
  }));
  has('consensus fell: red arrow', against, 'board-card__movement-arrow--down');
  has('and a red line', against, 'board-sparkline--down');
  lacks('never a green line beside a red arrow', against, 'board-sparkline--up');
}

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILED`);
process.exit(failures === 0 ? 0 : 1);
