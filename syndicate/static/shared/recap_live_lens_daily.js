/* Shared renderers for the per-sport live-lens daily-accuracy pages.
 *
 * EXTRACTED 2026-09-09 from `templates/{mlb,nba,nhl,wnba}/live_lens_daily_accuracy.html`,
 * where these six were byte-identical across all four -- verified on full
 * function text, with the extractor refusing to merge on any mismatch.
 *
 * PAIR THIS WITH `recap_common.js`, which carries the four helpers this family
 * shares with the market-accuracy pages. Both are needed; neither is enough.
 *
 * DELIBERATELY LEFT INLINE: `localYMD` and `renderDailyRecaps`, because MLB's
 * differ from the other three (MLB's `localYMD` is 183 chars against 684, a
 * genuinely simpler implementation without the ET 06:00 cutoff). Hoisting the
 * three-way agreement and letting MLB shadow it would work and would be the
 * kind of cleverness nobody can read later. The remaining three-way duplication
 * is recorded in `leads.md` with its measurement.
 *
 * NOTE: this file's `renderSummaryCards` is NOT the one in
 * `recap_market_accuracy.js` -- same name, different function, and they are
 * only ever loaded on different pages. A page that loaded both would silently
 * take whichever came last.
 */
function fmtPct01(x){try{if(x==null) return '—';const v=Number(x);return Number.isFinite(v)?(v.toFixed(1)+'%'):'—';}catch(_){return '—';}}
function hitLine(s){if(!s) return '—';const n=Number(s.n||0);const w=Number(s.wins||0),l=Number(s.losses||0),p=Number(s.pushes||0);const hr=(s.hit_rate_pct!=null)?fmtPct01(Number(s.hit_rate_pct)):(s.hit_rate!=null?fmtPct01(Number(s.hit_rate)*100):'—');return `${w}-${l}${p?('-'+p+'P'):''} · hit ${hr} · n=${n}`;}
function hrPctFromRow(r){try{if(!r) return '—';if(r.hit_rate_pct!=null && Number.isFinite(Number(r.hit_rate_pct))) return fmtPct01(Number(r.hit_rate_pct));if(r.hit_rate!=null && Number.isFinite(Number(r.hit_rate))) return fmtPct01(Number(r.hit_rate)*100);return '—';}catch(_){return '—';}}
function renderBreakdownTable(items,title,keyField,keyTitle){const arr=Array.isArray(items)?items:[];if(!arr.length) return '';const rows=arr.map((r)=>{const key=r&&r[keyField]!=null?String(r[keyField]):(r&&r.key!=null?String(r.key):'');const n=Number(r.n||0);const w=Number(r.wins||0),l=Number(r.losses||0),p=Number(r.pushes||0);const hr=(r.hit_rate_pct!=null)?fmtPct01(Number(r.hit_rate_pct)):(r.hit_rate!=null?fmtPct01(Number(r.hit_rate)*100):'—');return `<tr><td>${esc(key||'(blank)')}</td><td>${n}</td><td>${w}-${l}${p?('-'+p):''}</td><td>${hr}</td></tr>`;}).join('');return `<div class="mt-4"><div class="title-sm">${esc(title)}</div><div class="table-wrap"><table><thead><tr><th>${esc(keyTitle)}</th><th>N</th><th>W-L-P</th><th>Hit%</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;}
function renderSummaryCards(js){const root=document.getElementById('summaryRoot');if(!root) return;root.innerHTML='';const win=js&&js.window?js.window:null;const since=win&&win.since?String(win.since):'';const until=win&&win.until?String(win.until):'';const sum=js&&js.summary?js.summary:null;const all=sum&&sum.summary?sum.summary:null;const head=document.createElement('div');head.className='card card-summary';head.innerHTML=`<div class="title-sm">Last 30 days</div><div class="title-lg">Live Lens Accuracy</div><div class="muted-small">${esc(since)} → ${esc(until)}</div>`;root.appendChild(head);const c=document.createElement('div');c.className='card card-summary';c.innerHTML=`<div class="title-sm">Overall</div><div class="mt-4 title-md">${esc(hitLine(all))}</div>`;root.appendChild(c);const m=document.createElement('div');m.className='card card-summary';const byM=sum&&Array.isArray(sum.by_market)?sum.by_market:[];const topM=byM.slice(0,6).map((r)=>`${String(r.key||'')}: ${hrPctFromRow(r)}`).join(' · ');m.innerHTML=`<div class="title-sm">Top markets</div><div class="mt-4 muted-small">${esc(topM || '—')}</div>`;root.appendChild(m);try{const banner=document.getElementById('windowBanner');if(banner) banner.textContent=`Last 30 days (${since} → ${until})`;}catch(_){}}
function updateUrlDate(d){try{const u=new URL(window.location.href);u.searchParams.set('date',d);window.history.replaceState({},'',u.toString());}catch(_){}}
