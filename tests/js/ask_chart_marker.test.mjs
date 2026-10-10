// Ask the Syndicate chart renderers draw today's line, signed bars and hit/miss
// (lane board-history-charts, 2026-10-10). Both renderers are extracted at run time.
// Run: node tests/js/ask_chart_marker.test.mjs
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const here = path.dirname(fileURLToPath(import.meta.url));
const read = (p) => fs.readFileSync(path.resolve(here, p), 'utf8');
function extract(src, name) {
  const start = src.indexOf(`function ${name}(`);
  if (start < 0) throw new Error(`${name} not found`);
  let depth = 0; let seen = false;
  for (let i = start; i < src.length; i += 1) {
    if (src[i] === '{') { depth += 1; seen = true; } else if (src[i] === '}') {
      depth -= 1;
      if (seen && depth === 0) return src.slice(start, i + 1);
    }
  }
  throw new Error(`unbalanced ${name}`);
}

const bar = read('../../syndicate/static/shared/ask_bar.js');
const page = read('../../syndicate/templates/syndicate.html');
const sidebar = (new Function(`
  const finiteNumber = (v) => (Number.isFinite(v) ? v : null);
  const escapeHtml = (v) => String(v);
  const safeText = (v, d) => (v === undefined || v === null || v === '' ? d : String(v));
  const sectionAttrs = () => '';
  ${extract(bar, 'formatChartValue')}
  ${extract(bar, 'renderEvidenceChart')}
  return renderEvidenceChart;
`))();
const standalone = (new Function(`
  const esc = (v) => String(v);
  const safeText = (v, d) => (v === undefined || v === null || v === '' ? d : String(v));
  ${extract(page, 'formatChartValue')}
  ${extract(page, 'renderVisualChart')}
  return renderVisualChart;
`))();

let failures = 0;
const ok = (label, cond) => { if (!cond) failures += 1; console.log(`${cond ? 'ok  ' : 'FAIL'} ${label}`); };
const count = (s, needle) => s.split(needle).length - 1;

const margin = {
  title: 'Home FC — margin by game', x_label: 'Game', y_label: 'Margin',
  points: [{ x: '09-21', y: 0, hit: false }, { x: '09-28', y: -2, hit: false }, { x: '10-05', y: 2, hit: true }],
  marker: { y: 1.5, label: "Today's line" },
};
const plain = { title: 'Plain', x_label: 'Game', y_label: 'Pts', points: [{ x: 'a', y: 10 }, { x: 'b', y: 20 }] };

for (const [name, render] of [['sidebar', (c) => render1(c)], ['standalone', (c) => standalone(c)]]) {
  const m = render(margin);
  ok(`${name}: marker drawn once per bar`, count(m, 'border-top:1px dashed') === 3);
  ok(`${name}: marker named in the axis`, m.includes("dashed = Today's line 1.5"));
  // lo=-2, hi=2, span=4: the -2 bar starts at 0% and is 50% tall; the zero line is at 50%.
  ok(`${name}: loss draws below zero`, m.includes('bottom:0%;height:50%'));
  ok(`${name}: win starts at zero`, m.includes('bottom:50%;height:50%'));
  ok(`${name}: marker at 1.5 -> 87.5%`, m.includes('bottom:87.5%'));
  ok(`${name}: misses dimmed, hits not`, count(m, 'opacity:0.35') === 2);
  ok(`${name}: hit named in the tooltip`, m.includes('10-05: 2 (hit)'));
  const p = render(plain);
  ok(`${name}: no marker -> no dashed line`, !p.includes('dashed'));
  ok(`${name}: no hit -> nothing dimmed`, !p.includes('opacity'));
  ok(`${name}: unsigned chart unchanged in scale (20 -> 100%)`, p.includes('bottom:0%;height:100%') && p.includes('height:50%'));
}
function render1(c) { return sidebar(c, 'k', false); }

if (failures) { console.log(`${failures} failure(s)`); process.exit(1); }
console.log('all ok');
