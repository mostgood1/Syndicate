# FINDINGS — WNBA prop ladder width: measured, fitted out of sample, wired behind a flag (fix #1)

**Lane** `wnba-prop-dispersion`, session `39b666bb`. **Date** 2026-10-03. **No deploy; flag default OFF.**
Follows `findings_2026-10-02_wnba_lines_props_backtest.md` §7 fix #1. Substrate: the as-of re-run of fleet code
`9a7f0d2f` (340 games, 500 sims) — evidence about the CODE, not the deployment — scored against ESPN box scores and
the OddsAPI historical book (tip −60 min).

## 0. Headline

1. **A per-market width factor fitted on May–July improves every priced market except threes out of sample**, at the
   book line AND across the whole ladder, Aug–Sep and playoffs both, CIs excluding 0. Points held-out Brier
   −0.0181 [−0.0214, −0.0151]; PRA −0.0372 [−0.0429, −0.0314].
2. **It does not reach the book.** Points stays +0.035 worse than the de-vigged book (it closes ~1/3 of the gap).
3. **The reason it cannot, measured:** at the book's own line the sim has **no discrimination** for points, rebounds
   or PRA — the observed over-rate is flat (0.42–0.57) across every predicted decile, from P = 0.08 to P = 0.64.
   Widening removes overconfidence; it cannot add information. Threes is the only market with a slope (0.40 → 0.58).
4. **Wired** into the engine at one Syndicate-owned choke point, WNBA-only, OFF unless `SYNDICATE_WNBA_PROP_DISPERSION`
   is set. Reachability proven through the real engine and the board's reader.

## 1. The fit (`scripts/fit_wnba_prop_dispersion.py`)

Estimator, exactly as the engine applies it: `v' = max(0, round_half_up(mu + k (v − mu)))` per simulated value, one k
per market; P(over) read the board's way, P(v' ≥ floor(line)+1). Train = regular season before 2026-08-01; test =
regular season on/after it, and playoffs, separately. 5,233 player-games per market.

| market | k (ladder fit) | measured resid sd / sim sd | held-out Brier k=1 → k | d vs k=1 [95% CI] | d vs book after [CI] | playoffs d vs k=1 [CI] |
|---|---|---|---|---|---|---|
| points | **1.35** | 1.39 | 0.3019 → 0.2838 | **−0.0181 [−0.0214, −0.0151]** | +0.0349 [+0.0231, +0.0474] | −0.0154 [−0.0239, −0.0084] |
| rebounds | **1.25** | 1.41 | 0.2923 → 0.2861 | **−0.0063 [−0.0083, −0.0044]** | +0.0411 | −0.0041 [−0.0085, −0.0000] |
| assists | **1.25** | 1.45 | 0.2941 → 0.2885 | **−0.0057 [−0.0079, −0.0037]** | +0.0413 | −0.0062 [−0.0096, −0.0029] |
| threes | 1.15 | 1.23 | 0.2517 → 0.2517 | +0.0000 [0, 0] | +0.0091 [−0.0022, +0.0201] | 0 |
| PRA | **1.60** | 1.58 | 0.3400 → 0.3029 | **−0.0372 [−0.0429, −0.0314]** | +0.0539 | −0.0297 [−0.0386, −0.0222] |
| PR | **1.50** | — | 0.3212 → 0.2923 | **−0.0289 [−0.0333, −0.0242]** | +0.0426 | −0.0193 [−0.0230, −0.0155] |
| PA | **1.40** | — | 0.3138 → 0.2903 | **−0.0235 [−0.0282, −0.0192]** | +0.0408 | −0.0271 [−0.0361, −0.0188] |
| RA | **1.30** | — | 0.3019 → 0.2853 | **−0.0166 [−0.0209, −0.0128]** | +0.0362 | −0.0115 [−0.0214, −0.0026] |

Whole-ladder ranked probability score improves on every market but threes (points −0.031 [−0.050, −0.013], PRA
−0.149 [−0.188, −0.112]). The widened sim sd matches the realised residual sd (points 5.73 vs 5.93, PRA 7.73 vs
7.66). Mean shift from rounding and the clip at 0: +0.01..+0.13. **Every fitted k is interior to the 0.80–4.00 grid.**

**Threes is inert, and the fit already knew it.** With small integer counts, k = 1.15 rounds back to the same
values unless a draw is > ~3.3 from the mean; the re-run shows a threes ladder-sd ratio of 1.00 with the flag on.

## 2. Two wrong turns, kept because they look right

- **A book-line log-loss fit runs to the top of any grid** (k ≥ 2.4 on a 0.8–2.6 grid; k = 4.0 on 0.8–4.0, even
  re-centred on the player's own average). Book lines sit at the median, so flattening every P(over) toward 0.5
  keeps improving the loss at that line. At k = 4, re-centred, the ladder is uninformative and reaches **parity** with
  the book (PR −0.0005 [−0.0044, +0.0035]) — which says widening cannot create an edge at the book's own line, NOT
  that the right width is 4. Width must be fitted line-agnostically.
- **My first ranked probability score divided by the number of thresholds**, which rewards a wider ladder for having
  more of them; every "ladder" fit then ran to the grid edge too. Fixed to the standard unnormalised sum; the
  regression test (`test_rps_does_not_reward_width_for_its_own_sake`) fails on the old formula.

## 3. The engine change

- NEW `syndicate/features/shared/wnba_prop_dispersion.py`: loads `wnba_prop_dispersion.json` from the WNBA
  processed root, rebuilds each player's ladders (and `prop_distributions`) from widened values with the vendor's own
  `build_exact_ladder_payload`, stamps `prop_dispersion` on the row and the result. Missing/unreadable/out-of-bounds
  (k ∉ [0.5, 3.0]) factor file → ladders untouched and a NAMED reason (`PROP_DISPERSION skipped reason=...`), never a
  silent neutral default. Never raises. `*_mean`/`*_sd` fields are NOT changed (the board does not read them for P).
- ONE hook in `basketball_props_smart_sim.py`, right after `_attach_sim_distributions_local` (so PR/PA/RA are
  widened too); a Syndicate-owned file, so a vendor re-pull cannot revert it.
- Factor file (produced by `fit_wnba_prop_dispersion.py --write-artifact`, `ladder` fit only, edge-k markets left out):
  `{"pts": 1.35, "reb": 1.25, "ast": 1.25, "threes": 1.15, "pra": 1.6, "pr": 1.5, "pa": 1.4, "ra": 1.3}`.

**Reachability, through the real engine** (one-date re-run 2026-07-20, 4 games, 200 sims, factor file present in
both arms, only the flag differs): flag OFF → ladder-sd / sim-sd 1.00 on every market, 0 files stamped, no log line;
flag ON → `PROP_DISPERSION applied players=22 ladders=176` per game, points 1.30, rebounds 1.20, assists 1.15, PRA
1.57, threes 1.00. **Through the board's input and reader:** production's own `_build_cards_sim_detail_from_local_smart_sim`
over the same files → 88/88 rows stamped, points sd ratio 1.30, and `wnba_projections._hit_prob_over` at mean+8.5
**0.034 → 0.069**. Tests: `tests/test_wnba_prop_dispersion.py` 10 pass; `tests/test_fit_wnba_prop_dispersion.py` 8
pass; 59 existing SmartSim / distributions / projections tests pass.

## 4. NOT done, needs a user decision

1. **Allowlist** `wnba_source/data/processed/wnba_prop_dispersion.json` in `EXPORT_ONLY_ARTIFACT_PATTERNS`
   (`artifact_publisher.py`, claimed by OPEN lane `nhl-live-resim` → a cross-lane write). Required by the engine
   standard §3 before the input is relied on.
2. **Place the factor file** on the fleet disk (`~/syndicate-prod/data/wnba_source/data/processed/`).
3. **Set the flag** on the worker(s) that run the WNBA props SmartSim, and fast-forward the fleet to the commit.

## 5. What this does and does not buy

It makes the published ladder honest about its uncertainty: alt lines and the live line grid read a calibrated
width, and per-line edges stop being inflated by overconfident P(over) (at mean+8.5 the tail probability doubles). It
does **not** make the prop board beat the book — that needs the mean (fix #2 minutes: bias −2.96 min/player; fix #3
rates), and the sim currently has no discrimination at the book line. Re-fit k AFTER fixes #2/#3 (mechanism vs
estimator, standard §4.4): a better mean leaves less residual for the width to absorb.

---

## 6. RE-FIT ON THE NEW STACK (fix #2 availability + fix #3 rate shrink), 2026-10-03 — supersedes the k values above

User decision: "hold it, re-fit fix #1 on the new stack". The stack's ladders were built by applying fix #3's engine
module (post-sim, deterministic; reproduced 316/316 by a real-engine re-run) to the availability-on re-run of all 116
dates (339 of 340 games shifted; the season opener has no player with 3 prior games). Same split, grid and
whole-ladder objective as section 1.

| market | k (old → stack) | held-out d Brier vs k=1 [95% CI] | stack Brier: widened / book / own-avg normal | playoffs d vs k=1 |
|---|---|---|---|---|
| points | 1.35 → **1.25** | −0.0017 [−0.0029, −0.0004] | 0.2608 / 0.2489 / 0.2590 | −0.0034 [−0.0087, +0.0020] |
| rebounds | 1.25 → **1.30** | −0.0004 [−0.0012, +0.0003] | 0.2524 / 0.2446 / 0.2494 | **+0.0029 [+0.0010, +0.0052]** |
| assists | 1.25 → 1.20 | 0 (rounding-inert) | 0.2556 / 0.2478 / 0.2511 | — |
| threes | 1.15 → 1.15 | 0 (rounding-inert) | 0.2524 / 0.2431 / 0.2466 | 0 |
| PRA | 1.60 → **1.40** | −0.0080 [−0.0108, −0.0053] | 0.2634 / 0.2492 / 0.2608 | −0.0131 [−0.0225, −0.0043] |
| PR | 1.50 → 1.35 | −0.0051 [−0.0074, −0.0027] | 0.2617 / 0.2498 / 0.2615 | |
| PA | 1.40 → 1.30 | −0.0047 [−0.0068, −0.0026] | 0.2600 / 0.2495 / 0.2562 | |
| RA | 1.30 → 1.40 | −0.0040 [−0.0070, −0.0013] | 0.2552 / 0.2493 / 0.2514 | |

**What changed.** With the mean fixed, widening buys ~10x less (points −0.0017 vs −0.0181 before): most of what the
first fit's widening was doing was compensating for a biased mean. The factors are smaller for points and combos and
all interior. Widening is still worth having on points and the combos (held-out gains, CIs < 0); on rebounds,
assists and threes it is ~nothing, and on rebounds it slightly HURTS in the playoffs.

**What did not change, and is now the main finding.** At the book's line, points and PRA still have NO discrimination:
observed over-rate 0.38–0.55 across every predicted decile (points P from 0.29 to 0.62). Rebounds and threes do show a
slope (rebounds 0.43 → 0.63 across deciles). For rebounds/assists/threes the player's own average with the player's
own spread (a normal) prices the book line better than the sim ladder (rebounds 0.2494 vs 0.2524) -- so for those
markets the ladder's SHAPE, not its width, is the remaining defect. Every market is still behind the book
(+0.006..+0.014).

**Factor file for the stack:** `{"pts": 1.25, "reb": 1.3, "ast": 1.2, "threes": 1.15, "pra": 1.4, "pr": 1.35, "pa": 1.3, "ra": 1.4}`
(`C:/tmp/wnba_bt/dispersion_stack/wnba_prop_dispersion.json`). Recommendation if enabled: ship points and the four
combos; leave rebounds/assists/threes OUT of the file (the engine then leaves those ladders untouched) -- that choice
reads the held-out/playoff numbers, so it is stated as a recommendation for the user, not as a fit.
