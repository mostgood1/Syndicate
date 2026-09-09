/* Helpers shared by the market-accuracy AND live-lens-daily-accuracy pages.
 *
 * EXTRACTED 2026-09-09. These four were byte-identical in all EIGHT of those
 * templates -- verified against each other and against the already-shipped
 * `recap_market_accuracy.js`, and the extractor refuses to hoist anything that
 * is not an exact match.
 *
 * NOT loaded by the reconciliation pages: `recap_reconciliation.js` carries its
 * OWN `esc`, which is a different implementation (that family's `fmtPct` also
 * renders `null` as "0.0%" where this family's returns an em dash). Two
 * families, two behaviours, and unifying them would be a behaviour change
 * rather than a de-duplication.
 *
 * Load order does not matter: everything here is a function DECLARATION and
 * nothing runs at load time, so the page's inline script resolves these
 * whenever it calls them.
 */
function addDaysUTC(iso, days){try{const d=new Date(String(iso).slice(0,10)+'T00:00:00Z');if(Number.isFinite(Number(days))) d.setUTCDate(d.getUTCDate()+Number(days));return d.toISOString().slice(0,10);}catch(_){return iso;}}
function esc(s){const str=String(s==null?'':s);return str.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));}
function isoTodayUTC(){try{return new Date().toISOString().slice(0,10);}catch(_){return '';}}
function pickYmdFromQuery(){try{return new URL(window.location.href).searchParams.get('date');}catch(_){return null;}}
