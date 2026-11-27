// Live lines + fresh-quote live-edge flag on the Games-rail cards (lane layer2-live-rail-edges, todo #781).
//
// A live rail card now shows, per full-game market, our live re-sim number against the book's main live line
// and the quote's age; the card is highlighted, and the rail filter keeps it, ONLY when a live edge was priced
// against a FRESH quote (todo #780 + addendum: every game-line market realises ~0 under 120 s; the "edge" on
// older quotes is the line not having moved). The flag is worded as a disagreement, never as an edge.
// This pins the page's OWN block (extracted from intelligence.html, not restated) and that renderGameCards
// calls it.
//
// Run it directly:   node tests/js/games_rail_live_lines.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const template = process.env.TEMPLATE || path.join(here, '..', '..', 'syndicate', 'templates', 'intelligence.html');
const html = fs.readFileSync(template, 'utf8').split('\r\n').join('\n');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

// ---------------------------------------------------------------- extraction
const block = html.match(/ {2}\/\/ ===== LIVE RAIL LINES -- BEGIN[\s\S]*?\/\/ ===== LIVE RAIL LINES -- END =====/);
const formatAgeSrc = html.match(/ {2}function formatAge\(seconds\)[\s\S]*?\n {2}}\n/);
const buildSrc = html.match(/ {2}function boardBuildEpochMs\(response\)[\s\S]*?\n {2}}\n/);
const staleSrc = html.match(/const LIVE_PRICE_STALE_AFTER_SECONDS = (\d+);/);
check('the LIVE RAIL LINES block exists', Boolean(block), true);
check('formatAge / boardBuildEpochMs / LIVE_PRICE_STALE_AFTER_SECONDS exist', Boolean(formatAgeSrc && buildSrc && staleSrc), true);
if (!block || !formatAgeSrc || !buildSrc || !staleSrc) { console.log(`\n${failures} assertion(s) failed`); process.exit(1); }

const escapeHtml = (v) => String(v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const trimClubAffixes = (name) => String(name || '').trim();
const api = new Function('escapeHtml', 'trimClubAffixes', `
  const LIVE_PRICE_STALE_AFTER_SECONDS = ${Number(staleSrc[1])};
  ${formatAgeSrc[0]}
  ${buildSrc[0]}
  ${block[0]}
  return { liveRailMarketKey, liveRailSegmentKey, liveQuotePricingAgeSeconds, liveQuoteAgeNowSeconds, liveRowFreshEdge, liveRailMainRow,
           liveRailSummary, liveEdgeFilterMatches, renderLiveRailLines, tickLiveRailAges, LIVE_RAIL_AGE_TICK_MS,
           mergeLiveRailFresh, liveRailIdentity, LIVE_RAIL_FAST_POLL_MS,
           LIVE_EDGE_FRESH_QUOTE_SECONDS, LIVE_EDGE_MIN_PP, LIVE_PRICE_STALE_AFTER_SECONDS };
`)(escapeHtml, trimClubAffixes);

const text = (out) => out.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- the stated defaults
check('fresh-quote threshold is 120 s (#780 addendum: ~0 under 120 s in every market; MLB join ceiling)', api.LIVE_EDGE_FRESH_QUOTE_SECONDS, 120);
check('minimum live edge is 3 points', api.LIVE_EDGE_MIN_PP, 3);
check('the block states the #780 reason in code', /#780/.test(block[0]) && /under 120 s/.test(block[0]) && /180-300 s/.test(block[0]), true);
check('the block says a flag is a disagreement, not an edge', /A FLAG IS A DISAGREEMENT, NOT A PROVEN EDGE/.test(block[0]), true);
check('the join ceiling is named as another lane\'s, and the flag is never looser', /_MAX_QUOTE_AGE_BY_SPORT/.test(block[0]) && /never looser than that ceiling/.test(block[0]), true);

// ---------------------------------------------------------------- fixtures (shaped like served rows, 2026-11-10 23:45Z)
const NOW = Date.parse('2026-11-10T23:45:00Z');
const BUILT = '2026-11-10T23:44:40Z'; // the overlay's own grid build, 20 s ago
const response = { state_meta: { read_at: '2026-11-10T23:45:00Z', newest_age_seconds: 60 } };
const chip = {
  sport: 'ncaab', state: 'live',
  away: { abbr: 'FLA', key: 'florida' }, home: { abbr: 'FSU', key: 'florida state' },
  intervals: { source: 'live_resim', final: { total: 145.9, home_margin: -10.2, home_win_prob: null } },
};
const base = {
  kind: 'game', market_state: 'live', is_live: true, segment: 'full',
  away_key: 'florida', home_key: 'florida state', away_team: 'Florida Gators', home_team: 'Florida St Seminoles',
  price_grid_generated_at: BUILT,
};
const totals = (line, side, fair, extra = {}) => ({
  ...base, market: 'totals', line, side, odds: -110, live_total: 145.92,
  book_age_seconds: 12, quote: { fair_probability: fair, books_quoting: 6, book_age_seconds: 12 }, ...extra,
});
const fresh = () => [
  totals(147.5, 'over', 0.497),
  totals(147.5, 'under', 0.503),
  totals(149.0, 'under', 0.56, { live_aware: true, model_edge_pct: 10.29 }),
  totals(149.0, 'over', 0.44, { live_aware: true, model_edge_pct: -10.29 }),
  totals(145.5, 'over', 0.45),
  { ...base, market: 'spreads', side: 'home', team: 'Florida St Seminoles', line: 8.5, odds: -110, live_model_probability: 0.32,
    book_age_seconds: 40, quote: { fair_probability: 0.5, books_quoting: 5 } },
  { ...base, market: 'spreads', side: 'away', team: 'Florida Gators', line: -8.5, odds: -110, live_model_probability: 0.68,
    book_age_seconds: 40, quote: { fair_probability: 0.5, books_quoting: 5 } },
  { ...base, market: 'h2h', side: 'home', team: 'Florida St Seminoles', odds: 575, live_model_probability: 0.142,
    book_age_seconds: 104.5, quote: { fair_probability: 0.155 } },
  // A first-half total, as college interval rows are served: a display-only live number, NO priced edge
  // (segment pricing is off, #763). It gets its own interval row and never flags.
  { ...base, market: 'totals', segment: 'h1', segment_label: '1st half', line: 61.0, side: 'over', live_total: 62.3,
    live_model_probability: 0.56, book_age_seconds: 5, quote: { fair_probability: 0.5 } },
];

// ---------------------------------------------------------------- row selection
check('a live full-game total is a rail row', api.liveRailMarketKey(fresh()[0]), 'totals');
check('a first-half total is a rail row too, in its own interval', `${api.liveRailMarketKey(fresh()[8])}|${api.liveRailSegmentKey(fresh()[8])}`, 'totals|h1');
check('a full-game row is segment "full"', api.liveRailSegmentKey(fresh()[0]), 'full');
check('an NBA alt interval line is the same family', api.liveRailMarketKey({ ...fresh()[8], market: 'totals_alt' }), 'totals');
check('a three-way interval moneyline is not', api.liveRailMarketKey({ ...fresh()[8], market: 'h2h_3_way' }), null);
check('a pregame row is not', api.liveRailMarketKey({ ...fresh()[0], market_state: 'pregame', is_live: false }), null);
check('a prop row is not', api.liveRailMarketKey({ ...fresh()[0], kind: 'prop' }), null);
const mainTotal = api.liveRailMainRow(fresh().slice(0, 5), 'totals');
check('main total = the line priced closest to even', mainTotal.line, 147.5);
const mainSpread = api.liveRailMainRow(fresh().slice(5, 7), 'spreads');
check('main spread names the favourite side of the line', mainSpread.line, -8.5);

// ---------------------------------------------------------------- the live line renders for a live game with a priced row
const live = api.liveRailSummary(fresh(), chip, response, NOW);
check('the full game first, then the interval', live.markets.map((m) => `${m.segment}:${m.key}`).join(','), 'full:spreads,full:totals,full:h2h,h1:totals');
const out = text(api.renderLiveRailLines(live));
check('header: LIVE OURS BOOK AGE', /^LIVE OURS BOOK AGE/.test(out), true);
check('total: the table row shows the line the callout names (u149), with our re-sim and the quote age NOW (12 s + 20 s since the build)', /Total 145\.9 149 32s/.test(out), true);
check('spread: our margin restated for the line\'s team vs the book line', /Sprd FLA −10\.2 FLA −8\.5 60s/.test(out), true);
check('moneyline: our live % vs the book price', /ML FSU 14% FSU \+575 2m/.test(out), true);
check('the callout reads in the card\'s units: our score for the line, then sim vs book as percentages', /≠ Total u149: ours 145\.9 · sim 66% vs book 56%/.test(out), true);
check('no callout speaks in "pts" any more (it meant probability points beside a table in score points)', /pts/.test(out), false);
check('the flag never calls itself an edge', /EDGE|edge/.test(out), false);
check('interval row: no PROJ block on this chip, so OURS is the row\'s own live total', /1H Total 62\.3 61 25s/.test(out), true);
check('a display-only interval gets a callout too: the rail is information, sim vs book (#803)', /≠ 1H Total o61: ours 62\.3 · sim 56% vs book 50%/.test(out), true);

// ---------------------------------------------------------------- intervals against the card's own PROJ box
const withBox = (periods) => ({ ...chip, intervals: { ...chip.intervals, periods } });
const collegeBox = withBox([
  { key: 'h1', label: '1H', away: 30, home: 32.4, state: 'in_progress' },
  { key: 'h2', label: '2H', away: 35, home: 38, state: 'ahead' },
]);
const h2Row = { ...fresh()[8], segment: 'h2', segment_label: '2nd half', line: 74.5, live_total: 72.0 };
const boxOut = text(api.renderLiveRailLines(api.liveRailSummary([...fresh(), h2Row], collegeBox, response, NOW)));
check('1H OURS = the PROJ box\'s 1H (30 + 32.4), not the row', /1H Total 62\.4 61 25s/.test(boxOut), true);
check('2H follows 1H, OURS = the box\'s 2H (35 + 38)', /1H Total 62\.4 61 25s 2H Total 73\.0 74\.5 25s/.test(boxOut), true);
const settledBox = withBox([
  { key: 'h1', label: '1H', away: 31, home: 29, state: 'settled' },
  { key: 'h2', label: '2H', away: 35, home: 38, state: 'in_progress' },
]);
const settledOut = text(api.renderLiveRailLines(api.liveRailSummary([...fresh(), h2Row], settledBox, response, NOW)));
check('a SETTLED interval is skipped even if a build still carries its row', /1H/.test(settledOut), false);
check('...and the open one still shows', /2H Total 73\.0 74\.5/.test(settledOut), true);
// A quarter-period card (NBA): the 1H market = Q1 as played + Q2 as projected.
const nbaBox = { ...chip, sport: 'nba', intervals: { source: 'live_resim', final: { total: 228.0, home_margin: 6.0 }, periods: [
  { key: 'q1', away: 25, home: 30, state: 'settled' }, { key: 'q2', away: 27.5, home: 28.5, state: 'in_progress' },
  { key: 'q3', away: 28, home: 29, state: 'ahead' }, { key: 'q4', away: 27, home: 28, state: 'ahead' } ] } };
const nbaH1 = [
  { ...fresh()[8], market: 'totals_alt', line: 110.5, live_total: 109.0, quote: { fair_probability: 0.5 } },
  { ...fresh()[8], market: 'spreads_alt', side: 'home', team: 'Florida St Seminoles', line: -5.5, live_model_probability: 0.55,
    live_total: undefined, quote: { fair_probability: 0.5 } },
];
const nbaOut = text(api.renderLiveRailLines(api.liveRailSummary(nbaH1, nbaBox, response, NOW)));
check('NBA 1H total = Q1 + Q2 from the box (55 + 56)', /1H Total 111\.0 110\.5/.test(nbaOut), true);
check('NBA 1H spread = Q1 + Q2 home margin (5 + 1), named for the line\'s team', /1H Sprd FSU −6\.0 FSU −5\.5/.test(nbaOut), true);
// A PRICED interval (e.g. MLB F5, or any interval the join prices) flags like any line, and counts in its family.
const pricedH1 = fresh().map((row) => (row.segment === 'h1' ? { ...row, live_aware: true, model_edge_pct: 6.5 } : { ...row, live_aware: undefined }));
const pricedSummary = api.liveRailSummary(pricedH1, chip, response, NOW);
check('a priced interval gap on a fresh quote flags', pricedSummary.hasFreshEdge, true);
check('...named with its interval, read off its own numbers', /≠ 1H Total o61: ours 62\.3 · sim 56% vs book 50%/.test(text(api.renderLiveRailLines(pricedSummary))), true);
check('...and counts toward the Total filter', api.liveEdgeFilterMatches(pricedSummary, 'totals'), true);
const staleH1 = pricedH1.map((row) => (row.segment === 'h1' ? { ...row, book_age_seconds: 200 } : row));
check('the same interval gap on a 200 s quote does not', api.liveRailSummary(staleH1, chip, response, NOW).markets.find((m) => m.segment === 'h1').edge, null);
check('summary: fresh gaps in spreads and totals (the spread is sim 68% vs book 50% on a 40 s quote)', JSON.stringify(live.freshEdges), '{"spreads":true,"totals":true}');
check('card highlight fires on a fresh-quote edge', live.hasFreshEdge, true);
check('age cell: the age NOW, green while 120 s or less, with the two numbers it ticks from', /game-mini-card__live-age is-fresh" data-rail-age-priced="12" data-rail-built-at="\d+" title="Quote 12s old when the board priced it; ≈32s now">32s</.test(api.renderLiveRailLines(live)), true);
check('a 40 s quote served 20 s later is green too (60 s now)', /is-fresh[^>]*>60s</.test(api.renderLiveRailLines(live)), true);
check('a 104.5 s quote served 20 s later is past the fresh line: not green', /game-mini-card__live-age"[^>]*>2m</.test(api.renderLiveRailLines(live)), true);

// ---------------------------------------------------------------- the filter
check('filter all keeps it', api.liveEdgeFilterMatches(live, 'all'), true);
check('filter any keeps it', api.liveEdgeFilterMatches(live, 'any'), true);
check('filter totals keeps it', api.liveEdgeFilterMatches(live, 'totals'), true);
check('filter spreads keeps it', api.liveEdgeFilterMatches(live, 'spreads'), true);
check('filter h2h drops it', api.liveEdgeFilterMatches(live, 'h2h'), false);
check('a non-live game (no summary) only survives "all"', api.liveEdgeFilterMatches(null, 'all') && !api.liveEdgeFilterMatches(null, 'any'), true);

// ---------------------------------------------------------------- STALE: the same edge priced against an old quote
const staleRows = fresh().map((row) => ({ ...row, book_age_seconds: 237, quote: { ...row.quote, book_age_seconds: 237 } }));
const stale = api.liveRailSummary(staleRows, chip, response, NOW);
check('stale quote: NO highlight', stale.hasFreshEdge, false);
check('stale quote: filter any drops the game', api.liveEdgeFilterMatches(stale, 'any'), false);
check('stale quote: filter totals drops the game', api.liveEdgeFilterMatches(stale, 'totals'), false);
const staleOut = text(api.renderLiveRailLines(stale));
check('stale quote: no flag line anywhere on the card', /≠|pts/.test(staleOut), false);
check('stale quote: the line still renders, with its age', /Total 145\.9 147\.5 4m/.test(staleOut), true);
check('the boundary: 120 s is fresh, 121 s is not',
  Boolean(api.liveRowFreshEdge({ ...fresh()[2], book_age_seconds: 120 }, response, NOW))
  && !api.liveRowFreshEdge({ ...fresh()[2], book_age_seconds: 121, quote: {} }, response, NOW), true);
check('a 46.8 s quote counts (the 11-10 RUTG o149.5 row)', Boolean(api.liveRowFreshEdge({ ...fresh()[2], book_age_seconds: 46.8 }, response, NOW)), true);
check('a 153.5 s quote does not (the 11-10 RUTG o147.5 row)', api.liveRowFreshEdge({ ...fresh()[2], book_age_seconds: 153.5, quote: {} }, response, NOW), null);

// Fresh at pricing, but the board has not been rebuilt for 10 minutes: the page already calls that price stale.
const frozen = fresh().map((row) => ({ ...row, price_grid_generated_at: '2026-11-10T23:35:00Z' }));
check('fresh at pricing but served 10 min later: NO highlight', api.liveRailSummary(frozen, chip, response, NOW).hasFreshEdge, false);
check('...and its age cell shows the age NOW, in orange', /is-stale"[^>]*title="Quote 12s old when the board priced it; ≈10m now">10m</.test(api.renderLiveRailLines(api.liveRailSummary(frozen, chip, response, NOW))), true);

// A pregame model edge on a live row (no live join) is never a live edge.
const pregameEdge = fresh().map((row) => ({ ...row, live_aware: undefined, live_model_probability: undefined }));
check('model_edge_pct without live_aware or a live sim probability: NO highlight', api.liveRailSummary(pregameEdge, chip, response, NOW).hasFreshEdge, false);
const liveProbOnly = fresh().map((row) => ({ ...row, live_aware: undefined, model_edge_pct: undefined }));
check('a live sim probability on its own is enough: the comparison is information, priced or not', api.liveRailSummary(liveProbOnly, chip, response, NOW).hasFreshEdge, true);
// Below the vig.
const small = fresh().map((row) => {
  const out = row.model_edge_pct ? { ...row, model_edge_pct: Math.sign(row.model_edge_pct) * 2.0 } : { ...row };
  const fair = (row.quote || {}).fair_probability;
  if (typeof row.live_model_probability === 'number' && typeof fair === 'number') out.live_model_probability = fair + 0.02;
  return out;
});
check('a 2-point edge is under the 3-point minimum: NO highlight', api.liveRailSummary(small, chip, response, NOW).hasFreshEdge, false);
// Unknown age is never fresh.
const noAge = fresh().map((row) => ({ ...row, book_age_seconds: null, quote: { ...row.quote, book_age_seconds: undefined } }));
const noAgeSummary = api.liveRailSummary(noAge, chip, response, NOW);
check('no quote age: NO highlight', noAgeSummary.hasFreshEdge, false);
check('no quote age: AGE reads ?', /Total 145\.9 147\.5 \?/.test(text(api.renderLiveRailLines(noAgeSummary))), true);
// A shortlist row (no own grid stamp) is aged from the page's build time.
const shortlistRow = { ...fresh()[2], price_grid_generated_at: undefined };
check('no row stamp: age now = priced age + time since the page build', api.liveQuoteAgeNowSeconds(shortlistRow, response, NOW), 72);

// ---------------------------------------------------------------- spreads with no live number stay blank (NFL / NHL decisions)
const nflChip = { ...chip, sport: 'nfl' };
const noLiveSpread = fresh().map((row) => (row.market === 'spreads' ? { ...row, live_model_probability: undefined } : row));
check('spread with no live number upstream: OURS is blank, not the chip margin',
  /Sprd – FLA −8\.5/.test(text(api.renderLiveRailLines(api.liveRailSummary(noLiveSpread, nflChip, response, NOW)))), true);

// ---------------------------------------------------------------- no chip block: fall back to the row's own live total
const noBlock = { ...chip, intervals: { source: 'pregame_pace', final: { total: 150.0 } } };
check('pace block is not a re-sim: totals OURS comes from the live row',
  /Total 145\.9 149/.test(text(api.renderLiveRailLines(api.liveRailSummary(fresh(), noBlock, response, NOW)))), true);
check('pace block: no margin, so the spread shows the cover probability',
  /Sprd 68% cover FLA −8\.5/.test(text(api.renderLiveRailLines(api.liveRailSummary(fresh(), noBlock, response, NOW)))), true);

// ---------------------------------------------------------------- a chip whose home/away disagree with the book
const flipped = {
  ...chip, away: { abbr: 'FSU', key: 'florida state' }, home: { abbr: 'FLA', key: 'florida' },
  intervals: { source: 'live_resim', final: { total: 145.9, home_margin: 10.2 } },
};
check('flipped chip: team and margin follow the canonical keys',
  /Sprd FLA −10\.2 FLA −8\.5/.test(text(api.renderLiveRailLines(api.liveRailSummary(fresh(), flipped, response, NOW)))), true);

// ---------------------------------------------------------------- no live rows: nothing renders
check('a live game with no live rows renders no line', api.renderLiveRailLines(api.liveRailSummary([], chip, response, NOW)), '');

// ---------------------------------------------------------------- todo #803: one line per market, the card's units
// GT @ CLE, the served board 2026-11-14 19:16Z (full-game totals; our live total 34.508). The table used to read the
// line priced closest to even at any age while the callout named the biggest fresh gap: two different lines.
const gtCle = [
  totals(37.5, 'over', 0.5, { book_age_seconds: 108.5, live_model_probability: 0.4118, live_total: 34.508 }),
  totals(39.5, 'over', 0.511, { book_age_seconds: 305.5, live_model_probability: 0.4118, live_total: 34.508 }),
  totals(37.5, 'under', 0.5, { book_age_seconds: 305.5, live_model_probability: 0.5881, live_total: 34.508 }),
  totals(38.5, 'under', 0.499, { book_age_seconds: 64.5, live_model_probability: 0.5881, live_total: 34.508 }),
  totals(39.5, 'under', 0.488, { book_age_seconds: 351.5, live_model_probability: 0.5881, live_total: 34.508 }),
].map((row) => ({ ...row, quote: { ...row.quote, book_age_seconds: row.book_age_seconds } }));
const ncaafChip = { ...chip, sport: 'ncaaf', intervals: { source: 'live_resim', final: { total: 34.5, home_margin: -9.9 } } };
const gtSummary = api.liveRailSummary(gtCle, ncaafChip, response, NOW);
const gtTotal = gtSummary.markets.find((m) => m.key === 'totals');
check('GT @ CLE: the callout is the 64 s under 38.5 (the 305 s under 37.5 is not fresh)', gtTotal.edge && gtTotal.edge.side, 'u38.5');
check('GT @ CLE: the table row shows that same line', gtTotal.book, '38.5');
check('GT @ CLE: and its age', gtTotal.pricedAge, 64.5);
check('GT @ CLE: the callout reads off the cells above it',
  /≠ Total u38\.5: ours 34\.5 · sim 59% vs book 50%/.test(text(api.renderLiveRailLines(gtSummary))), true);

// With no callout, the table's line comes from the FRESH quotes: an old quote keeps the fair it had when it was the
// main line (the 41.5 that had stood 13 min while the books were at 38.5).
const oldMain = [
  totals(41.5, 'over', 0.5, { book_age_seconds: 780 }),
  totals(38.5, 'over', 0.52, { book_age_seconds: 30 }),
  totals(37.5, 'over', 0.56, { book_age_seconds: 30 }),
];
check('main line: a fresh quote beats an old one priced closer to even', api.liveRailMainRow(oldMain, 'totals').line, 38.5);
check('main line: with no fresh quote, the closest to even of what there is', api.liveRailMainRow(oldMain.map((r) => ({ ...r, book_age_seconds: 400, quote: { ...r.quote, book_age_seconds: 400 } })), 'totals').line, 41.5);

// Every flagged market: the callout's line is the table row's line.
const sameLine = (summary) => summary.markets.filter((m) => m.edge).every((m) => (m.key === 'totals'
  ? m.edge.side.slice(1) === m.book
  : m.key === 'spreads' ? m.edge.side === m.book : m.book.startsWith(m.edge.side)));
check('same line, every flagged market (fixture)', sameLine(live) && live.markets.some((m) => m.edge), true);
check('same line, every flagged market (GT @ CLE)', sameLine(gtSummary), true);

// A spread callout says our margin for the line's team; a moneyline callout says the probabilities only.
const spreadOut = text(api.renderLiveRailLines(live));
check('spread callout: our margin for the line\'s team, then sim vs book', /≠ Spread FLA −8\.5: ours FLA −10\.2 · sim 68% vs book 50%/.test(spreadOut), true);
const mlRows = [{ ...base, market: 'h2h', side: 'away', team: 'Florida Gators', odds: -383, live_model_probability: 0.8387,
  book_age_seconds: 13, quote: { fair_probability: 0.779, book_age_seconds: 13 } }];
const mlOut = text(api.renderLiveRailLines(api.liveRailSummary(mlRows, chip, response, NOW)));
check('moneyline callout: sim vs book, no OURS repeat', /≠ Moneyline FLA: sim 84% vs book 78%/.test(mlOut), true);

// The gap is against the book's NO-VIG fair only: a row with just a price never flags off its vig-inclusive odds.
const noFair = [{ ...base, market: 'totals', line: 150.5, side: 'over', odds: -110, live_model_probability: 0.6, book_age_seconds: 10, quote: { book_age_seconds: 10 } }];
check('no no-vig fair on the row: no callout from the price\'s own (vig) probability', api.liveRailSummary(noFair, chip, response, NOW).hasFreshEdge, false);

// ---------------------------------------------------------------- a flagged total's OURS is its own row's (rail monitor 11-25 R20)
// Liberty @ Princeton o134.5, 11-25 22:22Z: the flagged row's p 0.59 came from its own live total 137.74, while the
// chip's PROJ box carried the NEXT re-sim (134.3, 2.5 s newer). OURS read 134.3 beside an OVER 134.5 flag: the box
// and the probability on opposite sides of the line, from two ticks of one re-sim (user 2026-11-26 "Yes, fix it here").
const r20Chip = { ...chip, intervals: { source: 'live_resim', final: { total: 134.3, home_margin: -1.0 } } };
const r20 = (extra = {}) => [
  totals(134.5, 'over', 0.5, { live_total: 137.74, live_model_probability: 0.59, book_age_seconds: 37.5, ...extra }),
  totals(134.5, 'under', 0.5, { live_total: 137.74, live_model_probability: 0.41, book_age_seconds: 37.5, ...extra }),
].map((row) => ({ ...row, quote: { ...row.quote, book_age_seconds: row.book_age_seconds } }));
const r20Total = api.liveRailSummary(r20(), r20Chip, response, NOW).markets.find((m) => m.key === 'totals');
check('R20: the over 134.5 is flagged', r20Total.edge && r20Total.edge.side, 'o134.5');
check('R20: OURS is the flagged row\'s own live total, not the PROJ box', r20Total.ours, '137.7');
check('R20: the callout reads off it', /≠ Total o134\.5: ours 137\.7 · sim 59% vs book 50%/.test(text(api.renderLiveRailLines(
  api.liveRailSummary(r20(), r20Chip, response, NOW)))), true);
check('R20: the tooltip names the PROJ box\'s other tick', r20Total.oursTip,
  'Live total 137.7: the re-sim this line\'s probability came from. The PROJ box shows 134.3, from another re-sim tick');
check('R20: the OURS cell carries that tooltip', /game-mini-card__live-ours" title="Live total 137\.7: [^"]*PROJ box shows 134\.3/.test(
  api.renderLiveRailLines(api.liveRailSummary(r20(), r20Chip, response, NOW))), true);
// off != on: the same rows UNFLAGGED (a 200 s quote) keep the PROJ box, so the flagged branch is what moved OURS.
const r20Stale = api.liveRailSummary(r20({ book_age_seconds: 200 }), r20Chip, response, NOW).markets.find((m) => m.key === 'totals');
check('R20 unflagged (200 s quote): no flag', r20Stale.edge, null);
check('R20 unflagged: OURS stays the PROJ box', `${r20Stale.ours}|${r20Stale.oursTip}`, '134.3|null');
check('R20: flagged and unflagged OURS differ (the branch is reached)', r20Total.ours !== r20Stale.ours, true);
// When the box and the row agree to the shown decimal there is nothing to explain: no tooltip.
const r20Same = api.liveRailSummary(r20({ live_total: 134.32 }), r20Chip, response, NOW).markets.find((m) => m.key === 'totals');
check('flagged, own = box to one decimal: OURS 134.3 and no tooltip', `${r20Same.ours}|${r20Same.oursTip}`, '134.3|null');
// No re-sim box on the chip: the flagged row's own number, as before, with no tooltip.
const r20NoBox = api.liveRailSummary(r20(), { ...chip, intervals: null }, response, NOW).markets.find((m) => m.key === 'totals');
check('flagged, no PROJ box: OURS is the row\'s own, no tooltip', `${r20NoBox.ours}|${r20NoBox.oursTip}`, '137.7|null');
// A flagged row with no live total of its own falls back to the box, as before.
const r20NoOwn = api.liveRailSummary(r20({ live_total: undefined }), r20Chip, response, NOW).markets.find((m) => m.key === 'totals');
check('flagged, no own live total: OURS falls back to the PROJ box', `${r20NoOwn.ours}|${r20NoOwn.oursTip}`, '134.3|null');
// Full game only: a FLAGGED interval keeps the PROJ box's period (the 2026-11-11 INTERVALS decision).
const r20H1 = { ...fresh()[8], live_total: 60.1 };
const r20H1Box = withBox([{ key: 'h1', label: '1H', away: 30, home: 32.4, state: 'in_progress' }]);
const r20H1Out = api.liveRailSummary([r20H1], r20H1Box, response, NOW).markets.find((m) => m.segment === 'h1');
check('a flagged 1H total keeps the box\'s 1H (62.4), not its own 60.1', `${Boolean(r20H1Out.edge)}|${r20H1Out.ours}|${r20H1Out.oursTip}`, 'true|62.4|null');

// ---------------------------------------------------------------- todo #803: the age NOW, counting between refreshes
const liveHtml = api.renderLiveRailLines(live);
check('the callout says how old its quote is now', /≠ Total u149: ours 145\.9 · sim 66% vs book 56% · 32s old/.test(text(liveHtml)), true);
check('a callout on a quote still inside 120 s is not faded', /class="game-mini-card__live-edge" data-rail-age-priced="12"[^>]* title=/.test(liveHtml), true);
// Priced on a 100 s quote, served 40 s later: 140 s old now. Still called out (the rule tests the age at pricing
// and the 300 s stale line), but faded.
const agedRows = fresh().map((row) => (row.line === 149.0 && row.side === 'under'
  ? { ...row, book_age_seconds: 100, quote: { ...row.quote, book_age_seconds: 100 }, price_grid_generated_at: '2026-11-10T23:44:20Z' } : row));
const agedHtml = api.renderLiveRailLines(api.liveRailSummary(agedRows, chip, response, NOW));
check('aged callout: still shown', /≠ Total u149/.test(text(agedHtml)), true);
check('aged callout: faded, with its age now', /class="game-mini-card__live-edge"[^>]*style="opacity:0\.55"[^>]*>≠ Total u149[^<]*<span class="game-mini-card__live-edge-age">2m old<\/span>/.test(agedHtml), true);

// The ticker: a fake DOM of one age cell and one callout, rendered at NOW, ticked 60 s later.
function fakeEl(cls, attrs, text0, child) {
  const classes = new Set(cls.split(' '));
  return {
    textContent: text0, style: { opacity: '' }, attrs,
    classList: { contains: (c) => classes.has(c), toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); }, has: (c) => classes.has(c) },
    getAttribute: (k) => attrs[k], querySelector: () => child || null,
  };
}
const builtMs = String(Date.parse(BUILT));
const ageCell = fakeEl('game-mini-card__live-age is-fresh', { 'data-rail-age-priced': '12', 'data-rail-built-at': builtMs }, '32s');
const edgeAge = { textContent: '32s old' };
const callout = fakeEl('game-mini-card__live-edge', { 'data-rail-age-priced': '12', 'data-rail-built-at': builtMs }, '', edgeAge);
const root = { querySelectorAll: () => [ageCell, callout] };
check('the ticker updates both elements', api.tickLiveRailAges(root, NOW + 60000), 2);
check('...the age cell now reads 92 s (formatAge: 2m), still green', `${ageCell.textContent}|${ageCell.classList.has('is-fresh')}`, '2m|true');
check('...the callout\'s age follows', edgeAge.textContent, '2m old');
api.tickLiveRailAges(root, NOW + 120000);
check('a tick past 120 s (152 s): the age cell leaves green', `${ageCell.textContent}|${ageCell.classList.has('is-fresh')}|${ageCell.classList.has('is-stale')}`, '3m|false|false');
check('...and the callout fades', callout.style.opacity, '0.55');
api.tickLiveRailAges(root, NOW + 300000);
check('a tick past 300 s: orange', ageCell.classList.has('is-stale'), true);
check('the ticker runs every 5 s and fetches nothing', api.LIVE_RAIL_AGE_TICK_MS === 5000 && !/fetch\(/.test(block[0].split('function tickLiveRailAges')[1] || ''), true);
check('a row with no build time carries no tick attributes', /data-rail-built-at/.test(api.renderLiveRailLines(api.liveRailSummary(fresh().map((r) => ({ ...r, price_grid_generated_at: undefined })), chip, {}, NOW))), false);

// ---------------------------------------------------------------- todo #803: the rail's own 15 s refresh
const OLDER = '2026-11-10T23:44:00Z';
const NEWER = '2026-11-10T23:44:50Z';
const boardRows = () => [
  { ...totals(149.0, 'over', 0.44), sport: 'ncaab', event_id: 'ev1', price_grid_generated_at: OLDER },
  { ...totals(149.0, 'under', 0.56), sport: 'ncaab', event_id: 'ev1', price_grid_generated_at: OLDER },
  { ...base, market: 'spreads', side: 'home', line: 8.5, odds: -110, sport: 'ncaab', event_id: 'ev1', price_grid_generated_at: OLDER,
    quote: { fair_probability: 0.5 } },
  { kind: 'prop', market: 'player_points', sport: 'ncaab', event_id: 'ev1', line: 18.5, player_name: 'X' },
];
// The book moved the total to 150.5: the fresh group for that identity carries only the new line.
const freshTotals = [
  { ...totals(150.5, 'over', 0.48), sport: 'ncaab', event_id: 'ev1', price_grid_generated_at: NEWER },
  { ...totals(150.5, 'under', 0.52), sport: 'ncaab', event_id: 'ev1', price_grid_generated_at: NEWER },
];
const freshNewGame = [{ ...totals(130.5, 'over', 0.5), sport: 'ncaab', event_id: 'ev9', price_grid_generated_at: NEWER }];
check('the rail polls every 15 s', api.LIVE_RAIL_FAST_POLL_MS, 15000);
check('identity is game, market, segment, player -- not line or side (the server merge\'s)',
  api.liveRailIdentity(freshTotals[0]) === api.liveRailIdentity(boardRows()[1]), true);
const merged = api.mergeLiveRailFresh(boardRows(), { rows: [...freshTotals, ...freshNewGame] });
const mergedTotals = merged.filter((r) => r.market === 'totals');
check('a moved line replaces the identity\'s whole group: only 150.5 remains', JSON.stringify(mergedTotals.map((r) => `${r.side}${r.line}`).sort()), '["over150.5","under150.5"]');
check('an identity the fresh poll does not carry is kept (the spread)', merged.some((r) => r.market === 'spreads' && r.line === 8.5), true);
check('a non-rail row is never touched (the prop)', merged.some((r) => r.kind === 'prop'), true);
check('an identity the board does not show is not added (waits for the whole-board poll)', merged.some((r) => r.event_id === 'ev9'), false);
const staleFresh = freshTotals.map((r) => ({ ...r, price_grid_generated_at: '2026-11-10T23:43:00Z' }));
check('older fresh rows never overwrite newer board rows', JSON.stringify(api.mergeLiveRailFresh(boardRows(), { rows: staleFresh })
  .filter((r) => r.market === 'totals').map((r) => r.line)), '[149,149]');
const unchanged = boardRows();
check('no fresh rows: the board\'s own list, untouched', api.mergeLiveRailFresh(unchanged, null) === unchanged
  && api.mergeLiveRailFresh(unchanged, { rows: [] }) === unchanged, true);
// Through the summary: the rail reads the fresh line.
const railFresh = api.liveRailSummary(api.mergeLiveRailFresh(boardRows().filter((r) => r.kind !== 'prop'), { rows: freshTotals }), null, response, NOW);
check('the rail\'s total row reads the fresh line', railFresh.markets.find((m) => m.key === 'totals').book, '150.5');

// The page wiring (source checks): renderGameCards merges, the poller is the shared one, the off switch stops it,
// and the strip keeps its scroll.
check('renderGameCards builds the rail rows through the merge', /for \(const item of mergeLiveRailFresh\(items, liveRailFresh\)\)/.test(html), true);
check('renderGameCards records whether the rail shows a live game', /liveRailHasLive = liveSummaries\.size > 0;/.test(html), true);
const loader = html.match(/ {2}async function loadLiveRail\(\)[\s\S]*?\n {2}}\n/);
check('loadLiveRail exists', Boolean(loader), true);
const ld = loader ? loader[0] : '';
check('it polls only while the rail shows a live game', /if \(!liveRailHasLive\) return;/.test(ld), true);
check('it reads the light endpoint, uncached', /fetch\("\/api\/board\/live-rail", \{ cache: "no-store" \}\)/.test(ld), true);
check('the server\'s off switch stops it for good', /body\.enabled === false[\s\S]*liveRailPoller\.stop\(\)/.test(ld), true);
check('nothing new (same newest overlay): no re-render', /previous\.newest === liveRailFresh\.newest\) return;/.test(ld), true);
check('the re-render keeps the strip\'s horizontal scroll', /scrollLeft = strip \? strip\.scrollLeft : 0[\s\S]*after\.scrollLeft = scrollLeft/.test(ld), true);
check('the poller is the shared one, paused when hidden and idle, its own interval',
  /SyndicatePolling\.start\(\{\s*intervalMs: LIVE_RAIL_FAST_POLL_MS,\s*onTick: loadLiveRail,\s*skipWhenHidden: true,[\s\S]*idleTimeoutMs: 15 \* 60 \* 1000,/.test(html), true);

// ---------------------------------------------------------------- wiring in renderGameCards
const render = html.match(/ {2}function renderGameCards\(items\)[\s\S]*?\n {2}}\n/);
check('renderGameCards exists', Boolean(render), true);
const r = render ? render[0] : '';
check('it builds one summary per live game', /liveRailSummary\(liveRowsByGame\.get\(game\.key\) \|\| \[\], chip, lastResponseForActions, nowMs\)/.test(r), true);
check('rows are keyed through the #165 merge map', /gameKeyMergeMap\.get\(raw\) \|\| raw/.test(r), true);
check('a live chip card renders the live lines', /\$\{isLive \? renderLiveRailLines\(liveSummary\) : ""\}/.test(r), true);
check('a chip-less live card renders them too', /\$\{game\.hasLive \? renderLiveRailLines\(liveSummary\) : ""\}/.test(r), true);
check('the card highlight is the fresh-edge flag', /liveEdge \? " game-mini-card--live-edge" : ""/.test(r), true);
check('the rail is filtered by the live-edge filter (and the rail sport, #806)', /const edgeMatch = \(game\) => liveEdgeFilterMatches\(liveSummaries\.get\(game\.key\), liveFilter\);/.test(r)
  && /games\.filter\(\(game\) => game\.key === state\.game \|\| \(railSportMatches\(game, railSport\) && edgeMatch\(game\)\)\)/.test(r), true);
check('the filter tabs are rendered', /data-live-edge-filter=/.test(r), true);
check('the empty note speaks of a fresh line, not an edge', r.includes('No live game has our model off a fresh ${liveFilter === "any" ? "" :'), true);
check('the card badge reads MODEL ≠ LINE, never EDGE', /MODEL ≠ LINE<\/span>/.test(r) && !/>▲ EDGE</.test(r), true);
check('the first filter tab is "Model ≠ line"', /\{ value: "any", label: "Model ≠ line" \}/.test(block[0]), true);
check('the filter is in the URL', /url\.searchParams\.set\("live_edge", state\.liveEdge\)/.test(html), true);
check('the filter is NOT a board-row default (rail-only view)', /FILTER_DEFAULTS = \{[^}]*liveEdge/.test(html), false);

console.log(`\n${failures ? `${failures} assertion(s) failed` : 'all passed'}`);
process.exit(failures ? 1 : 0);
