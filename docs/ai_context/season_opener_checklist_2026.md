# Football season-opener checklist — 2026

NCAAF starts ~Aug 29, NFL ~Sep 10. This is the concrete list of what
actually needs a manual step before then, and what's already automatic --
verified against current code on 2026-08-03, not assumed from the
2026-08-02 assessment doc's own list (which got some of this wrong; see
the notes under each item).

## Manual steps needed

1. **`SYNDICATE_ACTIVE_SPORTS` env var (Render, web service).** Gates
   which sports appear on the home command-center overview
   (`syndicate/blueprints/home.py:519-526`, `_active_sport_slugs()` ->
   `build_home_overview`). Defaults to `"mlb,wnba"` in code
   (`syndicate/app.py:273-274`) and is **not currently set at all in
   render.yaml** -- confirmed by grep. Set it to include `nfl,ncaaf`
   (and whatever else should show) before their seasons start, or NFL/
   NCAAF simply won't appear on the home dashboard even once real games
   exist. This is a config-only change (Render dashboard env var), no
   deploy needed for the value to take effect on next restart -- but per
   [[project_render_env_needs_deploy]], a restart alone does NOT
   re-inject a *newly added* env var reliably; use the single-key
   endpoint then deploy, per that memory's established workflow.

2. **`WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN` (Render, all
   services).** Currently `"false"` in `render.yaml` -- the entire NFL/
   NCAAF/NCAAB odds-refresh autorun is off in production right now. This
   is a real decision with OddsAPI call-budget implications (5M cap, see
   [[project_oddsapi_call_budget]]), not something to flip silently.
   Decide when to turn it on (some lead time before Aug 29 to validate
   the pipeline, or right at kickoff) and whether to add a
   football-specific cadence override (soccer already has its own 4h
   cadence via `run_refresh_worker.py:371`; football has never had one,
   flat 6h `WEEKLY_SPORTS_REFRESH_INTERVAL_SECONDS`).

3. **NCAAF 2026 rosters.** `build_ncaaf_roster_snapshot.py --season 2026`
   can't produce anything yet -- confirmed via a real CFBD API call this
   session: `year=2026` returns 0 rows (vs. 30,072 real rows for
   `year=2025`). Re-check CFBD directly close to Aug 29 and re-run once
   real 2026 rosters exist.

4. **NFL evaluation tracking.** `scripts/backfill_nfl_performance.py`
   (added 2026-08-03) needs real completed games to produce anything --
   there's nothing to backfill until Week 1 has actually been played.
   Run it weekly once the season starts (`--season 2026 --weeks all`) to
   build the same kind of ongoing log NCAAF already has.

## Already automatic -- do NOT add a manual step for these

- **Weekly-sports autorun's own season-window gate.**
  `_active_sports_for_date()` (`syndicate/features/shared/ops_refresh.py:1073-1107`)
  is a hardcoded calendar, not an env var: NFL activates automatically
  at `month >= 8` (i.e. already "active" by this gate's definition as of
  today, 2026-08-03), NCAAF at `month == 8 and day >= 15` (Aug 15). This
  is a *different* mechanism from `SYNDICATE_ACTIVE_SPORTS` above (item
  1 gates the home dashboard *display*; this gates whether the weekly
  autorun *would* refresh a sport, if the autorun itself is enabled per
  item 2) -- don't confuse the two, and don't add a checklist step for
  this one, it needs no manual update.
- **NFL/NCAAF week resolution.** `nfl_target_week()`/`ncaaf_target_week()`
  already correctly compute the current week from real schedule data
  (fixed earlier this session's Phase 0 audit) -- no manual "update the
  current week" step needed at kickoff.

## Cross-check before relying on this doc

This list reflects what was true 2026-08-03. Before the actual rollout,
re-verify item 1 and 2's current render.yaml/Render-dashboard state
directly rather than trusting this doc, the same way this session found
the original assessment's own hygiene list had several claims that no
longer held up when actually checked.
