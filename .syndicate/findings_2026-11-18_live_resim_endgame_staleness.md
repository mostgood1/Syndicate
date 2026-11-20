# #836 — live re-sims go stale at the end of games: what sets the age, who reads it, and the smaller fix

Lane `live-resim-endgame-staleness`, opened 2026-11-18 ~11:15 AM CST (session e2f5878d, started by the decision-engine
session local_898e5510). Read-only on the fleet; nothing deployed, restarted or loaded. Times are CST unless marked Z.

## Answer in four lines

1. **The state age is set by each producer's loop, not by the evidence log.** The time between new states is p50 151 s for NBA, 154 s for NCAAF and 91 s for NHL (fleet evidence log, dev 11-09..11-14). Those gaps predict the ages the engine read measured. No producer comes near 30 s.
2. **No live-money order is placed from a re-sim probability in play today.** The executor refuses Kalshi and Polymarket entries after kickoff (`SYNDICATE_EXECUTION_KALSHI_PREGAME_ONLY` is unset on every role, so it is ON). The in-play program prices from the book median. Re-sim numbers late in a game do reach the board, its ranking, the rail flag, the paper books and the engine's opinions.
3. **The smaller fix is the refusal**, not a faster refresh. The refusal is one pure predicate at two existing consumer seams. A faster refresh means three producers on two roles, including taking NHL out of a shared serial loop and NCAAF off refresh-worker's main loop, on a host already 100% busy in the live evening (#832). It could not be measured before it was loaded.
4. **Re-measured on dev:** the rule refuses 767 of 829 last-5% line-instants (92.5%, 85 games); those lose to Kalshi by **+0.174 nats (se 0.053)**. The 62 it keeps (-0.048, se 0.019) come from 14 games, two NBA games carrying 38 of them. **The rule rests on the stale majority. It does NOT show that a fresh state beats Kalshi.**

## 1. The trace, per sport (file:line on main `f9e2af5cb`)

**What `evidence_age_s` is.** `engine_experts.live_resim_expert` takes the line instant `t` from the ledger row's `recorded_at` (`engine_experts.py:599`). It picks the newest evidence row at or before `t` (`EvidenceIndex.pick`, `:558-571`), and the age is `t` minus `instant(row)` = max(the snapshot tick `t`, the lane's `as_of`) (`:514-522`, `:659`). Rows are written by the live evidence log (`live_evidence_log.py`), which polls each sport's snapshot every 30 s on refresh-worker (`DEFAULT_INTERVAL_SECONDS` `:52`, loop `:350-365`, started at `run_refresh_worker.py:8368-8370`). Each row keeps the producer's own `t` (`generatedAt`) and `as_of` (`liveStateAsOf`). The log captured every producer tick (publish gap = new-state gap below), so **it adds no age of its own.**

| sport | producer, role | per-tick work | the wait that sets the cadence | state time (`liveStateAsOf`) |
|---|---|---|---|---|
| NBA | `nba/live_resim.py` own thread (`start_nba_live_resim_loop` `:2065`, started from `live_lens_loop.py:1309`), live-odds-worker; `SYNDICATE_NBA_LIVE_RESIM=on`, `_SIMS=100` (local_production.env) | scoreboard, then per live game (stalest first) one ESPN summary + re-sim until the 240 s budget (`:101`, `:1577-1650`); `generatedAt` stamped at the END (`:1666`) | `_LOOP_STOP.wait(_interval_seconds())` after each tick (`:2056-2062`): **120 s** default, `SYNDICATE_NBA_LIVE_RESIM_INTERVAL_SECONDS` unset (`:1861-1866`) | the summary's build time (`resume_from_summary` `:290`), so state is read BEFORE the tick is stamped |
| NCAAF | `_run_ncaaf_live_resim_tick` (`run_refresh_worker.py:2700`), called once per refresh-worker main-loop iteration (`:8526`) | live-state record first (`_ncaaf_live_resim_live_index` `:2272`), ESPN scoreboard fetch only when the record is older than **120 s** while a game is live (`:2131-2165`); re-sim budget 120 s (`:1834`) | the tick's own floor `max(75, 6 x last elapsed)` (`:1850-1877`), BUT it fires only when the main loop comes round: a stack of stages plus `_sleep_reacting_to_live_pulls(poll_seconds)` (30 s, `:266`, `:8947`) | the record's or the fetch's `as_of` (`:2378`); `generatedAt` stamped at the start of the build (`ncaaf/live_resim.py:1317`) |
| NHL | `nhl/live_resim.build_live_lens_snapshot` (`:1011`), one sport in the shared live-lens loop (`live_lens_loop.py:264`), live-odds-worker | `generated_at` stamped first (`:1041`), then `fetch_score_rows`, then per-game re-sim (budget 25 s, `:134`) and the box capture | the loop builds mlb, nba (lens), wnba, soccer, nfl, nhl serially, runs a publish sweep, then `_LIVE_LENS_LOOP_STOP.wait(interval)` (`:1287`): **60 s** (`SYNDICATE_LIVE_LENS_INTERVAL_SECONDS=60`, fleet_env) | the score fetch's time (`:558`), just after `generatedAt` |

## 2. Measured on the fleet (read-only, nice 19)

**From the live evidence log**, dev 11-09..11-14. Fresh lanes only (no refusal, not carried, with a win probability and a readable clock). Late = share >= 0.95. Script: `C:\tmp\r836\cadence.py`.

| sport | games | new-state gap p50 / p90 (s), before 95% | same, last 5% | publish lag `t - as_of` p50 / p90 (s) | E[age] at a random instant (s), last 5% | engine read's measured age p50 / p90 |
|---|---|---|---|---|---|---|
| NBA | 43 | 151 / 186 | 140 / 169 | +13 / +43 (late +1 / +4) | 77 | 69-76 / 130-144 (95 / 163 late) |
| NCAAF | 48 | 154 / 342 | 153 / 308 | +40 / +93 (the record's age) | 129 + 40 | 104-113 / 208-269 |
| NHL | 43 | 91 / 128 | 84 / 110 | -1 / 0 | 46 | 39-63 / 70-102 |

**From the role logs** (live-odds-worker.log.1/.2, 11-16..11-18):
- NBA ticks with re-sims had elapsed p50 14-19 s, p90 106-223 s, max 245 s. Tick-to-tick p50 132-138 s, p90 226-343 s. The 120 s wait is the larger term at p50; the 240 s budget binds at peak.
- Live-lens loop cycle (TICK_COMPLETE to TICK_COMPLETE): p50 72-77 s, p90 99-114 s, max 345-372 s. That is 60 s of wait plus ~15 s of all-sport work.

**NCAAF** (refresh-worker.log.3, 11-13 17:59Z .. 11-15 06:05Z; 436 ticks with live games):
- Elapsed p50 8.9 s, p90 25.3 s.
- The gate `max(75, 6 x elapsed)` was p50 75 s, but the realised gap after a live tick was p50 142 s, p90 245 s. **So refresh-worker's main-loop cycle binds, not the gate.**
- 384 of 436 live ticks (88%) were served from the live-state record. 52 fell back to an ESPN fetch (`record_stale`).

**Hypothesis (lane block): HELD.** Each producer's loop explains the measured medians within ~10 s. The evidence log's 30 s poll explains none of it.

## 3. Who prices or bets from a re-sim probability late in a game

Survey of `syndicate/`, `pipeline/` and `scripts/`. The rows I could check, I re-read myself.

| consumer | reads the re-sim at | state-age check | clock rule | money |
|---|---|---|---|---|
| board join `live_gameline_join.attach_live_gamelines` | ML `home_win_prob`, distributions; writes `live_aware`, the live probability and edge | lane age `lane_age_verdict` (`:843`): NBA / NCAAB / WNCAAB 600 s, NCAAF / NFL 1,800 s (`:792-798`), default ON; **NHL, MLB, WNBA, soccer not gated** | none | feeds board ranking, Layer 2, the plan |
| Layer 2 board / `live_edge_policy` / `opportunity_gate` | `model_edge_pct` on live-aware rows | quote age only (book <= 900 s, observed <= 300 s) | none | ranking / shortlist |
| `portfolio_commit` | sizes from `model_edge_pct` | none | `_refuses_in_play_market_fair` refuses only rows WITHOUT a model edge (`portfolio_commit.py:575`), so re-sim rows pass | plan, live and paper |
| `execute_portfolio`, LIVE | | | refuses Kalshi entries after `commence_time` (`execute_portfolio.py:902-943`; switch `:221-224`, unset on every role = ON), and Polymarket's (`polymarket_us_orders._refuse_after_commence`); only `fair_source == "in_game"` is exempt (`:213-219`), which nothing sets | **live money: blocked in play** |
| `execute_portfolio`, PAPER books | same positions | none | no after-kickoff check found | **paper: re-sim in-play bets, late in games too** |
| in-play program `inplay_entries_paper` / `_live` | **not the re-sim**: `FAIR_VERSION = "inplay_book_median_novig/1"` (`inplay_entries_paper.py:48`) | book quotes <= 120 s | 180 s after a score | live Kalshi, not from the re-sim |
| cheat sheets `build_cheat_sheets.py` | pregame props only (`:189`, `:343`); a started game keeps its last pregame rows (`:941`) | n/a | n/a | none in play |
| rail "MODEL ≠ LINE" flag | the join's live number (`intelligence.html` LIVE RAIL block) | quote <= 120 s at pricing | none | display |
| props `live_projection_join` | NBA / NCAAB re-sim `liveProps` | **no snapshot-age check found** | none | ranking / plan / paper |
| engine experts `live_resim_expert` | `modelHomeWinProb`, distributions (`engine_experts.py:674-692`) | evidence <= 900 s (`:137`, `:666`) | records the clock bucket (`:664`), never refuses on it | shadow (M2 / M3 run on pinned code) |

**What this means for the fix:**
- The money the staleness costs today is **paper** money, plus board rows and the rail flag shown to the user.
- It is also the **future in-play entries**: execute_portfolio's comment says in-play entries come back once there is a measured in-game fair, and the decision engine's live experts are being built to be that fair.
- Two settings would put re-sim edges in front of live Kalshi with no late-game rule anywhere on the path: `SYNDICATE_EXECUTION_KALSHI_PREGAME_ONLY=off`, or a plan position stamped `fair_source="in_game"`.

## 4. The two fixes

| | faster refresh in the last ~3 min | refuse a stale late opinion / price |
|---|---|---|
| code | three producers on two roles. NBA: a late-game fast path inside one thread. NHL: out of the serial live-lens loop into its own thread. NCAAF: off the main loop, plus an ESPN fetch on every tick (the record is up to 120 s old by design) | one pure predicate (`live_endgame_freshness.py`) at two seams that already gate on age: the join's staleness choke point and the expert's evidence check |
| CPU | new periodic work on live-odds-worker and refresh-worker in exactly the hours the host is saturated (#832: 100% busy at 59-64% of nominal clock) | none |
| reaches the target? | only if every producer gets under ~25 s including its fetch and sim, and the board then reads it before serving | yes, by construction, for the consumers wired |
| measurable before loading? | no | yes: the re-measure below |
| its payoff rests on | the fresh cell (-0.048), which is 14 games and two NBA games (section 5) | the stale majority: 767 line-instants, 85 games, +0.174 (0.053) |

**Recommended: the refusal.** A faster late refresh can follow if a held-out read shows that fresh late states really do beat Kalshi.

## 5. Re-measure (dev 11-09..11-14 only; nothing of M2's 11-15..11-22 or M3's windows)

Script `C:\tmp\r836\staleness_836.py`, output `C:\tmp\r836\staleness_836.out`. It is `staleness.py` with the same joins, weights and game-clustered se, plus the true state age (line instant minus the evidence row's own `as_of`, joined from the fleet's evidence log). The state time was found by event id for 42,329 of 54,173 line-instants, as the only state in its tick for 5,822, as the oldest state in its tick for 1,006, and not found for 5,016.

**Reproduction (the kit's age), re-sim minus Kalshi log loss (se):**

| clock | 0-30 s | 30-60 s | 60-120 s | > 120 s |
|---|---|---|---|---|
| 75-95% | +0.023 (0.016) n 1,782 | +0.023 (0.022) n 1,655 | +0.033 (0.016) n 3,080 | +0.043 (0.036) n 1,700 |
| 95-100% | **-0.048 (0.019) n 62** | +0.208 (0.080) n 163 | +0.109 (0.075) n 387 | +0.264 (0.078) n 217 |
| overtime | +0.040 (0.076) n 7 | +0.096 (0.010) n 39 | +0.098 (0.009) n 33 | - |

The 95-100% row matches the engine read exactly. By true state age, 95-100% reads 0-30 s -0.048 (0.019) n 61, 30-60 s +0.251 (0.163), 60-120 s +0.086 (0.070), > 120 s +0.334 (0.115).

**The rule applied (refuse when the age is over 30 s):**

| scope | all | kept | refused | refused share |
|---|---|---|---|---|
| 95-100%, kit age | +0.162 (0.050) n 829 | -0.048 (0.019) n 62 | **+0.174 (0.053) n 767** | 92.5% |
| 95-100%, true age | +0.169 (0.059) n 686 | -0.048 (0.019) n 61 | +0.186 (0.063) n 625 | 91.1% |
| overtime | +0.096 (0.009) n 79 | +0.040 (0.076) n 7 | +0.097 (0.007) n 72 | 91.1% |
| 95-100% NBA | | -0.036 (0.021) n 39 | +0.120 (0.072) n 485 | 92.6% |
| 95-100% NCAAF | | 1 line-instant | +0.249 (0.081) n 242 | 99.6% |
| 95-100% NHL | | -0.070 (0.042) n 22 | +0.051 (0.106) n 40 | 64.5% |

**The kept cell is thin.** It holds 62 line-instants from 14 games. NBA 401909961 (19 instants, mean -0.496) and 401909957 (19, +0.004) carry 38 of them. The threshold sweep is not monotone: kept <= 45 s is already +0.178 (0.096). The 30 s bound came from the engine read's table on these same dates, so this data cannot validate it. **Held-out check: the 95-100% rows of the engine re-read registered for 11-24 (lane engine-learner).**

**What the refusal is worth:** the end game stops counting a number that loses to Kalshi by ~0.17 nats on ~92% of late line-instants. It is not a claim that the remaining ~8% beat Kalshi.

## 6. Built

- `syndicate/features/shared/live_endgame_freshness.py`: the pure rule. `endgame_verdict(sport, period, clock_seconds, as_of, now)`. Last 5% of regulation or overtime, state older than 30 s, gated sports NBA / NCAAF / NHL. Its clock table is pinned equal to `engine_experts.SPORT_CLOCK`. Switch `SYNDICATE_LIVE_ENDGAME_FRESHNESS`: absent = shadow, `off`, anything else = on. Override `SYNDICATE_LIVE_ENDGAME_MAX_STATE_AGE_SECONDS`.
- `tests/test_live_endgame_freshness.py`: 47 passed. They cover the switch, the clock (identical to the experts' on every state, the 95% boundary, overtime), the 30 s boundary, the absent-time refusal, clock skew and the override.

**Wiring: needs two loans.** The guard blocks both files. Nothing is wired yet.
- `live_gameline_join.py`, `attach_live_gamelines`: the switch read at the top, the verdict at the staleness choke point after the lane-age verdict, and the shadow tally plus one `LIVE_ENDGAME_FRESHNESS` print after the loop. Full-game hits only; the hit already carries `state_period`, `state_clock_seconds` and `as_of` (`:1174-1184`). Segment hits carry no state and are not judged.
  - The only holder is `live-player-exit-gate`, matched through a prose note in its `Files:` line ("no OPEN lane lists ... live_gameline_join.py ...").
- `engine_experts.py`, `live_resim_expert`: refusal `live_state_stale_in_endgame` after the clock bucket is known, behind the experts' own off list. Also records `state_age_s`, the true age, on every opinion. Lane `engine-live-prior`.

**EXPERT WIRED LOCALLY 2026-11-18 ~12:05 PM CST, NOT ON MAIN** (local `82908b24c` on `e75eadfde`, pinned `refs/keep/live-resim-endgame-staleness-82908b24c`): `live_resim_expert` judges the end game on the state's own `as_of`, after the existing refusals. `SYNDICATE_LIVE_ENDGAME_FRESHNESS` absent = shadow: it records `state_age_s` + `endgame_freshness` and refuses nothing; `on` refuses `live_state_stale_in_endgame`; `off`, or `endgame_freshness` in `SYNDICATE_ENGINE_EXPERTS_OFF`, leaves the opinion as before. Tests: 53 in `test_live_endgame_freshness.py`, incl. off != on through `live_resim_expert` and the NBA tick-after-state case (evidence_age_s 5, state 45 s, refused); 184 passed with the experts / learner / college-segment suites. Evidence `as_of` fill 93.6-100% per sport on 11-14, so no CONSUMED_UNPOPULATED alarm. Landing on main needs the user's own yes IN THIS SESSION (e2f5878d; corrected by the decision-engine session ~12:10 PM CST, which recorded the loan). The join gate still needs its loan (live-player-exit-gate or the user).

**ON MAIN 12:11 PM CST (user "Push it", this session): `3a04f43b0` (`live_endgame_freshness.py` + tests) + `18d036bef` (`live_resim_expert` end-game rule, loan from engine-live-prior).** Absent switch = shadow. No worker or web role imports either file, so a fleet ff loads nothing from them; the fleet hold to 11-22 stands. 184 passed (experts / learner / college-segment / this lane's 53) on the pushed base. Not a deploy, no betting change. Still owed: the join gate (`live_gameline_join.py`, loan from live-player-exit-gate or the user), its off != on test through `attach_live_gamelines`, then the shadow load after 11-22.

**JOIN GATE WIRED LOCALLY 2026-11-18 ~12:50 PM CST, NOT ON MAIN** (local `ab18a9c91`, pinned `refs/keep/live-resim-endgame-staleness-ab18a9c91`; loan from live-player-exit-gate, user "Lend it" 12:28 PM CST): `attach_live_gamelines` judges full-game NBA / NCAAF / NHL hits in the end game LAST at the staleness choke point. Absent switch = shadow (prices unchanged; `endgame_judged` / `endgame_would_refuse` / `_priced`, one `LIVE_ENDGAME_FRESHNESS` line per build per sport that judged a row); `on` withholds the edge (`live_state_stale_in_endgame`; the live display stays). Tests: 61 in `test_live_endgame_freshness.py`, incl. off != on through `attach_live_gamelines` and through `board_enrichment.attach_live_gamelines_for_sport` on the wall clock; 1,646 passed over the 78 test files that touch the join. Push to main awaits the user's yes; once on main, ANY later fleet ff loads the shadow tally (no price changes).

**JOIN GATE ON MAIN 12:50 PM CST (user "Push it", this session): `52e68382a`.** All three #836 pieces are now on main (`3a04f43b0` rule, `18d036bef` expert, `52e68382a` join), every one shadow when `SYNDICATE_LIVE_ENDGAME_FRESHNESS` is unset: not a betting change (windows rule 1), so any fleet ff may carry it. Re-run on the pushed base: 122 passed (this lane's 61 + the lane-age gate's); the 78-file join suite (1,646) ran on `6fdad22ee` and no join file changed since. Owed: (1) the first live evening's shadow reading after a fleet ff carries it (`LIVE_ENDGAME_FRESHNESS` lines on the role that builds the board: judged / would_refuse / would_refuse_priced per sport); (2) the pinned-experts repro check with it on (JOIN / PRIOR = 0); (3) `on` only in a window, earliest 2026-12-08, with the user's yes.

**Reachability, owed with the wiring:** a test through `attach_live_gamelines` itself. A last-5% NBA lane 45 s old must be priced under `off` and `shadow` (and counted under `shadow`), and refused `live_state_stale_in_endgame` under `on`. Under `on`, a 20 s lane and a 45 s lane at 90% elapsed must be priced. `off != on` on the same input.

## 7. Load plan (the user's decision; nothing loaded)

**BETTING-CHANGE WINDOWS (user 2026-11-18 "batch the betting changes into rare windows", `002a7e720`, `.syndicate/betting_change_windows.md`; relayed by session local_d7643dac):** the join gate and the expert rule as built are SHADOW when the switch is unset, which rule 1 lists as not a betting change, so they may land on main and load at any time. Switching `on` is treated as a betting change (the decision-engine session's classification; it changes the paper books' in-play bets and the board's late-game edges) and loads only in a window. The 11-24 window (08:00-13:00Z) closes before M2's 11-24 read, and the gate must stay shadow through that read and while M3 runs, so the earliest `on` is the 2026-12-08 window (08:00-13:00Z = 2-7 AM CST), after the pinned experts' JOIN / PRIOR reproduction lines read 0 on one slate with it on, and with the user's yes.

**LOANS 2026-11-18 ~11:50 AM CST (reply from the decision-engine session local_898e5510):** (1) `engine_experts.py` `live_resim_expert`, lane engine-live-prior: GRANTED, user "Yes, lend it" 11:42 AM CST (typed in session e32fef1a; recorded by that lane in `cc5ad8471`), off by default, landing on main needs its own yes; M2 and M3 run their own pinned copies (`981ef14f6`, hashed in the kits), so an edit on main cannot touch either gate. (2) `live_gameline_join.py`: not that session's to lend; lane live-player-exit-gate (session 86352bc9) or the user decides; put to the user in this session. **ENABLING PRECONDITION (same reply):** keep the join gate SHADOW through M2's 11-24 read and while M3 runs; the pinned experts' reproduction checks (JOIN and PRIOR in `engine_paper_m3.REPRO_LINES`, `engine_paper_m3.py:359-366`) compare against the board's live lines, so `on` could fail a sport's reproduction and that slate then places no M3 bet. Before any `on`: run the pinned experts on one slate with the gate on and check those lines read 0.

**DO NOT LOAD BEFORE 2026-11-22 ENDS (decision-engine session local_898e5510, 2026-11-18 ~11**:40 AM CST, relayed as an addition to this lane's brief): M2's test window (11-15..11-22) and the learner study's re-run window both end then, and holding keeps them on the re-sims they started with. After that a load still needs the user's own yes and is a betting change (`scripts/betting_change.py`); M3 tags each bet with its live re-sim version (`findings_2026-11-17_m3_paper_book.md` Addendum 5), so a load after 11-22 does not confound M3.

**Shadow first**, as the lane-age gate did (2026-11-07):
- An ff to the wiring commit loads the shadow tally only: prices are unchanged, and each build that has a would-refuse prints a `LIVE_ENDGAME_FRESHNESS` line.
- After one live evening's reading, the user decides `on`: a code-default flip plus an ff, or `LIVE_ODDS_WORKER__` / `REFRESH_WORKER__` env plus a drained `down`/`up`.

**Betting change: yes** (the decision-engine session's classification, 11-18; the conservative one). Shadow changes no price; `on` changes no LIVE order today (the executor refuses in play) but changes the paper books' in-play bets and the board's late-game edges.

## 8. Leads (not this item)

- **NBA / NCAAF age understatement in the experts.** `EvidenceIndex.instant` takes max(tick, `as_of`). For NBA the tick is stamped after the states are read (lag p50 13 s, p90 43 s before the end game), and NCAAF's state comes from a record 40-93 s older than its tick. The engine's `a<=60` prior-age cells and any study binned on `evidence_age_s` are therefore younger than the state they describe. The wiring above records the true age beside it.
- NHL / MLB / WNBA / soccer game-line lanes have no lane-age ceiling at the join (`live_gameline_join.py:792-821`).
- The props join (`live_projection_join`) checks no snapshot age.
- Paper mode places in-play bets with no after-kickoff check.
- NCAAB / WNCAAB / WNBA / NFL re-sims are not covered by this read (no Kalshi prior in the engine read). Gate them only after a read.


## Shadow reading and M3's reproduction check (2026-11-20 10:11 AM CST, lane `engine-learner`, user "fix gap")

The two follow-ups this lane left unowned at its close are now owned by lane `engine-learner` (session e32fef1a).

**Shadow reading.** The fleet has carried `52e68382a` since the 11-18 evening (fleet HEAD `38c3a6905`), so the shadow
tally has run on two live evenings. Source: `refresh-worker.log.1` + `refresh-worker.log` on the fleet, every
`LIVE_ENDGAME_FRESHNESS` line, 2026-11-19 02:19Z to 2026-11-20 05:50Z (8:19 PM CST 11-18 to 11:50 PM CST 11-19), mode
`shadow` on every line, `refused` empty on every line. Counts are row-builds (a row is judged again on every build).

| sport | builds with an end-game row | judged | would refuse | share | of those, priced now |
|---|---|---|---|---|---|
| NBA | 23 | 3,665 | 542 | 15% | 346 |
| NCAAF | 25 | 529 | 138 | 26% | 88 |
| NHL | 99 | 589 | 301 | 51% | 30 |

- "Priced now" is the board's late-game edges the gate would withhold when `on`: 346 NBA and 88 NCAAF row-builds over
  two evenings; NHL's would-refuse rows are mostly unpriced already.
- The share is far below the dev re-measure's 92.5% (section 5). That figure was over evidence-log line-instants; this
  one is over board rows per build, judged at build time. They are different populations, so this is not a
  contradiction, but the board's own share is the one `on` acts on.
- NHL alternates build to build between 0 and all 5 judged rows refused: its serial live-lens loop refreshes about every
  60 s while the board builds about every 30 s.

**M3's reproduction with the gate `on`.** M3's pinned experts (`981ef14f6`) check JOIN and PRIOR only on the ledger's
PRICED records (`live_state_as_of` present); a refusal record is `ledger_refusal_row` and opines nothing.
- Run on main's code (exported to `C:\tmp\elp\t836read\main_src`), with the join test's own fixture (NBA, Q4 1:00):
  - shadow, state 45 s: priceable, 1 ledger record in the priced half;
  - `on`, state 45 s: withheld `live_state_stale_in_endgame`, **0 ledger records** (neither half);
  - `on`, state 10 s: priceable, 1 priced record, as before.
- So a gated row never reaches the pinned checks, and switching `on` cannot add a JOIN or PRIOR mismatch: reproduction
  stays at 0 by construction. Its effect on M3 is fewer end-game opinions, hence fewer end-game bets. M3's morning
  capture records the switch as a new version (`SYNDICATE_LIVE_ENDGAME*` is on the 5b allowlist).
- Lead, not fixed: a withheld end-game row leaves no ledger record at all, as every staleness reason above the attach
  site does, so the ledger cannot show the gate's population afterwards; the `LIVE_ENDGAME_FRESHNESS` lines are the
  only record of it. Script: `C:\tmp\elp\t836read\repro_on.py`; reading: `summ.py`.

**What is left:** switching `on` (`SYNDICATE_LIVE_ENDGAME_FRESHNESS=on`; betting change yes; drained full down/up) in the
12-08 window at the earliest, on the user's own yes. It is on the 12-08 candidate list under `#846`.
