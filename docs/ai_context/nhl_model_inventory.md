# NHL model inventory — what exists and where

> 2026-08-18, lane `nhl-model-owner`. NHL's counterpart to the
> MLB/basketball "what exists and where" documents (`basketball_model_inventory.md`
> is the closest sibling in structure). Catalog only — for input-population
> findings, the pipeline trace, and the Elo backtest, see
> `docs/ai_context/hockeysim_engine_reference.md`.

---

## 1. Sim engine

**One Syndicate-native engine, `hockeysim`, replacing a vendored trained-NN
engine — NOT a straight port, a deliberate redesign.**

| | |
|---|---|
| engine | `syndicate/features/nhl/sim_engine/hockeysim/` — 34 files |
| entry points | `projection.project_game` (pregame xG/Poisson/Elo → expected goals + period lambdas), `game_market_sim.simulate_from_period_lambdas` (fast ML/spread/total path), `engine.HockeySim` (possession-level boxscore/props sim) |
| what it replaced | `vendor/nhl_betting_repo/nhl_betting/models/nn_games.py` — a trained neural net. `projection.py`'s own docstring: *"the Syndicate-native replacement for the vendor's trained NN game model... rather than porting the neural net, it derives per-team expected goals from an xG / Poisson / Elo formulation."* This was a deliberate architecture change, not a migration-in-progress. |
| calibration | **Two separate profile objects, easily conflated** (see reference doc §2): `projection.ProjectionProfile` (truth-calibrated, Phase 3b, `#440`) governs pregame expected goals; `calibration_profile.SimConfig` / `NHL_CALIBRATION_PROFILE_DEFAULT` (still the absorbed vendor's original constants, never truth-calibrated) governs in-sim mechanics — dispersion, special-teams multipliers, faceoff knobs. |
| granularity | pregame projection → per-period goal lambdas → fast game-market sim (ML/spread/total) **and separately** → possession-level boxscore sim (props) |
| truth layer | `historical_truth/` — real finished-game feeds from `api-web.nhle.com`, cached locally (1,312 games, 2025-10-07..2026-04-16, `nhl_source/data/truth/raw/landing_*.json`, untracked mirror output). Used for the Phase 3 truth baseline (`docs/reports/hockeysim_phase3_truth_baseline_report.md`), Phase 3b calibration (`hockeysim_phase3b_calibration_report.md`), and (new, this session) the Elo producer. |

**This is more mature on the sim-math side than CLAUDE.md's "Module maturity"
table implies** — that table describes board/UI migration status, not the
sim engine, which is closer to soccer's (real, calibrated, truth-baselined)
than "active migration, varying completeness" suggests.

---

## 2. Feature module inventory (`syndicate/features/nhl/`)

| file | size | role |
|---|---|---|
| `cards.py` | 46,126 bytes | main board — reads `predictions_{date}.csv` / `predictions_sim_{date}.csv` / `props_recommendations_{date}.csv` directly (`processed_path(...)`) |
| `live_lens.py` | 31,689 bytes | in-game live projection surface |
| `market_accuracy.py` | 12,802 bytes | model-vs-market accuracy tracking |
| `sources.py` | 9,949 bytes | artifact mirror path resolution |
| `picks.py` | 8,765 bytes | picks surface |
| `betting_recap.py` | 7,861 bytes | recap surface |
| `archive.py` | 6,066 bytes | daily archive |
| `player_props_reconciliation.py` | 5,818 bytes | props settlement reconciliation |
| `props_lines.py` | 3,611 bytes | props market-line handling |
| `intelligence_analysis.py` | 1,802 bytes | intelligence-layer integration |
| `live_lens_daily_accuracy.py`, `live_game_accuracy.py` | <1KB each | thin accuracy-tracking shims |

No `betting_card.py`/`features.py` split the way basketball's NBA module has
— NHL's `cards.py` is the single largest file and carries most of the board
logic directly, closer to WNBA's shape (one large `cards.py`) than NBA's
(split across dedicated files) per `basketball_model_inventory.md`'s §3
comparison.

`syndicate/blueprints/nhl.py` is the Flask blueprint; it does not call
`build_nhl_artifacts.py` or the sim engine directly — consistent with the
"web reads, workers/self-generation write" rule (see reference doc §7 for the
specific self-generation mechanism this sport uses instead of the
worker-push-to-web pattern MLB/basketball use).

---

## 3. Producer / script inventory (`scripts/`)

| script | role | new this session? |
|---|---|---|
| `build_nhl_artifacts.py` | the daily producer — `build_predictions_for_date`, `build_recommendations_for_date`, `build_props_for_date` | no |
| `refresh_nhl_oddsapi.py` | odds refresh + owns local-generation gating (`SYNDICATE_NHL_SOURCE_CLI_GENERATION`) | no |
| `refresh_nhl_source_mirror.ps1` | cold-start mirror refresh | no |
| `nhl_sim_input_checklist.py` | the CONSUMED-vs-POPULATED gate `model_engine_standard.md` §1 requires — **did not exist before this session**; corrected mid-session (reference doc §2b) | **yes** |
| `build_nhl_elo_artifact.py` | Elo producer from cached truth data | **yes** |
| `build_nhl_special_teams_artifact.py` | PP%/PK%/committed-per-game producer from cached truth data (extended `nhl_statsweb_loader.parse_landing` to capture penalties) | **yes** |

**No dedicated audit/checklist tooling existed in the vendor tree before this
session.** `vendor/nhl_betting_repo/nhl_betting/scripts/` holds
`backtest_daily_summary.py`, `build_two_seasons(_web).py`, `daily_update.py`,
`first10_eval.py`, `infer_odds_from_edges.py`, `reexport_onnx.py`,
`train_nn_games.py`, `train_nn_props.py` — training/backtest/build tooling for
the now-replaced NN engine, not input-population auditing. This contrasts with
basketball, which inherited a rich `audit_*.py` set (11+ tools per vendor tree)
from its own vendor repos; NHL had none of that class of tool at all until
`nhl_sim_input_checklist.py` this session.

---

## 4. Known open gaps, with `todo.md` IDs

| id | one-line | status |
|---|---|---|
| `#463` | This session's findings: `elo_rating` + `goals_per_60` staleness + `special_teams` (goal conversion + per-team shot + per-team block rate) + `special_teams_cal` (ALL 6 non-neutral keys calibrated) + a real xG model + `shots_per_60`/`faceoff_win_pct` + player usage weights ALL FIXED (reachable); `blocks_per_60`/`penalties_per_60` populated then proven a CONFIRMED DEAD GATE and REMOVED entirely (neither field could gain a legitimate consumer without duplicating already-live real data) — checklist reports a full PASS | FOUND, MEASURED, FULLY CLOSED this session |
| `#454` | Play-by-play was an unused offline modelling substrate — NHL was one of only 3 sports (with soccer, NCAAB) with **zero** pbp files ingested | **CLOSED as a data-availability gap this session** (still open as a cross-sport tracking item for soccer/NCAAB). `NhlWebIngestClient.play_by_play()` + `scripts/fetch_nhl_playbyplay_cache.py` bulk-fetched all 1,312 regular-season games (reference doc §2i) — the substrate now exists and is consumed by both the xG model (§2i) and team rates' faceoff data (§2j). |
| `#440` | Sim-engine track pin (cross-sport); this session's work is NHL's contribution to it | PLANNED, referenced throughout |

**`.syndicate/audit_2026-08-14_models.md`** (line 170/192) already flagged NHL's
`market_anchoring.py` circularity (current book prices as a model input,
making market-relative evaluation near-circular by construction) — carried
forward as a standing caveat in the reference doc §7, not re-litigated here.

---

## 5. What this lane did NOT do

- **Did** build the `HockeyTeamFeatures.special_teams` (`pp_pct`/`pk_pct`/
  `committed_per_game`) PP/PK data pipeline — extending the earlier session's
  framing, which had wrongly attributed this field to a different, unreachable
  parameter (`special_teams_cal`, corrected in reference doc §2b). Verified
  with a reachability test (elite PP outscores poor PP on average, 80 seeded
  runs) — not yet a calibration backtest of the effect SIZE.
- **Did** wire `special_teams_cal`'s 7 keys (reference doc §2c) — moved onto
  `SimConfig` (`pp_shot_cal_mult` etc), resolved via `build_nhl_sim_config`,
  mapped and passed by `player_props._special_teams_cal`. Values initially
  unchanged from the old neutral defaults (a wiring fix, not yet a calibration
  change); reachability-tested the same way as `pp_pct` above.
- **Did** calibrate `pp_goal_cal_mult`/`pk_goal_cal_mult` against real truth
  (reference doc §2d, full report `docs/reports/hockeysim_special_teams_goal_cal_report.md`).
  Added a new truth metric (`sh_goal_share`, from a new `sh_goals_home/away`
  parser extension — no new fetch) and ran the REAL engine over thousands of
  simulated games to search for the multiplier matching it. Result:
  `pp_goal_cal_mult` needed no correction (the existing mechanism was already
  accurate); `pk_goal_cal_mult` needed a real one — uncalibrated, the engine
  simulated shorthanded goals at more than double the real rate. Corrected to
  `0.4645`, locked in a test. Deliberately did NOT attempt per-team
  differentiation of either multiplier — that would double-count against the
  already-per-team `pp_pct`/`pk_pct` signal (reference doc §2d/§5).
- **Did** bulk-fetch the `boxscore` endpoint (`scripts/fetch_nhl_boxscore_cache.py`,
  1,297 new fetches, 0 failures — only 11/1,312 games were cached before) and
  build `historical_truth/boxscore_shot_strength.py` to parse per-team PP/PK
  SHOT volume (distinct from the goal-share truth above; the `landing` feed
  has no shot-by-strength-state breakdown). Cross-validated against the
  independent `landing` feed's SOG count (55.27 vs 55.66 — close agreement,
  two different endpoints/parsers).
- **Did** calibrate `pp_shot_cal_mult`/`pk_shot_cal_mult` against that new
  truth (reference doc §2e, full report
  `docs/reports/hockeysim_special_teams_shot_cal_report.md`). Found and fixed
  a real methodology bug along the way: a naive sequential fit (pp then pk)
  left a ~5% verification gap even at 260,000 simulated shots, because the two
  targets share a denominator and the uncalibrated pk correction shifts it
  substantially. Fixed with a JOINT alternating fit (3 rounds) plus a full
  round-robin team-pairing (removes a second variance source). Result:
  `pp_shot_cal_mult=0.9108` (real, modest correction), `pk_shot_cal_mult=0.3369`
  (real, substantial — shots-while-shorthanded were over-simulated ~2.8x,
  matching the same direction/magnitude as `pk_goal_cal_mult`'s correction,
  circumstantial evidence of one shared root cause rather than two). Final
  verification: 318,093 simulated shots, both targets matched almost exactly.
- **Did** build genuine per-team PP/PK SHOT-volume differentiation (reference
  doc §2f, full report `docs/reports/hockeysim_per_team_shot_rate_report.md`)
  — a NEW mechanism, not a calibration. `historical_truth.boxscore_shot_strength.compute_team_shot_rate_index`
  produces `pp_shot_index`/`pk_shot_index_allowed` per team, normalized by
  PP/PK OPPORTUNITY count (not raw shot count, to avoid conflating "how often
  on the power play" with "how many shots once there"). Wired into `engine.py`'s
  `home_factor`/`away_factor` shot-volume terms alongside the existing global
  multipliers. Measured: mean ≈1.006 across 32 real teams (confirms proper
  normalization); real spread NJD 1.237x to MTL 0.802x; EDM lands near the
  top (1.137x), the same team independently measured with the league's best
  PP goal rate — two unrelated data sources agreeing. **Verified the existing
  global calibration did not need re-fitting**: with real per-team indices
  active, the league-wide simulated aggregate still matches truth closely
  (`pp_shot_share` 0.1478 vs 0.1488, `sh_shot_share` 0.0279 vs 0.0272,
  158,826 simulated shots) — the per-team layer shifts which team gets more
  shots in a matchup, not the league average. Reachability-tested.
- **Did** build genuine per-team blocked-shot-rate differentiation (reference
  doc §2g, full report `docs/reports/hockeysim_per_team_block_rate_report.md`)
  — closing the last special-teams gap. `historical_truth.boxscore_block_rate.compute_team_block_rate_index`
  produces `block_rate_index` per team from the same `boxscore` cache §2e/§2f
  already bulk-fetched (blocks/shots-faced ratio, normalized against the
  league-wide ratio — the ONLY basis available, since blocked shots carry no
  strength-state split in this source at all, unlike PP/PK shots). Measured:
  1,312 games, league block rate 33.77%, 14.19 blocks/game/team, mean index
  0.9999 (confirms normalization); real spread PHI (1.102x)/VGK (1.098x)/MTL
  (1.091x) highest, NSH (0.867x)/CHI (0.869x) lowest, ~27% top-to-bottom.
  Wired into `engine.py`, scaling the blocking team's own probability right
  before the block roll, clamped `[0.02, 0.95]`. **Verified the league-wide
  average did not shift**: 200 round-robin pairings, 24.635 avg blocks/game
  neutral vs 24.475 real-indexed — noise-level. Reachability-tested. This pass
  deliberately did NOT calibrate the ABSOLUTE block rate — done next, below.
- **Did** calibrate the ABSOLUTE block rate (reference doc §2h, full report
  `docs/reports/hockeysim_absolute_block_rate_cal_report.md`) — the base
  constants the per-team pass above deliberately left at the vendor's
  never-measured 0.45/0.55/0.35. Only ONE league-wide truth target exists
  (blocked shots carry no strength-state split at all), so `scripts/calibrate_nhl_block_rate.py`
  fits a SINGLE shared scale factor applied uniformly to all three constants,
  preserving their existing structural ratio — the only degree of freedom the
  data supports (fitting 3 independently against 1 number would be
  underdetermined). Fit with `block_rate_index` held neutral (isolates the
  absolute level from the per-team layer), converged in 5 proportional-correction
  iterations against target `blocks_per_game(team)=14.1905`: 13.2613 → 14.2800
  → 14.1821 → 14.1958 → 14.1975. Result: `block_scale=1.0631` (a modest ~6.3%
  correction) → `block_rate_ev=0.4784`, `block_rate_pk=0.5847`,
  `block_rate_pp_def=0.3721`. **Verified twice** on the full 992-pairing
  round-robin (19,840 games each): 14.2606 with the index still neutral,
  14.2583 with the REAL per-team index active — both ~0.5% above target,
  confirming (again, now against the calibrated base) that the per-team layer
  doesn't disturb the league-wide level. Locked in a test. Every one of
  `special_teams_cal`'s 7 keys except `pp_goal_multiplier` (measured
  statistically indistinguishable from neutral, §2d) is now truth-calibrated.
- **Did** build the GLOBAL team rates the props engine's `TeamRates` reads —
  `shots_per_60`/`blocks_per_60`/`faceoff_win_pct` (reference doc §2j, full
  report `docs/reports/hockeysim_team_rates_report.md`) — distinct from the
  PP/PK-SPECIFIC shot/block differentiation built above (that's a per-strength-
  state SIGNAL; this is the flat ALL-situations rate `TeamRates` itself reads).
  `historical_truth/team_game_rates.py` parses SOG + blocks from the boxscore
  cache and faceoff wins from the play-by-play cache (`eventOwnerTeamId` on a
  `faceoff` event is the WINNING team — verified against `rosterSpots`, 0/70
  mismatches). Run against all 1,312 games: fully joined. League avg blocks/60
  = 14.19, an EXACT match to §2g/§2h's independently-computed truth — a real
  cross-check between two separately-built modules. `penalties_per_60` reuses
  `special_teams`'s already-computed `committed_per_game` — no new producer,
  just a second read of an already-real value. **A real finding, not glossed
  over**: reachability testing (holding to the SAME bar every other input this
  session got) proved `shots_per_60`/`faceoff_win_pct` change engine output,
  while `blocks_per_60`/`penalties_per_60` are a CONFIRMED DEAD GATE —
  populated all the way into `TeamRates` but never read by `engine.py`
  (proven with a fixed-seed, byte-identical-output test, not assumed from
  code reading) — the same class of bug as basketball's `#467`. Deliberately
  NOT force-fixed with a new consumption mechanism: blocks are already fully
  modeled by the truth-calibrated `block_rate_*` + `block_rate_index`
  mechanism (§2g/§2h), and bolting `blocks_per_60` on top risks double-
  counting; `penalties_per_60` has no market or mechanism to drive at all.
  Flagged as an explicit open follow-up decision (build a mechanism, or
  remove the dead fields), not silently marked "fixed."
- **Did** resolve that follow-up decision — REMOVED `blocks_per_60`/
  `penalties_per_60` entirely (reference doc §2l), rather than force-wiring a
  new mechanism. Checked, not assumed, before deciding which way to go:
  reading `engine.py`'s actual segment-generation code confirmed
  `special_teams`'s `committed_per_game` already drives PP/PK segment time —
  the exact quantity a `penalties_per_60` mechanism would need — so wiring it
  anywhere would have been a second signal for the same real-world quantity,
  double-counted against the first; block volume has the same shape, with no
  team-level rate input anywhere in the per-shot `block_rate_*` code path for
  `blocks_per_60` to legitimately join. Traced through the WHOLE chain, not
  just the two dataclass fields: `contracts.py`/`models.py` (the fields
  themselves), `player_props._team_rates()`, `loaders.build_team_features()`,
  `historical_truth/team_game_rates.py` (dropped `blocks_per_60` computation
  entirely — `parse_boxscore_sog_and_blocks` renamed `parse_boxscore_sog`),
  the producer script's CSV schema (backward-compatible: an old CSV with a
  leftover `blocks_per_60` column still loads, just ignored), and 3
  calibration scripts' inert `TeamRates(...)` fixture construction. The two
  "dead gate" reachability tests are replaced with regression tests
  asserting the fields are gone from `__dataclass_fields__`, guarding against
  either quietly coming back without a real consumer. **Checklist's
  `--- HockeyTeamFeatures ---` section is now EMPTY** — nothing left
  unreachable to report. 323 tests still pass (net count unchanged).
- **Did** build real player usage weights (`shot_weight`/`goal_weight`/
  `block_weight`, reference doc §2k, full report
  `docs/reports/hockeysim_player_weights_report.md`) — the checklist's LAST
  3 alarms, now a full PASS. UNLIKE the team-rates dead gate above, these
  were ALREADY reachable: `engine.py`'s `_weighted_choice` reads them
  directly with a documented position/TOI heuristic fallback (forwards get
  more shot-weight, defensemen more block-weight) that cannot differentiate
  a top-line sniper from a 4th-liner at the same position/TOI.
  `historical_truth/player_game_rates.py` parses the SAME boxscore cache's
  per-skater `sog`/`goals`/`blockedShots` (no new fetch) into per-game
  averages — 47,231 skater-game records, 828 players rated (>= 5 games
  floor). Real spread: N. MacKinnon, A. Matthews, J. Hughes, C. McDavid top
  `shot_weight` — real, well-known elite scorers, matching the external-
  validation pattern every per-team signal this session built has shown.
  Wired via `loaders.load_player_rates_map()` (the first per-PLAYER, not
  per-team, reader in this package) + `build_player_features`'s new
  `player_rates_map` parameter. **Reachability tested at the MECHANISM
  level** (population-reachability alone proves nothing new here, since it
  was already wired): 3 new `test_hockeysim_engine.py` tests hold TOI/
  position identical between two synthetic players and vary ONLY the field
  under test — `shot_weight`/`block_weight` (more events credited) and
  `goal_weight` with `shot_weight` held fixed (more goals per shot, the
  finishing-rate mechanism). All three pass.
  `scripts/nhl_sim_input_checklist.py`'s alarm count drops from 3 to **0** —
  a full PASS, the first time this session.
- Did not re-run the goal-multiplier calibration (§2d, earlier this session)
  with the joint-fit method the shot-multiplier bug discovery motivated —
  flagged as an open methodology-consistency gap, not a known error (its own
  verification was already reasonably tight).
- Did not build strength-state-specific per-team blocking (no data source
  distinguishes it — even the league-wide absolute calibration, §2h, could
  only fit ONE shared scale, not per-strength-state constants), or validate
  the vendor's original EV:PK:PP-def ratio itself (0.45:0.55:0.35, preserved
  through §2h's scale, never independently checked).
- **Did** investigate and fix the faceoff multiplier's mismatch with the
  per-team shot indices flagged above (reference doc §2m) —
  `_faceoff_multipliers` is gated `faceoff_ev_only=True` but was fed
  `TeamRates.faceoff_win_pct`, an ALL-SITUATIONS blend (PP/PK draws mixed
  into a mechanism that claims to exclude them). `historical_truth/faceoff_ev_index.py`
  parses `situationCode` per faceoff event (confirmed against a real cached
  game: `"1551"`=5v5 EV, `"1451"`/`"1541"`=PP for one side) to build a
  genuinely EV-specific per-team win-rate index. Faceoffs are zero-sum,
  which makes the index self-verifying: measured mean 1.00011 across 32
  teams (1,312 games, 58,762 EV faceoffs) — confirms correct normalization
  without needing an external sanity check. Real spread NYR (1.097x) to MIN
  (0.927x), ~18% top-to-bottom. **Verified the league-wide average did not
  shift**: 992-pairing round-robin, 61.786 neutral vs 62.079 real-indexed
  total shots/game — noise-level. **Found and fixed a real regression while
  wiring this**: a naive version made the index override
  `TeamRates.faceoff_win_pct` unconditionally, silently breaking that
  field's existing reachability whenever no index was supplied — caught
  immediately by the pre-existing `test_faceoff_win_pct_actually_changes_sog_projection`
  regressing, fixed with a raw (non-defaulted) per-side fallback so the
  index only overrides the blend when one is actually present.
- **Did** build zone-specific (offensive-zone) faceoff differentiation
  (reference doc §2n) — a refinement of the flat EV index above, not a
  separate mechanism: not every faceoff win is equally valuable. A win in a
  team's OWN offensive zone sets up an immediate shot chance; a win in
  their own defensive zone mostly just prevents one against them.
  Confirmed empirically that `zoneCode` is relative to the WINNER, not a
  fixed rink frame — two faceoffs at the identical `(xCoord, yCoord)`
  showed `zoneCode="O"` when home won and `"D"` when away won the same
  physical draw — so the loser's own zone is the mirror image (`O`↔`D`
  swap, `N` unchanged), letting every EV faceoff a team took (won OR lost)
  contribute to their own zone-relative counts, not just their wins.
  `compute_team_faceoff_oz_index` — same zero-sum-self-verifying ratio
  technique. Measured: 1,312 games, 38,120 OZ-attributed faceoffs, mean
  index 0.99973 across 32 teams; real spread NYR (1.101x) to FLA (0.907x),
  ~21% top-to-bottom — and notably a DIFFERENT ranking than the flat EV
  index (FLA mid-pack there, bottom-5 here), confirming this captures a
  distinct signal, not a rescaled duplicate. Wired via a three-tier
  fallback (`_resolve_faceoff_pct`): OZ index → EV index → all-situations
  blend, each tier used only when present, preserving every prior tier's
  reachability. **Verified the league-wide average did not shift**:
  992-pairing round-robin, 62.138 neutral vs 61.937 real-indexed total
  shots/game — noise-level. Reachability AND priority tested: a dedicated
  test sets OZ and EV to CONTRADICTORY values on the same side and confirms
  OZ wins, not just that one key happens to be checked first. Deliberately
  did NOT wire neutral-zone rates (the parser tracks all three, but no
  plausible consumption point exists for it distinct from the blended EV
  index) — defensive-zone rates, built next.
- **Did** build zone-specific (defensive-zone) faceoff differentiation
  (reference doc §2o) — closing the last piece of §2m's original gap
  analysis. NOT the OZ index's mirror image: a team's OZ and DZ win rates
  come from different, non-overlapping draws (a team can be elite at one
  and weak at the other). A team that wins its own DZ draws well both
  suppresses the OPPONENT's sustained shot generation from that zone-time
  AND can spring its own transition/rush chance — a dual effect, so this
  is wired as an ADDITIONAL multiplicative layer composed with the OZ/EV
  chain, not a fourth fallback tier of it. `compute_team_faceoff_dz_index`
  reuses the same `GameFaceoffZoneRecord`s the OZ pass already parses (no
  new fetch), reading `zone_wins["D"]` instead of `["O"]`. Measured: 1,312
  games, 38,120 DZ-attributed faceoffs, mean index 1.00063 across 32 teams;
  real spread OTT (1.100x) to STL (0.914x), ~20% top-to-bottom. **Confirmed
  genuinely independent of the OZ index, not its inverse**: measured
  Pearson correlation across all 32 teams = 0.69 — positive but far from
  1.0, proving DZ carries real information OZ doesn't already capture.
  **Deliberately gated on BOTH sides being present** (unlike the OZ/EV
  fallback chain, which falls back independently per side) since this is
  an additive layer with nothing to fall back to — a one-sided value would
  apply an asymmetric adjustment with no counterpart on the other side.
  **Verified the league-wide average did not shift**: 992-pairing
  round-robin, 61.940 neutral vs 61.934 real-indexed total shots/game —
  ~0.01%, essentially zero. Reachability AND gating tested: one test
  proves the index changes output; a second confirms a one-sided value
  (only HOME has it) is a near no-op.
- **Did** check neutral-zone faceoff calibration with a REAL measurement,
  not an assertion (reference doc §2p, full report
  `docs/reports/hockeysim_faceoff_nz_calibration_report.md`) — the prior
  entry's own "no plausible consumption point" line was a judgment call,
  not a measurement. `scripts/calibrate_nhl_faceoff_nz_index.py` checks
  directly whether a team's SEASON-AGGREGATE faceoff win rate, at ANY
  zone, correlates with their SEASON-AGGREGATE real `shots_per_60`.
  **Result: every correlation (NZ/OZ/DZ/EV) is under 0.02 in magnitude**
  — indistinguishable from zero, all 32 teams qualified. Does NOT prove
  the engine's segment-level mechanism is wrong (a real local effect could
  wash out in a season aggregate) — but DOES mean there's no basis to wire
  a new mechanism (NZ) on top of three (EV/OZ/DZ) that were never
  themselves checked against real aggregate shot data, only against their
  own internal normalization. `compute_team_faceoff_nz_index` is built and
  tested (5 unit tests) as real measurement infrastructure, but
  deliberately NOT added to the CSV producer, loader, or `engine.py` —
  publishing an unconsumed field would recreate the exact "populated but
  confirmed dead" anti-pattern already found and fixed once this session
  (`blocks_per_60`/`penalties_per_60`).
- **Did** build a segment-level faceoff validation (reference doc §2q, full
  report `docs/reports/hockeysim_faceoff_segment_validation_report.md`) —
  the check §2p's own season-aggregate null result explicitly left open,
  and it FLIPS the picture. `historical_truth/faceoff_segment_effect.py`
  counts real shots by the WINNING team vs the OTHER team in a window
  immediately after every real EV faceoff (1,312 games, 58,762 draws),
  truncated at the next draw so no shot double-counts. **Result, robust
  across 4 independent window sizes with the exact decay a real effect
  should show**: winner share 0.7935 (10s window, 3.84x shot-rate ratio)
  down to 0.6361 (30s window, 1.75x) — a large, real, LOCAL effect that
  decays smoothly toward parity as the window widens. **This is the single
  most important finding of the whole faceoff-zone track**: faceoffs DO
  matter for shot generation; §2p's null result was measuring the wrong
  TIMESCALE, not disproving the premise. **Stated with equal weight as the
  finding itself**: this does NOT validate the engine's CURRENT mechanism
  as-is — `_faceoff_multipliers` applies one uniform SEGMENT-WIDE
  multiplier from season-long win rate, not a discrete per-draw spike the
  way this measurement is, so directly recalibrating `faceoff_alpha` to
  match a ~2-4x per-draw ratio would be a category error (different kinds
  of quantities). A faithful model would need faceoffs as discrete,
  time-limited events with a real decay profile — a genuine engine
  redesign, not a calibration pass, explicitly out of scope this pass. 373
  hockeysim/nhl tests pass (13 new), checklist unaffected (nothing new
  added as a consumed field).
- **Did** build the discrete-event faceoff engine redesign §2q's own
  finding required (reference doc §2r, full report
  `docs/reports/hockeysim_faceoff_discrete_event_redesign_report.md`) —
  not just a sanity check, the actual mechanism change. First extended the
  measurement to the engine's real segment length: `scripts/build_nhl_faceoff_decay_curve.py`
  computes MARGINAL (non-overlapping) post-faceoff shot-rate buckets in one
  pass over the same 1,312-game cache, out to (60,90]s where the effect is
  fully converged (winner/other rates within 0.2%) — not extrapolated.
  `historical_truth/faceoff_decay_model.py::segment_average_multipliers`
  time-weight-averages this real curve over a segment's actual length, each
  bucket normalized to mean 1.0 (same invariant every per-team index this
  session built already uses). `engine.py`'s new
  `faceoff_discrete_event_model` flag (**default ON**, the one genuinely
  new flag this session's otherwise-flagless additive work introduced):
  simulates a discrete Bernoulli draw per EV segment from the SAME
  OZ→EV→blend percentages already resolved, applies the decay curve to
  winner/loser instead of one segment-wide constant. **Verified**: 17 unit
  tests on the pure curve function, 2 new reachability tests (flag changes
  output; a real per-team OZ edge still shows up under the NEW mechanism
  specifically), league-wide aggregate barely moved (992-pairing
  round-robin, 61.938 legacy vs 61.864 discrete-event, −0.12%), 392
  hockeysim/nhl tests pass with the new mechanism as default — including
  exact-seed determinism tests, despite the mechanism consuming an extra
  RNG draw per EV segment. **Stated plainly what this does NOT model**: not
  every engine segment corresponds to a real faceoff at its exact start
  (some real shifts begin off a line change); DZ's own segment-level effect
  was never separately measured, still uses the legacy diff-based math; PP/PK
  segments remain entirely untouched by any decay-curve logic.
- **Did** build the DZ-specific segment validation the item above left open
  (reference doc §2s, full report
  `docs/reports/hockeysim_faceoff_dz_segment_validation_report.md`) — and
  the result CONTRADICTS the mechanism's own justification. §2o's
  docstring claimed a dual effect (DZ win suppresses the opponent AND
  springs the winner's own transition chance), both predicting the winner
  out-shoots the loser, same direction as the general EV/OZ effect.
  Extended `faceoff_segment_effect.py` with a `winner_zone` filter
  (backward compatible, all 13 pre-existing tests unchanged) and measured
  directly: **DZ winner share sits BELOW 0.5 at every one of 4 window
  sizes tested (0.42-0.47, 19,458 real DZ draws)** — the team that wins its
  own defensive-zone draw is OUT-SHOT, not out-shooting, in the following
  seconds. **OZ-specific comparison confirms the technique rather than a
  method artifact**: winning your own OZ draw shows an EVEN STRONGER
  positive effect than the blended population (0.93 winner share at 10s,
  13.47x ratio) — exactly the expected direction, isolating DZ as the real
  anomaly. A coherent alternative explanation: a DZ draw happens because
  the puck was already in that zone; winning it doesn't instantly clear it,
  and the team that lost the draw is often still applying pressure moments
  later. **What this means for the shipped mechanism, stated carefully**:
  `faceoff_dz_index`'s WIRING DIRECTION (currently boosts the DZ-winning
  team's own shots) may be backwards relative to a faithful model — this is
  NOT a finding against the per-team index itself (still independently
  verified: real spread, correct normalization, genuine OZ independence at
  r=0.69), only against how it's composed into the engine. **Deliberately
  NOT fixed this pass**, matching the same measure-first discipline §2q→§2r
  followed. 4 new unit tests, 17 total in the segment-effect file.
- **Did** fix the DZ mechanism's wiring direction §2s recommended
  (reference doc §2t, full report
  `docs/reports/hockeysim_faceoff_dz_direction_fix_report.md`) — a narrow,
  targeted swap, not a mechanism redesign. `m_dz_h`/`m_dz_a` are computed
  exactly as before; only which team's shot lambda each is applied to
  changed: `lam_h *= m_dz_a`/`lam_a *= m_dz_h` (default), pulling the
  DZ-strong team's OWN shots down and the opponent's up, matching §2s's
  measured direction — the previous mapping (`lam_h *= m_dz_h`) is
  preserved behind `faceoff_dz_direction_fixed=False` for rollback/A-B, the
  same pattern §2r's `faceoff_discrete_event_model` already established.
  **The existing reachability test caught the change immediately**: failed
  on the first post-fix run with `strong=31.450 < weak=32.688` — the exact
  reversal intended — updated to assert the corrected direction, plus a new
  test confirming the flag itself gates the swap. **Verified**: league-wide
  aggregate barely moved (992-pairing round-robin, 62.230 legacy vs 62.106
  fixed, −0.199%, expected for a symmetric swap not a magnitude change);
  397 tests pass (up from 396); checklist re-confirmed full PASS. **Stated
  plainly what this does NOT do**: `faceoff_alpha`/`faceoff_diff_clip` are
  unchanged — only the direction of the DZ adjustment changed, not its
  size; a genuinely faithful DZ-specific discrete-event model (§2s's own
  segment data could fit one) remains a distinct, larger follow-up.
- **Did** build that DZ discrete-event model (reference doc §2u, full
  report `docs/reports/hockeysim_faceoff_dz_discrete_event_report.md`) —
  the SAME treatment §2r gave the general EV/OZ case, applied to DZ, not
  just another sign fix. `scripts/build_nhl_faceoff_decay_curve.py --winner-zone D`
  extends §2r's marginal-bucket technique to the 19,458 real DZ draws:
  0.24x at (0,5]s, briefly crossing back above 1.0x at (10,15]s (1.157x —
  reported as measured, not smoothed, given roughly a third the sample per
  bucket vs the general curve), settling at ~0.95x through 60-90s —
  **never fully reconverging to parity within the measured range**, unlike
  the general curve; tail buckets beyond 90s hold at the last measured
  bucket's own values rather than assumed parity.
  `segment_average_multipliers_dz` shares a refactored `_integrate_curve`
  helper with the general curve's own function (confirmed byte-identical
  output for the general curve after the refactor). `engine.py`'s DZ layer
  now has a 3-tier fallback: discrete-event (default, curve's own sign
  encodes the direction) → direction-fixed diff (§2t) → original diff, every
  prior rollback point preserved. **Verified**: 34 unit tests (17 new), 2
  new reachability tests (flag changes output; the measured direction still
  holds under the new default specifically), the existing
  `faceoff_dz_direction_fixed` test needed updating — not because it broke
  silently, but because its premise changed (that flag now only matters on
  the legacy fallback path) — 416 tests pass (up from 397); checklist
  re-confirmed full PASS; league-wide aggregate barely moved (992-pairing
  round-robin, 62.082 legacy-direction-fixed vs 62.196 discrete-event,
  +0.185%). This closes the faceoff-zone track's own stated next step.
- **Did** close a real precision mismatch the DZ redesign left in place
  (reference doc §2v, full report
  `docs/reports/hockeysim_faceoff_oz_discrete_event_report.md`):
  `_resolve_faceoff_pct` already prefers the OZ-specific index over the
  coarser EV-blend index (§2n), but the more precise signal still fed the
  general (EV+OZ+DZ-blended) decay curve. Built `segment_average_multipliers_oz`
  from the same 18,662-draw population the DZ report used as its confirming
  OZ control: raw ratio 119.7x at (0,5]s (the team that just lost a draw
  deep in the opponent's zone has almost no shots yet — real hockey sense,
  not measurement instability), decaying smoothly to full reconvergence by
  (60,90]s — a dramatically stronger, cleaner version of the general
  curve's own effect, since OZ draws are the purest case of the phenomenon
  the general curve dilutes with NZ/DZ. `engine.py` now chooses the
  OZ-specific curve as a single segment-level decision gated on BOTH sides
  carrying real `faceoff_oz_index` data (same bilateral discipline as DZ),
  via `faceoff_oz_specific_curve` (default ON). **Verified**: 51 unit tests
  (17 new), 2 new reachability tests (flag changes output when both sides
  have real data; confirmed a near no-op when only one does, proving the
  bilateral gate actually gates), league-wide aggregate barely moved
  (992-pairing round-robin, 62.127 general vs 62.284 OZ-specific, +0.253%),
  checklist re-confirmed full PASS.
- **Did** build a real xG (expected goals) model (reference doc §2i, full
  report `docs/reports/hockeysim_xg_model_report.md`) — the last genuinely-
  absent input this document tracked. `xgf_per_60`/`xga_per_60` had a reader
  (`load_team_xg_map`, already wired from a prior session) but no producer;
  neither existing truth source carries shot location, so this bulk-fetched
  the SEPARATE `play-by-play` endpoint (`NhlWebIngestClient.play_by_play()` +
  `scripts/fetch_nhl_playbyplay_cache.py`, 1,312 games, 1,307 new fetches, 0
  failures) and built a real `sklearn` logistic shot-quality model
  (`historical_truth/shot_xg_model.py`) on distance, angle, shot type,
  strength state, rebound, and empty-net features — fit on 112,888 Fenwick
  shot attempts (blocked shots excluded; their recorded coordinate is the
  block point, not the release point, the same convention every public NHL
  xG model uses). Deliberately did NOT include team identity as a feature, so
  the model can't overfit to a specific team and the full-data-fit model can
  safely score every shot for the team-level aggregation. **Holdout-validated**
  (262 games the model never trained on): AUC=0.7450 (in line with public
  models on a comparable feature set), Brier=0.0667 (beats the naive
  base-rate baseline), and a calibration table tracking closely across all 10
  deciles. **League-wide aggregate**: xGF/60=xGA/60=3.1826, within ~1.8% of
  the real, truth-calibrated `league_baseline_goals_per_60` (3.1269) already
  used elsewhere — the expected structural property of a well-fit logistic
  model. **Real per-team spread, external sanity check**: CAR (3.83)/COL
  (3.69) rate highest, CHI (2.73)/SEA (2.80) lowest — matches known 2025-26
  team strength. Stated plainly rather than hidden: `is_rebound` and the
  tip-in/deflected shot-type coefficients came out negative, the opposite
  sign hockey intuition predicts — a real, measured finding, flagged as an
  open question rather than adjusted to match a prior. Closes the checklist's
  alarm count from 9 to 7, the lowest measured this session.
- Did not turn on `elo_blend_weight` — measured that a naive win/loss Elo
  shows no edge over a constant baseline at the current `elo_home_adv`, and
  left the mechanism populated-but-off with that measurement recorded
  (reference doc §6), per the standard's mechanism-vs-estimator discipline.
- Did not truth-calibrate `calibration_profile.py`'s `SimConfig` (shot/goal
  dispersion, special-teams multipliers, faceoff knobs) — flagged in the
  correction (reference doc §2) as a distinct, still-open gap from the
  `ProjectionProfile` calibration that WAS already done.
- Did not wire `nhl_sim_input_checklist.py` into `/preflight` or
  `migration_gate.py` — built and verified standalone; gating integration is
  a follow-up.
- Did not fully trace NHL's per-service self-generation mechanism to a single
  definitive call site (reference doc §7) — traced it far enough to confirm
  production actually serves real data and to name the likely mechanism
  (`SYNDICATE_NHL_SOURCE_CLI_GENERATION`, defaults enabled), but stopped short
  of a file:line-exact trace once the "is this broken" question was answered
  (it is not).
- Did not deploy. All changes are local/committed-pending; `predictions_*.csv`'s
  self-generation means this sport's runtime behavior does not depend on a
  push deploy the way MLB's roster-artifact reuse trap does — but the elo/xG
  allowlist and `goals_per_60` fix still need a normal code deploy to reach
  Render like any other `.py` change.
- **Did** build a real market-comparison backtest (reference doc §8, full
  report `docs/reports/hockeysim_market_backtest_report.md`) — the instrument
  that answers "does this show an edge," distinct from every calibration
  above, which only checks aggregate-statistic match. `scripts/grade_nhl_predictions_vs_market.py`
  scores real published moneyline/total/puck-line predictions (real market
  odds already embedded on the same CSV row) against real settled outcomes
  (the same boxscore cache this session's work already bulk-fetched), using
  Brier score and `devig()`, mirroring MLB's `convergence-phase7-crps`
  methodology. Confirmed non-circular by reading `adapters.py` directly
  (`build_game_prediction` never touches `market_anchoring.py`, a genuinely
  separate code path). **Found a real bug in the process**: 4 of 5 local
  prediction files turned out to be byte-identical stale duplicates of an
  earlier date (confirmed with `diff`), which would have silently inflated
  the sample with non-independent observations — fixed with an explicit
  dedup, counted not dropped. Measured n=3–4 per market after dedup, market
  wins all three — but stated as plainly as every other finding this
  session: that sample is nowhere near powered enough to support a real
  verdict, and the run's value is proving the harness correct end-to-end on
  real data, not settling whether hockeysim has an edge.
- **Did** widen that backtest against real PRODUCTION data (reference doc
  §8b) rather than stopping at the thin local mirror — per CLAUDE.md's own
  standing rule to check production before concluding data is missing. Added
  `--source production`/`both`, pulling every date `/nhl/api/cards/dates`
  lists from `https://syndicate-an21.onrender.com` (a public route, no admin
  token), confirmed non-circular for this route specifically by reading its
  own payload fields (`source_path` points at the real `predictions_<date>.csv`
  on Render's disk). **Found a second real bug the same way as the first**:
  `lookahead_applied` does not mean live/circular adjustment as its name
  suggests — verified against every cached response, it means "requested
  date had no games, served the next date that does." An early draft
  rejected those rows outright, silently discarding real games mislabeled
  under the wrong date; fixed by keying on the RESOLVED date instead, which
  let the existing dedup collapse 13 redundant off-day requests. Sample grew
  from n=3–4 to n=14–15 (moneyline/total) across 12 dates instead of 4.
  Total flipped to "model beats market" on this larger sample — stated with
  equal weight to every caveat above, not less because n went up: this is
  evidence the harness holds up against a real production pull, not
  evidence of an edge on a still-far-from-powered sample.
- **Did** build the NZ discrete-event faceoff curve (reference doc §2w, full
  report `docs/reports/hockeysim_faceoff_nz_discrete_event_report.md`) —
  reversing an earlier decision (§2p) not to wire `faceoff_nz_index` at all,
  on the strength of real evidence rather than a change of mind. §2p's
  season-aggregate check found no correlation between NZ win rate and real
  shot generation; §2s later proved a season-aggregate null doesn't rule
  out a real segment-level effect (DZ's own season correlation was equally
  null, yet its segment effect was real, just backwards), so NZ's
  segment-level effect got the same direct check: winner share 0.7203 at
  10s decaying to 0.5945 at 30s (20,642 real draws), a real effect in the
  EXPECTED direction, unlike DZ. **A real correction caught before
  shipping**: an early docstring draft claimed the NZ curve was "stronger
  than the general curve's blend" from the marginal buckets alone;
  computing the actual time-weighted INTEGRAL both curves use (the real
  comparison) at 7 segment lengths showed the opposite — NZ sits BELOW the
  general curve at every length, because the general curve's early strength
  is disproportionately driven by the OZ-heavy portion of its pooled
  population. Wired end to end for the first time (CSV producer, loader,
  `engine.py`, as a third additional layer alongside DZ, same bilateral
  gate) with no legacy fallback, since this signal was never live before.
  Verified: 17 new unit tests (85 total in the decay-model file), 3 new
  reachability tests, 1 loader test, league-wide aggregate barely moved
  (61.795 off vs 61.774 on, −0.034%, 992-pairing round-robin), 456
  hockeysim/nhl tests pass, checklist re-confirmed full PASS. **This closes
  the faceoff-zone track's last open signal** — EV, OZ, DZ, and NZ all now
  have their own real, measured, discrete-event mechanism.
- **Did** build the strength-state (PP/PK) faceoff effect (reference doc §2x,
  full report `docs/reports/hockeysim_faceoff_strength_state_report.md`) —
  the first faceoff mechanism to fire OUTSIDE even strength, closing the
  population every zone-specific (EV/OZ/DZ/NZ) check this session ran had, by
  construction, never touched (`_extract_timed_events`'s default filter is
  `away_skaters == home_skaters`). Real, large, directionally sensible
  effect measured separately by role: PP-role winner share 0.9329 at 10s
  decaying to 0.8790 at 30s (8,033 draws — the already-advantaged team
  winning the draw compounds its edge); PK-role winner share 0.4313 at 10s
  decaying to 0.2749 at 30s (6,701 draws — even winning the draw
  shorthanded, the opponent's man advantage reasserts, and the curve's
  DIRECTION FLIPS as the window widens, unlike any other curve this session
  built). Neither curve reconverges within 90s, unlike the general/OZ/NZ
  curves — a real power play often runs that long.
  **A real bug found by the round-robin check every layer this session was
  held to, and fixed, not shipped**: the first wiring branched naively on
  each curve's own `winner_mult`/`other_mult`. Each curve is individually
  mean-1.0, but that only guarantees the SUM of the two sides' expected
  multipliers is 2, not that EACH side's own expectation is 1.0 — and since
  the PP-side's baseline lambda is already larger than the PK-side's
  (`pp_shots_mult > pk_shots_mult`) and PP-role's magnitude dwarfs PK-role's,
  this inflated the league-wide total by **+4.478%** in a 992-pairing
  round-robin, silently fighting the already truth-calibrated
  `pp_shot_cal_mult`/`pk_shot_cal_mult` baseline. A damping constant was
  considered and rejected — the bias scales linearly with damping strength
  through the origin, so no nonzero damping both keeps a real effect and
  removes the bias. Fixed instead with `_strength_state_multipliers`
  (`engine.py`, extracted as an independently testable pure function):
  computes each side's own expected multiplier PER SEGMENT at that
  segment's specific win probability, then divides the realized multiplier
  by that expectation, making `E[applied_mult] = 1.0` exactly for any win
  probability while leaving each curve's real, measured, asymmetric shape
  untouched. **Verified two ways**: analytically (a test confirms `E[]=1.0`
  to 6 decimal places at 5 win probabilities using the real curve values —
  a proof, not an approximation) and empirically (round-robin delta dropped
  from +4.478% to **+0.203%** after the fix). A separate test confirms the
  fix did not flatten the real effect into a no-op. **Stated limitation**:
  no dedicated per-team PP/PK-role-specific win-rate index exists — this
  reuses the general OZ→EV→blend signal as the best available
  approximation, not a role-specific index built this pass. Verified: 31
  new decay-curve unit tests (99 total), 7 new segment-effect unit tests
  (24 total), 3 new engine tests (reachability, the E[]=1.0 proof,
  shape-preservation), checklist and full suite re-confirmed unaffected (no
  new consumed field — reuses signals already wired elsewhere).
- **Did** close that same limitation: built a real per-team `faceoff_pp_role_index`/
  `faceoff_pk_role_index` (reference doc §2y, full report
  `docs/reports/hockeysim_faceoff_strength_state_role_index_report.md`). Same zero-sum
  winner/loser-attribution technique as the zone indices, split on the WINNER's own
  strength-state role instead of zone -- real, self-verifying (mean index ~1.0002 on both),
  disjoint populations (a team can rank very differently on PP-role vs PK-role -- PHI bottom-5
  PP-role, top-5 PK-role), ~30-45% top-to-bottom spread. `_resolve_strength_state_faceoff_pct`
  sits one tier ahead of the existing OZ->EV->blend chain, preferring each side's own
  role-matching index when present, falling through unchanged otherwise -- no new `SimConfig`
  flag, since this refines an existing consumption point. **A real trap caught in this piece's
  own first reachability-test draft**: home/away-symmetric role-index magnitudes produced an
  EXACTLY identical mean output whether the index was present or absent (62.500 == 62.500 to 3
  decimals) -- not a wiring bug, but a fixture flaw: matched magnitudes put the win probability
  back at exactly 0.5 in both configurations by construction. Rebuilt asymmetric, which DID move
  the mean but by less than a coarse 120-seed comparison could reliably distinguish from noise --
  an expected consequence of the strength-state mechanism's own exact-normalization design
  (`E[applied_mult]=1.0` for ANY win probability), not a bug. Final reachability test compares
  exact per-seed total-shot vectors instead, a noise-free proof. Verified: 15 new parser/index
  unit tests, 1 new loader test, 6 new engine tests, 519 hockeysim/nhl tests pass overall (up
  from 497), checklist full PASS with both new keys AST-derived. **Round-robin**: -0.131% (992
  pairings, real production data), noise-level, consistent with the mean-invariance property
  above.
- **Did** close the strength-state report's own "What this does NOT do" gap: built a joint
  role-and-zone refinement (reference doc §2z, full report
  `docs/reports/hockeysim_faceoff_strength_zone_joint_report.md`). NZ/DZ/OZ draws happening DURING
  a PP/PK segment were not separately modeled, only role. A joint (role, zone) segment check found a
  real, large, DIRECTLY consistent effect (PP-role+DZ, a rare 3.7% tail, dramatically LESS
  favorable than the PP-role average; PK-role+OZ, a rarer 2.9% tail, dramatically MORE favorable
  than the PK-role average) — matching the general OZ>NZ>DZ ordering the even-strength curves
  already established. **Measured before building, matching the NZ precedent**: a per-team joint
  index checked and confirmed infeasible for 4 of 6 cells (PK+O: 197 draws leaguewide, median
  6/team across a WHOLE SEASON) — population-level only, a real stated limitation. Five of six
  cells got their own dedicated discrete-event curve; PK+O falls back to the flat PK-role curve, a
  real, stated, data-driven floor. `_strength_state_zone_multipliers` (`engine.py`) reuses
  `_strength_state_multipliers`'s exact-normalization structure without re-deriving it from
  scratch — only the denominator changes, to the zone-marginalized expectation
  (`expected_multipliers_strength_zone`); the numerator uses the specific zone drawn. Verified
  analytically (`E[]=1.0` to 4 decimal places at 5 win probabilities) and empirically (round-robin
  delta **-0.055%**, 992 pairings, real production data — noise-level). 27 new unit tests (182
  total in the decay-model file), 4 new engine tests, 605 hockeysim/nhl tests pass overall (up
  from 519), checklist full PASS (no new consumed field — population-level constants, not a new
  per-team CSV column).
- **Did** build the first PLAYER-level faceoff signal (reference doc §2zz, full report
  `docs/reports/hockeysim_player_faceoff_rate_report.md`). Every faceoff mechanism above operates
  on TEAM-level rates only. Real per-player win rate from `playbyplay`'s `winningPlayerId`/
  `losingPlayerId` (Claude Giroux 0.6308/799 draws, Jonathan Toews 0.6209/1026 draws, ~0.30 weak,
  league average 0.4867, 238 players at a 100-real-draw floor). **A real data trap caught before
  building on it**: the boxscore's own `faceoffWinningPctg` field looked usable, but 22% of real
  center-games show an EXACT 0.0/1.0 (low-draw games) — a naive average-of-per-game-rates put real
  active centers at a literal 0.0000 across 68-82 games. Fixed with TRUE win/total counts, never an
  average of ratios. **A reachability bug caught before shipping**: a first draft overrode
  `TeamRates.faceoff_win_pct` directly — completely dead weight, since that's the BOTTOM fallback
  tier, behind the already-100%-populated OZ/EV/role indices. Fixed by composing it as an
  ADDITIONAL multiplicative layer instead (`faceoff_lineup_model`), the same pattern DZ/NZ use,
  gated `ev_only` only (strength-state extension a real, stated next step). Verified: 31 new unit
  tests, checklist shows `faceoff_lineup_pct` 100% populated against the REAL local mirror (genuine
  end-to-end reachability), 634 hockeysim/nhl tests pass overall (up from 605). Round-robin:
  **-0.112%** (real per-team lineup data), noise-level; a no-data control confirmed an EXACT 0.000%
  delta, proving the bilateral gate correctly no-ops.
- **Did** extend the lineup-aware faceoff layer to strength-state (PP/PK) segments, closing the
  above item's own stated next step, same day (reference doc §2zz addendum, report addendum in
  `docs/reports/hockeysim_player_faceoff_rate_report.md`). `faceoff_lineup_model_strength_state`
  (default ON) applies the SAME `faceoff_lineup_pct` raw values as an INDEPENDENT additional layer
  composed after the strength-state mechanism's own multipliers -- not a tier in
  `_resolve_strength_state_faceoff_pct`'s chain. Kept deliberately INDEPENDENT of
  `faceoff_lineup_model` (the EV-only switch), not umbrella-gated under it, so each layer can be
  A/B'd or rolled back separately -- a dedicated test confirms the two flags stay independent.
  Verified: 3 new engine tests (reachability via per-seed vectors, direction, independence),
  checklist full PASS (no new consumed field). Round-robin: **-0.138%** (992 pairings, real
  per-team lineup data), noise-level.
