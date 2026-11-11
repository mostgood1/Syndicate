// Live lines + fresh-quote live-edge flag on the Games-rail cards (lane layer2-live-rail-edges, todo #781).
//
// A live rail card now shows, per full-game market, our live re-sim number against the book's main live line
// and the quote's age; the card is highlighted, and the rail filter keeps it, ONLY when a live edge was priced
// against a FRESH quote (todo #780: live edges on quotes older than ~30 s graded as the line not having moved).
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
  return { liveRailMarketKey, liveQuotePricingAgeSeconds, liveQuoteAgeNowSeconds, liveRowFreshEdge, liveRailMainRow,
           liveRailSummary, liveEdgeFilterMatches, renderLiveRailLines,
           LIVE_EDGE_FRESH_QUOTE_SECONDS, LIVE_EDGE_MIN_PP, LIVE_PRICE_STALE_AFTER_SECONDS };
`)(escapeHtml, trimClubAffixes);

const text = (out) => out.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------- the stated defaults
check('fresh-quote threshold is 30 s (the bucket #780 graded as fresh)', api.LIVE_EDGE_FRESH_QUOTE_SECONDS, 30);
check('minimum live edge is 3 points', api.LIVE_EDGE_MIN_PP, 3);
check('the block states the #780 reason in code', /#780/.test(block[0]) && /REALISED/.test(block[0]), true);
check('the join ceiling is named and NOT changed here', /_DEFAULT_MAX_QUOTE_AGE_SECONDS/.test(block[0]) && /NOT made here/.test(block[0]), true);

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
  // A first-half total: not a full-game line, never on the rail line.
  { ...base, market: 'totals', segment: 'h1', line: 61.0, side: 'over', live_aware: true, model_edge_pct: 22,
    book_age_seconds: 5, quote: { fair_probability: 0.5 } },
];

// ---------------------------------------------------------------- row selection
check('a live full-game total is a rail row', api.liveRailMarketKey(fresh()[0]), 'totals');
check('a first-half row is not', api.liveRailMarketKey(fresh()[8]), null);
check('a pregame row is not', api.liveRailMarketKey({ ...fresh()[0], market_state: 'pregame', is_live: false }), null);
check('a prop row is not', api.liveRailMarketKey({ ...fresh()[0], kind: 'prop' }), null);
const mainTotal = api.liveRailMainRow(fresh().slice(0, 5), 'totals');
check('main total = the line priced closest to even', mainTotal.line, 147.5);
const mainSpread = api.liveRailMainRow(fresh().slice(5, 7), 'spreads');
check('main spread names the favourite side of the line', mainSpread.line, -8.5);

// ---------------------------------------------------------------- the live line renders for a live game with a priced row
const live = api.liveRailSummary(fresh(), chip, response, NOW);
check('three markets on the line', live.markets.map((m) => m.key).join(','), 'spreads,totals,h2h');
const out = text(api.renderLiveRailLines(live));
check('header: LIVE OURS BOOK AGE', /^LIVE OURS BOOK AGE/.test(out), true);
check('total: our re-sim (the card\'s own Proj final) vs the main line, with the quote age at pricing', /Total 145\.9 147\.5 12s/.test(out), true);
check('spread: our margin restated for the line\'s team vs the book line', /Sprd FLA −10\.2 FLA −8\.5 40s/.test(out), true);
check('moneyline: our live % vs the book price', /ML FSU 14% FSU \+575 2m/.test(out), true);
check('fresh-quote edge is flagged with its line, size and quote age', /▲ Total u149 \+10\.3 pts · 12s quote/.test(out), true);
check('the half-time row never reaches the line', /61/.test(out), false);
check('summary: fresh edge in totals only', JSON.stringify(live.freshEdges), '{"totals":true}');
check('card highlight fires on a fresh-quote edge', live.hasFreshEdge, true);
check('age cell green on a fresh quote, showing the age the flag tested', /game-mini-card__live-age is-fresh" title="Quote 12s old when priced; ≈32s now">12s</.test(api.renderLiveRailLines(live)), true);
check('a 40 s quote is not green', /is-fresh[^>]*>40s</.test(api.renderLiveRailLines(live)), false);

// ---------------------------------------------------------------- the filter
check('filter all keeps it', api.liveEdgeFilterMatches(live, 'all'), true);
check('filter any keeps it', api.liveEdgeFilterMatches(live, 'any'), true);
check('filter totals keeps it', api.liveEdgeFilterMatches(live, 'totals'), true);
check('filter spreads drops it (no spread edge)', api.liveEdgeFilterMatches(live, 'spreads'), false);
check('filter h2h drops it', api.liveEdgeFilterMatches(live, 'h2h'), false);
check('a non-live game (no summary) only survives "all"', api.liveEdgeFilterMatches(null, 'all') && !api.liveEdgeFilterMatches(null, 'any'), true);

// ---------------------------------------------------------------- STALE: the same edge priced against an old quote
const staleRows = fresh().map((row) => ({ ...row, book_age_seconds: 237, quote: { ...row.quote, book_age_seconds: 237 } }));
const stale = api.liveRailSummary(staleRows, chip, response, NOW);
check('stale quote: NO highlight', stale.hasFreshEdge, false);
check('stale quote: filter any drops the game', api.liveEdgeFilterMatches(stale, 'any'), false);
check('stale quote: filter totals drops the game', api.liveEdgeFilterMatches(stale, 'totals'), false);
const staleOut = text(api.renderLiveRailLines(stale));
check('stale quote: no edge line anywhere on the card', /▲|pts/.test(staleOut), false);
check('stale quote: the line still renders, with its age', /Total 145\.9 147\.5 4m/.test(staleOut), true);
check('the boundary: 30 s is fresh, 31 s is not',
  Boolean(api.liveRowFreshEdge({ ...fresh()[2], book_age_seconds: 30 }, response, NOW))
  && !api.liveRowFreshEdge({ ...fresh()[2], book_age_seconds: 31, quote: {} }, response, NOW), true);

// Fresh at pricing, but the board has not been rebuilt for 10 minutes: the page already calls that price stale.
const frozen = fresh().map((row) => ({ ...row, price_grid_generated_at: '2026-11-10T23:35:00Z' }));
check('fresh at pricing but served 10 min later: NO highlight', api.liveRailSummary(frozen, chip, response, NOW).hasFreshEdge, false);
check('...and its age cell shows the age NOW, in orange', /is-stale" title="Quote 12s old when priced; ≈10m now">10m</.test(api.renderLiveRailLines(api.liveRailSummary(frozen, chip, response, NOW))), true);

// A pregame model edge on a live row (no live join) is never a live edge.
const pregameEdge = fresh().map((row) => ({ ...row, live_aware: undefined }));
check('model_edge_pct without live_aware: NO highlight', api.liveRailSummary(pregameEdge, chip, response, NOW).hasFreshEdge, false);
// Below the vig.
const small = fresh().map((row) => (row.model_edge_pct ? { ...row, model_edge_pct: Math.sign(row.model_edge_pct) * 2.0 } : row));
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
  /Total 145\.9 147\.5/.test(text(api.renderLiveRailLines(api.liveRailSummary(fresh(), noBlock, response, NOW)))), true);
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

// ---------------------------------------------------------------- wiring in renderGameCards
const render = html.match(/ {2}function renderGameCards\(items\)[\s\S]*?\n {2}}\n/);
check('renderGameCards exists', Boolean(render), true);
const r = render ? render[0] : '';
check('it builds one summary per live game', /liveRailSummary\(liveRowsByGame\.get\(game\.key\) \|\| \[\], chip, lastResponseForActions, nowMs\)/.test(r), true);
check('rows are keyed through the #165 merge map', /gameKeyMergeMap\.get\(raw\) \|\| raw/.test(r), true);
check('a live chip card renders the live lines', /\$\{isLive \? renderLiveRailLines\(liveSummary\) : ""\}/.test(r), true);
check('a chip-less live card renders them too', /\$\{game\.hasLive \? renderLiveRailLines\(liveSummary\) : ""\}/.test(r), true);
check('the card highlight is the fresh-edge flag', /liveEdge \? " game-mini-card--live-edge" : ""/.test(r), true);
check('the rail is filtered by the live-edge filter', /games\.filter\(\(game\) => game\.key === state\.game \|\| liveEdgeFilterMatches\(liveSummaries\.get\(game\.key\), liveFilter\)\)/.test(r), true);
check('the filter tabs are rendered', /data-live-edge-filter=/.test(r), true);
check('the empty note says "an edge" / "a moneyline edge"', r.includes('liveFilter === "any" ? "an" : `a ${escapeHtml(((LIVE_RAIL_MARKETS.find('), true);
check('the filter is in the URL', /url\.searchParams\.set\("live_edge", state\.liveEdge\)/.test(html), true);
check('the filter is NOT a board-row default (rail-only view)', /FILTER_DEFAULTS = \{[^}]*liveEdge/.test(html), false);

console.log(`\n${failures ? `${failures} assertion(s) failed` : 'all passed'}`);
process.exit(failures ? 1 : 0);
