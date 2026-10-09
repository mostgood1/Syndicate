// Games-rail FINAL card plays line (lane games-rail-full-detail, 2026-10-09).
// Run: node tests/js/games_rail_plays.test.mjs
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.resolve(here, '../../syndicate/templates/intelligence.html'), 'utf8');
const start = html.indexOf('function chipPlaysText(');
let depth = 0; let end = -1;
for (let i = start; i < html.length; i += 1) {
  if (html[i] === '{') depth += 1;
  else if (html[i] === '}') { depth -= 1; if (depth === 0 && i > start + 30) { end = i + 1; break; } }
}
const chipPlaysText = new Function(`${html.slice(start, end)}; return chipPlaysText;`)();
let failures = 0;
const eq = (label, got, want) => {
  const ok = got === want; if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `  got=${JSON.stringify(got)} want=${JSON.stringify(want)}`}`);
};
eq('final with lines and pending props',
  chipPlaysText({ state: 'final', plays: { total: 5, lines: 3, props: 2, line_results: { win: 2, loss: 1, push: 0, pending: 0 }, prop_results: { win: 1, loss: 0, push: 0, pending: 1 } } }),
  '5 plays · lines 2–1 · props 1–0, 1 pending');
eq('props all pending', chipPlaysText({ state: 'final', plays: { total: 1, lines: 0, props: 1, prop_results: { win: 0, loss: 0, push: 0, pending: 1 } } }), '1 play · props 1 pending');
eq('postponed is void', chipPlaysText({ state: 'postponed', plays: { total: 2, void: true } }), '2 plays · void');
eq('pregame says nothing (the board count stands)', chipPlaysText({ state: 'pregame', plays: { total: 2 } }), '');
console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
