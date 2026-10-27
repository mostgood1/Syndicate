# Decision policy v1, PAPER track — build + z fit + first reachability read `[2026-10-26, lane decision-policy-paper, Decision Engine Phase 2, #736 / todo #738]`

**Pre-registration: `8d16ab07`** (`.syndicate/findings_2026-10-26_decision_policy_v1_preregistration.md`),
committed **19:25:13Z**: before the z fit ran (19:29:55Z), before I opened any DecisionRecord, and before any
forward paper bet existed. Nothing in it has been changed. Two implementation clarifications, neither of
which changes a registered rule, are listed in section 5.

**Status: BUILT and TESTED; NOT running anywhere.** The forward test has not started. It starts when the
fleet job is enabled, which is the user's decision (section 6).

## 1. What was built

| file | what |
|---|---|
| `syndicate/features/shared/decision_policy_v1.py` | The policy (prereg §2, §4, §5): σ sources, `p_lb`, `EV_net` / `EV_lb` at the venue's ask plus the record's fee, Kelly on `p_lb` × Baker–McHale, one bet per (event, `event_concentration.axis_key`), the three strategies. Pure: no I/O, no order module. |
| `syndicate/features/shared/decision_policy_v1_params.json` | The frozen fit: z_S1, z_S2, r²_S2 cells (section 2). |
| `scripts/fit_decision_policy_z.py` | The pre-registered fit (prereg §3), offline, Idle priority. |
| `syndicate/features/shared/decision_policy_paper.py` | The paper book: booking from each heavy build's record, grading on the Pinnacle close plus final scores, the gate looks (prereg §6–§7). |
| `scripts/run_decision_policy_paper.py`, `scripts/evaluate_decision_policy_paper.py` | The job (`book` every 15 min; `nightly` = grade + read) and a read printer. |
| `scripts/local_production.py` | Two `SCHEDULED_JOBS` entries, both INERT until `SYNDICATE_DECISION_POLICY_PAPER=paper` (absent = off; off writes nothing). |
| `tests/test_decision_policy_v1.py` (22), `tests/test_decision_policy_paper.py` (19) | Hermetic. See section 4. |

**Pipeline trace** (file:line at this commit):

```
refresh-worker heavy build: pipeline/intelligence_state.py:7938 run_shadow(...)
  -> decision_record.run_shadow :1192 -> write_records :1130
     WRITES <root>/reports/intelligence/decision_records/<date>.json.gz        (the latest build per date)
scripts/run_decision_policy_paper.py book   (SCHEDULED_JOBS decision-policy-paper, every 15 min; local_production.py:1055)
  -> decision_policy_paper.run_book :319   (mode() off -> returns, writes nothing)
     -> book_build :234   per record file written in the last 3 h, newest unprocessed build per date
        -> load_grid :152 (book_grid_<date>.json for the date + next, every sport with a venue-priced record)
        -> sigma_for_record :169   S1 record.fair_v1.sigma_fair_v1 | S2 dispersion + r² | S3 inflated
        -> decision_policy_v1.evaluate :254 per (record, venue) -> select :357 per strategy -> stake_units :369
        APPENDS <root>/reports/intelligence/decision_policy_paper/bets.jsonl   (:302, first qualification only)
        APPENDS .../builds.jsonl                                               (:311, one line per build)
scripts/run_decision_policy_paper.py nightly   (decision-policy-paper-nightly, 13:45Z; local_production.py:1056)
  -> run_grade :507 -> collect_closes :373 (book_quotes D-1 and D, two streamed passes) -> close_probabilities :421
     -> grade_outcome :476 (fleet web game chips; full-game h2h/spreads/totals only)
     WRITES .../grades.json   (:560)
  -> run_evaluate :709 -> strategy_read :639 -> take_look :679
     WRITES .../reads/<date>.json (:742), .../looks.json
```

Log lines: `[decision_policy_paper] PAPER_BOOKED`, `MODE_OFF`, `PARAMS_MISSING`, `PAPER_GRADED`,
`CHIPS_UNREADABLE`, `GATE_READ`, `NO_BOOK`.

## 2. The z fit (prereg §3), run 19:29:55Z

**S1 (`sigma_fair_v1`): input check PASSED, z_S1 = 1.012.** The stage-1 held-out arrays reproduced the
published ±1σ coverage in all four families: NCAAF game 0.7165 vs 0.717; NHL game 0.7345 vs 0.735; NHL props
0.7720 vs 0.772; soccer game 0.6998 vs 0.700. That confirms the arrays are what I took them to be.

| | outcomes | games | z |
|---|---|---|---|
| pooled (USED) | 79,563 | — (NHL game and props share events) | **1.012** (coverage at z: 0.8413) |
| NCAAF game | 21,894 | 235 | 0.86 |
| NHL game | 2,930 | 141 | 0.89 |
| NHL props | 35,778 | 141 | 1.16 |
| soccer game | 18,961 | 372 | 0.91 |

**S2 (book dispersion + fitted residual): z_S2 = 0.677.**
- r² was fitted on dates 09-30..10-17 (135,116 outcomes); 27 cells were written at the three levels, every one
  with ≥ 200 outcomes.
- z was fitted on the held-out dates 10-18..10-26: 172,949 outcomes, 389 games. Coverage at z is 0.8413.
- Under σ_S2 alone, two-sided ±1σ coverage is 0.79 and ±2σ is 0.93. The held-out residual is smaller than the
  training window's, so σ_S2 is too wide and the fitted z (< 1) corrects for that.
- By sport (reported, not used): NFL 0.42, NCAAF 0.57, NBA 0.63, MLB 0.59, WNBA 0.57, NHL 0.98, soccer 1.00.

**Most important number in this section (reported, not used): against the PINNACLE close only, z would be
1.28 (S1) and 1.32 (S2).** As registered, z is fitted against "Pinnacle else the Shin-median close". The
Shin-median close sits closer to the Shin median at decision time than Pinnacle's close does. So the
registered lower bound covers the SHARP close less often than its nominal 84%. P1 will therefore admit lines
with less margin against the gate's own truth than the name "lower bound" suggests.
- This is a known, pre-data property of the registration. It is not a reason to change it now: changing it
  would be a new registration.
- It also tells us that **if P1 fails the gate, a refit of z on the sharp close is the first lever**, ahead of
  any change to the policy.
- **Scope of that lever `[2026-10-27]`:** it applies when P1 reaches a look and misses it on CLV. It does not fix
  VOLUME. The 10-27 funnel (`.syndicate/findings_2026-10-27_ev_lb_funnel.md`) found 97.9% of eligible lines fail on
  the ask plus the fee before σ enters, and a sharp-close refit RAISES z (1.28 / 1.32), so it books fewer. Prereg §8
  already rules on volume: a candidate that never reaches L1 by 2027-01-31 has not passed.

## 3. First reachability read on REAL fleet data (scratch copy; not part of the forward test)

- **Input:** read-only copies of the fleet's 10-26 and 10-27 record files (heavy builds 19:39:02Z and
  19:16:41Z) and the NBA / NFL / NCAAF / NHL / soccer book grids. Copied to `C:\tmp\dpv1\smoke\` at nice 19.
- **Run:** booked with the real params into that scratch store. No outcome or close was read.
- **Load:** 6.4 s, about 230 MB peak working set, for both builds.

| | 10-26 build | 10-27 build (next-day board) |
|---|---|---|
| records / with a venue price | 4,567 / 707 | 2,786 / 445 |
| (record, venue) candidates / eligible | 946 / 402 | 623 / 45 |
| failed gates | outside 36 h window 528, one-sided fair 16, wrong-date contract 6 | outside window 578, wrong-date 5 |
| σ source of eligible | S2 134, S3 268 | S2 43, S3 2 |
| qualifying: P1 `ev_lb` / P2 `net_floor_719` / C0 `suggested_2pct` | **0** / 6 / 15 | 0 / 0 / 1 |

- **σ coverage:** S1 is 0, because the fleet's writer predates `636ba4ff` (not loaded). The S3 lines were all
  MLB / WNBA, whose grids I did not copy, plus 4 soccer corners rungs under 2 books. Every eligible
  NBA / NFL / NCAAF / soccer line with a grid got S2. **The forward run needs no input that the fleet does not
  already write.**
- **C0 reproduces the audit's F1:**
  - C0 booked 15 axes. Their median EV at the VENUE's own ask is **−6.07%**, against ≥ +2% at the board's best
    book.
  - Today's Suggested is mostly negative where we would actually buy (the one-engine audit: 12 of 13 Kalshi
    sides).
- **P1:**
  - The best eligible S2 line had EV_net +0.3% (an NFL Receptions prop on Kalshi), with EV_lb −1.5%.
  - P1 needs a venue ask about 2.8 pp below the consensus: roughly 1.1 pp of σ·z plus the ~1.75c fee.
  - **Volume risk, stated now:** if Monday-type boards stay near 0 P1 bets, L1 (400 bets with a sharp close) may
    not arrive before the 2027-01-31 final. That outcome is the plan's kill rule working, not a defect. The
    first week of running gives the rate; it is reported at the first Monday read.

## 4. Tests and checks

- **41 hermetic tests pass.** `tests/test_decision_policy_v1.py`: 22. `tests/test_decision_policy_paper.py`: 19.
  Neighbours: `tests/test_local_production.py` passes. `tests/test_decision_record.py` passes except its
  reader guard (section 6, D-A).
- **Reachability `off != paper` through the REAL job entrypoint**, on a record file written by the REAL
  `decision_record.write_records`:
  - `off` writes nothing, for `book` and `nightly` both;
  - `paper` books P1 and C0 rows;
  - absent, empty and unknown values all mean off.
- **No order path:**
  - static: no file of ours imports any of `kalshi_orders`, `polymarket_us_orders`, `execute_portfolio`,
    `execution_ledger`, `portfolio_commit`, `kalshi_maker_pilot`, `inplay_entries_live` or `execution_exits`;
  - runtime: a clean interpreter books a build and then holds none of them in `sys.modules`. The test asserts
    the booking happened, so the check cannot pass vacuously.
- **Parity:** the S2 dispersion term equals `syndicate_fair.dispersion_var` with equal weights (the code
  σ_fair_v1 was fitted with).
- **`p_fair_v1` is never read:** moving it changes no policy number.
- **Decide once:** a later build with a better rung on the same axis books nothing. An older build after a
  newer one books nothing. Re-running a build books nothing.
- **Grading:** Pinnacle close by power de-vig; a post-start Pinnacle quote is ignored; a moved line gives
  `no_pinnacle_close_at_this_line` and still reports the consensus CLV; props are ROI-ungraded, not dropped. The
  real `iter_book_quotes` reader is exercised under `SYNDICATE_DATA_ROOT`.
- **Gate:**
  - L1 / L2 / L3 at the registered n, games and boundaries;
  - one look per strategy per date;
  - the 2027-01-31 final reads at L3's boundary and closes the test;
  - final-underpowered closes it too;
  - the clustered SE was checked by hand.
- **Four mutants, all caught:**
  - the switch defaulting on;
  - grouping per line instead of per axis;
  - dropping the look-ahead guard on grid quotes;
  - letting post-start quotes into the close.

## 5. Implementation clarifications (they do not change a registered rule)

1. **S2 is computed "as of the decision instant".** A book quote first observed AFTER the build's
   `written_at` is excluded, not just quotes older than 12 h. The grid holds only each book's latest quote, so a
   book that moved after the build is simply absent. Otherwise σ would read information from after the decision.
2. **One look per strategy per daily read, taken in order.** If one day's data cross both L1's and L2's counts,
   L1 is taken that day and L2 the next. "The first daily read with n ≥ …" read literally.

## 6. Decisions owed by the user (routed to the session "Syndicate AI decision engine")

- **D-A: loan of `tests/test_decision_record.py` (lane `decision-record-shadow`).**
  - The problem: `test_nothing_outside_the_lane_reads_the_record` fails on ANY importer of `decision_record`
    under `syndicate/` or `pipeline/`. The paper book is that importer, and it is the D2 "paper2 first" reader
    (record step 3).
  - **Recommendation (A):** one narrow allowlist entry for `decision_policy_paper.py`, with the reason in the
    test's docstring. The loan is recorded in both lane blocks and returned on landing.
  - (B) Move the reader under `scripts/`: passes the scan, defeats its intent. Not recommended.
  - (C) Hold the paper track.
  - **Until the answer arrives, the paper module, its scripts, its tests and the two job entries stay
    committed on this lane's branch and are NOT on main**, so the guard stays green.
- **D-A RESOLVED 2026-10-26 20:00:18Z.** The user approved option A, verbatim: "Approve the loan (Recommended)". Landed: reader `03f29ac4` + guard entry `9e85b605`, both on main; the loan is returned (both lane blocks).
- **D-B: enable the paper job on the fleet.**
  - Steps: a fleet ff to a HEAD with this lane's code; `SYNDICATE_DECISION_POLICY_PAPER=paper` in the
    refresh-worker env; one full supervisor down/up, because `SCHEDULED_JOBS` and the env load only at `up`.
  - Cost: a 15-minute subprocess of ~6 s / ~230 MB at nice 19, and a nightly grade that streams two
    book_quotes shards per sport.
  - **Recommendation:** ride along the next user-approved full down/up, so it costs no restart of its own. The
    same restart also loads `636ba4ff` (S1) and `46fba654` (D3).
  - **Calendar matters:** the gate needs ≥ 400 sharp-graded bets, and none accrue until the job runs.
  - Verify by: the first `[decision_policy_paper] PAPER_BOOKED` line in `job-decision-policy-paper.log`, then
    a `bets.jsonl` row whose `build_id` matches that day's record header.

## 7. Dated reads (`#717`)

- Weekly on Mondays from the first Monday after the job is enabled, until a candidate reaches L1 (n ≥ 400 with
  a sharp close, ≥ 100 games).
- The final read is **2027-01-31** (plan Phase 3 end; the §9 kill rule).
- The first Monday read also reports the booking rate per strategy, so the volume risk in section 3 is
  measured, not guessed.

### Section 6 update

- **D-B RESOLVED 2026-10-27 05:20:04Z.** The user chose "Widen tonight's window" (10-26, asked in the session
  "Syndicate AI decision engine", which ran it): ff to `0fca3f2b`, `REFRESH_WORKER__SYNDICATE_DECISION_POLICY_PAPER=paper`,
  one full supervisor down/up. `.syndicate/deploys.md` has the 05:20Z and 06:20Z entries.

### Section 7 dated reads

- **2026-10-27 15:12:52Z (fleet, read-only) -- the verify reading.**
  - `job-decision-policy-paper.log`: 48 `PAPER_BOOKED`, 0 `MODE_OFF`. The first booking on post-restart code is
    build |1793079152 (deploys.md 06:20Z); `sigma` has carried `S1_fair_v1` since then.
  - `bets.jsonl`: 35 rows on 19 distinct record build_ids. ev_lb 3 (all MLB World Series props on Kalshi:
    batter_rbis, outs, batter_hits; S2), net_floor_719 13 (Kalshi 12, Polymarket 1), suggested_2pct 19.
  - The 13:45Z nightly wrote `reads/2026-10-27.json` and `looks.json`: every look `waiting`, n = 0. It wrote
    no `grades.json` and printed no `PAPER_GRADED`. That is correct: the earliest bet starts 17:30Z, and
    `run_grade` returns without a line when no bet is 30 min past its start. A night with nothing due is
    therefore silent; read `reads/<date>.json` for proof that the nightly ran.
  - **Next reading owed:** the 10-28 13:45Z nightly's first `PAPER_GRADED bets=.. sharp_close=.. outcome=..`
    and `grades.json`.
- **ev_lb funnel 2026-10-27 (decision-engine lane, user-asked, post hoc):**
  `.syndicate/findings_2026-10-27_ev_lb_funnel.md`, `scripts/ev_lb_funnel_read.py` (`149936fe`). It re-runs this
  job's own path (`load_grid` -> `sigma_for_record` -> `evaluate` -> `qualifies`) without writing. Of 1,312
  eligible candidate-sides: 74.0% have the ask at or above the consensus, 23.9% have a raw edge the taker fee
  eats, 2.1% are held back by the haircut, and 0 qualify. See section 2's lever scope.
- **For the 11-02 read (the first Monday):** run `scripts/evaluate_decision_policy_paper.py` for the gate read and
  the booking rate per strategy, and re-run the funnel:
  `nice -n 19 python scripts/ev_lb_funnel_read.py --data-root ~/syndicate-prod/data --out <dir>`.
  Read buckets C/D on that morning's current record files only: replaying an older file falls back to S3.
