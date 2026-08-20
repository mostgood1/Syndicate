# state.md — [football-smartsim2] archived 2026-08-20

Moved VERBATIM from `state.md` by lane `football-model-owner`, which OWNS this
subject, when the file stood at 236KB against a 175KB cap and therefore arrived
LOSSY at every session start.

The section had accumulated 25 bullets across three days. Roughly half were
SUPERSEDED by the 2026-08-20 finding that the model is STRICTLY DOMINATED —
chiefly the careful planning for how to wire `feature_generation_payload`, which
is moot once the model's deviation from the market is measured to carry zero
information. The rest were resolved history (the 2026-08-18 board cap) or
self-declared superseded.

`state.md` keeps ONE keyed section for this subject, carrying every LIVE fact,
so `state_key_check.py` still sees one subject per section. Nothing was deleted;
the full original is below.

ONLY THIS LANE'S OWN SUBJECT WAS TOUCHED — compressing another lane's prose is
that lane's call, the rule `state_archive_2026-08-19.md` states.

---

## [football-smartsim2] FOOTBALL (NFL + NCAAF) — smartsim2 runs on FOUR SCALARS `[measured 2026-08-18, lane football-model-owner]`

**Owner: `football-model-owner`.** Full reference:
`docs/ai_context/football_sim_engine_reference.md`. Gate:
`py -3 scripts/football_sim_input_checklist.py --season 2025 --week 1` (exits 1).

- **The engine consumes 9 feature blocks / 65 keys out of
  `feature_generation_payload`, and 0 of 3 production entrypoints pass one.**
  Every NFL and NCAAF game served runs on `home/away_offense_rating`,
  `home/away_defense_rating` and a hardcoded `pace_seconds_per_play=24.0`.
  `returning_production_index` 0.5 / `coach_continuity_index` 0.5 /
  `player_usage_index` 0.25 / `market_prior_index` 0.5 are constants carried
  identically by every game.
- **Reachability measured, not inferred:** 21 of 21 drive-prior fields move when
  fed. 400 seeds/arm → margin −1.125, total −1.685, home win% **−6.50 pts**.
- **DO NOT SIMPLY WIRE IT.** Both calibration profiles were fit against a payload
  the engine cannot read, so this is a mechanism added to a calibrated engine and
  owes a **re-fit** (`model_engine_standard.md` §4.4 — negative interaction in
  4 of 4 markets measured elsewhere). Those deltas are the DISTURBANCE, not the
  improvement. `#457`.
- **Three unfed blocks, three DIFFERENT remedies — do not batch them.** Over 272
  real NFL games: `defensive_metrics` **MISROUTED** (all 7 keys sit in
  `team_metrics` at 100%), `pace` **NULL AT SOURCE** (all 4 keys `None`),
  `player_usage` **WRONG GRAIN** (19,400 player rows exist; no game-level block;
  `adapters.py:_team_player_usage` already aggregates correctly and nothing
  consumes it). `offensive_metrics`/`advanced_metrics`/`market_features` are
  **100% fed**.
- **NCAAF PICKS ARE SUPPRESSED IN PRODUCTION — the margin model LOSES to the
  closing line** `[measured 2026-08-19, live web 8833cfd6 19:18:07Z]`.
  `/ncaaf/api/picks?week=1` serves **0 cards (was 12)** with a suppression
  `empty_state`; `/ncaaf/api/cards?week=1` still serves **51 games** and NFL
  picks still serve 12 — only the BET is withheld. Evidence: prior-season 2024
  SP+ scoring realised 2025 margins, n=220, closing spread on the same games —
  **model MAE 13.763 vs market 11.586, paired dMAE +2.176, SE 0.518, t=+4.20.**
  Every scale 6..24 loses, so it is the MODEL, not a constant. By week:
  **+1.815 (wk1-3) → +4.111 (wk7-9)** — staleness is a real driver and the
  opener is where the model is closest. Gate (default-DENY, a market opens only
  on a recorded win): `syndicate/features/football/pick_gate.py`. Plan and exit
  criterion: `docs/ai_context/ncaaf_beat_the_close_strategy.md`.
  **CALIBRATED IS NOT COMPETITIVE** — the earlier "margins fixed, SD 1.74 →
  15.37, ratio 1.06" was a DISPERSION match and said nothing about accuracy,
  which had never been tested until now. `CFBD_API_KEY` is set (user, 08-18).
  refresh-worker `f2eb719d` (SP+ ratings + as-of PPA leak fix) live 18:51:08Z,
  stage 1 verified by content; **STAGE 2 STILL OWED** — ~51/51 non-null
  `predictions.home_mean`, 86400s autorun, ≤24h. Season opens **2026-08-29**.
- **The model loses to the close AND the open, CLEAN and OUT-OF-SAMPLE.**
  `[measured 2026-08-19: 2023 SP+ -> 2024 games, all 15 weeks, 100 seeds,
  PRODUCTION generator via --ratings-season, graded from the pick ledger,
  graded_leak_status {'clean': 2236}, no leak warning]`
  vs close **n=2233 model MAE 15.775 vs market 12.212, +3.563, t=+17.20**;
  vs open n=2148 **+3.329** (t=+16.23). Loses to Bovada (+3.578), DraftKings
  (+3.560) and ESPN Bet (+3.549) INDEPENDENTLY. **Replicates the leaked 2025
  season** (+3.419) and is slightly WORSE clean — the direction leakage
  predicts, so the two measurements corroborate rather than merely agree.
  **2 of 14 per-week buckets read TIED — that is multiplicity, NOT an edge**:
  the best bucket is still positive, and TIED loses after vig anyway.
  `[superseded: full 2025 season, LEAKED rows, vs close +3.419 / vs open +3.358]`
  The open is **0.06 MAE softer than the close** — this is an ACCURACY problem,
  not a timing one, and "beat the open first" is dead as a shortcut. Loses to
  Bovada/DraftKings/ESPN Bet individually, so not an artefact of one sharp book.
  Those rows are 100% LEAKED (`cfbd_ppa_season_2025`), which FLATTERS the model
  and makes the verdict stronger, not weaker.
- **THE NCAAF MODEL IS STRICTLY DOMINATED — not broken, and that changes the
  fix** `[measured 2026-08-20, 751 clean out-of-sample games]`. Fitting
  `actual = a + b*market + w*(model-market)`: **b=+0.990** CI [0.909,1.076] (the
  closing line is UNBIASED) and **w=-0.028** CI [-0.130,+0.069] (the model's
  deviation carries ZERO information). r(market,actual)=+0.645 → R² **41.6%**;
  r(model,actual)=+0.421 → R² **17.8%**. The model has REAL signal and is
  strictly dominated: everything it knows the market knows, and where they
  differ it is noise. **Gap = 23.8 points of R².** This ONE fact explains every
  failed remedy — no threshold, weight or subset helps a dominated model.
  Diagnostic: `scripts/grade_football_model_weight.py`.
- **THE MODEL LOSES TO A MINDLESS SIDE BET** `[measured 2026-08-20]`.
  always-bet-the-underdog **51.2%** vs the model's **46.8%** (NCAAF, 735 bets);
  **58.9%** vs **54.7%** (NFL preseason, 95 bets) — **−4.4 and −4.2 points in two
  independent sports**. NCAAF ATS gets WORSE as the edge filter tightens
  (46.8% → 45.2% at 10+ points), so "serve only the strong picks" fails in the
  direction opposite to the one that would help.
- **EVERY LEVER IS NOW MEASURED, AND ALL ARE DEAD** `[2026-08-20]`.
  **Situational** (rest/travel/altitude/tz/neutral/dome/conference/kick-hour):
  all 8 priced, 1,746 games, no |t|≥2 — positive control t=+2.70 proves the
  instrument. **Injuries**: the NFL market prices them, 272 games, all 4 burden
  measures null, direct ATS 54.5/50.0/58.3% with every CI spanning 52.4% and
  NON-MONOTONIC. **Returning production**: pooled ΔMAE −0.062, t=−0.89, code
  REMOVED. **Ratings tuning**: every scale 6..24 loses. **Blending**: w≈0, so
  the optimal blend is 100% market.
- **NO USABLE NCAAF INJURY FEED** `[measured 2026-08-20]`. CFBD's OpenAPI spec
  enumerated: **74 endpoints, none injury-shaped**. ESPN core API — NFL control
  **597 fresh injuries across 8 teams** vs CFB **1 record across 60, dated
  2020-11-21 (2,097 days stale)**. Structural cause: the NCAA has **no mandatory
  injury report**, so every vendor inherits that ceiling.
  Re-check in-season: `scripts/probe_ncaaf_injury_feed.py`.
- **THE PICK-GATE EXIT CRITERION WAS REPLACED** `[2026-08-20, web `ea6f431f`
  live 15:55:25Z, verified 8/8 probes]`. The old bar (paired MAE ≤ the close)
  was necessary but far too weak. Now `pick_gate.LIFT_CONDITION` requires: ATS
  above the better naive baseline, a 95% CI LOWER bound above 52.4%,
  out-of-sample with subsets pre-specified, and denominators in BETS not rows
  (per-book rows overstated significance **3.4×**). Measured by
  `scripts/grade_football_playability.py`; pinned by `LiftConditionTests`.
- **THE BOARD SERVES SP+, WEEK 1 ONLY** `[measured 2026-08-19, web 6b23d6fa,
  MULTI-PROBE 10 probes/week]`. Weeks 1/5/12 each 10/10 -> 51 games, `|margin|`
  SD **12.93**, max **50.60** (old PPA: 1.58 / 7.80). Every week resolves to
  week 1 — the only week inside the pregame window.
  **A SINGLE READ OF THIS SERVICE IS NOT A MEASUREMENT**: after the previous
  deploy one sample said SP+ while 12 probes read **9 PPA / 3 SP+** (gunicorn
  workers cache the projection index at different moments around the bootstrap
  sync). Probe repeatedly.
- **THE ARTIFACT REACHES WEB VIA GIT -> WEB DEPLOY -> BOOTSTRAP -> MOUNTED DISK,
  NOT VIA THE WORKER** `[measured 2026-08-19]`. `smartsim2_projections_*.csv`
  matches **NONE of the 127** `HOT_ARTIFACT_PATTERNS`; web reads
  `SYNDICATE_NCAAF_SOURCE_ROOT=/opt/render/project/data/ncaaf_source` (its
  MOUNTED DISK, not the checkout); `bootstrap_data_root` copies and **NEVER
  prunes**. So the refresh-worker season-projection autorun regenerates a file
  **nothing reads**, and deleting a stale artifact from git does NOT remove it
  from the disk being served — the pregame-window guard is what stops it.
  Both generators now call `publish_hot_artifact`, INERT until the allowlist
  lands (handed to `soccer-odds-capture-cadence-gap`).
- **Returning production: BUILT, MEASURED, NOT SHIPPED** `[2026-08-19]`. Wired
  as a RATING adjustment (17.2% lever, not the 4.1% payload). Reachability
  passed (50 of 51 margins moved). 2024 backtest, leak-free, n=749: OFF MAE
  15.778 -> ON 15.630, paired **dMAE -0.149, SE 0.094, t=-1.58 NOT
  SIGNIFICANT**. Opt-in behind `--returning-production`, default OFF. A second
  season was running at checkpoint to settle it — **no pooled result yet.**
- **Stage 0 instrumentation EXISTS** — `syndicate/features/football/pick_ledger.py`
  + `scripts/build_ncaaf_pick_ledger.py`, one row per (game × provider) carrying
  model margin / OPENING line / CLOSING line / realised result. **It BACKFILLS**:
  CFBD serves `spreadOpen` retrospectively (~74%) with finals on the same
  payload, which is why the open question was answered the day it was written.
  2025 backfilled (2,530 rows); 2024 market-only until the clean backtest lands.
- **DO NOT diagnose NCAAF from a local checkout.** `load_features(sport="ncaaf")`
  returns **0 games locally** while production serves 16. I filed that local zero
  as a production defect and retracted it. `data/**` lossy mirror, as CLAUDE.md
  says.
- **FIXED, DEPLOYED AND MEASURED 2026-08-18 18:48Z: the NCAAF board was capping
  the slate at 16.** Live on web as `5fdabc46` (cap) + `4c3b0aa5` (its counter).
  **Served payload, six weeks: 16 -> 51 / 49 / 57 / 56 / 56 / 66, with
  `games == runtime_rows`, `truncated: false`, `dropped: 0` on every one.**
  **Week 1 = 51 = CFBD's independent FBS-vs-FBS count** — cross-source
  agreement, not merely a bigger number. Max slate 66 vs the 80 guard.
  **The alternative is dead:** `runtime_rows` of 49-66 proves the summaries
  always held a full slate, so the 16 was entirely the cap. Had `runtime_rows`
  read 16, the cap would have been exonerated — which is why the counter shipped
  WITH the change, not after it.
- **The cap fix's own INSTRUMENT shipped inert, and it was the SAME defect.**
  `board_row_counts` was absent from the payload while the fix worked, because
  `build_game_board_api_payload` **whitelists** response keys.
  `apply_game_board_contract` does preserve extras (`dict(context)`) — **it is
  not the last hop.** Presence in the context is not reachability to the client,
  exactly as presence in `_collapse_games` was not reachability to the board.
  Twice in one change.
- **`deploy_preflight --service web` can NEVER return CLEAR** — web does not emit
  `ALL_PROCESS_MEMORY` at all (sample 3.9 days old, predating the live deploy).
  Positive control: refresh-worker on the same instrument reads **7s**. A
  break-glass grant was used, user-authorised, with a live `/api/ops/memory`
  process read substituted as better evidence. **OWED: make web emit it** so this
  does not need a grant every time.
- **`/portdetectorv2` is RENDER PLATFORM INFRA, not a job**, and it appears
  *because* you just deployed — so a name-based idle check blocks the second
  deploy of every pair. `deploy_preflight` classes it `[infra]`. Same for pid 1
  `bash /home/render/graceful-shell-command.sh`. **Classify by cmdline.**
- **SUPERSEDED (was: the deploy-ordering hazard).** The board fix is live BEFORE
  the key, which is the order that was required. The SmartSim2-standalone branch
  can no longer truncate ~51 rows to 16 when the artifact starts existing.
- ~~**FIXED (`752a866d`, UNDEPLOYED): the NCAAF board was capping the slate at 16.**~~
  Weeks 1/2/3/5/8/12 all served exactly 16; CFBD lists **51** FBS-vs-FBS for wk1.
  16 = 32 teams / 2 — an **NFL-shaped number**, correct for NFL, wrong for a
  50-60 game sport, which is why it was invisible. **THREE caps on three branches
  of the same page**; the route calls `build_smartsim_cards_page_context`, NOT
  `build_cards_page_context`, so fixing `_collapse_games` alone would have been
  INERT. `_NCAAF_BOARD_GAME_LIMIT = 80` — raised, not removed (~9.8 KB/game, 2GB
  web service). Truncation now self-reports via `board_row_counts` on the payload
  (present whether or not it bit) + `NCAAF_BOARD_TRUNCATED` on web stdout.
- **DEPLOY ORDERING IS LOAD-BEARING: web (`752a866d`) FIRST or together, THEN the
  key.** The SmartSim2-standalone branch is empty today only because the artifact
  is missing; the moment the key lands it returns ~51 rows, and the old `[:16]`
  would cut them back to 16 **with `verify:` passing**. Key-alone is the one
  combination to avoid.
- **RENDER IS THE SOURCE OF TRUTH — now MANDATORY in
  `model_engine_standard.md` §3b** `[user directive 2026-08-18]`. Every claim
  must name its substrate and that substrate must be Render. Also: an input NOT
  in `HOT_ARTIFACT_PATTERNS` is UNAUDITABLE — NCAAF's `recommendations_summary`
  (the artifact its board renders from) is not allowlisted. **Owed.**
- **There are TWO unrelated football models.** `FootballSimulationAdapter`
  (`adapters.py:110`) is a closed-form linear formula that **never calls
  smartsim2**; its callers are all offline analysis. smartsim2 is the only
  user-facing one. `NflAdapter`/`NcaafAdapter` have zero non-self callers.
- **`smartsim2/calibration_profile.py` showing as `M` in `git status` is NOT
  orphaned work** — it is `964c89a4`, already on `origin/main`.

**NOT AUDITED** (so not a clean bill): `SYNDICATE_DATA_ROOT` backing,
`HOT_ARTIFACT_PATTERNS` allowlisting, reuse-flag rebuild procedure, and a
market-relative scoreboard.


