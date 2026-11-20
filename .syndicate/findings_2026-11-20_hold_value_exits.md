# Hold-value exits (todo #856, optimization lever L1) — pre-registration, build, load plan, 12-08 predictions

Lane `hold-value-exits` (session ffd41dea). Loan of `execution_exits.py` sections from `kalshi-exit-path`.

**Authorisation.** The user, 2026-11-20 ~9:50 AM CST, answering "Start a session to build hold-value exits
default-off with a shadow log?" in session 3bf4646c (lane `product-optimization-program`): "Yes, start it".
That approves the default-off build, the shadow log and landing both on main. It does NOT approve any
fleet load (the shadow is not a betting change but still needs the user's explicit OK, claims and a
preflight) or switching the rule on (a betting change: a window, and the user's call).

Evidence it rests on (`findings_2026-11-18_product_optimization_program.md` §3.1 L1; pass B
`C:/tmp/optprog/B_exits.py` / `B_exits_out.txt`, read-only): exited live bets sold below what holding
paid. Exit price minus settled outcome −2.10 pp [−5.88, +1.69] (559 bets / 374 events / 30 dates),
−3.74 [−8.73, +1.24] since 11-03 (295 / 192 / 16). Exit fees 0.83-0.95 pp of book stake, 2.45-2.65% of
exited stake. Net exit effect since 11-03 −2.56 [−7.50, +2.37] pp of book stake. Fails BH (p 0.28 /
0.14 in a 182-test family); LODO holds. Worth ≈ $0.5/day, ceiling $1.58/day, at $61.75/day staked.

## 1. What exists today (read 2026-11-20 09:30-09:50 AM CST, `origin/main` `df7901fe8`)

- `execution_exits.evaluate_exit` computes two rules on NET figures (`net = bid − exit fee / contract`):
  - `take_profit`: `net − entry_cost_per_contract >= margin` (fleet margin 0.10, EXIT_TICK 11-20 15:46Z).
  - `model_fair`: `net >= model_probability_at_entry + SYNDICATE_EXIT_FAIR_MARGIN`. This is the lane goal's
    "or >= model fair" variant. It is the RAW model view AT ENTRY (fair + model edge), not a current fair,
    and it is PAPER ONLY on the fleet (`SYNDICATE_EXIT_LIVE_RULES` absent = `take_profit`).
- Both callers use `evaluate_exit`: the slow tick (`_run_exit_tick_unlocked`, live-odds-worker execution
  tick, ~5-9 min) and the in-game fast loop (`execution_exits_fast.mark_pass`, 15 s, in-play Kalshi only,
  which hands live triggers back to `run_exit_tick(orders=...)`).
- Which rule fired IS recorded on exit rows (`rule`), but not on the portfolio payload; nothing records it
  on ticks that did not book a first exit.
- The only CURRENT consensus fair the live-odds-worker holds for a Kalshi contract is the executor's plan
  sighting (`kalshi_maker_pilot._seen["<ticker>|<leg>"] = {"fair": P(price) x (1 + ev_pct/100), "at":
  epoch}`), written for every live Kalshi plan position at the top of `execute_portfolio`'s loop while
  `SYNDICATE_KALSHI_MAKER_PILOT` is on (it is on the fleet). `ev_pct` is on market fair (#704); the maker
  review measured it within ~1 pp of the book consensus. The exit tick runs BEFORE the executor in the
  same tick and process, so a sighting is at most one execution tick old when the plan still names the
  contract.
- Sizing (EXIT_TICK 2026-11-20 15:37Z / 15:46Z): positions 336 (live 31; Kalshi 259 / Polymarket 75-77),
  quoted 241-243, `triggered` 65-67, `near_settlement_hold` 24-25.

## 2. PRE-REGISTRATION (frozen 2026-11-20 ~10:00 AM CST, before any code, shadow row or outcome)

### 2.1 The rule

`SYNDICATE_EXIT_HOLD_VALUE`: absent / anything unrecognised = `off` (today, byte-identical); `shadow` =
today's decisions + the shadow log; `on` = the gate decides + the shadow log.

Per position, per evaluation, after today's two rules are computed:

- **Hold value** (per contract, the fair probability that our leg settles $1):
  - `consensus`: the plan sighting for `<ticker>|<leg>`, used only when its fair is set, its age is
    <= `SYNDICATE_EXIT_HOLD_VALUE_MAX_FAIR_AGE_SECONDS` (default 1800), and the game has NOT started
    (`_is_in_play` is explicitly False). In play the book consensus lags Kalshi (learnings 2026-10-21),
    so it is never a hold value there.
  - else `venue_mid`: (our leg's bid + our leg's ask) / 2, the ask being the leg's own ask field when the
    venue gives one, else 1 − the other leg's bid.
  - else `none` (no two-sided book): the hold value is unknown.
- **Would exit** iff `net − hold > exit_fee_per_contract` (the net bid beats the hold value by more than
  the exit fee). Unknown hold → would NOT exit (an unknown must not default to selling).
- **ON:** `take_profit` stays in the rule set only if the position would exit. `model_fair` is untouched
  (paper only on the fleet). A position the gate stops reports reason `hold_value_hold`.
- Consequence stated before any data: the bid never exceeds the mid, so a `venue_mid` hold value can
  never clear the bid; under ON a position sells on take-profit only when a fresh pregame consensus says
  the venue's bid is rich by more than two exit fees. Every position is its own decision; there is no
  market, sport or phase switch.

### 2.2 The shadow log

`reports/intelligence/execution_exits_hold_value/shadow_<UTC date>.jsonl` under the fleet's reports root,
appended by the slow tick (and by the fast loop's dispatches into it, marked `tick=dispatch`):

- every LIVE position, every tick, with today's reason and rule (`today_rule`), and where a bid exists:
  bid, ask, mid, exit fee per contract, net, entry cost, hold value, `hold_source`, consensus fair and its
  age, `would_exit`, `hv_edge` (net − hold) and the threshold;
- PAPER positions only when today's rule set holds `take_profit` or the gate would exit, once per
  (entry, today-take-profit, would-exit) state per process. A row per paper position per tick would be
  ~12 MB/day at 336 positions; the grade needs only the first trigger.

### 2.3 Grading rule (script `scripts/exit_hold_value_shadow_grade.py`)

- **Window:** shadow rows from the first one written after the load through 2026-12-06 23:59:59 CST;
  positions whose game starts on or before 2026-12-06 (Central).
- **Outcomes:** the execution ledger's `outcome` (`full_history_orders`), joined on `idempotency_key` =
  `entry_key`, read at the verdict. Only `won` / `lost` count; push, void and ungraded are counted and
  reported, never scored as 0.
- **Primary population P (the DIFFER population):** entries with `entry_mode=live`, `family=kalshi`,
  `entry_phase=pregame` (the only phase sold live today). T1 = the earliest row whose `today_rule`
  contains `take_profit`. In P iff T1 exists, `would_exit` is False at T1 (today sells, the new rule
  holds), and the outcome is won/lost.
- **Arms**, per contract, both valued on the shadow's own bids:
  - today: `value_today = net` at T1;
  - new: `value_new = net` at T2, the earliest row at or after T1 with `take_profit` in `today_rule` AND
    `would_exit` True; else the settlement value (1.0 won / 0.0 lost).
- **Metric:** `EmH_i = 100 x (value_today − value_new)`, exit-minus-hold in pp per contract, one value
  per position (flat). Negative = selling paid less than the new rule.
- **Estimator:** the mean over P; 95% CI = mean ± 1.96 x the event-clustered SE (cluster = the ledger
  order's `event_id`, else the ticker up to its last `-`): SE = sqrt(Σ_g (Σ_{i∈g} (x_i − m))²) / N x
  sqrt(G / (G − 1)) (pass B's `clus` with unit weights).
- **LODO:** the mean with each game date (Central) left out in turn.
- **Minimum sample:** >= 60 distinct events AND >= 80 positions in P.
- **Verdict date:** Mon 2026-12-07, at or after 12:00 PM CST (before the Tue 12-08 2-7 AM CST window).
- **Instrument checks (any failure = INVALID, no verdict):**
  - I1: zero rows with `hold_source=venue_mid` and `would_exit` True (the structural invariant).
  - I2: >= 95% of the window's LIVE take-profit sales (exits document + archive, `mode=live`, `rule`
    containing `take_profit`, `submitted_at` in the window) have a shadow row for that entry with
    `take_profit` in `today_rule` at or before `submitted_at` and no more than 15 minutes earlier.
- **Verdict:**
  - INVALID if I1 or I2 fails.
  - INSUFFICIENT if the minimum sample is not met: no 12-08 recommendation; the same rule is re-read for
    the 12-22 window.
  - SUPPORT if mean EmH < 0 AND every LODO mean < 0. Labelled STRONG when the CI's upper bound < 0, else
    WEAK (CI spans 0).
  - AGAINST if mean EmH >= 0.
  - INCONCLUSIVE otherwise (mean < 0 but some LODO mean >= 0).
- **Reported, never decisive:** S1 the share of first take-profit fires the gate holds (hypothesis >=
  80%); S2 the contract-weighted mean; S3 the same metric on paper positions; S4 the break-even variant
  (would exit iff net − hold > 0); S5 splits by `hold_source` and `in_play` at T1; S6 actual live fills
  vs the shadow's net at T1 for the today arm; S7 hold-source coverage over live pregame-entry rows; S8
  the count of P positions whose T1 hold source was `consensus` and that were then sold live in full
  (no later tick can be observed, so `value_new` falls to settlement; flagged if > 10% of P).

### 2.4 Hypothesis and falsification

- **H:** the gate holds >= 80% of first take-profit fires (S1), and on P mean EmH < 0, of the order of
  L1's −2.10 / −3.74 pp.
- **Falsified** if, with the minimum sample met, mean EmH >= 0 (AGAINST) or the CI lies wholly above 0.

## 3. Build — on main `ace2020d3` (2026-11-20 ~10:35 AM CST), DEFAULT OFF, NOT LOADED

Written after §2 was pushed (`923596e4d`). Nothing below changes §2.

- `syndicate/features/shared/exit_hold_value.py` (NEW): the switch (`hold_value_mode`, exact words only),
  `max_fair_age_seconds`, `consensus_sighting` (reads `kalshi_maker_pilot._seen`, never raises), `leg_ask`,
  `assess` (pure given the sighting reader), `failed_assessment`, `apply_gate`, `ShadowTick` (collects and
  writes one tick's rows; inert when off), `grade_shadow` (§2.3, pure), `read_shadow_rows`.
- `execution_exits.py` (the three loaned sections only): the gate at the end of `evaluate_exit`; the
  `ShadowTick` hook + the `hold_value` summary key in `_run_exit_tick_unlocked`; the `hold_value=` field in
  `exit_tick_line`. Off: the decision dict, the tick summary, the EXIT_TICK line and the exits document are
  exactly as before. An assessment that raises reads as an UNKNOWN hold value (shadow: today's rules
  stand; on: it holds). A shadow write or observe failure is counted and never breaks the tick.
- The gate lives in `evaluate_exit`, which the fast loop already calls (`execution_exits_fast.mark_pass`),
  so the fast loop obeys it with no edit to that file (lane `in-game-trading`'s).
- `scripts/exit_hold_value_shadow_grade.py` (NEW): the §2.3 grade, read-only, registered defaults; any
  other parameters print `registered_parameters: false` and an EXPLORATORY note.
- `tests/test_exit_hold_value.py` (NEW, 40 tests): switch parsing; absent = today (the decision's key set
  pinned, `off`/garbage equal absent); shadow = today's decision + only the assessment; off != on on the
  decision and on the tick (OFF books the paper exit, ON books none and reads `hold_value_hold`); the
  mid-never-clears-the-bid invariant over a grid; consensus pregame-fresh only (in play / stale fall to
  the mid; the age switch reaches); `model_fair` untouched; unknown hold holds; the pilot's own
  `note_plan_sighting` feeds `consensus_sighting`; the shadow document identical to absent except
  `last_tick.hold_value`; paper first-trigger logging; error paths; REACHABILITY through the worker's
  `_exit_tick` (orders from the ledger: rows are `tick=slow`) and the fast loop's `mark_pass`; the grader
  on hand-computed numbers (A −30, B −7, C +60; clustered SE by hand), SUPPORT/AGAINST/INSUFFICIENT/
  INVALID (I1 and I2), exclusions, and the script on files.
- Test runs (Windows, `python -m pytest`): the new file + `test_execution_exits.py` +
  `test_execution_exits_fast.py` + `test_exit_sliver_retry.py` + the maker-pilot tests 176 passed; ten more
  exit/settlement files (`test_exit_hold_near_settlement.py`, `test_paper_settlement_exits.py`,
  `test_venue_settlement_*`, `test_kalshi_fractional_counts.py`, ...) 215 passed; after the rebase onto
  `origin/main` the three core files 127 passed.
- Fleet facts read for the design (no outcome read): `LIVE_ODDS_WORKER__SYNDICATE_KALSHI_MAKER_PILOT=on`
  in `local_production.env`, so the sightings the consensus reads are being written; fleet HEAD
  `38c3a6905` (11-20 ~10:10 AM CST) does not carry this build.
- **Betting-change classification: `no` while absent or `shadow`** (decisions and documents equal OFF,
  by test, per the 11-18 rule). **`on` is `yes`.**
- Not built: pruning of the shadow files (~3 MB/day of live rows; the grade needs the whole window), and
  `HOT_ARTIFACT_PATTERNS` (an output read on the fleet by a script, not a web input).

## 4. Load plan for the SHADOW — the user's decision (NOT approved yet)

Loading is an env change: `LIVE_ODDS_WORKER__SYNDICATE_EXIT_HOLD_VALUE=shadow` in
`~/syndicate-prod/local_production.env`, which only a drained full `down`/`up` picks up, on a checkout
that carries `ace2020d3`. It is NOT a betting change, so it may load at any time — but only with the
user's explicit OK, claims and a preflight (`--betting-change no`).

- **Recommended: ride the 11-24 window batch** (task `nfl-level-refit-load-1120`, Tue 11-24 2:15 AM CST,
  ONE ff to a TARGET cut from `origin/main` then, plus ONE drained full down/up). Its ff carries
  `ace2020d3` anyway (inert while absent; its ride-along gate will list it). Adding the shadow costs one
  env line in the same down/up, as a droppable CHANGE H:
  - kit `C:/tmp/hv856/kit_env_856.sh` (`check | apply | restore <backup>`; prints only this key; backup
    first; idempotent; refuses nothing but never writes `on`). Self-tested 2026-11-20 10:15 AM CST on a
    dummy file: append, idempotent re-apply, restore, mode 600 kept, real env file untouched (0 lines).
  - order: run `apply` AFTER the batch's other env kits, so a batch STOP's earliest-backup restore undoes
    it too.
  - verify after `up`: `kit_role_env.py SYNDICATE_EXIT_HOLD_VALUE` (or the kit's `check`) shows
    live-odds-worker `shadow`, refresh-worker and web ABSENT; `fleet_role_env_reading.py compare` with
    `--expect-added SYNDICATE_EXIT_HOLD_VALUE`; the first EXIT_TICK after boot carries
    `hold_value={'mode': 'shadow', 'rows': N` with N = that tick's `live=`; its `reasons` has no
    `hold_value_hold`; `shadow_<UTC date>.jsonl` exists under
    `~/syndicate-prod/data/reports/intelligence/execution_exits_hold_value/` (or the role's reports root)
    and grows by N rows a tick; 0 Traceback in the live-odds-worker log; live take-profit sales continue
    as before (EXIT_LIVE lines).
  - deploys.md: `- betting change: no` for this line (the batch's other changes are `yes`).
  - Window it buys: 11-24 ~2:30 AM .. 12-06 = ~12.9 days. At ~11 live pregame take-profit events a day
    (pass B: 179 exited events / 16 days since 11-03) that is ~140 events, over the 60-event minimum if
    the gate holds most fires.
  - Adding CHANGE H to that task's prompt changes another lane's batch: it needs the user's OK, and the
    prompt read back after the edit. If the batch STOPs, the shadow waits for the next drained down/up.
- **Alternative: a standalone drained down/up before 11-24** (e.g. Sat 11-21 morning). ~3 more days of
  shadow, including a full NCAAF/NFL weekend. Costs: a full fleet restart outside the batch (claims on all
  three services, a joint CLEAR preflight from a worktree at `origin/main`, a drain, the ride-along check
  over everything on main since `38c3a6905`), and every restart comes back LIVE. Not recommended unless
  the user wants the weekend in the sample.

## 5. Predictions for a 12-08 switch-on (`SYNDICATE_EXIT_HOLD_VALUE=on`) — written before the shadow loads

Conditional on a SUPPORT verdict on 12-07 and the user's yes. Read over the 14 days after the load
(12-08..12-21) against the 14 days before it (the shadow keeps logging under `on`).

- **P1 (the gate fires as designed):** live take-profit sales per day fall by the shadow's measured S1
  held share, ± 15 pp (H: S1 >= 80%, so a fall of >= ~65%).
- **P2:** every remaining live take-profit sale's row has `hold_source=consensus`; 0 with `venue_mid`.
- **P3:** live exit fees per day fall in proportion to P1 (± 15 pp). At the 11-03..11-18 rate that is up
  to ~$0.51/day (pass B exit fees −0.83 pp of $61.75/day).
- **P4:** in-play take-profit dispatches from the fast loop (`FAST_EXIT_LIVE_DISPATCH` carrying
  `take_profit`) go to 0: in play the hold value is always the venue mid.
- **P5 (guard: nothing else moved):** live entry orders per day within ±25% of the prior 14 days;
  `EXIT_TICK` lines every tick with no `EXIT_TICK_FAILED`; `model_fair` paper exits still book; no
  Traceback.
- **P6 (economic, noisy, NOT a revert trigger):** on the live pregame-entry positions the switch holds,
  the §2.3 exit-minus-hold continued forward is < 0.
- **Side effect stated in advance:** `on` also stops the slow tick's PAPER take-profit exits wherever the
  gate holds, so `exit_counterfactual_report.py`'s paper `take_profit` rows thin out from the load. The
  shadow rows keep today's would-be decision (`today_rule`), so nothing is lost for grading.
- **Bookkeeping at the load:** a betting change: `betting_change.py add --kind yes` (restarts the
  scale-up gate's 800-event count), `--betting-change yes` on the preflight, inside a window. Back-out:
  set the line back to `shadow` (a risk-reduction revert may use `--outside-window "revert: ..."`).
