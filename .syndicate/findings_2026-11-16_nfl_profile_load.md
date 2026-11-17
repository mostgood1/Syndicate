# NFL profile load: #808's held-out candidate as `data/calibration/nfl_profile.json` — 2026-11-16..17 (lane `nfl-profile-load`, todo #808)

User "load the NFL profile after the MNF check" (2026-11-16). This follows the #808 end-of-half code (on main
`38e237e6d..5ddfdd86e`, every switch OFF) and the live timeouts consumer (`6f7cb9eb3`).

## What "the profile load" is, read before any change

- **A file, not code.** `calibration_profile.NFL_CALIBRATION_PROFILE` is `load_versioned_profile(...)` on
  `calibration_profile_path("nfl")`. That path is `<checkout>/data/calibration/nfl_profile.json` unless
  `SYNDICATE_CALIBRATION_PROFILE_DIR` or `SYNDICATE_CALIBRATION_PROFILE_PATH_NFL` is set. Neither is set on any fleet
  role (read 2026-11-16 2:20 PM CST from `render_env/<role>.json` and `local_production.env`, key names only).
  So the file reaches the fleet by an ff of `~/Syndicate`, the same way NCAAF's did
  (`state_football.md [ncaaf-calibration-profile-live]`).
- **Resolved at import.** A fresh process picks it up. The NFL projections are a fresh subprocess per run
  (`generate_smartsim2_nfl_projections.py`, relaunched when the week's artifact is a day old or missing). The NFL
  live re-sim runs IN-PROCESS in refresh-worker (`SYNDICATE_NFL_LIVE_RESIM=1` there): it keeps the profile it
  imported at boot until refresh-worker restarts.
- **The fleet before:** no `data/calibration/nfl_profile.json` (only NCAAF's); a fresh process under
  refresh-worker's environ reads `source=default`, all seven switches False, `home_field_bonus` 0.0,
  `touchdown_weight_multiplier` 1.0 (read 20:21:06Z).
- **The loader drops unknown keys silently** (`profile_with_overrides`) and degrades to the default on any read
  error. A typo would ship the default for that field with no error anywhere, hence the test below.

## The file

`data/calibration/nfl_profile.json`, version `nfl-808-v3h0.03-t0.825`. It sets nine fields (plus `name`
"nfl", which picks the NFL clock / fourth-down tables): `halftime_kickoff`, `q2_urgency_ignores_score`,
`end_of_half_clock`, `end_of_half_kneel_out`, `end_of_half_clock_by_need`, `q4_kick_waits`, `kneel_out_q4_only`
all true; `home_field_bonus` 0.03; `touchdown_weight_multiplier` 0.825. Every other field stays at the
in-source default, as in the held-out read. `fit_from` carries the provenance.

## It is the held-out candidate, seed for seed

The held-out harness (`C:\tmp\football_eoh_fix\fit.py`, production's `build_projection` on the private 2026 root),
PYTHONHASHSEED=0, 3 held-out games (`2026_01_BAL_IND`, `2026_04_NE_BUF`, `2026_08_TEN_CIN`) x 100 seeds:

| run | profile resolved | per-seed finals |
|---|---|---|
| the file, no overrides | `source=artifact`, hfb 0.03, TD 0.825, clock on | equal to the held-out candidate arm's first 100 seeds, 3 of 3 games |
| default + the nine fields as overrides (the held-out way) | `source=default` + overrides | equal to the file's, 3 of 3 |
| default, no overrides (production today) | `source=default` | equal to the held-out `off` arm's first 100 seeds, 3 of 3; differs from the file's |

## Tests

- **`tests/test_nfl_calibration_profile_artifact.py` (new)** pins that the file loads to exactly the nine fields and names no unknown key. The loader drops unknown keys silently, so this test is the only guard against a typo shipping the default.
- **With the file present, 10 existing tests failed, and 0 without it.** None was a defect: each assumed production's NFL profile IS the in-source default. Two examples:
  - the live re-sim's `rating_sd` fixture landed in the uninformative band at p = 0.635;
  - one test held that seeds 1-60 contain no overtime, though OT is reached 13 times in 600.
- **Fixed in 7 files,** each now naming the in-source default where that is what it meant. One file was on LOAN from `football-scenario-calibration` (user "Loan it"). The edited files pass both with the file and with it moved aside.

## Load

Full entry: deploys.md 2026-11-17 15:25:08Z.

- **Push.** `f5be2b5e2` (the file), `ae673e5bd` and `0111eae90` (test names) landed on main `f571a8ffa..0111eae90` at 10:13 PM CST 11-16. That was right after the Q4 two-minute timeouts check: MNF LAC @ BAL, 04:11:40Z, keys on 87 of 87 live reads, 0 mismatch.
- **The ff answer came 11 h later.** The user answered at ~9:15 AM CST 11-17 ("Ff now, let them ride"). By then:
  - the first claim and preflight (04:14Z, CLEAR) had expired;
  - the MNF final (04:25Z) had passed;
  - week 11 had already built on the DEFAULT profile: launched 04:34:19Z (`artifact_is_preseason_backfill`), files at 04:35:18Z.
- **Fleet ff `d7c183d8d` -> `17ff69398` at 15:25:08.591Z.** The ride-alongs (59 commits, listed before the merge):
  - lane `nfl-live-possession-map`'s #813 possession map `9049537d1` and timeouts adapter `17ff69398` (user "land ... with it too");
  - #814's `884a2928a` / `f668eb6b9`, default ON (user "let them ride");
  - the rest default OFF or tooling.
- **A fresh process under refresh-worker's environ** read `source=artifact version=nfl-808-v3h0.03-t0.825`, with the nine fields, at 15:25:33Z.
- **The refresh-worker restart:** drained, claimed, TERM 15:47:38.540Z. New pid 4027303 at 15:47:46.588Z (the in-process live re-sim). Betting-change register BC-022, so the scale-up clock restarts at 15:47:46Z.
- **Week 11 rebuilt on the profile,** on the user's "Rebuild now" (rather than waiting for the next daily launch at ~04:35Z 11-18).
  - The run: the autorun's own command, `generate_smartsim2_nfl_projections.py --season 2026 --week 11`, under refresh-worker's environ, nice 19, 16:12:37Z-16:17:31Z (289 s; the worker's 04:34Z run took 59.7 s).
  - The output: same inputs (13 games, `pbp_rows=0`, 0 injury adjustments). CSV 16:17:28Z, sidecar 16:17:30Z.
  - **The quarter shape moved the way #808 predicts** (13 games, mean points per game, the 04:35Z default write -> the profile write):

    | segment | default | profile | league (#808) |
    |---|---|---|---|
    | q1 | 9.19 | 8.71 | |
    | q2 | 12.90 | **14.11** | 14.02 |
    | q3 | 10.71 | **9.23** | 9.50 |
    | q4 | 13.02 | 13.11 | |
    | full | 45.97 | 45.27 | |

    - q2 share 0.281 -> 0.312; q3 share 0.233 -> 0.204.
    - CSV `total_mean` -0.69 on average (max 3.43); `margin_mean` -0.47; `home_win_rate` -0.006.
    - OT sims 96 -> 70 (of 3,900).
  - **No profile stamp in the output.** The CSV's `profile_name` reads `nfl_v1` both times: it is the engine's name, not the file's version. The evidence is the fresh-process read plus this shape.
  - **The manual run is not in the sim-run ledger,** which the autorun writes at launch. The artifact's new age moves the worker's next NFL launch to ~16:17Z 11-18, still before TNF.
  - Copies of the before and after files: `C:	mp
fl_live_timeouts\wk11_before\` and `wk11_after\`; the comparison is `npl_wk11_cmp.py`.

## Owed

- **TNF 11-19 (IND @ HOU), the first live NFL game on the profile.** Read:
  - `timeouts_fed` True on in-progress lanes, and the fed values against ESPN's;
  - `possession_marginalised` False (#813);
  - refusals by reason.
  Watcher `npl_tnf_watch.py` is armed.
- **The #752 segment re-grade on weeks 11-13,** pre-registered (`findings_2026-11-16_nfl_segment_regrade_808.md`). It runs Tue 12-08 10:00 AM CST. Its condition (d) needs each week's sidecar written after 15:25:08Z; week 11's was, at 16:17:30Z.
