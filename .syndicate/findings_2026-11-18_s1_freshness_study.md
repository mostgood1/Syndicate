# Findings -- lane `s1-freshness-study`: study S1 of the profit learning program (2026-11-18)

Plan: `.syndicate/plan_2026-11-18_profit_learning_program.md`, study S1. Read-only: this lane changes no live code,
env or fleet state, and deploys nothing. Counts and percentages only (the repo is public).

## PRE-REGISTRATION (written 2026-11-18 19:09Z = 1:09 PM CST, before any outcome number is computed)

**Question.** Do picks lose because the trigger fires on a STALE reference price, so that we buy sides the market has
already moved against?

**What was already seen, stated so the overlap is visible.** Test B looks 1-3
(`findings_2026-10-24_live_cell_scorecard.md` s11-s13) split the P1 arm at a capture age of 2 min. P1 is Pinnacle
edge >= 0.4 pp, about 5% of the population.
- As of 11-16: <= 2 min **-1.0% [-15.2, +12.2]** (456 bets / 216 games); > 2 min **-11.3% [-22.2, -0.8]**
  (767 / 277).
- Those looks covered orders submitted 10-25..11-15. So the P1 subset of this study's TEST window (11-08..11-15),
  at N = 2, has been seen.
- **Nothing else has been looked at by freshness:** not the full population, not any other N, not the consensus age,
  not 11-16..11-17.

**Instrument.** `scripts/s1_freshness_study.py` (this lane; 13 tests in `tests/test_s1_freshness_study.py`).
- It reuses Test B's reader from `scripts/pinnacle_edge_deciles.py`, unmodified: `capture_age`, `heartbeat_dates`
  and `load_heartbeats`. The exploratory section also reuses `load_quotes`, `join_order` and `contract_price`.
- **Substrate:** the fleet ledger dump (`live_cell_scorecard.py dump`, 2026-11-18 ~18:51Z), run with refresh-worker's
  env at nice 19: `live_document_read_ok=True`, 55,815 rows, newest submit 2026-11-18T18:50:26Z.
- The fetch heartbeats are read from the fleet's data root by the same run.

**Population.**
- **Included:** settled (won / lost / push), filled, staked orders with an event_id, at a venue:
  - live `kalshi` / `polymarket`;
  - `paper:<venue>` (the paper twin);
  - `paper:<venue>:ladder`.
- **Pregame only:** `live_cell_gate.phase_of` is pregame AND `submitted_at < commence_time`.
- **Deduplication:** paper rows per (venue, position_key), keeping the first submit (`live_cell_scorecard`'s rule).
  Live rows are real fills and are never deduplicated.
- **Excluded:** `paper` (the sportsbook paper book), `paper:prophetx` and `paper:novig`.

**Reference age at submit.**
- **PRIMARY: the Pinnacle capture age.** This is `capture_age` with key `pinnacle_events`: the seconds from the last
  fetch at or before submit that SAW Pinnacle on the event, to submit.
  - It is the reader Test B split on.
  - It is "unknown" when no such fetch exists. Unknown is never fresh and never stale.
- **SECONDARY (reported, not gating): the sportsbook-consensus capture age.** This is the same reader over the
  heartbeats that carry at least one non-venue book, key `events`.
  - The live trigger's reference is the consensus (`market_fair`), and Pinnacle is one book inside it.
  - A venue-only capture (books = kalshi / polymarket only) does not refresh the consensus, so it does not count.
- **This is the age of OUR COPY** (time since we last looked), not the time since Pinnacle's price last changed.

**Outcome.** Fee-net flat ROI per order: the mean of `pnl_dollars / fill_stake_dollars`, in percent. `pnl_dollars` is
net of fees on every book.

**Interval.** Event-clustered (cluster = the event_id, `live_cell_gate.game_of`), with a linearised SE and
95% = +-1.96 SE (as in `live_book_edge_readout.summarize`).
- For a difference of two means over overlapping sets (fresh-only is a subset of all), each event's influence is
  sum over F of (r - m_F) / n_F, minus sum over A of (r - m_A) / n_A. The variance is the sum of their squares.
- A seeded event-cluster bootstrap of the same difference is printed as a check. It is NOT the registered interval.

**Time split.**
- **FIT:** orders submitted before 2026-11-08T00:00Z. Ages exist from the first fetch heartbeat
  (2026-10-25T18:36:27Z), so FIT is in effect 10-25..11-07.
- **TEST:** orders submitted 2026-11-08T00:00Z .. 2026-11-18T00:00Z, settled by the dump.

**Choosing N (FIT only).**
- Candidates: N in {1, 2, 5, 10, 15} min. Fresh = age <= N min; stale = age > N min. Both are among orders with a
  readable age.
- Choose the N that maximises flat ROI(fresh) minus flat ROI(stale) on FIT.
- An N qualifies only if each side keeps >= 100 orders and >= 30 events. Ties go to the smaller N.
- If no N qualifies, the verdict is NOT TESTABLE. (Coverage below: every candidate qualifies on FIT.)

**PRIMARY HYPOTHESIS H-fresh.**
- **Statement:** on TEST, D = flat ROI(fresh-only, age <= N) minus flat ROI(all orders with a readable age) is > 0,
  and its event-clustered 95% interval excludes 0 (lower bound > 0).
- **Falsified if** the interval includes 0, or D <= 0.
- **Reported with it:** the fresh-only ROI and its 95% interval, and the "all" ROI and its interval.
- "All" means the orders with a readable age, so that D isolates freshness from the sport mix of the unknown-age
  orders (NCAAB and WNCAAB have no Pinnacle at all). Unknown-age orders are reported as coverage.
- This is the paired form of the plan's win condition: "out-of-sample fee-net ROI lower bound > the champion's on the
  same dates".

**Also reported (descriptive, not gating), all with the same N:**
- live-only; paper-only (twin + ladder pooled, then each);
- Kalshi and Polymarket separately;
- the ROI gradient across age buckets 0-1, 1-2, 2-5, 5-15, 15-60 and > 60 min, plus unknown, on TEST, on FIT and on
  both;
- coverage: how many orders have a readable age, by window, book, venue and sport;
- the secondary (consensus-age) arm, run by the same FIT/TEST procedure with its own N;
- diagnostics: the mean `ev_pct` of fresh-only vs all on TEST (does freshness just pick a different EV mix?), and
  the dollar ROI in percent.
- **Multiple comparisons:** there is one primary test. The 6 slices x 2 arms are descriptive. Under a true null about
  0.6 of those 12 intervals would exclude 0 by chance. No slice is a finding on its own, and none is ever a sport or
  market switch (learnings line 1056).

**EXPLORATORY (labelled; not a registered test).** For orders with a readable Pinnacle age and our venue's own quote
in `book_quotes`:
- Read our venue's logged quote on our side and line at the reference fetch (submit minus the Pinnacle capture age),
  and again at submit.
- Classify the move against the reference fair (Pinnacle's two-way at submit, else the consensus) as toward, away,
  or flat, and report ROI by class.

**Decision use.**
- **H-fresh survives:** state the candidate challenger rule precisely, as a PER-LINE rule: the trigger fires only when
  its reference quote's capture age at submit is <= N min.
  - It is a betting change. Only the user decides it, and it may load only in a betting-change window (next:
    2026-11-24 08:00-13:00Z, `betting_change_windows.md`).
  - Paper first, if the user prefers.
- **H-fresh falsified:** the freshness of the reference quote is not the lever. Adverse selection then has to be
  looked for in the other S6 features: book count, dispersion, time to start, price band, the venue's own move.

**Known limits, stated before the run.**
- The paper ladder dominates the count, and pooled flat ROI weights every order equally. That is why live-only is
  reported.
- Only settled orders count. TEST orders on games not yet final are absent.
- The ladder places many orders per event (readable Pinnacle age: TEST 6,300 orders on 274 events, FIT 7,239 on 552),
  so the event clustering, not the order count, sets the width of every interval.
- The live stake cut to one contract (lane `live-stake-minimum`, 11-18) is after TEST and does not touch it.

## Coverage, measured before this pre-registration was pushed (counts only, no outcome)

Run 2026-11-18 ~19:00Z on the fleet, refresh-worker env, nice 19, worktree code at `3c1d4dfbd` plus this lane's
script: `S1_JOIN orders=20475 pin_known=13606 cons_known=17302 heartbeat_files=142`, 241 s.

**Per-family date coverage and the intersection.**

| family | dates | first | last | gaps |
|---|---|---|---|---|
| orders (pregame settled population, submit UTC date) | 48 | 2026-10-02 | 2026-11-18 | none |
| fetch heartbeat (any sport, shard date) | 25 | 2026-10-25 | 2026-11-18 | none |
| orders with a readable Pinnacle capture age | 25 | 2026-10-25 | 2026-11-18 | none |

- **Intersection: 25 dates, 2026-10-25..2026-11-18.** The study rests on FIT 10-25..11-07 (14 dates) and TEST
  11-08..11-17 (10 dates).
- Orders before the first heartbeat (3,142, 10-02..10-25) have no age, by construction.

**Readable age by window and book.**

| window | orders | Pinnacle age known | consensus age known |
|---|---|---|---|
| FIT | 8,684 | 7,239 (83%) | 8,654 |
| TEST | 8,571 | 6,300 (74%) | 8,570 |
| TEST, live | 570 | 441 | 570 |
| TEST, paper twin | 195 | 169 | 195 |
| TEST, ladder | 7,806 | 5,690 | 7,805 |

- **By sport (FIT + TEST), Pinnacle age known:** NBA 8,301 / 9,050; NCAAF 1,647 / 1,796; NHL 1,423 / 1,754;
  NFL 904 / 969; soccer 894 / 904; MLB 249 / 300; WNBA 121 / 121; **NCAAB 0 / 2,254; WNCAAB 0 / 107.**
- **Drops:**
  - ladder: in game 4,712; duplicate position 4,367; unsettled 2,392;
  - paper twin: in game 517; duplicate position 427; unsettled 62;
  - live: no event_id 552 (the Aug-Sep venue rebuilds); in game 419; not filled 117; unsettled 71; no times 30;
    no stake 2.

**Fresh / stale counts per candidate N** (orders, then events, Pinnacle age).

| window | N=1 | N=2 | N=5 | N=10 | N=15 |
|---|---|---|---|---|---|
| FIT | 646 / 6,593 (230 / 546 ev) | 1,266 / 5,973 (302 / 524) | 2,142 / 5,097 (414 / 472) | 3,342 / 3,897 (480 / 424) | 4,080 / 3,159 (507 / 383) |
| TEST | 471 / 5,829 (153 / 271) | 1,016 / 5,284 (203 / 250) | 2,182 / 4,118 (253 / 205) | 3,153 / 3,147 (263 / 193) | 3,714 / 2,586 (264 / 171) |

**Every candidate N qualifies** (>= 100 orders and >= 30 events per side on FIT), so the population exists at every
N (learnings 2026-09-17).

**Age distribution (orders).**

| window / age | 0-1m | 1-2m | 2-5m | 5-15m | 15-60m | >60m | unknown |
|---|---|---|---|---|---|---|---|
| FIT, Pinnacle | 646 | 620 | 876 | 1,938 | 2,155 | 1,004 | 1,445 |
| TEST, Pinnacle | 471 | 545 | 1,166 | 1,532 | 1,851 | 735 | 2,271 |
| FIT, consensus | 790 | 709 | 1,098 | 2,203 | 2,394 | 1,460 | 30 |
| TEST, consensus | 823 | 793 | 1,757 | 2,243 | 2,042 | 912 | 1 |
