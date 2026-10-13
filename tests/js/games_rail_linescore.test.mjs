// Games-rail line score (lane games-rail-full-detail, user 2026-10-13).
// Run: node tests/js/games_rail_linescore.test.mjs
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.resolve(here, '../../syndicate/templates/intelligence.html'), 'utf8');
const start = html.indexOf('function chipLineScore(');
let depth = 0; let end = -1;
for (let i = start; i < html.length; i += 1) {
  if (html[i] === '{') depth += 1;
  else if (html[i] === '}') { depth -= 1; if (depth === 0 && i > start + 30) { end = i + 1; break; } }
}
const escapeHtml = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const chipLineScore = new Function('escapeHtml', `${html.slice(start, end)}; return chipLineScore;`)(escapeHtml);
let failures = 0;
const check = (label, ok) => { if (!ok) failures += 1; console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}`); };
const text = (h) => h.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();

const nfl = chipLineScore({ leader: 'away', away: { abbr: 'TB', score: '24' }, home: { abbr: 'DAL', score: '16' },
  linescore: { kind: 'periods', labels: ['1', '2', '3', '4'], away: [0, 7, 17, 0], home: [7, 3, 0, 6] } });
check('periods + T header, rows in order', text(nfl) === '1 2 3 4 T TB 0 7 17 0 24 DAL 7 3 0 6 16');
check('5 grid columns after the team', nfl.includes('--box-cols:5'));
check('leader total is bold', /game-mini-card__box-total is-leader">24/.test(nfl));

const mlb = chipLineScore({ leader: 'home', away: { abbr: 'LAD', score: '4' }, home: { abbr: 'MIL', score: '7' },
  linescore: { kind: 'rhe', labels: ['R', 'H', 'E'], away: [4, 3, 2], home: [7, 12, 2] } });
check('R/H/E, no separate total', text(mlb) === 'R H E LAD 4 3 2 MIL 7 12 2');
check('3 grid columns', mlb.includes('--box-cols:3'));

check('no line score -> empty', chipLineScore({ away: {}, home: {} }) === '');
console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
