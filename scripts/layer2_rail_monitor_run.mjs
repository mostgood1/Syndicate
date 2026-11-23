// Read-only: run the SERVED page's own Games-rail code over served payloads, one reading.
// Usage: node layer2_rail_monitor_run.mjs <served.html> <query.json> <chips.json> <liverail.json> <nowIso> <out.json> [<railDate>|all]
// Driven by scripts/layer2_rail_monitor_probe.py.
// Lane layer2-rail-monitor. Nothing here restates the page's rules: deriveGameCards, chipForGame,
// gameKey, mergeLiveRailFresh, liveRailSummary and liveRowFreshEdge are sliced from the served HTML.
import fs from 'fs';

const [tplPath, qPath, chipsPath, lrPath, nowIso, outPath, railDateArg] = process.argv.slice(2);
const html = fs.readFileSync(tplPath, 'utf8').split('\r\n').join('\n');
function slice(a, b) {
  const i = html.indexOf(a), j = html.indexOf(b, i + 1);
  if (i < 0 || j < 0 || j <= i) throw new Error(`slice ${a} .. ${b} not found`);
  return html.slice(i, j);
}
function fnSrc(name) {
  const re = new RegExp(` {2}function ${name}\\([\\s\\S]*?\\n {2}}\\n`);
  const m = html.match(re);
  if (!m) throw new Error(`function ${name} not found`);
  return m[0];
}
const stale = html.match(/const LIVE_PRICE_STALE_AFTER_SECONDS = (\d+);/);
const block = html.match(/ {2}\/\/ ===== LIVE RAIL LINES -- BEGIN[\s\S]*?\/\/ ===== LIVE RAIL LINES -- END =====/);
if (!stale || !block) throw new Error('rail block or stale constant missing');
const src = [
  `const LIVE_PRICE_STALE_AFTER_SECONDS = ${Number(stale[1])};`,
  fnSrc('escapeHtml'), fnSrc('matchesDateFilter'), fnSrc('formatAge'), fnSrc('boardBuildEpochMs'), fnSrc('rehydrateAliases'),
  slice('const CLUB_AFFIXES', '// `layer2-board-chip-race`. The FIRST call to `renderGameCards`'),
  fnSrc('trimClubAffixes'),
  slice('function chipForGame', 'function chipTeamRow'),
  slice('function displayMatchup', 'function gameKey'),
  slice('function gameKey', '// A whole-numbered line must keep its decimal'),
  slice('function deriveGameCards', 'function renderGameCards'),
  block[0],
].join('\n');

// The page's DEFAULT day is today, Central (user decision 2026-08-17); pass 'all' for the combined window.
let state = { sport: 'all', date: railDateArg && railDateArg !== 'all' ? railDateArg : null, liveEdge: 'all', railSport: 'all' };
let gameChipsById = new Map(), gameChipsByMatchup = new Map(), gameChipsByCanonical = new Map(),
  gameChipsByMatchupLoose = new Map(), gameKeyMergeMap = new Map();
const recommendationState = (item) => {
  const s = String((item && (item.market_state || item.game_state)) || '').toLowerCase();
  return s === 'live' || (item && item.is_live === true) ? 'live' : (s === 'final' ? 'final' : 'pregame');
};
const names = ['deriveGameCards', 'chipForGame', 'gameKey', 'mergeLiveRailFresh', 'liveRailMarketKey', 'liveRailSummary',
  'liveRowFreshEdge', 'liveRowGap', 'liveQuotePricingAgeSeconds', 'liveQuoteAgeNowSeconds', 'normalizeClubName',
  'rehydrateAliases', 'liveRailIdentity', 'matchesDateFilter', 'pickChipByStart'];
const fn = new Function('state', 'gameChipsById', 'gameChipsByMatchup', 'gameChipsByCanonical', 'gameChipsByMatchupLoose',
  'gameKeyMergeMap', 'recommendationState',
  `${src}\n; return { ${names.map((n) => `${n}: typeof ${n} === "function" ? ${n} : null`).join(', ')} };`);
const api = fn(state, gameChipsById, gameChipsByMatchup, gameChipsByCanonical, gameChipsByMatchupLoose, gameKeyMergeMap, recommendationState);
const missing = names.filter((n) => !api[n]);

// Chips indexed as loadGameChips() does. The exact index (since 2026-09-22, addExactMatchup) and the canonical
// index (since 2026-11-23, addCanonical, 3983309ce) keep a LIST per key, and chipForGame chooses through
// pickChipByStart. Only the loose index still drops a collided key. Until 11-23 this script dropped canonical
// collisions too, so the MLS playoff pair (LAFC @ St. Louis on 11-24 01:00Z and 12-03 01:00Z) read chip-less here
// while the page joined it; and its exact index kept only the last chip, a doubleheader's later half.
const chips = JSON.parse(fs.readFileSync(chipsPath, 'utf8')).chips || [];
const norm = api.normalizeClubName;
const looseCollisions = new Set();
// One GAME listed twice (same game_key) replaces its entry; a different game on the key is another candidate.
const addListed = (index, indexKey, chip) => {
  const list = index.get(indexKey);
  if (!list) { index.set(indexKey, [chip]); return; }
  if (list.includes(chip)) return;
  const chipKey = String(chip.game_key || '').trim();
  const same = chipKey ? list.findIndex((o) => String(o.game_key || '').trim() === chipKey) : -1;
  if (same >= 0) list[same] = chip; else list.push(chip);
};
for (const chip of chips) {
  const sport = String(chip.sport || '').toLowerCase();
  const key = String(chip.game_key || '').trim();
  if (key) gameChipsById.set(`${sport}|${key}`, chip);
  const matchup = String(chip.matchup || '').trim().toLowerCase();
  if (matchup) addListed(gameChipsByMatchup, `${sport}|${matchup}`, chip);
  const awayName = String((chip.away || {}).name || '').trim().toLowerCase();
  const homeName = String((chip.home || {}).name || '').trim().toLowerCase();
  if (awayName && homeName) addListed(gameChipsByMatchup, `${sport}|${awayName} @ ${homeName}`, chip);
  const awayKey = String((chip.away || {}).key || '').trim().toLowerCase();
  const homeKey = String((chip.home || {}).key || '').trim().toLowerCase();
  if (awayKey && homeKey) addListed(gameChipsByCanonical, `${sport}|${awayKey} @ ${homeKey}`, chip);
  if (awayName && homeName && norm) {
    const l = `${sport}|${norm(awayName)} @ ${norm(homeName)}`;
    if (gameChipsByMatchupLoose.has(l)) looseCollisions.add(l); else gameChipsByMatchupLoose.set(l, chip);
  }
}
for (const k of looseCollisions) gameChipsByMatchupLoose.delete(k);
// A page older than 3983309ce has no list-aware chipForGame; fail loud rather than read every list as a chip.
if (!/pickChipByStart\(gameChipsByCanonical\.get\(/.test(html)) throw new Error('served page predates the list canonical index (3983309ce)');

const q = JSON.parse(fs.readFileSync(qPath, 'utf8'));
const resp = q.response || q;
api.rehydrateAliases(resp);
const items = (resp.top_opportunities && resp.top_opportunities.length) ? resp.top_opportunities : (resp.recommendations || []);
const liveRail = JSON.parse(fs.readFileSync(lrPath, 'utf8'));
const nowMs = Date.parse(nowIso);

// renderBoardBody: renderGameCards(lastRenderItems.filter(matchesDateFilter)).
const dateFiltered = items.filter(api.matchesDateFilter);
const cards = api.deriveGameCards(dateFiltered);
// Live rows per card, exactly as renderGameCards keys them.
const liveRowsByGame = new Map();
const merged = api.mergeLiveRailFresh(dateFiltered, liveRail);
for (const item of merged) {
  if (!api.liveRailMarketKey(item)) continue;
  const raw = api.gameKey(item);
  const key = raw ? (gameKeyMergeMap.get(raw) || raw) : null;
  if (!key) continue;
  if (!liveRowsByGame.has(key)) liveRowsByGame.set(key, []);
  liveRowsByGame.get(key).push(item);
}
const out = { missing, railDate: state.date, items: items.length, dateFiltered: dateFiltered.length, merged: merged.length, cards: [], chips: chips.length };
for (const game of cards) {
  const chip = api.chipForGame(game);
  const live = chip ? chip.state === 'live' : Boolean(game.hasLive);
  const rec = {
    key: game.key, sport: game.sportSlug || game.sport, matchup: game.matchup, count: game.count,
    awayKey: game.awayKey || null, homeKey: game.homeKey || null, hasLive: Boolean(game.hasLive),
    chip: chip ? { game_key: chip.game_key, state: chip.state, matchup: chip.matchup, away: chip.away && { abbr: chip.away.abbr, name: chip.away.name, key: chip.away.key }, home: chip.home && { abbr: chip.home.abbr, name: chip.home.name, key: chip.home.key }, start: chip.start_time_utc, status: chip.status || chip.status_text || null } : null,
    live,
  };
  if (live) {
    const rows = liveRowsByGame.get(game.key) || [];
    const summary = api.liveRailSummary(rows, chip, resp, nowMs);
    rec.liveRows = rows.length;
    rec.markets = summary.markets.map((m) => ({ key: m.key, segment: m.segment, label: m.label, ours: m.ours, book: m.book, ageNow: m.ageNow, pricedAge: m.pricedAge, edge: m.edge }));
    rec.hasFreshEdge = summary.hasFreshEdge;
    // Every live row's own flag verdict and gap, for the independent cross-check.
    rec.rows = rows.map((r) => ({
      id: api.liveRailIdentity(r), market: r.market, segment: r.segment || 'full', side: r.side, line: r.line, odds: r.odds,
      team: r.team || r.display_name, live_aware: r.live_aware, model_edge_pct: r.model_edge_pct,
      live_model_probability: r.live_model_probability, fair: (r.quote || {}).fair_probability ?? (r.quote || {}).fair_consensus_prob ?? null,
      book_age_seconds: r.book_age_seconds ?? (r.quote || {}).book_age_seconds ?? null,
      seen_age_seconds: (r.quote || {}).quote_seen_age_seconds ?? null, price_grid_generated_at: r.price_grid_generated_at || null,
      source: r.source || null, live_total: r.live_total ?? null,
      fresh: api.liveRowFreshEdge(r, resp, nowMs), gap: api.liveRowGap(r),
      ageNow: api.liveQuoteAgeNowSeconds(r, resp, nowMs),
    }));
  }
  out.cards.push(rec);
}
// TEAM-MISMATCH DETECTORS, ported from tests/js/game_rail_production_replay.mjs (same joins, same reasons).
// They resolve chips with the script's OWN join, never chipForGame (learnings 2026-09-16 FORBIDDEN: a detector
// keyed on a field the defect writes reads 0 in both states). Detector 3 is the one that sees the 09-16 shape.
function slugOfCard(c) {
  const parts = String(c.key || '').split('|');
  return (parts[0] === 'chip' ? parts[1] : parts[0] || '').toLowerCase();
}
function resolveChip(c) {
  const sport = slugOfCard(c);
  if (gameChipsById.has(c.key)) return gameChipsById.get(c.key);
  const matchup = String(c.matchup || '').trim().toLowerCase();
  // Both indexes hold lists (see the indexing above); a list is chosen on the card's start, or refused.
  const exact = api.pickChipByStart(gameChipsByMatchup.get(`${sport}|${matchup}`), c);
  if (exact) return exact;
  const ak = String(c.awayKey || '').trim().toLowerCase();
  const hk = String(c.homeKey || '').trim().toLowerCase();
  if (ak && hk) {
    const canonical = api.pickChipByStart(gameChipsByCanonical.get(`${sport}|${ak} @ ${hk}`), c);
    if (canonical) return canonical;
  }
  const sides = matchup.split(' @ ');
  if (sides.length !== 2 || !norm) return null;
  return gameChipsByMatchupLoose.get(`${sport}|${norm(sides[0])} @ ${norm(sides[1])}`) || null;
}
const perChip = new Map();
for (const c of cards) {
  const chip = resolveChip(c);
  if (!chip) continue;
  if (!perChip.has(chip)) perChip.set(chip, []);
  perChip.get(chip).push(c);
}
out.det1 = [...perChip].filter(([, l]) => l.length > 1).map(([chip, l]) => ({ sport: chip.sport, chip: chip.matchup, game_key: chip.game_key, cards: l.map((c) => `${c.matchup} n=${c.count}`) }));
const pairIndex = new Map();
for (const c of cards) {
  const sides = String(c.matchup || '').toLowerCase().split(' @ ');
  if (sides.length !== 2 || !norm) continue;
  const k = `${slugOfCard(c)}|${norm(sides[0])} @ ${norm(sides[1])}`;
  if (!pairIndex.has(k)) pairIndex.set(k, []);
  pairIndex.get(k).push(c);
}
out.det2 = [...pairIndex].filter(([, l]) => l.length > 1).map(([k, l]) => ({ pair: k, cards: l.map((c) => `${c.matchup} n=${c.count}`) }));
const rowPairs = new Map();
for (const it of dateFiltered) {
  const ak = String(it.away_key || '').trim().toLowerCase();
  const hk = String(it.home_key || '').trim().toLowerCase();
  if (!ak || !hk) continue;
  const k = `${String((it.sport_slug || it.sport) || '').trim().toLowerCase()}|${ak} @ ${hk}`;
  rowPairs.set(k, (rowPairs.get(k) || 0) + 1);
}
out.det3 = [];
for (const c of cards) {
  if (!String(c.key || '').startsWith('chip|')) continue;
  const chip = resolveChip(c);
  if (!chip) continue;
  const ak = String((chip.away || {}).key || '').trim().toLowerCase();
  const hk = String((chip.home || {}).key || '').trim().toLowerCase();
  if (!ak || !hk) continue;
  const n = rowPairs.get(`${slugOfCard(c)}|${ak} @ ${hk}`) || 0;
  const flipped = rowPairs.get(`${slugOfCard(c)}|${hk} @ ${ak}`) || 0;
  if (n || flipped) out.det3.push({ sport: chip.sport, chip: chip.matchup, game_key: chip.game_key, seeded: c.matchup, count: c.count, rows_same: n, rows_flipped: flipped });
}
// Chip-less cards (the 11-07 "Tenn-Martin @ IUPUI" shape), with the rows behind them.
out.chipless = cards.filter((c) => !api.chipForGame(c)).map((c) => {
  const rows = dateFiltered.filter((it) => { const raw = api.gameKey(it); return raw && (gameKeyMergeMap.get(raw) || raw) === c.key; });
  return { sport: c.sportSlug || c.sport, key: c.key, matchup: c.matchup, count: c.count, awayKey: c.awayKey || null, homeKey: c.homeKey || null,
    sample: rows.slice(0, 3).map((r) => ({ market: r.market, away_team: r.away_team, home_team: r.home_team, away_key: r.away_key, home_key: r.home_key, game_date: r.game_date, commence_time: r.commence_time, source: r.source })) };
});
// Flipped orientation: a card whose rows' home key is the chip's AWAY key.
out.flipped = [];
for (const c of cards) {
  const chip = api.chipForGame(c);
  if (!chip || !c.awayKey || !c.homeKey) continue;
  const ak = String((chip.away || {}).key || '').toLowerCase(), hk = String((chip.home || {}).key || '').toLowerCase();
  if (ak && hk && String(c.homeKey).toLowerCase() === ak && String(c.awayKey).toLowerCase() === hk) out.flipped.push({ sport: chip.sport, card: c.matchup, chip: chip.matchup });
}
fs.writeFileSync(outPath, JSON.stringify(out));
console.log(`missing=${missing.join(',') || 'none'} items=${items.length} merged=${merged.length} cards=${cards.length} live=${out.cards.filter((c) => c.live).length}`);
