# Stale OPEN lane triage — 2026-10-30 (lane `stale-lane-triage`, session eb9e3103)

READ-ONLY classification. Nothing closed until the user approves.

## Population

- Census on `origin/main` 2500a7647 (`py -3 scripts/lane_census.py`): **69 OPEN / 1 UNOWNED / 42 quiet >7d**.
  The brief's 79 / 72 came from the PRIMARY tree, 2,013 commits behind — a population nobody else has.
- "Quiet" = newest date mentioned anywhere in the block (census definition; a floor on staleness).
- Owner liveness: lane headers carry CLI session UUIDs, which never appear in `list_sessions` (0 of 30 matched).
  Mapped instead to `~/.claude/projects/*/<uuid>.jsonl`, reading the LAST message timestamp inside the
  transcript. File mtimes cluster at 06:44Z on 10-21/10-23, a batch touch rather than activity.
  Owners active ≤7d: **e0a3e383 (10-29)**, **2d413211 (10-26)**. All others 09-04..10-22; 2aff0397 has no transcript.
- Evidence per lane: three read-only readers over `deploys.md`, `git log origin/main` (slug + claimed files since
  the block's newest date), `todo.md`/`todo_closed.md`, and read-only fleet reads (file mtimes, served static JS,
  env KEYS only).
- Platform context that decides many rows: Render billing-suspended 2026-09-30 (`state_worker.md [local-production-host]`),
  so goals whose verification is a Render service/events API reading can no longer be measured as written.

## Classification (42)

| # | slug | owner last seen | rec | evidence / reason |
|---|---|---|---|---|
| 1 | ncaaf-kickoff-cache-staleness | 09-23 | CLOSE-MET | 09-23 16:36Z reading 0 TBD / 218 chips; block says ready to close |
| 2 | wnba-lines-props-backtest | 10-09 | CLOSE-MET | `03a0ab29`, 340 games; graded 10-08 |
| 3 | optimizer-props-tier | 10-14 | CLOSE-MET | `b4108767` live since 10-14 ff; 10-30 report `stake_scale: {}` = its pre-registered no-entry branch |
| 4 | optimizer-model-ev-basis | 10-19 | CLOSE-MET | `4b985db8` live; soccer predicted_ev moved -56% -> -48.1%; clean window ~11-16 (lead). Close with #3 so the daily_optimizer loan resolves |
| 5 | ci-suite-red-1015 | 10-16 | CLOSE-MET | GOAL: MET 10-16 (`bd4c7023`); both residuals now pass / fixed `78b42164`; releases broad `tests/` claim |
| 6 | kalshi-maker-shadow-paper | 10-20 | CLOSE-MET | supervisor runs it (fleet run 10-30 16:34Z, eval 12:30Z); decision carried by #706 |
| 7 | venue-native-selection | 10-22 | CLOSE-MET | findings `5e329c34`, built, live 10-21 18:13Z; readout in #719 |
| 8 | soccer-uefa-followups | 10-22 | CLOSE-MET | 2/3 read 10-21; branding CSV mtimes 10-29 on fleet; clears the contested-file FAIL with soccer-uefa-competitions |
| 9 | one-engine-alignment-audit | 10-20 | CLOSE-MET | audit delivered; owed re-measure 10-20 21:08Z 0/56 + 0/454 wrong-date; follow-on in #709 |
| 10 | polymarket-ask-pricing | 09-18 | CLOSE-MET | `POLYMARKET_PRICE_AT_ASK=1` on fleet (deploys 10-22 14:44Z); PRICED_AT_ASK place lines 10-21 |
| 11 | settlement-final-score-grader | 09-17 | CLOSE-MET | superseded + met by settlement-graders-all-sports (10-13 12:10Z: 7 sports, 62.9% settled) |
| 12 | mlb-settlement-props-join | 09-18 | CLOSE-MET | `7156d2c6` live since 09-18; MLB props grading in 10-13 all-sport read; releases 3 hot settlement files |
| 13 | polling-idle-pause-all | 09-19 | CLOSE-MET | `f4b26d70` served by fleet (`DEFAULT_IDLE_TIMEOUT_MS` read today); 28/28 node test; frees market_board.js for #699 |
| 14 | soccer-live-fotmob-fixture-cache | 09-21 | CLOSE-ABANDONED | offline half met `858a1763`; production timing was a Render live-odds-worker reading |
| 15 | layer2-adverse-movement-sanity | 09-21 | CLOSE-ABANDONED | NCAAF window passed; results in findings_2026-09-21; movement-weight question -> lead |
| 16 | live-gameline-game-identity | 09-23 | CLOSE-ABANDONED | met offline `4a231ac8`; DH reading is 2027, already in leads.md + task dh-verify-2027-opening-day |
| 17 | accuracy-ledger-budget-raise | 09-04 | CLOSE-ABANDONED | coverage met 09-11; memory clause Render-only; releases intelligence_evaluation.py; #626(h) keeps the history |
| 18 | polymarket-rejected-resubmit-loop | 09-18 | CLOSE-ABANDONED | `1f9c9c62` live; trigger never recurred; holds nothing |
| 19 | live-odds-worker-oom-loop | 09-13 | CLOSE-ABANDONED | Render 2Gi events-API goal; service suspended |
| 20 | layer2-today-next-day-starvation | 09-18 | CLOSE-ABANDONED | measured on Render; floor decision never made; new lane if still wanted on fleet |
| 21 | quote-state-publish-retry | 09-13 | CLOSE-ABANDONED | fleet runs with worker->web publish OFF (shared disk); retry path cannot fire |
| 22 | web-memory-guard | 09-17 | CLOSE-ABANDONED | Render web service id + limits; holds nothing |
| 23 | nfl-game-day-injuries | none | HAND-OFF #690 | flag only ever on Render; #690 OPEN carries it |
| 24 | venue-prop-close-coverage | 10-22 | HAND-OFF #729 | fix live + measured 10-22; forward read is #729's |
| 25 | worker-disk-auto-retention | 09-18 | HAND-OFF #668 | dry run only; no RETENTION env on fleet; #668 needs restating for the fleet |
| 26 | wnba-sprint-0917 | 09-17 | HAND-OFF #623 | window passed; readings 1-3 PASS; holds nothing |
| 27 | daily-accuracy-suite (UNOWNED) | 09-20 | HAND-OFF new todo | 3/4 clauses met; OWED (b) NBA regular-season grading read. NOTE: lent population_outcomes_espn.py to OPEN `cheat-sheets` "returns on close" |
| 28 | nba-layer2-projections | 10-05 | HAND-OFF new todo | prop half (`prop_rows_with_projection`) readable now that regular-season props exist |
| 29 | fleet-watchdog-auto-recovery | 10-16 | HAND-OFF new todo | built + installed; RECOVERY_START never fired. User kept it open 10-14 — confirm |
| 30 | nfl-prop-missing-odds-relaunch | 10-07 | HAND-OFF new todo | `544cbb4e` landed; fleet `odds_newer_than_launch` read at a week rollover |
| 31 | soccer-corners-distribution | 10-14 | HAND-OFF new todo | pickup item never started; holds nothing |
| 32 | nhl-game-any-line-pricing | 10-14 | HAND-OFF new todo | pickup item never started; holds nothing |
| 33 | nfl-segment-model | 10-14 | HAND-OFF new todo | never started; more relevant since segment capture `a126ae95` |
| 34 | games-rail-full-detail | 10-14 | HAND-OFF new todo | one live NFL/NCAAF down-and-distance read left; ~20-file claim |
| 35 | football-scenario-calibration | 10-12 | KEEP | 10-27 activity; task nfl-2026-refit-v2-validation (11-03) depends on the lane being open |
| 36 | paper-bet-optimization | 10-20 | KEEP | forward read 10-27; weekly task paper-bet-optimization-forward |
| 37 | nba-lines-props-backtest | **10-29** | owner live: ASK OWNER (would be CLOSE-MET) | "nothing owed" per block |
| 38 | nba-prop-calibration | **10-29** | owner live: ASK OWNER (would be CLOSE-MET) | GOAL MET 10-04 in header; follow-on reads unowned |
| 39 | nba-season-phase | **10-29** | owner live: ASK OWNER (would be HAND-OFF / fold into #696) | post-10-20 checks unrecorded; 12 files held |
| 40 | nba-live-tick-native | **10-26** | owner live: ASK OWNER (would be CLOSE-MET) | port live, writes daily; A/B vs vendor impossible (vendor deleted). Task wnba-p5-end-state-check watches it |
| 41 | wnba-fixture-identity-native | **10-26** | owner live: ASK OWNER (would be CLOSE-MET) | `44508f56` live; game_cards read owed -> 2027 lead |
| 42 | wnba-live-period-lines-native | **10-26** | owner live: ASK OWNER (would be HAND-OFF, May 2027) | parity 32/32; live read is 2027 opener |

## Side findings (not acted on)

- Stale OPEN todo headlines: `#662` (ask pricing is live), `#670` (all-sport settlement measured 10-13),
  `#697` (both residual tests pass), `#706` ("hourly NOT running" false since 10-20 15:23Z), `#709` ("NO CODE" — step 2 built).
- Fleet WNBA `game_cards_*` location unknown (no `wnba_source` under the fleet data root).
