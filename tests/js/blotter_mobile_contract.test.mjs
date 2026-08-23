// The mobile blotter is a CSS/markup CONTRACT. Pin both halves.
//
// WHY THIS EXISTS. `table.board-blotter` carries `min-width: 880px` inside an
// `overflow-x: auto` wrapper and had NO mobile rule at all. On a 390px viewport
// that is a table 2.25x the screen: every row has to be panned sideways, and
// odds/model/edge start off the right edge. The horizontal scroll made it
// reachable, which is why it never looked broken -- it was never usable.
//
// The fix turns each row into a labelled card below 720px, and that only works
// if the markup and the stylesheet agree on three things:
//
//   1. every cell carries `board-blotter__cell--<key>`, because the CSS treats
//      `state`, `entity` and `slip` differently from the label/value columns;
//   2. every cell carries `data-label`, which is what `td::before` renders --
//      injected via `nth-child` instead, every label silently shifts the moment
//      a column moves;
//   3. an empty cell is CLASS-MARKED, because a card of nine "Closing —" lines
//      is worse than no card, and CSS cannot detect an em-dash.
//
// Nothing in the browser fails loudly if these drift: the card simply renders
// unlabelled, or nine dashes tall. So the contract is asserted here.
//
// Run it directly:   node tests/js/blotter_mobile_contract.test.mjs

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const js = fs.readFileSync(path.join(here, '..', '..', 'syndicate', 'static', 'shared', 'market_board.js'), 'utf8');
const css = fs.readFileSync(path.join(here, '..', '..', 'syndicate', 'static', 'shared', 'board_cards.css'), 'utf8');

let failures = 0;
function check(label, ok, detail = '') {
  if (!ok) failures += 1;
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${ok || !detail ? '' : `  (${detail})`}`);
}

// The column keys the JS declares.
// `key:` sits on its own line in the multi-line column definitions, so anchoring
// on `{ key:` found 9 of 12 and reported three real columns missing. The keys are
// what the CSS selects on; a matcher that quietly sees two-thirds of them is the
// same class of half-blind instrument this repo keeps writing down.
const keys = [...js.matchAll(/key:\s*"([a-z_]+)"/g)].map((m) => m[1]);
check('BLOTTER_COLUMNS is declared and non-trivial', keys.length >= 10, `found ${keys.length}`);

// 1. ONE definition feeds the header and the cells. Two hand-maintained
// parallel lists is how a heading ends up over the wrong column.
check('the header is generated, not hand-written', /renderBlotterHeader\(\)/.test(js));
check('no hand-written <th> list survives', !/<th>State<\/th><th>Player/.test(js));

// 2. The three cells the CSS special-cases must exist as keys, or those rules
// are dead and the card silently loses its layout.
for (const key of ['state', 'entity', 'slip']) {
  check(`column "${key}" exists (the CSS targets it by name)`, keys.includes(key));
  check(`the CSS targets --${key}`, css.includes(`board-blotter__cell--${key}`));
}

// 3. Every cell emits its key class, its label and the empty marker.
check('cells emit board-blotter__cell--<key>', /board-blotter__cell board-blotter__cell--\$\{col\.key\}/.test(js));
check('cells emit data-label', /data-label="\$\{escapeHtml\(col\.label\)\}"/.test(js));
check('empty cells are class-marked', /board-blotter__cell--empty/.test(js));
check('the CSS hides empty cells on mobile', /board-blotter__cell--empty\s*\{\s*display:\s*none/.test(css));
check('the label is rendered from data-label', /content:\s*attr\(data-label\)/.test(css));

// 4. The regression itself: the 880px floor must be lifted below 720px, or
// none of the above matters -- the table still pans.
const mobile = css.slice(css.indexOf('THE BLOTTER ON A PHONE'));
check('a mobile block for the blotter exists', mobile.length > 0 && mobile.includes('@media (max-width: 720px)'));
check('min-width is reset below the breakpoint', /table\.board-blotter\s*\{[^}]*min-width:\s*0/.test(mobile));
check('the desktop 880px floor is still there', /min-width:\s*880px/.test(css));

// 5. Headers hidden ACCESSIBLY, not removed -- it stays a real table.
check('thead is clipped, not display:none', /thead\s*\{[^}]*clip-path:\s*inset\(50%\)/.test(mobile));
check('thead is not display:none', !/thead\s*\{[^}]*display:\s*none/.test(mobile));

// 6. The entity cell must survive the empty-hiding rule -- it is the only thing
// that says WHICH bet the card is.
check('the entity cell is exempt from empty-hiding',
  /cell--entity\.board-blotter__cell--empty\s*\{\s*display:\s*block/.test(mobile));

console.log(failures === 0 ? '\nall assertions passed' : `\n${failures} assertion(s) failed`);
process.exit(failures === 0 ? 0 : 1);
