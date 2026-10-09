// Dated prop charts on the Layer 2 board (lane board-history-charts, 2026-10-09).
// Extracted from the template at run time, like the sibling harnesses.
// Run: node tests/js/board_history_charts.test.mjs
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = fs.readFileSync(path.resolve(here, '../../syndicate/templates/intelligence.html'), 'utf8');
function extract(name) {
  const start = html.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  let depth = 0; let seen = false;
  for (let i = start; i < html.length; i += 1) {
    if (html[i] === '{') { depth += 1; seen = true; } else if (html[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) return html.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced ${name}`);
}
const api = (new Function(`
  const numericValue = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const escapeHtml = (v) => String(v);
  ${extract('gameMarketKind')}
  ${extract('gameSide')}
  ${extract('teamForm')}
  ${extract('backedSide')}
  ${extract('recentForm')}
  ${extract('recentFormChart')}
  return { recentForm, recentFormChart };
`))();

let failures = 0;
const ok = (label, cond) => { if (!cond) failures += 1; console.log(`${cond ? 'ok  ' : 'FAIL'} ${label}`); };

const dated = {
  kind: 'prop', line: 1.5, side: 'over',
  recent_values: [3, 1, 2],
  recent_dates: ['2026-10-04', '2026-09-27', '2026-09-20'],
  recent_opponents: ['v Arsenal', '@ Spurs', 'v Wolves'],
};
const form = api.recentForm(dated);
ok('labels kept aligned with values', JSON.stringify(form.dates) === JSON.stringify(dated.recent_dates)
  && JSON.stringify(form.opps) === JSON.stringify(dated.recent_opponents));
const svg = api.recentFormChart(dated);
ok('newest bar tooltip names date + opponent + value', svg.includes('<title>2026-10-04 v Arsenal: 3</title>'));
ok('oldest bar tooltip too', svg.includes('<title>2026-09-20 v Wolves: 2</title>'));
ok('caption shows the date span oldest -> newest', svg.includes('2026-09-20 → 2026-10-04'));

const gap = { ...dated, recent_values: [3, 'x', 2] };
const g = api.recentForm(gap);
ok('a non-numeric value drops its own label, not the others', JSON.stringify(g.values) === '[3,2]'
  && JSON.stringify(g.dates) === JSON.stringify(['2026-10-04', '2026-09-20']));

const undated = { kind: 'prop', line: 1.5, side: 'over', recent_values: [3, 1, 2] };
const u = api.recentFormChart(undated);
ok('no dates: bare value tooltips as before', u.includes('<title>3</title>') && !u.includes('→'));

const short = { ...dated, recent_dates: ['2026-10-04'] };
const s = api.recentFormChart(short);
ok('misaligned dates are not used (aligned opponents still are)', s.includes('<title>v Arsenal: 3</title>') && !s.includes('2026-10-04'));

const week = { ...dated, recent_dates: ['2026 W5', '2026 W4', '2026 W3'], recent_opponents: ['BUF', 'MIA', 'NYJ'] };
ok('season+week labels render', api.recentFormChart(week).includes('<title>2026 W5 BUF: 3</title>'));

console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
