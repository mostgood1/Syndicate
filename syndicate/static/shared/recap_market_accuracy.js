/* Shared renderers for the per-sport market-accuracy pages.
 *
 * EXTRACTED 2026-09-09 from `templates/{mlb,nba,nhl,wnba}/market_accuracy.html`,
 * where these ELEVEN were byte-identical across all four -- verified on full
 * function bodies, and the extractor refuses to merge if any pair differs.
 *
 * DELIBERATELY LEFT INLINE: `renderDailyRecaps` and `updateUrlDate`, which
 * genuinely DIFFER between sports (MLB's recap renders row tables, warnings and
 * preset filters the others do not have), plus MLB's own `renderRowsTable`,
 * `renderWarnings`, `setPreset`, `applyRowFilters`, `slugify`, `fmtNum` and the
 * window-preset helpers. Hoisting those would have meant reconciling real
 * differences, which is a redesign, not a de-duplication.
 *
 * See `recap_reconciliation.js` for why that family's `esc`/`fmtPct` are not
 * shared with these.
 *
 * PAIR THIS WITH `recap_common.js`: `esc`, `addDaysUTC`, `isoTodayUTC` and
 * `pickYmdFromQuery` moved there on 2026-09-09 when the live-lens pages turned
 * out to hold byte-identical copies of the same four. Both files are needed.
 */
// `unpriced` counts SETTLED rows that could not contribute a priced P/L, so
// ROI is a rate over fewer rows than `settled`. THE SUMMARY LINE FLAGS IT
// ONLY WHEN NON-ZERO -- deliberately, to keep the line short. The three-way
// distinction (a count / zero / NOT COUNTED BY THIS PRODUCER) is carried by
// the table below, in `unpricedCell`, and that is where to read it: a
// producer that does not instrument this renders an em dash there, never a
// reassuring `0`.
function bucketLine(b){if(!b) return '—';const w=Number(b.wins||0),l=Number(b.losses||0),p=Number(b.pushes||0);const res=Number(b.resolved||0);const acc=(b.accuracy_pct!=null)?fmtPct(Number(b.accuracy_pct)):'—';const roi=(b.roi_pct!=null)?fmtPct(Number(b.roi_pct)):'—';const pl=(b.profit_total!=null)?fmtMoneyUnits(b.profit_total):'—';const unp=Number(b.unpriced||0);const unpTxt=(b.unpriced!=null&&unp>0)?` · ${unp} unpriced`:'';return `${w}-${l}${p?('-'+p+'P'):''} (${acc}) · ROI ${roi} · P/L ${pl} · ${res} settled${unpTxt}`;}
function fmtMoneyUnits(u){try{if(u==null) return '—';const v=Number(u)*100;if(!Number.isFinite(v)) return '—';const sign=v>=0?'':'-';return sign+'$'+Math.abs(v).toFixed(0);}catch(_){return '—';}}
function fmtPct(x){try{if(x==null) return '—';const v=Number(x);return Number.isFinite(v)?(v.toFixed(1)+'%'):'—';}catch(_){return '—';}}
function localYMD(){const tz='America/New_York';const cutoffHour=6;try{const now=new Date();const hourStr=new Intl.DateTimeFormat('en-US',{timeZone:tz,hour:'2-digit',hour12:false}).format(now);const hour=Number(hourStr);const base=(Number.isFinite(hour)&&hour<cutoffHour)?new Date(now.getTime()-24*60*60*1000):now;return new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit'}).format(base);}catch(_){const d=new Date();const base=(d.getHours()<cutoffHour)?new Date(d.getTime()-24*60*60*1000):d;const y=base.getFullYear();const m=String(base.getMonth()+1).padStart(2,'0');const day=String(base.getDate()).padStart(2,'0');return `${y}-${m}-${day}`;}}
function renderByMarketTable(byMarket,title){const keys=byMarket&&typeof byMarket==='object'?Object.keys(byMarket):[];if(!keys.length) return '';const rows=keys.sort((a,b)=>String(a).localeCompare(String(b))).map((k)=>{const b=byMarket[k]||{};const n=Number(b.bets||b.total||0);const res=Number(b.resolved||0);const w=Number(b.wins||0),l=Number(b.losses||0),p=Number(b.pushes||0);const acc=(b.accuracy_pct!=null)?fmtPct(Number(b.accuracy_pct)):'—';const roi=(b.roi_pct!=null)?fmtPct(Number(b.roi_pct)):'—';const pl=(b.profit_total!=null)?fmtMoneyUnits(b.profit_total):'—';return `<tr><td>${esc(k)}</td><td>${n}</td><td>${res}</td><td>${w}-${l}${p?('-'+p):''}</td><td>${acc}</td>${unpricedCell(b)}<td>${roi}</td><td>${pl}</td></tr>`;}).join('');return `<div class="mt-4"><div class="title-sm">${esc(title)}</div><div class="table-wrap"><table><thead><tr><th>Market</th><th>Picks</th><th>Settled</th><th>W-L-P</th><th>Acc</th><th title="settled rows with no price; excluded from ROI">Unpriced</th><th>ROI</th><th>P/L</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;}
function renderSummaryCards(js){const root=document.getElementById('summaryRoot');if(!root) return;root.innerHTML='';const win=js&&js.window?js.window:null;const since=win&&win.since?String(win.since):'';const until=win&&win.until?String(win.until):'';const title=`${since} → ${until}`;const combined=js&&js.summary&&js.summary.combined&&js.summary.combined.overall?js.summary.combined.overall:null;const games=js&&js.summary&&js.summary.games&&js.summary.games.overall?js.summary.games.overall:null;const props=js&&js.summary&&js.summary.props&&js.summary.props.overall?js.summary.props.overall:null;const head=document.createElement('div');head.className='card card-summary';head.innerHTML=`<div class="title-sm">Last 30 days</div><div class="title-lg">Market Accuracy</div><div class="muted-small">${esc(title)}</div>`;root.appendChild(head);function addCard(label,b){const c=document.createElement('div');c.className='card card-summary';c.innerHTML=`<div class="title-sm">${esc(label)}</div><div class="mt-4 title-md">${esc(bucketLine(b))}</div>`;root.appendChild(c);} addCard('Combined',combined); addCard('Games',games); addCard('Props',props); try{const banner=document.getElementById('windowBanner');if(banner) banner.textContent=`Last 30 days (${since} → ${until})`;}catch(_){}}
function unpricedCell(b){const raw=b?b.unpriced:null;if(raw==null) return '<td title="this producer does not count unpriced rows">—</td>';const n=Number(raw)||0;if(n<=0) return '<td>0</td>';const priced=Math.max(0,Number(b.resolved||0)-n);return `<td class="bad" title="settled rows with no price: ROI is computed over ${priced} of ${Number(b.resolved||0)} settled rows">${n}</td>`;}
