# FINDINGS -- is the SGP builders' `p_joint` miscalibrated on settled tickets? (lane `sgp-pjoint-calibration`, 2026-10-27)

OFFLINE and read-only on production. I read a snapshot of the fleet's SGP ledgers. No deploy, restart or env edit.
Todo `#743`.

- **Pre-registration:** `.syndicate/findings_2026-10-27_sgp_pjoint_calibration_preregistration.md`.
  - Committed **`1e7793e3`** at 14:24Z (9:24 AM CT), before any outcome join.
  - **Amendment A1 `cfee6f28`** at 14:31Z, committed with the code before the run. It corrects the graded snapshot's
    time and records the SE forms and the §7 composition.
- **Code:** `scripts/sgp_pjoint_calibration.py`. Tests: `tests/test_sgp_pjoint_calibration.py`, 13 hermetic tests. They
  include:
  - §2 reachability: a void-leg LOSS is in as-graded and out of clean;
  - the §3 SE equalling `grade_sgp_paper.summarize`'s;
  - §6d: `pair_legs` gives identical `p_joint`, tickets and order at discounts 0, 0.185 and 0.5.
- **Snapshot:** fleet `cheatsheets/<sport>/sgp_{ledger,graded}.jsonl` and the correlations files, copied at 14:25Z.
  - The graded files are the 13:09:39Z write. sha256 prefixes are in A1.
  - Manifest: `C:\tmp\sgpcal\snap_manifest.txt`.
- **Run:** 2026-10-27, ended 14:31:32Z.
- **Raw output (scratch, not in git):**
  - `C:\tmp\sgpcal\report.json`, `C:\tmp\sgpcal\run1.log`;
  - the post-hoc checks: `C:\tmp\sgpcal\posthoc.py` and `posthoc.json`.

## Verdict

**NOT SHOWN, under the registered rule, in every gated cell. "The gap is real" = FALSE.** Holm over {pooled, NHL, NBA,
NFL}: every adjusted p = 1.0.

**The lead's 3-6 point over-prediction was mostly a grading artefact, not the model.**
- `grade_sgp_paper` counts a ticket with an unresolved leg (pending or void) as LOST when another leg lost, but never
  as WON.
- That asymmetric censoring alone adds **+2.4 points [+1.3, +3.5]** pooled, and **+4.3 [+2.6, +6.3]** in NHL.
- It comes almost entirely from **permanently ungraded ("pending") legs**:
  - correlation-family legs (sheet rows and ladder rungs) carry no `player_id`, so `leg_actuals` cannot grade them;
  - **34% of NHL sheet-row legs** in the ledger never resolve.
- On the clean population (every leg won or lost), `p_joint` sits **+1.7 points [-3.1, +6.4]** from the realised rate
  pooled. NHL flips sign, to -1.6.

| Cell (clean, primary) | Tickets / games | Mean `p_joint` | Realised | CITL = p - y [95% CI] | Cluster-bootstrap CI | MDE80 | Verdict |
|---|---|---|---|---|---|---|---|
| **Pooled** | 971 / 139 | 34.0% | 32.3% | **+1.7 [-3.1, +6.4]** | [-3.2, +6.6] | 6.8 | NOT SHOWN |
| NHL | 482 / 65 | 25.2% | 26.8% | **-1.6 [-7.1, +4.0]** | [-7.4, +3.8] | 7.9 | NOT SHOWN |
| NBA | 262 / 39 | 45.3% | 40.5% | +4.8 [-7.2, +16.9] | [-7.6, +16.3] | 17.2 | NOT SHOWN |
| NFL | 160 / 24 | 36.7% | 33.1% | +3.6 [-5.5, +12.7] | [-5.1, +13.1] | 13.0 | NOT SHOWN |
| WNBA (not gated) | 38 / 5 | 46.9% | 36.8% | +10.1 [-26.8, +46.9] | | 52.7 | reported |
| MLB (not gated) | 29 / 6 | 46.6% | 41.4% | +5.2 [-26.9, +37.4] | | 45.9 | reported |

- All values are in percentage points.
- **MDE80** is the gap this n would detect with 80% power. A null here means **"no gap larger than ~7 points pooled"**.
  It does NOT mean calibrated to within 1-2 points. NBA and NFL cannot rule out gaps of 13-17 points.
- The registered SE is the uncentered `grade_sgp_paper` form, and the bootstrap agrees on every cell.

**Slope (§4, secondary):**
- Pooled `b` = **0.92 [0.66, 1.18]**, consistent with 1. Offset intercept -0.09 [-0.35, +0.17].
- Per sport: NHL 0.95 [0.63, 1.28], NBA 0.79 [0.14, 1.44], NFL 1.20 [0.56, 1.84]. None differs from 1.

## Where the lead came from -- the as-graded population and the censoring term

| Cell | As-graded tickets / games | As-graded CITL [CI] | Clean CITL | `G_censor` = as-graded - clean [bootstrap CI] |
|---|---|---|---|---|
| Pooled | 1,181 / 141 | **+4.0 [+0.0, +8.1]** | +1.7 | **+2.4 [+1.3, +3.5]** |
| NHL | 666 / 66 | +2.7 [-1.5, +7.0] (19.4% vs 22.1%) | -1.6 | **+4.3 [+2.6, +6.3]** |
| NBA | 268 / 39 | +5.6 [-6.4, +17.6] | +4.8 | +0.8 [0.0, +2.0] |
| NFL | 180 / 25 | +5.0 [-3.2, +13.2] | +3.6 | **+1.4 [+0.1, +3.1]** |
| WNBA / MLB | 38 / 29 | identical | identical | 0 (no unresolved legs) |

- **The as-graded numbers reproduce E4's descriptive table.** E4 had NHL 601 / 63 at 19.5% vs 22.8%; with one more
  date, 666 / 66 reads 19.4% vs 22.1%.
- The nightly `SGP_PAPER` line uses the same as-graded population. It carries the same bias.

**Mechanism (POST-HOC, not registered; `posthoc.json`):**
- **NHL:**
  - 184 as-graded tickets are not clean, all LOST by construction. 178 of them are correlation family, which is
    ledger-only and not served. Their mean `p_joint` is 13.9%.
  - Their unresolved legs are **227 pending, 7 void**.
  - Over every NHL ledger leg dated <= 10-26:
    - 327 of 961 sheet-row legs are pending (34%);
    - 166 of 1,555 alt legs are pending.
  - **488 of the 493 pending legs have no `player_id`** (correlation family: `nfl/sgp.py` `_leg` / `rung_leg`,
    `nhl/sgp.py` `_leg`).
  - Pending legs date back to 10-17, so they are permanent, not late.
- **NFL:** 20 tickets, all correlation family; 42 sheet-row legs pending, none with a `player_id`.
- **NBA:** 6 tickets (4 void legs, 3 pending).
- **The served hit-rate family is barely touched:** 5 NHL and 4 NFL pool legs are pending.

**Symmetric check (POST-HOC): the "book rule".**
- Drop every unresolved leg, re-price the resolved sub-ticket with the builders' own copula, and grade on the legs
  that resolved. This is what books do with a void leg.
- **Pooled +2.0 [-2.2, +6.2]** over 1,290 tickets / 142 games. NHL +0.5 [-4.4, +5.4], NBA +4.4, NFL +2.5.
- The 319 re-priced sub-tickets alone: +3.0 [-3.9, +9.8].
- **The clean filter is not biasing the result the other way.**

## Breakdowns (descriptive, clean population, pooled unless named)

| Group | n / games | `p_joint` | Realised | CITL [CI] |
|---|---|---|---|---|
| hit_rate / safer (served) | 369 / 121 | 51.9% | 49.9% | +2.0 [-5.7, +9.7] |
| hit_rate / payout (served) | 199 / 105 | 39.9% | 37.2% | +2.7 [-5.8, +11.3] |
| correlation (ledger-only) | 391 / 67 | 15.0% | 14.3% | +0.7 [-4.0, +5.3] |
| size 2 / 3 / 4 | 234 / 205 / 271 | | | +0.5 / +1.6 / +0.7, every CI spanning 0 |
| size 5 / 6 | 148 / 113 | | | +5.3 [-5.1, +15.6] / +1.9 [-9.5, +13.3] |
| relation: teammate / mixed / opponent / same_player | 299 / 613 / 35 / 24 | | | +1.5 / +2.2 / +0.9 / -7.1, every CI spanning 0 |
| seen (<= 10-25) | 855 / 125 | 34.3% | 34.0% | **+0.3 [-4.7, +5.2]** |
| unseen (10-26) | 116 / 14 | 31.8% | 19.8% | +12.0 [-4.5, +28.4] (one Sunday; NBA 42 of the 116 at 26% vs 46%) |

- **Reliability by `p_joint` decile:** 1 decile of 10 has a CI excluding 0 (decile 4, +8.0 [+0.5, +15.5]). That is the
  rate expected by chance; no monotone pattern.
- **NHL without its 12 pre-family tickets:** -1.8 [-7.4, +3.9].
- **The unseen 10-26 slice reads worse** (+12.0) but is one date with 14 games. It is the reason the forward read
  (§8) matters. It is not evidence by itself.

## Decomposition (§6) -- DESCRIPTIVE ONLY

§3 did not reject anywhere, so by the registration none of this is an attribution. It is reported because it says what
each component does on the record.

### Ticket arms on clean tickets with every leg priced

| Cell | n | `G_A` market x independent | `G_B` posterior x independent | `G_C` `p_joint` | `D_nudge` (B - A) | `D_copula` (C - B) | LL(C) - LL(A) |
|---|---|---|---|---|---|---|---|
| Pooled | 959 / 137 | **-3.8 [-8.6, +1.1]** | -0.9 [-5.7, +3.9] | +1.6 [-3.2, +6.4] | +2.9 [+2.5, +3.3] | +2.5 [+2.1, +2.9] | -0.0087 [-0.0249, +0.0076] |
| NHL | 470 / 63 | -5.1 [-11.0, +0.8] | -3.2 | -1.8 | +1.9 | +1.4 | **-0.0180 [-0.0353, -0.0007]** |
| NBA | 262 / 39 | -2.3 [-14.0, +9.5] | +2.5 | +4.8 | **+4.7 [+4.1, +5.3]** | +2.4 | +0.0105 [-0.0252, +0.0461] |
| NFL | 160 / 24 | -4.9 [-14.9, +5.1] | -2.6 | +3.6 | +2.3 | **+6.2 [+5.3, +7.1]** | -0.0217 [-0.0737, +0.0303] |

- Arm B reproduces the ledger's `p_independent` on 100% of tickets.
- **Read:**
  - Plain market independence (A) **under**-predicts the realised all-legs rate in every gated sport. The legs are
    positively correlated, and A ignores that.
  - The consistency nudge and the copula each push the prediction up. On the pooled record they land it at +1.6,
    nearer the truth than A.
  - **In NHL, `p_joint` beats market independence on log loss**, with a CI below 0.
  - NBA is the one cell where A is closest. There the nudge adds the most (+4.7 points per ticket, from about 4-6
    legs nudged up by about 2 points each). It is the cell to watch in the forward read.

### Legs (§6b) -- marginals, de-vig, nudge

The unit is a unique resolved leg.

| Cell | Legs / games | Realised | `p_market` | posterior `q` | `g_m` = m - y [CI] | LL(q) - LL(m) [CI] |
|---|---|---|---|---|---|---|
| Pooled | 1,703 / 140 | 68.5% | 68.1% | 69.3% | **-0.4 [-2.4, +1.7]** | **-0.0039 [-0.0071, -0.0007]** |
| NHL | 860 / 65 | 60.8% | 60.2% | 60.9% | -0.6 [-3.7, +2.4] | **-0.0068 [-0.0117, -0.0019]** |
| NHL alt pool | 636 / 63 | 64.3% | 61.9% | 62.9% | -2.4 [-6.4, +1.6] | -0.0027 [-0.0076, +0.0021] |
| NHL sheet rows | 224 / 45 | 50.9% | 55.3% | 55.2% | +4.4 [-0.9, +9.6] | **-0.0184 [-0.0282, -0.0087]** |
| NBA (all alt pool) | 460 / 39 | 81.1% | 80.9% | 82.9% | -0.2 [-4.2, +3.8] | -0.0008 [-0.0066, +0.0050] |
| NFL | 278 / 25 | 68.7% | 68.2% | 69.3% | -0.5 [-5.3, +4.4] | -0.0022 [-0.0077, +0.0033] |
| WNBA / MLB | 58 / 5, 47 / 6 | | | | +4.0 / -1.3, CIs about +/-12-16 | -0.0071 / +0.0139, CIs span 0 |

- **The de-vig is calibrated** on these legs:
  - recalibration slope of `logit(m)`: NHL 1.06 [0.88, 1.24], NFL 0.96 [0.65, 1.27];
  - the gate-selected alt rungs, by band: NBA 0.80-0.85 realised 82.0% vs `m` 81.9% (266 legs); NHL 0.80-0.85
    86.4% vs 82.0% (147).
- **The nudge is not worse than the market anywhere**, and pooled it is slightly better.
- `q` reproduces `(40 m + hits) / (40 + games)` on 100% of legs, so the ledger's posterior is the k=40 rule as built.

### Pairs (§6c) -- the copula

The unit is a unique within-ticket leg pair, both legs resolved. Reconstruction passed in every sport: **810 / 276 /
199 / 38 / 29 tickets re-priced exactly, max error 5e-5**.

| Cell | Pairs / games | Both won | Copula `P_c` | Independence `P_i` | Excess vs copula [CI] | `D_K` = LL copula - LL independence [CI] |
|---|---|---|---|---|---|---|
| Pooled | 3,677 / 139 | 57.6% | 56.6% | 56.0% | +1.0 [-2.7, +4.6] | **-0.0061 [-0.0102, -0.0020]** |
| same player | 285 / 79 | 61.1% | 62.1% | 57.7% | | **-0.0700 [-0.1159, -0.0241]** |
| teammate | 1,900 / 137 | 53.9% | 53.6% | 53.0% | | -0.0016 [-0.0043, +0.0011] |
| opponent | 1,492 / 121 | 61.7% | 59.5% | 59.5% | | +0.0004 [-0.0007, +0.0015] |
| NFL same player | 80 / 22 | 72.5% | 68.6% | 61.2% | | **-0.180 [-0.271, -0.088]** |

**The copula is not over-correlating.** Realised co-occurrence sits at or above it, and it beats independence where it
carries real rho (same player). This agrees with E4: the measured copula is the right correlation source.

### The 18.5% haircut (§6d)

**Zero, confirmed by test.** `ASSUMED_BOOK_DISCOUNT` enters only `est_dec` / `est_ev_pct` (`nfl/sgp.py:447,460,568,577`).
With the discount at 0, 0.185 and 0.5, `pair_legs` returns identical tickets, order and `p_joint`
(`test_assumed_discount_changes_no_p_joint`). It is an assumption about the PRICE, still unmeasured (E4 Stage 2). It is
not a term in the probability.

## Correction (§7)

**No model correction is proposed.**
- §7 runs only for a component §6e flags, and §6e runs only where §3 rejects. Nothing rejected.
- Independently, no leg-level or pair-level test shows any component wrong.

**The correction is to the MEASUREMENT.** Both changes are per ticket and per leg. There is no market or sport switch.

1. **Calibrate on resolved legs only.**
   - `grade_sgp_paper.summarize` should compute hit rate vs `p_joint` over tickets whose every leg is won or lost.
   - Better, use the book rule: drop void or pending legs and compare against the re-priced resolved sub-ticket.
   - Keep the WON / LOST / VOID status rule in `cheat_sheets.sgp_results` as it is. A ticket with a lost leg IS lost
     for the record and P&L. Only the calibration read is biased.
2. **Grade the legs that never resolve.**
   - Correlation-family legs carry no `player_id`, so any leg the sheet itself did not grade stays pending forever.
     That is 34% of NHL sheet-row legs.
   - Fix: carry the game-log `player_id` on `nfl/sgp.py` `_leg` / `rung_leg` and `nhl/sgp.py` `_leg`, as the pool
     legs already do, so `leg_actuals` can grade them.

**Owner:** lane `cheat-sheets` (session 9e18a0e7). Its files are the leg builders and `grade_sgp_paper.py`, and this
lane edited none of them. The item is `#743`.

## Recommendation

1. **Keep `p_joint` as built.** No market-level or line-level change to the probability is warranted. The leg
   marginals, the k=40 nudge and the measured copula each measure as calibrated, or better than their alternative.
2. **Fix the calibration read and the leg grading (`#743`, owner `cheat-sheets`).** Until then, read the nightly
   `SGP_PAPER` calibration line as biased toward over-prediction by roughly the censoring term: about +2 points
   pooled, +4 in NHL.
3. **Forward read (§8, registered; the independent test).**
   - Same script, same constants, tickets dated >= 2026-10-27.
   - When NHL, NBA and NFL each have >= 30 new clean settled games, or on 2026-11-24, whichever is first.
   - Run it as:

     ```
     py -3 scripts/sgp_pjoint_calibration.py --snap <fresh snapshot> --out <out>
     ```

     with `FREEZE` / `SEEN_LAST` moved to the new window. That is the only edit allowed.
   - **Watch NBA:** it has the largest nudge contribution (+4.7 points per ticket), the weakest power (MDE80 17
     points), and a bad 10-26 (26% vs 46% on 42 tickets).

## Caveats

- **This is a confirmatory re-analysis of data that suggested the effect,** not an independent replication (prereg
  disclosure). The forward read is the independent test.
- **Power:** the pooled null rules out gaps above about 7 points. NBA and NFL individually cannot rule out 13-17
  points. "NOT SHOWN" is not "calibrated to the point".
- **Tickets are not independent within a game:** they share legs, which is why every SE is game-clustered. Ticket
  counts overstate the information. The games column is the effective n.
- **The ledger holds each ticket's FIRST build** (`append_ledger`), so `p_joint` is the earliest price of the day.
  Later rebuilds are not scored.
- **Freeze:** dates <= 10-26 and the 13:09Z graded file. 141 NHL / 17 NFL / 2 NBA tickets were still pending, mostly
  for good (see Mechanism).
