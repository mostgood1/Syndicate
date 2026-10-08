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
  ${extract('gameMarketKind')}
  ${extract('gameSide')}
  ${extract('teamForm')}
  ${extract('backedSide')}
  ${extract('recentForm')}
  ${extract('recentFormText')}
  return { simLadderBuckets, recentForm, recentFormText, teamForm };
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

// Game lines: a moneyline has no line (0 on the chart), sides are home/away.
const marg = [[-2.5, 0.8], [-1.5, 0.7], [-0.5, 0.6], [0, 0.55], [0.5, 0.5], [1.5, 0.4], [2.5, 0.3]];
const ml0 = api.simLadderBuckets({ sim_ladder: marg, sim_ladder_kind: 'margin', line: null, side: 'away', confidence: 0.45 });
eq('moneyline away row draws at line 0', ml0 && ml0.line, 0);
eq('away side is the complement', ml0 && Math.round(ml0.pSide * 100), 45);
const raw = api.simLadderBuckets({ sim_ladder: marg, sim_ladder_kind: 'margin', line: 0, side: 'home', confidence: 0.70, sim_ladder_raw_over: 0.55 });
eq('NBA blended row checks against the RAW sim and says so', raw && raw.raw, true);

// Team last-10 on game rows: [date, for, against], newest first.
const tr = { home: [['d', 34, 30], ['d', 31, 34], ['d', 37, 20], ['d', 10, 13]], away: [['d', 20, 24], ['d', 27, 3]] };
const spread = { market: 'spreads', side: 'Dallas Cowboys', home_team: 'Dallas Cowboys', away_team: 'Tampa Bay Buccaneers', line: -3, team_recent: tr };
eq('spread: home covers -3 when margin > 3', api.teamForm(spread, 'home').record, '2/4');
eq('spread: the other team gets +3', api.teamForm(spread, 'away').label, 'covered +3');
eq('spread: away covers +3 when margin > -3', api.teamForm(spread, 'away').record, '1/2');
eq('spread text names the backed team', api.recentFormText(spread), 'Dallas Cowboys L4 covered -3 2/4');
const tot = Object.assign({}, spread, { market: 'totals', side: 'over', line: 50.5 });
eq("totals: game total over today's line", api.teamForm(tot, 'home').record, '3/4');
const mlr = Object.assign({}, spread, { market: 'h2h', side: 'away', line: null });
eq('moneyline: W-L of the backed team', api.recentFormText(mlr), 'Tampa Bay Buccaneers L2 1–1');
eq('no team_recent: game row has no form', api.recentForm({ market: 'totals', kind: 'game', side: 'over', line: 6 }), null);

// Spreads: the card carries the side's OWN line; the ladder is in the away frame.
const sp = [[-0.5, 0.62], [0.5, 0.48], [1.5, 0.30], [2.5, 0.16], [3.5, 0.08]];
const homeSp = api.simLadderBuckets({ sim_ladder: sp, sim_ladder_kind: 'margin', line: -1.5, side: 'home', confidence: 0.30 });
eq('home -1.5 reads P(margin > +1.5)', homeSp && Math.round(homeSp.pSide * 100), 30);
const awaySp = api.simLadderBuckets({ sim_ladder: sp, sim_ladder_kind: 'margin', line: 1.5, side: 'away', confidence: 0.70 });
eq('away +1.5 reads 1 - P(margin > +1.5)', awaySp && Math.round(awaySp.pSide * 100), 70);
const named = api.simLadderBuckets({ sim_ladder: sp, sim_ladder_kind: 'margin', line: -0.5, side: 'Real Madrid', home_team: 'Real Madrid', away_team: 'Villarreal', confidence: 0.48 });
eq('soccer team-name side resolves to home', named && named.sideWord, 'home covers');

console.log(failures ? `\n${failures} FAILED` : '\nALL PASS');
process.exit(failures ? 1 : 0);
