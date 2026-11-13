# College half lines: does the live re-sim beat the books, and at what quote age? (pre-registration)

Lane `college-segment-grade`, for `#763` (college live halves are built and OFF until "a measured college segment
quote-age ceiling ... then a scored sample") and `#736`. Session e32fef1a.

**REGISTERED 2026-11-13 22:20Z (4:20 PM CST), BEFORE ANY OUTCOME WAS READ.** The grade has not run. The "Result" section is appended once,
after one grade run; nothing above it is edited after that.

## What is graded

Every OPINED row of the live segment expert (`engine_experts.live_segment_expert`, `live_segment/1`) on NCAAB, first
and second halves, totals and spreads, for every game FINAL on ESPN's NCAAB scoreboards dated 2026-11-09, 11-10, 11-11
and 11-12 (162 games). Each row: at one logged re-sim tick, one half line a book was quoting; the engine's two-way
probability (the live join's own estimator) beside the books' de-vigged median at that instant; and the quote age,
the age of the NEWEST usable book's quote then. One enumeration covers every evidence file and quote shard from
11-08 to 11-13. Rows seen twice are counted once.

- **Outcome:** ESPN's half scores (`ncaab_source/data/scoreboard/scoreboard_<date>.json`, final games), joined on
  the ESPN event id. First half = period 1. Second half = period 2 plus every overtime period, which is the books'
  rule and the college re-sim's (`#763`).
- **Event:** totals, over the line. Spreads, home margin above the expert's line, which is the away team's handicap
  (a home -2.5 quote is line 2.5). A row landing on the line is a push and is dropped. A neutral-site game is
  oriented by team name; a spread whose orientation cannot be resolved is not graded (counted: 0 at registration).
- **Score:** per row, d = engine Brier minus books Brier, negative where the engine is better. A cell reads the
  row-weighted mean of d with a GAME-clustered bootstrap interval (20,000 draws, seed 763).

## The decision (fixed here; `PREREG` in `scripts/college_segment_grade.py`)

Eight primary tests: (first half, second half) x (totals, spreads) x quote age at most 30 s and at most 120 s
(cumulative). A test **PASSES** when its cell has at least 30 graded games AND the upper bound of its family-wise
interval (Bonferroni over the eight: two-sided 1 - 0.05/8 = 99.375%) is below 0. Fewer than 30 games is
`insufficient`, which is no decision. Anything else is `no_edge`.

- **No test passes:** the hypothesis holds. On this evidence the engine does not beat fresh books on any college half
  line, and `#763` stays off. The 95% half-widths say how large an edge this sample could have missed.
- **A test passes:** the hypothesis is falsified for that pair. Its smallest passing ceiling is the measured
  quote-age ceiling `#763` asks for. That is a candidate, not a switch: turning pricing on is the user's decision.

**Hypothesis (the lane's, written before this):** the half-line gaps between the re-sim and the books are mostly a
stale-quote effect, as `#780` found on full games. Against quotes 120 s old or younger the engine is not better than
the books on any pair, and its apparent advantage grows with quote age.

**Read beside it, never a decision:** d by disjoint quote-age bucket (0-30, 30-120, 120-300, 300-900 s), and on rows
where the engine and books differ by 5 pp or more, the claimed edge against the realised one, betting the engine's
side at the books' fair, at 120 s or younger and at all ages.

## Found while counting (no score read), fixed before registering

- **Every NCAAB segment opinion was written twice.** `EvidenceIndex` filed each evidence row under its team names and
  its abbreviations; NCAAB's abbreviations reduce to the same key as its names, so each tick sat twice in one series
  (3,529-6,029 duplicate instants a night). Fixed in `engine_experts.py` (each distinct key once; a test pins it). The
  live-segment-expert lane's NCAAB line and opinion counts were therefore DOUBLE; its 0-mismatch gates stand (the
  copies were identical).
- **Per-date runs split some games' quotes.** `book_quotes` keys a shard by each quote row's kickoff date, and a game
  whose rows carry two kickoff times lands in two shards: 1,079 rows came out of two dates' runs, about 840 with
  different market prices. Hence the single enumeration above.

## Pinned

- Grader: `scripts/college_segment_grade.py`, blob `dbcdcce69a22a52672e0ef581fce3814db66598b`, commit `f771a8c6b` (worktree branch, with the
  evidence-index fix; both go to main on the user's yes). 14 grader tests pass, including a planted-edge positive
  control (all eight PASS) and two nulls (none PASS); breaking the spread sign, the overtime rule, the orientation
  swap or the pass rule each fails them.
- Run: ONCE, `--grade`, on the fleet, read-only, at nice 19, with refresh-worker's environment.

## Counts at registration (`--count-only`, fleet, no score read)

Enumeration: 196 games with segment quotes, 160 matched to an evidence game by team name, 71,155 standing lines,
68,708 opined. Rows: 68,067 kept, 154 duplicates, 487 outside the window or not final, 0 without a quote age, 0 with
an unresolvable orientation. 162 final games in the window.

| half | market | quote age | games | rows |
|---|---|---|---|---|
| first | totals | <= 30 s | 110 | 235 |
| first | totals | <= 120 s | 157 | 2,881 |
| first | spreads | <= 30 s | 107 | 201 |
| first | spreads | <= 120 s | 157 | 2,514 |
| second | totals | <= 30 s | 99 | 191 |
| second | totals | <= 120 s | 155 | 2,886 |
| second | spreads | <= 30 s | 94 | 174 |
| second | spreads | <= 120 s | 155 | 2,479 |

Every primary cell has at least 30 games. About 84% of the opined rows (57,000 of 68,000) sit at a quote older
than 120 s.
