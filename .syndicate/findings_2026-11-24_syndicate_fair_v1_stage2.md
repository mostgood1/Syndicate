# Syndicate Fair v1 — STAGE-2 forward read `[2026-11-24, lane syndicate-fair-v1, todo #737, OFFLINE, read-only]`

The registered stage-2 read of pre-registration `be3fcf23` §11 plus amendment A1 `7786ab1e`. Stage 1:
`.syndicate/findings_2026-10-26_syndicate_fair_v1.md`. Stage 1 and stage 2 are read separately and never pooled.
Run by the scheduled task `syndicate-fair-v1-stage2-read-1124`. The lane's own session is archived, so this run is
the reader. All times are US Central (CST).

| | |
|---|---|
| **Banner** | `REGISTERED STAGE-2 READ`; report `registered_read: true` (not PREVIEW), window `[2026-10-26T08:00Z, 2026-11-23T08:00Z)` = kickoffs from 3:00 AM CDT 10-26 to 2:00 AM CST 11-23 |
| **Code** | driver `scripts/syndicate_fair_stage2.py` (`21306271`) from a worktree at origin/main `e7b0c09b`. **Pins held on both hosts:** `syndicate_fair_fit.py` `acdc917bd435`, `syndicate_fair.py` `17bb127f636b`. No `--allow-unpinned`, no `--window`. |
| **Substrate** | fleet data root `/home/amyn/syndicate-prod/data` `book_quotes`, extracted on the fleet at `nice 19 / ionice idle`, 9:32–9:41 AM (rc 0). Outcomes: the fleet web's `game-chips` GET for 10-26..11-23 (rc 0). The read ran on Windows at Idle priority, 9:45–~10:57 AM; it reached its final `return 0` lines with an empty stderr. The `Start-Process` wrapper's ExitCode came back empty, so the rc comes from the log, not the wrapper. **No OddsAPI call; nothing published; no fleet change.** |
| **Data ends** | latest commence in the data 7:42 PM CST 11-22. The window's last 6 h have no game, so no end-of-data warning. |
| **Scratch** | `C:\tmp\sfv1_stage2\` (extract, chips, `stage2.json`, `read.log`, `summary.txt`), not in git |

## Verdict in one paragraph

**Arm A, the gate: 8 of 13 families PASS.**
- PASS: NBA game, NCAAF game, NFL game, NHL game, soccer game.
- PASS (outcome unmeasured): NBA props, NFL props, NHL props.
- **FAIL:** NCAAF props.
- **UNDERPOWERED:** MLB game and props (3 games), WNBA game and props (3 games, never trained).
- **Arm B (A1's lower ridge) gives the same verdict in every family.** There is no B-only pass, so there is no lead. Every arm-A pass also clears the Bonferroni 1 − 0.05/13 interval.
- **No family trips G2's harm guard.**

**But most of the gain is mechanical.** Pinnacle is now on NBA, NFL and soccer game lines (it was absent before 10-25), and the fit leans on it to predict its own close.
- **Against the consensus close** (the non-mechanical split, prereg §8), v1 is better than the Shin median in only three families, all small: NCAAF game, NBA props and NHL game.
- v1 is **worse** in NBA game, NFL props and NHL props.
- Soccer's stage-1 non-mechanical gain **did not replicate**: −0.64 [−1.67, +0.40].
- **In absolute pp, v1 is again further from the close than Shin** in NCAAF, NFL and NHL game lines.

**Recommendation:** keep `σ_fair_v1` in shadow and extend its basis to the newly passing families, with NBA props and NHL game marked σ-uncalibrated. **Do not use `p_fair_v1` for EV, pricing or staking.** The standing user rule of 2026-10-26 stands, and this read gives no evidence against it (§6).

## 1. Coverage: what the read rests on (the window's rows only, fleet data)

Rows = line × snapshot. "games / dates" are held-out games and test dates in the window.

| family | rows | games | dates | sharp-close rows | consensus-close rows | outcome rows | dates with sharp ∩ outcome |
|---|---|---|---|---|---|---|---|
| mlb·postseason·game | 403 | 3 | 3 | 129 | 270 | 38 | 3 |
| mlb·postseason·prop | 1,082 | 3 | 3 | 0 | 1,070 | 0 | 0 |
| **nba·regular·game** | 171,298 | 205 | 28 | 45,728 | 124,219 | 5,028 | 27 |
| **nba·regular·prop** | 102,702 | 205 | 28 | 26,682 | 74,388 | 0 | 0 |
| ncaaf·regular·game | 16,609 | 256 | 22 | 4,030 | 12,198 | 7,464 | 22 |
| ncaaf·regular·prop | 9,861 | 181 | 22 | 0 | 8,558 | 0 | 0 |
| nfl·regular·game | 4,330 | 56 | 16 | 787 | 3,488 | 1,543 | 16 |
| nfl·regular·prop | 16,707 | 56 | 16 | 7,209 | 8,642 | 0 | 0 |
| nhl·regular·game | 2,949 | 193 | 29 | 0 | 2,899 | 2,765 | 0 |
| nhl·regular·prop | 41,564 | 193 | 29 | 24,236 | 16,970 | 0 | 0 |
| soccer·regular·game | 16,530 | 382 | 18 | 7,651 | 8,727 | 4,882 | 17 |
| wnba·postseason·game | 1,298 | 3 | 3 | 259 | 1,018 | 93 | 3 |
| wnba·postseason·prop | 1,083 | 3 | 3 | 0 | 803 | 0 | 0 |

Preseason families have 0 rows in the window.

- **This is the first NBA regular-season read.** The first NBA test date is 10-26, trained on 5 dates and 31 games.
- **Soccer has no test date from 11-09 to 11-19.** This is plausibly the November international break; I did not check it.
- **The sharp target is now material for NBA, NFL and soccer.** It covers 27–47% of those rows, against < 3% at stage 1.
- **Outcome coverage thins after ~11-08.** Final chips fall from ~300 a day to 156–268 a day (soccer chips left `pregame`, the stage-1 caveat). G2 rests on 203 / 245 / 56 / 183 / 238 games (NBA / NCAAF / NFL / NHL / soccer).
- Assembly drops: `rows_under_min_books` (< 2 books) is the largest population cut everywhere. NBA lost 729k candidate rows and kept 324k. The baseline parity re-check inside `assemble_sport` counted 10,854 rows across the sports, and the assembly counters show no mismatch key.

## 2. The gate table: arm A (registered). Units are 10⁻⁵ nats per row; lower is better

Δ = CE(v1) − CE(Shin consensus) against the close target. The CIs come from 2,000 game-clustered bootstrap resamples.

| family | verdict | held-out rows / games / dates | Δ close [95% CI] | Bonferroni CI | equal-weight pool Δ | Δ outcome [95% CI] (rows / games) |
|---|---|---|---|---|---|---|
| nba·regular·game | **PASS** | 169,947 / 205 / 28 | −3.42 [−4.66, −2.39] | [−5.22, −2.00] ✓ | +0.05 [−0.50, +0.54] | −13.71 [−33.25, +5.37] (5,028 / 203) |
| nba·regular·prop | **PASS (outcome unmeasured)** | 101,070 / 205 / 28 | −14.22 [−15.54, −12.97] | [−16.07, −12.52] ✓ | −1.81 [−2.48, −1.16] | — |
| ncaaf·regular·game | **PASS** | 16,228 / 256 / 22 | −0.64 [−0.81, −0.46] | [−0.90, −0.40] ✓ | −0.51 [−0.68, −0.34] | −7.60 [−22.37, +7.23] (7,464 / 245) |
| ncaaf·regular·prop | **FAIL** | 8,558 / 181 / 22 | +0.01 [−0.29, +0.29] | [−0.37, +0.40] | +0.19 [−0.09, +0.47] | — |
| nfl·regular·game | **PASS** | 4,275 / 56 / 16 | −0.77 [−1.28, −0.29] | [−1.50, −0.04] ✓ | −0.52 [−1.06, −0.02] | +0.55 [−27.25, +25.22] (1,543 / 56) |
| nfl·regular·prop | **PASS (outcome unmeasured)** | 15,851 / 56 / 16 | −9.54 [−11.39, −7.70] | [−12.59, −6.96] ✓ | −3.05 [−4.05, −2.09] | — |
| nhl·regular·game | **PASS** | 2,899 / 193 / 29 | −0.71 [−1.06, −0.36] | [−1.24, −0.24] ✓ | −0.56 [−0.92, −0.21] | **−19.36 [−37.44, −1.64]** (2,765 / 183) |
| nhl·regular·prop | **PASS (outcome unmeasured)** | 41,206 / 193 / 29 | −17.45 [−18.51, −16.27] | [−19.12, −15.86] ✓ | +1.08 [+0.51, +1.63] | — |
| soccer·regular·game | **PASS** | 16,378 / 382 / 18 | −2.61 [−3.43, −1.82] | [−3.78, −1.35] ✓ | −0.45 [−1.29, +0.38] | −11.39 [−29.89, +6.41] (4,882 / 238) |
| mlb·postseason·game | UNDERPOWERED | 399 / 3 / 3 | +1.19 | — | +2.68 | −30.89 (38 / 3) |
| mlb·postseason·prop | UNDERPOWERED | 1,070 / 3 / 3 | +1.63 | — | +2.07 | — |
| wnba·postseason·game | UNDERPOWERED | 0 (never trained: 3 window games + 14 before) | — | — | — | — |
| wnba·postseason·prop | UNDERPOWERED | 0 | — | — | — | — |

**The ridge again chose its lower edge.** In arm A, λ = 1e−5 was chosen at 26 of 28 NBA game refits, all 28 NBA prop refits, all 22 NCAAF game refits, 23 of 29 NHL game refits and 17 of 18 soccer refits.

## 3. Where the passes come from (breakdowns: reported, never a pass). Arm A, 10⁻⁵ nats (rows / games)

| family | sharp-target rows | **consensus-target rows (non-mechanical)** |
|---|---|---|
| nba·game | −15.33 [−19.96, −11.48] (45,728 / 205) | **+0.97 [+0.36, +1.68]** (124,219 / 205): **v1 WORSE** |
| nba·prop | −51.06 [−55.45, −47.02] (26,682 / 205) | **−1.01 [−1.50, −0.54]** (74,388 / 205): better |
| ncaaf·game | −1.51 [−2.00, −1.02] (4,030 / 255) | **−0.35 [−0.52, −0.19]** (12,198 / 256): better |
| ncaaf·prop | — | +0.01 [−0.29, +0.29] (8,558 / 181) |
| nfl·game | −2.84 [−4.83, −1.10] (787 / 56) | −0.30 [−0.73, +0.08] (3,488 / 56): not separable from 0 |
| nfl·prop | −22.05 [−26.36, −17.94] (7,209 / 54) | **+0.90 [+0.20, +1.85]** (8,642 / 56): **v1 WORSE** |
| nhl·game | — | **−0.71 [−1.06, −0.36]** (2,899 / 193): better, but the equal-weight pool alone gets −0.56 |
| nhl·prop | −30.91 [−32.50, −29.30] (24,236 / 192) | **+1.77 [+0.97, +2.58]** (16,970 / 193): **v1 WORSE** (stage 1: +2.06) |
| soccer·game | −4.86 [−5.92, −3.75] (7,651 / 382) | −0.64 [−1.67, +0.40] (8,727 / 365): **stage-1's −3.15 did not replicate** |

**Fitted weights, NBA game** (last refit, quote age < 15 min, relative to an equal vote = 1.0):
- Pinnacle is 1.7–2.3× on h2h, spreads and totals, and 2.9–5.0× on `game_other`. It rises toward the start.
- Every other book is 0.88–1.02.
- **The NBA-game equal-weight pool is +0.05 [−0.50, +0.54]**, so its whole gain is the Pinnacle weight, i.e. mechanical. The same holds for the prop families: their equal pools are small or worse.

**By snapshot:**
- The gains in the prop families and NBA game now **grow toward T−30m**: NBA game −5.48 at T−30m vs −1.89 at T−6h. That is the signature of Pinnacle predicting its own close.
- The pure consensus families still fade toward the start, as at stage 1. NHL game: −1.69 at T−24h, −0.07 at T−30m. NCAAF game: −1.04 at T−6h, −0.38 at T−30m.

## 4. Beside the gate: |fair − close| (pp) and σ coverage. Arm A, on held-out rows with a close target

v1 − Shin is the mean of the per-row difference in absolute distance to the close, game-clustered 95% CI. Negative means v1 is closer.

| family | \|Shin − close\| pp | \|v1 − close\| pp | **v1 − Shin, pp [95% CI]** | \|v1 − Shin\| pp | inside ±1σ (0.683) | inside ±2σ (0.954) | median σ pp | 1σ calibrated [0.60, 0.76] |
|---|---|---|---|---|---|---|---|---|
| nba·game | 0.943 | 0.932 | **−0.010 [−0.016, −0.005]** | 0.227 | 0.719 | 0.897 | 1.17 | yes |
| nba·prop | 1.093 | 1.027 | −0.066 [−0.075, −0.056] | 0.439 | 0.800 | 0.929 | 1.40 | **no (too wide)** |
| ncaaf·game | 0.563 | 0.581 | **+0.019 [+0.015, +0.023]** | 0.125 | 0.718 | 0.905 | 0.73 | yes |
| ncaaf·prop | 0.394 | 0.444 | +0.050 [+0.045, +0.056] | 0.115 | 0.847 | 0.947 | 0.66 | no (too wide) |
| nfl·game | 0.538 | 0.579 | **+0.042 [+0.032, +0.051]** | 0.163 | 0.732 | 0.904 | 0.67 | yes |
| nfl·prop | 0.915 | 0.847 | −0.068 [−0.087, −0.048] | 0.302 | 0.714 | 0.902 | 0.99 | yes |
| nhl·game | 0.782 | 0.797 | **+0.015 [+0.007, +0.023]** | 0.143 | 0.768 | 0.923 | 0.94 | **no (0.768, just too wide; stage 1 0.735)** |
| nhl·prop | 1.000 | 0.758 | −0.243 [−0.258, −0.227] | 0.510 | 0.765 | 0.937 | 1.03 | no (too wide) |
| soccer·game | 1.272 | 1.278 | +0.006 [−0.004, +0.015] | 0.246 | 0.713 | 0.917 | 1.39 | yes |

Read the pp column with the gate:
- **Where v1 is closer in pp** (NBA game and the three prop families), the families are the Pinnacle-weighted ones, and the pp gain shares the mechanical caveat. The pp column is not split by target source.
- **In every game family judged mostly or wholly against the consensus** (NCAAF, NFL, NHL), v1 is **further** from the close than the Shin median, as at stage 1. EV is linear in p.
- **±2σ is short everywhere** (0.897–0.947 vs 0.954), as at stage 1. ±1σ holds in 5 families.

## 5. Arm B (amendment A1, λ ∈ 1e−8..1e−5): reported, never a gate pass

| family | arm A verdict / Δ close | arm B verdict / Δ close [95% CI] | arm B consensus-target rows | arm B v1 − Shin pp |
|---|---|---|---|---|
| nba·game | PASS / −3.42 | PASS / −4.17 [−5.81, −2.82] | +1.30 [+0.61, +2.12] (worse) | −0.029 [−0.037, −0.021] |
| nba·prop | PASS (o.u.) / −14.22 | PASS (o.u.) / −15.65 [−17.19, −14.25] | −1.06 [−1.59, −0.57] | −0.116 |
| ncaaf·game | PASS / −0.64 | PASS / −0.95 [−1.36, −0.36] | −0.05 [−0.51, +0.68] | −0.001 [−0.006, +0.004] |
| ncaaf·prop | FAIL / +0.01 | FAIL / −0.11 [−0.42, +0.19] | (same rows) | +0.051 |
| nfl·game | PASS / −0.77 | PASS / −1.85 [−2.93, −0.97] | −0.12 [−0.52, +0.25] | +0.019 [+0.004, +0.032] |
| nfl·prop | PASS (o.u.) / −9.54 | PASS (o.u.) / −11.46 [−13.95, −9.02] | +1.07 [+0.34, +1.96] (worse) | −0.124 |
| nhl·game | PASS / −0.71 | PASS / −0.61 [−1.13, −0.09]; Bonferroni [−1.46, +0.21] ✗ | (all consensus) | +0.021 [+0.011, +0.031] |
| nhl·prop | PASS (o.u.) / −17.45 | PASS (o.u.) / −18.46 [−19.66, −17.15] | +2.32 [+1.47, +3.18] (worse) | −0.286 |
| soccer·game | PASS / −2.61 | PASS / −5.75 [−7.00, −4.51] | −0.63 [−1.94, +0.73] | −0.050 [−0.063, −0.036] |
| MLB ×2, WNBA ×2 | UNDERPOWERED | UNDERPOWERED | | |

**A1's question is answered: no B-only pass, so there is no lead.**
- Arm B's larger Δ comes from the sharp-target rows. Soccer's sharp rows go −4.86 → −11.60, and NBA game's go −15.33 → −19.06.
- **Against the consensus close, arm B is no better than A anywhere**, and it is worse in the three families where A was already worse.
- This matches what the stage-1 post-hoc §6b predicted: a looser ridge buys more mechanical Pinnacle weight, not information.
- The NCAAF game pp gap closes under B (−0.001), and soccer's turns negative (−0.050). Both families' arm-B gains sit on sharp rows.

## 6. Recommendation (a recommendation, not an action)

Registered rule §10: at least 1 family passes, so shadow-wire `p_fair_v1` / `σ_fair_v1` for the passing families, with the basis stamped per row. Shadow wiring already exists (`636ba4ff`; fleet params `syndicate_fair_v1@2026-10-26@18ed2e2c`, fitted on stage-1 data).

1. **Extend the shadow basis to the stage-2 passes, `σ_fair_v1` first.**
   - **σ calibrated:** NBA game, NFL game, NFL props, soccer and NCAAF game.
   - **σ flagged uncalibrated:** NBA props (0.800), NHL props (0.765) and **NHL game (0.768, newly over the band)**.
   - **±2σ is short everywhere**, so any lower-bound EV built on σ keeps the ×1.2–1.3 tail multiplier the stage-1 findings proposed.
   - Doing this needs a refit plus `scripts/publish_syndicate_fair_params.py` (lane `syndicate-decision-engine`). **This run did neither. That is a separate user decision.**
2. **`p_fair_v1` stays out of every EV, price, Suggested flag and stake.** The standing user rule of 2026-10-26 is unchanged, and the stage-2 evidence supports it:
   - On the non-mechanical split, v1 beats the Shin median in 3 families (NBA props −1.01, NCAAF game −0.35, NHL game −0.71), is worse in 3 (NBA game, NFL props, NHL props) and is not separable in 2 (NFL game, soccer).
   - The NHL game gain is mostly the pooling form (equal pool −0.56).
   - In the consensus-judged game families, v1 sits 0.015–0.042 pp **further** from the close.
3. **The engine message is Pinnacle.** Where Pinnacle quotes (now NBA, NFL and soccer game lines, and NBA / NFL / NHL props), its own price predicts its close, and a learned pool mostly re-discovers that.
   - A sharp-anchored fair that uses Pinnacle where it quotes, and the Shin consensus elsewhere, captures the mechanical gain without a learned model. That is what `layer2_board`'s anchor already does.
   - Whether the anchor's close is the truth is a G2 question.
4. **One outcome lead, not a result:** NHL game G2 is −19.36 [−37.44, −1.64] (2,765 rows / 183 games). It is the first outcome CI below 0 in either stage, and it is family-wise uncorrected: 1 of 5 G2 reads.
5. **What remains for v2**, if anyone registers it:
   - fitting to outcomes, once there is enough (prereg §3);
   - an MLB / WNBA read, which can only come next season: both stay UNDERPOWERED on 3 games;
   - a σ tail model.

## 7. Owed by this lane

Nothing registered remains: the stage-2 read was the lane's last owed item. The shadow-basis refit/republish (§6.1) is a user decision for the decision-engine lane, not owed here.
