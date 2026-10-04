# H37 stage 2 — FotMob shot-xG ratings for the goals-rated leagues (design, ready if H37 passes)

**2026-10-03, lane `soccer-1x2-ratings-xg-source`, session 43e4d5fe.** Read-only design, written WHILE H37 stage 1 runs,
so a SUPPORTED result can be implemented without a second survey. Researched by a read-only agent against origin/main;
file:line references are its citations, NOT individually re-verified -- re-read each before editing. Nothing here is
licensed until H37 grades SUPPORTED and the user decides.

## Facts the design rests on
- **Production holds no FotMob xG today.** `ingestion/fotmob_shots.py` (`shots_for_match`, per-shot xG from
  `/api/data/matchDetails`) is research-only, "NOT WIRED INTO THE SIM". The live poller keeps only `momentum`. The sole
  xG store is the git research cache `reports/soccer_backtest/fotmob_2y.json.gz`. No fotmob pattern in either artifact
  allowlist -- and no `soccer_source/*/history/*` pattern at all.
- **History reaches production as a frozen git seed.** `_load_team_ratings` (`build_soccer_artifacts.py` ~68-109) globs
  `<root>/<league>/history/matches_*.csv` (+ `espn_match_stats.json`); `run_refresh_worker` seeds the disk only when a
  glob has no match; `_soccer_history_step` fetches completed seasons only when missing.
- **The resolver is season-proof** (primaryId + country, `c725cc29`); a history walk uses `matches_for_date`, not the
  ESPN join. The weak point is football-data short names vs FotMob full names -- solved in the H37 harness
  (`_apply_fotmob_xg`: exact canonical, then `match_team_name` on both sides, +-1 day): 272 -> 503 of 552 Championship.

## Change list
1. **Producer** `scripts/fetch_soccer_fotmob_match_xg.py` (new): walk `matches_for_date`, keep per-side xG SUMS only,
   write `soccer_source/<league>/history/fotmob_match_xg_<season>.json` (one bounded document per completed season:
   `{date, fotmob_match_id, home, away, home_xg, away_xg, n_shots}`), resumable, small pool, refuse on league-id mismatch.
   Committed backfill (like `matches_*.csv`) -- production makes NO FotMob calls for ratings.
2. **Loader hook**: move `_apply_fotmob_xg` into `features/loaders.py` (applied to `team_rows_from_match_history` output);
   gate with a DECLARED flag (e.g. `SYNDICATE_SOCCER_FOTMOB_XG_RATINGS`, absent = off); the backtest imports the shared
   helper so it measures the same code. NOTE: `poll_soccer_live_state.py` also calls `_load_team_ratings`, so the live
   tier moves too.
3. **Degradation**: named log reason (file missing / joined X of Y), never a silent fallback.
4. **Seeding**: `_bootstrap_soccer_seed_files(... glob_pattern="fotmob_match_xg_*.json")` in `run_refresh_worker.py`
   (own glob, as `espn_match_stats.json` needed). REUSE TRAP: seeding never overwrites an existing disk file -- a
   corrected season needs a new filename or a manual push.
5. **Allowlist**: `soccer_source/*/history/fotmob_match_xg_*.json` in `EXPORT_ONLY_ARTIFACT_PATTERNS` (auditable, never
   served); consider allowlisting `history/matches_*.csv` + `espn_match_stats.json` too (unallowlisted today).
6. **Tests**: reachability (flag off != on in `_load_team_ratings` and a `build_artifacts` output), join-rate floor
   (>= 90% per league-season), allowlist predicate, and the input added to `soccer_sim_input_checklist.py`.
7. **Re-fit (engine standard 4.4)** -- shot xG is an estimator swap into constants calibrated on goals:
   `_RATING_SCALE` 0.55 / `_RATING_CAP` 0.35 (`loaders.py`; copies of the cap in `market_anchoring.py`, `live_lens.py`),
   the `0.5 + rating` blend in `possession_priors.py`, per-league `home_advantage_attack_boost`. xG has a smaller spread
   than goals, so the scale is the main lever. Re-fit on one slice, score held out on the same fixtures. Do NOT bundle
   re-enabling the 0.14 goals terms (separate mechanism).

## Risks / open decisions
- **FotMob ToS unresolved** (`scope_2026-08-21_fotmob_xg_enrichment.md`: "a decision, not an implementation detail") --
  needs a user decision before any producer ships. Unofficial API (path moved once).
- **Coverage**: FotMob history starts 2024-08; a 90-match window reaches 2023-24 rows that stay on goals (mixed scales in
  one league mean). Backfilling 2024-25 for championship/eredivisie/belgian is possible (~1.1k matches, < 1 h at 6
  workers); 2023-24 would be needed for a pure-xG window. H37 stage 1 measured the dilution: eredivisie mean in-window
  FotMob share 0.24 (0.03 first month, 0.35 from January).
- Cost is trivial at sums-only (~100 B/match).
