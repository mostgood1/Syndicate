// Prop charts (sim spread + L5/L10), lane layer2-board-ui-redesign 2026-10-08.
// Extracted from the template at run time, like the sibling harnesses.
// Run: node tests/js/board_prop_charts.test.mjs
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
  const CHART_AGREE_TOLERANCE = 0.02;
  const numericValue = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  const escapeHtml = (v) => String(v);
  ${extract('confidenceValue')}
  ${extract('simLadderBuckets')}
  ${extract('recentForm')}
  ${extract('recentFormText')}
  return { simLadderBuckets, recentForm, recentFormText };
`))();

let failures = 0;
const eq = (label, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want);
  if (!ok) failures += 1;
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}${ok ? '' : `  got=${JSON.stringify(got)} want=${JSON.stringify(want)}`}`);
};

// Poisson(0.745) ladder, Van Buren u0.5 passing TDs at 52.3% under.
const pge = (lam, k) => { let t = Math.exp(-lam), c = t; for (let i = 1; i < k; i += 1) { t *= lam / i; c += t; } return 1 - c; };
const ladder = [-0.5, 0.5, 1.5, 2.5, 3.5].map((t) => [t, t < 0 ? 1 : Number(pge(0.745, Math.floor(t) + 1).toFixed(4))]);
const row = { sim_ladder: ladder, line: 0.5, side: 'under', confidence: 1 - pge(0.745, 1) };
const b = api.simLadderBuckets(row);
eq('ladder that matches the row draws', b !== null, true);
eq('the under bucket (0) is on the side shown', b.buckets.filter((x) => x.over === false).map((x) => x.label), ['0']);
eq('buckets sum to 1', Math.round(b.buckets.reduce((s, x) => s + x.p, 0) * 1000) / 1000, 1);
eq('a ladder that DISAGREES with the row is not drawn', api.simLadderBuckets({ ...row, confidence: 0.76 }), null);
eq('no ladder, no chart', api.simLadderBuckets({ line: 0.5, side: 'under', confidence: 0.5 }), null);

const form = { recent_values: [0, 1, 0, 2, 0, 1, 0, 0, 2, 1], line: 0.5, side: 'under' };
eq('L5/L10 count the side shown, newest first', api.recentFormText(form), 'L5 3/5 · L10 5/10');
eq('over side counts the other way', api.recentFormText({ ...form, side: 'over' }), 'L5 2/5 · L10 5/10');
eq('fewer than 5 games still reads honestly', api.recentFormText({ recent_values: [3, 1], line: 1.5, side: 'over' }), 'L5 1/2 · L10 1/2');
eq('no values, no text', api.recentFormText({ line: 0.5, side: 'under' }), '');

console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
