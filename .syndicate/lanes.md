# Syndicate — Work Lanes

> Lanes are exclusive by file path. Two lanes may not claim the same file.
> Max concurrent OPEN lanes: 3 (see `state.md`).
> Managed by `/lane`. Do not hand-edit while a session is running.

## OPEN

### win-prob-null-readable — OPEN — **BUILT, TESTED AND COMMITTED (`b281bc7f`); ON NO SERVICE — the reading itself is still owed** — opened 2026-08-15 — session: win-prob-null-readable
- Goal: the `WIN_PROB_NULL_NO_PRICE` counter is READABLE from the web service
  (one HTTP read, no log archaeology), for both prop producers, on every run.
- **THE DEFECT, measured not suspected.** The counter deployed 2026-08-15
  (refresh-worker `903d09c5`, live-odds-worker `b7ae47e6`) `print()`s to stdout
  from `__main__`'s `finally`, and `refresh_odds_sources._run_command` runs every
  producer under `subprocess.run(capture_output=True)` and **discards a
  successful step's stdout** (bounded stderr tail only, only on FAILURE). Trap
  already documented at `ops.py:2263` on 2026-08-01 for this same script.
  - **The producer RAN and the line was still nowhere.** live-odds-worker's own
    `ALL_PROCESS_MEMORY` census 23:36:05Z lists PID 1900
    `refresh_wnba_oddsapi_props.py --date 2026-08-15 --do-edges --do-export`
    (started 23:36:04Z, ppid 1880 = `refresh_odds_sources.py`), while
    `render_logs.py` returned **zero matches on both workers** across the whole
    window since the deploy. "Not yet run" was the WRONG reading; the silence
    belonged to the emitter.
- **SHIPPED IN CODE `b281bc7f`:** both producers also publish through
  `write_json_file`; new `syndicate/features/shared/win_prob_null_diag.py` owns
  the key so writer and reader cannot disagree; `/api/ops/win-prob-null` reads it
  back and reports what it PROBED next to what it found. Per-service keys (the
  `disk_maintenance._status_path` lesson: one shared key made a per-service fact
  a race). 11 new tests + 55 targeted green; route exercised end-to-end
  (worker-slug write → web-slug read → 200, 401 unauthenticated).
  - **Env verified before relying on it, all three services:**
    `SYNDICATE_REPORTS_ROOT=/opt/render/project/data/reports`,
    `SYNDICATE_REFRESH_STATE_BACKEND=keyvalue`, so the key string matches
    cross-service. `SYNDICATE_REFRESH_LANE` = `web` / `refresh-worker` /
    `live-odds-worker`.
  - The commit also carries the EARLIER session's counter (`_WIN_PROB_STATS`, the
    `_clamp_probability` counting, the `finally` block) — live on both workers,
    never committed to main. Not this lane's work; committed rather than left one
    checkout away from loss.
- Files (exclusive to this lane; `lane-guard.py` `_claims()` CLEAR **and** every
  OPEN lane's `Files:` block read, per the under-report rule):
  - `syndicate/features/shared/win_prob_null_diag.py` (new)
  - `scripts/refresh_wnba_oddsapi_props.py`
  - `scripts/refresh_nba_oddsapi_props.py`
  - `syndicate/blueprints/ops.py` — the only two `lanes.md` mentions are explicit
    NON-claims ("consumer only", "NOT claimed"); former holder
    `quote-feed-age-alarm` is CLOSED-VERIFIED.
  - `tests/test_win_prob_null_diag.py` (new)
- Falsification test: if a producer run completes after the deploy and the key is
  still absent, the keyvalue write is NOT the readable channel either — EXECUTE
  `_keyvalue_backed()` against the real path (as `disk_maintenance._status_path`
  did) and compare `reports_root()` on web vs worker. **Do not add a third
  channel first.**
- Verification (NOT DONE — this lane does not close on the code): after both
  workers and web carry `b281bc7f`, `/api/ops/win-prob-null` returns a WNBA
  reading whose `generated_at` post-dates the deploy. Until then the `or 0.5` fix
  stays **UNVERIFIED IN EFFECT**; this lane made the measurement possible, not
  made.
- Blocked by: none. Needs a deploy to **both workers and web**; no deploy without
  `/preflight`.

### closing-stamp-is-detection-time — OPEN — **FIXED AND DEPLOYED (`325b2822`, workers 23:1xZ); stamp is now the price's observation time, detection kept as `closing_detected_at`. OUTPUT UNVERIFIED — forward-only, today's stamps unrecoverable** — opened 2026-08-15 — session: lane-cleanup
- **DISCRIMINATOR RUN 2026-08-15 22:0xZ on the `-186 -> +168` row. RESULT: NEITHER
  ORIGINAL BRANCH. The price is not stale and the clock is not the main problem —
  IT IS THE WRONG SIDE'S PRICE.**
  - Event `dbbb481a…` = **New York Yankees @ Toronto Blue Jays**, first pitch
    19:08Z. FanDuel h2h `history_first` 06:02:51Z carries
    `line={away_odds: -186, home_odds: +156}` — our opening of `-186` is the
    AWAY side, correctly recorded.
  - The stamped close is `closing_price = 168.0`. In that market's own history
    the scalar `odds`/`line` field tracks **`entity`**, and `entity` is
    **`Toronto Blue Jays` — the HOME team**. `+168` is a HOME price (betrivers
    independently shows home `+165` at the same 20:34 tick).
  - **So the joiner differenced an AWAY opening against a HOME close.** That is
    the entire `-27.72`. It is not CLV, not a stale price, and not a late clock.
  - **Measured across every stamped market, not just this one: `entity ==
    home_team` on 18 of 18.** So `closing_price` is ALWAYS the home price.
- **THE DEFECT, in code:** `resolve_close` path 1 takes
  `market_state.get("closing_price")` as a **side-blind scalar**. Path 2
  (`last_pregame_quote`) reads the `line` dict and picks `away_odds`/`home_odds`
  by side — which is exactly why the 100%/100% split fell where it did. The file's
  own docstring already knew: *"Game keys carry NO side — `entity` names one team
  … the history point's `line` dict carries BOTH."* Path 2 acts on that; path 1
  does not.
  - Consequence: **home-side openings get a CORRECT close; away-side openings get
    a garbage one.** Whether a given row is wrong depends only on its side, which
    is why the contaminated bucket had no consistent sign.
  - `totals` markets carry `home_odds/away_odds = None` entirely (6 of the 18),
    so over/under has no side resolution on this path at all.
- **MY SHIPPED FIX WAS RIGHT BY ACCIDENT, AND IT OVER-EXCLUDES. Stated plainly.**
  Web `4316c907` drops `close_age_seconds < 0` rows from the CLV headline. Those
  are exactly the `observed_transition` rows, so it removed the side-mismatched
  ones — **but for a reason that is not the real one**, and it also drops the
  HOME-side rows on that path, whose closes were fine. The exclusion stays (it is
  net-correct and named), but its stated rationale in `deploys.md` is now known to
  be secondary.
- **The timestamp claim is NOT refuted, just demoted:** `closing_captured_at`
  20:34:26Z against a 19:08Z first pitch is still 86 minutes late, and
  `odds_refresh_tracking.py:1602` still writes `now`. Fix the side first; the
  clock is a smaller, separable error.
- **SIDE FIX SHIPPED under `clv-without-settlement` (it owns `clv_join.py`):**
  web `c8810f45` live 21:58:19Z, main `ae0bc968`. 20 away-side openings now
  refuse the home stamp; `observed_transition` 48 -> 22; `in_play_excluded_n`
  48 -> 19; `same_book_n` 131 -> 151; headline `-0.3077` -> `-0.2714`,
  recompute-verified. **THIS LANE'S REMAINING SCOPE IS THE CLOCK ONLY** —
  `odds_refresh_tracking.py:1602` still writes `closing_captured_at = now`
  (detection time), which is why a 19:08Z first pitch carries a 20:34Z stamp.
  That file is still claimed here and untouched.
- **THE `-29.90` ROW IS EXPLAINED, 2026-08-15 22:2xZ. IT IS NOT A MARKET MOVE.
  THE ODDS-HISTORY FEED SWAPPED ITS `home_line`/`away_line` LABELS DURING THE
  DAY, so the same two prices appear under opposite labels.** Event
  `69928d29…` = Seattle Mariners @ **Houston Astros**, FanDuel spreads:

      history_first 06:02:51Z   away_line -1.5 away_odds +168 | home_line  1.5 home_odds -205
      history_last  21:26:47Z   away_line  1.5 away_odds -205 | home_line -1.5 home_odds +168

  **Identical prices (-205 / +168). The line labels are transposed.** The market
  did not move at all — `-205` and `+168` are the two sides of ONE run line.
- **Why the guard could not catch it.** `_price_for_side` checks the line by
  NUMERIC EQUALITY (`abs(point_line - opening_line) > 1e-6`). With the labels
  flipped, opening `home -1.5` matches the close's `home_line -1.5` — which by
  then is the OTHER bet. The guard is doing exactly what it was written to do
  and is defeated by an unstable label, not by a missing one. **Equality of a
  label is not identity of a bet when the label's convention is not stable.**
- **The openings look self-consistent; the history does not.** Three opening
  records for that event's spreads: `home +1.5 @ +178` (05:07, kalshi),
  `home -1.5 @ -183` (07:06, onexbet), `home +1.5 @ +186` (20:40, betopenly) —
  +1.5 is plus money at both ends of the day. The 06:02 history point calls
  `home +1.5` **-205**, contradicting them.
- **SCOPE, measured rather than assumed — and it is NOT the headline killer it
  looks like:**

      same_book subset        n     mean      median   |clv|>10
      spreads (line-bearing)  42   +0.515    +0.000       2
      h2h / totals           128   -0.521    -0.246       0

  The two extreme rows are a **mirror pair from this one event** (`+30.428` on
  `home +1.5`, `-29.900` on `home -1.5`), because BOTH openings were recorded
  and each got the other's close. **They nearly cancel**, which is why the
  spreads mean reads a benign `+0.515` on a median of exactly `0.000`.
  So: **severe per row, self-cancelling in aggregate.** It corrupts any
  per-recommendation CLV, any variance or CI, and any "worst bets" list — while
  leaving the headline roughly intact. h2h and totals are clean (0 of 128).
- **NOT FIXED, and deliberately not fixed from here.** The defect is upstream of
  `clv_join.py` (an unstable label in the odds-history feed), the mirror-pair
  cancellation means it is not urgent for the headline, and a numeric-equality
  guard cannot be patched into correctness without deciding which source owns
  the sign convention. **That decision is the next lane**, and it should start
  from: does the board's published `line` sign agree with the feed's, per sport?
- **OPEN THREAD, NOT MINE TO CLOSE:** one row survives at `clv_pct -29.90`
  (`open -205`, `close 168.0`, side **home**, source **last_pregame_quote**) —
  side-aware path, not a side mismatch. Real move or a third defect, unknown.
- **REVISED FIX, for whoever takes this:** make path 1 side-aware — resolve
  `closing_price` through the same `line`-dict logic path 2 uses, and REFUSE
  (named, counted) when the side cannot be determined rather than returning the
  entity's price. Then re-run this discriminator and re-derive
  `in_play_excluded_n`.

- Goal: `closing_captured_at` means the time the CLOSING PRICE WAS OBSERVED, or
  it is renamed to say what it is. Testable outcome: for every market carrying
  a closing stamp, `closing_captured_at <= commence_time`, OR the field is split
  into an observation time and a detection time and every reader is updated.
- **WHY THIS IS ITS OWN LANE AND NOT AN EDIT INSIDE `clv-without-settlement`:**
  the fix is in the PRODUCER (`odds_refresh_tracking.py`), the CLV joiner is only
  a consumer, and `clv_join.py` is claimed by that lane. Changing a stamp that
  persists in shard files is also a data-shape change, not a display change.
- **WHAT IS ALREADY MEASURED (2026-08-15, do not re-derive):**
  - `/api/ops/clv/report` mlb 2026-08-15: **48 of 179 same-book rows** carry
    `close_age_seconds < 0`, i.e. a closing stamp AFTER first pitch.
  - Clean 100%/100% split by source: every contaminated row is
    `close_source=observed_transition`; every clean row is `last_pregame_quote`.
  - One event: opened `-186`, closing price recorded `+168`, stamped
    `20:34:26Z` against a `19:08Z` first pitch — 86 minutes late.
- **I GOT THE MECHANISM WRONG ONCE ALREADY. The correction is the starting
  point of this lane, not a footnote.** I told the user the recorded price "is
  already live". **Reading `odds_refresh_tracking.py:1600-1602` says the
  opposite**: the stamp is guarded on `was_confirmed_pregame` and deliberately
  records `previous_line`/`previous_odds` — "the value observed the tick BEFORE
  this one -- not current_line/current_odds, which is already the in-play
  number." So the PRICE is intended to be the last pregame price. Only
  `closing_captured_at = now` is the detection tick.
- Hypothesis: **`closing_captured_at` is the DETECTION time, not the observation
  time of the price it accompanies.** The price comes from tick N-1 and the
  timestamp from tick N, so on a ~2h sweep cadence the stamp can post-date the
  price by a full interval and land after commence. If true, `close_age_seconds`
  systematically overstates lateness and says nothing about whether the PRICE
  was pregame.
- Falsification test: if the recorded `closing_price` for the late-stamped rows
  is genuinely an IN-PLAY price (not a stale pregame one), then the stamp is
  honest and the defect is in the `was_confirmed_pregame` gate instead — a
  different fix in a different place. **Discriminator:** compare each late row's
  `closing_price` against that market's own history points before commence. If
  it matches a pregame point, the price is fine and only the clock is wrong. The
  `-186 -> +168` swing is the case to run first; it is large enough that "stale
  pregame price" and "in-play price" make visibly different predictions.
- **THIS LANE CAN INVALIDATE PART OF MY OWN SHIPPED FIX, stated up front so
  nobody has to discover it.** Web `4316c907` excludes `close_age_seconds < 0`
  from the CLV headline. If the hypothesis holds, some of those 48 rows carry
  legitimate pregame prices and are being excluded on a bad clock — the headline
  would be right to distrust the timestamp but wrong to drop the row. The
  exclusion stays until this is resolved (a wrong-but-named exclusion beats a
  silent contamination), but it is **provisional**.
- Verification: (1) the discriminator above run on at least 10 late rows, with
  the split reported; (2) whichever fix follows lands with a test pinning
  `closing_captured_at <= commence_time`; (3) `/api/ops/clv/report` re-read and
  `in_play_excluded_n` re-interpreted against the finding.
- Files (exclusive to this lane):
  - `syndicate/features/shared/odds_refresh_tracking.py` — the single write site
    (`:1602`). Collision check RUN via `lane-guard.py`'s own `_claims()`: CLEAR.
  - `tests/test_odds_closing_stamp.py` (new). CLEAR.
  - **NOT claimed:** `syndicate/features/shared/clv_join.py` (held by
    `clv-without-settlement`) and `syndicate/blueprints/ops.py` (consumer only).
    If the fix needs either, coordinate rather than edit across the lane.
- Blocked by: none. **No deploy from this lane without `/preflight`** — a change
  to a stamp that persists in shard files needs its backfill story decided
  before it ships, not after.

### spread-line-sign-convention — OPEN — **DIAGNOSED AND FIXED; DEPLOYED TO WORKERS 23:1xZ, ARTIFACT OUTPUT STILL UNVERIFIED** — the row's `line` is the AWAY handicap and home candidates inherited it (525/525 cells) — opened 2026-08-15 — session: lane-cleanup
- **TEMPLATE QUESTION ANSWERED 2026-08-15 23:2xZ. THE CONVENTION IS
  `row["line"] == THE AWAY HANDICAP`, AND ONLY THE HOME SIDE IS BROKEN.**
  - From the 525-cell result: `cell.home.line == -row.line` and (per-book
    internal consistency) `cell.home.line == -cell.away.line`. Therefore
    **`cell.away.line == row.line`, exactly.**
  - So: **away-side rows are CORRECT** — their price and `row["line"]` describe
    the same bet. **Home-side rows are INVERTED** — `layer2_board.py:852` pairs
    `cell["home"]["price"]` with `row["line"]`, which is the away handicap.
  - That is why the no-arb violation showed up only when comparing a home `-1.5`
    opening against a home `+1.5` one: both were home rows.
- **NO TEMPLATE CONSUMES THE SHORTLIST — but chat does, because I wired it there
  tonight.** `grep` over `templates/` and `static/` for `layer2-shortlist`:
  **zero hits**; the board still renders `ranked_all`. The one consumer on a
  user-facing path is `ask_the_syndicate_adapter.py:599`
  (`_board_top_opportunities`), shipped this session as web `c774fe1a`, whose
  `_board_row_selection` renders `f"{side} {line}"`.
  - **Verified live**: the chat headline served
    `'away -1.5 (San Diego Padres @ Cleveland Guardians)'` — an AWAY row, which
    is the correct case. **A HOME spreads row in that list would display the
    away handicap beside the home price.**
  - **So the user-facing blast radius is: home-side spread selections appearing
    in the Ask headline.** Narrow, real, and created by my own change tonight —
    before `c774fe1a` the shortlist had no user-facing consumer at all.
- **SEVERITY, stated so it is not over- or under-called:** not a board-wide
  mislabel (the board does not read these rows), not zero either. It also
  corrupts every home-side spread row in the CLV join, which is where it was
  found.
- Files (claimed 2026-08-15 23:0xZ — **claimed LATE, after the edit, which is a
  protocol lapse of mine; recorded rather than quietly backfilled**):
  `syndicate/features/shared/layer2_board.py`,
  `tests/test_layer2_book_prices_line.py`. Collision check RUN via
  `lane-guard.py`'s own `_claims()` at edit time AND again now: CLEAR both times,
  so no other lane was blocked by the gap.
- **FIX IMPLEMENTED, TESTED, ON MAIN AS `edbbee9d` — DEPLOY HELD.**
  `_side_line_from_cells` reads the handicap from the same cell as the price;
  no-op for away/h2h/props; returns None (caller keeps the row value) when books
  disagree on the sign. 8 new tests, 71 green across board + CLV suites.
  **Not deployed: it needs REFRESH-WORKER, and an MLB sim (pid 79) plus a board
  build were in flight.** Forward-only — today's openings keep the bad lines.
  Ship when the slate is quiet, then re-run the 525-cell invariant.
- **FIX unchanged and now fully justified:** at `layer2_board.py:852` take the
  line from the same cell as the price. Away is already right, so the change
  must not touch it — negate only for the home side, or carry
  `cell[side]["line"]` per book.
- **SAME-BOOK TEST RUN 2026-08-15 23:1xZ on `/api/board/book-grid` (mlb, 33
  spreads rows, 525 book-cells). THIS IS THE DECISIVE MEASUREMENT and it is
  UNIFORM, not statistical:**

      1. each book's OWN home/away lines sum to zero    525/525  consistent
      2. cell's home line vs the ROW's `line`             0/525  agree
                                                        525/525  OPPOSITE SIGN
      3. no-arb per book (implied home + implied away)  median 1.0483, none < 1.0

- **`book_prices` IS NOT MIXING BOOKS. Every book agrees with every other book
  and with itself.** The 2026-08-07 `_complementary` condition (*"books inside a
  single grid row disagree on the SIGN"*) is real but is **NOT** what is
  happening on this data. My previous entry blamed book-vs-book mixing; that is
  now refuted — 100% agreement between books.
- **THE ACTUAL DEFECT, and it is deterministic:** the ROW's `line` is the
  NEGATION of the cell's `home.line`, in every single case. So
  `layer2_board.py:852` building `book_prices = {book: cell["home"]["price"]}`
  and publishing it beside `row["line"]` pairs **the home team's price with the
  opposite handicap**. Every home-side spread opening is therefore recorded as
  `side=home, line=L, price=<home price at -L>`.
- **THIS PARTIALLY REINSTATES THE FINDING I WITHDREW, with a corrected
  mechanism.** The 16-of-17 no-arbitrage violations were REAL; my second reading
  ("confounded by book mixing") was wrong. It is not mixing — it is a uniform
  row-vs-cell convention mismatch. **Third revision of this attribution; this
  one is measured on 525 cells with 100% agreement rather than inferred from a
  neighbouring module's comment.** The sequence, so nobody re-treads it:
  feed transposes labels (WRONG) -> books disagree so `book_prices` mixes
  (WRONG) -> row.line is uniformly the negation of the cell's home line (this,
  measured).
- **STILL NOT ESTABLISHED — the user-facing question, now sharper.** `row["line"]`
  being the away handicap may be the board's INTENDED convention, in which case
  the cards are fine and only the home-side flattening at `:852` is wrong. The
  test is narrow: **does any template render `row.line` beside a HOME selection?**
  Read the card template before assigning any user-facing severity.
- **FIX, now well-specified:** at `layer2_board.py:852`, take the line from the
  same cell as the price (`cell[side]["line"]`) rather than inheriting
  `row["line"]` — either by carrying it per book or by negating for the home
  side. Do NOT "fix" the sign at the CLV end; the pairing is wrong where it is
  built, and every other consumer of `book_prices` inherits it.
- **TRACED 2026-08-15 23:0xZ. THE LINE IS SET AT `layer2_board.py:852-858`, AND
  THE DEFECT IS A DROPPED FIELD, NOT AN INVERTED SIGN.**

      "book_prices": {
          str(book): cell[side]["price"]        # <- price kept
          for book, cell in (row.get("cells") or {}).items()
          ...                                    # <- cell[side]["line"] DROPPED
      }

  Full chain: fetcher (`fetch_mlb_oddsapi_local.py`, EXONERATED — derives
  `home_line = -away_line` per lane) -> book grid (`book_grid.py:304`, passes
  `row.get("line")` through) -> `layer2_board` flattens each cell to a bare
  price -> `record_openings` stores that flat map -> `clv_join`'s same-book
  override reads `book_prices[book]` and pairs it with the ROW's line.
- **THIS REPO ALREADY KNEW, IN A NEIGHBOURING MODULE, AND SAID SO.**
  `board_cross_book.py` tags each quote with *"the CELL's own line, which is not
  always the row's line … this is the pairing guard"*, and `_complementary`
  documents the measured reason (production 2026-08-07, `spreads_alt`, first5):

      betmgm     away -1.5 (+210)   home +1.5 (-295)
      betrivers  away +1.5 (-240)   home -1.5 (+180)

  **Books inside ONE grid row disagree on the SIGN of the line.** That module
  refuses such pairings ("*spreads are signed per side*", postmortem §2.6, after
  a false +250.88% arbitrage). `layer2_board`'s `book_prices` drops the very
  field that guard depends on — and the comment above it says so deliberately:
  *"Flat {book: price}, not the whole cell."* The choice was made for artifact
  size; its cost is that sign information is unrecoverable downstream.
- **SO MY PREVIOUS CONCLUSION IS WRONG AND I AM WITHDRAWING IT.** I reported "the
  BOARD's home-spread `line` sign is inverted, 16 of 17 — possible user-facing
  mislabel". **That test was confounded by exactly this mixing:** it compared
  `book_prices` across books for one row-level line, and those books were not
  all quoting the same side. The 16/17 measures **sign disagreement BETWEEN
  BOOKS**, which is a known and expected market fact — not a board defect.
  **There is no evidence of a user-facing mislabel. Do not act on that claim.**
- **What IS established:** `book_prices` silently mixes books quoting opposite
  sides of a spread, so ANY consumer reading it for a spread selection can get
  the opposite bet's price. `clv_join`'s same-book override is one such consumer;
  that is the `-29.90`/`+30.428` mirror pair.
- **What is NOT established, and needs a same-book test to settle:** whether the
  ROW's own `line`+`price` (anchor book) are correct. My attempt was confounded —
  the two openings had DIFFERENT anchor books (onexbet, betopenly), and since
  books disagree on sign, an anchor-vs-anchor comparison proves nothing. The
  clean test is one book quoting both lines of one event.
- **REVISED FIX (do not ship before the same-book test):** carry the cell's line
  alongside its price — `{book: {"price": …, "line": …}}` — or refuse a same-book
  join whose book line is unknown. The size objection in that comment is real and
  should be answered with a line-only companion field, not by dropping the guard.
- **DISCRIMINATOR RUN 2026-08-15 22:4xZ. It trusts NEITHER label**, which is what
  makes it decisive: for one team, `-1.5` (win by 2+) is strictly harder than
  `+1.5`, so `implied(-1.5) < implied(+1.5)` is a no-arbitrage fact regardless of
  whose naming is right.

      source                          respects invariant   violates
      BOARD (published openings)            1 of 17          16
      FEED  (odds-history lanes)            2 of 2            0

  Board pairs span **15 distinct events** and many books; junk quotes
  (`novig -100000`) excluded. The single exception is `nordicbet -1.5=117 /
  +1.5=111` — implied 0.461 vs 0.474, a 1.3-point gap on a near-pick'em, i.e.
  inside the vig and not evidence of correctness.
- **The feed, on the same event, is internally right both times:** home `+1.5`
  at `-205` (implied 0.672, the easier bet, minus money) and home `-1.5` at
  `+168` (implied 0.373, the harder bet, plus money).
- **SO: `fetch_mlb_oddsapi_local.py` IS EXONERATED. The bug is downstream, where
  a published home-spread selection gets its `line`.** The hypothesis in this
  lane's header is CONFIRMED and the falsification branch (lane-collapse only)
  is REFUTED — lane collapse is real but cannot explain a systematic sign
  violation across 15 events.
- **MY EARLIER ATTRIBUTION IS NOW DOUBLY CORRECTED, and this is the final
  version.** First I wrote that the FEED "transposed its labels" (in
  `learnings.md`). Then I corrected that to "each point is internally
  consistent; the market state holds one lane at a time". **Measured, it is
  neither: the feed is correct and the BOARD is inverted.** The learnings entry
  from earlier tonight describes the right FAILURE MODE (a label whose
  convention is not stable across sources) but names the wrong culprit.
- **THIS IS BIGGER THAN CLV AND MUST NOT SHIP AS A CLV FIX.** These openings are
  recorded FROM published board rows, so if the board serves `side=home,
  line=-1.5` while the price is the `+1.5` price, **users are being shown the
  wrong side of the run line.** That is a correctness problem on the product
  surface; CLV merely made it visible.
- **UNVERIFIED, and it decides the severity — DO THIS BEFORE ANY FIX:** I have
  NOT checked what the rendered card/API actually displays. Two possibilities and
  they need different fixes: (a) the board's `line` field is genuinely inverted at
  the point of publication -> user-facing defect; (b) the board's `line` means
  something other than the home team's handicap (e.g. it carries the away line,
  or the market line) and only the CLV join misreads it -> internal-only. **The
  price data cannot tell these apart; only reading the publisher and the template
  can.**
- Next step, concrete: find where a spreads selection's `line` is set on the
  published row (start from `pipeline/layer2_shortlist.py` and the per-sport
  `cards.py`), and read what the card template renders beside it. Then decide (a)
  vs (b). **Still no deploy** — and generality beyond MLB is still unmeasured.

- Goal: for a spread, ONE source owns the sign of `line` and every consumer
  agrees with it. Testable outcome: for every same-book spreads row in
  `/api/ops/clv/report`, the opening's `(side, line, price)` and the close's
  `(side, line, price)` describe the SAME bet — checked by an assertion that does
  not itself rely on the label (see below) — and a test pins the convention per
  source.
- **WHY: a `-29.90` CLV on a market that never moved.** Event `69928d29…`
  (Seattle @ Houston), FanDuel spreads. The opening recorded `home -1.5 @ -205`;
  the close resolved `home -1.5 @ +168`. `-205` and `+168` are the two sides of
  ONE run line, so the "30-point move" is a bet differenced against its opposite.
- **REFINEMENT FROM READING THE FETCHER — my first framing was too strong and is
  corrected here before anyone acts on it.** I wrote in `learnings.md` that the
  feed "transposed its labels". **Each history point is internally consistent:**
  `fetch_mlb_oddsapi_local.py:505-525` derives `home_line = -away_line` and keys
  each lane by the home line, so `{away -1.5 / home +1.5}` and
  `{away +1.5 / home -1.5}` are both correct — they are **two different lanes of
  the same spreads market**.
  - **The real mechanism is that the odds-history market key carries NO line**
    (`event_id|home_team|away_team|market|bookmaker`), which `clv_join.py`'s own
    docstring already states. So every spread lane collapses into ONE market
    state and the last writer wins. At 06:02Z that state held the home `+1.5`
    lane; at 21:26Z it held home `-1.5`.
  - **What is still genuinely unresolved, and is this lane's question:** the
    opening says `home -1.5` costs `-205`; the 06:02 history says `home +1.5`
    costs `-205`. Same price, opposite line. **One of the two is using the
    opposite sign convention for a home spread, and I do not yet know which.**
- Hypothesis: the board's published `line` for `side=home` carries the OPPOSITE
  sign to the feed's `home_line`. If so every home spread opening is joined to
  the wrong lane, and away rows are joined correctly by accident.
- Falsification test: if the board and feed signs agree, then the mismatch is
  purely lane-collapse (the state simply held a different lane than the opening),
  the sign is exonerated, and the fix is to key history by line rather than to
  change any sign.
  - **Discriminator that does NOT trust either label:** for one event, take the
    published `book_prices` for the home `-1.5` selection and the feed's two
    lanes at the same instant. The lane whose `home_odds` EQUALS the published
    price identifies which line the board meant. Prices are the invariant here;
    labels are the thing under test.
- **SCOPE ALREADY MEASURED, so nobody re-derives it:** mlb 2026-08-15 same-book —
  spreads n=42, mean `+0.515`, median **exactly 0.000**, only 2 rows |clv|>10 and
  those two are a **mirror pair from this one event** (`+30.428` / `-29.900`),
  because both openings were recorded and each got the other's close. h2h/totals
  n=128, **zero** |clv|>10. **Severe per row, near-cancelling in aggregate** —
  so this corrupts per-recommendation CLV, variance, CIs and any "worst bets"
  list, while leaving the headline roughly intact. **It is NOT a headline
  emergency and must not be deployed like one.**
- Files (exclusive to this lane):
  - `scripts/fetch_mlb_oddsapi_local.py` — where `home_line`/`away_line` and the
    lane key are derived. Collision check RUN via `lane-guard.py`'s own
    `_claims()`: CLEAR.
  - `tests/test_spread_line_sign_convention.py` (new). CLEAR.
  - **NOT claimed, held by other OPEN lanes — coordinate, do not edit across:**
    `syndicate/features/shared/odds_refresh_tracking.py`
    (`closing-stamp-is-detection-time`) and
    `syndicate/features/shared/clv_join.py` (`clv-without-settlement`). Both are
    this session's lanes, so the marker can simply be moved if the fix lands
    there — but the claim must be updated first, not bypassed.
- Verification: (1) the discriminator run on >= 5 events across >= 2 books, with
  the winning convention named per source; (2) a test pinning it; (3) the
  spreads |clv|>10 count re-derived and the mirror pair gone.
- **Generality is UNMEASURED and must be established before any fix ships:** all
  of the above is ONE event, ONE date, MLB, FanDuel. NFL/NCAAF spreads and other
  books are untested, and MLB run lines are the asymmetric case that makes the
  error visible — symmetric `-110/-110` spreads would hide it entirely.
- Blocked by: none. **No deploy without `/preflight`**, and not before generality
  is measured — a sign flip applied to a source that was already correct would
  invert every spread join instead of fixing it.

### clv-without-settlement — OPEN — **GOAL RE-SCOPED 2026-08-15 23:5xZ: `clv_pct` PER RECOMMENDATION ALREADY EXISTS; THE GAP IS EXPOSURE, AND THE PREDICTION LEDGER IS THE WRONG SUBSTRATE** — opened 2026-08-14 — session: lane-cleanup
- **MEASURED BEFORE BUILDING, and it stopped the build:**
  - `/api/portfolio/summary`: **3 prediction records**, all sport `multi`,
    `settled: 0`, `avg_clv: null`. That is the whole ledger.
  - Same instant, published recommendations: **11,864 opportunities considered**,
    ~600 openings recorded for the date.
  - So `PredictionResult.clv_pct` — the field that exists and is never populated
    — sits on a table with **3 rows**. Filling it would make
    `/api/portfolio/summary.avg_clv` a real number computed over 3
    records: **a metric with no denominator, which is worse than null** because
    null is honestly empty and a number invites use.
- **`clv_pct` PER RECOMMENDATION IS ALREADY PRODUCED.** `compute_clv_for_date`
  emits one row per published opening, each carrying `clv_pct`, `beat_close`,
  `close_source`, `close_timing`, `model_edge_pct` and `ev_pct`, keyed by
  `event_id|market|player|segment|side|line|bookmaker`. **An opening IS a
  published recommendation** — that key is the recommendation's identity.
  Reachable now: `/api/ops/clv/report?date=...&sport=...&rows=1` (179 same-book
  rows today).
- **THE REAL GAP, stated precisely:** the per-recommendation CLV exists only on
  an ops diagnostic endpoint. Nothing a user or the board reads carries it. The
  work is EXPOSURE, not computation — and that is a different, smaller job than
  the lane's original wording implies.
- **THREE SUBSTRATES, materially different work — needs a decision, not a
  default:**
  1. **Attach at artifact build** (`layer2_shortlist`) — every published row
     carries its own `clv_pct`. Truest home; costs a WORKER deploy and only
     applies to rows built after it ships.
  2. **Join at serve time** on web — `/api/board/layer2-shortlist` merges the
     joiner's rows by key. Web-only deploy, works on today's data immediately,
     but recomputes per request (the joiner is a pure read, so it is legal).
  3. **Backfill the prediction ledger** — REJECTED on the evidence above until
     something actually writes recommendations into it at volume.
- **NOT STARTED. No files claimed for this.** Recorded so the next session does
  not rebuild what exists or build onto the 3-row table.

 — OPEN — **PUBLISH FIXED AND MEASURED (web `bebe87c9`, live 19:36:45Z): `same_book_n` 0 → 144, FIRST UNBIASED CLV = -0.07% AT A 27.1% BEAT RATE (PRELIMINARY, TAKEN PRE-FIRST-PITCH). THE LANE'S BREADTH HYPOTHESIS IS REFUTED** — opened 2026-08-14 — session: lane-cleanup
- **RESULT 2026-08-15 19:38Z — the publish fix landed and it changed the answer.**
  `PUBLISH_FAILED`×8/16h (`HTTP 403 FORBIDDEN`, last 19:32:50Z) → `PUBLISH_OK`×2
  at 19:37:00Z and 19:38:10Z, 15s after the deploy; zero failures since. Web now
  holds the artifact. MLB: `openings 0→520`, `resolved 0→293`,
  `same_book_n 0→144`. Also landed on main as `baec34a8` — it had existed ONLY
  on deploy branches (web and main both carried blob `aff59302`).
- **THE PRE-REGISTERED RULE IS REFUTED. Do not re-derive it.** "If `same_book_n`
  is still 0, the blocker is odds-history breadth" — `same_book_n` moved 0→144
  with **no change to odds history**; only the reader moved. Breadth is real but
  it constrains `resolved`, not `same_book_n`:
  `no_market_in_history: 172`, `close_precedes_open: 42`, `line_mismatch: 13`.
- **FIRST UNBIASED NUMBER, and the selection effect is now measured:**

      scope                    n     avg_clv   beat_close
      same_book (UNBIASED)   144     -0.0711      27.1%
      book_agnostic_close    143     +2.7261      82.5%
      different_book_close     6     +1.3907      66.7%

  The biased scopes say the board crushes the close; the honest one says it is
  flat-to-negative and beats the close **27%** of the time. Supersedes the
  retracted `-5.215`.
- **THE LANE'S GOAL WAS ALREADY MET — `clv_pct` PER RECOMMENDATION EXISTS AND
  SHIPS. Do not build it.** Checked 2026-08-15 21:1xZ before writing any code:
  `/api/ops/clv/report?date=...&sport=mlb&rows=1` returns **355 rows, 355 of
  them carrying `clv_pct`**, plus `beat_close`, `close_book_scope`,
  `model_edge_pct` (291/355) and `ev_pct` — no grading, no outcome, no
  `settle_result`, exactly as the goal specifies. `clv_join.py` has done this
  since it was written; it was invisible only because of the 403 publish bug
  fixed earlier today. **The build was already done and the lane did not know.**
  - **The prediction ledger is NOT the recommendation stream and must not be
    used as one** — `/api/portfolio/summary` reports **3 predictions, 0
    settled, `avg_clv: null`** for a single pseudo-sport `multi`, against 636
    MLB openings recorded today. `record_result()` is also the wrong door: it
    computes `clv_pct` only via the settlement path this lane is defined to
    avoid.
- **WHAT WAS ACTUALLY MISSING IS THE SEGMENTATION THE AUDIT WANTED IT FOR.
  Computed below on the 172 unbiased same-book rows — biased scopes excluded.**
- **§4, THE THRESHOLD QUESTION: model edge DOES buy CLV, and the honest
  threshold is far higher than 2%.**

      model_edge bucket    n     avg_clv    beat_close
      edge < 0            69     -0.419        26.1%
      0-2%                25     -1.772        24.0%
      2-5%                17     -1.245        29.4%
      5-10%               25     -0.112        32.0%
      10%+                12     +1.396        41.7%

  Monotone in BOTH columns from `0-2%` up, and **only the 10%+ bucket is
  positive**. On this evidence a 2% threshold publishes rows that lose CLV.
  **Unexplained and left unexplained:** `edge < 0` (-0.419) beats `0-2%`
  (-1.772). Do not build a story on it; n is small.
- **THE HEADLINE LOSS IS ONE BOOK-MARKET CELL, NOT A BROAD PROBLEM.** Two
  findings looked separate ("h2h is bad", "fanduel is bad"); cross-tabbing
  showed they are one:

      cell                        n      avg_clv    beat
      ALL same_book             172      -0.672     27.9%
      FanDuel h2h ONLY           54      -2.648     20.4%
      EVERYTHING ELSE           118      +0.232     31.4%

  FanDuel h2h is **31.4% of rows and 124% of the total loss** — remove it and
  the board's CLV is **positive**. It is not h2h generally (DraftKings h2h
  `+0.488`, n=24) and not FanDuel generally (FanDuel totals `+0.122`, spreads
  `+0.132`).
- **ANSWERED 2026-08-15 21:5xZ — AND MY OWN "FanDuel h2h" HEADLINE IS RETRACTED.
  IT IS NOT A FANDUEL PROBLEM AND NOT AN h2h PROBLEM.**
  - **The cause: rows whose "close" was sampled AFTER FIRST PITCH.**
    `close_age_seconds = (commence - stamp)` (`clv_join.py:216,254`), so a
    NEGATIVE value means the close observation is POST-COMMENCE — an in-play
    price, not a close. **37 of 172 same-book rows (21.5%) are post-commence,
    and they carry 60% of the entire loss.**
  - **The worst four rows are one event.** `dbbb481a…` h2h away: open `-186`,
    "close" `+168`, stamped 20:34:26Z against a 19:08Z first pitch — 86 minutes
    into the game. That is a team going behind early, priced live. It is not
    CLV. Four published openings (kalshi, polymarket, betopenly, betfair_ex_eu)
    all matched that same FanDuel pair, so one bad close entered the mean four
    times at ~-27 points each.
  - **CLEANED, THE FANDUEL CELL IS UNREMARKABLE AND DRAFTKINGS IS WORSE:**

        cell                              n     avg_clv    beat
        ALL same_book (as I reported)   172     -0.672    27.9%
        EXCLUDING post-commence closes  135     -0.346    25.2%
          FanDuel h2h, cleaned           47     -0.616    23.4%
          DraftKings h2h, cleaned        21     -1.378    14.3%

    **"Strip FanDuel h2h and CLV is positive" does not survive cleaning. Do not
    act on it.** The board's honest same-book CLV on this date is about
    **-0.35**, not -0.67, and it is not concentrated in one book-market cell.
  - **How I got it wrong, recorded because the shape repeats:** I read a
    negative `close_age_seconds` as "close precedes open" WITHOUT reading the
    field's definition, then built an attribution on it. The guard for
    close-precedes-open (`:430`) was never the issue — it correctly did not
    fire, because `close > open` on all 37 rows. **Two different defects can
    both produce a negative number in a field you did not define.**
  - **H4 (favourite asymmetry) and H2 (stale openings) are REFUTED by data:**
    FanDuel vs DraftKings h2h open-price medians 102 vs 115.5, favourite share
    41% vs 29%, `close_age` medians 8025s vs 8265s — comparable on every axis.
    **H3 stays refuted at the code level.** What remains of H1 is small and is
    NOT FanDuel-specific.
  - **`n=172` IS NOT 172 INDEPENDENT OBSERVATIONS.** The same book's open/close
    pair is reused for every published opening on that event/market/side, so one
    pair can enter the mean many times. Any confidence interval over these rows
    is overstated until that fan-out is collapsed.
- Files (claimed 2026-08-15 22:0xZ, collision check CLEAR via `lane-guard.py`'s
  own `_claims()`): `syndicate/features/shared/clv_join.py`,
  `tests/test_clv_close_timing.py` (new).
- **DEFECT FIXED AND VERIFIED — web `4316c907` live 21:41:18Z, main `a68e1ce0`.**
  Headline now counts same-book AND pregame closes only. Verified by recomputing
  the mean from the rows at the same instant: `-0.3077` both ways, n=131,
  `in_play_excluded_n=48`, 374/374 rows carry `close_timing`.
  - **The in-play bucket flipped sign between readings** — strongly negative at
    21:1xZ, **`+0.7937` (n=48, beat 54.2%) at 21:4xZ**. The old code would now
    publish `-0.0124`. **The contamination is noise, not a fixed bias**, and it
    could have manufactured a "CLV is improving" story out of game-state drift.
  - Clean series moved 0.04 pts across 2.5h (`-0.346` -> `-0.3077`); dirty series
    moved 0.66 pts (`-0.672` -> `-0.0124`).
  - `clv_join.py` was **entirely absent from main** until `a68e1ce0` (600
    insertions), the same "lives only on a deploy branch" pattern as the
    allowlist entry.
- **OLD, kept for the record:**
- **THE DEFECT TO FIX (its own change, not done here):** `compute_clv_for_date`
  labels post-commence closes but still counts them in the headline
  `avg_clv_pct`. The docstring already anticipates this — *"a caller that wants
  only gold data can filter on them"* — but the headline IS that caller and does
  not filter. Either exclude `close_age_seconds < 0` from the headline or report
  it as a separate scope beside `same_book`, the way book scopes already are.
- **HYPOTHESES FOR THE FanDuel-h2h CELL, WRITTEN BEFORE TESTING (2026-08-15 21:3xZ):**
  - **H3 — join artifact (best-of-N open vs FanDuel close). REFUTED AT THE CODE
    LEVEL BEFORE ANY DATA WAS PULLED.** `clv_join.py:380` sets
    `open_price_override = book_prices.get(book)` whenever it matches a
    same-book close, and `:435` prefers that override over
    `opening.get("price")`. So within `same_book`, open and close are the SAME
    book's prices. The best-of-N price only survives as `open_price_best_book`,
    which is not what `clv_pct` is computed from. **This candidate is dead;
    do not re-raise it without new evidence.**
  - **H1 — real movement.** FanDuel h2h genuinely drifts against the sides we
    publish. Falsified if open/close timing and price levels look like
    DraftKings h2h, which is `+0.488` over the same events.
  - **H2 — stale openings.** Our recorded FanDuel opening is old relative to its
    close, so we are comparing a price nobody could still get. Falsified if
    `open_captured_at` / `close_age_seconds` for the FD cell match the rest.
  - **H4 — favourite/underdog asymmetry (NEW, and the arithmetic favours it).**
    `clv_pct` is in probability POINTS, and `_implied_from_american` is convex:
    the same relative move is worth more points at -250 (71.4%) than at +150
    (40%). If the FD h2h rows sit systematically on heavy favourites, the cell
    can read negative from the METRIC's scale rather than from worse prices.
    Falsified if the FD and DK h2h price distributions are comparable.
  - **H5 — side selection.** We publish one side (the value side); if that side
    is systematically the one that drifts out at FanDuel, the cell is real but
    is a statement about our selection, not about FanDuel.
  - **Sign convention, stated so nobody re-derives it backwards:** `clv_pct =
    (closing_implied - original_implied) * 100`. **Negative means the close is
    LONGER than the price we took** -- we took a short price and it drifted out.
- **CAUSE OF THE FanDuel-h2h CELL IS NOT ESTABLISHED.** Candidates not
  discriminated: FanDuel moneyline closes genuinely moving against us; our
  openings at FanDuel being stale relative to its close; or a `matched_bookmaker`
  artifact in the join. **Do not act on this until one is measured** — its own
  lane.
- **ALL OF THE ABOVE IS PRELIMINARY, same caveat as the headline:** rows fetched
  ~21:1xZ with roughly 10 of 14 MLB games unstarted, so most "closes" are latest
  observations. One date, one sport. Several buckets are n < 25. Re-run after
  the settled read before anything is promoted to a threshold change.
- **SECOND READING 2026-08-15 20:4xZ (4 of 14 MLB games started) — THE NUMBER IS
  MOVING, AND DOWNWARD.** Same endpoint, same date, ~1h later:

      reading           games started   same_book_n   avg_clv   beat_close
      19:38Z (first)         0 of 14         144      -0.0711      27.1%
      20:4xZ (second)        4 of 14         167      -0.668       29.3%

  - The biased scope barely moved (`book_agnostic_close` +2.7261 -> +2.8425,
    n=143 -> 164, beat 82.5% -> 83.5%), so the gap between the honest and the
    flattering number **widened** from ~2.80 to ~3.51 points.
  - `different_book_close` FLIPPED SIGN, +1.3907 -> **-0.5665** (n=6 -> 9). At
    n<10 that is noise; do not read it as a trend.
  - `unresolved_reasons` grew as expected: `close_precedes_open` 42 -> 64,
    `line_mismatch` 13 -> 19, plus a new `no_pregame_observation: 4`.
    `no_market_in_history` held at 172.
  - **STILL NOT THE SETTLED NUMBER.** Last first pitch is **2026-08-16T01:40Z
    (20:40 CDT)** — 10 of 14 games had not started at this reading.
  - **DIRECTION OF TRAVEL MATTERS FOR ANYONE WAITING ON THIS:** both readings
    are negative and the second is 9x more negative. Nothing here supports "the
    board beats the close"; the evidence so far points the other way.
- **A re-read is ARMED** (background monitor, fires after 01:45Z) to capture the
  settled figure. If this session is gone when it fires, run by hand:
  `/api/ops/clv/report?date=2026-08-15&sport=mlb` and record `same_book_n`,
  `avg_clv_pct`, `beat_close_rate` plus the `by_book_scope` table.
- **Minor data oddity, logged not chased:** `by_book_scope` carries a bucket
  keyed `None` with `n=0`. Harmless today; it means some row's scope label is
  null rather than a scope name. Worth a look only if `n` ever becomes nonzero.
- **`-0.0711` IS PRELIMINARY — timing, not arithmetic.** Taken 14:38 CDT, before
  first pitch for most of the slate, so most "closes" are latest observations.
  **Re-read after the last MLB game starts.** One date, one sport, 144 pairs.
- **STILL OPEN, and this is what the lane is now for:** (1) re-read post-slate
  and record the settled number; (2) NFL 246 openings / WNBA 80 both `resolved:
  0` — odds history has no markets for them; (3) NBA/NHL/NCAAF/NCAAB/soccer
  record **0 openings at all** — nobody has asked why; (4) `clv_pct` per
  recommendation, the lane's original goal, is NOT built.
- **Handed back:** lane left OPEN and unclaimed at the end of this session; the
  per-session marker was released. `artifact_publisher.py` is free.

- **THE PUBLISH FAILURE IS DIAGNOSED. Every link measured 2026-08-15 19:0xZ,
  no link inferred.**
  1. **Recorder healthy.** refresh-worker: `[clv_opening_ledger] OPENINGS
     date=2026-08-15 ... already=490`. **490 real openings exist.**
  2. **Sender tries.** refresh-worker (live `c67f7373`) HAS
     `reports/intelligence/clv_openings/*.jsonl` in `HOT_ARTIFACT_PATTERNS`, so
     it calls `publish_hot_artifact` — but only `if written:`, which is why the
     attempts are sparse rather than per-tick.
  3. **Receiver refuses: `HTTP Error 403: FORBIDDEN`**, 8 times in 16h.
     `_write_published_artifact` returns 403 on exactly one condition —
     `if not is_hot_artifact_relative_path(relative_path)` (`ops.py:1100-1101`).
  4. **Web's copy does not have the pattern.** Live web `0bf866c3` →
     0 occurrences of `clv_openings`.
  5. **Not a transport, token or size problem, and this was checked rather than
     assumed:** soccer `live_state` artifacts logged `PUBLISH_OK` to the SAME
     url with the SAME token at 19:11:25Z, seconds after a clv `PUBLISH_FAILED`.
     Zero `SKIP_NOT_CONFIGURED` lines. The file is ~286KB against a 4MiB stream
     threshold, so it takes the proven JSON-envelope path.
- **CORRECTION TO MY OWN FIRST READING, made before acting on it.** I said the
  entry was "on origin/main" and that web had merely fallen behind. **It is NOT
  on main.** Blob for `artifact_publisher.py` is `aff59302` on BOTH web
  `0bf866c3` and `origin/main`; the worker carries `ee94fe6b`. I had grepped the
  WORKING FILE and reported it as main. The entry exists only on the worker's
  deploy branch and in the working tree — it has never been committed to main,
  so it is one `git checkout` away from being lost.
- **THE FIX IS A DEPLOY, NOT A CODE CHANGE.** Diff between web's blob and the
  worker's is a single pure addition: the comment plus
  `"reports/intelligence/clv_openings/*.jsonl"`. The working tree is
  byte-identical to the worker's deployed blob (`ee94fe6b`), so shipping it to
  web makes sender and receiver agree.
- Files (exclusive to this lane): `syndicate/features/shared/artifact_publisher.py`.
  Collision check RUN via `lane-guard.py`'s own `_claims()`: CLEAR.
  **NOT claimed:** `syndicate/blueprints/ops.py` (held by `quote-feed-age-alarm`)
  — no edit needed there, the receiver logic is already correct.
- Falsification test: if web still 403s after the allowlist ships, the 403 is
  NOT coming from the allowlist branch and `ops.py:1100` is the wrong line —
  re-read the receiver before changing anything else.
- Verification: (1) a `PUBLISH_OK` line for a `clv_openings` path in
  refresh-worker's log; (2) `/api/ops/artifacts/export?pattern=...clv_openings/*.jsonl`
  returns `count >= 1, bytes > 0`; (3) `/api/ops/clv/report?date=2026-08-15&sport=mlb`
  returns `openings > 0`. **All three, or it is not fixed.**
- **DOES NOT CLOSE THE LANE.** This unblocks the measurement; it does not
  produce `clv_pct`. Breadth remains untested.

- **STATUS 2026-08-14 19:50 CDT.** Recorder LIVE (`2b14fbeb`) + `book_prices`
  LIVE (`96e3a9b7`). Joiner is **library-only, no call site, NOT deployed**
  (`deploy/clv-joiner-guards-r2`, `2f596260`). 42 tests green.
- **THE `-5.215` SAME-BOOK AVERAGE IS RETRACTED. Do not resurrect it.** It came
  from 25 rows and looked right — it even had the OPPOSITE SIGN to the biased
  scopes, which is what a genuine bias correction looks like. Two independent
  defects, now refused by name:
  - `line_mismatch` / `line_unverifiable` — history keys carry no line, the
    point's `line` block does; `home -5.0` was being differenced against a
    `home -1.5` close.
  - `close_precedes_open` — **25 of 25** closes were captured BEFORE their
    openings. **This is a PRODUCTION condition**, not a backfill artifact: it
    fires whenever a market is first published after the last pregame
    observation of it.
- **Current honest output on real data:** `same_book_n=0`, `avg_clv_pct=None`,
  `unresolved={close_precedes_open: 38, no_market_in_history: 14,
  no_pregame_observation: 23, line_mismatch: 1}`.
- **BLOCKED ON THE WORKER OOM LOOP `[2026-08-14 20:38 CDT]`.** The worker has
  been OOM-killed **18 times** today, ~1 per 11-15 min per instance across 7
  instances. Tomorrow's measurement needs the worker to stay up long enough to
  record a full day of openings, so **this lane is downstream of the memory
  lanes.** `#435` (`c9378c91`) is live and owns the diagnosis. **Worker deploys
  are HELD.**
- **TODAY'S OPENINGS ARE STRANDED ON THE WORKER.** `/api/ops/clv/report` reads
  `openings=0` for all sports while the worker has ~150+ recorded, because the
  publish fires only on `written > 0` and every 08-14 market was first-seen
  before the publish shipped. Not a bug in the recorder; a gap in when it
  pushes. One-shot-per-boot publish is the fix, and it needs a worker deploy.
- **THE MEASUREMENT IS NOW EXECUTABLE (shipped 2026-08-14 ~20:05 CDT).** It was
  not before: the joiner had no call site and the openings were unreadable off
  the worker. `GET /api/ops/clv/report?sport=<s>[&date=<d>][&rows=1]` is live on
  web (`d9a39ce8`); the worker publishes the openings (`d70f70d8`).
- **NEXT ACTION — the first clean measurement is 2026-08-15 (Central).**
  Production's 08-14 openings only began at 18:32 CDT, so tonight's file is
  late-loaded and its closes mostly predate its openings. Tomorrow, run
  `compute_clv_for_date('2026-08-15', sport)` per sport and read
  `same_book_n` + `avg_clv_pct`. **If `same_book_n` is still 0, the blocker is
  odds-history breadth** (median 2 books per event-market vs the board's best
  of ~13), not the joiner.
- **Known gaps, measured, each its own lane if pursued:** NFL and WNBA resolve
  0 — their odds-history artifact for 08-14 has no markets at all. MLB
  `_alt`/`_lay`/`3_way` families are absent from history entirely.
- **JOINER BUILT 22:5xZ** — `syndicate/features/shared/clv_join.py`, branch
  `deploy/clv-joiner` (`57e32a04`, off `2b14fbeb`). **Library only, no call
  site, NOT deployed** — it ships no production behaviour.
- **THE FIRST CLV NUMBERS THIS SYSTEM HAS EVER PRODUCED, on 150 real openings:**

      scope                  n    avg_clv   beat_close
      different_book_close  32     +6.206    29/32 (91%)
      book_agnostic_close   27     +2.716    18/27 (67%)
      same_book              0         --       --

  **`avg_clv_pct` is None and that is the correct answer.** A +6.2-pt average
  at a 91% beat rate is a SELECTION EFFECT, not skill: the board publishes the
  BEST price across books by construction, so pairing that opening with another
  book's close compares a best-of-N draw to a single draw. The headline counts
  same-book rows only; biased scopes are reported beside it, never blended.
- **What the join can and cannot reach** `[measured, mlb 78 openings]`:
  - props **28/28 matched (100%)**
  - `no_market_in_history` 18 — `h2h_lay`, `totals_alt`, `h2h_3_way`,
    `spreads_alt` are absent from odds history entirely (capture-side gap)
  - 32 game rows matched only via a DIFFERENT book
  - **NFL 0/60 and WNBA 0/12** — their odds-history artifact for 2026-08-14 has
    no markets at all. Capture-side, not a join defect. **Own lane.**
- **THE CHEAP FIX FOR SAME-BOOK CLV, and the next action:** have the opening
  ledger record a MAINSTREAM-book price alongside the best-book one. Odds
  history tracks fanduel/betmgm/draftkings; the board picks polymarket /
  prophetx / betfair_ex. One extra field on each opening makes an unbiased
  same-book comparison possible from tomorrow. Without it the headline stays
  None no matter how good the joiner gets.
- **Recorder is LIVE and verified** — refresh-worker `2b14fbeb`,
  `OPENINGS rows_in=150 written=150 ... truncated=False` at 22:32:02Z.
  Idempotence on the production disk (`written=0 already=150`) is STILL
  unconfirmed; builds are ~21 min apart.
- **UPDATE 22:3xZ — option (a) chosen by the user and SHIPPED.** refresh-worker
  `2b14fbeb`, live 22:20Z. `[clv_opening_ledger] OPENINGS ... rows_in=150
  written=150 already=0 duplicate=0 unkeyable=0 truncated=False` at 22:32:02Z.
  Openings are now being recorded; they were being lost on every build before.
- **OWED, in order:** (1) read a SECOND `OPENINGS` line to confirm idempotence
  in production (`written=0 already=150`) — builds are ~21 min apart; (2) build
  the joiner. (3) optional: put `clv_openings` on
  `/api/board/layer2-shortlist`, which currently omits it (log-only).
- **THE JOINER'S KNOWN PROBLEM, inherited deliberately:** odds history is keyed
  `event_id|home_team|away_team|market|bookmaker` with **no side and no line**;
  the side lives as `entity` INSIDE the history points. The opening ledger keys
  on `event_id|market|player|segment|side|line|bookmaker`. Mapping `side` ->
  `entity` is the unsolved half and must be measured against real data, not
  assumed — the settlement join already failed exactly here (4,560
  `no_key_match` of 8,276).
- **The close is the easy half and is already available:** stamped
  `closing_line` on only ~1.7% of markets, but `history_points > 0` on 100%, so
  derive it from the last pregame observation and LABEL which one was used
  (`observed_transition` vs `last_pregame_quote`) plus `close_age_seconds`.
- Goal: audit §7 ranked fix **#1** — produce `clv_pct` per recommendation with
  no dependency on grading, outcomes or `settle_result`. The audit calls this
  the one measurement that unblocks §4's threshold, §6's cadence decision, and
  every "where should modelling effort go" question.
- **READ-ONLY SO FAR. No files claimed, no code changed.**

**FINDING 1 — the CLOSE side is in far better shape than the audit implies,
but not where it says.** `[measured 08-14 21:3xZ via /api/ops/odds-history/inspect]`

      sport/date        markets   closing_line STAMPED   history_points > 0
      mlb  2026-08-13       1074          18  ( 1.7%)        1074 (100%)
      wnba 2026-08-13        119          11  ( 9.2%)         119 (100%)
      mlb  2026-08-14       3361           0  ( 0.0%)   (no transitions yet)

  The stamp fires only when the pregame->live transition is OBSERVED
  (`odds_refresh_tracking.py:1599` requires `was_confirmed_pregame` and a prior
  `is_live is False`). Only 81 of 1074 MLB markets were ever seen live at all.
  **Building the join on the STAMPED close yields ~18 rows.** But every market
  has history (median 20 points), so a close is DERIVABLE for ~100% by taking
  the last pregame observation before `commence_time`.
- **Design consequence:** the two are NOT the same measurement and must never be
  mixed silently — the `book_margin_model` lesson. A CLV row must carry
  `close_source` = `observed_transition` (gold, ~2%) vs `last_pregame_quote`
  (derived, ~100%) plus `close_age_seconds` = commence_time - captured_at, so a
  close taken 2h early (the pregame sweep cadence) is visible as such.

**FINDING 2 — THE BLOCKER. The OPENING side is effectively unavailable, and the
audit's premise that this is reachable "without touching the 367 MB chunk path"
does not hold.** `[measured 08-14]`
  - `data/prediction_ledger.json` holds **3 records** (it is the portfolio's
    positions — the `pending_count: 3` on `/api/portfolio/summary`), NOT the
    8,276 recommendations.
  - The 8,276 recommendation records WITH their opening `quote` are written to
    `evaluation_ledger_chunks/<date>.jsonl` — the 367 MB path.
  - `board_state_ledger_recorded_fingerprints` is only per-date HASHES; it
    records THAT a board state went into those chunks, not the openings.
  - **The chunks are not merely expensive, they are being SKIPPED at read time.**
    Observed in refresh-worker logs 21:24:54Z:
    `[intelligence_evaluation] SKIP_OVERSIZED_LEDGER_CHUNK path=2026-08-05.jsonl
    bytes=367229260 ceiling=256000000`. And 19 of 21 dates do not exist at all.
  - So openings are unreadable for every date, including the two that exist.

**THE DECISION THIS NEEDS (not mine to take alone — it is a build):**
  - **(a) Record a compact opening snapshot going forward.** One small JSONL per
    date, first-sighting-only per `market_id`: sport, market, side, price,
    bookmaker, books_quoting, fair_prob, model_prob, captured_at. Bounded by
    distinct market_ids/day (~3.4k for MLB), so kilobytes, not 367 MB. The
    joiner then needs no chunk access at all. **Cost: first real CLV number is
    ~24h away, not today.** This is what "unrecorded is unrecoverable" implies.
  - **(b) Recover openings from the 08-05/08-06 chunks.** Rejected unless
    overridden: they exceed the read ceiling and are already skipped, so this
    means raising a guard that exists for OOM reasons on a 4 GB worker, to
    recover 2 dates.
- **Recommendation: (a).** It is the audit's own "smallest change that starts
  capturing CLV" once Finding 2 is accounted for, and it does not touch the
  memory-sensitive path the two OPEN memory lanes are working.
- **NEXT ACTION:** get a decision on (a) vs (b). If (a), claim
  `pipeline/intelligence_state.py` (writer) — **currently held by
  `layer2-board-freshness`, so that lane must be consulted first.**
- Files: none claimed yet, deliberately.

### quote-join-enrich-cost — FOLLOW-UP 2026-08-14 04:37Z — the fix HOLDS, the workload OUTGREW it

- **UNION-NARROWING ANALYSIS 2026-08-14 05:0xZ — TRACED, NOT SHIPPED. Read the
  equivalence warning before writing any of it.**
  - **Where the ~12k rows/call come from.** The union is
    `by_event | by_player | team_groups`
    (`odds_book_quotes.py` ~1292-1307). For a GAME row, `wanted_teams` pulls in
    **every quote row for that game** — every market x every book x every
    selection. That branch dominates; `by_event` and `by_player` are narrow.
  - **OPTION A — market prefilter.** The caller already passes `market`. A
    `by_market` index intersected with the union would cut it by roughly the
    markets-per-game factor (potentially 10x+).
    **NOT equivalence-preserving.** Today the order is identity FIRST, then
    market narrowing with `candidates = narrowed or candidates`. That trailing
    `or` means a market-vocabulary mismatch **falls back to every row of the
    game**. Prefiltering by market removes that fallback: rows that today
    return a same-game quote would return `None`.
    Arguably MORE correct — but it is a silent-failure join, and the decision
    to drop the fallback must be made deliberately, not as a side effect of an
    optimisation.
  - **OPTION B — skip `team_groups` when `by_event` or `by_player` already hit.**
    Team matching is the FALLBACK identity signal; when `event_id` matched, its
    rows are the same game anyway. Same objection: it changes which rows reach
    `identified`, so it is not equivalence-preserving either.
  - **WHY NEITHER WAS SHIPPED TONIGHT.** The original `#414` index was safe
    because it was PROVABLY equivalent — 30+ query shapes asserted identical
    against a full-scan reference, exercising `by_event`, `by_player`,
    `by_teams_fallthrough` AND `no_identity`. Both options above deliberately
    change the identified set, so a differential test cannot pass; they need a
    test that PINS the new semantics, plus an explicit answer to "is losing the
    market fallback intended?".
  - This function's own docstring is the reason for the caution: *"a missing
    quote is visibly missing, a wrong one silently misprices the card and, once
    `#213` records it at bet time, poisons CLV."*
  - **RECOMMENDED ORDER for whoever takes it:** (1) decide the fallback
    question — it is a product call, not a performance one; (2) write the test
    that pins the chosen semantics; (3) then implement. Doing 3 first is how a
    silent mispricing ships.

- **The `#414` index is still doing its job.** 833,619 rows walked against a
  13,215,068-row shard = **6.3% scanned**, ~16x reduction, consistent with the
  21.5x measured at 00:18Z. It has not degraded.
- **But per-game cost is climbing again: 7-8s -> 14.70s.** Fresh MLB readings:
  ```
  04:37:09  total 14.70s  walked  833,619  shard 13,215,068  calls 69
  04:29:34  total  9.12s  walked  760,417  shard 12,832,072  calls 44
  04:15:55  total  4.76s  walked   16,642  shard     49,172  calls  2
  ```
- **TWO separable drivers, and neither is the index failing:**
  1. **Call count 20 -> 69 per game.** More candidates enriched — good for board
     richness, linear in cost.
  2. **Cost per call 0.2755 -> 0.7346s (2.7x).** The shard grew again:
     **~191k rows/call now**, against ~216k earlier and ~83k yesterday
     afternoon. 6.3% of a bigger shard is still more rows.
- `join` is **14.69 of 14.70s**; `post`, `score` and `unattributed_s` are all
  0.00. The segment split is clean and the join is the entire cost — same shape
  as before the fix, at a lower level.
- The two small games at 04:15 (3.95s / 4.76s on a 49,172-row shard) confirm
  cost tracks shard size closely, which is what a join-dominated profile
  predicts.
- **NEXT LEVER, unchanged from what this lane already named: the residual ~12k
  rows walked PER CALL.** Indexing removed the full-shard scan; what remains is
  a linear pass over the candidate union, and at 69 calls a game that is ~833k
  row visits per game. Narrowing the union, or making the per-row test cheaper,
  is the remaining work.
- **Do not read this as a regression of the fix.** Without the index those same
  games would walk 13.2M rows instead of 833k. The lane's verification stands;
  this records that the win is real and eroding under growth.

### quote-join-enrich-cost — PRODUCTION RESULT IN 2026-08-14 00:18Z — the index works, 21.5x measured

- **Both profilers fired at 00:11:15 and 00:18:46Z**, after
  `SYNDICATE_SLOW_ROW_TOTAL_SECONDS=1` / `SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS=1`
  were set on refresh-worker (both were absent, defaulting to 5s — at which the
  instruments could never fire if the fix worked).
  ```
  SLOW_SEGMENT_PROFILE  total_s=7.17 tail_s=7.17 enrich_block=7.17
                        rows_walked=502,157  shard_rows=10,806,750  calls=50
  SLOW_ENRICH_PROFILE   total_s=7.17 join_s=7.16 post_s=0.00 score_s=0.00
                        accounted_s=7.17 unattributed_s=0.00
                        candidates=26 join_calls=26 join_s_per_call=0.2755
  ```
- **READ THESE COUNTERS AS CUMULATIVE, NOT PER-CALL.** `_bump` accumulates
  across the window, so `shard_rows` is 50 calls x ~216k, not a 10.8M-row
  shard. Per call: **216,135 rows before -> 10,043 walked now = 21.5x
  reduction, measured in production.**
- **Board-build cost 21-54s -> 7-8s.** The `#414` cause is fixed.
- **Not the 130x measured locally, and the same line says why: the shard GREW.**
  ~83k rows/call this afternoon -> ~216k now (2.6x). The index is working
  against a target that got bigger. Quote the 21.5x, not the 130x.
- `unattributed_s=0.00` — the segment accounting is complete, so the split is
  trustworthy.
- **`join_s` is still 7.16 of 7.17s.** The join remains essentially the entire
  cost; it is just 3-7x less of it. **The next lever is the residual ~10k
  rows/call, not the scan that is already gone.** Do not re-optimise the scan.
- Verification for this lane is now MET in production. What remains open is
  only whether 7-8s is acceptable, which is a different question.

### ask-sport-coverage — OPEN — ROUTING WIN LIVE + MEASURED 25->38/52 ZERO REGRESSIONS; K6 FIX IN origin/main BUT UNDEPLOYED (riding along, predicate UNMEASURED); SOCCER/NCAAB/NHL UNPROVEN ON DATA — opened 2026-08-15 — session: ask-sport-coverage
> **K6 DEPLOY STATUS, added 2026-08-15 ~20:3xZ by the coordinating session (no
> claim on this lane).** Your K6 fix `3ba1c2cf` is **NOT LIVE**. It was fired at
> 19:15:54Z and **CANCELLED mid-build at ~19:20** when a peer session started
> `dep-da0bnrflk1mc73fk95ig` — Render cancels an in-flight deploy when a new one
> begins. Re-checked against live `7abd8e12` at 20:22Z **by patch-id: still
> absent.** It is built, tested (137 green, `render.yaml` untouched, 1
> production file) and pushed as **`deploy/ask-k6-2026-08-15` (`3d68dfe4`)**,
> cut from `bebe87c9`. It was never fired because a deploy was in flight on both
> attempts. **So `K6 RETRACTED AS INERT ON PROD` still stands and no as-of
> predicate has been measured** — the retraction is not resolved by this commit
> existing on `origin/main`.
- Goal: the deterministic path names and answers for all eight sports, not
  three. Single testable outcome: `scripts/ask_syndicate_regression.py` moves
  `lookup` (2/8) and `entity` (2/10) above baseline with **no** class
  regressing, measured against the post-M1 **23/52** in
  `reports/ask_regression/post_m1_fixed_2026_08_14.json`.
- Scope, in order (from `plan_2026-08-14_ask_the_syndicate.md` K9/K2/K11/K3/K4/K5/K6):
  - K9 — NFL nickname matching (`_nfl_teams_in_question` needs the full team
    name; `_nfl_matchup_evidence` returns `None` at `len(teams) < 2`). Audit the
    same function per sport.
  - K2/K11 — `soccer` and `ncaab`: no `_SPORT_HINTS` entry, no
    `_fetchers_for_sport` branch (falls to `return []`).
  - K3 — routing collisions: `wnba` its own entry; score `_SPORT_HINTS` matches
    instead of first-match-wins; exact-match the sport filter; emit a reason
    when the filter matches nothing.
  - K4 — dispatch bugs: `nba` -> `_wnba_focused_evidence`; no-sport ranking ->
    MLB-only. **Check first whether M1 already subsumed the second.**
  - K5/K6 — `routed_sport` in the payload; as-of from `freshness.computed_at`.
- Files (exclusive to this lane):
  - `syndicate/blueprints/ask_the_syndicate_router.py`
  - `syndicate/blueprints/ask_the_syndicate_data.py`
  - `syndicate/blueprints/ask_the_syndicate.py`
  - `tests/test_ask_sport_coverage.py`
  - `.claude/hooks/lane-guard.py`
- Collision check RUN via `lane-guard.py`'s own `_claims()`, not by grep: 19
  claims across 4 OPEN lanes at open time, **zero** overlap with the files above.
- NOT claimed, and DELIBERATELY KEPT OUT OF THE `Files` BLOCK ABOVE —
  `_claims()` reads every nested bullet under `- Files:` as a CLAIM, so a
  disclaimer written there becomes a phantom claim. **This lane did exactly that
  and it blocked real work**: `ask-headline-from-board` could not apply a
  one-line fix to `ask_the_syndicate_adapter.py` (a live `Best edge 635.0%`
  regression) because this lane's "NOT claimed" line was being read as a claim
  on it. Corrected 2026-08-15; both entries are now top-level bullets:
  - `syndicate/blueprints/ask_the_syndicate_adapter.py` — held by OPEN lane
    `ask-headline-from-board`.
  - `scripts/ask_syndicate_regression.py` — defines the predicate this lane is
    judged by; editing it would be marking my own exam. (`ask-headline-from-board`
    claims it, which contradicts the brief's "claimed by nobody".)
- Read-only dependency: `pipeline/intelligence_state.py`
  (`read_layer2_shortlist`), claimed by OPEN `memory-cutover-ship`. If a fix
  needs to WRITE there, this lane stops and hands off.
- Hypothesis: n/a for K2/K11/K3/K4/K5/K6 (defects read from code). For K9 the
  measured claim is that entity strictness alone, not missing data, is why NFL
  produces zero evidence.
- Falsification test for K9: after nickname matching resolves
  `"Patriots vs Seahawks projection"` to two teams, `_nfl_matchup_evidence`
  still returns `None` — which would mean the artifact, not the matcher, is the
  cause.
- Verification: `py -3 scripts/ask_syndicate_regression.py --out
  reports/ask_regression/latest.json` re-run and diffed per class against
  23/52. Anything that does not move a class score is NOT done. Production
  re-measure needs a deliberate `/preflight`-gated deploy (`autoDeploy: no`).
- Blocked by: none.
- MARKER CONTENTION, recorded: `.syndicate/.current-lane` is a single global
  token but four sessions are live. It held `ask-headline-from-board` when this
  lane opened. Taken for this lane and the holding session notified; they must
  re-write it before editing the adapter.

### soccer-model-coverage — OPEN — BACKTEST DELIVERED (MODEL LOSES TO MARKET, 1,112 matches, gap +0.0139); 4 FIXES BUILT + TESTED, NONE COMMITTED; #2 DELIBERATELY HELD; CALIBRATION HARNESS NEVER RUN ON REAL DATA — opened 2026-08-15 — session: soccer-model
> **DEPLOY STATUS UPDATE 2026-08-15 22:3xZ (coordinating session, no claim).**
> The **soccer as-of pair IS NOW LIVE** on live-odds-worker (`25774aaf`,
> 22:09:15Z) — `allow_undated` present in 5 places in
> `soccer/features/loaders.py`, verified by content in the deployed tree, with
> `191a001b` an ancestor so nothing was dropped. Both halves shipped together,
> so `50fd7fe2`'s MLS-emptying regression cannot recur. This supersedes the
> earlier note here saying it was built but undeployed.
> **Unchanged:** fixes #1 (seed bootstrap) and #3 (accent join) are still NOT
> committed by this lane, and **#2 (3-way de-vig) remains deliberately HELD** by
> user decision — the model measures worse than the market (Brier 0.5875 vs
> 0.5737, worse in 8 of 9 leagues) and its errors sit on favourites.
> **CROSS-LANE, added 2026-08-15 ~21:5xZ by the coordinating session (no claim).**
> The soccer **as-of pair** (`0b0d44d9` + `f05a21c4`, audit §7 #6) is on
> `origin/main` and is built into `deploy/low-props-soccer-asof-2026-08-15`
> (`25774aaf`) together with the prop `0.5` fix — but **it is NOT deployed**.
> live-odds-worker has been `HOLD` for 26+ minutes (odds refresh + rolling
> soccer builds) so no lull was found. **Take both commits or neither**:
> `50fd7fe2`, the first half, once emptied MLS ratings in production on its own.
> Route one (warm the mirror, then deploy) is armed for that service and is the
> proven technique — see `state.md`.
> **CLAIMS RELEASED 2026-08-15 AT SESSION ARCHIVE — the lane is NOT done.**
> Owning session `soccer-model` is being archived deliberately, so its file
> claims are released rather than left as an orphaned lock. This is the same
> failure mode this lane inherited from `soccer-projection-gap`; releasing on
> the way out is the fix.
> **THE WORK IS UNFINISHED AND LIVES UNCOMMITTED IN THE SHARED WORKTREE** — 9
> files, listed in `log/2026-08-15.md`. Anyone taking these files must read the
> RECONCILIATION and RECIPE CORRECTION blocks below first: `loaders.py` depends
> on the orphaned `soccer-backtest-leakage` as-of work, which `origin/main` does
> not have. **Do not `git checkout` or revert these paths casually** — that
> discards a day of tested work that no branch holds.
> **To resume: `/lane open soccer-model-coverage` and re-take the files.**
> Everything below is measured unless labelled otherwise, but re-verify before
> relying on it.
- Goal: soccer carries a REAL model on the published board. **Testable outcome:**
  `/api/board/layer2-shortlist` reports soccer rows with `model_edge_pct`
  non-null at a rate > 0 (today: `rows_with_model_edge: 0`,
  `unmatched_match_rows: 8,393` against `matches_in_source: 4`), AND a
  leak-free soccer backtest number exists for at least one league.
- **FIRST QUESTION, BEFORE ANY BUILD — the headline number is disputed 250x.**
  Two production endpoints, same sport, same date, 45s apart `[measured
  2026-08-14 19:1xZ by session model-audit]`:
  - `/api/board/layer1?sport=soccer` — rows 8,456, `rows_with_projection` 2,504 = **29.6%**
  - `/api/board/layer2-shortlist` — rows 8,512, `rows_with_projection` **12** = **0.1%**,
    `rows_with_model_edge` 0, `matches_in_source` 4, `unmatched_match_rows` 8,393
  These are two different joins and **at most one describes the board a user
  sees.** Settle which before building. If the defect is the layer2 join rather
  than projection coverage, raising coverage fixes nothing and this lane's
  shape changes.
- Hypothesis (H1): the layer2 ingest's match-key join is broken/starved
  (`matches_in_source: 4` is not a coverage number, it is an empty source), and
  projection COVERAGE at 29.6% is a separate, less urgent fact.
- Hypothesis (H2): `SOCCER_PLAYER_ROWS_MISSING league=eredivisie|primeira_liga|
  championship` `[live-odds-worker logs 19:25Z, observed once, LEAD not finding]`
  means the sim's own input is absent, so the projections that would feed either
  join are not being produced for those leagues.
- Falsification test: for H1 — if `matches_in_source` rises with no change to
  projection coverage and `rows_with_model_edge` stays 0, the join is not the
  binding constraint. For H2 — if a league that DOES project has an equally
  empty `players/` dir, the log line is not diagnostic.
- Verification: production `layer2-shortlist` counters re-read after the change,
  plus a leak-free backtest number computed with per-match as-of ratings and its
  per-family date coverage + intersection printed alongside.
- Blocked by: none. **Coordinate with UI Lane G (soccer card end-to-end) — the
  UI plan's G4 says to run these together.**
- **SCOPE FENCES, measured, do not rediscover:**
  - `player_shots` / `player_shots_on_target` map to a **mean**;
    `soccer_projections` refuses by design to derive a probability from a mean,
    and the rows are 100% one-sided so `_no_vig_over_probability` returns None.
    `player_to_receive_red_card` / `player_assists` are not in the market map.
    **These markets can never carry an edge.** Scope around, not into.
  - **MLS cannot be backtested from its current source at all** —
    `fetch_asa_mls_team_history` returns undated season aggregates; a season
    average already contains the season. Needs a per-match source that does not
    exist here.
  - **Soccer `game` odds are frozen platform-wide** (stop at 2026-08-10T20:54:06,
    all leagues); only `prop` rows are fresh, from a different producer.
  - `data/soccer_source/*/validation/*_backtest_*.csv` are **NOT CITABLE**
    (leakage, retired). Soccer backtest accuracy is **unmeasured** until this
    lane produces a leak-free number.
  - The models lane's uninformative-EV filter keys on
    `fair_method == "book_margin_model"` and **self-heals** — do not try to
    defeat it.
- Files (exclusive to this lane):
  - `syndicate/features/soccer/`
  - `scripts/build_soccer_artifacts.py`
  - `scripts/validate_soccer_vs_market.py`
  - `scripts/backtest_soccer_live_lens.py`
  - `tests/test_soccer_feature_loaders.py`
  - `tests/test_soccer_projections.py`
  - `tests/test_soccer_adapter.py`
  - `tests/test_build_soccer_artifacts.py`
  - `syndicate/features/shared/soccer_projections.py`
  - `scripts/run_live_odds_refresh_worker.py`
  - `tests/test_soccer_three_way_devig.py`
  - `tests/test_soccer_seed_bootstrap.py`

- CLAIM WIDENED 2026-08-15 02:5xZ: `soccer_projections.py` lives under
  `features/shared/`, not `features/soccer/`, and the player-props root cause is
  in the live-odds-worker ENTRYPOINT. Checked against every OPEN lane's parsed
  claims before taking them: neither is claimed. `run_refresh_worker.py` is
  deliberately NOT claimed — the `#435` session is live on that service.

- NOT this lane's files (held by live sessions, read-only here):**
  `syndicate/features/shared/recommendation_engine.py`,
  `syndicate/features/shared/layer2_board.py`,
  `syndicate/features/shared/layer1_board.py`,
  `syndicate/features/shared/opportunity_signals.py`,
  `pipeline/intelligence_state.py`, soccer card templates and `board_cards` CSS.

### live-game-line-projection — OPEN — DROP 1 DEPLOYED **TO THE WRONG SERVICE** (web, where it is INERT); DROP 2 BUILT (`4bd7dbb3`) AND ON NO SERVICE; DROP 3 UNBUILT — opened 2026-08-15 — session: live-game-line-projection
> **STATUS LINE CORRECTED 2026-08-15 ~18:0xZ by the coordinating session.** It
> read "NOT DEPLOYED" and that is no longer true: `0e0b0aa1` rode the web train
> and is in the deployed tree (`dep-da0a5rlg1s2s73cm43kg`, live 17:40:30Z).
> **This does NOT discharge the lane's measurement obligation.** By this lane's
> own commit message the change publishes nothing on its own — the visible
> effect needs Drop 2 — so "deployed" here means *present*, not *proven*. No
> production predicate was declared for it and none was measured. Do not read
> the deploy as evidence the lens now serves a live win probability.
- Goal: MLB game lines carry a projection computed from the CURRENT game state
  rather than the pregame sim. **Testable outcome:** on a live MLB slate, a
  published artifact carries a live win probability per live game whose value
  MOVES between two consecutive builds while the pregame `predictions.full`
  for the same game does not — and `rows_live_edged` on the book-grid counters
  is > 0 for game-line markets.
- **THE PREMISE IS FALSE AND THAT IS THIS LANE'S CENTRAL FINDING.** "No live
  game-line projection exists" is a statement about PUBLICATION, not about
  computation. `estimate_live(LiveSituation(...))` runs in production today,
  120 sims per live game, on every live-lens tick, and returns `homeWinProb`,
  `awayWinProb`, projected `total` and `homeMargin` from the live inning /
  outs / bases / score / batter / pitcher state. Evidence in
  `.syndicate/spec_live_game_line_projection.md` §1.
- Files (exclusive to this lane):
  - `.syndicate/spec_live_game_line_projection.md` (new — the deliverable of
    this phase)
  - `syndicate/features/mlb/live_lens.py` — the merge site at 1090-1100 that
    discards the live-MC game lens for exactly the live games.
- Hypothesis (H1): the live MC's `gameLens` is dropped by
  `_enhance_card_row_with_live_projection`'s `should_use_projection_lens`
  because the card's own pregame-derived lens already satisfies
  `_lens_rows_have_projection_signal`, so the branch is False on precisely the
  live games it was written to serve.
- Hypothesis (H2): a second, independent drop — the report that is PUBLISHED
  is the slim HTTP-fetched shape from `scripts/refresh_mlb_oddsapi.py`, which
  carries no `gameLens` at all. Fixing H1 alone therefore changes nothing that
  crosses to web.
- Falsification test: for H1 — a live game whose card row carries NO gameLens
  still shows no `source: live_mc` row after the merge, which would mean the
  MC payload never reached the merge. For H2 — a published report that already
  carries `gameLens` rows, which would mean the slim path is not the binding
  drop.
- Verification: (1) the spec is reviewed and its scope agreed BEFORE any engine
  work — this phase produces no source edit; (2) any later code change is
  measured on the published artifact, never through web's `/mlb/api/live-lens`,
  which recomputes a cards fallback locally and is structurally blind to the MC
  (`cardsFallback: True`, `simContextAvailable: False` on 14/14 games, measured).
- Blocked by: none. **NO DEPLOY FROM THIS LANE.** refresh-worker is under
  `#435` and had a deploy in flight (`eea7554a`) at lane-open.

#### soccer-model-coverage — COMMIT HYGIENE + FINAL TEST NUMBERS 2026-08-15

**DO NOT COMMIT `loaders.py` AGAINST `origin/main`. The as-of work it builds on
is UNMERGED, and a naive commit would sweep in another lane's branch work.**
`[measured]` `git show origin/main:.../loaders.py | grep -c as_of` returns **0** —
`compute_team_ratings` on `origin/main` has no `as_of` parameter at all. The
whole `soccer-backtest-leakage` machinery lives only on branch
`fix/soccer-backtest-leakage` (tip `2dcca4fe`) and in this shared worktree.
`git merge-base --is-ancestor fix/soccer-backtest-leakage origin/main` -> **NO**.

    vs origin/main                    loaders.py  153 insertions  (THEIRS + MINE, mixed)
    vs fix/soccer-backtest-leakage    loaders.py   73 insertions / 3 deletions  (MINE only)

`validate_soccer_vs_market.py`, `backtest_soccer_live_lens.py` and
`build_soccer_artifacts.py` show **zero** diff against that branch — the
worktree already matches it, which is why they read as "modified" against a
local `main` that is 129 commits behind `origin/main`.
`soccer_projections.py` (+120) and `run_live_odds_refresh_worker.py` (+30) ARE
purely mine — those files are identical at `HEAD` and `origin/main`.

**RECIPE: branch from `fix/soccer-backtest-leakage`, not from `main`.** Stack,
do not merge — the same rule `learnings.md` records for pinned deploys. Commit
through an isolated `GIT_INDEX_FILE` with an explicit pathspec, never
`git add -A`, and read `git diff --cached --stat` before committing: the shared
index has held another session's 4,993 staged deletions before.

**Exactly 7 files, no strays** `[git status, scoped]`:

    M  scripts/run_live_odds_refresh_worker.py
    M  syndicate/features/shared/soccer_projections.py
    M  syndicate/features/soccer/features/loaders.py
    ?? scripts/backtest_soccer_h2h_calibration.py
    ?? syndicate/features/soccer/seed_bootstrap.py
    ?? tests/test_soccer_history_date_parsing.py
    ?? tests/test_soccer_seed_bootstrap.py

**FINAL TEST STATE:** full `-k soccer` after all four changes —
**571 passed, 0 failed** (1273s), against a 553/0 baseline taken before the
loaders change; the delta is the 18 new soccer-matching tests. Blast-radius set
378/0. Every new test mutation-verified red.

**NOTHING COMMITTED, NOTHING PUSHED, NOTHING DEPLOYED.** Fix 1 is inert until a
live-odds-worker deploy. Fix 2 should NOT ship without the calibration number —
see the dispersion finding above.

#### live-game-line-projection — STATUS 2026-08-15 03:5xZ — SPEC PHASE COMPLETE, NO CODE WRITTEN
- **Deliverable:** `.syndicate/spec_live_game_line_projection.md` (`9067b606`).
- **H1 (the merge at :1094 rejects the MC lens) — EFFECT CONFIRMED, MECHANISM
  NOT YET DISCRIMINATED.** The served snapshot carries 3 card-derived lanes,
  `source: None`, 0 `modelHomeWinProb`, against `_build_game_lens`'s 6 sourced
  lanes. Whether the merge rejected it or the payload never arrived is spec §6.1
  and is the FIRST build step — recorded as unproven rather than banked.
- **H2 (the published report is the slim shape with no `gameLens` field) —
  CONFIRMED** from the deployed `ccd10349:scripts/refresh_mlb_oddsapi.py:764` and
  the published artifact's own zeroed `perf` + `gameLens rows 0`.
- **The MC runs:** 9 `LIVE_MC_BAIL` per tick × 11 ticks, all `status_not_live`,
  against 9 Final / 5 Live. One uninstrumented exit named in the spec.
- **Sequencing correction, re-derived here:** `0.1` is not a prerequisite for the
  live product; the 1800s cooldown is bypassed whenever any game is live.
- **`rows_live_edged` is a PROP counter and this lane does not move it** — the
  lane's own success metric is a new `rows_live_gameline_*` family. The brief's
  framing invites that conflation; recorded so it is not made.
- **Awaiting a product answer on spec §8.1** (120 sims → ±4.56 pp SE; publish
  refusing to price / raise the sim count / never price). Recommendation: publish
  refusing to price, zero added compute.
- No deploy. refresh-worker was `update_in_progress` (`eea7554a`) at lane-open.

#### soccer-model-coverage — RECIPE CORRECTION 2026-08-15. MY OWN PREVIOUS NOTE WAS WRONG.

**"Branch from `fix/soccer-backtest-leakage`" IS WRONG AND WOULD BE A MASSIVE
ROLLBACK.** `git diff --stat origin/main fix/soccer-backtest-leakage` =
**127 files, 3,618 insertions, 33,673 DELETIONS** — the branch predates a full
day of many sessions' work (clv_join, layer2 uninformative-EV, the UI lanes,
the whole `.syndicate` ledger). It is also 114 lines BEHIND `origin/main` on
`scripts/run_live_odds_refresh_worker.py`, the very file I edited. This is the
same shape as `state.md`'s "a branch cut for web is a ROLLBACK for
refresh-worker" — I reproduced the mistake one note after quoting the rule.

**THE ACTUAL SITUATION.** The `soccer-backtest-leakage` as-of change is
UNCOMMITTED IN THE SHARED WORKTREE (its session is archived; `origin/main` has
`as_of` count **0**). It spans `loaders.py`, `build_soccer_artifacts.py`,
`validate_soccer_vs_market.py`, `backtest_soccer_live_lens.py` and
`tests/test_soccer_team_ratings_as_of.py`. **My date fix sits on top of it and
is meaningless without it** — `_as_iso_day` repairs a comparison that only
exists in that change.

**SO THE COMMIT NEEDS A DECISION, NOT A RECIPE — flagging rather than
guessing.** Branch from `origin/main`, then either:
 (a) two commits — land the orphaned as-of work first (it is CLOSED-VERIFIED
     and was always meant to land), then mine on top, preserving attribution; or
 (b) one commit that states plainly it carries both.
Either way the `compute_team_ratings` signature change forces its callers to
come along, so the 5 as-of files cannot be left behind.
**Do NOT cherry-pick my `loaders.py` alone onto `origin/main`** — it would call
`compute_team_ratings(as_of=...)` against a signature that has no such
parameter.

#### live-game-line-projection — H1 CONFIRMED 2026-08-15 04:0xZ, and the open discriminator is now MOOT
- **Method:** imported the codebase's own `_lens_rows_have_projection_signal`
  and evaluated `should_use_projection_lens`'s three disjuncts over the served
  production payload, per live game. Not a code reading — the real function over
  real data.
- **Result: `False` on 5 of 5 live games.** `card_game_lens` non-empty (4 rows),
  game is live, and the card's text-derived lens HAS signal — e.g. game 824159
  `first1 projection={'homeMargin': 0.57, 'total': 1.31}`.
- **This moots the discriminator the spec listed as build step §6.1.** The third
  disjunct was the only one that could rescue the MC lens, and it is False
  *because the card lens has signal*, independent of what the MC produced. So
  **even if the MC payload arrives with a full lens, it is discarded.** Whether
  it arrives no longer changes the outcome — only the fix's shape.
- Residual caveat, stated: the card lens was read from web's served payload as a
  proxy for the worker's. Same producer (`_live_lens_segments_from_card`) both
  places, and the values are visibly pregame interpolations, but it is a proxy.
- **USER DECISION on spec §8.1 (2026-08-15): PUBLISH, REFUSE TO PRICE.** Ship at
  120 sims carrying `probStdErr` and a `priceable` gate; do not raise the sim
  count now. Zero added compute; leaves the raise available once §6.2 measures
  what a sim costs on live-odds-worker (84–89% of 2 GB).

#### soccer-model-coverage — THE OWED NUMBER, DELIVERED 2026-08-15. THE MODEL LOSES TO THE MARKET.

**First leak-free soccer backtest number this repo has ever had.**
`scripts/backtest_soccer_h2h_calibration.py`, **1,112 matches / 9 leagues**,
ratings recomputed per match day with `as_of` set to that day — only
meaningful because `_as_iso_day` repaired the inert filter first.

    MODEL  multiclass Brier  0.5875
    MARKET multiclass Brier  0.5737   (proportionally de-vigged closing odds, same matches)
    gap                     +0.0139   lower is better -> THE MODEL LOSES

    league               n   model   market     gap   m_stdev  mkt_stdev
    eredivisie         126  0.5211   0.5064  +0.0147   0.1886   0.2257
    primeira_liga      125  0.5722   0.5405  +0.0317   0.1596   0.2088
    championship       126  0.6158   0.6061  +0.0097   0.1237   0.1540
    belgian_pro_league 120  0.6045   0.6056  -0.0011   0.1484   0.1696
    epl                120  0.5794   0.5572  +0.0222   0.1617   0.2021
    la_liga            123  0.5947   0.5846  +0.0101   0.1518   0.1545
    bundesliga         126  0.5840   0.5653  +0.0187   0.1898   0.1861
    serie_a            120  0.5970   0.5869  +0.0101   0.1574   0.1724
    ligue_1            126  0.6201   0.6117  +0.0084   0.1367   0.1566

**Worse in 8 of 9 leagues; two-sided sign test p = 0.039.** The lone exception
(belgian_pro_league, -0.0011) is noise at n=120 and must not be reported as a
win.

**THE UNDER-DISPERSION DIAGNOSIS IS CONFIRMED BY AN INDEPENDENT ROUTE.** Mean
model stdev(P home) **0.1575** vs market **0.1811**, narrower in **8 of 9**
leagues. eredivisie's reliability curve shows the model too TIMID at both
ends: predicted 0.144 -> actual 0.000; predicted 0.823 -> actual 1.000. The
production-artifact stdev (0.1364 over 166 rows) and this backtest stdev
(0.1575 over 1,112) agree on the shape.

**THE DECISION THIS FORCES.** Soccer's model must NOT publish `model_edge_pct`
yet. A model that loses to the closing line over 1,112 matches emits edges that
are noise against a better-informed price — and its errors are systematically
on the favourites, so those edges point at underdogs. **Fix #2 removes a stale
BLOCK; it does not make the number publishable.** Ship #1 (seeds), #3 (accent
join) and #4 (as-of) freely — they are correctness fixes with no such hazard.

**Coverage, per the `data/**` rule:** eredivisie 918 history rows spanning
2023-08-11..2026-05-17; with result 918; with complete closing odds 918;
**intersection 918**. This does not rest on a narrow join. Matches are skipped
where either side has <20 prior as-of matches (eredivisie: 180 skipped, 126
scored at `--limit 120`), so early-season rows are not scored as though the
model had an opinion.

**Named, cheap levers, neither done:** sharpen the distribution, and raise
`adapters._DEFAULT_SIMULATIONS` from 300 (±2.9pp of pure Monte Carlo noise).
`SoccerSimulationOutput.evaluation.calibration.win_probability.brier` is still
`None` — the harness exists but is not wired into the sim's own slot.
Full result: `reports/soccer_backtest/h2h_calibration_2026-08-15.json`.


## Archived lanes (full bodies in `lanes_closed.md`)

> Moved 2026-08-15 to bring this file back under the digest budget.
> Nothing was deleted. Each line points at a full body — including the
> file/line maps and the ORPHANED lanes' resume notes.

- `mlb-prop-oos-calibration` — mlb-prop-oos-calibration — CLOSED-VERIFIED 2026-08-15 — D4 CLOSED: the split ran on production, `batter_hits` is the one verdict that did NOT survive  → `lanes_closed.md`.
- `probability-clamp-removal` — probability-clamp-removal — CLOSED-VERIFIED 2026-08-15 — WNBA site fixed, scored 5/5, shipped as `de0c367f`; the other TWO sites are held by other OPE → `lanes_closed.md`.
- `probability-differential-test` — probability-differential-test — CLOSED-VERIFIED 2026-08-15 — harness + table + owners shipped as `d448a100`; ONE live misprice CONFIRMED in production → `lanes_closed.md`.
- `soccer-backtest-leakage` — soccer-backtest-leakage — CLOSED-VERIFIED 2026-08-14 — **ARCHIVED to `lanes_closed.md`**. Audit §7 #6. HEAD `2dcca4fe`; `50fd7fe2` ALONE IS UNSAFE TO  → `lanes_closed.md`.
- `ask-headline-from-board` — ask-headline-from-board — CLOSED-VERIFIED 2026-08-15 — web `c774fe1a` live 03:29:56Z; B01 delta 0.000 and refusal 4/8 matching its control, both measu → `lanes_closed.md`.
- `recommendation-lane-correctness` — recommendation-lane-correctness — CLOSED-VERIFIED 2026-08-14 — 4 shipped+measured; A3a (`28291eb6`) HELD BACK BY CHOICE, not by doubt — opened 2026-08 → `lanes_closed.md`.
- `soccer-odds-coverage` — soccer-odds-coverage — ORPHANED-CLAIMS-RELEASED 2026-08-15 — claims on `refresh_odds_sources.py` released; the per-league cadence is NOT fixed — opene → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-projection-gap` — soccer-projection-gap — ORPHANED-CLAIMS-RELEASED 2026-08-15 — it claimed NO files; the 30% projection coverage is unchanged — opened 2026-08-14 — sess → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `wnba-skill-backtest` — wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `odds-capture-stall` — odds-capture-stall — CLOSED 2026-08-14 — NOT A DEFECT: the 2h gap IS the configured pregame cadence → `lanes_closed.md`.
- `board-ui-freshness-slip-books` — board-ui-freshness-slip-books — CLOSED 2026-08-14 — all three shipped and verified → `lanes_closed.md`.
- `build-time-estimate` — build-time-estimate — CLOSED 2026-08-14 — board build timed at ~2-4 min on current code; estimator can no longer collapse to ~0 — opened 2026-08-14 —  → `lanes_closed.md`.
- `layer2-board-freshness` — layer2-board-freshness — CLOSED-VERIFIED 2026-08-14 (memory follow-on lives on branch `memory/overview-sum-to-max`, undeployed) — 3h clean window, all → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-skill-declaration` — projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED 2026-08-14 — opened 2026-08-14 — session: nfl-day-of-game → `lanes_closed.md`.
- `projection-degeneracy-detector` — projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `anon-allocation-site` — anon-allocation-site — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the lane's OWN FINDINGS ARE NOT CLOSED — opened → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-degenerate-writer` — nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `refresh-worker-anon-leak` — refresh-worker-anon-leak — ORPHANED-REASSIGNED 2026-08-15 — file claims released to `memory-watchdog-435`; the leak itself IS STILL UNEXPLAINED — open → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED 2026-08-13 — opened 2026-08-13 — session: nfl-day-of-game → `lanes_closed.md`.
- `nfl-day-of-game` — nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map → `lanes_closed.md`.
- `quote-join-enrich-cost` — quote-join-enrich-cost — CLOSED 2026-08-14 — all three verification criteria MET → `lanes_closed.md`.
- `checkpoint-witness` — checkpoint-witness — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `checkpoint-guard-scope` — checkpoint-guard-scope — CLOSED-VOID 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `memory-guard-reclaimable` — memory-guard-reclaimable — CLOSED 2026-08-13 — fix VERIFIED, and it uncovered a leak → `lanes_closed.md`.
- `mlb-props-regen` — mlb-props-regen — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `live_refresh_loop.py` released; the props-regen fixes are NOT confirmed shipped — opened 2026 → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `hooks-enforcement-test` — hooks-enforcement-test — CLOSED 2026-08-13 — opened 2026-08-13 — session: hooks-test → `lanes_closed.md`.
- `intelligence-state-red-baseline` — intelligence-state-red-baseline — CLOSED 2026-08-13 — opened 2026-08-13 — session: intel-state-baseline → `lanes_closed.md`.
- `board-transport` — board-transport — CLOSED 2026-08-13 (work measured 08-10/11) → `lanes_closed.md`.
- `sim-execution-observability` — sim-execution-observability — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `soccer-sim-grouping` — soccer-sim-grouping — CLOSED 2026-08-10 — shipped and verified, one thread handed on → `lanes_closed.md`.
- `layer1-live-tier` — layer1-live-tier — CLOSED-PENDING-MEASUREMENT 2026-08-13 → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED 2026-08-13 — verified in production → `lanes_closed.md`.
- `internal-hostname-cutover` — internal-hostname-cutover — CLOSED — opened 2026-08-13 — session: <name> → `lanes_closed.md`.
- `ask-refusal-gate` — ask-refusal-gate — CLOSED-VERIFIED 2026-08-14 — refusal 3/8 -> 6/8 in production, zero regressions — opened 2026-08-14 — session: ask-audit → `lanes_closed.md`.
- `ask-board-candidates` — ask-board-candidates — ORPHANED-CLAIMS-RELEASED 2026-08-15 — `ask_the_syndicate_data.py` released; M1 SHIPPED but a REVERT OF IT IS STAGED IN GIT — op → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `board-ui-visible-defects` — board-ui-visible-defects — CLOSED-VERIFIED 2026-08-14 — deployed as web `aadcde77`, every criterion measured in production — opened 2026-08-14 — sessi → `lanes_closed.md`.
- `memory-cutover-ship` — memory-cutover-ship — CLOSED-VERIFIED 2026-08-15 — `#387` shipped in TWO halves (`cfee9c6e` + `705eeefc`), sports=8 restored, peak 34.3% of ceiling —  → `lanes_closed.md`.
- `board-contract-absent-not-neutral` — board-contract-absent-not-neutral — ORPHANED-CLAIMS-RELEASED 2026-08-15 — 6 claims released incl. `game_board_contract.py`; partial work IS committed  → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `mlb-oom-outlier-2003z` — mlb-oom-outlier-2003z — CLOSED 2026-08-15 — QUESTION WAS MALFORMED: no outlier, 16 kills that day; H1 falsified — opened 2026-08-15 — session: memory- → `lanes_closed.md`.
- `mlb-hydration-oom-435` — mlb-hydration-oom-435 — CLOSED 2026-08-15 — `build_cards_page_context` is 2 of 6 kills, NOT the common factor — opened 2026-08-15 — session: memory-cu → `lanes_closed.md`.
- `memory-watchdog-435` — memory-watchdog-435 — CLOSED-VERIFIED 2026-08-15 — watchdog + 3 censuses live; ROOT CAUSE FOUND: append-only quote shard, 92.4% superseded, 6.3x read  → `lanes_closed.md`.
- `odds-props-fabricated-probability` — odds-props-fabricated-probability — ORPHANED-CLAIMS-RELEASED 2026-08-15 — the two prop-refresh scripts released; work committed, artifact effect UNMEA → `lanes_closed.md`.  **ORPHANED — resume notes + file claims in the archive.**
- `soccer-card-end-to-end` — soccer-card-end-to-end — CLOSED-VERIFIED 2026-08-15 — deployed as web `7e334509`, every criterion measured in production — opened 2026-08-15 — session → `lanes_closed.md`.
- `model-audit-devig-and-hygiene` — model-audit-devig-and-hygiene — CLOSED-VERIFIED 2026-08-15 — #5 falsified then collapsed for real + D5 done (`2ac3c6bc`, committed, NOT deployed, cons → `lanes_closed.md`.

### clamp-fix-to-workers — OPEN — **BRANCH READY AND PUSHED (`c70eeff0`, cut on live `191d098f`), DEPLOY BLOCKED ON ANOTHER SESSION'S CLAIM. live-odds-worker needs nothing — its in-flight target `49797f4b` already carries the fix** — opened 2026-08-15 — session: clamp-fix-verification-watch
- Goal: the ±4900 clamp stops being published. **Testable outcome:**
  `py -3 scripts/watch_clamp_trigger.py --once` returns `POST_FIX_OK` on a slate
  that carries an out-of-clamp probability.
- **WHY THIS LANE EXISTS — the web deploy was falsified.** `e831263e` shipped the
  fix to web on 2026-08-15 and production kept mispricing. Measured 23:10:13Z
  (nfl `h2h_3_way` 0.014698 → +4900, correct +6704) and 23:15:46Z (mlb `spreads`
  0.009911/0.990089 → ±4900, correct ±9990) — two triggers, two unrelated slates,
  both `PRE_FIX_MISPRICE` against a fix-carrying web SHA.
  `reports/clamp_watch/trigger_20260815T2310*.json`, `..._231546*.json`.
- **The runbook's "WEB SERVICE ONLY" was wrong, and the reason is instructive.**
  It inferred serve-time stamping from "0 of 108 shortlist-artifact rows carry
  `fair_price`" — true, and about the WRONG ARTIFACT. The shortlist has no
  `fair_price` at all; the intelligence-state card does. Web's block is a
  **backfill** (`if ... card.get("fair_price") is None`), so an upstream-clamped
  value passes through untouched and the web fix is structurally inert.
- Files: `pipeline/intelligence_state.py`, `syndicate/features/wnba/cards.py`.
  - **`syndicate/features/shared/layer2_board.py` DELIBERATELY NOT TOUCHED** — it
    is claimed by OPEN `spread-line-sign-convention`, and that lane's worker
    deploy already carried the layer2_board fix to both workers. Collision found,
    then dissolved by re-measuring rather than by negotiating. 3 sites → 2.
  - Collision check on the two: `clv-without-settlement` claims no files;
    `ask-sport-coverage` lists `intelligence_state.py` read-only;
    `soccer-model-coverage` lists both as "NOT this lane's files". CLEAR.
- Hypothesis: n/a — the producer is established by content, not guessed.
- Falsification test: if refresh-worker deploys with 0 clamp sites and a
  subsequent trigger still reads `PRE_FIX_MISPRICE`, the producer is NOT the
  intelligence-state loop and this attribution is wrong.
- Verification: `watch_clamp_trigger.py --once` → `POST_FIX_OK`, plus 0 clamp
  sites by content at the new live refresh-worker SHA.
- **Blocked by: the refresh-worker deploy claim**, held by `red-intelligence-tests`
  (target `037eb356`, since 23:35:01Z), which still carries both sites.
  `send_message` is unavailable from this scheduled-task session, so the claim
  was NOT taken and no coordination message could be sent. Waiting for release.

#### smaps-anon-breakdown — CLOSED 2026-08-15 23:5xZ
**HYPOTHESIS CONFIRMED.** pid 39 anon is **91% mmap** (1,007.2 of 1,106.9MB)
against only **95.9MB of brk `[heap]`**. Falsification was "if `[heap]` dominates,
`mallinfo2`'s `arena` is the follow-up rather than `hblkhd`" — it does not.

**AND THE LANE'S PREMISE WAS RETRACTED BY ITS OWN INSTRUMENT.** The "673MB
outside pymalloc" this lane was opened to chase was cgroup `anon` (1,607MB,
CONTAINER) minus pymalloc arenas (934MB, pid 39 ONLY). Different scopes. The
smaps reader's reconciliation check refused its first production read
(`reconciles: false`, 27.0%) and that refusal was the finding. Per-process the
residue is **~173MB**; ~410MB was always just the 8-10 child processes.

**CONSEQUENCE: `mallinfo2` IS NOT THE NEXT STEP.** I recommended it two hours
ago. The question it was for has largely dissolved, and with pymalloc holding
~934MB of arenas the mmap total is very nearly pymalloc itself — a duller answer
than a mystery, and the right one.

**SHIPPED:** `b0ab37a1` (reader) live 22:41:04Z, minimal — live sha + 1 commit,
not converged main, which would have moved production 330 commits for an
instrument.
**NOT SHIPPED:** `c7747a29` (reconcile against the process, not the container).
Three sessions held the deploy claim in 70 min and the live sha moved twice under
a rebase, so it is filed as a request rather than raced for —
`.syndicate/deploy/requests/2026-08-15T2350Z-smaps-reconciliation.md`.
Until it lands the reader reports `reconciles: false` on every read. Cosmetic;
the breakdown itself is correct.
- [(superseded lane detail](lanes_closed.md) — (superseded lane detail — the original body this lane was opened with)
- [quote-join-enrich-cost (detail below, kept for the file/line map)](lanes_closed.md) — quote-join-enrich-cost (detail below, kept for the file/line map) — session: memory-guard
- [memory-guard-reclaimable (detail below, kept for the file/line map)](lanes_closed.md) — memory-guard-reclaimable (detail below, kept for the file/line map) — session: memory-guard
- [render-yaml-web-block-hygiene](lanes_closed.md) — render-yaml-web-block-hygiene — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- [(superseded lane detail, kept for the file/line map)](lanes_closed.md) — (superseded lane detail, kept for the file/line map)
- [hooks-enforcement-wiring](lanes_closed.md) — hooks-enforcement-wiring — DONE 2026-08-13 — **NO LANE WAS EVER OPENED**
- [red-intelligence-tests](lanes_closed.md) — red-intelligence-tests — CLOSED-VERIFIED 2026-08-15 — all three reds fixed, 218/0, shipped `1322d0a8`/`d348e040`/`4ae71c4a`, pushed `89c3d94
- [mlb-live-pitcher-projection](lanes_closed.md) — mlb-live-pitcher-projection — CLOSED-VERIFIED 2026-08-16 — (a)/(b)/(c) all measured on 423 rows, 0 violations; live coverage 11.6% -> 50.3%;
- [board-publish-stall](lanes_closed.md) — board-publish-stall — CLOSED-FALSIFIED 2026-08-16 — no stall, no publish failure; the REAL result is that my deployed fix is INERT and resta
- [line-decimal-renderer](lanes_closed.md) — line-decimal-renderer — CLOSED-VERIFIED 2026-08-16 — shipped `f3b9b293`; 5 live rows change, 77 untouched; WEB DEPLOY OWED — opened 2026-08-
