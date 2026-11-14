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

## Result `[2026-11-13 22:25Z (4:25 PM CST)]` -- the hypothesis HOLDS: no primary test passes, so `#763` stays off

Run once on the fleet, read-only, at nice 19, with the registered grader (blob `dbcdcce69a22`, checked against the
working copy before the run). 162 final games and 67,985 graded rows; 82 pushes were dropped, and 67,985 + 82 matches
the 68,067 registered. The enumeration grew by 59 rows, all of them tonight's (11-13) games, which are outside the
window.

### The eight registered tests

d = engine Brier minus books Brier; negative means the engine was better.

| half | market | quote age | games | rows | engine | books | d | 95% interval | family-wise interval | status |
|---|---|---|---|---|---|---|---|---|---|---|
| first | totals | <= 30 s | 110 | 235 | 0.2585 | 0.2477 | +0.0108 | -0.0100..+0.0332 | -0.0179..+0.0423 | no_edge |
| first | totals | <= 120 s | 157 | 2,880 | 0.2557 | 0.2482 | +0.0074 | -0.0055..+0.0207 | -0.0102..+0.0263 | no_edge |
| first | spreads | <= 30 s | 107 | 201 | 0.2536 | 0.2511 | +0.0024 | -0.0115..+0.0169 | -0.0168..+0.0229 | no_edge |
| first | spreads | <= 120 s | 157 | 2,513 | 0.2478 | 0.2494 | -0.0016 | -0.0094..+0.0062 | -0.0127..+0.0094 | no_edge |
| second | totals | <= 30 s | 99 | 191 | 0.2383 | 0.2496 | -0.0113 | -0.0279..+0.0065 | -0.0348..+0.0140 | no_edge |
| second | totals | <= 120 s | 155 | 2,885 | 0.2569 | 0.2496 | +0.0073 | -0.0066..+0.0218 | -0.0115..+0.0280 | no_edge |
| second | spreads | <= 30 s | 94 | 174 | 0.2473 | 0.2484 | -0.0011 | -0.0174..+0.0155 | -0.0242..+0.0216 | no_edge |
| second | spreads | <= 120 s | 155 | 2,477 | 0.2547 | 0.2496 | +0.0051 | -0.0061..+0.0163 | -0.0105..+0.0211 | no_edge |

Against quotes 2 minutes old or younger, the engine is within about 0.01 Brier of the books on every pair. It is
slightly worse in five of the eight cells and better in three, none of them beyond noise. The 95% half-widths
(0.008-0.014 at <= 120 s, 0.014-0.022 at <= 30 s) are the size of edge this sample could have missed.

### Beside it (not decisions)

**By disjoint quote age**, d with its 95% interval:

| half / market | 0-30 s | 30-120 s | 120-300 s | 300-900 s |
|---|---|---|---|---|
| first / totals | +0.0089 (-0.012..+0.031) | +0.0075 (-0.005..+0.021) | -0.0114 (-0.023..+0.000) | **-0.0592 (-0.071..-0.046)** |
| first / spreads | +0.0010 (-0.014..+0.016) | -0.0018 (-0.010..+0.006) | **-0.0227 (-0.030..-0.015)** | **-0.0710 (-0.082..-0.060)** |
| second / totals | -0.0123 (-0.029..+0.006) | +0.0086 (-0.006..+0.024) | -0.0024 (-0.016..+0.012) | **-0.0340 (-0.047..-0.020)** |
| second / spreads | -0.0007 (-0.017..+0.016) | +0.0054 (-0.006..+0.017) | -0.0014 (-0.012..+0.009) | **-0.0258 (-0.037..-0.014)** |

**Claimed vs realised edge** where the engine and books differ by 5 pp or more, betting the engine's side at the
books' fair (realised with its 95% interval):

| half / market | <= 120 s: rows, claimed, realised | all ages: rows, claimed, realised |
|---|---|---|
| first / totals | 2,002, 13.7 pp, 3.6 pp (-2.0..+9.3) | 13,506, 20.6 pp, 17.6 pp (+14.4..+20.7) |
| first / spreads | 1,479, 11.5 pp, 5.3 pp (+0.1..+10.5) | 11,765, 21.0 pp, 20.2 pp (+17.6..+22.7) |
| second / totals | 1,946, 13.3 pp, 3.9 pp (-2.3..+10.0) | 15,468, 18.6 pp, 13.3 pp (+9.1..+17.4) |
| second / spreads | 1,560, 11.1 pp, 2.2 pp (-5.0..+9.5) | 12,281, 17.3 pp, 10.9 pp (+6.6..+15.1) |

### What it says

1. **No edge against fresh books.** The verdict the registration fixed: `#763`'s college segment pricing stays off
   on this evidence. No quote-age ceiling is supported, because nothing passed at 30 s or at 120 s.
2. **The instrument could see one.** The same grade, on the same games, finds the engine far better than quotes 5-15
   minutes old: d -0.026 to -0.071, two to six half-widths from zero, every interval clear of 0. So the
   fresh-quote result is not blindness; any edge there is smaller than about 0.01 Brier.
3. **The advantage is the quote's age, as hypothesised.** d falls with age in every pair, and the realised edge
   against stale quotes (11-20 pp) is real against the price we LOGGED. Whether any venue would still have taken a
   half bet at a price 5+ minutes old is not in this data. The game has moved on, which is exactly why the engine
   (which knows the state) wins against it. This is `#780`'s finding again, on halves.
4. **Against fresh books the engine's gaps are mostly over-confidence.** It claims 11-14 pp and realises 2-5 pp
   (intervals spanning 0 in three of four pairs). Segments are untempered (k 1); `#780` measured the same pattern on
   full games and tempers those.
5. **84% of the opinion rows sit on quotes older than 120 s.** In-play segment capture is the bottleneck `#763`
   already names (the in-play lane fetches every 240 s). Even where the quotes were fresh, there was no edge.

**Limits:** four nights, 162 games, NCAAB only (WNCAAB has no segment quotes); a first-half spreads realised edge of
5.3 pp at <= 120 s (interval +0.1..+10.5) is one of eight secondary readings at nominal 95%, not evidence.

## Provenance `[2026-11-14 15:26Z (9:26 AM CST)]`

The registration pinned the grader at a worktree commit (`f771a8c6b`). It reached main rebased, as `9ec4c43b9` (grader) + `faa292b81` (EvidenceIndex fix, grader enumerates once) + `40b580a92` (doc). The blob of `scripts/college_segment_grade.py` on main is `dbcdcce69a22a52672e0ef581fce3814db66598b`, the registered one.
