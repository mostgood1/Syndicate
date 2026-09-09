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
 * AN OPEN QUESTION THIS MAKES VISIBLE RATHER THAN ANSWERS. The default here is
 * `America/New_York`, because that is what 5 of the 6 copies did. But
 * `tests/test_slate_date_timezone_discipline.py` opens with "Syndicate's slate
 * date is CENTRAL, always" and calls it a ratchet, not a style preference --
 * and the client side does not agree with itself either: `America/New_York`
 * appears in 6 places and `America/Chicago` in 3 (mlb/cards.html,
 * intelligence.html, mlb/cards_source.js). Changing it is a behaviour decision
 * about what date every one of these pages opens on, not a refactor, so it is
 * recorded in `leads.md` and NOT taken here. When it is taken, it is now a
 * one-line change in one file.
 *
 * Load order does not matter: `localYMD` reads the config when CALLED, and
 * every call site is inside a DOMContentLoaded handler or a click handler.
 */
function slateYMD(timeZone, cutoffHour){const cutoff=Number(cutoffHour)||0;if(timeZone){try{const now=new Date();const hourStr=new Intl.DateTimeFormat('en-US',{timeZone,hour:'2-digit',hour12:false}).format(now);const hour=Number(hourStr);const base=(Number.isFinite(hour)&&hour<cutoff)?new Date(now.getTime()-24*60*60*1000):now;return new Intl.DateTimeFormat('en-CA',{timeZone,year:'numeric',month:'2-digit',day:'2-digit'}).format(base);}catch(_){}}const d=new Date();const base=(d.getHours()<cutoff)?new Date(d.getTime()-24*60*60*1000):d;const y=base.getFullYear();const m=String(base.getMonth()+1).padStart(2,'0');const day=String(base.getDate()).padStart(2,'0');return `${y}-${m}-${day}`;}
// `window.SYNDICATE_SLATE_DATE = {timeZone, cutoffHour}` overrides per page.
// Absent means the 5-of-6 majority: Eastern with an 06:00 rollback.
function localYMD(){const cfg=(typeof window!=='undefined'&&window.SYNDICATE_SLATE_DATE)||{};const tz=('timeZone' in cfg)?cfg.timeZone:'America/New_York';const cut=('cutoffHour' in cfg)?cfg.cutoffHour:6;return slateYMD(tz,cut);}
