/* Shared renderers for the per-sport betting-recap (reconciliation) pages.
 *
 * EXTRACTED 2026-09-09 from `templates/{nba,nhl}/reconciliation.html`, where all
 * FIFTEEN of these were byte-identical copies -- verified by comparing full
 * function bodies, not first lines, and the extractor refuses to merge if any
 * pair differs. Every fix to them used to be a two-way edit and a one-way
 * chance to miss one; the `unpriced` column added earlier the same day was
 * exactly that shape.
 *
 * NOT SHARED WITH `recap_market_accuracy.js`, deliberately. That family has its
 * own `esc` and `fmtPct`, and they are NOT equivalent: this `fmtPct` renders
 * `null` as `Number(null)` -> "0.0%", while the market-accuracy one returns an
 * em dash. Merging them would be a behaviour change wearing a refactor's
 * clothes, so the two files stay separate and `localYMD` -- the one function
 * that IS identical across both -- is carried twice. Two copies, down from six.
 *
 * Loaded as a plain classic script, so these stay window globals and the inline
 * page script keeps calling them unchanged.
 */
function addTotals(total,bucket){if(!bucket) return;total.total += Number(bucket.total||0);total.resolved += Number(bucket.resolved||0);total.wins += Number(bucket.wins||0);total.losses += Number(bucket.losses||0);total.pushes += Number(bucket.pushes||0);total.stake_total += Number(bucket.stake_total||0);total.profit_total += Number(bucket.profit_total||0);}
function applyLast14(){const until=localYMD();document.getElementById('untilInput').value=until;document.getElementById('sinceInput').value=shiftDate(until,-13);document.getElementById('daysInput').value='14';load();}
function applySingleDate(){const until=localYMD();document.getElementById('sinceInput').value=until;document.getElementById('untilInput').value=until;document.getElementById('daysInput').value='1';load();}
function bucketOverall(group){return group&&group.buckets?(group.buckets.Overall||null):null;}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
function finalizeTotal(total){const resolved=Number(total.resolved||0);const stake=Number(total.stake_total||0);return {...total,accuracy_pct:resolved>0?((100*Number(total.wins||0))/resolved):null,roi_pct:stake>0?((100*Number(total.profit_total||0))/stake):null};}
function fmtPct(value){const n=Number(value);return Number.isFinite(n)?`${n.toFixed(1)}%`:'—';}
function fmtUnits(value){const n=Number(value);if(!Number.isFinite(n)) return '—';return `${n>0?'+':''}${n.toFixed(2)}u`;}
// `Unpriced` counts SETTLED rows that could not contribute a priced P/L, so
// ROI is a rate over fewer rows than `Settled`. Three states, kept apart on
// purpose: a NUMBER when the producer counts them, `0` when it counts and
// found none, and an em dash when the field is ABSENT -- that last one is
// "not counted here", which must not render as "none", or an uninstrumented
// producer would read as a clean one.
function fmtUnpriced(bucket){const raw=bucket?bucket.unpriced:null;if(raw==null) return '<td class="muted" title="this producer does not count unpriced rows">—</td>';const n=Number(raw)||0;if(n<=0) return '<td>0</td>';return `<td class="bad" title="settled rows with no price: ROI is computed over ${esc(String(Math.max(0,Number(bucket.resolved||0)-n)))} of ${esc(String(bucket.resolved||0))} settled rows">${esc(String(n))}</td>`;}
function localYMD(){const tz='America/New_York';const cutoffHour=6;try{const now=new Date();const hourStr=new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'2-digit',hour12:false}).format(now);const hour=Number(hourStr);const base=(Number.isFinite(hour)&&hour<cutoffHour)?new Date(now.getTime()-24*60*60*1000):now;return new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}).format(base);}catch(_){const d=new Date();const base=(d.getHours()<cutoffHour)?new Date(d.getTime()-24*60*60*1000):d;const y=base.getFullYear();const m=String(base.getMonth()+1).padStart(2,'0');const day=String(base.getDate()).padStart(2,'0');return `${y}-${m}-${day}`;}}
function renderBucketTable(group){const rows=['Overall','High','Medium','Low'].map((name)=>{const bucket=group&&group.buckets?group.buckets[name]:null;if(!bucket) return '';const profitClass=Number(bucket.profit_total||0)>=0?'good':'bad';return `<tr><td>${esc(name)}</td><td>${esc(String(bucket.total||0))}</td><td>${esc(String(bucket.resolved||0))}</td><td>${esc(wl(bucket))}</td><td>${esc(fmtPct(bucket.accuracy_pct))}</td>${fmtUnpriced(bucket)}<td class="${profitClass}">${esc(fmtPct(bucket.roi_pct))}</td><td class="${profitClass}">${esc(fmtUnits(bucket.profit_total))}</td></tr>`;}).join('');return `<div class="table-wrap"><table class="recap-table"><thead><tr><th>Tier</th><th>Total</th><th>Settled</th><th>W-L-P</th><th>Accuracy</th><th title="settled rows with no price; excluded from ROI">Unpriced</th><th>ROI</th><th>Net</th></tr></thead><tbody>${rows||'<tr><td colspan="8">No data.</td></tr>'}</tbody></table></div>`;}
function renderDays(payload){const root=document.getElementById('daysRoot');const items=Array.isArray(payload.items)?payload.items:[];if(!items.length){root.innerHTML='<div class="card">No scored recap rows were available for this window.</div>';return;}root.innerHTML=items.map((item)=>{const games=bucketOverall(item.games)||{};const props=bucketOverall(item.props)||{};return `<section class="day-card"><div class="day-head"><div><div class="day-title">${esc(item.date||'Unknown date')}</div><div class="day-meta">Games ${esc(wl(games))} • Props ${esc(wl(props))}</div></div><div><span class="pill ${Number(games.profit_total||0)>=0?'good':'bad'}">Games ${esc(fmtUnits(games.profit_total))}</span> <span class="pill ${Number(props.profit_total||0)>=0?'good':'bad'}">Props ${esc(fmtUnits(props.profit_total))}</span></div></div><div class="section-grid"><div class="card"><div class="meta-line">Game plays</div>${renderBucketTable(item.games)}</div><div class="card"><div class="meta-line">Prop plays</div>${renderBucketTable(item.props)}</div></div></section>`;}).join('');}
function renderSummary(payload){const totals={games:{total:0,resolved:0,wins:0,losses:0,pushes:0,stake_total:0,profit_total:0},props:{total:0,resolved:0,wins:0,losses:0,pushes:0,stake_total:0,profit_total:0}};(payload.items||[]).forEach((item)=>{addTotals(totals.games,bucketOverall(item.games));addTotals(totals.props,bucketOverall(item.props));});totals.games=finalizeTotal(totals.games);totals.props=finalizeTotal(totals.props);document.getElementById('summaryRoot').innerHTML=`<div class="card summary-kpi"><div class="label">Window</div><div class="value">${esc(`${payload.window?.since||'—'} to ${payload.window?.until||'—'}`)}</div><div class="meta-line">${esc(String((payload.items||[]).length))} scored dates</div></div><div class="card summary-kpi"><div class="label">Games</div><div class="value ${Number(totals.games.profit_total||0)>=0?'good':'bad'}">${esc(fmtUnits(totals.games.profit_total))}</div><div class="meta-line">${esc(wl(totals.games))} settled, ${esc(fmtPct(totals.games.roi_pct))} ROI</div></div><div class="card summary-kpi"><div class="label">Props</div><div class="value ${Number(totals.props.profit_total||0)>=0?'good':'bad'}">${esc(fmtUnits(totals.props.profit_total))}</div><div class="meta-line">${esc(wl(totals.props))} settled, ${esc(fmtPct(totals.props.roi_pct))} ROI</div></div>`;}
function shiftDate(ymd, deltaDays){const base=new Date(`${String(ymd)}T12:00:00`);if(Number.isNaN(base.getTime())) return localYMD();base.setDate(base.getDate()+Number(deltaDays||0));const offsetMs=base.getTimezoneOffset()*60000;return new Date(base.getTime()-offsetMs).toISOString().slice(0,10);}
function wl(bucket){return `${Number(bucket?.wins||0)}-${Number(bucket?.losses||0)}-${Number(bucket?.pushes||0)}`;}
