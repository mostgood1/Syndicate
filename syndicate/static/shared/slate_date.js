/* The slate date the date-pickers default to, in ONE place.
 *
 * EXTRACTED 2026-09-09. There were SIX definitions of `localYMD` across the
 * templates and the two recap modules, in TWO distinct implementations:
 *
 *   5 copies  America/New_York with a 06:00 cutoff  (both recap modules,
 *             and the nba/nhl/wnba live-lens pages)
 *   1 copy    the BROWSER's local timezone with NO cutoff  (mlb live-lens)
 *
 * They are now one parameterised function plus a per-page configuration, so
 * MLB's difference is DECLARED IN ITS TEMPLATE IN ONE LINE instead of hiding
 * inside a sixth copy of a helper everyone assumes is the same everywhere.
 * Behaviour is unchanged on all ten pages -- both variants are reproduced
 * exactly, and that was verified by evaluating the new function and the old one
 * SIDE BY SIDE IN THE SAME PAGE LOAD, so no clock drift could mask a mismatch.
 *
 * THE DEFAULT IS CENTRAL `[2026-09-09, user decision: "move it to Central"]`.
 *
 * It was `America/New_York`, inherited from 5 of the 6 copies this file
 * replaced. That was never a decision anyone made -- it was what the copies
 * happened to say. The server has no such ambiguity:
 * `syndicate/features/shared/timezone.py` defines the slate day as
 * `ZoneInfo("America/Chicago")` and `central_today()` has **306 call sites**
 * across `syndicate/` and `pipeline/`, while
 * `tests/test_slate_date_timezone_discipline.py` opens "Syndicate's slate date
 * is CENTRAL, always" and calls it a ratchet, not a style preference. The
 * client was defaulting these ten pages to a different day from the one the
 * server resolves.
 *
 * WHAT ACTUALLY CHANGED, measured: between 05:00 and 06:00 Central the page now
 * opens on the PREVIOUS day where it used to open on the current one -- e.g. at
 * `2026-07-01T10:59Z` (05:59 ET / 04:59 Central) Eastern gave `2026-07-01` and
 * Central gives `2026-06-30`. Outside that window the two agree, which is why
 * an equivalence check run at any ordinary hour cannot see this at all.
 *
 * NOT changed, and neither is a slate-date default: `nhl/cards_source.html`
 * compares against an ET "today" DELIBERATELY ("artifact dates are ET-based")
 * to decide live polling, and `mlb/cards.html`, `mlb/cards_source.js` and
 * `intelligence.html` format an already-known timestamp. Still open:
 * `nba/cards_source.js:getLocalDateISO()` is a genuine ET slate default on a
 * different page family -- see `leads.md`.
 *
 * Load order does not matter: `localYMD` reads the config when CALLED, and
 * every call site is inside a DOMContentLoaded handler or a click handler.
 */
function slateYMD(timeZone, cutoffHour){const cutoff=Number(cutoffHour)||0;if(timeZone){try{const now=new Date();const hourStr=new Intl.DateTimeFormat('en-US',{timeZone,hour:'2-digit',hour12:false}).format(now);const hour=Number(hourStr);const base=(Number.isFinite(hour)&&hour<cutoff)?new Date(now.getTime()-24*60*60*1000):now;return new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(base);}catch(_){}}const d=new Date();const base=(d.getHours()<cutoff)?new Date(d.getTime()-24*60*60*1000):d;const y=base.getFullYear();const m=String(base.getMonth()+1).padStart(2,'0');const day=String(base.getDate()).padStart(2,'0');return `${y}-${m}-${day}`;}
// `window.SYNDICATE_SLATE_DATE = {timeZone, cutoffHour}` overrides per page.
// Absent means the SERVER's slate day: Central with an 06:00 rollback.
function localYMD(){const cfg=(typeof window!=='undefined'&&window.SYNDICATE_SLATE_DATE)||{};const tz=('timeZone' in cfg)?cfg.timeZone:'America/Chicago';const cut=('cutoffHour' in cfg)?cfg.cutoffHour:6;return slateYMD(tz,cut);}
