// The games rail's sport selector and the foldable filter grid (todo #806, lane rail-sport-and-filter-fold).
//
// User 2026-11-14, relayed by session 8062940b: "The rail needs a sport selector. The top section needs an
// accordian option so we can shrink it so the rail can be the main thing seen if the user chooses."
//
// Pins the page's OWN code (extracted from intelligence.html and board_cards.css, not restated):
//   - the rail sport options: the rail's sports in the panel's order, counted, "All" first; a picked sport
//     with no game stays clearable; the filter narrows the rail only (rail-only state, in the URL, out of
//     FILTER_DEFAULTS); each rail filter's counts are taken under the other one;
//   - the fold: one toolbar toggle, remembered per viewer (storage failures never break it), CSS that hides
//     the grid only wider than a phone and hides the toggle on a phone (the bottom sheet already folds it).
//
// Run it directly:   node tests/js/board_rail_sport_and_fold.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, '..', '..');
const html = fs.readFileSync(path.join(root, 'syndicate', 'templates', 'intelligence.html'), 'utf8').split('\r\n').join('\n');
const css = fs.readFileSync(path.join(root, 'syndicate', 'static', 'shared', 'board_cards.css'), 'utf8').split('\r\n').join('\n');

let failures = 0;
function check(label, actual, expected) {
  const ok = actual === expected;
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok ? '' : `  (got ${JSON.stringify(actual)}, want ${JSON.stringify(expected)})`}`);
}

// ---------------------------------------------------------------- the rail sport helpers
const block = html.match(/ {2}\/\/ ===== LIVE RAIL LINES -- BEGIN[\s\S]*?\/\/ ===== LIVE RAIL LINES -- END =====/);
const formatAgeSrc = html.match(/ {2}function formatAge\(seconds\)[\s\S]*?\n {2}}\n/);
const buildSrc = html.match(/ {2}function boardBuildEpochMs\(response\)[\s\S]*?\n {2}}\n/);
check('the rail block exists', Boolean(block && formatAgeSrc && buildSrc), true);
if (!block || !formatAgeSrc || !buildSrc) { console.log(`\n${failures} assertion(s) failed`); process.exit(1); }
const api = new Function('escapeHtml', 'trimClubAffixes', `
  const LIVE_PRICE_STALE_AFTER_SECONDS = 300;
  ${formatAgeSrc[0]}
  ${buildSrc[0]}
  ${block[0]}
  return { railSportOptions, railSportMatches, railSportOf, railSportLabel, RAIL_SPORT_ORDER };
`)((v) => String(v), (v) => String(v || ''));

const games = [
  { key: 'a', sportSlug: 'ncaaf', sport: 'NCAAF' }, { key: 'b', sportSlug: 'ncaaf', sport: 'NCAAF' },
  { key: 'c', sportSlug: 'nba', sport: 'NBA' }, { key: 'd', sportSlug: 'nhl', sport: 'NHL' },
  { key: 'e', sportSlug: 'soccer', sport: 'SOCCER' },
];
const options = api.railSportOptions(games, 'all');
check('options: All first, then the rail\'s sports in the panel\'s order, each counted',
  options.map((o) => `${o.label}:${o.count}`).join(' '), 'All:5 NBA:1 NCAAF:2 NHL:1 Soccer:1');
check('option values are the sport slugs', options.map((o) => o.value).join(','), 'all,nba,ncaaf,nhl,soccer');
check('a picked sport with no game on the rail stays listed (count 0), so it can be cleared',
  api.railSportOptions(games, 'wncaab').map((o) => `${o.value}:${o.count}`).pop(), 'wncaab:0');
check('a chip-less group (only an upper-case label) still has its sport', api.railSportOf({ sport: 'NCAAB' }), 'ncaab');
check('All matches every game', games.every((g) => api.railSportMatches(g, 'all')), true);
check('a sport matches only its own games', games.filter((g) => api.railSportMatches(g, 'ncaaf')).map((g) => g.key).join(''), 'ab');
check('the panel\'s sport order', api.RAIL_SPORT_ORDER.join(','), 'mlb,nba,wnba,nfl,ncaaf,ncaab,wncaab,nhl,soccer');

// ---------------------------------------------------------------- wiring in renderGameCards
const render = html.match(/ {2}function renderGameCards\(items\)[\s\S]*?\n {2}}\n/);
const r = render ? render[0] : '';
check('renderGameCards exists', Boolean(render), true);
check('the rail is narrowed by the rail sport AND the live-edge filter, the picked game always kept',
  /games\.filter\(\(game\) => game\.key === state\.game \|\| \(railSportMatches\(game, railSport\) && edgeMatch\(game\)\)\)/.test(r), true);
check('the live-edge counts are taken under the rail sport', /const sportGames = games\.filter\(\(game\) => railSportMatches\(game, railSport\)\);/.test(r)
  && /tab\.value === "all" \? sportGames\.length/.test(r), true);
check('the sport counts are taken under the live-edge filter', /railSportOptions\(games\.filter\(edgeMatch\), railSport\)/.test(r), true);
check('the sport row shows when the rail spans 2+ sports, or while one is picked', /railSports\.size >= 2 \|\| railSport !== "all"/.test(r), true);
check('the sport row sits above the live-edge row', /\$\{sportFilter\}\$\{edgeFilter\}\$\{emptyNote\}/.test(r), true);
check('a sport chip re-renders the RAIL only (not renderBoardBody)',
  /\[data-rail-sport\][\s\S]*?state\.railSport = [\s\S]*?syncUrlState\(\);\s*renderGameCards\(items\);/.test(r), true);
check('an empty sport says so by name', /No \$\{escapeHtml\(railSportLabel\(railSport\)\)\} game on the rail right now\./.test(r), true);

// ---------------------------------------------------------------- state + URL
check('state.railSport reads rail_sport from the URL, default all', /railSport: String\(urlParams\.get\("rail_sport"\) \|\| "all"\)\.trim\(\)\.toLowerCase\(\) \|\| "all",/.test(html), true);
check('it is written back to the URL only when set', /if \(state\.railSport !== "all"\) url\.searchParams\.set\("rail_sport", state\.railSport\); else url\.searchParams\.delete\("rail_sport"\);/.test(html), true);
check('it is NOT a board-row default (rail-only view)', /FILTER_DEFAULTS = \{[^}]*railSport/.test(html), false);

// ---------------------------------------------------------------- the fold: markup, CSS
check('the toggle is in the toolbar\'s first row and controls the grid',
  /<div class="board-toolbar-row">[\s\S]*?<button type="button" class="cards-nav-pill board-filter-fold" id="board-filter-fold" aria-controls="board-filter-grid" aria-expanded="true">Hide filters<\/button>[\s\S]*?<\/div>\s*<!-- EVERY FILTER IS VISIBLE/.test(html), true);
check('setupFilterFold runs at start, after the phone sheet', /setupFilterSheet\(\);\s*setupFilterFold\(\);/.test(html), true);
check('CSS: the folded grid is hidden only wider than a phone', /@media \(min-width: 768px\) \{\s*\.board-toolbar--folded \.board-filter-grid \{ display: none; \}\s*\}/.test(css), true);
check('CSS: the toggle is hidden on a phone (the bottom sheet already folds it)', /@media \(max-width: 767px\) \{\s*\.board-filter-fold \{ display: none; \}\s*\}/.test(css), true);

// ---------------------------------------------------------------- the fold: behaviour, on a fake DOM
const foldSrc = html.match(/ {2}const FILTER_FOLD_STORAGE_KEY = [^\n]*\n\n {2}function setupFilterFold\(\)[\s\S]*?\n {2}}\n/);
check('setupFilterFold exists', Boolean(foldSrc), true);
function fakeDom(stored, { throwing = false } = {}) {
  const classes = new Set(['cards-control-card', 'board-toolbar']);
  const listeners = [];
  const store = { value: stored };
  const form = { classList: { toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); }, contains: (c) => classes.has(c) } };
  const attrs = {};
  const button = { textContent: 'Hide filters', setAttribute: (k, v) => { attrs[k] = v; }, addEventListener: (name, fn) => listeners.push(fn) };
  const document = { getElementById: (id) => (id === 'board-toolbar' ? form : id === 'board-filter-fold' ? button : null) };
  const localStorage = {
    getItem: (k) => { if (throwing) throw new Error('blocked'); return k === 'syndicate.board.filtersFolded' ? store.value : null; },
    setItem: (k, v) => { if (throwing) throw new Error('blocked'); if (k === 'syndicate.board.filtersFolded') store.value = v; },
  };
  return { document, window: { localStorage }, form, button, attrs, classes, store, click: () => listeners.forEach((fn) => fn()) };
}
function run(dom) {
  new Function('document', 'window', `${foldSrc[0]}\nsetupFilterFold();`)(dom.document, dom.window);
  return dom;
}
const fresh = run(fakeDom(null));
check('no stored choice: unfolded', `${fresh.classes.has('board-toolbar--folded')}|${fresh.attrs['aria-expanded']}|${fresh.button.textContent}`, 'false|true|Hide filters');
fresh.click();
check('a click folds it, says Show filters, and remembers', `${fresh.classes.has('board-toolbar--folded')}|${fresh.attrs['aria-expanded']}|${fresh.button.textContent}|${fresh.store.value}`, 'true|false|Show filters|1');
fresh.click();
check('a second click unfolds it and remembers', `${fresh.classes.has('board-toolbar--folded')}|${fresh.store.value}`, 'false|0');
const remembered = run(fakeDom('1'));
check('a stored fold is applied at start', `${remembered.classes.has('board-toolbar--folded')}|${remembered.button.textContent}`, 'true|Show filters');
const blocked = run(fakeDom('1', { throwing: true }));
check('blocked storage: starts unfolded', blocked.classes.has('board-toolbar--folded'), false);
blocked.click();
check('blocked storage: the toggle still works for this page view', blocked.classes.has('board-toolbar--folded'), true);

console.log(`\n${failures ? `${failures} assertion(s) failed` : 'all passed'}`);
process.exit(failures ? 1 : 0);
