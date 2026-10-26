# FINDINGS -- E5: do Kalshi / Polymarket move LATER than the books after availability news? (lane `e5-venue-news-lag`, 2026-10-26)

Decision Engine plan §4 **E5**. OFFLINE, read-only on production (fleet `~/syndicate-prod/data`, nice 19; Kalshi
PUBLIC GETs only). No deploy, restart or env edit. No LLM.

- **Pre-registration:** `.syndicate/findings_2026-10-26_e5_venue_news_lag_preregistration.md`, committed
  **`d9ce947f` (19:28Z)** before any news x venue / news x book join; amendments A1 `0a9b9fed`, A2 `0bfcc8bc`,
  A3 `e3fd2e2a` (all eligibility / run-time interpretations, each committed before any result was read).
- **Code:** `scripts/e5_venue_news_lag.py`, tests `tests/test_e5_venue_news_lag.py` (31, hermetic).

## Verdict

| Venue | Registered verdict | Rests on | What it means |
|---|---|---|---|
| **Kalshi** | **KILL** (clause b: the move is symmetric) | 197 primary units, 93 games, 14 t0-dates (10-13..10-26) | After our capture, Kalshi's signed drift is **+0.04pp [-0.05, +0.13]**. On the news side at the executable ask, fee-net EV is **-4.32% [-4.58, -4.07]** at +1 min. The increment over placebo is -0.22pp [-0.52, +0.05]. Nothing is left to take. |
| **Polymarket** | **PASS_CANCEL_PROTECTION_ONLY**, by the letter | 39 primary units, 27 games, 11 dates; 34 NHL, all `to_out` | The drift that survives is **+0.21pp [+0.07, +0.35]**, a fifth of the 1c tick. The lag "passes" only because **18 of 18** lags are censored: the venue never moved 2c. EV is -4.31% [-4.75, -3.92]. Clock: our 3-13 min board loop. INDICATIVE. |

**E5 as a timing edge is not supported.** In 13 days of collector events, the venues did not trail the books on
game lines by anything that survives the fee and spread. Post hoc, on the few events the books *did* reprice,
Kalshi had **already moved before our collector saw the news**, ahead of the books. That is the opposite of a lag.

## What it rests on (CLAUDE.md coverage rule)

All data was read on the fleet on 2026-10-26 between 19:43Z and 20:10Z, at nice 19. Kalshi candles came from the
public API: 1,018 GETs; a re-run reproduced every registered number from the cache.

| Source | Coverage |
|---|---|
| Collector runs (A3: `logs/news_collector.log`) | 1,983 runs, 10-13 19:29Z .. 10-26 19:56Z. 1 gap > 25 min (390 min, the known 10-14 host sleep). MLB starts 10-14 22:51Z. |
| News change logs | nba / nfl / nhl / wnba 10-13..10-26 (14 files each); mlb 10-14..10-26 (8); NHL gameinfo 14 |
| `book_quotes` | nba 10-12..10-28 (13 files); nhl 10-12..10-27 (16); nfl weeks 5-7 plus dailies (21); wnba 5; mlb 11 |
| Kalshi | 1-min candles for every eligible unit. Market discovery from `venue_odds/kalshi__*` (nba 24 files, nfl 15, nhl 33) |
| Polymarket | `venue_odds/polymarket__*` points (nba 30, nfl 16, nhl 31 files). 48-point cap, board-loop cadence. |

**Funnel:**

| | nba | nfl | nhl | wnba | mlb |
|---|---|---|---|---|---|
| Events | 232 | 771 | 264 + 449 scratches | 2 | 70 |
| Team-game units | 134 | 276 | 358 | 1 | 2 |
| Book-eligible units | 77 | 276 | 285 | 1 | 2 |
| Kalshi rows | 77 | 276 | 256 | 1 | 0 |
| Primary (impact) rows | 15 | 97 | 84 | 1 | 0 |

- **De-duplication worked:**
  - NFL: 2 flaps.
  - NHL: 1 flap, plus 7 scratch flaps.
  - NBA: 0 flaps, and 0 `t0_uncertain` events anywhere.
  - Same-run id-churn pairs never become events.
- **Excluded:**
  - 29 NHL units refused on Kalshi identity.
  - Polymarket: 100 identity refusals; 268 ineligible (250 of them NFL: no retained point by t0 - 30 min, or
    capture ended before t0 + 15 -- which of the two was not split); and 119 with an ambiguous orientation.
- **Lag n:** a lag exists only where some book moved >= 1pp toward the news within W. That is 79 of the 197 Kalshi
  primary units; the drift and EV use all 197.
- **Validation:** 60 of 64 NBA `to_out` Kalshi rows (93.8%) are OUT on the game-date official snapshot
  (`raw/injuries.csv`).
- **Intersection:** Kalshi primary units fall on all 14 t0-dates, 2 to 29 per date. NBA contributes only 15 primary
  units, because its regular season started about 10-20.
- **Timing resolution:** the book-move bracket (previous snapshot to snapshot) has a median of 1.97 min on Kalshi rows
  and 4.87 min on Polymarket rows. Kalshi itself is timed to the minute.

## Results (registered measures, primary units)

| | Kalshi (197 / 93 games) | Polymarket (39 / 27 games) |
|---|---|---|
| Median lag vs first book move, mid [95% CI] | 39.0 min [28.0, 47.2] | 26.8 [17.3, 36.0] |
| Median lag, early / late book bound | 39.5 [28.7, 48.4] / 34.0 [26.5, 45.2] | 28.7 [18.7, 38.7] / 24.9 [12.3, 28.7] |
| Lags censored (venue never moved >= 2c in the news direction within W) | 65 of 79 (82%) | 18 of 18 |
| Venue directional >= 2c move within 15 min, news vs placebo | 0.5% vs 0.0% | 0.0% vs 0.0% |
| Books: any book >= 1pp within 15 min, news vs placebo | 17.3% vs 8.6% | 17.9% vs 2.6% |
| **Venue signed drift, t0+1 -> t_end** | **+0.04pp [-0.05, +0.13]** | +0.21pp [+0.07, +0.35] |
| Book-consensus signed drift, same window | +0.13pp [+0.02, +0.26] | +0.04pp [-0.01, +0.11] |
| Fee-net EV at the executable ask, +1 / +5 / +15 min | -4.32% / -4.31% / -4.27% (every CI below -4.0%) | -4.31% / -4.45% / -4.50% |
| EV increment over placebo, +1 / +5 / +15 | -0.22 [-0.52, +0.05] / -0.20 / -0.18pp | -0.11 [-0.37, +0.11] / -0.24 / -0.21pp |
| Units with EV_1 > 0 | 2 of 197 (max +2.2%) | 0 of 39 |
| Realised return at +1 min (Kalshi result) | -5.9% [-19.4, +8.8] | n/a |

**Read:**

- **The 39-minute "lag" is not a lag.** It is the censoring value: in 82% of cases the venue never moved 2c in the
  news direction, because the books barely did either (+0.13pp).
- **The kill comes from the symmetric clause.** After we know, the venue has nothing left to move in the news
  direction.
- **Splits:**
  - `to_out` (158 units): +0.06pp [-0.05, +0.18].
  - `to_in` (39): -0.06pp [-0.27, +0.09].
  - NFL (97 units / 27 games): +0.01pp [-0.07, +0.08], flat.
  - NHL (84 / 54): +0.14pp [-0.04, +0.35].
  - NBA (15 / 11): -0.33pp [-0.67, -0.08], a small reversal after t0.

**Own-prop arm (descriptive, as registered):**

- **Kalshi:** 205 of the player's own prop markets were quoted at t0. 50 (24%) moved >= 2c within 15 min, against
  30 (15%) in the placebo window, and **0 were withdrawn**.
- **Books:** of 4,442 prop keys quoted before t0, only **101 (2.3%) were re-quoted** within 15 min, against 239
  (5.4%) in the placebo window. Books update a ruled-out player's props *less* after the news. That is consistent
  with pulls, as `news-price-follow` found.
- **No edge either way:** Kalshi settles an inactive player's prop at a fair price (rules_secondary, prereg).

## Post hoc (NOT registered; these subsets are conditioned on the books' later move)

| Subset (Kalshi) | Units / games | Book move pre-t0 / post-t0 | Kalshi move pre-t0 / post-t0 | Kalshi vs books at t0 | Gap left at t0+1 | EV_1 |
|---|---|---|---|---|---|---|
| Books moved >= 2pp toward the news over [t0-60, t_end] | 19 / 16 | +2.01 / +1.84pp | **+2.53** / +1.05pp | -0.80pp (Kalshi ahead) | +1.03pp | -2.16% [-3.06, -1.32] |
| Books moved >= 2pp AFTER t0 | 9 / 8 | -0.06 / +3.43pp | **+1.56** / +1.44pp | -1.61pp [-3.96, -0.18] | +1.83pp [+1.16, +2.35] | -0.80% [-1.98, +0.12] (3 of 9 > 0, max +1.2%) |
| NHL scratches (all) | 162 / 87 | +0.01 / +0.01pp | +0.01 / -0.02pp | -0.06pp | -0.04pp | -4.39% |
| Within 3 h of the start | 249 / 136 | -0.01 / +0.02pp | +0.04 / -0.05pp | -0.08pp | -0.06pp | -4.52% |

- **The example that matters: Kawhi Leonard OUT, 10-25, 49 min before tip.**
  - Kalshi had already gone from 0.505 to 0.405 by our capture.
  - The book consensus sat at 0.500 at t0. Its first >= 1pp book move came ~0.5 min after t0, and it ended at
    0.405 by t_end.
  - So Kalshi moved first, the books followed within our capture, and our collector saw the news after Kalshi.
- **On the material events, Kalshi leads or matches the books.** The 1.8pp still open at t0+1 is below the ~4.3%
  round trip of fee plus spread, so even a perfect trigger on these 9 units loses.
- **The NHL scratches are not news to game lines** (+0.01pp). The scratch list mostly names depth players.
- **What the post-hoc look does NOT cover:**
  - These subsets were chosen by looking ahead, so they are not a test.
  - n = 9 / 19.
  - The scheduled lineup classes the plan names were not in the window as events: NFL inactives at T-90 (ESPN's
    injury feed does not carry them) and EPL XI at T-75 (not collected).

## Engine read -- which availability events the sims ignore today, and whether removal reaches them

(Code + ledger read on main 2026-10-26; NHL and NBA facts are fleet-verified in the cited state entries.)

| Sport | What the sim reads | OUT removed? | What it ignores |
|---|---|---|---|
| NBA | `raw/injuries.csv` (the official-PDF / fetch-injuries snapshot), not the collector | Yes: OUT, DOUBTFUL, SUSPENDED, INACTIVE dropped (`_drop_excluded`); re-sim ~3 min after an injuries refresh inside 30 min of tip (10-16 PHI_BOS) | DTD / Questionable kept at FULL weight (78 of 88 on 10-16); the snapshot is periodic, so an intraday OUT reaches the sim only at the next injuries refresh, not at the collector's 10-min event |
| NHL | the collector's STATE since 10-16 (`lineup_availability.py`, `bf60a2b2`, verified: 7 excluded on the first build, 0 dressed-OUT rows) | Yes: Out / IR / LTIR / Suspension and posted scratches, before `infer_lines` | Day-To-Day stays dressed; a scratch posted ~T-25 reaches the sim only if a lineup rebuild runs after it; not gated by `nhl_sim_input_checklist.py` and not in any artifact allowlist (state_model) |
| NFL | nothing in the prop model (rolling mean x game multiplier); `injury_adjustment.py` OFF since `36cd8a5c` | **No** (the board flag unseats OUT props; the sim still projects them) | every status; an injury change triggers an odds sweep, not a re-sim |
| NCAAF | nothing (ESPN's CFB injury feed is dead) | No | every status |
| MLB | StatsAPI IL + the posted nine | Yes (IL) | DTD; no live example in the postseason window |
| Soccer | no injury feed; confirmed XI ~1 min before kickoff | Indirect only | everything before kickoff |

**What this means for the engines, given E5:**

- The fair the plan trades against is the book consensus. The books and Kalshi price an availability change within
  minutes of each other, and often before our collector does.
- So a sim's removal timing does not set any EV today: the sim's mean weight is 0 under D3.
- **Removal CORRECTNESS is still real engine work. It is not a timing edge.**
  - NBA keeps DTD at full weight.
  - NFL / NCAAF / soccer read no status.
  - Whether an NHL lineup rebuild runs after a T-25 scratch is UNVERIFIED here.
- Those fixes belong to the sim owners; nothing in E5 promotes them.

## Recommendation for Phase 4 (the availability event bus)

1. **Do not build the bus as a TIMING strategy.**
   - E5 is killed on Kalshi by the registered rule.
   - Polymarket's surviving drift is 0.2c with EV -4.3%.
   - Every increment over placebo is ~0.
   - No paid news feed is justified on E5's evidence. This is §6's condition ("only if E5 shows that minutes of
     latency are worth money"), and it is not met.
2. **Build it as CANCEL-PROTECTION and correctness plumbing only, and only when the Phase 3 maker engine exists.**
   That means cancel resting orders, stale-gate, re-sim and record.
   - **The measured caveat:** on the events that mattered, Kalshi had moved BEFORE our 10-min ESPN collector captured
     the news.
   - So a bus fed by today's collector would cancel a resting maker order after the venue had already repriced. The
     order would be picked off first.
   - Protection therefore needs an earlier source **before** it is built: the official NBA report on its 15-min
     schedule, with its report time; NHL gameinfo polled tightly near puck drop; NFL inactives; EPL XI.
   - Moving the collector from 10 to 5 min is a pending user decision in `news-availability-gate`. It would not have
     helped the Kawhi case, where the venue moved before ESPN.
3. **Re-run this script (it is reusable) once an official-source t0 exists, or after a month of NBA regular season.**
   - That run should state the official report time, and keep the same constants.
   - Until then the bus's "record" step is the only part that improves this measurement.
4. Every line stays its own decision. Nothing here switches a market off or on.

**Decision owed (routed to "Syndicate AI decision engine"):** downgrade Phase 4 from "parallel from Phase 1" to
"cancel-protection plumbing, gated on Phase 3 and on an official-schedule t0". The plan text is the decision-engine
lane's file; this lane does not edit it.

## Caveats

- **t0 is our ESPN capture.** It falls up to 10 min after ESPN, which itself trails official reports and beat
  reporters.
  - That is the right t0 for a bus built on today's collector.
  - It is the wrong t0 for one built on official schedules: untested.
- **Game lines only for the economics.** The own-prop arm is descriptive, and teammates' props were not measured.
- **Polymarket is weak evidence:**
  - its clock is our board loop at 3-13 min, with the 48-point cap and no outcome labels;
  - orientation is mapped pre-t0 and identity goes through Kalshi codes;
  - its prices are recorded side prices that look like asks, not executable depth.
- **The NFL book set includes a dot-prefixed weekly file** (`.2026_wk5`), unioned and de-duplicated with the rest.
- **Script note:** the run that produced these numbers also writes POST-HOC diagnostic fields: `b_pre60` / `b_t0` /
  `b_1` / `b_end` / `v_pre60` / `v_1` / `v_end`. They change no registered measure, and the registered outputs
  reproduced exactly after they were added.
- **Raw output (scratch, not in git):** `C:\tmp\e5\report_nba_nfl_nhl_wnba_mlb.json` (733 rows) and the run logs
  `C:\tmp\e5\run_all*.log`. The post-hoc reader is `C:\tmp\e5\posthoc.py`.
