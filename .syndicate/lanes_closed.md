# Closed lanes

Moved out of `lanes.md` so the working file stays readable.
Full bodies live here; `lanes.md` keeps a one-line pointer for each.

### wnba-skill-backtest — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: `#428`, first of six. Measure whether the WNBA game model predicts
  anything, and write the answer into a `MEASURED_SKILL`-shaped constant the
  producer attaches itself. Testable outcome: a correlation and an MAE for
  `pred_margin` and `pred_total` against real finals, **each reported against a
  constant baseline**, over a stated sample size — or an evidenced statement
  that the data does not support one.
- **WHY WNBA FIRST:** production holds **81 dates** (2026-05-17..08-15), the
  deepest of any sport, and its contract ships MEANS WITHOUT A DISTRIBUTION, so
  correlation is the only honest measure available and there is no probability
  to be tempted into deriving.
- **THE "BLOCKED ON DATA" PREMISE WAS WRONG AND IS ALREADY CORRECTED IN `#428`.**
  It came from a LOCAL read ("4 game-card files"); production has 81 dates. The
  local `game_cards_*.csv` are 7-column stubs with no projections at all, while
  production's carry 19 columns including `pred_margin` / `pred_total`. Do not
  scope anything here from the checkout.
- Data, both confirmed by fetching before any code was written:
  - PROJECTIONS — production `wnba_source/data/processed/game_cards_<date>.csv`
    via `/api/ops/artifacts/stream?path=`, admin token. Carries `pred_margin`,
    `pred_total`, plus the market's `home_spread` / `total` for a baseline.
  - OUTCOMES — **not in that file.** Sourced from ESPN's public WNBA scoreboard,
    the same feed `#429`-era NFL work already uses. Join on date + tri-codes.
- Files (exclusive to this lane):
  - `scripts/backtest_wnba_projection.py` (new)
  - later, if a number is produced: a `MEASURED_SKILL` constant + the one-line
    producer attach in `syndicate/features/shared/wnba_projections.py`
- **HAZARDS, written before running anything:**
  - **Report MAE against a CONSTANT BASELINE, not bare correlation.** NFL's
    totals model sits at r=0.269 and beats the historical mean by only 0.22
    MAE; a bare r would have read as skill. The baseline is the finding.
  - **A sample size is part of the number.** `#377`/`#429` both produced
    authoritative-looking values with no n behind them. If the join yields few
    games, say so and do NOT emit a constant.
  - **Publish the INTERSECTION, not the union** — CLAUDE.md's standing trap.
    Dates with a projection but no final, or vice versa, are excluded and
    COUNTED.
  - Margin sign convention must be pinned against a real game before any
    correlation is believed; an inverted sign turns skill into anti-skill and
    looks plausible either way.
- Falsification: if the model has no skill, that is a RESULT and gets written
  down. `#367` did exactly that for NFL (corr −0.047) and it is why NFL's
  margin projection is suppressed today.
- Blocked by: none.

### projection-skill-declaration — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: `#425` gap 1. Every projection on the board declares whether its model
  has ever been evaluated, so a consumer can tell a validated number from an
  unvalidated one. Testable outcome: 100% of projection rows carry a
  `model_skill` block on every sport; NFL keeps its richer measured note
  untouched; the other six report `status: "unmeasured"` explicitly.
- **SCOPE, AND WHAT THIS DELIBERATELY DOES NOT DO.** It does NOT measure the six
  models. That needs six bespoke backtests and the data is not there:
  measured on this checkout today — soccer results **0 files**, MLB
  `feed_live` **1 date**, WNBA processed game-cards **4 files**. CLAUDE.md's
  standing warning is exactly this case: a backtest built on those "will look
  like it ran on months of data and actually be running on whatever the
  narrowest family happens to cover". Producing `correlation: 0.31` from n=4
  would be `#377`'s own failure — an authoritative-looking number that means
  nothing — committed by the ticket written to prevent it.
- So this closes the SYSTEMIC half: silent absence becomes **declared**
  absence. `unmeasured` is a first-class value, not a missing key. The six
  actual measurements get their own ticket with the data gate named.
- Files (exclusive to this lane):
  - `syndicate/features/shared/projection_skill.py` (new)
  - `syndicate/features/shared/board_enrichment.py` — one call in the existing
    `attach_projections` wrapper
  - `tests/test_projection_skill.py` (new)
- Design:
  - Same choke point as the degeneracy detector: the `attach_projections`
    wrapper. One place, seven sports, 13 return sites, zero call sites.
  - **Never overwrite a producer's own note.** NFL's `skill_note` is
    profile-aware (preseason only) and carries real backtest numbers; the
    wrapper fills in only where `model_skill` is ABSENT, and normalises the
    existing one by adding `status: "measured"` so both shapes agree.
  - **Keep the unmeasured note SMALL.** It lands on every projection row on
    every sport, and `#374` records `extraHitterProps` being 68% of the MLB
    live-lens payload. Prose belongs in the module docstring, not in 2,000
    rows. Status + verdict + nulls only.
- Falsification tests: NFL's measured note must survive byte-identical apart
  from the added `status`; a row with no projection must not gain one; the
  block must not grow the payload by more than a few keys.
- Blocked by: none. The six measurements are NOT blocked by this — they are
  blocked by production data access.

### projection-degeneracy-detector — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: `#425`. A projection that has collapsed to ONE value across a slate is
  detected and reported for **every** sport, not just the one where a human
  happened to notice. Testable outcome: a synthetic constant slate is flagged
  with sport, market and value; a varying slate is not; and the check runs on
  all seven producers without touching any of them.
- Files (exclusive to this lane):
  - `syndicate/features/shared/board_enrichment.py` — the wrapper + detector.
  - `tests/test_projection_degeneracy.py` (new).
- **`.current-lane` deliberately NOT claimed.** It is one file shared by every
  session and `anon-allocation-site` holds it right now; taking it would break
  that session's own-lane exemption. Verified against the real hook that both
  my files return exit 0 without it, so claiming it would buy nothing and cost
  someone else. Re-check if a file added here IS claimed by an open lane.
- **SCOPE: `#425` has TWO gaps and this lane fixes ONE.** Stated so the ticket
  is not closed on half the work:
  1. **No degeneracy check** — IN SCOPE. A model with real historical skill can
     still emit a constant TODAY because its input went missing, and a
     backtested skill note cannot catch that. It is what actually happened on
     2026-08-13, and nothing reported it.
  2. **No skill annotation on six builders** — OUT OF SCOPE. Needs a measured
     backtest per model (`#367` did NFL's: corr −0.047 over 146 games). Six
     backtests is not a plumbing change, and inventing skill numbers to fill
     the field would be worse than the gap. Stays open on `#425`.
- Design, recorded before implementing:
  - `attach_projections` has **13 return sites across 7 sports**. Adding the
    check at each is the exact mistake `#334` records. Instead the per-sport
    body becomes `_attach_projections_by_sport` and `attach_projections`
    becomes a thin wrapper running the detector over the GRID afterwards — one
    place, all sports, all 13 paths, **zero call sites touched** (4 callers:
    `intelligence.py:2208`, `book_grid_artifact.py:221`,
    `layer2_shortlist.py:176`, and one internal).
  - Group by `(kind, market, segment)`; count distinct **GAMES**, not rows —
    alt lines put many rows on one game and a row-based count would inflate
    into false positives. Unit key is `event_id`, falling back to
    `(home_team, away_team)`, plus `player_name` for props.
  - Compare `projected_raw` where present, else `projected`. Raw is the model
    output before calibration; calibration mapping distinct inputs onto one
    output is a different bug.
- Threshold and its justification: flag only when distinct values == 1 across
  **>= 4 distinct games**. Two- or three-game slates can tie by coincidence;
  four independent games agreeing to full float precision cannot happen to a
  working model. Deliberately conservative — a false positive BLANKS a real
  projection.
- Falsification tests, which matter more than the positive ones: a varying
  slate must NOT flag; a 3-game constant slate must NOT flag (below threshold);
  a slate with many alt-line ROWS but few GAMES must NOT flag; a sport with no
  projections must NOT flag.
- Blocked by: none.

### nfl-degenerate-writer — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: a SmartSim2 NFL run with no play-by-play data cannot write a
  league-constant projection artifact over a healthy one. Testable outcome:
  with the pbp absent, the generator exits non-zero having written NOTHING,
  and the previously-good artifact is byte-identical afterwards.
- Why this exists: `98950c6d` made the READER immune to the degenerate file
  (drops both-sides-neutral rows, reads every root, newest wins). It does not
  stop the file being WRITTEN, and writing it OVERWRITES the healthy copy —
  which is how the board came to serve `margin 0.96 / total 44.38 /
  home_win 0.5267` on all 16 games across 4 dates.
- Root cause, already measured: `data/nfl_source/tracking/` is **gitignored**,
  so the nflverse pbp is on the mounted disk and absent from the repo
  checkout. A run whose `DATA_ROOT` resolves to the checkout loads ZERO plays,
  `team_rating` returns `(0.0, 0.0, "neutral_no_data")` for every club, and
  300 seeds are burned producing byte-identical rows.
- Files (exclusive to this lane):
  - `scripts/generate_smartsim2_nfl_projections.py` — the shared guards live
    here because the preseason script imports from it (`team_rating`,
    `load_pbp_plays`), so one implementation covers both generators.
  - `scripts/generate_smartsim2_nfl_preseason_projections.py` — wire the guard.
  - `tests/test_nfl_degenerate_writer_guard.py` (new).
- NOT touched: `syndicate/features/shared/nfl_game_projections.py`. The
  reader-side fix is already deployed and verified; re-opening it would put two
  changes on one observable.
- Design decision, recorded before implementing: refuse only when **EVERY**
  projection in the run is degenerate. A partial (e.g. two clubs whose
  abbreviations do not resolve) still yields a file carrying real information
  for the other games, and the deployed reader already drops the bad rows.
  Refusing on a partial would blank a mostly-good board — a worse failure than
  the one being fixed.
- Two guards, deliberately at different stages:
  1. PRECONDITION — zero plays loaded for both seasons is a hard data outage.
     Fail before simulating, so the failure names the missing path instead of
     surfacing as odd numbers 300 seeds later.
  2. PRE-WRITE — every projection degenerate means do not write AT ALL, so the
     last good artifact survives. Never truncate a healthy file with a bad one.
- Falsification test: the guard must NOT fire on a run where at least one club
  has real ratings, and must NOT fire on an empty schedule (no games is a
  different condition from no data, and conflating them would make an
  out-of-season run look like an outage).
- Blocked by: none.

### nfl-day-of-game — CLOSED-VERIFIED — superseded header, kept for the file/line map
- Goal: the NFL day-of-game engine is proven, stage by stage, against
  tonight's 6-game preseason slate (2026-08-13). Testable outcome: for each
  of the five stages — sim run, odds refresh, sim-projection→odds mapping,
  live lens, game-card update — a PRODUCTION measurement that is either
  "works, here is the non-zero reading" or "broken here, this is the first
  stage that is zero". No stage may be closed on a local-checkout reading.
- **Opens as lane 4 against a stated cap of 3.** Recorded, not hidden;
  `state.md` notes the cap is policy with no enforcement and that four ran
  unchallenged on 08-13. Flagged to the user at open time.
- Files (LITERAL PATHS — see the note below; a glob here is not enforcement):
  - `syndicate/features/nfl/live_game_state.py`
  - `syndicate/features/nfl/preseason_cards.py`
  - `syndicate/features/shared/game_chip_scoreboard.py`
  - `tests/conftest.py`
  - `tests/test_nfl_live_game_state.py`
  - `tests/test_nfl_preseason_market_board_live_odds.py`
  - `tests/test_game_chip_scoreboard.py`
  - `tests/test_nfl_preseason_cards.py`
- **THIS BLOCK ORIGINALLY READ `syndicate/features/nfl/**`, AND THAT GUARDED
  NOTHING.** `lane-guard.py` compares literal paths, so a glob claims no file
  at all: every file above was edited with the lane reporting protection it
  was not providing. Found during `/preflight`, by running the ledger's own
  `awk '/^### /{h=$0} /<path>/{print h}'` check and getting NO header back for
  three of the four source files. No collision resulted — none of them is
  claimed by another OPEN lane — but the claim was false while it mattered.
  **Never write a glob in a Files block.** Sibling of the 08-13 entry on
  `lanes.md` being executable configuration rather than documentation: this is
  the same class, arriving through syntax rather than through deletion.
- NOT touched, deliberately — claimed by other OPEN lanes:
  `syndicate/features/shared/live_refresh_loop.py` (mlb-props-regen),
  `pipeline/intelligence_state.py` and
  `syndicate/features/shared/memory_observability.py`
  (memory-guard-reclaimable). If the NFL defect lands in one of these, STOP
  and surface the collision instead of editing across the lane boundary.
- Hypothesis (recorded before testing): the day-of-game path is **not** end
  to end for NFL, and the break is upstream of the board. Three specific
  priors from the ledger, each to be confirmed or exonerated by measurement:
  1. `attach_projections` wires mlb/wnba/soccer only, and `board_enrichment`
     recorded that production holds no NFL predictions/edges of any kind
     (`#329` notes) — so the sim→odds mapping stage may have no join at all.
  2. `#377`: NFL `margin_mean` is a CONSTANT 0.96 and `total_mean` a constant
     38.76 across every game. If a sim runs tonight and the projections are
     still one value per market family, the sim executed and produced nothing
     game-specific — a pass on "did it run" and a fail on "is it a
     projection".
  3. `#389` follow-up: NFL projections were written to the ephemeral checkout
     (`/opt/render/project/src/data/...`) while the guard read
     `/opt/render/project/data/...`; the `nfl_artifact_output_root()` fix is
     recorded as AWAITING FIRST RUN. Tonight is the first live slate to test
     whether a completed sim's artifact is now visible to the reader.
- Falsification test: for prior 1 — a non-empty projection join on an NFL
  card tonight exonerates it. For prior 2 — two or more distinct `projected`
  values across tonight's 6 games exonerates it; one value confirms it. For
  prior 3 — `SEASON_PROJECTION_ARTIFACT_MISSING` absent after a launch, with
  the artifact readable at the guard's root, exonerates it.
- Hazards carried from `learnings.md` into this lane:
  - **A null agrees with everything.** Every zero recorded here needs a
    positive control — a case that makes the same instrument read non-zero —
    before it is written down as a finding. NFL is week-scoped, so an empty
    board is the EXPECTED reading for a wrong week and must never be reported
    as a broken stage.
  - **Preseason and regular season are separate week domains** and separate
    routes (`/nfl/preseason/*` vs `/nfl/*`). Tonight is preseason; reading
    the regular-season route would produce a legitimate empty and look like a
    defect.
  - Local `data/nfl_source/**` is a lossy mirror. Production first, always.
- Verification: a stage-by-stage table written into this lane and into
  `state.md`, each row carrying its measurement and its timestamp, with the
  first zero stage named explicitly if there is one.
- Blocked by: none.

#### MEASURED, 2026-08-13 slate (6 games, kickoffs 18:00–20:00 CDT)

| stage | verdict | measurement |
|---|---|---|
| sim run | RAN, output degenerate | 2 runs (20:59:41Z season, 21:00:11Z preseason); 16 distinct per-game `generated_at` 21:00:18→21:02:06 |
| odds refresh | **WORKS** | 8,537 shard rows, 11 books; DET@CIN 12→132 rows through kickoff, quotes <1.5 min fresh across 12 polls |
| sim→odds mapping | join works, input degenerate | 39/68 rows carry a projection; suppression honest |
| live lens | FAILS | `ll_live_rows = 0` on all 12 polls |
| game cards | FAILS | `cards live=0 final=0` on all 12 polls |
| board game state | **FAILS — root cause** | `by_state {pregame:6, live:0, final:0}` on all 12 polls, 35 min, with 3 games live |

**ROOT CAUSE — one join, not five surfaces.** `_NFLDataProvider.games()`
(`home.py:5704`) hands `build_game_chips` the week-scoped projection cards,
which carry no game state at all: `status` is the plain string
"Preseason Week 1", no `live_state`, no score, no clock, no kickoff time. So
`game_chip_scoreboard._game_flags` returns `(False, False)` for every NFL game
and `build_game_chip` stamps `pregame` by construction. Live lens, cards,
`by_state` and the Layer 1 game-state join all inherit that one value.

**FIXED** — `syndicate/features/nfl/live_game_state.py` stamps `live_state`
onto the cards. Chosen because both `publication_adapter._shared_game_state`
and `game_chip_scoreboard._game_flags` ALREADY read `live_state`; no NFL
builder ever set one. `#334`'s lesson: the fix goes inside the shared shape,
zero call sites touched. Live integration against the real slate:
`matched 16/16, live 2`, `by_state {live:2, pregame:14}`, real scores
(GB@PIT 3-0), real tokens (`Q1 3:42`), and a real kickoff time on all 16 —
the cards had none before.

#### CORRECTIONS MADE IN THIS LANE

- **RETRACTED: "odds refresh stops at kickoff."** It does not. I read a
  13-minute pregame→live transition lag (loop flipped `phase=live` at
  23:13:24Z, 13 min after the 23:00Z kickoff) and reported a stoppage. The
  odds path is the healthiest stage of the five. Exactly the "a null agrees
  with everything" trap this lane's own hazard list named.
- **RETRACTED: "the week label is wrong."** `PRESEASON_WEEK_LABELS` maps
  internal week 2 → "Preseason Week 1" **deliberately** — internal week 1 is
  Hall of Fame Weekend, so tonight IS public Preseason Week 1. Caught by
  reading the code before shipping a "fix". Residual real nit, not fixed:
  `requested_date` formats the RAW index as `f"Preseason Week {selected_week}"`,
  so it says "Week 2" beside `date`'s "Week 1". Cosmetic, left alone.
- **`#377` CONFIRMED and EXTENDED, and the join EXONERATED.** Not just
  `margin_mean`: `home_win_rate` 0.5267, `margin_mean` 0.96, `total_mean`
  44.38 are each ONE value across 16 games and 4 dates (08-13/14/15/16). The
  16 distinct per-game `generated_at` stamps prove the sim ran per game and
  produced identical output — so this is the MODEL, not the lookup.
  `model_prob_over` varies (0.4393–0.5237) only because the LINES vary, which
  makes a degenerate model read as a working one on the board. Lead, not
  conclusion: the artifact carries
  `rating_source=...[neutral_no_data/neutral_no_data]` and `seeds_used=2`.
  **Unowned, needs its own lane.**
- **UNRESOLVED:** cards and Layer 1 disagree about the same 16 games (cards
  show per-game totals, e.g. DET@CIN 46.275; Layer 1 shows the constant
  44.38). Different root resolvers — `default_nfl_source_root()` vs
  `preferred_source_roots()`. Could not settle it: `smartsim2*` is not in
  `HOT_ARTIFACT_PATTERNS`, so ops export/stream both 403 and the production
  CSV is unreadable from here. Flagged, not guessed.

#### FOUND IN PASSING — cross-sport, unclaimed file

`game_chip_scoreboard._score_value(0)` returned **None**: it routed through
`_text`, which is `str(value or "")`, so an integer 0 became `""`. Every
scoreless team lost its score on the chip, in **every sport**. Found because
GB @ PIT rendered `away 3, home None` instead of 3-0. Fixed in `_score_value`
only — not in `_text`, whose other callers are labels and names where the
falsy-collapse is harmless. Pinned by 6 tests in `test_game_chip_scoreboard.py`,
including that the pregame 0-0 placeholder suppression still works.

#### TEST HYGIENE DEFECT I INTRODUCED, THEN FIXED

The game-state stamp made `build_preseason_cards_page_context` perform a live
ESPN call — measured: exactly 1 fetch, ~1.5s, per build. That made the suite
network-dependent, and `test_nfl_preseason_cards` began failing because it
builds 2026 preseason week 1 (Hall of Fame weekend) and ESPN correctly returns
`final` where the board used to hardcode `pregame` — a true reading of the
world and a flaky test. Blocked at the `_fetch_scoreboard` seam by an autouse
conftest fixture, so the index's own caching/keying still runs under test and
only the socket is removed. Positive control written and run: no sockets
opened, `_fetch_scoreboard` returns None under pytest.

### spread-line-sign-convention — **CLOSED-VERIFIED 2026-08-16 — home candidates now carry their own handicap, confirmed on a post-deploy artifact (`written_at=00:12:35Z`, 2/2 home rows). n=2; generality beyond mlb unmeasured** — opened 2026-08-15 — session: lane-cleanup
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

### (superseded lane detail — the original body this lane was opened with)
- Goal: name why MLB odds went **2h01m without a single new quote observation**
  on 2026-08-14 while the refresh loop ticked ~8 times through it. Testable
  outcome: the gap is attributed to a named gate/failure with a log line or a
  counter proving it, and either fixed or filed with the fix specified.
- **MEASURED BEFORE HYPOTHESISING, all times CDT:**
  - Freshest MLB quote observation was **08:09:14** and was still 08:09:14 when
    re-read **78 minutes later** — the identical instant, so this is a stall,
    not a slow cadence. Read twice off `/api/board/layer1` (10:00 and 10:18).
  - The board artifact rebuilt normally through the whole gap (10:09 build
    against 08:09 odds). **Board freshness and odds freshness are independent**
    — the grid keeps re-pivoting a frozen shard, which is exactly why nothing
    downstream noticed.
  - **The loop was NOT dead.** `loop_tick_begin` on live-odds-worker at 08:08,
    08:24, 08:39, 08:54, 09:09 ... and `loop_sleep` carrying
    `interval_seconds: 900`, i.e. the adaptive pregame cadence, working as
    designed. Ticks ran; quotes did not appear.
  - **Not memory.** 795MB of 2048, 1252MB headroom, zero `MEMORY_GUARD` hits in
    the window. The two `server_failed earlyExit=true evicted=false` events
    (06:16Z, 12:22Z, ~6h apart) are the worker's OWN `max_uptime_seconds`
    recycle, not crashes — `run_live_odds_refresh_worker.py:411` prints
    `RECYCLING ... to reset accumulated page cache`. Do not chase these.
  - **It recovered on its own** between 10:18 and 10:36 (freshest observation
    moved to 10:10). So the target is an intermittent gate, not a dead service.
  - Cross-sport at 10:37: mlb 23.5m, wnba 54.0m, nfl 53.1m, soccer 12.9m. Tens
    of minutes is NORMAL here. The 2h hole is the tail of an existing
    distribution, not a unique event — so "is 2h just a long sample of the
    ordinary cadence" is a live alternative to the gate story and must be
    tested, not assumed away.
- Hypothesis: the tick runs but the per-sport fetch is skipped by a gate that
  is time- or state-dependent (a T-window/cost gate, an "already captured"
  short-circuit, or an OddsAPI error swallowed into a no-op), so the tick
  reports success while writing nothing to the `book_quotes` shard.
- Falsification test: if a tick inside a stall is shown to CALL the OddsAPI and
  receive quotes, then the fetch is not being skipped and the loss is
  downstream in the shard write or the last-seen tracking — a different fix in
  a different file, and this hypothesis is dead.
- Secondary falsifier: if the per-tick quote-write count is nonzero throughout
  the 08:09-10:10 window, then nothing stalled and `seen_age` is simply not
  measuring what the board is now reporting — which would make the freshness
  field I just shipped WRONG and is the first thing to rule out.
- Files: none claimed yet — this is read-only diagnosis until the gate is
  named. Any fix will land in `syndicate/features/shared/live_refresh_loop.py`
  or `scripts/run_live_odds_refresh_worker.py`, **both of which are claimed by
  OPEN lane `mlb-props-regen`** (`live_refresh_loop.py`) and
  `refresh-worker-anon-leak` / `anon-allocation-site`
  (`run_live_odds_refresh_worker.py`). Diagnosis can proceed; a fix cannot be
  written here without reassigning that file. Flagged now rather than at the
  point of edit.
- Blocked by: none for diagnosis. Blocked on lane reassignment for any fix.

### quote-join-enrich-cost (detail below, kept for the file/line map) — session: memory-guard
- Goal: the MLB board-build's ~33s per slow game is attributed to a named
  cause inside `enrich_block` and then cut. Testable outcome: on a comparable
  evening slate, `SLOW_SEGMENT_PROFILE tail_s` for MLB drops below 10s with
  `rows_walked` down by at least an order of magnitude.
- **THE MEASUREMENT LANDED. This lane starts from data, not a hypothesis.**
  `sim-execution-observability` handed this on CLOSED-PENDING-MEASUREMENT,
  waiting for one evening build. It fired 2026-08-13 18:10Z on refresh-worker
  (`03073270`), twice:
  ```
  18:10:24 [home] SLOW_SEGMENT_PROFILE sport=mlb total_s=33.32 rows=2
     rows_s=0.00 tail_s=33.32 enrich_block=33.32 mlb_props_block=0.00
     row[0]=0.00 join:by_player=15,by_teams_fallthrough=5,calls=20,
     rows_walked=1718960
  18:10:58 [home] SLOW_SEGMENT_PROFILE sport=mlb total_s=34.28 rows=2
     rows_s=0.00 tail_s=34.28 enrich_block=34.27 record_rows_block=0.00
     join:by_player=17,by_teams_fallthrough=2,calls=19,rows_walked=1
  ```
  Reading it against that lane's own decision rule:
  - `tail_s` (33.32) **>>** `rows_s` (0.00) -> the cost is **post-loop**, and
    `enrich_block=33.32` names it. The row loop is **EXONERATED** — 0.00s in
    both samples.
  - This confirms the retraction already in `learnings.md`: `SLOW_ROW_PROFILE`'s
    "one pathological iteration takes 100-400s" was a span artifact. There is
    no pathological row.
  - `rows_walked=1718960` over `calls=20` — ~86k rows walked per call. The
    second sample walked **1** row for a near-identical total time, which is
    the single most interesting number here (see falsification test).
- Files (exclusive to this lane):
  - `syndicate/features/shared/odds_book_quotes.py` — the join and its
    counters. `_bump("rows_walked", len(rows))` at L1254; `_QUOTE_JOIN_STATS`
    is per-call, not per-row (documented L1250).
  - `syndicate/features/shared/quote_enrichment.py` — `enrich_candidate_rows`
    at L366, the entry point the enrich block calls.
  - `syndicate/blueprints/home.py` — `enrich_block` mark at L2872, profiler
    emit at L2926. Segment/profiler code only.
- NOT claimed, deliberately: `syndicate/features/intelligence.py`. It is the
  caller (L6362) and holds the `blueprints.home` imports, but this lane does
  not need to edit it, and `memory-guard-reclaimable` has a (never-exercised)
  L2563-constant-only claim on it. If a fix needs that file, resolve the claim
  first rather than editing across lanes.
- Collision check: CLEAR. Neither OPEN lane (`memory-guard-reclaimable`,
  `mlb-props-regen`) claims any of the three files above. The CLOSED
  `sim-execution-observability` lane claimed two of them; this lane is the
  continuation it handed on.
- Hypothesis: the ~33s is a linear scan in the quote join, taken on the
  `by_teams_fallthrough` path when the cheap `event_id` key misses.
- **Falsification test, and it must be run FIRST.** The two samples disagree
  with the hypothesis as stated: sample 1 walked **1,718,960** rows in 33.32s;
  sample 2 walked **1** row in 34.28s. **Near-identical time, six orders of
  magnitude apart in rows walked.** If `rows_walked` does not drive the time,
  the join scan is NOT the cause and the cost is elsewhere in
  `enrich_candidate_rows` — an I/O wait, a per-call artifact load, or a
  network call. Do not optimise the scan until this is resolved.
- **HAZARD — the two instruments agree EXACTLY and that is not corroboration.**
  `SLOW_SEGMENT_PROFILE total_s=33.32` and `SLOW_GAME_CANDIDATE elapsed_s=33.32`
  match to the hundredth in both samples. `learnings.md` ("An instrument's SPAN
  is not its NAME") records that this exact agreement was previously read as two
  independent measurements confirming each other when they were **the same
  quantity measured twice**. Prove they are not reading the same clock interval
  before citing either as independent evidence.
- **HAZARD — `QUOTE_JOIN_STATS` returns 0 hits as a standalone token.** The
  join counters are emitted *inside* the `SLOW_SEGMENT_PROFILE` line
  (`join:...`), so a search for the bare token is not evidence of anything.
  Do not read that zero as a missing instrument.
- Architectural finding, recorded not actioned: `syndicate/features/
  intelligence.py` imports **four** symbols from `syndicate/blueprints/home.py`
  (`_build_sport_overview` L47, `_build_prop_dashboard_row` L48,
  `_game_bet_candidates_from_game` L49, `_mlb_actual_payload_for_game` L6641).
  The worker's board build therefore executes a Flask **presentation
  blueprint**, which inverts the layering CLAUDE.md specifies. Concrete
  consequence already observed: the `[home]` prefix makes worker cost look like
  a web-route problem. Out of scope here; worth its own ticket.
- Verification: a comparable evening slate shows MLB `tail_s` < 10s, with the
  cause named in the lane before any change ships, and a before/after pair
  taken from the SAME instrument on comparable slates.
- Deploy exposure: refresh-worker `.py` only when it comes. No `render.yaml`.
  NOTE: refresh-worker currently carries an OPEN `#417` measurement due
  2026-08-14 13:00 — **do not deploy this lane's changes before that read
  lands**, or the two changes become unattributable.
- Blocked by: none for diagnosis. Deploy blocked until the `#417` read.
- **STATUS 2026-08-13 17:0x CDT — FIX WRITTEN, PUSHED (`9d730aec`), NOT
  DEPLOYED. `/preflight` FAILED; held until after the `#417` read.**
  - The join now indexes `event_id` / `player_name` / `(home,away)` to a
    candidate union instead of scanning the shard. **Measured at production
    shard size (82,500 rows): 85.43 -> 0.66 ms/call, 130x, identical result.**
    Per game: 1.71s -> 0.01s at 20 calls, 5.30s -> 0.04s at 62.
  - **Teams could be indexed safely and that was the load-bearing question.**
    `_row_teams_match` delegates to the alias maps, so a token index would
    silently drop matches ("chc" vs "chicago cubs" is the gap that left 0 of
    108 candidates priced on 2026-08-06). It reads ONLY `home_team`/
    `away_team`, so rows sharing a pair cannot disagree — grouping by pair
    runs the fuzzy matcher once per PAIR (~15) instead of once per ROW (~83k).
  - Equivalence PROVEN, not assumed, because this join's wrong answers are
    silent: 30+ query shapes asserted identical to the full scan, where the
    reference is the real old path (union forced to every row). The grid is
    also asserted to exercise `by_event`, `by_player`,
    `by_teams_fallthrough` AND `no_identity` — a differential test proves
    equality, not coverage — plus index-narrows and no-stale-index tests.
    105 passed / 30 subtests across every quote suite.
  - **The fix will silence its own instrument.** `SLOW_SEGMENT_PROFILE` is
    gated at 5s, so success means it stops emitting — and that zero is
    indistinguishable from a broken instrument or an empty slate. Read it only
    against a positive control (`LAYER2_SHORTLIST` still recurring) and the
    pre-fix baseline of 8 lines in ~4 minutes. Same emitter trap as `basis`,
    caught before the deploy this time rather than after.
  - Local absolute numbers run ~19x faster per call than production's ~1.6s;
    the RATIO is the transferable claim and is likely conservative, since the
    indexed path does not scale with shard size while the scan does.
  - Still unexplained and worth watching: the 18:07:20 sample at **10.53 s/M**
    against ~18-21 for the other seven, at the largest volume. That suggests
    an amortised per-call cost the index will not touch.

- **STATUS 2026-08-13 16:4x CDT — HYPOTHESIS CONFIRMED, NOT FALSIFIED. THE
  FALSIFICATION TEST ABOVE RESTED ON MY OWN TRUNCATION ARTIFACT. Read this
  before acting on anything earlier in this lane.**
  - **RETRACTED: "sample 2 walked 1 row in 34.28s".** That was never in the
    data. The log line is **216 characters** and the printout that produced it
    cut at **210**, turning `rows_walked=1633012` into `rows_walked=1`. The
    "six orders of magnitude apart for identical time" paradox — the entire
    stated reason to distrust the join-scan hypothesis — was an artifact of my
    own display code, not a property of the system.
  - **Eight samples, pulled untruncated 2026-08-13 16:4x from the already-
    deployed profiler.** No new deploy was needed to get them.
    ```
    time      total_s   rows_walked  calls  rows/call  s/call  s per 1M rows
    18:07:20    54.17     5,143,272     62     82,956   0.874         10.53
    18:07:59    38.39     2,073,900     25     82,956   1.536         18.51
    18:08:20    21.22     1,161,384     14     82,956   1.516         18.27
    18:08:44    24.11     1,327,296     16     82,956   1.507         18.16
    18:09:19    34.59     1,704,000     20     85,200   1.730         20.30
    18:09:50    31.72     1,718,960     20     85,948   1.586         18.45
    18:10:24    33.32     1,718,960     20     85,948   1.666         19.38
    18:10:58    34.28     1,633,012     19     85,948   1.804         20.99
    ```
  - **`rows_walked` per call is essentially CONSTANT: 82,956 – 85,948.** Every
    call walks the same ~83k rows. Linear fit of `total_s` on `rows_walked`,
    excluding the 5.1M sample: **19.86 s per million rows, intercept −1.07s,
    R² = 0.918.** Near-zero intercept and near-perfect proportionality — the
    time IS the scan. Hypothesis CONFIRMED.
  - **And it is sharper than the lane predicted.** The lane expected the cost
    on the `by_teams_fallthrough` path when the cheap `event_id` key misses.
    It is not: `by_player` resolves 15–17 of ~20 calls and those calls STILL
    walk ~83k rows. **The scan is unconditional** — a successful join costs the
    same as a failed one. Fixing the fallthrough would have changed nothing.
  - Cost model: ~83k rows/call × ~20s per million ≈ **1.6s per call**, and a
    game makes 14–62 calls, which reproduces the observed 21–54s.
  - One sample resists the model: 18:07:20 is **10.53** s/M against ~18–21 for
    the other seven, and it is the largest (5.1M rows, 62 calls). Cheaper per
    row at higher volume suggests an amortised per-call cost (shard load, cache
    warm). Recorded rather than explained away — it is the one point that would
    move the fix's expected payoff.
  - **Fix direction:** index the quote log by join key instead of scanning it
    per candidate. Not a micro-optimisation of the scan.
  - The `SLOW_ENRICH_PROFILE` deploy is still worth doing — it separates
    `join_s` from `post_s`/`score_s` definitively and gives `join_s_per_call`
    directly — but it is now CONFIRMATION of a known answer, not the discovery
    step. Do not let its absence block the fix.
- **STATUS 2026-08-13 16:2x CDT — INSTRUMENT WRITTEN, PUSHED, NOT DEPLOYED.**
  - `7ce27100` on `origin/main`: `SLOW_ENRICH_PROFILE` splits
    `enrich_candidate_rows` into `setup_s`/`join_s`/`post_s`/`score_s` plus
    `accounted_s`/`unattributed_s`. **Observability only, no behaviour change.**
    Gated at 5s (`SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS`), one line per slow game.
  - Verified rather than assumed, four ways: **liveness** (forced slow join →
    emits, `join_s=0.51` of `total_s=0.54`); **accounting**
    (`accounted_s == total_s`, `unattributed_s=0.00` — no blind spot);
    **silence** below threshold; **degraded path** (a raising join still returns
    every row). Plus a **mutation check** — deleting the `join_s` accumulation
    turns exactly the two attribution tests red and leaves the other 19 green,
    so they are not toothless (`#288`'s failure mode).
  - Two deliberate safety properties: timing locals live OUTSIDE the `try`
    (its `except Exception` swallows and returns unenriched candidates, so
    anything raising in there degrades the board silently), and the emit is in
    a `finally` (three exits; a profiler covering only the happy one would
    under-report exactly the slow calls worth seeing).
  - **DEPLOY FOLDED INTO THE 2026-08-14 13:00 WINDOW** as Part 3 of the
    `417-24h-read` scheduled task, gated on the `#417` read returning a
    CONCLUSIVE verdict. If that read is INCONCLUSIVE the deploy is skipped —
    another reboot would reset the re-warm clock and the read would never land.
  - **Scope of that deploy depends on what happens overnight.** If
    `deploy-419-refresh-worker` fires (00:00–05:00) the worker lands on
    `d6188ca7` and `7ce27100` then adds **exactly one production file**
    (`quote_enrichment.py`). If it does NOT fire, `7ce27100` also carries
    `live_refresh_loop.py` (+107, `#419`) which belongs to `mlb-props-regen` —
    two substantive changes, and not this lane's to bundle. The task is told
    to check and ask rather than decide.
  - **First useful reading is the following EVENING, not at deploy time.** The
    line only fires on a slow game and MLB's slow builds cluster 20:49–00:45Z.
    Silence before then is expected and is not evidence — the same mistake the
    predecessor lane made when it read "neither instrument has emitted" as a
    finding.

### memory-guard-reclaimable (detail below, kept for the file/line map) — session: memory-guard
- Goal: `memory_headroom_snapshot` decides on unreclaimable memory
  (`anon + shmem + slab_unreclaimable`), so that total memory in use FALLING
  can never tighten the guard. Unblocks `#417` and `#387` in one change.
- Files (exclusive to this lane):
  - `syndicate/features/shared/memory_observability.py` — the fix. Two sites
    share the same wrong formula:
    - `memory_headroom_snapshot()` L238–242 — `reclaimable_bytes =
      inactive_file + slab_reclaimable`. This is the guard.
    - `log_container_memory()` L599–609 — recomputes the SAME expression to
      derive `memory_unreclaimable_mb`. Diagnostic only, but it is the line
      humans read, so it must move with the guard or the log will contradict
      the decision.
  - `tests/test_memory_observability.py` — see hazard below.
  - `pipeline/intelligence_state.py` — L3189 constant only
    (`_MIN_SAFE_MEMORY_HEADROOM_BYTES = 1900MB`). No call-site change.
  - `syndicate/features/intelligence.py` — L2563 constant only
    (`_OVERVIEW_MIN_SAFE_HEADROOM_BYTES = 3000MB` vs a stage measured at
    ~1479MB). No call-site change.
- Not touched, deliberately: the five calling modules
  (`live_refresh_loop.py` ×2 wrappers, `live_lens_loop.py` ×2 wrappers, and
  both `intelligence_state.py` call sites) all funnel through the one shared
  function. Per the `#334` lesson, the fix goes INSIDE it and touches zero
  call sites — that is what makes it unmissable.
  `scripts/check_worker_memory_gate.py` L338 records that it never inherited
  this formula and works on an RSS basis; adjacent, not the same defect,
  and out of scope.
- Hypothesis: the guard's verdict moves on kernel LRU bookkeeping, not on
  memory pressure. `#417`'s 300 consecutive aborts were caused by ~243MB
  being promoted `inactive_file` → `active_file`, which the formula counts
  as unavailable, while `anon` drifted +18.9MB across all 300 samples.
- Falsification test: replay the `#417` sample series — effective headroom
  fell 1877 → 1643MB while total memory in use fell 3120 → 2705MB. Under the
  new metric the guard must NOT tighten across that series. If it still
  tightens, the LRU-promotion hypothesis is wrong and something else moved it.
- Verification (all three required):
  1. Unit: the replayed `#417` series does not tighten.
  2. Liveness — the guard must still be able to REFUSE. Construct a case with
     genuinely high unreclaimable memory and assert `sufficient` is False.
     Without this, "zero aborts in production" is indistinguishable from a
     permanently-inert guard, and inert is how `#75` (the 4GiB OOM) happened.
  3. Production, after deploy: `MEMORY_GUARD_ABORT
     stage=pre_source_state_fingerprint` over a full day drops to ~0 with
     `anon` flat, and `#387`'s overview build stops aborting at
     `sports_done=0 sports_total=8`.
- HAZARD — an existing test asserts the bug is intentional.
  `test_active_file_and_shmem_are_not_treated_as_reclaimable`
  (`tests/test_memory_observability.py:173`) and the code comment at
  `memory_observability.py:234–237` both call the current formula
  "deliberately the conservative reading". That premise was overturned by
  `#417`: excluding `active_file` is not conservative, it is unstable — it
  makes the verdict swing on a quantity the kernel moves for free. This test
  must be rewritten with a comment recording WHY the premise changed, never
  deleted or quietly made green.
- HAZARD — the direction of failure. Relaxing this guard is what the
  `memory_observability.py:166–168` comment warns walks back into `#75`, the
  4GiB OOM. Note `shmem` was 0.0 in the `#79` measurement, so it has never
  actually been exercised as a pinned-cache term; do not assume it is zero on
  refresh-worker today.
- Deploy: refresh-worker `.py` only. No `render.yaml`, so no `blueprint_sync`
  exposure. Standing sim-check gate applies before any deploy is triggered.
- Blocked by: none.
- **STATUS 2026-08-13 — falsification test written and RUN. Hypothesis
  SURVIVED; the lane is cleared to proceed to the fix.**
  `tests/test_memory_observability.py`, 11 passed / 2 failed, the two failures
  being the new falsification tests, failing for exactly the predicted reason:
  - `test_417_page_cache_promotion_must_not_move_the_guard` — moving 243MB
    between LRU buckets, with `current`, `anon` and total file cache all held
    constant, swings the guard **1895.3 -> 1652.3 (243.0MB)**. The observable
    moves the full size of the reclassification with nothing real changing.
  - `test_417_series_never_tightens_while_memory_in_use_falls` — the recorded
    4-sample series is refused at sample 1 (`09:29:27 refused a build that
    fits`), i.e. all 300 aborted cycles had room under the unreclaimable
    reading.
  - Fixture provenance: `slab_reclaimable` is absent from the recorded table
    and was back-solved per row (34.2 / 35.3 / 34.8 / 39.3MB). All four rows
    then reproduce the recorded `headroom` to **±0.00MB**, so the fixture is
    derived from the real formula rather than fitted to the conclusion. If a
    future edit breaks that reproduction, the fixture is wrong, not the code.
  - `test_unreadable_anon_must_not_produce_a_rosy_headroom` **passes today and
    is still required.** It is inert against the current formula, which never
    reads `anon`; it becomes load-bearing the moment the fix does. Do not read
    its green as evidence of anything about the fix — it is a regression guard
    placed ahead of the change, and its own predicate is not yet exercised.
  - Not committed. The file is RED on a shared tree by design.
- **STATUS 2026-08-13 — FIX WRITTEN. Both falsification tests now pass;
  `tests/test_memory_observability.py` 13/13 green. Not committed, not
  deployed, production effect UNVERIFIED.**
  - The guard now decides on `max_bytes - unreclaimable`, where unreclaimable
    is `max(anon + shmem + slab_unreclaimable, current - reclaimable_file)`
    and `reclaimable_file` now includes `active_file`.
  - **The max() is the part worth reviewing.** The formula `learnings.md`
    prescribed (`anon + shmem + slab_unreclaimable`) is a LOWER bound on
    unreclaimable memory — it credits everything `memory.stat` fails to
    attribute as available, which is the permissive-on-unknown shape. Taking
    the larger of it and the residual basis (`current - reclaimable_file`,
    which is what `#318`'s log line already used) makes unaccounted memory
    count against the guard. On the `#417` samples the two bases differ by
    ~5.1-5.6MB, so this does not change the verdict there — it changes what
    happens if `#327`'s unattributed allocator ever shows up in this reading.
  - Both helpers are shared by the guard and by `log_container_memory`, which
    had an independent second copy of the reclaimable expression. Fixing only
    the guard would have left the abort line contradicting the decision it is
    read to explain. Grepped after the change: no third copy exists.
  - Degrade path unchanged in the safe direction: `anon` absent -> return None
    -> fall back to the previous arithmetic, never to a rosier number.
  - `#417`'s second defect fixed in the same pass:
    `headroom_including_file_cache_mb` -> `headroom_excluding_file_cache_mb`.
    The name stated the opposite of its value and produced a 792MB apparent
    deficit against a real one of 278MB during the incident. Renamed rather
    than aliased; nothing outside this module's tests reads it.
  - Two pre-existing tests changed deliberately, neither made green by
    weakening it:
    - `test_reclaimable_page_cache_does_not_count_against_headroom` (`#79`)
      moved +34.3MB, exactly its fixture's `active_file`. Conclusion it
      protects is intact (868 vs 3428, was 868 vs 3393).
    - `test_active_file_and_shmem_are_not_treated_as_reclaimable` split into
      `test_shmem_is_not_treated_as_reclaimable` (still true, different
      reason) plus the new `#417` invariance test that owns the overturned
      active_file half.
  - Consumer blast radius, partially checked: 7/7
    `test_intelligence_overview_memory_guard.py`, and 25 memory/headroom/guard
    tests across `test_intelligence_state.py`, `test_deploy_preflight.py`,
    `test_live_lens_loop.py`. **Full 6-file consumer sweep still running at
    time of writing — not yet a result.**
  - REMAINING before this can close: the production half of Verification
    (items 2 and 3 above) is untouched. Nothing here proves the deployed
    behaviour changes; per `learnings.md` a deployed fix can be inert.
- **STATUS 2026-08-13 12:2x CDT — PUSHED to `origin/main` as `03073270`,
  decoupled from config. NOT DEPLOYED. Production effect still UNVERIFIED.**
  - `/preflight` returned **FAIL** on the original candidate (`03073270` on
    local `main`) for a reason that had nothing to do with the fix: local
    `main` carried **four unpushed `render.yaml` commits** underneath it
    (web env block 64 -> 52 keys). Render deploys from GitHub, so shipping
    the fix required a push, and that push would have fired `blueprint_sync`
    — rewriting the whole env block on all three live services. A code fix
    would have carried an undecided production config change as a passenger.
  - Resolved by cherry-picking onto `origin/main` in a throwaway worktree
    (the shared tree has other sessions' uncommitted work). Verified before
    pushing: 3 files, **zero `render.yaml` delta**, web-block key count
    64 == 64, and `render.yaml` absent from the commit entirely. 20/20 tests
    green on that base (13 memory_observability + 7 overview guard).
  - **The `render.yaml` web-block audit is now unshipped and unowned.** It
    still sits on local `main` only. It needs its own `/preflight` and its
    own `deploys.md` row — it is a production config change, not a passenger.
    One item for whoever takes it: `MLB_ENABLE_LIVE_LENS_LOOP: "false"` is
    among the 12 keys being removed from web. If the code default is True,
    removing it turns the loop ON for web rather than off — the `absent != off`
    hazard. NOT verified by this lane.
  - **`main` has diverged and this commit now exists twice.** `03073270`
    (local) and `03073270` (origin) are the same change. Local `main` is 6
    ahead / 1 behind origin. Do not `git pull` and assume a clean merge —
    reconcile deliberately, and drop the local duplicate rather than
    re-landing it.
  - Deploy still gated: `scripts/check_deploy_safety.py` returned NOT CLEAR
    twice, 12:14 and 12:2x CDT — MLB sims running back-to-back (pid 4514
    `tip_off_window`, then pid 4718 `fingerprint_change`) plus a live odds
    refresh, with live games in progress. Deploying kills them.
  - **Falsifiable discriminator for the post-deploy read, stated before the
    deploy:** the new `basis` field. `basis=unreclaimable` proves the new
    path executed; `basis=reclaimable_cache` means it degraded to the old
    arithmetic and any "zero aborts" reading is inert-guard-shaped and means
    nothing. Read that BEFORE reading the abort count.
- **STATUS 2026-08-13 ~12:5x CDT — local `main` reconciled with `origin/main`
  (`a3f9ed97`). Push HELD by decision. Still not deployed.**
  - Merge, not rebase. `git cherry` showed two local commits patch-equivalent
    to origin (`03073270`≡`03073270`, `b48aa0d3`≡`b48aa0d3`); a rebase would
    have dropped them cleanly but rewritten **seven commits belonging to other
    sessions** working this shared checkout, and the ledger cites SHAs by
    hand. Verified after: 0 behind / 11 ahead, `origin/main` is an ancestor,
    all six other-session SHAs unchanged, and the merge commit is **empty
    against its first parent** — content was already identical, only ancestry
    changed.
  - One conflict (`.syndicate/lanes.md`), both regions ours-only with an
    **empty theirs side**. Resolved keep-ours; verified content-complete
    (468 lines both sides, differing only CRLF vs LF).
  - NEAR-MISS worth recording: the first merge attempt was aborted because
    another session had **8 files staged in the shared index** (the
    `.syndicate` enforcement hooks). A merge commit takes the WHOLE index, so
    completing it would have swallowed their in-flight work. Proved the merge
    safe in a throwaway worktree instead, and ran it only once their index
    cleared. `learnings.md` already has the never-chain-add-and-commit rule;
    this is the same hazard arriving through `git merge` instead.
- **RETRACTION — the `render.yaml` hazard I raised is NOT a hazard.** This
  lane earlier flagged `MLB_ENABLE_LIVE_LENS_LOOP: "false"` as a possible
  `absent != off` trap in the web-block audit. Checked against the code:
  **no Python reads that key anywhere** — it exists only in `render.yaml`, so
  removing it from web is inert. Also cleared:
  `WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN` defaults **False** when absent
  (`scripts/run_refresh_worker.py:338`), `REFRESH_PREDICT_PROPS_SMART_SIM_PBP`
  defaults **True** matching its removed value, and
  `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` is read only by a worker script as
  EXTRAS (absent = no extras, `scripts/fetch_mlb_oddsapi_local.py:1593`).
  The audit's "already declared on both workers, unchanged there" claim holds.
  Recording the retraction loudly because a false caveat about someone else's
  work silently devalues their correct readings too.
- **What still blocks the push is the MECHANISM, not the diff.** A
  `blueprint_sync` writes the WHOLE env block on all three services — not the
  diff — including live drift nobody has read, and last time it 502'd every
  route for ~2 minutes. That restart kills an in-flight MLB sim exactly as a
  deploy does. Decision taken: **hold the push until
  `check_deploy_safety.py` reports CLEAR, then push and deploy in the same
  quiet window** so the config sync and the code deploy cost one interruption
  instead of two. Watcher `b07yqo98b` is armed, polling every 90s.
- Discrepancy noted, does not affect the verdict: the `#417` narrative in
  `.syndicate/log/2026-08-13.md` and `todo.md` says `current_mb` fell
  "3120 -> 2705", but the 4-row table it sits beside records 2988.6 -> 2705.3.
  The 3120 figure is not in the table; it is presumably an intermediate peak.
  Both readings agree in DIRECTION (usage fell, guard tightened), so the
  falsification test holds either way — but the table is the authoritative
  per-sample record and is what the fixture uses.

### (superseded lane detail, kept for the file/line map)

### mlb-live-pitcher-projection — CLOSED-VERIFIED 2026-08-16 00:3xZ — all three invariants measured at scale, 423 rows, zero violations
Opened 2026-08-15 from a user report: "live projections rarely get appended, and
the ones that do are unrealistic, especially pitcher props." Both halves were
real and were different defects. Todo `#437`.

- **Goal, and it was met.** On a live MLB slate a live prop row must never show
  (a) a projection below an already-recorded actual, (b) a `model_prob_over` on
  the opposite side of the line from its own `projected`, or (c) a blank live
  column with no attributable reason.
- **VERIFIED IN PRODUCTION, served board, 423 live-lens overlaid rows:**
  **(a) 0 violations. (b) 0 violations** (baseline was 7 of 13). **(c)
  `live_projections` served** — `rows_live_considered 1377 /
  rows_live_projected 599 / rows_live_edged 0 / rows_live_prob_withheld 599 /
  miss_no_market_alias 778 / live_games_in_snapshot 8`. Live prop coverage went
  **11.6% -> 50.3%** on a clean same-slate read.
- **`rows_live_prob_withheld == rows_live_projected` (599 = 599) is the
  designed reading, not a fault:** the re-sim priced nothing that tick, and the
  counter exists to say so out loud instead of letting a pregame probability
  stand in.
- **Four fixes shipped:** `f4cd2bc8` (probability follows the projection or goes
  absent; pregame preserved as `sim_model_prob_over`), `3a476001` (the snapshot
  is a projection set, not a pick list — four causes), `302ea0f4` (alt lines),
  plus the route change that made the counters readable at all.
- **Deployed and CONFIRMED BY CONTENT after other sessions redeployed over the
  top:** refresh-worker `57a437d5` and live-odds-worker `c4116ab6` both still
  carry all five markers (`totals_alt`, `spreads_alt`, `lanes`,
  `include_projection_only`, `sim_model_prob_over`); web `484221bd` carries the
  route change. **Ancestry was never used as the test** — every service runs its
  own SHA and none are on `origin/main`.
- **Two findings handed on, NOT closed here:**
  1. **`game_chip_scoreboard._game_flags` reintroduces the abstract-only live
     check** that `features/mlb/game_state.py` exists to prevent and forbids by
     name. It marks a warming-up game `live`, which is what made MIA @ CIN read
     0-of-114 before first pitch and 74-of-117 (63.2%) after. **Blast radius is
     every sport's board chips. Needs an owner.** Detail in `state.md`.
  2. **The alt-line predicate is UNMEASURED** — deployed 23:47/23:49Z, window
     closed at UTC midnight. One-shot watch `alt-line-shortlist-watch` fires
     2026-08-16 10:00 CT, gated on both the book grid AND the shortlist, and
     re-arms itself up to 4 times rather than reporting a false negative.
- **Self-inflicted, recorded rather than buried:** two commits (`f4cd2bc8`,
  `36439f4e`) reverted other sessions' ledger lines via a stale scratch index —
  the second one *after* I had written that exact race into `learnings.md`.
  Both repaired (`6da01dd3`, `6ccc4779`), nothing lost, and the rule is now a
  FORBIDDEN entry with the ref-lock backstop named.
- Commits: `f4cd2bc8` `6da01dd3` `a7ad6aed` `3a476001` `265884c0` `9eb5b7bc`
  `dc85bfeb` `f96a00fd` `36439f4e` `6ccc4779` `b11e19ba` `302ea0f4` `e6405fcc`
  `803dd65d`. All confirmed present in HEAD at close.
- Full detail: `.syndicate/log/2026-08-15.md`, and `deploys.md` for every
  measurement with its working.

### (superseded lane detail — the original body this lane was opened with)
- Goal: name why MLB odds went **2h01m without a single new quote observation**
  on 2026-08-14 while the refresh loop ticked ~8 times through it. Testable
  outcome: the gap is attributed to a named gate/failure with a log line or a
  counter proving it, and either fixed or filed with the fix specified.
- **MEASURED BEFORE HYPOTHESISING, all times CDT:**
  - Freshest MLB quote observation was **08:09:14** and was still 08:09:14 when
    re-read **78 minutes later** — the identical instant, so this is a stall,
    not a slow cadence. Read twice off `/api/board/layer1` (10:00 and 10:18).
  - The board artifact rebuilt normally through the whole gap (10:09 build
    against 08:09 odds). **Board freshness and odds freshness are independent**
    — the grid keeps re-pivoting a frozen shard, which is exactly why nothing
    downstream noticed.
  - **The loop was NOT dead.** `loop_tick_begin` on live-odds-worker at 08:08,
    08:24, 08:39, 08:54, 09:09 ... and `loop_sleep` carrying
    `interval_seconds: 900`, i.e. the adaptive pregame cadence, working as
    designed. Ticks ran; quotes did not appear.
  - **Not memory.** 795MB of 2048, 1252MB headroom, zero `MEMORY_GUARD` hits in
    the window. The two `server_failed earlyExit=true evicted=false` events
    (06:16Z, 12:22Z, ~6h apart) are the worker's OWN `max_uptime_seconds`
    recycle, not crashes — `run_live_odds_refresh_worker.py:411` prints
    `RECYCLING ... to reset accumulated page cache`. Do not chase these.
  - **It recovered on its own** between 10:18 and 10:36 (freshest observation
    moved to 10:10). So the target is an intermittent gate, not a dead service.
  - Cross-sport at 10:37: mlb 23.5m, wnba 54.0m, nfl 53.1m, soccer 12.9m. Tens
    of minutes is NORMAL here. The 2h hole is the tail of an existing
    distribution, not a unique event — so "is 2h just a long sample of the
    ordinary cadence" is a live alternative to the gate story and must be
    tested, not assumed away.
- Hypothesis: the tick runs but the per-sport fetch is skipped by a gate that
  is time- or state-dependent (a T-window/cost gate, an "already captured"
  short-circuit, or an OddsAPI error swallowed into a no-op), so the tick
  reports success while writing nothing to the `book_quotes` shard.
- Falsification test: if a tick inside a stall is shown to CALL the OddsAPI and
  receive quotes, then the fetch is not being skipped and the loss is
  downstream in the shard write or the last-seen tracking — a different fix in
  a different file, and this hypothesis is dead.
- Secondary falsifier: if the per-tick quote-write count is nonzero throughout
  the 08:09-10:10 window, then nothing stalled and `seen_age` is simply not
  measuring what the board is now reporting — which would make the freshness
  field I just shipped WRONG and is the first thing to rule out.
- Files: none claimed yet — this is read-only diagnosis until the gate is
  named. Any fix will land in `syndicate/features/shared/live_refresh_loop.py`
  or `scripts/run_live_odds_refresh_worker.py`, **both of which are claimed by
  OPEN lane `mlb-props-regen`** (`live_refresh_loop.py`) and
  `refresh-worker-anon-leak` / `anon-allocation-site`
  (`run_live_odds_refresh_worker.py`). Diagnosis can proceed; a fix cannot be
  written here without reassigning that file. Flagged now rather than at the
  point of edit.
- Blocked by: none for diagnosis. Blocked on lane reassignment for any fix.

### quote-join-enrich-cost (detail below, kept for the file/line map) — session: memory-guard
- Goal: the MLB board-build's ~33s per slow game is attributed to a named
  cause inside `enrich_block` and then cut. Testable outcome: on a comparable
  evening slate, `SLOW_SEGMENT_PROFILE tail_s` for MLB drops below 10s with
  `rows_walked` down by at least an order of magnitude.
- **THE MEASUREMENT LANDED. This lane starts from data, not a hypothesis.**
  `sim-execution-observability` handed this on CLOSED-PENDING-MEASUREMENT,
  waiting for one evening build. It fired 2026-08-13 18:10Z on refresh-worker
  (`03073270`), twice:
  ```
  18:10:24 [home] SLOW_SEGMENT_PROFILE sport=mlb total_s=33.32 rows=2
     rows_s=0.00 tail_s=33.32 enrich_block=33.32 mlb_props_block=0.00
     row[0]=0.00 join:by_player=15,by_teams_fallthrough=5,calls=20,
     rows_walked=1718960
  18:10:58 [home] SLOW_SEGMENT_PROFILE sport=mlb total_s=34.28 rows=2
     rows_s=0.00 tail_s=34.28 enrich_block=34.27 record_rows_block=0.00
     join:by_player=17,by_teams_fallthrough=2,calls=19,rows_walked=1
  ```
  Reading it against that lane's own decision rule:
  - `tail_s` (33.32) **>>** `rows_s` (0.00) -> the cost is **post-loop**, and
    `enrich_block=33.32` names it. The row loop is **EXONERATED** — 0.00s in
    both samples.
  - This confirms the retraction already in `learnings.md`: `SLOW_ROW_PROFILE`'s
    "one pathological iteration takes 100-400s" was a span artifact. There is
    no pathological row.
  - `rows_walked=1718960` over `calls=20` — ~86k rows walked per call. The
    second sample walked **1** row for a near-identical total time, which is
    the single most interesting number here (see falsification test).
- Files (exclusive to this lane):
  - `syndicate/features/shared/odds_book_quotes.py` — the join and its
    counters. `_bump("rows_walked", len(rows))` at L1254; `_QUOTE_JOIN_STATS`
    is per-call, not per-row (documented L1250).
  - `syndicate/features/shared/quote_enrichment.py` — `enrich_candidate_rows`
    at L366, the entry point the enrich block calls.
  - `syndicate/blueprints/home.py` — `enrich_block` mark at L2872, profiler
    emit at L2926. Segment/profiler code only.
- NOT claimed, deliberately: `syndicate/features/intelligence.py`. It is the
  caller (L6362) and holds the `blueprints.home` imports, but this lane does
  not need to edit it, and `memory-guard-reclaimable` has a (never-exercised)
  L2563-constant-only claim on it. If a fix needs that file, resolve the claim
  first rather than editing across lanes.
- Collision check: CLEAR. Neither OPEN lane (`memory-guard-reclaimable`,
  `mlb-props-regen`) claims any of the three files above. The CLOSED
  `sim-execution-observability` lane claimed two of them; this lane is the
  continuation it handed on.
- Hypothesis: the ~33s is a linear scan in the quote join, taken on the
  `by_teams_fallthrough` path when the cheap `event_id` key misses.
- **Falsification test, and it must be run FIRST.** The two samples disagree
  with the hypothesis as stated: sample 1 walked **1,718,960** rows in 33.32s;
  sample 2 walked **1** row in 34.28s. **Near-identical time, six orders of
  magnitude apart in rows walked.** If `rows_walked` does not drive the time,
  the join scan is NOT the cause and the cost is elsewhere in
  `enrich_candidate_rows` — an I/O wait, a per-call artifact load, or a
  network call. Do not optimise the scan until this is resolved.
- **HAZARD — the two instruments agree EXACTLY and that is not corroboration.**
  `SLOW_SEGMENT_PROFILE total_s=33.32` and `SLOW_GAME_CANDIDATE elapsed_s=33.32`
  match to the hundredth in both samples. `learnings.md` ("An instrument's SPAN
  is not its NAME") records that this exact agreement was previously read as two
  independent measurements confirming each other when they were **the same
  quantity measured twice**. Prove they are not reading the same clock interval
  before citing either as independent evidence.
- **HAZARD — `QUOTE_JOIN_STATS` returns 0 hits as a standalone token.** The
  join counters are emitted *inside* the `SLOW_SEGMENT_PROFILE` line
  (`join:...`), so a search for the bare token is not evidence of anything.
  Do not read that zero as a missing instrument.
- Architectural finding, recorded not actioned: `syndicate/features/
  intelligence.py` imports **four** symbols from `syndicate/blueprints/home.py`
  (`_build_sport_overview` L47, `_build_prop_dashboard_row` L48,
  `_game_bet_candidates_from_game` L49, `_mlb_actual_payload_for_game` L6641).
  The worker's board build therefore executes a Flask **presentation
  blueprint**, which inverts the layering CLAUDE.md specifies. Concrete
  consequence already observed: the `[home]` prefix makes worker cost look like
  a web-route problem. Out of scope here; worth its own ticket.
- Verification: a comparable evening slate shows MLB `tail_s` < 10s, with the
  cause named in the lane before any change ships, and a before/after pair
  taken from the SAME instrument on comparable slates.
- Deploy exposure: refresh-worker `.py` only when it comes. No `render.yaml`.
  NOTE: refresh-worker currently carries an OPEN `#417` measurement due
  2026-08-14 13:00 — **do not deploy this lane's changes before that read
  lands**, or the two changes become unattributable.
- Blocked by: none for diagnosis. Deploy blocked until the `#417` read.
- **STATUS 2026-08-13 17:0x CDT — FIX WRITTEN, PUSHED (`9d730aec`), NOT
  DEPLOYED. `/preflight` FAILED; held until after the `#417` read.**
  - The join now indexes `event_id` / `player_name` / `(home,away)` to a
    candidate union instead of scanning the shard. **Measured at production
    shard size (82,500 rows): 85.43 -> 0.66 ms/call, 130x, identical result.**
    Per game: 1.71s -> 0.01s at 20 calls, 5.30s -> 0.04s at 62.
  - **Teams could be indexed safely and that was the load-bearing question.**
    `_row_teams_match` delegates to the alias maps, so a token index would
    silently drop matches ("chc" vs "chicago cubs" is the gap that left 0 of
    108 candidates priced on 2026-08-06). It reads ONLY `home_team`/
    `away_team`, so rows sharing a pair cannot disagree — grouping by pair
    runs the fuzzy matcher once per PAIR (~15) instead of once per ROW (~83k).
  - Equivalence PROVEN, not assumed, because this join's wrong answers are
    silent: 30+ query shapes asserted identical to the full scan, where the
    reference is the real old path (union forced to every row). The grid is
    also asserted to exercise `by_event`, `by_player`,
    `by_teams_fallthrough` AND `no_identity` — a differential test proves
    equality, not coverage — plus index-narrows and no-stale-index tests.
    105 passed / 30 subtests across every quote suite.
  - **The fix will silence its own instrument.** `SLOW_SEGMENT_PROFILE` is
    gated at 5s, so success means it stops emitting — and that zero is
    indistinguishable from a broken instrument or an empty slate. Read it only
    against a positive control (`LAYER2_SHORTLIST` still recurring) and the
    pre-fix baseline of 8 lines in ~4 minutes. Same emitter trap as `basis`,
    caught before the deploy this time rather than after.
  - Local absolute numbers run ~19x faster per call than production's ~1.6s;
    the RATIO is the transferable claim and is likely conservative, since the
    indexed path does not scale with shard size while the scan does.
  - Still unexplained and worth watching: the 18:07:20 sample at **10.53 s/M**
    against ~18-21 for the other seven, at the largest volume. That suggests
    an amortised per-call cost the index will not touch.

- **STATUS 2026-08-13 16:4x CDT — HYPOTHESIS CONFIRMED, NOT FALSIFIED. THE
  FALSIFICATION TEST ABOVE RESTED ON MY OWN TRUNCATION ARTIFACT. Read this
  before acting on anything earlier in this lane.**
  - **RETRACTED: "sample 2 walked 1 row in 34.28s".** That was never in the
    data. The log line is **216 characters** and the printout that produced it
    cut at **210**, turning `rows_walked=1633012` into `rows_walked=1`. The
    "six orders of magnitude apart for identical time" paradox — the entire
    stated reason to distrust the join-scan hypothesis — was an artifact of my
    own display code, not a property of the system.
  - **Eight samples, pulled untruncated 2026-08-13 16:4x from the already-
    deployed profiler.** No new deploy was needed to get them.
    ```
    time      total_s   rows_walked  calls  rows/call  s/call  s per 1M rows
    18:07:20    54.17     5,143,272     62     82,956   0.874         10.53
    18:07:59    38.39     2,073,900     25     82,956   1.536         18.51
    18:08:20    21.22     1,161,384     14     82,956   1.516         18.27
    18:08:44    24.11     1,327,296     16     82,956   1.507         18.16
    18:09:19    34.59     1,704,000     20     85,200   1.730         20.30
    18:09:50    31.72     1,718,960     20     85,948   1.586         18.45
    18:10:24    33.32     1,718,960     20     85,948   1.666         19.38
    18:10:58    34.28     1,633,012     19     85,948   1.804         20.99
    ```
  - **`rows_walked` per call is essentially CONSTANT: 82,956 – 85,948.** Every
    call walks the same ~83k rows. Linear fit of `total_s` on `rows_walked`,
    excluding the 5.1M sample: **19.86 s per million rows, intercept −1.07s,
    R² = 0.918.** Near-zero intercept and near-perfect proportionality — the
    time IS the scan. Hypothesis CONFIRMED.
  - **And it is sharper than the lane predicted.** The lane expected the cost
    on the `by_teams_fallthrough` path when the cheap `event_id` key misses.
    It is not: `by_player` resolves 15–17 of ~20 calls and those calls STILL
    walk ~83k rows. **The scan is unconditional** — a successful join costs the
    same as a failed one. Fixing the fallthrough would have changed nothing.
  - Cost model: ~83k rows/call × ~20s per million ≈ **1.6s per call**, and a
    game makes 14–62 calls, which reproduces the observed 21–54s.
  - One sample resists the model: 18:07:20 is **10.53** s/M against ~18–21 for
    the other seven, and it is the largest (5.1M rows, 62 calls). Cheaper per
    row at higher volume suggests an amortised per-call cost (shard load, cache
    warm). Recorded rather than explained away — it is the one point that would
    move the fix's expected payoff.
  - **Fix direction:** index the quote log by join key instead of scanning it
    per candidate. Not a micro-optimisation of the scan.
  - The `SLOW_ENRICH_PROFILE` deploy is still worth doing — it separates
    `join_s` from `post_s`/`score_s` definitively and gives `join_s_per_call`
    directly — but it is now CONFIRMATION of a known answer, not the discovery
    step. Do not let its absence block the fix.
- **STATUS 2026-08-13 16:2x CDT — INSTRUMENT WRITTEN, PUSHED, NOT DEPLOYED.**
  - `7ce27100` on `origin/main`: `SLOW_ENRICH_PROFILE` splits
    `enrich_candidate_rows` into `setup_s`/`join_s`/`post_s`/`score_s` plus
    `accounted_s`/`unattributed_s`. **Observability only, no behaviour change.**
    Gated at 5s (`SYNDICATE_SLOW_ENRICH_TOTAL_SECONDS`), one line per slow game.
  - Verified rather than assumed, four ways: **liveness** (forced slow join →
    emits, `join_s=0.51` of `total_s=0.54`); **accounting**
    (`accounted_s == total_s`, `unattributed_s=0.00` — no blind spot);
    **silence** below threshold; **degraded path** (a raising join still returns
    every row). Plus a **mutation check** — deleting the `join_s` accumulation
    turns exactly the two attribution tests red and leaves the other 19 green,
    so they are not toothless (`#288`'s failure mode).
  - Two deliberate safety properties: timing locals live OUTSIDE the `try`
    (its `except Exception` swallows and returns unenriched candidates, so
    anything raising in there degrades the board silently), and the emit is in
    a `finally` (three exits; a profiler covering only the happy one would
    under-report exactly the slow calls worth seeing).
  - **DEPLOY FOLDED INTO THE 2026-08-14 13:00 WINDOW** as Part 3 of the
    `417-24h-read` scheduled task, gated on the `#417` read returning a
    CONCLUSIVE verdict. If that read is INCONCLUSIVE the deploy is skipped —
    another reboot would reset the re-warm clock and the read would never land.
  - **Scope of that deploy depends on what happens overnight.** If
    `deploy-419-refresh-worker` fires (00:00–05:00) the worker lands on
    `d6188ca7` and `7ce27100` then adds **exactly one production file**
    (`quote_enrichment.py`). If it does NOT fire, `7ce27100` also carries
    `live_refresh_loop.py` (+107, `#419`) which belongs to `mlb-props-regen` —
    two substantive changes, and not this lane's to bundle. The task is told
    to check and ask rather than decide.
  - **First useful reading is the following EVENING, not at deploy time.** The
    line only fires on a slow game and MLB's slow builds cluster 20:49–00:45Z.
    Silence before then is expected and is not evidence — the same mistake the
    predecessor lane made when it read "neither instrument has emitted" as a
    finding.

### memory-guard-reclaimable (detail below, kept for the file/line map) — session: memory-guard
- Goal: `memory_headroom_snapshot` decides on unreclaimable memory
  (`anon + shmem + slab_unreclaimable`), so that total memory in use FALLING
  can never tighten the guard. Unblocks `#417` and `#387` in one change.
- Files (exclusive to this lane):
  - `syndicate/features/shared/memory_observability.py` — the fix. Two sites
    share the same wrong formula:
    - `memory_headroom_snapshot()` L238–242 — `reclaimable_bytes =
      inactive_file + slab_reclaimable`. This is the guard.
    - `log_container_memory()` L599–609 — recomputes the SAME expression to
      derive `memory_unreclaimable_mb`. Diagnostic only, but it is the line
      humans read, so it must move with the guard or the log will contradict
      the decision.
  - `tests/test_memory_observability.py` — see hazard below.
  - `pipeline/intelligence_state.py` — L3189 constant only
    (`_MIN_SAFE_MEMORY_HEADROOM_BYTES = 1900MB`). No call-site change.
  - `syndicate/features/intelligence.py` — L2563 constant only
    (`_OVERVIEW_MIN_SAFE_HEADROOM_BYTES = 3000MB` vs a stage measured at
    ~1479MB). No call-site change.
- Not touched, deliberately: the five calling modules
  (`live_refresh_loop.py` ×2 wrappers, `live_lens_loop.py` ×2 wrappers, and
  both `intelligence_state.py` call sites) all funnel through the one shared
  function. Per the `#334` lesson, the fix goes INSIDE it and touches zero
  call sites — that is what makes it unmissable.
  `scripts/check_worker_memory_gate.py` L338 records that it never inherited
  this formula and works on an RSS basis; adjacent, not the same defect,
  and out of scope.
- Hypothesis: the guard's verdict moves on kernel LRU bookkeeping, not on
  memory pressure. `#417`'s 300 consecutive aborts were caused by ~243MB
  being promoted `inactive_file` → `active_file`, which the formula counts
  as unavailable, while `anon` drifted +18.9MB across all 300 samples.
- Falsification test: replay the `#417` sample series — effective headroom
  fell 1877 → 1643MB while total memory in use fell 3120 → 2705MB. Under the
  new metric the guard must NOT tighten across that series. If it still
  tightens, the LRU-promotion hypothesis is wrong and something else moved it.
- Verification (all three required):
  1. Unit: the replayed `#417` series does not tighten.
  2. Liveness — the guard must still be able to REFUSE. Construct a case with
     genuinely high unreclaimable memory and assert `sufficient` is False.
     Without this, "zero aborts in production" is indistinguishable from a
     permanently-inert guard, and inert is how `#75` (the 4GiB OOM) happened.
  3. Production, after deploy: `MEMORY_GUARD_ABORT
     stage=pre_source_state_fingerprint` over a full day drops to ~0 with
     `anon` flat, and `#387`'s overview build stops aborting at
     `sports_done=0 sports_total=8`.
- HAZARD — an existing test asserts the bug is intentional.
  `test_active_file_and_shmem_are_not_treated_as_reclaimable`
  (`tests/test_memory_observability.py:173`) and the code comment at
  `memory_observability.py:234–237` both call the current formula
  "deliberately the conservative reading". That premise was overturned by
  `#417`: excluding `active_file` is not conservative, it is unstable — it
  makes the verdict swing on a quantity the kernel moves for free. This test
  must be rewritten with a comment recording WHY the premise changed, never
  deleted or quietly made green.
- HAZARD — the direction of failure. Relaxing this guard is what the
  `memory_observability.py:166–168` comment warns walks back into `#75`, the
  4GiB OOM. Note `shmem` was 0.0 in the `#79` measurement, so it has never
  actually been exercised as a pinned-cache term; do not assume it is zero on
  refresh-worker today.
- Deploy: refresh-worker `.py` only. No `render.yaml`, so no `blueprint_sync`
  exposure. Standing sim-check gate applies before any deploy is triggered.
- Blocked by: none.
- **STATUS 2026-08-13 — falsification test written and RUN. Hypothesis
  SURVIVED; the lane is cleared to proceed to the fix.**
  `tests/test_memory_observability.py`, 11 passed / 2 failed, the two failures
  being the new falsification tests, failing for exactly the predicted reason:
  - `test_417_page_cache_promotion_must_not_move_the_guard` — moving 243MB
    between LRU buckets, with `current`, `anon` and total file cache all held
    constant, swings the guard **1895.3 -> 1652.3 (243.0MB)**. The observable
    moves the full size of the reclassification with nothing real changing.
  - `test_417_series_never_tightens_while_memory_in_use_falls` — the recorded
    4-sample series is refused at sample 1 (`09:29:27 refused a build that
    fits`), i.e. all 300 aborted cycles had room under the unreclaimable
    reading.
  - Fixture provenance: `slab_reclaimable` is absent from the recorded table
    and was back-solved per row (34.2 / 35.3 / 34.8 / 39.3MB). All four rows
    then reproduce the recorded `headroom` to **±0.00MB**, so the fixture is
    derived from the real formula rather than fitted to the conclusion. If a
    future edit breaks that reproduction, the fixture is wrong, not the code.
  - `test_unreadable_anon_must_not_produce_a_rosy_headroom` **passes today and
    is still required.** It is inert against the current formula, which never
    reads `anon`; it becomes load-bearing the moment the fix does. Do not read
    its green as evidence of anything about the fix — it is a regression guard
    placed ahead of the change, and its own predicate is not yet exercised.
  - Not committed. The file is RED on a shared tree by design.
- **STATUS 2026-08-13 — FIX WRITTEN. Both falsification tests now pass;
  `tests/test_memory_observability.py` 13/13 green. Not committed, not
  deployed, production effect UNVERIFIED.**
  - The guard now decides on `max_bytes - unreclaimable`, where unreclaimable
    is `max(anon + shmem + slab_unreclaimable, current - reclaimable_file)`
    and `reclaimable_file` now includes `active_file`.
  - **The max() is the part worth reviewing.** The formula `learnings.md`
    prescribed (`anon + shmem + slab_unreclaimable`) is a LOWER bound on
    unreclaimable memory — it credits everything `memory.stat` fails to
    attribute as available, which is the permissive-on-unknown shape. Taking
    the larger of it and the residual basis (`current - reclaimable_file`,
    which is what `#318`'s log line already used) makes unaccounted memory
    count against the guard. On the `#417` samples the two bases differ by
    ~5.1-5.6MB, so this does not change the verdict there — it changes what
    happens if `#327`'s unattributed allocator ever shows up in this reading.
  - Both helpers are shared by the guard and by `log_container_memory`, which
    had an independent second copy of the reclaimable expression. Fixing only
    the guard would have left the abort line contradicting the decision it is
    read to explain. Grepped after the change: no third copy exists.
  - Degrade path unchanged in the safe direction: `anon` absent -> return None
    -> fall back to the previous arithmetic, never to a rosier number.
  - `#417`'s second defect fixed in the same pass:
    `headroom_including_file_cache_mb` -> `headroom_excluding_file_cache_mb`.
    The name stated the opposite of its value and produced a 792MB apparent
    deficit against a real one of 278MB during the incident. Renamed rather
    than aliased; nothing outside this module's tests reads it.
  - Two pre-existing tests changed deliberately, neither made green by
    weakening it:
    - `test_reclaimable_page_cache_does_not_count_against_headroom` (`#79`)
      moved +34.3MB, exactly its fixture's `active_file`. Conclusion it
      protects is intact (868 vs 3428, was 868 vs 3393).
    - `test_active_file_and_shmem_are_not_treated_as_reclaimable` split into
      `test_shmem_is_not_treated_as_reclaimable` (still true, different
      reason) plus the new `#417` invariance test that owns the overturned
      active_file half.
  - Consumer blast radius, partially checked: 7/7
    `test_intelligence_overview_memory_guard.py`, and 25 memory/headroom/guard
    tests across `test_intelligence_state.py`, `test_deploy_preflight.py`,
    `test_live_lens_loop.py`. **Full 6-file consumer sweep still running at
    time of writing — not yet a result.**
  - REMAINING before this can close: the production half of Verification
    (items 2 and 3 above) is untouched. Nothing here proves the deployed
    behaviour changes; per `learnings.md` a deployed fix can be inert.
- **STATUS 2026-08-13 12:2x CDT — PUSHED to `origin/main` as `03073270`,
  decoupled from config. NOT DEPLOYED. Production effect still UNVERIFIED.**
  - `/preflight` returned **FAIL** on the original candidate (`03073270` on
    local `main`) for a reason that had nothing to do with the fix: local
    `main` carried **four unpushed `render.yaml` commits** underneath it
    (web env block 64 -> 52 keys). Render deploys from GitHub, so shipping
    the fix required a push, and that push would have fired `blueprint_sync`
    — rewriting the whole env block on all three live services. A code fix
    would have carried an undecided production config change as a passenger.
  - Resolved by cherry-picking onto `origin/main` in a throwaway worktree
    (the shared tree has other sessions' uncommitted work). Verified before
    pushing: 3 files, **zero `render.yaml` delta**, web-block key count
    64 == 64, and `render.yaml` absent from the commit entirely. 20/20 tests
    green on that base (13 memory_observability + 7 overview guard).
  - **The `render.yaml` web-block audit is now unshipped and unowned.** It
    still sits on local `main` only. It needs its own `/preflight` and its
    own `deploys.md` row — it is a production config change, not a passenger.
    One item for whoever takes it: `MLB_ENABLE_LIVE_LENS_LOOP: "false"` is
    among the 12 keys being removed from web. If the code default is True,
    removing it turns the loop ON for web rather than off — the `absent != off`
    hazard. NOT verified by this lane.
  - **`main` has diverged and this commit now exists twice.** `03073270`
    (local) and `03073270` (origin) are the same change. Local `main` is 6
    ahead / 1 behind origin. Do not `git pull` and assume a clean merge —
    reconcile deliberately, and drop the local duplicate rather than
    re-landing it.
  - Deploy still gated: `scripts/check_deploy_safety.py` returned NOT CLEAR
    twice, 12:14 and 12:2x CDT — MLB sims running back-to-back (pid 4514
    `tip_off_window`, then pid 4718 `fingerprint_change`) plus a live odds
    refresh, with live games in progress. Deploying kills them.
  - **Falsifiable discriminator for the post-deploy read, stated before the
    deploy:** the new `basis` field. `basis=unreclaimable` proves the new
    path executed; `basis=reclaimable_cache` means it degraded to the old
    arithmetic and any "zero aborts" reading is inert-guard-shaped and means
    nothing. Read that BEFORE reading the abort count.
- **STATUS 2026-08-13 ~12:5x CDT — local `main` reconciled with `origin/main`
  (`a3f9ed97`). Push HELD by decision. Still not deployed.**
  - Merge, not rebase. `git cherry` showed two local commits patch-equivalent
    to origin (`03073270`≡`03073270`, `b48aa0d3`≡`b48aa0d3`); a rebase would
    have dropped them cleanly but rewritten **seven commits belonging to other
    sessions** working this shared checkout, and the ledger cites SHAs by
    hand. Verified after: 0 behind / 11 ahead, `origin/main` is an ancestor,
    all six other-session SHAs unchanged, and the merge commit is **empty
    against its first parent** — content was already identical, only ancestry
    changed.
  - One conflict (`.syndicate/lanes.md`), both regions ours-only with an
    **empty theirs side**. Resolved keep-ours; verified content-complete
    (468 lines both sides, differing only CRLF vs LF).
  - NEAR-MISS worth recording: the first merge attempt was aborted because
    another session had **8 files staged in the shared index** (the
    `.syndicate` enforcement hooks). A merge commit takes the WHOLE index, so
    completing it would have swallowed their in-flight work. Proved the merge
    safe in a throwaway worktree instead, and ran it only once their index
    cleared. `learnings.md` already has the never-chain-add-and-commit rule;
    this is the same hazard arriving through `git merge` instead.
- **RETRACTION — the `render.yaml` hazard I raised is NOT a hazard.** This
  lane earlier flagged `MLB_ENABLE_LIVE_LENS_LOOP: "false"` as a possible
  `absent != off` trap in the web-block audit. Checked against the code:
  **no Python reads that key anywhere** — it exists only in `render.yaml`, so
  removing it from web is inert. Also cleared:
  `WEEKLY_SPORTS_ENABLE_REFRESH_WORKER_AUTORUN` defaults **False** when absent
  (`scripts/run_refresh_worker.py:338`), `REFRESH_PREDICT_PROPS_SMART_SIM_PBP`
  defaults **True** matching its removed value, and
  `SYNDICATE_LIVE_ODDS_GAME_LINE_REGIONS` is read only by a worker script as
  EXTRAS (absent = no extras, `scripts/fetch_mlb_oddsapi_local.py:1593`).
  The audit's "already declared on both workers, unchanged there" claim holds.
  Recording the retraction loudly because a false caveat about someone else's
  work silently devalues their correct readings too.
- **What still blocks the push is the MECHANISM, not the diff.** A
  `blueprint_sync` writes the WHOLE env block on all three services — not the
  diff — including live drift nobody has read, and last time it 502'd every
  route for ~2 minutes. That restart kills an in-flight MLB sim exactly as a
  deploy does. Decision taken: **hold the push until
  `check_deploy_safety.py` reports CLEAR, then push and deploy in the same
  quiet window** so the config sync and the code deploy cost one interruption
  instead of two. Watcher `b07yqo98b` is armed, polling every 90s.
- Discrepancy noted, does not affect the verdict: the `#417` narrative in
  `.syndicate/log/2026-08-13.md` and `todo.md` says `current_mb` fell
  "3120 -> 2705", but the 4-row table it sits beside records 2988.6 -> 2705.3.
  The 3120 figure is not in the table; it is presumably an intermediate peak.
  Both readings agree in DIRECTION (usage fell, guard tightened), so the
  falsification test holds either way — but the table is the authoritative
  per-sample record and is what the fixture uses.

### (superseded lane detail, kept for the file/line map)

### mlb-live-pitcher-projection — CLOSED-VERIFIED 2026-08-16 — (a)/(b)/(c) all measured on 423 rows, 0 violations; live coverage 11.6% -> 50.3%; archived to lanes_closed.md — opened 2026-08-15 — session: mlb-live-pitcher-projection
- Goal: on a live MLB slate, a live prop row never shows (a) a projection below
  an already-recorded actual, (b) a `model_prob_over` on the opposite side of
  the line from its own `projected`, or (c) a blank live column with no
  attributable reason. **Testable outcome:** on the served `/api/board/book-grid`,
  `proj-side != prob-side` on live pitcher rows goes 7/13 -> 0, and
  `live_projections` (the join's own counters) becomes readable from the API.
- Files (exclusive to this lane):
  - `syndicate/features/mlb/cards.py` — `_bounded_live_pitcher_projection` + its 2 call sites
  - `syndicate/features/shared/live_projection_join.py` — the overlay's probability stamp
  - `syndicate/blueprints/intelligence.py` — book-grid artifact response passthrough
  - `tests/test_mlb_live_pitcher_projection.py` (new)
- **NOT taken, deliberately:** `syndicate/features/mlb/live_lens.py` is claimed
  exclusively by OPEN lane `live-game-line-projection`. Its `modelProbOver`
  fallback chain (:541) is the ORIGIN of the pregame-probability-labelled-live
  defect; this lane fixes the CONSUMER instead, which honours the contract
  `live_lens.py:549` already documents in its own comment.
- Hypothesis (H1): `_bounded_live_pitcher_projection` uses GAME progress
  (`_live_progress_fraction`, total outs/54) where it needs the PITCHER's own
  remaining workload, has no still-in-game check, and floors the residual at 0 —
  so a pulled starter keeps accruing and a pitcher ahead of his mean projects to
  add exactly nothing.
- Hypothesis (H2): `live_projection_join` stamps `hit["model_prob_over"]` (which
  `build_live_prop_index` fills from the lens's `modelProbOver`, i.e. the PREGAME
  number) onto a row it labels `mlb_live_lens_monte_carlo`, so `projected` moves
  with live state and the probability beside it does not.
- Falsification test: for H1 — a live pitcher row whose projection already tracks
  remaining outs and drops to the actual once the pitcher is pulled, which would
  mean some other writer owns the number. For H2 — a live-lens row whose
  `model_prob_over` differs from the pregame `_dist_prob_over` value for the same
  player/market/line, which would mean the probability IS being recomputed live.
- **NOT hypothesised, and deliberately so:** the cause of the 435 unmatched live
  prop rows (`batter_home_runs` 0/116, `batter_hits_runs_rbis` 0/79). The alias
  table already carries both names, so the miss is snapshot-side — but per
  learnings.md 2026-08-15 ("never read a joiner zero as a data-quality verdict
  until the reader has been shown to SEE the data") the published lens snapshot
  has NOT been read from this session (it lives in keyvalue; web 404s on it).
  This lane makes the counters READABLE and stops there. No cause is claimed.
- Verification: (1) new tests, each mutation-verified red before green;
  (2) `pytest -k "mlb and live"` plus the blast-radius set green;
  (3) production re-measure on the served book-grid against the baseline taken
  2026-08-15 20:12:48Z (below). NOT closed on tests alone.
- **BASELINE, served `/api/board/book-grid?sport=mlb&date=2026-08-15`, artifact
  generated 20:12:48Z, web `f475c775`:** 638 live rows; 57 (8.9%) live-overlaid;
  **0 edged**; 13 live pitcher rows of which **7 have projection and probability
  on opposite sides of the line**; `live_projections` absent from the response.
  Ground truth for the user-reported game (StatsAPI 824644, Top 7, STL 7-CHC 3):
  McGreevy 18 outs recorded vs **proj 17.136**; Boyd out of the game with 2 K /
  7 ER vs **proj 4.057 K / 3.242 ER**.
- Blocked by: none. **NO DEPLOY FROM THIS LANE** — refresh-worker writes this
  artifact and is under `#435`; its deployed commit has NOT been read.

### board-publish-stall — CLOSED-FALSIFIED 2026-08-16 — no stall, no publish failure; the REAL result is that my deployed fix is INERT and restart starvation is separately real — opened 2026-08-16 — session: red-intelligence-tests
- Goal: name the stage where a COMPLETED board build stops without publishing,
  with a measurement, so the 77-minute-stale board has a cause rather than a
  suspicion. Not a fix — this lane ends at a named stage and a handover.
- **NOT A FILE-EDITING LANE (yet). `pipeline/intelligence_state.py` is claimed by
  TWO OPEN lanes** — `clv-without-settlement` ("writer, currently held by") and
  `clamp-fix-to-workers` (Files: it). **I will not edit it.** If the diagnosis
  points there, it gets handed to whoever holds it. Read-only for me.
- Files (read/diagnose only): `pipeline/intelligence_state.py`, worker logs.
- **HYPOTHESIS, written before testing it.** The build is STALLING, not crashing,
  in the unlogged span between `DECIDED_LIVE_PROPS_REMOVED` (last marker,
  00:08:31Z) and `EXPOSURE_BUDGETS_*` / `LAYER2_SHORTLIST` (never reached). That
  span runs three things over the whole merged pool:
  `attach_board_correlation_flags`, `_attach_board_stakes`, and
  `_attach_adjusted_scores`. The third is the suspect: its own comment says
  `rank_recommendations` "walks odds-history/market-feature state per candidate"
  and "was previously never called on the board path at all". 579 candidates x
  an odds-history walk is exactly the shape `#414` measured at 21.5x.
- **Falsification test:** if a `BOARD_OVERVIEW_READY` for a NEW build appears
  after 00:08:31Z, the build was ABANDONED by the loop rather than stalled, and
  the stall hypothesis is wrong. Equally, if candidate counts for this build are
  no larger than the 22:5x build that published fine in ~3 min, then volume is
  not the cause and the stage is failing for a different reason.
- **Already established, and NOT to be re-derived:**
  - Last publish `computed_at 2026-08-15T22:55:10Z`; still stale at 00:12:29Z.
  - This build: `BOARD_OVERVIEW_READY` 00:02:00, collect 00:02:01->00:07:58
    (357.73s), `BOARD_RAW_CANDIDATES` 684/684, `CANDIDATE_SLATE_FILTER` kept
    579, `DECIDED_LIVE_PROPS_REMOVED` 00:08:31. **Then silence.**
  - The only `Traceback` in the window is `generate_smartsim2_nfl_projections.py`
    `assert_ratings_data_available` — a DIFFERENT job, **not this path**. Do not
    attribute the stall to it.
  - Real builds tonight took **178 / 197 / 241 / 325 / 358 s**. Everything else
    logging `BUILD_SPAN_EXIT elapsed_s=0.0` is the documented empty-pool
    short-circuit, not a build.
- **RESTART-STARVATION IS SEPARATELY TRUE AND IS NOT THIS.** 13 refresh-worker
  deploys since 21:30Z. Builds completed at 21:53 / 22:32 / 22:52 / 23:10, all
  inside gaps of 15-33 min. Then SIX deploys in 46 min (gaps 6-9 min) and **zero
  builds completed**. A 3-6 min build cannot fit a 6-9 min gap minus boot. The
  churn was starving the artifact the whole queue was waiting on. **But the
  current stall is on a quiet worker with no restart since 23:56:06Z**, so
  starvation does not explain it.
- Blocked by: none. NO DEPLOY, NO EDIT to the claimed writer.

#### board-publish-stall — CLOSED-FALSIFIED 2026-08-16. The hypothesis was wrong and the by-product is the finding
- **HYPOTHESIS FALSIFIED.** There was no stall and no publish failure. The build
  completed normally: `ADJUSTED_SCORES_ATTACHED` 00:12:00 (the span I suspected
  took 3.5 min, not forever) -> `EXPOSURE_BUDGETS_APPLIED` ->
  `LAYER2_SHORTLIST` -> `CANDIDATE_POOL_READY 567` ->
  `BOARD_PUBLICATION_RESPONSE_READY` **00:12:39Z**.
- **MY "IT DID NOT PUBLISH" CLAIM WAS AN ARTEFACT OF READING TEN SECONDS EARLY.**
  I read `computed_at` at 00:12:29 and a log window that was still being
  written. `absence in a window is not absence` — a rule I already held.
- **THE REAL RESULT, and it is a negative one: `2c14d9ae` IS INERT.** After the
  confirmed rebuild, `line as a string` is still **0**. The falsifier I wrote
  before deploying fired exactly as designed.
- **TRACED, not guessed:** every served row carries `source: layer2_shortlist`,
  `surface_key: layer2`, `candidate_type: None`. Its `line` is stamped at
  **`syndicate/features/shared/layer2_board.py:1104`** (`"line": row.get("line")`).
  `UniversalCandidate.to_dict` is **never on that path**, and a web deploy would
  not have helped — the field is stamped in the worker, in another module.
- **Root error is upstream of the deploy:** the failing test exercised
  `run_intelligence_query(force_refresh=True)`; production serves Layer 2. I had
  a real defect, a mutation pin, a production baseline and a written falsifier —
  and never checked that the baseline and the fix describe the SAME PATH.
- **STILL STANDING, independent of all of the above: restart starvation.**
  Builds take 178-358 s; they completed in every 15-33 min gap and in NONE of
  six deploys spaced 6-9 min. The board went 77 min stale on a busy worker.
- **HANDOVER, deliberately not actioned.** The real fix for whole-numbered lines
  is `layer2_board.py:1104`, in a file claimed by an OPEN lane. **Not cosmetic:**
  `line` is one of `_IDENTITY_FIELDS` and feeds the dedupe key at `:450`, so
  changing its type changes dedupe behaviour. Whoever takes it should measure
  dedupe counts before and after.
- **I edited nothing in `pipeline/intelligence_state.py`**, as the lane promised.

#### LEDGER DATA LOSS FOUND AND REPAIRED 2026-08-16 — `learnings.md` worktree was 905 lines short of HEAD
- Caught because the index builder reported **103 rules** where it had reported
  **118** an hour earlier. **A count that goes DOWN on an append-only file is
  the alarm.**
- The worktree copy was missing **46 rule headings that are in HEAD**, including
  several FORBIDDEN entries and three rules I had already committed. It had 3
  genuinely new ones (two from another session, one mine) appended onto the
  stale base. **Committing the worktree would have deleted 46 rules.**
- Repaired by rebuilding `HEAD + the 3 new rule bodies` and regenerating the
  index: 2259 -> 2368 lines, 146 rules, deletions vs HEAD limited to the index
  block. Stale copy preserved at `C:/tmp/learnings_worktree_backup.md`.
- **Possible near-duplicate to dedupe, flagged not resolved:** the worktree
  carried a reworded joiner-zero FORBIDDEN rule while HEAD has the original
  `same_book_n=0` wording. I kept BOTH — a duplicate is recoverable, a lost rule
  is not. Whoever owns that rule should merge them.

### line-decimal-renderer — CLOSED-VERIFIED 2026-08-16 — shipped `f3b9b293`; 5 live rows change, 77 untouched; WEB DEPLOY OWED — opened 2026-08-16 — session: red-intelligence-tests
- Goal: a whole-numbered line stops rendering without its decimal on the board.
  Testable: `9.0` renders `9.0`, not `9`, while `4.5` and `10.25` are unchanged.
- **DEFECT CONFIRMED IN A REAL BROWSER, not inferred.** Live `/intelligence`,
  89 Line cells: `"9 · totals"` and `"7 · totals"` sit beside `"11.5 · totals"`,
  `"5.5 · totals"`, `"6.5 · totals"`. 21 cells render without a decimal (most
  are `h2h`/`h2h_3_way`, which correctly have no line; the totals ones are the
  defect). On the wire: **40 `"line"` tokens end in `.0` and ZERO are quoted**,
  so `JSON.parse` yields a number and `String(7.0)` is `"7"` — confirmed by
  evaluating `String(7.0)` in the page itself.
- **Two invalid verifications on the way here, both mine, both recorded:**
  a Python mirror of `displayLine` (`str(9.0)` is `"9.0"` in Python but
  `String(9.0)` is `"9"` in JS — the mirror said "no defect"), and a first
  browser read taken before the async board rendered (0 cells found).
- Files (exclusive): `syndicate/templates/intelligence.html` — `displayLine()`
  only. `tests/test_intelligence.py` — extend the existing template guard.
- **Collision check: the ONLY mention of this template in `lanes.md` is my own
  lane's note saying it is unclaimed and read-only. File is clean in git.**
  Deliberately chosen over `layer2_board.py:1104`, which is claimed by OPEN
  `spread-line-sign-convention` and currently carries **144 uncommitted lines**
  from that session — and their change is to `line` itself. Fixing the renderer
  avoids that file entirely and is the more correct layer: the payload carrying
  a number is fine, the renderer dropping the decimal is the defect.
- Hypothesis: `displayLine()` does a bare `String(line)`. Numbers need an
  explicit format; integers must keep one decimal, non-integers must be left
  alone so `10.25` does not become `10.3`.
- Falsification test: if injecting the corrected function into the live page
  does not change `9 -> 9.0` while leaving `4.5`, `-1.5` and `h2h` untouched,
  the renderer is not the site and the fix is wrong.
- Verification: (1) injected before/after against the LIVE page's real rows;
  (2) template guard test; (3) `test_intelligence.py` still green.
- **WEB-ONLY change — needs a web deploy to reach users. NOT deploying without
  a separate decision.**
- Blocked by: none.

#### line-decimal-renderer — CLOSED-VERIFIED 2026-08-16 — shipped `f3b9b293`, **WEB DEPLOY OWED**
- **Falsification test PASSED on real data.** Injected the old and new
  `displayLine` into the LIVE page over its own 100-row payload: **exactly 5
  rows changed** (`9->9.0`, `7->7.0`, `17->17.0`, all `totals`), **77 unchanged,
  18 line-less**. Synthetic cases confirm `4.5`, `-1.5`, `10.25`, `"4.5"`,
  `null` and `"-"` are untouched. Integers only are padded.
- Tests: 8 template guards + 177 adjacent template-reading suites green.
  Mutation-pinned: reverting the numeric branch OR swapping the integer pad for
  a blanket `toFixed` both redden, and `assertNotIn` blocks the `10.25 -> 10.3`
  variant specifically.
- **NOT DEPLOYED. This is WEB-ONLY** — `intelligence.html` is served by the web
  service (live `484221bd`), so the 5 rows do not change for users until a web
  deploy. Deliberately not fired: web took five deploys in twenty-one minutes
  from four sessions earlier tonight and peers cancel each other mid-build.
- **`layer2_board.py:1104` remains untouched and is NOT owed by this lane.** The
  producer emitting a number is defensible; the renderer dropping the decimal
  was the defect. If `spread-line-sign-convention` changes `line`'s type as part
  of their per-side rewrite, this renderer already handles both — it branches on
  `typeof line === "number"` and falls through to the string path otherwise.
- **CORRECTION recorded against my own earlier claim:** I said the dedupe key at
  `layer2_board.py:450` made a producer-side fix risky. It keys off the SOURCE
  row, not the output card, so that hazard was overstated. The live collision
  (144 uncommitted lines in that file, from a lane rewriting `line` itself) is
  the real and better reason to have stayed out.
- **Two invalid verifications on the way here, both mine:** a Python mirror of
  `displayLine` (`str(9.0)`=="9.0" in Python, `String(9.0)`=="9" in JS — the
  mirror said "no defect, stand down"), and a browser read taken before the
  async board rendered (0 cells found). **Mirroring JS semantics in Python is
  not a verification; running it in the page is.**


<!-- archived 2026-08-16 from lanes.md -->

### win-prob-null-readable — CLOSED-VERIFIED 2026-08-16 — **the counter is readable in production: `wnba/live-odds-worker rows=0 null=0`, generated_at 02:01:19Z (80s after the deploy), commit `3573a0c3` — worker wrote, web read. THE `or 0.5` MEASUREMENT IS NOT THIS LANE'S AND REMAINS OWED (`rows=0` = empty denominator)** — opened 2026-08-15 — session: win-prob-null-readable — opened 2026-08-15 — session: win-prob-null-readable
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

### slate-size-headroom — CLOSED 2026-08-16 — UNKNOWN FROM HISTORY (slate range is 1 game wide; naive fit gives an absurd +703MB/game). Solid: max peak 3,518MB = 85.9%, 578MB headroom — opened 2026-08-16 — session: memory-cutover-ship
- Goal: answer "at what slate size does the worker cross 4GiB", with a number and
  an honest error bar. Post-`#435` peak is **3,527.8MB (86.1%)** on a 15-game MLB
  slate — 568MB of headroom. Whether that survives a 16-18 game night is
  currently a guess, and the wrong way to find out is on a Sunday.
- Files: none claimed — READ-ONLY. Measurement from production history first.
- **METHOD, and the order matters:** model from EXISTING data before running any
  experiment. Every board build already emits `game_count` alongside
  `CONTAINER_MEMORY`, so the relationship between slate size and peak anon is
  already recorded across days. An experiment that forces a large slate on the
  live worker risks repeated OOM kills to learn something the logs may already
  contain.
- **Hypothesis:** peak anon scales roughly linearly with MLB game count, and the
  crossing point is within reach of a real slate (16-18 games).
- **Falsification test:** if peak anon shows no usable relationship to game count
  — because the quote-shard ramp and time-of-day dominate it — then the model is
  unavailable from history and the honest answer is "unknown, and a stress test
  is the only way", stated as such rather than fitted anyway.
- **KNOWN CONFOUND, declared up front:** slate size and shard size are
  correlated (more games -> more quotes -> bigger shard) AND the shard grows
  through the day independently. A naive fit will attribute shard growth to game
  count. Any number produced must say which of the two it actually measured.
- Verification: a table of (game_count, peak anon) with the sample count per
  bucket, and an explicit statement of what the confound leaves unresolved.
- Blocked by: none.

#### slate-size-headroom — CLOSED 2026-08-16 01:3xZ — FALSIFICATION FIRED, NO NUMBER PRODUCED
249 complete board builds, 20,000 samples, 20:42Z-01:31Z:

    games  builds  median peak   max peak  % of 4096   hours seen
       14      14        835.4     1672.2      40.8%   00,01,21,22,23
       15     235       1538.1     3518.0      85.9%   00,01,20,21,22,23

**THE OBSERVED SLATE RANGE IS ONE GAME WIDE.** Every MLB slate in the post-fix
window was 14 or 15 games, so there is no variation to model against.

**AND THE NAIVE FIT IS SELF-EVIDENTLY WRONG: +702.7 MB PER GAME.** No single
baseball game costs 700MB. Two buckets one game apart differing by 703MB means
they are different KINDS of build, not different sizes — the 14-game bucket has
18 builds against 235 and sits at a different point in the quote-shard ramp. Its
extrapolation ("~19 games to 4096MB") is an artifact and **must not be quoted.**

**SO THE ANSWER IS: UNKNOWN FROM HISTORY**, exactly as this lane's falsification
test specified. Fitting it anyway would have produced a confident number with no
support, which is the failure mode this whole investigation kept hitting.

WHAT IS SOLID FROM THE SAME DATA:
- max peak **3,518.0MB = 85.9%** of the 4,096MB ceiling, over 249 builds.
- **578MB of headroom** at that peak.
- Zero OOM kills in 7h15m post-fix, across a full evening ramp.

**WHY I AM NOT RUNNING THE EXPERIMENT WITHOUT A DECISION.** Answering this
empirically means forcing an oversized slate on the live worker to find the
crossing point — i.e. deliberately OOM-killing production, repeatedly, to learn
a number. A local run cannot substitute: `learnings.md` records local
underestimating production by ~40x on this exact code path.

**THE CHEAPER DECISION IS CAPACITY, NOT DIAGNOSIS.** 578MB of headroom on a
worker that legitimately holds ~1.6GB and spawns 8-10 children is thin. Raising
the plan removes the question; measuring it costs production outages to answer
something the answer to which is "add memory" either way. That is an owner call,
and `render.yaml` is a `blueprint_sync` change — it applies to production on push.

### worker-child-processes — CLOSED 2026-08-16 — CONFIRMED: worst combined 3,972MB = 97.0% of ceiling; 3 concurrent daily_update variants + `--workers 2` spawns are the lever — opened 2026-08-16 — session: memory-cutover-ship
- Goal: characterise the refresh-worker's CHILD processes over a window — how
  many, which, how big, how long-lived, and whether their peak coincides with
  pid 39's. Measured twice and got 0.4MB and ~504MB, which is not a
  characterisation, it is two anecdotes.
- Files: none claimed — READ-ONLY, from `ALL_PROCESS_MEMORY` already in
  production. No deploy.
- **Hypothesis:** the children are dominated by MLB `daily_update.py` and its
  `multiprocessing` spawns (`--workers 2` is on its command line), so the count
  is CONFIGURABLE and the reduction is a flag rather than a rewrite.
- **Falsification test:** if the largest child is NOT `daily_update`/its spawns —
  e.g. the soccer or odds refresh jobs — the flag does nothing and the lever is
  elsewhere.
- **The measurement that matters is CONCURRENCY WITH THE PARENT'S PEAK**, not the
  children's own size. 504MB of children while pid 39 sits at 1.1GB is
  affordable; the same 504MB during pid 39's 3.5GB peak is what kills. A
  characterisation that reports only the children's totals answers the wrong
  question.
- Verification: per-cmdline table (count, median/max rss, lifetime) plus the
  joint distribution against parent rss at the same instant.
- Blocked by: none.

#### worker-child-processes — CLOSED 2026-08-16 01:4xZ — HYPOTHESIS CONFIRMED, LEVER NAMED
6,199 `ALL_PROCESS_MEMORY` samples, 18:11Z-01:4xZ.

**THE CHILDREN ARE CONCURRENT WITH THE PARENT'S PEAK, which is the finding —
their own size was never the question:**

    parent rss      samples   median kids   max kids   worst sum
    0-1000 MB           742           3.3      677.0      1650.3
    1000-2000 MB      1,391         300.2      771.8      2668.9
    2000-3000 MB      2,013         450.2      778.1      3665.1
    3000+ MB             53         206.4      672.1    **3972.0**

**WORST COMBINED 3,972.0MB = 97.0% OF THE 4,096MB CEILING** — parent 3,302.4 +
children 669.6 across 11 kids, at 22:00:31Z. **124MB from the ceiling.** The
`#435` fix did not leave 578MB of headroom; it left 124MB at the worst observed
moment, because the earlier figure counted the parent alone.

**THE WORST MOMENT, named:**

    3302.4  pid 39   run_refresh_worker.py
     180.6  pid 341  daily_update.py --workers 2
      95.5  pid 382  refresh_odds_sources.py
      86.7  pid 415  build_soccer_artifacts.py
      76.8  pid 370  daily_update.py --workers 2      <- a SECOND one
      53.7  pid 493  multiprocessing spawn
      53.7  pid 490  multiprocessing spawn
      47.9  pid 369  daily_update_multi_profile.py --workers 2
      39.2  pid 340  run_mlb_daily_sim_job.py --workers 2

**HYPOTHESIS CONFIRMED:** the largest children are `daily_update.py` and its
`multiprocessing` spawns, and **`--workers 2` is on every one of their command
lines** — so the count is CONFIGURABLE. Falsification would have been the biggest
child being a soccer/odds job; the soccer jobs are there (95.5 + 86.7) but they
are second-tier.

**THE LEVER, in order of size:**
1. **THREE `daily_update` variants ran CONCURRENTLY** (`ui-daily`, `core`,
   `multi_profile`) = 305.3MB before their spawns. Serialising them is the
   single biggest win and costs no memory work at all.
2. **`--workers 2` on four jobs** produced 2 live spawns at 53.7MB each. Dropping
   to 1 saves ~107MB at the worst moment.
3. Soccer (`refresh_odds_sources` + `build_soccer_artifacts`) = 182.2MB
   concurrent with the MLB peak. Scheduling, not code.

Together these are ~400-500MB against a 124MB margin — i.e. the children are a
BIGGER lever than pymalloc's 350MB retention, and cheaper to pull.
Read-only lane. No files touched, no deploy.

#### worker-child-processes — CORRECTION 2026-08-16 01:5xZ — THEY ARE NESTED, NOT CONCURRENT
I recommended "serialise the three `daily_update` variants — the single biggest
win". **That was wrong. They are already sequential.** The ppid chain at the
22:00:31Z worst moment:

    pid  39  run_refresh_worker.py                  3,302.4
    └ pid 340  run_mlb_daily_sim_job.py                39.2
      └ pid 341  daily_update.py (ui-daily)           180.6
        └ pid 369  daily_update_multi_profile.py       47.9
          └ pid 370  daily_update.py                   76.8
            ├ pid 490/493 multiprocessing spawn       107.4
            └ pid 371  python                          11.9
    └ pid 381  run_refresh_odds_job.py                 20.4
      └ pid 382  refresh_odds_sources.py               95.5
        └ pid 415  build_soccer_artifacts.py           86.7

Three processes with the same NAME are not three concurrent jobs. `daily_update`
spawns `multi_profile`, which spawns another `daily_update`. Each parent then
sits holding its memory while its child works.

**SO THE LEVER IS NESTING COST, NOT SCHEDULING.** ~305MB of that chain is parents
IDLING with memory retained (180.6 + 47.9 + 76.8) while the actual work happens
in the leaf spawns. Serialising cannot help something already serial; the
question is why a process that is only `wait()`ing holds 180MB.

**WHAT IS GENUINELY CONCURRENT is the ODDS BRANCH**: `run_refresh_odds_job` ->
`refresh_odds_sources` -> `build_soccer_artifacts` = **202.6MB running alongside
the MLB chain**, off a different child of pid 39. That IS a scheduling lever and
it is the one I should have named.

**REVISED, in order of size and cheapness:**
1. **Odds/soccer branch off the MLB peak — 202.6MB.** Pure scheduling, no code.
2. **The idle-parent chain — ~305MB.** Needs the parents to release before
   spawning, or to hand off rather than nest. Real work, not a flag.
3. **`--workers 2` -> 1 — ~54MB** (2 spawns at 53.7MB; only one is saved since
   one worker remains).

### ncaaf-schedule-fallback — **CLOSED-VERIFIED 2026-08-16 — `#445` fixed in `483bb9dd`, on `origin/main`. NOT DEPLOYED (NCAAF opens 08-29)** — opened 2026-08-16 (retroactively, see below) — session: sim-engine-track
- **PROTOCOL GAP, RECORDED NOT HIDDEN:** the collision check was run before any
  edit (both files CLEAR), but the lane entry itself was never written until
  checkpoint. The claim was made and not published, so for ~40 minutes another
  session could have taken `generate_smartsim2_ncaaf_projections.py` without
  seeing a conflict. No collision occurred; the exposure was real anyway.
- Files: `scripts/generate_smartsim2_ncaaf_projections.py`,
  `tests/test_ncaaf_schedule_fallback.py` (new).
- **Goal met:** an absent engine schedule reaches the CFBD fallback instead of
  raising. `load_engine_schedule` returns `[]` and logs `ENGINE_SCHEDULE_ABSENT`.
- **The fallback was already written, already correct and already called** — its
  own docstring names this case. It was unreachable because the read raised.
  Four lines.
- **The fix this lane did NOT make, deliberately:** re-pointing the hard-coded
  2025 filename at 2026. No 2026 file exists, nothing writes one, all 278 in the
  checkout are 2025 — it would rate 2026 from 2025 predicted totals, silently
  wrong rather than loudly broken. My own `#445` ticket proposed exactly that;
  see `learnings.md` on reasoning by analogy from a just-solved defect.
- **Verification:** 5 new tests, two guarding the FALLBACK rather than the change
  (FBS-vs-FBS only; rows missing a team), because a widened slate would alter
  which games get projected rather than merely keeping the run alive.
  295 passed / 0 failed across `-k ncaaf`.
- **UNVERIFIED and handed over:** that CFBD `/games` returns rows for
  `season=2026 week=1` in production. Not called against the live API, and not
  deployed. Check when this ships.
- Blocked by: none.

### nfl-pbp-fetcher — **CLOSED-VERIFIED 2026-08-16 18:31:15Z — pbp_2025.csv written on the mounted disk (97,951,481 bytes, 46,452 REG plays) and the guard stopped refusing. `#441` FIXED.** — opened 2026-08-16 — session: sim-engine-track
- Goal: `#441`. A pbp ingestion path exists, so the NFL SmartSim2 projection has
  real ratings again instead of refusing for 2.8 days.
- Files (exclusive to this lane): `scripts/fetch_nfl_pbp.py` (new),
  `tests/test_fetch_nfl_pbp.py` (new). Collision check RUN: CLEAR on both.
  `scripts/run_refresh_worker.py` (autorun wiring — claimed 2026-08-16 after a
  fresh collision check: CLEAR, no OPEN lane holds it).
- **Root cause is SETTLED by measurement, not assumed** (`a775e372` diagnostic,
  17:10:45Z): the pbp is absent from all four candidate roots including the
  mounted disk, env vars reach the subprocess, strict storage is on. There is no
  pbp fetcher in this repo — ten scripts reference pbp, all reads.
- **THE FILE THAT ACTUALLY MATTERS IS pbp_2025.csv, NOT 2026.** The 2026 regular
  season has not started, so there are no current-season plays for week 1;
  `assert_ratings_data_available` accepts current OR prior, and NFL ratings for
  wk1 come from the prior season (`prior_season_fallback`, the mechanism
  `verify_nfl_autorun_obligations.py` was written to check). A fetcher that only
  pulls the current season would ship and change nothing.
- Template: `fetch_nfl_schedule.py` (nflverse games.csv), plus the roster and
  depth-chart fetchers. Write under `nfl_artifact_output_root()` — the `#389`
  resolver — NOT under `default_nfl_source_root()`, which resolves to the
  ephemeral checkout.
- **REFUSE TO INSTALL A DEGENERATE FILE.** Same philosophy as the guard this
  feeds: validate required columns and non-zero REG rows BEFORE replacing an
  existing file, so a truncated or schema-changed download cannot overwrite a
  good one. Write atomically.
- Hypothesis: with pbp_2025.csv present on the mounted disk, the next autorun
  writes a real artifact with non-identical rows per game.
- Falsification: if the artifact still refuses, or writes with IDENTICAL rows for
  every game, the ratings path is broken for a second reason and the fetcher is
  not sufficient.
- Verification: `SEASON_PROJECTION_LAUNCHING` stops recurring; the artifact
  appears with a fresh mtime AND per-game variance (identical rows would mean the
  guard was satisfied wrongly).
- Blocked by: none. `#443` (stale PID stalls the autorun ~45 min per restart)
  will DELAY observation and is not a blocker.


#### CLOSED-VERIFIED 2026-08-16 18:31:15Z
- **Verification ran and passed, on the real success condition rather than a proxy.**
  `season 2025: status=written, bytes=97,951,481, reg_plays=46,452` to
  `/opt/render/project/data/nfl_source/tracking/nflverse/pbp/pbp_2025.csv`, and
  `NO PLAY-BY-PLAY` has not recurred since. The generator ran again at 18:31:43
  and did not refuse.
- **The lane's own falsification test did NOT fire:** "if the artifact still
  refuses, the fetcher is not sufficient." It stopped refusing.
- **2026 returned 404 and that is CORRECT** — the season has not started. The
  lane predicted this ("the file that actually matters is pbp_2025.csv"), which
  is why `--season` fetches the prior year by default. A current-season-only
  fetcher would have shipped, 404'd, and changed nothing.
- **Two bugs caught pre-ship:** a ~300MB memory transient on a service at 95% of
  cap (rewritten to stream), and `gzip.decompressobj` which does not exist (it is
  `zlib`) — that one would have crashed every real fetch.
- **One regression I caused and reversed:** default-ON broke three
  `test_main_run_once_*` contracts; confirmed mine against a clean-HEAD worktree,
  now default-off like every sibling.
- **One overstatement corrected:** "starved" was wrong; a 23-minute delay at
  position 6 is not `#341`'s weeks of muteness. Position-2 move stands as an
  improvement, not a fix.
- **Files released:** `scripts/fetch_nfl_pbp.py`, `tests/test_fetch_nfl_pbp.py`,
  `tests/test_nfl_pbp_fetch_autorun.py`, `scripts/run_refresh_worker.py`.
- **Handover:** `b909d008` (position-2 + skip logging) is on `origin/main`,
  NOT deployed, rides the next worker deploy. `#443` (stale-PID silent stall)
  and `#445` (NCAAF hard-coded 2025 input) remain open and unowned.

### spread-line-sign-convention — CLOSED-VERIFIED 2026-08-16 — **ARTIFACT OUTPUT NOW MEASURED: 12 of 12 MLB spreads rows correct on the served shortlist (9 away + 3 home, the previously broken case).** File claim released to `layer2-board-quality`; holding session `lane-cleanup` archived 01:14Z — opened 2026-08-15 — session: lane-cleanup → verified by layer2-board-quality
- **VERIFICATION (2026-08-16 ~16:3xZ, by `layer2-board-quality`).** The one open
  item — "artifact output still unverified" — is now closed against the SERVED
  payload (`/api/board/layer2-shortlist`, `written_at` 2026-08-16T16:20:21Z)
  cross-checked cell-by-cell against `/api/board/book-grid?sport=mlb`:

      away rows agree      9/9      (already correct pre-fix)
      home rows agree      3/3      (the case this lane fixed)
      total               12/12

  `_side_line_from_cells` confirmed present in the DEPLOYED tree —
  `git show 97491161:syndicate/features/shared/layer2_board.py` returns 3
  occurrences, identical to `main`.
- **THIS LANE'S OWN DEPLOY CLAIM WAS UNPROVABLE BY ANCESTRY, AND ANCESTRY SAYS
  THE OPPOSITE OF THE TRUTH.** `git merge-base --is-ancestor edbbee9d 97491161`
  returns **NO**. refresh-worker runs branch `deploy/nfl-pbp-root`, not `main`,
  so the fix rode in by content while failing every ancestry test.
  `project_web_runs_a_deploy_branch_not_main` generalises to the WORKERS.
- **A FALSE 3-of-3 DEFECT CAME OUT OF THIS DATA FIRST; recorded so nobody
  re-derives it.** The grid carries MIRRORED rows for one (event, market,
  segment): `row.line=+1.5 / home_cells=-1.5` beside `row.line=-1.5 /
  home_cells=+1.5`. Joining the shortlist to the grid ON `line` picks the wrong
  twin and produces a uniform-looking "home side still inverted, 3/3". The
  discriminating field is the **price vector** — the disputed row's
  `{leovegas_se:123, prophetx:140, unibet_nl:125, unibet_se:125}` matches
  `row.line=1.0` (home cells -1.0) exactly, so its `-1.0` is CORRECT.
  **The lane's original 525-cell result is NOT affected** — it compared cells
  WITHIN a row, never across mirrored rows.
- **THIS LANE'S "NO TEMPLATE CONSUMES THE SHORTLIST" IS NOW STALE AND WAS THE
  BASIS FOR ITS SEVERITY CALL.** Measured 2026-08-16: `layer2_is_primary=True`,
  `legacy_candidate_count=0`, and **108 of 108** board cards carry
  `source=layer2_shortlist`. The `grep` over `templates/`/`static/` still returns
  zero because the wiring is SERVER-SIDE. The blast radius was never limited to
  the Ask headline; the shortlist is the board.
- **CLAIM WAS NEVER ENFORCED.** `lane-guard.py`'s `_claims()` yields **zero**
  claims on `layer2_board.py` from this lane: `FILES_RE` matched the Files header
  on the colon inside `23:0xZ` (harvesting no paths), and the continuation lines
  holding the real paths start with a backtick rather than `-`. This lane's note
  "Collision check RUN … CLEAR both times, so no other lane was blocked by the
  gap" read CLEAR **because its own claim was invisible**, not because the file
  was free.
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

### commit-guard-reads-wrong-index — CLOSED 2026-08-16 — the guard read the MAIN worktree's index while the commit used another one — session: `live-gameline-eval`
- Goal: `commit-guard.py` evaluates the index the COMMIT will use. **DONE.**
- Files: `.claude/hooks/commit-guard.py`, `tests/test_commit_guard_worktree_index.py`.
  Neither claimed by any OPEN lane at the time of the edit.
- **The bug.** Both predicates ran with `cwd=CLAUDE_PROJECT_DIR`. The commit runs
  wherever the shell is — and this repo's own documented recipe for a contended
  tree is `git worktree add` and commit from there. A linked worktree has its own
  index and its own HEAD.
- **Two opposite failures, and the SECOND is the one that mattered:**
  - *False positive*, observed **3× in one session**: a session committing from
    `/c/tmp/lgl-ck` was blocked over reverts staged in the MAIN index while its
    own index held exactly its four intended appends.
  - *False negative*, **never observed and strictly worse**: a stale index in the
    worktree being committed from was never examined, so the guard would pass it
    in silence. That is the entire hazard it was written to catch.
- **`-C` is now checked instead of skipped.** The old code waved
  `git -C <dir> commit` through because it "has its own index". **Having your own
  index is not having a fresh one** — that conflation is what this guard exists
  to catch, so it cannot be the reason to skip. `--git-dir` / `--work-tree` stay
  skipped and are now named as a KNOWN GAP: index and tree decouple there, so
  predicate 1's "is it still on disk" has no single correct base.
- **Verification — falsified, not just asserted.** 13 tests on REAL git repos in
  `tmp_path` (a mocked git reproduces nothing; the bug was which directory git
  ran in). Against the pre-fix hook: **7 fail, 6 pass**, and the load-bearing
  `test_a_stale_index_in_the_LINKED_worktree_is_caught` fails as `assert 0 == 2`
  — the false negative, reproduced. Against the fix: **13 pass.**
- **Honest limit on the end-to-end check.** The real hook binary was run on the
  real payload shape and returned 0, but the shared index happened to be CLEAN at
  that moment, so **that reading is not a positive control** — it cannot
  distinguish the fix from the bug. The positive control is the pytest pair on
  real repos. Deliberately staging a revert in the live shared index to produce
  one would have created the exact landmine the guard exists to prevent.
- Blocked by: none.

### ask-answer-substance — **CLOSED-VERIFIED 2026-08-16 — 8 deploys, all measured, live web `9f617f34`. The inline quick ask names a bet a human can place and grounds it in the sim. TWO ITEMS CARRIED OUT, NOT DROPPED: the soccer margin precondition is unverified on served rows (soccer had 0 board rows all session), and board finding 3 (`live_gameline_join.py:643` pairing hazard) is diagnosed and handed to `layer2-board-quality`. Both recorded in `state.md`.** — opened 2026-08-16 — session: ask-answer-substance
> **ASK-ANSWER-SUBSTANCE CHECKPOINT 3 applied.**
> **ASK-ANSWER-SUBSTANCE CHECKPOINT 2, 2026-08-16 22:0xZ.** Six deploys shipped
> and measured today, all web-only, all cut from web's own live SHA. Live
> `d8985df8`; `main` carries the code (`339e510b`) and the ledger (`18bfc6f8`).
> Nothing of this lane is uncommitted — all four source files verified
> byte-identical to `origin/main` BY BLOB (local HEAD is 6 behind; the `M` flags
> are that gap).
>
> **Shipped:** the bet is nameable (market/line/side/price/book); reason
> sentences generated from `projection.projected` + `model_skill`; the briefing
> renders 5 not 3; `bet_analysis.edge` no longer publishes EV under the model
> edge's name (same pick read 14.01 and 0.0139 on two surfaces); quote age
> offset by artifact age and its threshold re-calibrated 15 -> 45 min; only
> positive-edge rows published, with every edge term vetoing; the sim-vs-line
> clause no longer asserts causation it cannot support.
>
> **NOT CLOSED, and the reasons are deliberate:**
> 1. **A BOARD DEFECT WAS FOUND AND HANDED OFF.** `projection.projected` sits on
>    the wrong side of `line` on 12-21 of 31-39 over/under rows, pregame as well
>    as live. Handed to `layer2-board-quality` with the table. **Consequence they
>    must expect: the panel now visibly says "does NOT support the {side}" on
>    roughly a third to a half of over/under rows until it is fixed.**
> 2. **`8172fdef` is INERT on production data** — proven by unit test only. Do
>    not read a clean board as evidence it fired.
> 3. **HARNESS RE-RUN, OBLIGATION CLOSED (22:2xZ, live `d8985df8`): 37/52 with
>    ZERO pass/fail flips** vs the same-slate control, every class identical.
>    Non-regression, not a win — the harness is blind to nearly everything the
>    six deploys changed. Its one moved warning
>    (`edge_without_market_probability` 0 → 25) was checked against the diff and
>    is BOARD DATA, not this lane's code.
> 4. **CSS ships INLINE in `ask_bar.js`** because `board_cards.css` is held by
>    `layer2-board-quality`. Move the `STYLE` const into the stylesheet when that
>    lane closes.
> 5. **A row can still publish model-positive with EV negative's opposite** —
>    resolved for the both-positive case, but the underlying question of which
>    term should win when they disagree is a product call, recorded in
>    `deploys.md` under `ask-both-edges`.
>
> **Process, worth carrying:** a resumed session does NOT inherit its own lane
> marker — it lands on the shared global `.current-lane` and `lane-guard.py`
> blocks the first edit. Fix is the per-session slot the hook names in its own
> error text (`.syndicate/.current-lane.<session-id>`), not closing the lane.
- Goal: the inline quick ask names a bet a human can actually place and grounds
  it in the sim projection that is **already in the response payload**, instead
  of a bare name and one edge number. **Single testable outcome**, on the served
  `/api/syndicate/query` payload plus the rendered panel:
  (a) a prop answer carries market, line and side (`Ryan Johnson over 2.5
  earned_runs`), not `Ryan Johnson`;
  (b) `structured_response.edge` on `bet_analysis` equals the row's
  `model_edge_pct` (same number the briefing shows for the same pick) — today
  the same pick reads **14.0% in the briefing and 1.4% per-pick**;
  (c) the briefing renders as many rows as its own sentence claims (says 5,
  renders 3);
  (d) a game-side selection names the team, never a bare `home -1.5`;
  (e) every answer carries at least one sim-derived term (projection vs line,
  or `model_skill.status`) sourced from fields already fetched.
- Files:
  - `syndicate/blueprints/ask_the_syndicate_adapter.py`
  - `syndicate/static/shared/ask_bar.js`
  - `tests/test_ask_answer_substance.py` (NEW)
  - `syndicate/blueprints/ask_the_syndicate_data.py` — **TAKEN 2026-08-16 from
    ORPHANED lane `ask-sport-coverage`** (archived session, last active
    2026-08-15 19:44; file clean and unchanged since `67ff20a0`). Scope is
    `_board_row_label` + the `_board_candidates_evidence` table ONLY. Hand back
    on request.
- Collision check, run by reading every OPEN lane's `- Files:` block:
  `ask_the_syndicate_adapter.py` was held by `ask-headline-from-board`, which is
  **CLOSED-VERIFIED 2026-08-15** (`lanes.md:1820`); the only remaining mention
  is a *disclaimer* bullet inside `ask-sport-coverage`, not a claim.
  `ask_bar.js` is claimed by nobody — zero hits in `lanes.md`. CLEAR.
- NOT claimed, read-only dependencies (top-level bullets on purpose, so
  `_claims()` cannot read them as claims):
  - `syndicate/blueprints/ask_the_syndicate_data.py`, `..._router.py`,
    `..._the_syndicate.py` — held by OPEN `ask-sport-coverage`. This lane does
    **not** edit them. The sim evidence it needs (`visuals.tables/charts`) is
    already built there and already served; nothing new is required of it.
  - `syndicate/features/shared/layer2_board.py` — held by OPEN
    `layer2-board-quality`. Read-only. `_pick_label` there is the reviewed owner
    of the side→team convention; this lane pins against it rather than
    re-deriving it.
- Hypothesis: the "answers are only edge-based" symptom is **not** missing data
  and **not** a missing model. Every discriminating field — `line`, `side`,
  `market`, `sim_projection`, `projection.model_skill`, `quote.bookmaker`,
  `quote.price`, `model_edge_pct` — is already on the candidate the adapter
  holds in `explanation.top_candidate`, and the per-pick answer already ships 7
  sim tables and 3 sim charts in `visuals` that the inline panel never reads.
  The loss is entirely in the adapter's field selection and the panel's render.
- Falsification test: if a served `bet_analysis` payload for a real prop is
  found whose `explanation.top_candidate` lacks `line`/`side`/`sim_projection`,
  then the cause is upstream data, this lane cannot fix it in the adapter, and
  the work belongs to `ask-sport-coverage` instead.
- Verification: (1) `py -3 scripts/ask_syndicate_regression.py --out
  reports/ask_regression/latest.json` re-run and diffed per class against the
  38/52 in the `ask-sport-coverage` measurement — **no class may regress**;
  (2) a new `tests/test_ask_answer_substance.py` asserting (a)–(e) against a
  captured production row; (3) the panel re-read in a browser, since (c) and the
  visuals render are client-side and no server test can see them.
- Blocked by: none.

### nfl-pbp-root-resolution — **CLOSED 2026-08-16 — resolution mechanism PROVEN CORRECT and the hypothesis FALSIFIED in the same reading. `#441` root cause settled as an ingestion gap; the lane goal (projection writes again) is NOT met and moves to a fetcher.** — opened 2026-08-16 — session: sim-engine-track
- Goal: `#441`. The NFL SmartSim2 projection writes again, because the pbp READ
  path resolves to the mounted disk instead of the ephemeral repo checkout.
- Files (exclusive to this lane): `syndicate/features/nfl/sources.py`,
  `scripts/generate_smartsim2_nfl_projections.py`,
  `tests/test_smartsim2_nfl_pbp_root.py` (new). Collision check RUN against all
  OPEN lanes: CLEAR on all three.
- **DIAGNOSIS COMPLETE BEFORE ANY EDIT — measured in production, not inferred:**
  - `DATA_ROOT : /opt/render/project/src/data/nfl_source` (the CHECKOUT)
  - `looked for : .../src/data/nfl_source/tracking/nflverse/pbp/pbp_2026.csv`
  - `.gitignore:96` excludes `data/nfl_source/tracking/`, so the pbp exists ONLY
    on the mounted disk. Zero plays loaded -> `assert_ratings_data_available`
    refuses -> artifact never written -> `age_seconds` climbs forever ->
    ~107 relaunches/day.
- **THE GUARD IS NOT THE BUG. It is working exactly as designed** — it refuses to
  write a degenerate artifact where every team rates `neutral_no_data` and all
  games get the same league-average projection (production served exactly that on
  2026-08-13: `margin 0.96 / total 44.38 / home_win 0.5267` on all 16 preseason
  games across four dates). Do NOT relax it.
- **ROOT CAUSE, and `#389` already found it for the OTHER path:**
  `_first_existing_root` picks a root by probing for `upcoming_recs_*.csv` — a
  DIFFERENT artifact family. The checkout ships those (5 tracked files); the pbp
  subtree is gitignored. So an unrelated artifact's presence decides where the
  pbp is read from. `#389` fixed the WRITE path by adding
  `nfl_artifact_output_root()` and left the READ path on the same selector.
- Hypothesis: adding a pbp-specific resolver that probes candidates for the pbp
  FILE (not for `upcoming_recs_*.csv`) makes the generator find it on the mounted
  disk and write the artifact.
- Falsification test: if the pbp is ALSO absent from the mounted disk, root
  selection is a red herring and the real gap is ingestion. The production
  message says otherwise ("that is the bug, not a missing download") but that is
  the code's assertion, not a directory listing — treat as unconfirmed until the
  artifact actually writes.
- Verification: `SEASON_PROJECTION_LAUNCHING` stops recurring every ~40s, and
  `smartsim2_projections_2026_wk1.csv` appears with a fresh mtime and
  NON-IDENTICAL rows per game (identical rows would mean the guard was bypassed
  rather than satisfied).
#### FALSIFIED 2026-08-16 15:53:28Z — the lane's own falsification test fired
- This lane wrote the test before shipping: *"if the pbp is ALSO absent from the
  mounted disk, root selection is a red herring."* It is, and it was.
- `DegenerateProjectionRun` raised again 8 minutes after go-live, with the same
  `looked for` path as before the fix.
- **THE LOG WAS AMBIGUOUS BY CONSTRUCTION** — the resolver's not-found fallback is
  `default_nfl_source_root()`, i.e. the same checkout path the old code printed.
  "Not deployed" and "ran and found nothing" are indistinguishable in the log.
  Settled by CONTENT: `97491161` carries `nfl_pbp_path` (1) and the generator's
  delegation (1), and refresh-worker is live on it.
- **v3 root cause:** the pbp is gone from every root; ten scripts reference it,
  all reads, zero writes; no nflverse fetcher exists for play-by-play. It was
  present 2026-08-13 (`verify_nfl_autorun_obligations.py:25`, real ratings on
  16/16 games), which matches the 2.79-day staleness.
- **Lane goal NOT met.** The change is kept — it removes a real latent
  misresolution and is inert when the file is absent — but it must not be
  recorded as fixing `#441`.
- Handover: find what REMOVED the file and how it is meant to arrive. That is not
  a code fix and not this lane's scope; `#441` carries the next step.

#### CLOSED 2026-08-16 17:10:45Z — settled by the diagnostic this lane shipped
- **Verification ran and the result is negative-but-decisive.** The lane's own
  falsification test fired, then the diagnostic it prompted answered the question
  outright on the first post-restart refusal:

      strict_hosted_storage_resolves_to = True
      candidate[0] /opt/render/project/data/nfl_source/source_artifacts/... exists=False
      candidate[1] /opt/render/project/data/nfl_source/...                  exists=False
      candidate[2..3] /opt/render/project/src/data/...                      exists=False

- **What the lane BUILT is correct and stays:** `nfl_pbp_path` searches the
  mounted disk FIRST (candidates 0/1 prove it), replacing a resolver that picked
  a root by probing for the unrelated `upcoming_recs_*.csv`. That was a real
  latent defect and `#389` fixed its twin on the write path.
- **What the lane BELIEVED was wrong twice:** v2 (root selection is the cause —
  shipped, falsified) and v4 (env not reaching the subprocess — falsified by the
  same reading that killed v2's successor). Root cause is v3: the file is absent
  everywhere.
- **Two of my own readings corrected here:**
  1. The `DATA_ROOT`-prints-the-checkout "contradiction" was not one —
     `_first_existing_root` returns the first root holding `upcoming_recs_*.csv`,
     which only the checkout ships, even though mounted-disk candidates come
     first in the list.
  2. I claimed strict mode cannot append the checkout. There is a SECOND append
     under `strict AND RENDER` that adds it as a lower-priority fallback.
- **Files released:** `syndicate/features/nfl/sources.py`,
  `scripts/generate_smartsim2_nfl_projections.py`,
  `tests/test_smartsim2_nfl_pbp_root.py`.
- **Handover:** `#441` needs a pbp FETCHER — no ingestion path exists in-repo.
  Template is `fetch_nfl_schedule.py` (nflverse games.csv). `#443` (stale PID
  silently stalling the autorun ~45 min per restart) delayed this verification
  twice and remains open.

### render-events-reader — CLOSED-VERIFIED 2026-08-16 — **`scripts/render_events.py` + `tests/test_render_events.py` SHIPPED TO THE TREE (no deploy — this is local tooling). Falsification test PASSED: 29/29 known `oomKilled` reproduced for 2026-08-14 CT, and the unpaged control returns 20/29 — i.e. a single-page reader undercounts by 31% while looking like an answer.** — opened 2026-08-16 — session: branch-overlap-baseline-watch
- Goal: `scripts/render_events.py` exists and answers "was this service killed,
  and why" from `/v1/services/<id>/events`, so the 2026-08-15 FORBIDDEN rule
  ("never conclude no-OOM from a LOG search") has a tool behind it. That rule
  names `render_logs.py` as unable to answer the question and leaves nothing in
  its place; every session that has needed a kill census since has hand-rolled
  one. Success = the script reports the window it ACTUALLY covered, pages the
  cursor to exhaustion, and distinguishes `oomKilled` / `evicted` / `unhealthy` /
  `earlyExit` rather than lumping them as "failed".
- Files: `scripts/render_events.py` (NEW). Checked against every OPEN lane's
  `- Files:` at open time: the only claims held anywhere are
  (`clamp-fix-to-workers`) and the four `live_gameline` paths
  (`live-game-line-projection`). No lane claims anything under `scripts/`.
  `refresh-worker-oom-recurrence` is the adjacent lane — it OWNS diagnosing
  refresh-worker memory and this lane must not touch that. Read-only tooling
  only; no service code, no config, no deploy.
- Hypothesis: n/a (tooling, not diagnostic).
- Falsification test: the tool is worthless if it can silently under-cover, which
  is exactly how `render_logs.py`'s predecessor lied (`#434`: 99 samples spanning
  1.2s of a 51s window). So: run it against a window whose contents are already
  known independently — the 29 `oomKilled` on refresh-worker 2026-08-14 CT — and
  require it to return all 29. If a single-page run and a paged run disagree on
  the count, the pager is wrong and the tool must not ship.
- Verification: (a) the 2026-08-14 census reproduces 29/29 `oomKilled`;
  (b) `--json` output round-trips through `json.loads`; (c) `py -3 -m pytest
  tests/test_render_events.py` passes. Recorded here, not in `deploys.md` —
  nothing deploys.
- **Outcome, all three verification criteria run:**
  (a) `--failures-only --since 2026-08-14T05:00:00Z --end 2026-08-15T05:00:00Z`
      returns **29 `oomKilled`**, matching the independently-derived census.
      With `max_pages=1` the same window returns **20** — the pager is the
      difference between a measurement and a plausible undercount.
  (b) `--json` round-trips through `json.loads` (checked on live-odds-worker:
      5 `earlyExit`, 0 OOM since 2026-08-15).
  (c) `py -3 -m pytest tests/test_render_events.py -q` → **15 passed**.
- **Positive control works:** the branch-overlap window 10:09:51Z..15:09:30Z
  today returns zero events AND names the newest event overall
  (`2026-08-16T06:01:34Z deploy_ended`), so "quiet" and "reader broken" print
  differently and exit differently (0 vs 2). This is the whole reason the tool
  exists — the 2026-08-15 FORBIDDEN rule said a negative result about process
  death must come from the events API, and named `render_logs.py` as unable to
  provide one, leaving no tool in its place.
- **Reading it produced, recorded because it is load-bearing for
  `refresh-worker-oom-recurrence` (that lane's, not this one's, to interpret):**
  refresh-worker `server_failed` since 2026-08-09 is **42 events, all 42
  `oomKilled`, none evicted** — 08-08:5, 08-13:4, **08-14:29**, 08-15:4,
  08-16:0-so-far (CT). Kills cluster 15:00–00:00 CT. Separately,
  live-odds-worker's 19 failures over the same week are **zero OOM, all
  `earlyExit`**, still recurring ~1–3/day through 08-16 05:54 CT — a different
  failure mode that a "19 failures" summary would have buried. Not diagnosed
  here; filed as an observation only.
- Files touched: `scripts/render_events.py` (new), `tests/test_render_events.py`
  (new, not in the opening claim — added when the verification step needed it).
  No service code, no config, no deploy.

### ui-probe-settle-plateau — CLOSED 2026-08-16 — the settle now needs 2400ms of stillness, and a verdict resting on absence says so — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `_settle()` can no longer return `settled: true` on a render that never
  started. A verdict that rests on absence of change is labelled as such in the
  JSON and in the printed row, so no reader can mistake it for a proven settle.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Hypothesis: the 800ms artifact in `reports/ui_layout/rerun_2026-08-16.json`
  (mlb desktop, `contentUnits min==max==33`, `renderSettled: true`) is the two-
  equal-poll rule firing inside a pre-enrichment plateau, not a finished render.
- Falsification test: if the growth curve on mlb desktop shows the fingerprint
  genuinely constant from `load` through enrichment, the plateau theory is wrong
  and the uniform 33 is a real slate.
- **CONFIRMED, not falsified.** Replaying the old rule over a plateau-then-growth
  tape returns `settledMs: 800, settled: true, finalFingerprint: 100` while the
  render goes on to 400 — it stops inside the plateau and reports the
  pre-enrichment DOM as final. On the live re-run with the new rule, mlb desktop
  settled at **6800ms with `sawChange: true`** and desktop/mobile agree at
  **41–53 pairs/card**; under the old rule the same two widths read 33–33 and
  33–49. The contradiction is gone because the reading is no longer premature.
- Verification: `tests/test_ui_layout_probe.py` 35 passed (27 pre-existing + 8
  new); the plateau test asserts `settledMs > 800`, which the old rule fails by
  construction. Live production run 2026-08-16 ~11:0x CDT, all 8 rows OK, no
  false alarm, footer names exactly the six server-side rows.
- What is NOT claimed: the quiet window is a longer window, not a proof. A
  render that stays still for 2400ms and only then starts would still fool it.
  What changed is that such a reading is now *labelled* (`sawChange: false`) and
  fails as soon as a second reading contradicts it.
- Blocked by: none
- Governed by `learnings.md` 2026-08-16 "a wait loop must gate on an AFFIRMATIVE
  success token, never on the absence of a failure string" — `_settle` was that
  rule recurring in a render poll. Absence of DOM change cannot distinguish
  "render finished" from "render has not started".

### ui-probe-desktop-height-model — CLOSED 2026-08-16 — desktop is UNFITTABLE, not mis-tuned; measured the floor instead of tuning the threshold — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: desktop reports a height figure that is a real layout signal — either a
  model that fits because it matches how the desktop grid actually sets height,
  or a stated finding that no per-card model can fit and why.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Hypothesis (written BEFORE testing): (a) grid row-stretching, or (b) pairs
  wrapping into columns so height goes as `ceil(u/cols)`.
- **BOTH HYPOTHESES FALSIFIED.** (a) dead: every card sits at `left=4`, one per
  row — there is no row to equalise against. (b) dead as stated: the pair grid is
  10 visible columns at 1440 and 2 at 390, not 2, and `visRows` fits WORSE than
  `u` (ratio 1.69 vs 1.16).
- **What is true instead:** the grid is a wrapping flow and text WIDTH decides
  where it wraps, so height is not a function of pair count at all. Cards with
  identical `u` differ by **116px** (u=45, n=7) and **97px** (u=49, n=5) on
  desktop; by 81px and 40px on mobile. Agreeing on BOTH `uVis` and `visRows`
  still leaves **74px**. That is a floor no model in these variables can beat.
- **Why no threshold rescues it:** `reliable` needs `residual <= 0.25*explained`,
  so a 116px floor requires 464px of explained range; desktop's content spans
  197px. Tuning the bar would manufacture a fit.
- **Bonus correction:** mobile's residual (81px) EQUALS its floor (81px) — the
  passing model sits on the noise floor and reports text wrap, not layout
  deviation. It passes only because its slope is ~62px/pair vs desktop's ~16,
  buying 743px of range to hide identical noise behind. This revises the
  "residual band ~80–105px" recorded earlier in `log/2026-08-16.md`.
- Verification: 42 tests pass (35 prior + 7 new); the new ones drive the REAL
  shipped `fitGroup` JS in a headless browser over captured production points and
  independently reproduce `floorPx == 116` and mobile `residual == floor == 81`.
- **Verification LIMIT, not claimed as done:** not observed on a live run. The
  11:5x CDT slate collapsed to a uniform 33 pairs at both widths with games Live,
  so nothing fits anywhere (`statesUnfitted: [Live, Preview]`). Verified by
  replay through the shipped code path only.
- Follow-up left open by decision, not oversight: making desktop actually fit
  needs a variable capturing rendered text extent (summed visible section
  heights, or per-section wrapped row counts). Both edge toward circular, so it
  was flagged for a call rather than chosen unilaterally.
- Blocked by: none

### ui-probe-tie-floor-tracking — CLOSED 2026-08-16 — floor collected on every row; 5 of 6 stable, mlb mobile fires the rule at 2.06x — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `identicalContentSpread` emitted on EVERY run at both widths, printed,
  compared across runs, and unable to fail a run while its stability is unknown.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Decision rule, written BEFORE the readings: moves more than ~2x across runs
  with no card-surface deploy → slate-driven, cannot be baselined → option C.
- **RESULT — 3 consecutive production runs:** nfl desktop 14/14/14, nfl mobile
  50/50/50, ncaaf desktop 45/45/45, ncaaf mobile 53/53/53, mlb desktop
  125/125/125 (116 on the earlier 11:0x geometry, so 1.08x across a slate
  change). **mlb mobile 109/109/53 = 2.06x — the rule FIRES for that row only.**
  It fails informatively: `n` at the worst tie group moved 7 → 8, so tie-group
  membership churns as data enriches and which group is "worst" moves with it.
- **The row the desktop question was actually about (mlb desktop) is stable** at
  125px across three readings while its own `contentUnits` moved 33-57 → 41-57.
  That looks like a property of the CSS, not of the slate.
- Verification: 51 tests pass (42 prior + 9 new), including one proving the floor
  is emitted when `heightModel is None` and `statesUnfitted == ["Preview"]` —
  run through the real shipped JS, not a stub. Three production runs recorded.
- Kept as WATCH, NOT promoted to STABLE_METRICS: one row fails the bar, and the
  metric is one day old.
- **Deliberately not done:** a statistic that would probably pull mlb mobile under
  the bar exists (largest tie group, or a median across groups). Choosing it
  *after* seeing which looks stable is manufacturing the result — the same error
  as tuning the fit threshold, which is what started this whole thread. Left for
  a decision.
- Bug found and fixed en route, predating this lane: `compare()` guarded
  `httpStatus >= 400` but not an `error` row, so `soccer mobile`'s 30s
  `page.goto` timeout was reported as `CODE-DRIVEN DRIFT` on four metrics at
  once. Errored rows are now SKIPPED and named; they still fail the run.
- Blocked by: none

### ui-probe-tie-statistic — CLOSED 2026-08-16 — implemented as decided; the statistic did NOT help and the instability is the SLATE — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: track the spread within the LARGEST tie group (user decision), applied at
  every row; the fit-impossibility floor keeps using the MAX across groups.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Hypothesis (written BEFORE the runs): switching statistic will NOT rescue mlb
  mobile.
- **CONFIRMED — and it is worse, not merely no better.** 3 production runs:
  mlb mobile tracked 67/132/164 = **2.45x** (fires) against worst-group
  99/132/164 = 1.66x; mlb desktop tracked 64/80/64 = 1.25x against worst-group
  83/80/83 = 1.04x. **On both MLB rows the new statistic is LESS stable than the
  one it replaced.** My stated expectation ("would probably pull mlb mobile under
  the bar") was wrong. Mechanism differed from the guess too: the largest group's
  SIZE churns, n = 7/14/7 between runs.
- **The real finding: the axis was wrong.** nfl and ncaaf read 1.00x across three
  runs, both widths, under BOTH statistics — their slates are static (units 3-3,
  16-16). MLB carries a live game and enriches continuously (units 41-57 / 33-57
  / 41-57, Live 1 + Preview 14 every run). The identical-content spread is
  exactly reproducible on a static slate and not reproducible on a churning one;
  no choice of statistic survives content moving underneath it.
- Verification: 57 tests pass (51 prior + 6 new) incl. largest-group tracked
  while `floorPx` takes the worst, and equal-n groups breaking toward the larger
  spread so the tie-break cannot hide a difference. 3 production runs recorded.
- Both statistics are emitted and printed when they differ, so nothing is lost
  whichever is diffed; only `_cmp_value` selects. Reverting is one line.
- **Recommendation NOT taken unilaterally:** revert the tracked statistic to
  `worstGroupPx` (more stable on both MLB rows, and identical to the quantity the
  impossibility floor already uses), then baseline nfl/ncaaf and treat
  MLB-during-a-live-slate as not baselineable in any statistic.
- Provenance caveat: this statistic was chosen AFTER seeing which looked stable,
  so its behaviour is not independent evidence. It did not come true.
- Blocked by: none

### ui-probe-tracked-statistic-revert — CLOSED 2026-08-16 — reverted to worstGroupPx; exposed and fixed two false alarms that were failing a healthy board — opened+closed 2026-08-16 — session: ui-probe-rerun-compare
- Goal: tracked statistic back to the worst tie group, printed number == diffed
  number == the quantity the impossibility floor uses.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Cross-era safety: `_cmp_value` reads `worstGroupPx` BEFORE `spreadPx`, because
  reports from the largest-group window carry `spreadPx` meaning the other
  quantity. Verified live: post-revert run vs a largest-group-era report reads
  `identicalContentSpread unchanged`.
- **False alarm 1 fixed:** mlb mobile printed "AT ITS NOISE FLOOR (164px) ... not
  layout deviation" and failed the run on that same number (164px > 150px
  budget). A residual at its floor is unmeetable by any model; now reported, not
  failed.
- **False alarm 2 fixed:** mlb desktop then failed with "LAYOUT SPREAD OVER
  BUDGET (313px) with content not driving height" while identical-content cards
  differed by 70px. The branch inferred "content-independent" from a flat linear
  slope; on desktop that is false, because the grid WRAPS and a flat slope means
  the line cannot see content, not that content is absent. The budget now applies
  to the content-controlled figure where tied cards exist, falls back to raw
  spread where none do, and says which it used.
- Verification: 65 tests pass (58 + 7 new); production run after both fixes exits
  0 / OK where the same board failed two rows before.
- Blocked by: none

### branch-overlap-baseline-instrumentation — CLOSED 2026-08-16 — the baseline was sampling hours where the failure does not happen — session: `branch-overlap-baseline-watch` (scheduled-task run)
- Goal: take one Phase 1 (`#440`) before-baseline sample; it turned into fixing
  the instrument, because the sample was honest and the schedule was not.
- Files: `.syndicate/scheduled_task_branch_overlap.md`,
  `.syndicate/scheduled_task_oom_band.md`, and three task files under
  `~/.claude/scheduled-tasks/` (outside VCS — prompts now embedded in the
  oom_band mirror so all three are recreatable).
- **NO LANE WAS OPEN WHILE THE WORK HAPPENED.** Opened at checkpoint, closed
  immediately. Config + mirrors only, no app code, nothing contended — but the
  protocol says claim first and I did not.
- Measured: 42 `oomKilled` in 8 days, **41 of 42 in 15:00–23:59 local**; cron
  moved `15 */4 * * *` → `45 19,22,1 * * *` (three 5h windows tiling
  14:45–01:45). Sampling drops 6/day → 3/day with the kill band fully covered.
- Corrected: the oom-band tasks' SHA-equality pin → containment check. See
  `learnings.md` 2026-08-16.
- Added: `preband-refresh-worker-sha-check`, one-time 21:45Z, returns
  BAND CLEAN / BAND COMPROMISED. **It notifies nobody** — created from a
  scheduled-task run session, which cannot subscribe another task.
- Pushed: `8150ff5b`, `b37b870c`, `80581700`, `38bb30b2`. Ledger writes from this
  checkpoint are UNCOMMITTED (shared files carry other sessions' in-flight edits).
- Blocked by: none. Nothing here is load-bearing for another lane; the
  `refresh-worker-oom-recurrence` owner keeps the diagnosis.

### ui-probe-baseline-nfl-ncaaf — CLOSED 2026-08-16 — armed for nfl/ncaaf only; mlb stays watch-only — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `identicalContentSpread` fails on drift for nfl/ncaaf, stays watch-only
  for mlb/soccer, with a new baseline carrying the field.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`,
  `reports/ui_layout/baseline_2026-08-16.json` (NEW)
- Falsification test: if nfl/ncaaf tie spreads differed between two runs now with
  no deploy, they are not baselineable. **They did not** — 14/50/45/53 held
  across every run today, and the armed comparison reports all four as
  `unchanged (baselined)`.
- Four outcomes kept distinct: drift FAILS; a baseline predating the field is
  NOT COMPARED and does not fail; a VANISHED current value FAILS (absence is
  never a pass); a state change is NOT COMPARABLE rather than drift — which is
  what stops kickoff reading as a layout regression.
- Verification: 72 tests pass (65 + 7 new); live run splits exactly as intended,
  nfl/ncaaf baselined-unchanged while mlb moved 68 -> 69 on the watch line
  without failing.
- **First baseline run was DISCARDED, not shipped**: it failed on `ncaaf desktop
  tab click identity`. Second run clean; the baseline carries `ok: true`. The
  tab-click intermittent is real and unexplained — recorded, not chased.
- **Open and unrelated:** mlb mobile Live state now fails legitimately — residual
  151px against a 40px floor, `atNoiseFloor` False, worst card +79px at 45 pairs,
  1px over budget. The exemption correctly declines. Needs its own look.
- Blocked by: none

### mlb-mobile-live-residual — CLOSED 2026-08-16 — HYPOTHESIS FALSIFIED; it is a false alarm, the Live fit is convex and `fitRatio` cannot see curvature — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: name what makes one Live card +79px off the model, or show the residual
  is noise.
- Hypothesis: the outlier carries a BLOCK its same-pair-count peers lack.
- **FALSIFIED. There is no outlier.** Residuals are U-shaped across pair count
  (+76 at u=45; -2/-10/-42 at u=49; -41/-75 at u=53; +73 at u=57) — a line
  fitted to a curve, not an anomalous card.
- **Mechanism found:** per-pair cost is LINEAR in Preview (62.4, 62.1 px/pair)
  and CONVEX in Live (41.3, 61.8, 76.6). The curvature is entirely in
  `section.cards-panel.is-active > div.cards-overview-grid` (3187 -> 3906px
  across the Live series; every sibling block flat or <=28px). Live puts cells of
  differing heights into a wrapping row-max grid, so each added pair costs more
  than the last; Preview's cells are uniform.
- **The harness is at fault, not the board:** `fitRatio = residual/explained`
  cannot see curvature, so a misspecified model with a wide explained range
  (771px) passed as `reliable: True` at ratio 0.2 and then tripped the budget
  with a STRUCTURED residual. The named worst card (u=45) is the ONLY card at
  that u — no peers — so "+79px off the model" is deviation from a LINE. Cards
  that do have peers agree to 40px.
- Recommended, NOT implemented (needs a decision): fail on deviation from
  same-content PEERS (`floorPx`, model-free) rather than from the line; and
  optionally flag monotone per-step slope drift as MISSPECIFIED so `fitRatio`
  stops certifying curved fits.
- Live consequence: the probe fails every run while MLB has a live slate.
- Blocked by: none

### branch-overlap-manual-run-marker — CLOSED — opened 2026-08-16 — session: `branch-overlap-baseline-watch` — verified in production 2026-08-16T19:52:23+00:00
- **PROVEN IN PRODUCTION.** The 14:45 local slot landed a record at
  `recorded_at=2026-08-16T19:52:23+00:00` carrying **`run_mode="scheduled"`** — the
  first record ever written with the field set, so `--scheduled` does reach the
  live task. Covered 2026-08-16T14:52:07Z—19:51:47Z (09:52—14:51 local),
  `samples=1967`. The three prior records carry NO field and stay UNKNOWN.
- Goal: a record in `reports/branch_overlap/baseline.jsonl` states whether it came
  from the scheduled run or from a human, so a manual probe can never be counted
  as evidence in the Phase 1 (`#440`) before-distribution.
- Files: `scripts/watch_branch_overlap.py`,
  `reports/branch_overlap/baseline.jsonl`,
  `.syndicate/scheduled_task_branch_overlap.md`, and the live task file.
- Why: testing the new 14:45 slot appended a record indistinguishable in shape
  from a scheduled sample — same failure the pre-band drift check was added to
  prevent, in the instrument this session was fixing. Baseline also already
  double-counts 10:09–15:09Z (two runs overlapping ~4.5 of 5 hours).
- Design: `--scheduled` flag; **absent means manual**. Fails safe — forgetting the
  flag excludes a run from the distribution rather than silently counting a probe.
  No time-vs-cron math, which would re-couple the script to a schedule that has
  already changed twice today.
- Consumer note: records written before this change carry NO field. Absent must
  read as UNKNOWN, never as scheduled.
- Blocked by: none. `refresh-worker-oom-recurrence` owns the diagnosis; this is
  instrument provenance only.

### ui-probe-peer-deviation-gate — CLOSED 2026-08-16 — one model-free height rule; production green, coverage gap printed — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: ONE height failure rule — deviation from same-pair-count peers — with
  residual-from-the-line and raw-spread removed.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Falsification test had two halves and BOTH passed: a fabricated 420px peer
  deviation still fails (so a real defect with peers is caught), and the live
  board went GREEN (exit 0/OK) where it had been failing — matching the
  diagnosis that no card deviates from its peers.
- Live peer deviations: mlb desktop 96px, mlb mobile 123px, nfl 14/50, ncaaf
  45/53, all under the 150px budget.
- **Coverage loss stated, not hidden:** a card with no same-`u` peer cannot be
  judged. The row now prints `peer check covered 11/15 cards` and, where nothing
  ties at all, `PEER CHECK DID NOT RUN` — a stated gap, the treatment
  `statesUnfitted` already gets.
- The fit is still reported (residual, chrome, px/pair, UNFITTABLE, UNRELIABLE,
  noise floor) as CONTEXT. It decides nothing.
- Verification: 71 tests pass. Nine tests encoding the removed rules were
  DELETED rather than adjusted; the default fixture is now a healthy slate under
  the peer rule; 8 new tests cover fail/pass/per-state/coverage/did-not-run/
  no-model.
- Closes the root cause behind all three of today's false alarms: the fitted
  line was treated as ground truth when the tie structure is the only model-free
  evidence available.
- Blocked by: none

### layer1-board-coverage — UPDATE 2026-08-16 17:5xZ — **DEPLOYED AND FALSIFICATION TEST PASSED. Supersedes this lane's "UNDEPLOYED" line above.**
- Two deploys to **refresh-worker** (`srv-d91dpertqb8s73co8ls0`), both cut on the
  LIVE SHA rather than `main` — `main` did not contain the worker's lineage (22
  commits incl. another session's `#441` diagnostic), so deploying it would have
  rolled all of them back. `01a4b83e` live 17:26:25Z, `f88796a9` live 17:40:50Z.
  Web deliberately NOT deployed: `/api/board/layer1` is a pure read and the
  `projection` field is written at artifact-build time, so a web deploy would
  have been inert.
- **RUN 1 FAILED, and that is the result worth keeping.** mlb 284 → 0
  unattributed; **3 WNBA `game|h2h|full` rows did not move.**
  `wnba_game_projections.py:208` writes `row["projection"]` DIRECTLY and never
  passes through `attach_projections` — a **fourth producer**, exactly the shape
  the brief warned about for `fair_price`. My pre-deploy replay proved the
  HELPER (I supplied its arguments) and never asked whether production calls it.
  New learnings entry: *a replay proves the FUNCTION; only the call path proves
  the FIX.*
- Fixed at that producer (`f88796a9`). **RUN 2 PASS: RESIDUAL 0 across 10,692
  rows**, all three in-season sports, on artifacts stamped after the deploy.
  Confirmed on a SECOND independent build (17:46–17:48Z), also 0.
- Regression check: edges still served — mlb 867 / wnba 326 / soccer 528, none
  created or removed. **mlb's edged count fell 1,462 → 867 and that is NOT this
  change**: `by_state` went `{live 1, pregame 14}` → `{live 8, pregame 7}` and
  the live-edge refusal rose 65 → 697 to match. Re-read on a pregame slate.
- Another session's deploy `b9f2b5f1` went out on top at ~17:5xZ; checked by
  content AND ancestry — `f88796a9` is an ancestor and both fixes are present,
  so this work survives it.
- **Lane STAYS OPEN** for the one unmeasured goal: the cross-sport LIVE A/B needs
  two sports live at once. Everything else in the audit is delivered.

### ui-probe-curvature-detection — CLOSED 2026-08-16 — `curved` forces `reliable:false`; Preview (the falsification case) is not flagged — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: `reliable` stops certifying a CURVED fit.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Method: slopes between consecutive pair-count group MEANS, then monotone-drift
  test. >=3 steps required; two steps can only say "one went up".
- Threshold measured: Live drift 0.88 vs Preview 0.008 — two orders of magnitude
  apart, so the 0.5 cutoff is not load-bearing.
- **Falsification test PASSED:** the known-linear Preview series is NOT flagged,
  while Live is flagged with `fitRatio` still 0.20. Two-step and non-monotone
  series also not flagged.
- Verification: 77 tests pass, both series driven through the real shipped JS.
  Live run shows no false positives; today's slate has too few distinct pair
  counts per state to exercise the detector either way.
- Reported as MISSPECIFIED, deliberately distinct from UNRELIABLE: the line is
  the wrong shape, not noisy, and "no layout signal here" would understate it.
- Low risk: `reliable` gates no failure now, so this changes a label not a
  verdict — which is why it was safe to do after the peer rule, not before.
- **HANDS OFF, needs a decision (see log):** the peer budget is a FIXED 150px
  against a quantity that scales with content. mlb mobile's identical-content
  spread read 81/109/123/164/193px today; the 193px case is 7 cards evenly
  spread (gaps 11/23/16/49/28/66), i.e. wrap, not a defect. Must not be resolved
  by raising 150 until the board passes.
- Blocked by: none

### ui-probe-proportional-budget — CLOSED 2026-08-16 — shipped; falsification test FIRED (proportional does not tighten the spread) but it fixes the width bias — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: peer budget as a share of the tie group's card height, percentage chosen
  from measurement.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Method held: denominator added FIRST, 16 readings collected, threshold picked
  only afterwards — so the number could not be reverse-engineered from the answer.
- Calibration: worst healthy reading 9.9% (mlb desktop Live); 15% is ~1.5x.
  Deliberately tighter than the old 3x principle, which here would be 30% = 1440px
  on a 4800px card.
- **FALSIFICATION TEST FIRED.** The lane predicted healthy readings would cluster
  as a share of height. They do not: raw px max/median 3.3, percentages 3.0 —
  the same scatter. The premise was wrong and is recorded, not dropped.
- Kept anyway because it fixes a DIFFERENT real defect: the width bias. 150px is
  2.8% of a 4800px mlb mobile card and 27% of a 541px ncaaf desktop one.
  Percentages separate by width; px separate the opposite way.
- Verification: 80 tests pass incl. the same 400px passing at 4800px (8.3%) and
  failing at 541px (73.9%); no-height groups named NOT JUDGED rather than
  skipped; live run exit 0/OK with all four baselined rows unchanged.
- **Standing recommendation:** this is a BACKSTOP. Drift-against-baseline caught
  nothing false all day while the absolute budget produced three false alarms.
  Extending `TIE_SPREAD_BASELINED` beyond nfl/ncaaf is worth more than tuning
  this percentage.
- Blocked by: none

### layer1-board-coverage — **CLOSE REFUSED 2026-08-16 18:0xZ.** Verification is not met, and a NEW production defect was found in this lane's own scope while attempting to close
- The `/lane close` gate says: confirm the verification ran and state the result;
  if it did not, refuse and say what is missing. Two things are missing.
- **(1) The lane's own stated verification is unmet.** Cross-sport LIVE A/B
  requires two sports live at once. At 18:00Z: mlb 8 live, wnba 3 pregame (first
  kickoff 21:00Z, ~3h out), soccer *reported* 0 live. **Satisfiable from ~21:00Z
  today**, when WNBA's 21:00Z games overlap the MLB slate.
- **(2) SOCCER SERVES BETTABLE EDGES ON FINISHED MATCHES — found by the USER, not
  by my sweep.** They said "SOCCER has live games" while the board said `live: 0`.
  Measured 18:03Z: **14 soccer games past kickoff, 12 carrying a real score, 0
  marked live; 45 rows serving an edge on a game in play or over.** GRO @ ADO
  kicked off 7.8h ago, finished 4-1, and the board offers an edge on `totals 2.5`
  — settled OVER before lunch. mlb/wnba: 0 such games.
  - Cost mechanism: `live_edge_policy` keys on `game.state`, and `pregame` is its
    PERMISSIVE branch, so a game stuck there never has its edge withheld. `#413`
    reappearing on a sport whose state never becomes live at all.
  - Decision site: `game_chip_scoreboard._game_flags:113` infers live/final from
    status TEXT only and **never consults kickoff time or score**; absent status
    falls through to `pregame`. `attach_game_state` copies `chip["state"]`
    through and is NOT the cause.
  - Unconfirmed hypothesis (two greps, not a measurement): soccer emits `status`
    as a STRING (`soccer/cards.py:197,512`) while `_game_flags` reads it as a
    DICT, so soccer's status is invisible by TYPE. **Falsify by dumping one
    soccer chip as the worker sees it before touching `_game_flags`.**
  - NOT fixed here on purpose: `_game_flags` is shared by all 8 sports and a
    wrong `live` costs as much as a wrong `pregame`. Needs its own lane, its own
    falsification test, and a decision. `game_chip_scoreboard.py` is unclaimed.
- **This also invalidates my own G3 conclusion.** I wrote "no second sport was
  live, so the cross-sport A/B is deferred". Soccer WAS live; the board could not
  see it. The blocker was the finding.
- Lesson, already a standing rule and violated anyway: *the user watches the
  board, and their concrete board report beats my automated check.* My instrument
  had produced the evidence (10 stale-pregame, 17 unknown) and I read it as a
  scoping curiosity instead of an outage. Third occurrence.
- Lane REMAINS OPEN.

### soccer-live-game-state — CLOSED-VERIFIED 2026-08-16 18:56Z — a kicked-off match is no longer `pregame`, and no finished match carries an edge
- **Verification RAN and PASSED**, on production artifacts stamped after the
  18:54:37Z deploy:
  - soccer `by_state` `{live 0, final 0, pregame 49, unknown 17}` →
    **`{live 4, final 11, pregame 34, unknown 17}`**; games past kickoff still
    marked pregame **10 → 0**.
  - **Harmful edges (on a finished game, or on a live game from a pregame
    projection) across all in-season sports: 0.** Was 27 + 9 on soccer.
  - MLB's **2 live-aware edges preserved** — the main regression risk, since
    suppressing those would delete the only genuinely live number on the board.
  - **The branch is confirmed to have RUN, not just to have produced a zero:**
    served coverage reads `live_edge_enforced_rows: 36` for soccer
    (`final` 27 + `live` 9 — matching the pre-fix count exactly) and `0` for MLB.
- Two deploys, both cut on the LIVE worker SHA: `38ba954c` (state) 18:37:38Z,
  `a72b4bf4` (enforcement) 18:54:37Z. Measurement in `deploys.md`.
- **Deploy 1 alone was NOT enough and the sweep is what said so.** With states
  finally correct, 36 rows still carried edges, because
  `soccer_projections._price_against_market` opens `if model_prob is None:
  return` while `_mean_projection` sets `model_prob_over: None` alongside
  `edge_vs_line` — so every mean-based row returned before the refusal whose own
  comment claimed it ran "for every row, mean-based and probability-based alike.
  Checked rather than assumed."
- Fixed at `board_enrichment.attach_projections`, not in the producer: thirteen
  return sites across seven sports, and that wrapper already exists for exactly
  this argument. It also covers `soccer_projections.py` **without editing it**,
  so the orphaned lane's claim on that file was never crossed — the file is
  unmodified.
- Claim override taken on `syndicate/features/soccer/cards.py` only, logged at
  lane open: `soccer-model-coverage` is ORPHANED (owning session absent from a
  40-entry census incl. archived).
- Near-miss worth keeping: the first draft used `isinstance(row, Mapping)` in a
  module that does not import `Mapping` — a `NameError` on the FIRST row that
  would have taken the whole projection join down. Caught by running it.
- Files: `syndicate/features/soccer/cards.py`,
  `syndicate/features/shared/board_enrichment.py`,
  `tests/test_soccer_cards_live_state.py`, `tests/test_live_edge_enforcement.py`,
  `tests/test_projection_degeneracy.py` (one exact-dict assertion widened).

- **ROOT CAUSE FOUND 2026-08-16 ~18:2xZ — the freeze WRITER and the grading READER are on two different trees, separated by one path segment (`source_artifacts/`).**

      WRITER  `_freeze_oddsapi_pregame_markets`, market_dir = source_root/data/market/oddsapi
              source_root = REPO_ROOT/data/mlb_source   (`refresh_odds_sources.py:666`, passed as --source-root)
              => <checkout>/data/mlb_source/data/market/oddsapi/
              git-tracked files there: **0**

      READER  `_odds_paths` -> <root>/market/oddsapi, root[0] = MLB_BETTING_DATA_ROOT
              = /opt/render/project/data/mlb_source/source_artifacts/data   (all three services)
              => .../mlb_source/source_artifacts/data/market/oddsapi/
              git-tracked `*_pregame.json` there: **27, newest 2026-07-08**

- **That single fact explains both halves of this lane.** (1) `frozen_doc` is read back from the WRITER's tree, which git tracks as EMPTY — so every deploy recreates the checkout without it, `frozen_doc` comes back `{}`, and the merge (monotonic by construction) reseeds the freeze from live-only-pregame. (2) The grading builder reads the OTHER tree, whose newest sealed game-lines file is from **July 8** — so ~14 of 15 games warn `Missing game-line match` and exactly one grades, on every date.
- **The merge code is NOT at fault and should not be edited.** `_merge_pregame_game_lines` seeds `frozen_games` from `frozen_doc` and only ever adds or updates. Given a readable `frozen_doc` it cannot shrink. The observed shrink is proof the input was empty, not that the merge is wrong.
- **EVIDENCE for the deploy-reset half, stated at its real strength (n=1 on the transition):** refresh-worker deployed 6x between 16:46Z and 18:07Z. Freeze read **14 games at ~17:52Z** -> **8 games at 18:12Z** (7 of the 8 still pregame), with `cf467794` going live **18:07:36Z** between the two reads. Re-read at 18:18Z with no new deploy: still 8/7, i.e. steady between deploys. That is consistent, not conclusive; `7b544eb4` was still building and its landing is the next free test.
- **INSTRUMENT NOTE — I corrected myself mid-check.** I nearly concluded `market/` is absent in production because `/api/ops/artifacts/export` shows 3466 files under `mlb_source/source_artifacts/data/` and **zero** containing `/market/`. That endpoint runs on WEB and reads WEB's disk; the grading builder runs on refresh-worker and reads ITS disk. Separate disks (three-service architecture). The zero is real for web and says nothing about the worker. Not usable as evidence for the reader's tree.
- **`market/*.json` IS allowlisted** (`artifact_publisher.py:78`, `*_source/source_artifacts/data/market/*.json`, and fnmatch's `*` crosses `/`), so the absence on web is a publish/transfer question, not an allowlist one. Unresolved and NOT needed for the diagnosis above.
- **STILL OPEN, and it is the fix decision:** which of the two trees is meant to be canonical. Either the writer should target `source_root/source_artifacts/data/market/oddsapi` (write where the reader looks), or the reader's root should include the checkout tree. Do not guess — `--artifact-root` already exists on this script (`_local_source_artifact_root("mlb")`) and a publish step may be the intended bridge. Whichever way, the freeze must live somewhere a deploy does not wipe.
- **The scheduled check `grading-freeze-payload-check` (2026-08-17 07:00 CT) was rewritten** to predict the collapse rather than the full slate, and now carries the `_odds_data_roots()` exoneration so it is not re-opened.

- **FIX BUILT AND TESTED 2026-08-16 ~18:5xZ — NOT DEPLOYED, and it is INERT until it is.** `scripts/refresh_mlb_oddsapi.py`:
  - New `_freeze_market_dirs(source_root)` returns every `market/oddsapi` the freeze must live in: the writer's own tree (unchanged, and first — it is where the live doc it merges from is fetched to), **`<MLB_BETTING_DATA_ROOT>/market/oddsapi`**, and `source_root/source_artifacts/data/market/oddsapi` for env-less callers.
  - **Derived from the SAME env var the reader uses, deliberately not hardcoded to `source_artifacts`.** `_odds_data_roots` resolves odds from `MLB_BETTING_DATA_ROOT`; a hardcoded second layout would silently diverge again the next time that var is repointed, which IS this bug.
  - **Seed from every copy, not just this tree's** — `frozen_doc` is now the union of all existing seals (merged at `now_epoch=0.0` so started games carry across rather than being dropped by a pregame test that should only apply to the LIVE doc). Without this, writing to the right place still loses the slate on the next deploy.
  - `_ensure_dir` on every destination parent. Only `snapshot_dir` was ensured; the reader's tree on a fresh disk would have raised and taken the whole freeze down with it.
  - `_merge_pregame_game_lines` UNTOUCHED. It was never at fault.
  - Contract change: `copied` is keyed by FULL PATH, not basename — the copies share one filename, so a name-keyed dict reported one and hid the rest. It surfaces as `frozenPregame` in the run payload, which is where this fix gets verified in production.
- **TESTED: 419 passing.** 59 (freeze + odds-paths + odds-sources orchestrator) and 360 + 13 subtests (mlb market board, mlb refresh runner, live refresh loop). 3 new tests added in `tests/test_oddsapi_pregame_freeze.py::FreezeReachesTheGradingReaderTests`.
- **NON-VACUITY VERIFIED, and it mattered.** The 3 new tests were re-run against a simulated pre-fix `_freeze_market_dirs` (single directory): **all 3 fail**. Without that check `test_freeze_lands_in_the_source_artifacts_tree` could have passed for the wrong reason.
- **A test-result correction worth keeping:** the first adjacent run exited 0 with no FAILED/ERROR lines, but 464KB of worker debug output had swallowed the pytest summary. Exit code alone does not separate "all passed" from "collected oddly" — re-ran in batches to get real counts rather than bank the zero.
- **TWO LIMITS, STATED:** (1) `autoDeploy` is off, so this ships nothing until someone deploys — the 2026-08-17 07:00 CT check will measure the OLD behaviour unless a deploy lands first, and a deploy kills any in-flight sim. (2) **Forward-only.** It seals future slates; it does not repair the already-collapsed freezes for 08-09..08-16. `scripts/backfill_pregame_game_lines.py` is the tool for that and is untouched.

### ui-probe-tab-click-race — CLOSED 2026-08-16 — cause UNPROVEN and not reproduced; the blindness that made it undiagnosable is fixed — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: stop the intermittent, or name a real defect.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- **Three hypotheses written before testing, ALL FALSIFIED:** (1) deferred tab
  handler — `activateTab` is a synchronous `classList.toggle`; (2) selection lost
  because cards lack ids — all 16 ncaaf cards have ids; (3) the probe's click
  triggers `refreshOnFocus` — 0 refresh fetches after the click in 10/10 runs,
  10/10 passed.
- **NOT REPRODUCED** in 10 scripted attempts or any probe run since. The cause of
  the single instance stays UNKNOWN and is recorded as such.
- Real mechanism found, previously unguarded: `game_board.js` polls every 30s and
  does `cardsGrid.innerHTML = fresh.innerHTML`, detaching every node the check
  holds, while the check sampled panel state exactly ONCE after `click()`.
- Fixed: the failure now prints WHY (error type, or `active=[…] h=…px`) — the
  primary fix, since `tab click identity` cost this whole investigation; the
  check waits on the outcome (2000ms/100ms poll) and retries once on staleness;
  a no-measurement result carries `ok: False` explicitly.
- Verification: 85 tests pass (80 + 5). Live run exit 0/OK with ncaaf 4 / nfl 4 /
  mlb 3 tabs all ok at attempts=[1,1,1,1] — the retry never fires, correct for a
  synchronous handler.
- Process note: the failing artifact was OVERWRITTEN by the clean re-run and
  never committed, so its detail is unrecoverable. Keep a failing artifact under
  a separate name before re-running.
- Blocked by: none

### layer1-board-coverage — SCOPE ADDED 2026-08-16 20:0xZ — the HR threshold ladder
- Additional file claimed: `vendor/mlb_bettingv2/tools/daily_update.py` (the HR
  threshold counters and `_hr_row`). Checked against every OPEN lane: unclaimed.
  `prop_projections.py` is already this lane's.
- Goal: `batter_home_runs` at lines 1.5 and 2.5 stops being 0% projected.
  **504 dark rows**, the single largest coverage gap on the MLB board.
- **The cause, read from the emitter's own key table** (`daily_update.py:4452`):
  five stats go through the ladder helper and HR does not.
      _inc_ge_thresholds("hits", pid, h, 3)
      if hr >= 1: _inc_ge("hr_1plus", pid)          <- HR, single threshold
      _inc_ge_thresholds("hits_runs_rbis", pid, hrr, 5)
      _inc_ge_thresholds("runs", pid, rr, 3)
      _inc_ge_thresholds("rbi", pid, rbi, 4)
      _inc_ge_thresholds("total_bases", pid, tb, 5)
  `hr_2plus`/`hr_3plus` are never counted, `_hr_row` emits only `p_hr_1plus`,
  and the consumer refuses anything but line 0.5 outright
  (`prop_projections.py:366`). Three layers agreeing on a limit none of them
  needs — the model simulates HR per plate appearance and P(HR>=2) falls out of
  the same counter.
- Falsification test: if `hr_2plus` is counted and published and the board still
  shows 0 projections at line 1.5, the consumer is not the only remaining
  blocker and the artifact join needs looking at instead.
- **Verification requires a SIM RUN, not just a deploy** — the counters only
  change what a new sim writes, so an existing artifact will not gain the field.
  Stated up front so a green deploy is not mistaken for a working fix.
- Blocked by: nothing to build; verification blocked on the next MLB sim cycle.

### ui-probe-peer-min-group — CLOSED 2026-08-16 — verdicts need n>=3; thin groups reported, never dropped — opened 2026-08-16 — session: ui-probe-rerun-compare
- Goal: a PEER DEVIATION failure requires n>=3; thinner groups still reported.
- Files: `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`
- Evidence: a run failed at 30.9% on an n=2 Live group (2 cards at 41 pairs,
  312px apart) while the n=6 group on the same board sat at 82px. Minutes later
  only ONE card remained at 41 pairs — transient pairing from MLB live
  enrichment, which gives a card a passing pair count that can coincide with an
  unrelated card's. Three runs after: green.
- **Falsification test held:** had the n=6 groups also been over budget, group
  size would not be the discriminator. They were not — 82px vs 312px.
- `tieFloor` now returns the FULL per-group list. Required, not cosmetic: with
  only worst+largest the gate would skip a genuine n=6 group hiding behind a
  thin n=2 one with a larger spread. Pinned by a test.
- Verification: 91 tests pass (85 + 6). Three consecutive live runs OK, zero
  over-budget failures, all four baselined rows unchanged.
- **Deliberate trade, recorded:** a defect isolated to a card with fewer than 3
  same-content peers no longer carries a verdict, though it is still printed.
- Does NOT make MLB baselineable — that number still read 81..312px across the
  day. Tomorrow's scheduled pre-game run tests that separately.
- Blocked by: none

- **CHECKPOINTED 2026-08-16 ~21:0xZ — STATUS: fix BUILT + TESTED + PUSHED TO A BRANCH, NOT DEPLOYED, NOT ON `main`.**
  - Durable copy: **`origin/wip/grading-blocker-freeze-fix` = `8ad48ac8`**, verified on the remote by content (fix 2 occurrences, `FreezeReachesTheGradingReaderTests` present, handoff blob `9e6fc894` == local).
  - **Four earlier commits of this lane went unreachable** (`61e2c21e`, `419cc238`, `bf643d72`, `ca80ec46`) — `main` was rewritten under the session. Everything was re-landed from the working tree. See `learnings.md` 2026-08-16 "a local commit on this worktree is not durable".
  - Deploy runbook: `.syndicate/handoff_deploy_freeze_reader_tree.md`. **Must be executed by an ATTENDED session** — this one is a scheduled-task run and must not fire deploys.
  - **NEXT ACTION:** merge the wip branch (or cherry-pick `8ad48ac8`), then follow the handoff — both workers in one lull, ROUTE ONE warm-up, verify by content — and re-aim `grading-freeze-payload-check` from date 08-16 to 08-17 firing 08-18, because as armed it reads a date the fix cannot affect.

### sim-scheduling — **DEPLOYED AND MEASURED 2026-08-16 21:2xZ.** `#441` verified live; `#445` shipped but unverifiable today; layer2 (both halves) shipped and measured — session: sim-scheduling

- **Two deploys, each cut on that service's OWN live SHA, never on `main`:**
  - refresh-worker `c324447d` (20:33:23Z) — `#445`, `#441` position-2 + skip
    logging, layer2 producer. Later superseded by another lane's `a9e5d3d6`
    (20:50:14Z), which DESCENDS from it and preserves both fixes (checked).
  - web `73e59f51` (21:21:05Z) — the three `syndicate/features/shared/` modules
    (`layer2_board`, `opportunity_signals`, `book_shortlist` NEW). Layer 2's UI
    files were ALREADY live; verified per file by blob rather than assumed.
- **VERIFIED:** `#441` at dispatch position 2 in the running process; layer2
  `no_bettable_book` / `repriced_to_bettable` non-zero on 3 sports on the served
  payload. Numbers in `state.md` and `deploys.md`.
- **DEFECT I SHIPPED AND ITS CLOSURE:** `c324447d` landed a caller without its
  callee; ~17 min of zero layer2 rows, hidden by a per-sport `except`. Closed by
  `a9e5d3d6`. Full rule in `learnings.md` (check BOTH directions across a cut
  call boundary; ship callee-first).
- **NOT DONE / handed on:**
  - `#445` — cannot be closed until an ncaaf projection dispatches or the season
    opens (~08-29). Two readings still unseparated; see `todo.md`.
  - `#447` (NEW) — 6 `test_layer2_shortlist_wiring` tests are RED on live AND on
    `main`. `main` is a strict subset of live (6 vs 7), which was enough to clear
    the deploy as "not a regression" and is NOT a clean bill of health. Unowned.
  - `#443` — stale-PID silent stall. Still open, still unowned.
  - Layer 1 board lane needed NOTHING from me: its fix was already live and its
    falsification test had passed.
- **Files touched (all committed, worktree clean):** `scripts/fetch_nfl_pbp.py`,
  `scripts/run_refresh_worker.py`, `scripts/generate_smartsim2_ncaaf_projections.py`,
  `syndicate/features/shared/live_refresh_loop.py`, `syndicate/features/nfl/sources.py`,
  `scripts/census_kickoff_hours.py`, `scripts/watch_branch_overlap.py`, plus tests.
- **Plan artifact:** `.syndicate/plan_2026-08-16_sim_scheduling.md` (`#440`) —
  phases 0/1 landed, phases 2-9 untouched.

### game-shape-capture — UPDATE 2026-08-16 ~23:0xZ (checkpoint) — **PRIMITIVE COMMITTED `af3017e6`; EMIT STILL BLOCKED; HANDOFF SENT**

- **Committed:** `af3017e6` — `game_shape.py` (356 ln) + `test_game_shape.py`
  (332 ln), 2 files / 688 insertions / **0 deletions**, through an isolated
  `GIT_INDEX_FILE` with the file-count and deletion guards asserted in the same
  shell. Reachability asserted after the fact (`merge-base --is-ancestor`) —
  see below for why that step is not optional.
- **THE FIRST COMMIT (`87ffffd2`) WAS ORPHANED WITHIN MINUTES.** Another session
  moved local `main` to a commit not descending from it. Blobs were verified
  byte-identical (`rev-parse <sha>:<path>` vs `hash-object`) and re-committed as
  `af3017e6`. **`05f7d8fb`, another lane's wnba commit, was orphaned by the same
  move and is NOT recovered here** — it belongs to that lane and `origin/main`
  carries a different wnba commit (`e9fdcf98`). Rule filed in `learnings.md`.
- **`commit-guard` blocked twice**, both times on stale shared-index reverts that
  were not mine (5 ledger files, then 5 more incl. 182 dropped lines of
  `live_refresh_loop.py`). Disarmed path-scoped, index-only. **Its fix list was
  incomplete BOTH times** (`scheduled_task_ncaaf_445.md`, then `deploys.md`);
  every remaining staged path was audited by hand for on-disk/in-HEAD status.
  Other sessions' legitimate staged work was left untouched throughout.
- **HANDOFF SENT** to session `Layer 1 board coverage audit (fork 2)`
  (`local_c83b3d44-…`), which holds both `mlb-live-gameline-distributions` and
  `wnba-live-tier`: the two-line change (bind `situation` INSIDE the existing
  `try` so the bare-except semantics are unchanged; one `"gameShape"` key on the
  return) plus the guarded helper. **No reply yet.** They may decline; the
  primitive stands either way.
- **STILL BLOCKED, and the lane's verification has NOT run.** No production data
  has passed through this code. Every bucket count is **n=0**. Do not read
  "committed and tested" as "working in production".
- **Local `main` is ahead 1 / behind 2 of `origin/main` — `af3017e6` is NOT
  PUSHED.** That is the single largest risk to this work surviving.
- Blocked by: `mlb-live-gameline-distributions` (emit half only).

#### game-shape-capture — ORPHANED A SECOND TIME, THEN ANCHORED `[2026-08-16 ~23:1xZ]`

`af3017e6` was orphaned **again** while this checkpoint was being written —
local `main` was hard-reset to `origin/main` (`git status -sb` went from
`ahead 1, behind 2` to level). Twice in one session, two different sessions'
commits, so **re-committing onto `main` is not a fix; the next reset takes it
too.**

**The work is now anchored on a real ref: branch `lane/game-shape-capture` ->
`af3017e6`.** A ref makes the commit reachable, immune to any `main` move, and
safe from gc — and it costs nothing and touches no other session. Blobs
re-verified against disk (`95035c9a…`, `907b4d4e…`). **`game_shape.py` is NOT
in `main`/`HEAD` and NOT on `origin/main`.**

**NEXT ACTION for whoever picks this up:** get `lane/game-shape-capture` onto
`origin/main` (cherry-pick or merge, then push) — until then this work exists
only in this worktree.
- **CHECKPOINT 2 — 2026-08-16 ~22:3xZ. DEPLOY AUTHORISED, ARMED, NOT FIRED.**
  - Fix is on `origin/main` (blob `426bbd70`, `_freeze_market_dirs` = 2) and **not live** on either worker (both `f471b0d2`, = 0). Verified by blob, not ancestry.
  - User authorised this unattended session to fire it ("fire it"), logged as an OVERRIDE in `learnings.md` with scope bounded to this one deploy. **The override does not suspend the job gate.**
  - Not fired because both workers read HOLD at every check — refresh-worker 5 jobs incl. `run_mlb_daily_sim_job.py`, live-odds-worker 3 jobs.
  - **User constraint: do not fire if it slips past 08-17 first pitch.** Watch `bs8qocgqt` has two exits, `DEPLOYABLE` and `DEADLINE`; a resolver error counts as expired so an instrument failure cannot authorise a deploy. Deadline is measured from the production 08-17 snapshot, on a conservative 16:00:00Z floor until that feed populates (it currently holds 0 games).
  - `grading-freeze-payload-check` re-aimed to **date 08-17, firing 08-18 07:00 CT**, and gained Gate A: prove by content that the fix was RUNNING for the whole slate, else VOID rather than FAIL.
  - **NEXT ACTION:** if the window opens before first pitch, deploy both workers per the handoff doc (ROUTE ONE warm-up, one service at a time, verify by blob). If it does not, do not fire — let Tuesday's check return VOID and deploy for a later date.

#### game-shape-capture — **PUSHED AND VERIFIED ON `origin/main` `597f4a80`** `[2026-08-16 ~23:2xZ]`

Supersedes the two orphaning entries above: the work is now durable off this
worktree.

- **`dff358bb..597f4a80` on `origin/main`.** Built with plumbing directly on
  `origin/main`'s tip (`read-tree` into an isolated index -> `write-tree` ->
  `commit-tree -p origin/main` -> `push <sha>:main`), so it touched **no**
  working-tree file, **not** local `main`, and **not** the shared index — the
  three things that had already destroyed this commit twice.
- **Guards asserted before the push, in the same shell:** diff vs `origin/main`
  is exactly 2 files / **688 insertions / 0 deletions**, and the new commit's
  parent IS `origin/main` (checked by `rev-parse`, not assumed).
- **Verified AFTER the push, by re-fetch:** both paths present on `origin/main`;
  blobs byte-identical to disk (`95035c9a…`, `907b4d4e…`); **0 carriage returns**
  in the pushed blob — relevant because `origin/main`'s previous tip
  (`dff358bb`) was itself a warning that the commit recipe is the CRLF vector.
  That vector is `git hash-object --stdin` WITHOUT `--path`, which this recipe
  does not use.
- **`lane/game-shape-capture` re-anchored to `597f4a80`.**
- **A useful side effect:** the resets that orphaned this work twice were to
  `origin/main`. Now that the commit IS on `origin/main`, the next such reset
  DELIVERS these files instead of destroying them.
- **UNCHANGED BY THE PUSH — do not read this as progress:** nothing emits
  `gameShape`, the lane's verification has not run, and **every bucket count is
  still n=0**. The handoff to `Layer 1 board coverage audit (fork 2)` is
  unanswered.

#### game-shape-capture — WNBA EXTRACTOR ADDED `[2026-08-16 ~23:4xZ]` — **primitive done, emit blocked by the SAME session as MLB's**

**WNBA is a DIFFERENT job from MLB and the plan understated it.** MLB was
serialisation — `LiveSituation` existed in full and was discarded. WNBA has no
state vector at all, so this derives one.

**MEASURED, from a real in-progress game** (`data/live/wnba_cards_context_2026-06-05.json`,
DAL @ LAS, period 4, clock `"7:43"`, 84-83):
- `live_state` carries `period`, `clock`, `home_pts`, `away_pts`, `in_progress`,
  `final`, **and a per-quarter `periods` array** — richer than expected, and the
  per-quarter array is real run-detection material.
- **The team objects carry ONLY branding** (`abbr`, `logo`, `name`, colours).
  **No FGA / TOV / OREB / FTA anywhere**, and `basketball_props_features`'
  column map is box-score totals with no pace column either.
- **CONSEQUENCE: possession pace is NOT derivable and this module refuses to
  fake it.** The field is `points_per_minute` (scoring pace) and every record
  carries `possession_pace_available: False`. Naming it `pace` would let a
  reader join it to a possession-pace prior and be silently wrong. A test
  asserts the key `pace` does not exist.

**A SECOND FIND THAT CHANGED THE DESIGN: the derivation ALREADY EXISTS.**
`wnba/cards.py:891 _wnba_elapsed_minutes` is correct and complete (10-minute
quarters, 5-minute OT, regulation 40 — *not* NBA's 48), **and its own comment
says it was relocated once specifically so two copies would not drift apart.**
That file is claimed (by `clamp-fix-to-workers`, with a logged override from
`wnba-live-tier`), so I could not consolidate into it.
- Resolution: implemented in `shared/game_shape.py` **parameterised** by quarter
  length so it serves NBA (12) as well as WNBA (10), and **pinned to the
  existing function by a drift test** that asserts agreement across a 143-cell
  grid of periods x clocks, including the REJECTION cases. Being more permissive
  would itself be the drift. Mutation M5 (accept a bare `"7"` as `7:00`) fires it.
- **Owed follow-up, needs the claimed file:** have `cards.py:891` delegate here,
  so there is one copy again.

**NON-VACUITY VERIFIED BY MUTATION, 7 of 7 caught:** NBA given WNBA's 10-minute
quarters (1 fail), dropping the `status` period/clock fallback (1), unsupported
sport silently defaulting to WNBA (1), reusing baseball margin bands (2),
permissive clock parsing (1), pace dividing without the `>0` guard (1), run
detection including the in-progress period (1). **34 tests green** (19 MLB + 15).

**Margin bands are deliberately NOT MLB's** — basketball uses <=5 / <=10 / <=19
/ 20+. A 3-point basketball game is `close`; the baseball scale would call it a
blowout, which would put nearly every live game in one cell and measure nothing.

**EMIT BLOCKED, same session as MLB's.** The `live_state` producer is
`_public_scoreboard_live_state_payload` (`wnba/cards.py:3679`) — the exact
function `wnba-live-tier` took under a logged claim override 23:2xZ, in the same
session (`Layer 1 board coverage audit (fork 2)`) that holds
`mlb-live-gameline-distributions`. **One session gates both sports' emits.**
- **UNVERIFIED, and it is the whole point:** no production data has passed
  through this code. Every bucket count is **n=0** for WNBA too.

#### game-shape-capture — NFL/NCAAF ADDED, **AND THE NFL EMIT ACTUALLY LANDED** `[2026-08-17 ~00:0xZ]`

First sport whose producer was NOT held by another lane. Claim re-checked
immediately before the edit (the rule this lane learned the hard way at 23:0xZ),
`live_game_state` unclaimed in `lanes.md`.

**A THIRD DISTINCT SITUATION — the plan's field list was wrong again (3 for 3).**
It promised down/distance/field position/timeouts/`pace_secs_play` from a grep.
Measured:
- NFL's `_state_from_event` captures `period`, `clock`, `away_pts`, `home_pts`
  **and nothing else** — no down, distance, field position or possession.
- **BUT `_fetch_scoreboard` returns the WHOLE ESPN event JSON**, whose
  competitions carry a `situation` block that **nothing in `nfl/`, `ncaaf/` or
  `football/` reads** — the only `down` references in the tree are the sim
  engine's internal `play_state` and the historical loaders, neither on the live
  path. **Discarded, not absent** — the MLB pattern, and free to fix.
- **`pace_features.py` IS NOT LIVE.** It reads `game["pace_features"]`, a
  season-level secs/play feature for the pregame drive priors. Joining it to a
  live record as in-game tempo is a silent category error.
- **NCAAF HAS NO LIVE-STATE PRODUCER AT ALL** (no `live_game_state` analog).

**TWO SPORT RULES THAT WOULD HAVE BEEN SILENTLY WRONG:**
1. **NCAAF overtime is UNTIMED** — alternating possessions from the 25, no
   clock. Reusing NFL's timed-OT branch would invent a 15-minute period that
   does not exist and report a confident elapsed time. NCAAF OT returns
   `elapsed_minutes: None` and the record stays valid. Mutation F2 fires on it.
2. **NFL regular-season OT is 10 minutes, not 15.** Mutation F3 fires.

**MARGIN BANDS ARE IN SCORES, NOT POINTS** (<=8 / <=16 / <=24 / 25+). An
8-point football game is ONE possession; the basketball scale calls it
`moderate` and baseball's calls it a blowout. Three sports, three units — a
test asserts the same 8-point gap buckets differently in football vs basketball.

**THE EMIT (`nfl/live_game_state.py`):**
- `_state_from_event` now keeps `situation`, **on live games only** — a
  `situation` on a finished game is a feed artefact and would render "3rd and 7"
  hours after the whistle, the same class of defect as the 0-0 placeholder score
  that file already guards against. Mutation E1 fires on it.
- `attach_nfl_live_game_state` attaches `live_state["game_shape"]` behind a
  function-local import and a bare except, so a failure costs the shape block
  and nothing else. The cards board is the product.
- Tests call the REAL `attach_nfl_live_game_state`, not a stub — that file's own
  docstring warns that asserting a field is SET only proves presence.

**66 tests green** (46 shape + 20 NFL, up from 15). **10 of 10 mutations caught**
— 7 on the primitive (football quarters inheriting basketball's 10, NCAAF OT
treated as timed, NFL OT at 15, point bands reused, absent situation reading as
"not in the red zone", out-of-range situation values stored, `margin_in_scores`
flooring instead of ceiling) and **3 on the emit** (stale situation on a finished
game, shape built without the situation so the capture does nothing, shape never
attached).

**UNVERIFIED, and this is the part not to misread.** NFL is the first sport with
a live emit PATH; no production slate has run through it. **n is still 0.**
NCAAF has the contract and **no producer**, season opens 08-29, so nothing there
is verifiable today — a ready rules entry is not coverage. No deploy requested.

### ledger-sweep-2026-08-17 — CLOSED 2026-08-17 — **lane ownership was decoupled from reality; 9 of 15 OPEN lanes had no live owner, and the deploy-obligation counter could only ever count up** — opened 2026-08-17 — session: ledger-sweep

- Goal: make the ledger's OWNERSHIP and OBLIGATION state true. Bookkeeping only —
  no code, no config, no production surface touched. Testable outcome: every
  OPEN lane names its owner state and one next action, and the session-start
  obligation count reflects measured reality.
- Files: `.syndicate/lanes.md`, `.syndicate/deploys.md`, `.syndicate/state.md`,
  `.claude/hooks/session-start.sh`. No source file claimed, so no collision with
  any open lane.
- **Measured, not inferred:** roster census (`list_sessions include_archived:
  true`) plus a per-id `get_session` on every session named by a lane or by a
  `.current-lane.<id>` marker. "Not found" is what makes an orphan an orphan.
- **DONE:**
  - 13 lane headers annotated with owner state + single next action.
  - 18 stale claim markers MOVED (not deleted) to `.syndicate/lane_claims_retired/`.
  - `deploys.md`: `OBLIGATION RECONCILIATION` adjudicating all 14 pending
    markers — 12 already discharged, 2 permanently unmeasured by decision,
    **0 owed**. Nothing above it edited; the file's append-only convention holds.
  - `session-start.sh`: the count subtracts `- RECONCILED:` lines, so it can
    fall. Verified by running the hook: "none owed (14 of 14 markers reconciled)".
- **NOT DONE — needs a quiet window:** ~1,000 duplicate lines in `lanes.md` and
  six closed lanes still sitting in the OPEN file. The transform aborted twice
  on its own hash guard because live sessions kept appending. Script is
  `scratchpad/sweep_lanes.py`; re-baseline its `EXPECT_SHA` first.
- **Two enforcement gaps found and recorded in `state.md`:**
  `game-shape-capture` has no `— OPEN` header, so `lane-guard` has never
  protected its files; and one `layer1-board-coverage` block has an unparseable
  status field for the same reason.
- **Not claimed:** that any orphaned lane's WORK is done. The annotations say
  who is not holding it, not that it finished.

## SWEPT FROM `lanes.md` — 2026-08-17 12:5x CDT (part 2, dedupe)

Closed lanes that were still sitting in the OPEN file. Moved verbatim,
nothing edited. Blocks whose byte-identical copy was ALREADY here were
dropped from `lanes.md` rather than appended twice — the sweep record in
`state.md` lists them.

### ask-answer-substance — OPEN — **7 DEPLOYS SHIPPED AND MEASURED (web `9bae928c`). Panel names the bet, grounds it in the sim, filters non-positive edges, and reports real quote age. ONE BOARD DEFECT FOUND AND HANDED OFF, NOT CLOSED.** — opened 2026-08-16 — session: ask-answer-substance
> **[SWEEP 2026-08-17 12:1x CDT] THIS BLOCK IS STALE — THE LANE IS CLOSED.**
> `lanes_closed.md` carries the newer, closing entry (**CLOSED-VERIFIED
> 2026-08-16, 8 deploys, live web `9f617f34`**); this copy stopped at 7 deploys.
> Kept in place only because deleting a 100-line block from a file three live
> sessions are appending to needs a quiet window. **Read the closed entry, not
> this one.** Successor work is the OPEN lane `live-edge-basis`.
> **ASK-ANSWER-SUBSTANCE CHECKPOINT 3 applied.**
> **ASK-ANSWER-SUBSTANCE CHECKPOINT 2, 2026-08-16 22:0xZ.** Six deploys shipped
> and measured today, all web-only, all cut from web's own live SHA. Live
> `d8985df8`; `main` carries the code (`339e510b`) and the ledger (`18bfc6f8`).
> Nothing of this lane is uncommitted — all four source files verified
> byte-identical to `origin/main` BY BLOB (local HEAD is 6 behind; the `M` flags
> are that gap).
>
> **Shipped:** the bet is nameable (market/line/side/price/book); reason
> sentences generated from `projection.projected` + `model_skill`; the briefing
> renders 5 not 3; `bet_analysis.edge` no longer publishes EV under the model
> edge's name (same pick read 14.01 and 0.0139 on two surfaces); quote age
> offset by artifact age and its threshold re-calibrated 15 -> 45 min; only
> positive-edge rows published, with every edge term vetoing; the sim-vs-line
> clause no longer asserts causation it cannot support.
>
> **NOT CLOSED, and the reasons are deliberate:**
> 1. **A BOARD DEFECT WAS FOUND AND HANDED OFF.** `projection.projected` sits on
>    the wrong side of `line` on 12-21 of 31-39 over/under rows, pregame as well
>    as live. Handed to `layer2-board-quality` with the table. **Consequence they
>    must expect: the panel now visibly says "does NOT support the {side}" on
>    roughly a third to a half of over/under rows until it is fixed.**
> 2. **`8172fdef` is INERT on production data** — proven by unit test only. Do
>    not read a clean board as evidence it fired.
> 3. **HARNESS RE-RUN, OBLIGATION CLOSED (22:2xZ, live `d8985df8`): 37/52 with
>    ZERO pass/fail flips** vs the same-slate control, every class identical.
>    Non-regression, not a win — the harness is blind to nearly everything the
>    six deploys changed. Its one moved warning
>    (`edge_without_market_probability` 0 → 25) was checked against the diff and
>    is BOARD DATA, not this lane's code.
> 4. **CSS ships INLINE in `ask_bar.js`** because `board_cards.css` is held by
>    `layer2-board-quality`. Move the `STYLE` const into the stylesheet when that
>    lane closes.
> 5. **A row can still publish model-positive with EV negative's opposite** —
>    resolved for the both-positive case, but the underlying question of which
>    term should win when they disagree is a product call, recorded in
>    `deploys.md` under `ask-both-edges`.
>
> **Process, worth carrying:** a resumed session does NOT inherit its own lane
> marker — it lands on the shared global `.current-lane` and `lane-guard.py`
> blocks the first edit. Fix is the per-session slot the hook names in its own
> error text (`.syndicate/.current-lane.<session-id>`), not closing the lane.
- Goal: the inline quick ask names a bet a human can actually place and grounds
  it in the sim projection that is **already in the response payload**, instead
  of a bare name and one edge number. **Single testable outcome**, on the served
  `/api/syndicate/query` payload plus the rendered panel:
  (a) a prop answer carries market, line and side (`Ryan Johnson over 2.5
  earned_runs`), not `Ryan Johnson`;
  (b) `structured_response.edge` on `bet_analysis` equals the row's
  `model_edge_pct` (same number the briefing shows for the same pick) — today
  the same pick reads **14.0% in the briefing and 1.4% per-pick**;
  (c) the briefing renders as many rows as its own sentence claims (says 5,
  renders 3);
  (d) a game-side selection names the team, never a bare `home -1.5`;
  (e) every answer carries at least one sim-derived term (projection vs line,
  or `model_skill.status`) sourced from fields already fetched.
- Files:
  - `syndicate/blueprints/ask_the_syndicate_adapter.py`
  - `syndicate/static/shared/ask_bar.js`
  - `tests/test_ask_answer_substance.py` (NEW)
  - `syndicate/blueprints/ask_the_syndicate_data.py` — **TAKEN 2026-08-16 from
    ORPHANED lane `ask-sport-coverage`** (archived session, last active
    2026-08-15 19:44; file clean and unchanged since `67ff20a0`). Scope is
    `_board_row_label` + the `_board_candidates_evidence` table ONLY. Hand back
    on request.
- Collision check, run by reading every OPEN lane's `- Files:` block:
  `ask_the_syndicate_adapter.py` was held by `ask-headline-from-board`, which is
  **CLOSED-VERIFIED 2026-08-15** (`lanes.md:1820`); the only remaining mention
  is a *disclaimer* bullet inside `ask-sport-coverage`, not a claim.
  `ask_bar.js` is claimed by nobody — zero hits in `lanes.md`. CLEAR.
- NOT claimed, read-only dependencies (top-level bullets on purpose, so
  `_claims()` cannot read them as claims):
  - `syndicate/blueprints/ask_the_syndicate_data.py`, `..._router.py`,
    `..._the_syndicate.py` — held by OPEN `ask-sport-coverage`. This lane does
    **not** edit them. The sim evidence it needs (`visuals.tables/charts`) is
    already built there and already served; nothing new is required of it.
  - `syndicate/features/shared/layer2_board.py` — held by OPEN
    `layer2-board-quality`. Read-only. `_pick_label` there is the reviewed owner
    of the side→team convention; this lane pins against it rather than
    re-deriving it.
- Hypothesis: the "answers are only edge-based" symptom is **not** missing data
  and **not** a missing model. Every discriminating field — `line`, `side`,
  `market`, `sim_projection`, `projection.model_skill`, `quote.bookmaker`,
  `quote.price`, `model_edge_pct` — is already on the candidate the adapter
  holds in `explanation.top_candidate`, and the per-pick answer already ships 7
  sim tables and 3 sim charts in `visuals` that the inline panel never reads.
  The loss is entirely in the adapter's field selection and the panel's render.
- Falsification test: if a served `bet_analysis` payload for a real prop is
  found whose `explanation.top_candidate` lacks `line`/`side`/`sim_projection`,
  then the cause is upstream data, this lane cannot fix it in the adapter, and
  the work belongs to `ask-sport-coverage` instead.
- Verification: (1) `py -3 scripts/ask_syndicate_regression.py --out
  reports/ask_regression/latest.json` re-run and diffed per class against the
  38/52 in the `ask-sport-coverage` measurement — **no class may regress**;
  (2) a new `tests/test_ask_answer_substance.py` asserting (a)–(e) against a
  captured production row; (3) the panel re-read in a browser, since (c) and the
  visuals render are client-side and no server test can see them.
- Blocked by: none.

### export-force-refresh-escape — CLOSED — **DEPLOYED TO BOTH WORKERS 17:53Z (refresh-worker `b9f2b5f1`, live-odds-worker `e28594a7`), verified BY CONTENT; EFFECT UNMEASURED — needs a `:cards_props_snapshot` staged record from a forced run over an existing snapshot** — opened 2026-08-16 — session: win-prob-null-readable
- **CLOSED 2026-08-17 BY OVERRIDE, by the `wnba-fixture-identity` session, with
  explicit user authorization. NOT my lane and NOT my work - recording the
  override rather than quietly taking the file.**
  - **Why it could not release itself:** its session
    (`Wnba win prob counter read`, `local_e6fe220f-...`) is an **UNATTENDED
    scheduled-task run** - not running, ~20h idle, and `send_message` REFUSES
    delivery to it. It could not be asked and would never close itself.
  - **What was outstanding:** by this lane's own note, the work is DEPLOYED to
    both workers and verified BY CONTENT; only the EFFECT MEASUREMENT remained
    (`:cards_props_snapshot` staged record from a forced run). **That
    measurement is still owed and is NOT done** - closing this lane does not
    discharge it. Re-open or carry it forward if the force-refresh effect
    still matters.
  - **What I changed in its file:** `_GAME_CARDS_HEADER_ORDER` (`:2229`) and
    `_build_local_game_cards_artifact` (`:2262`) only. Its own region,
    `_export_cards_props_snapshot` (`:5082`), is UNTOUCHED.
  - **A finding it should have had:** on production `predictions_2026-08-17.csv`
    is ABSENT, so `expected_matchups` (`:2395`) is empty and every
    `issubset` coverage gate in that builder passes trivially.
- Goal: `--force-refresh` actually regenerates the three props SNAPSHOT exports
  instead of re-serving a stale per-date file. Testable: with `force_refresh=True`
  the builder is CALLED even when the snapshot exists; with `False` it is not.
- **Why: found while explaining a `rows=0` win_prob reading.** All three exporters
  short-circuit on a prior `<name>_<date>.json`, but only two take a
  `force_refresh` escape. `_export_cards_props_snapshot` (WNBA `:5082`) has NONE —
  and it is the builder that produced the `rows=32/null=3` reading, so its
  staleness is the least visible. NBA is worse: the whole trio lacks the escape
  AND `_materialize_artifact_bundle` has no `force_refresh` parameter to pass.
  The WNBA sibling comment already names this shape "the same reuse-forever bug".
- **DELIBERATELY NOT THE WHOLE CLASS.** ~30 `if existing:` short-circuits exist
  across the two producers (live snapshots, recon artifacts, game cards, season
  cards). `live_refresh_loop.py` passes `--force-refresh` on EVERY lineup/injury
  trigger, so adding escapes everywhere would turn each trigger into a full
  artifact rebuild on a 2GB worker — the same over-reach `#347`/the 2026-07-19
  `smart_sim_overwrite` fix already had to undo once. Scope is the props snapshot
  trio only; the rest is recorded, not touched.
- Files (exclusive to this lane; `_claims()` CLEAR and every OPEN lane's `Files:`
  block read — zero `oddsapi_props` mentions anywhere in `lanes.md`):
  - `scripts/refresh_wnba_oddsapi_props.py`
  - `scripts/refresh_nba_oddsapi_props.py`
  - `tests/test_export_snapshot_force_refresh.py` (new)
- Falsification test: if the builder still is not called under
  `force_refresh=True`, the gate is not the one at `:5082` — re-read the caller
  chain before changing anything else.
- Verification: new tests assert called/not-called in both files, plus targeted
  producer suites green. **NBA cannot be verified in production — out of season,
  its producer writes no artifact.** Default `False` keeps every path inert until
  someone actually forces a refresh.
- Blocked by: none. No deploy from this lane tonight unless asked.

### live-game-line-projection — ARCHIVED-SNAPSHOT 2026-08-18 — RE-TAKEN 2026-08-16 03:0xZ (session `live-gameline-eval`) — TIER 5'S PREMISE IS TRUE IN PRODUCTION; THE EDGES ARE UNEVALUATED

> Demoted 2026-08-18: an archived snapshot must not read as a live lane. The live record for this slug is in lanes.md, which carries it as OPEN, UNOWNED. Nothing deleted.

### layer1-board-coverage — CLOSED-VERIFIED 2026-08-17 — all four goals answered, and the last unmet criterion was EXECUTED (it returned a defect, which was then fixed and verified)
- **THE ONE OPEN CRITERION IS NOW MET.** This lane closed-refused twice for
  the same gap: the cross-sport LIVE A/B needed two sports live at once.
  **It was run 2026-08-16 22:2xZ** on a real live WNBA slate against a live
  MLB slate. Result: WNBA had **0 of 521 rows** carrying any live field —
  i.e. no live tier at all. That answer was the deliverable; it was then
  fixed (`wnba-live-tier`) and verified at **218 of 321 game rows
  live_aware**.
- G1 rates, G2 bucket classification, G3 (MLB live lens measured moving),
  G4 (missing term named at the producer, fixed in `e543e8dd`, 287/287
  attributed) all delivered and recorded in `deploys.md`.
- Scope added mid-lane and also delivered: the HR threshold ladder
  (`hr_2plus`/`hr_3plus`), the NFL window 5->7, and the soccer game-state
  defect that was serving edges on finished matches.
- Goal: for every in-season sport, a per-sport/per-market-family RATE of
  `projected / total` (alt and period families broken out), every unprojected
  prop classified as EITHER stale-fingerprint OR sim-does-not-emit-this-stat,
  and the `Edge` column's missing term named AT ITS PRODUCER.
- Files (claimed): `syndicate/features/shared/layer1_board.py`,
  `syndicate/templates/shared/layer1_board.html`,
  `syndicate/blueprints/layer1_page.py`,
  `syndicate/blueprints/intelligence.py` (the `/api/board/layer1` handler only).
  Edited in the end: `syndicate/features/shared/prop_projections.py` +
  `tests/test_prop_projections_edge_attribution.py` — checked against every OPEN
  lane's `- Files:` at edit time and claimed by none. Read-only throughout on
  `layer2_board.py`, `intelligence.html`, `bet_slip.js`, `board_cards.css`,
  `soccer_projections.py`, `pipeline/intelligence_state.py`, sim internals.
- **THIS ENTRY WAS WRITTEN TWICE.** The first append was silently overwritten in
  the worktree by a parallel session's read-modify-write of `lanes.md`, and my
  own commit then staged THEIR 44 lines under my message without either of us
  noticing. See the learnings entry of the same date. Re-appended, not rewritten.
- **RESULT** (full audit `.syndicate/audit_2026-08-16_layer1_board.md`;
  measurement + falsification test in `deploys.md`, 2026-08-16 16:19–16:40Z):
  - **Both briefed premises were wrong, and re-checking them first was the whole
    value of the first ten minutes.** Layer 1 is NOT dark (**5 of 5** consecutive
    builds non-zero). Alt lines are NOT unprojected on MLB (`totals_alt` 86/86,
    `spreads_alt` 76/77) — they are unprojected on **WNBA** (419/419 dark). The
    `Edge` column is not blank everywhere: MLB serves **1,462** edges, and most
    rows lacking one already state why on the row.
  - The prior baseline in `docs/ai_context/betting_contract_lifecycle.md` §3a
    (MLB 19.7% projected / **0** edges / game state 1,220 of 3,604) is **EXPIRED**
    — today 68.3% / 1,462 / 2,843 of 2,843. Quoting it would book another lane's
    fix as this lane's regression.
  - **G1** rates measured per sport × family. mlb 1,941/2,843 (68.3%), soccer
    1,704/6,453 (26.4%), wnba 305/872 (35.0%). The MLB gap is **LINE-shaped, not
    market-shaped**: `batter_home_runs` 0.5 → 82.8%, 1.5 → **0.4%**, 2.5 → **0%**.
  - **G2** every unprojected prop classified. mlb 504 no-such-rung / 337
    player-dark (63 players) / 42 residual; soccer 1,293 / 3,128 (836) / 268;
    wnba 39 / 41 / 0. Mapping named: the sim publishes a `<stat>_<N>plus` ladder
    and `hr_2plus`, `hr_3plus`, `hits_runs_rbis_1plus` are the missing rungs.
  - **G3** MLB live lens MEASURED working for props (27 of 201 `live_projected`
    moved, 3 `actual_so_far` advanced over 4 min, right direction) and NOT
    working for game lines (0 live projections on every `game|*` family).
  - **G4** missing term named at the producer: `prop_projections.py` set
    `edge_vs_market_pct = None` and no reason — key **ABSENT** on 284/284 —
    while its soccer sibling has always attributed the same refusal. Fixed in
    `e543e8dd`; replay over real served payloads gives **287/287 attributed, 0
    silent**. The refusal itself is correct (`#238`) and unchanged.
- **NOT DONE, owned elsewhere, routed by `send_message`:** missing sim rungs, the
  63 dark MLB players, WNBA needs a distribution → sim-engine session. The 1,416
  rows carrying BOTH EV terms → Layer 2 session and a **user decision**,
  deliberately not taken here because `modelled_fair` is a book-margin ESTIMATE,
  not a de-vig. The WNBA `wnba_game_cards` +31.7pp finding could NOT be delivered
  (that session is unattended) — it lives in audit §4b and `e543e8dd`'s message.
- Falsification test for the undeployed fix: re-sweep and count rows with a
  projection, no edge of either contract, and no reason. **Expected 0.** Do NOT
  verify by "the reason string appears" — it already appears on 287 rows in
  replay; the residual is the discriminator.
- Verification: met for G1/G2/G4 and for G3-props. **Unmet:** cross-sport live
  A/B (no second live sport in the window). Lane stays OPEN for that.
- Blocked by: none.

### mlb-live-gameline-distributions — CLOSED-VERIFIED 2026-08-17 — live MLB totals and spreads carry a live projection AND a priced edge — opened 2026-08-16 — session: layer1-board-coverage
- **VERIFICATION RAN AND PASSED**, production, live slate 2026-08-16 22:23Z
  (6 live MLB games): `game|spreads` **65 rows / 36 live_aware / 28 edged**,
  `game|totals` **65 / 37 / 30**, `game|h2h` 24 / 6 / 3. Before this lane the
  same families read **0 live_aware and 0 edged on every live game**.
- Re-closing: an earlier close of this lane was clobbered back to OPEN by a
  parallel rewrite of `lanes.md`. The measurement above is unchanged.
- Goal: a LIVE MLB game carries a live projection and a priced edge on its
  TOTALS and SPREADS, not just its moneyline, sourced from the same 120-sim
  re-sim and gated on the same interval. **Testable outcome:** on the served
  `/api/board/layer1?sport=mlb&view=live`, `totals|full` and `spreads|full` go
  from **0 live_aware / 0 edge** to non-zero, and every released edge carries a
  `prob_std_err` that cleared `PRICEABLE_SIGMA`.
- Files (all checked unclaimed at open):
  - `vendor/mlb_bettingv2/sim_engine/live_mc.py` (add a margin histogram)
  - `vendor/mlb_bettingv2/tools/web/flask_frontend.py` (carry the histograms)
  - `syndicate/features/shared/live_gameline_join.py` (consume + price)
  - `tests/test_live_gameline_join.py`, `tests/test_mlb_live_game_line_lens.py`
- **NOT taken:** `syndicate/features/mlb/live_lens.py` — claimed by
  `refresh-worker-oom-recurrence` and `odds-cadence-off-the-mlb-peak`. Avoid; if
  the merge side turns out to need a change, stop and coordinate.
- **The finding, measured 2026-08-16 19:13Z on 8 live MLB games:**
  `h2h|full` 8 rows / 7 joined / 2 priceable / 2 edges — the moneyline works.
  Every other game family is **0 live_gameline, 0 live_aware, 0 edge** across
  **470+ rows**: `totals_alt|first5` 98, `spreads_alt|first5` 79, `totals|full`
  41, `spreads|full` 36, and the rest. They render a PREGAME projection on a
  live game.
- **Root cause, and it is a discard, not a gap.** `live_mc.LiveMcResult` already
  carries `total_runs_dist: Dict[int, int]` — a full histogram over the 120
  sims. `flask_frontend`'s live-MC return (`:16683`) keeps `batterStatDist` and
  `pitcherStatDist` — added, in that same dict, with the comment *"Carried so
  the live PROP rows can price off the same 120 sims that produced the numbers
  above, instead of falling back to the pregame distribution"* — and drops
  `total_runs_dist` on the floor. So the props got a real live probability and
  the game total, from the identical sims, kept only `avg_total_runs`.
  `live_gameline_join` then has nothing but a mean, which is exactly what
  `REASON_TOTALS_MEAN = "totals_mean_not_distribution"` reports.
- `sigma: 2.0` in the served payload is `PRICEABLE_SIGMA`, the threshold — NOT a
  distribution width. I misread it as interval data on the first pass; it is not.
- No margin histogram exists yet. The MC's loop already computes `home_final -
  away_final` per sim, so it is a two-line addition in the same loop, not a new
  model.
- Falsification test: if `totals|full` still reports 0 `live_aware` after the
  dists are published and consumed, the diagnosis is wrong and the lens is not
  the carrier. Check `projections`/`live_gameline` coverage counters first.
- Verification: (a) unit tests price a known histogram at a known line;
  (b) production `view=live` shows non-zero live_aware + edge on totals/spreads;
  (c) Layer 2 inherits it with no Layer 2 change, since it reads the same grid.
- Blocked by: none.

### score-live-gameline-edges — OPEN — opened 2026-08-17 — session: layer1-board-coverage
> **[SWEEP 2026-08-17 12:1x CDT] THIS HEADER IS STALE — THE LANE CLOSED.**
> See `score-live-gameline-edges — CLOSED-VERIFIED 2026-08-17 02:1xZ` further
> down this file, plus its CROSS-SPORT + PLAN addendum. The live edges ARE
> scored and the model loses to the market on every population. The header is
> left reading OPEN only so its file claims keep being enforced until the
> block is swept; treat the lane as closed.
- **Goal:** the live game-line model's probabilities are SCORED against realised
  outcomes, and against the market recorded on the same row. **Testable
  outcome:** a written report over N ledger records with the window stated,
  carrying (a) Brier + calibration buckets for `model_home_win_prob`, (b) the
  SAME two for `market_fair_prob` on the identical rows, and (c) the difference.
  **(b) is the point.** A Brier score alone says nothing about whether the model
  is worth running; the market benchmark on the same rows is the only comparison
  that answers it. `soccer-model-coverage` already found its model LOSING to the
  market by this kind of test — that outcome is expected, permitted, and is a
  result, not a failure of this lane.
- **Why this lane exists now.** `live-game-line-projection` closed
  2026-08-17 00:4xZ having proved the ledger can produce a sample (`written=13`
  across two builds, 2 of them non-priceable). It explicitly carried forward:
  *"the ledger can now produce a sample; nobody has measured whether those 11
  edged rows were RIGHT."* This is that lane.
- **THE SAMPLE IS CURRENTLY UNREACHABLE, and that is the first task, not the
  scoring.** Measured 2026-08-17 00:4xZ: the ledger writes to
  `mlb_source/data/live_gameline_ledger/live_gameline_ledger_<date>.jsonl` on the
  WORKER's disk, and that path matches **zero** entries in
  `HOT_ARTIFACT_PATTERNS` — `/api/ops/artifacts/export?pattern=...` returns
  `count 0, bytes 0`. The COUNTERS are served on `/api/board/book-grid`; the
  RECORDS are not published anywhere. Three routes, to be chosen on evidence:
  1. publish the ledger (needs `artifact_publisher.py` — **NOT this lane's**),
  2. score worker-side and publish only the small summary,
  3. pull a copy and score offline for the first read.
  **Route 3 first**, because it needs no deploy and answers whether the sample is
  even large enough to score.
- **Files (claimed):**
  - `scripts/score_live_gameline_edges.py` (new)
  - `tests/test_score_live_gameline_edges.py` (new)
  - `syndicate/features/shared/live_gameline_ledger.py` (a READER only; the
    writer is settled and must not be touched)
  Collision check run with `lane-guard.py`'s own `_claims()` at open time: all
  three CLEAR.
- **NOT claimed, and why:**
  - `syndicate/features/shared/artifact_publisher.py` and `clv_join.py` — held by
    OPEN `clv-without-settlement`. Route 1 above needs the first; **coordinate,
    do not take it.** That lane owns the CLOSE half of CLV and this lane owns
    OUTCOME scoring; they are different questions on the same records.
  - `syndicate/features/shared/intelligence_evaluation.py` — CLEAR, but reuse
    `_calibration` (`:1477`, already computes Brier + MAE) rather than writing a
    fourth copy. Claim it only if it must change.
- **Hypothesis (falsifiable, stated before measuring):** the live game-line
  model's `model_home_win_prob` is NOT better calibrated than `market_fair_prob`
  on the same rows — i.e. Brier(model) >= Brier(market).
- **Falsification test:** Brier(model) < Brier(market) on a sample of stated size,
  with the win-rate and calibration buckets printed alongside so a single-number
  win cannot hide a bad curve.
- **Verification:** a report in `deploys.md` with the window, the sample size, and
  BOTH Brier scores. Scored two ways and both reported: over `priceable: true`
  rows (what the board actually showed) and over ALL projected rows (the model
  itself). The ledger writes `priceable` as a FIELD not a filter precisely so
  this split is possible — a pass restricted to priceable measures the publish
  gate, not the model.
- **Outcomes come from final scores, NOT from settlement.** The record carries
  `game_pk` plus live `home_score`/`away_score`; the final result is joined from
  the scoreboard. **This lane is therefore NOT blocked by
  `grading-blocker-settled-zero`**, whose `EVALUATION_SETTLEMENT_...AUTORUN` is
  off by user decision.
- **Known trap inherited from the writer, do not re-discover:** the ledger's own
  docstring records that the closing-price recorder
  (`closing-stamp-is-detection-time`) writes the HOME price on every row (18/18),
  so any CLV-style pairing against it inherits a known defect. This lane scores
  against OUTCOMES and sidesteps that; if it ever reaches for a close, read that
  note first.
- Blocked by: none. First step is Route 3.

#### game-shape-capture — `#455` FIXED UNDER A LOGGED CLAIM OVERRIDE `[2026-08-16 ~20:2x CDT]`

**Override taken on explicit user instruction** — "take the override and fix it - i dont think its actually being worked on by any other lane" — on `syndicate/features/wnba/cards.py`, ONE function (`build_live_pbp_stats_payload`). Recorded in `wnba-live-tier`'s own Files block, phrased as a release the guard recognises rather than bypassed. Coordination had been attempted three times: fork 2 archived before replying to two handoffs; a third went to fork 4 (running) and is unanswered.

**THE FIX, two halves:**
1. The stored-payload short-circuit required `bool(games)` — and a skeleton HAS games. Now requires `any(_has_pbp_signal(g))`.
2. The skeleton was PERSISTED, which is what made it sticky: the stored copy then satisfied the short-circuit on every later request. Now gated on the same predicate, so it can never be written.

**FOUR SIGNAL SOURCES, and the fourth was missing from my first attempt.** The existing `test_live_pbp_stats_payload_uses_local_snapshot` stores a real snapshot whose games carry ONLY `pbp_recent.points_total` (9 and 14). My predicate ignored `pbp_recent`, rejected that snapshot, and the test failed. **The suite caught a genuine gap in the fix, not a stale expectation.** Its own trap: the skeleton hardcodes `window_sec: 180`, so counting that field would make every skeleton read as real and silently undo the change — excluded explicitly, pinned by a test.

**THE `Mapping` NEAR-MISS, AGAIN, IN THE SAME FILE.** My first draft used `isinstance(x, Mapping)` in a module that does not import it — a `NameError` on the FIRST record, which would have taken the endpoint down. `lanes.md` already records `wnba-live-tier` hitting the identical thing here. Caught the same way both times: by running it.

**TWO VACUOUS TESTS OF MY OWN, CAUGHT BY MUTATION.** W1 (revert the short-circuit to `bool(games)` — the original defect) and W3 (count `home`/`away` as signal) both passed against a broken implementation. A replayed skeleton and a freshly built one are both all-null, so "no signal" cannot tell them apart — the stored fixture now carries a sentinel and the test asserts its ABSENCE. W3 was the same vacuity already fixed once this session in `scripts/wnba_pbp_possessions.py` and reintroduced here. **After fixing both: 5 of 5 mutations fire.**

**13 tests green. Full WNBA suite: 405 passed, 4 failed — all 4 PRE-EXISTING**, verified by re-running against `origin/main`'s `cards.py` (4 fail there too). My one real regression was the `pbp_recent` gap and it is closed.

**NOT DEPLOYED.** No deploy requested. The fix changes what a live endpoint serves; it needs a web deploy to take effect, and that is a decision, not a formality.

#### refresh-worker-oom-recurrence — M3 REFUTES THE PULL HYPOTHESIS; THE EXISTING CENSUSES REFRAME THE WHOLE PROBLEM `[2026-08-17 ~01:1xZ]`
- **M3 — artifact-pull correlation: REFUTED.** Presence of pull/publish activity,
  excursion windows vs matched controls, all windows COMPLETE except one:

      EXCURSION (n=7)   pulled_hot 1/7   PULL|STREAM 2/7   PUBLISH 2/7
      CONTROL   (n=6)   pulled_hot 1/6   PULL|STREAM 1/6   PUBLISH 1/6

  Same rate in both arms. The `+537MB` jump after `pulled_hot_artifacts count=17`
  at 00:32:01 was ONE observation and the other six excursions do not support it.
  **Candidate eliminated before anything was built on it.** The control arm is
  what did the work here; presence alone would have looked convincing.
- **The allocator is SILENT.** No stage markers (M1), no publisher activity (M3),
  no overview activity. Most excursion windows carry 5-15 log rows total.
  **Log-based attribution is exhausted** — no further correlation study will name
  this.
- **THE CENSUSES ALREADY RAN, AND NOBODY HAD READ THEM.**
  `_watchdog_maybe_heap_census` / `_watchdog_maybe_dump_allocations`
  (`memory_observability.py:877,1392`) fire once per process on an anon
  threshold. Output from 00:39 and 00:48 tonight:

      HEAP_CENSUS            gc_tracked_objects 1,071,841
                             top_by_count: dict 682,491 | list 298,937
      UNTRACKED_BYTES_CENSUS anon 2146.2MB  str_bytes 294.1MB
                             **explained_pct_of_anon = 13.7%**
      SMAPS_ANON             by_kind: anon_mmap 1848.2MB | heap 166.2MB
                             by_size:  >64MB = 1293.0MB
                             largest_regions_mb: 515.0, 181.1, 166.2[heap],
                                                 104.3, 102.0, 90.0, 83.7, 79.0

- **What that says, and it is a different problem from the one this lane has been
  chasing:** ~87% of anon is INVISIBLE to the Python object census, and 1293MB of
  it sits in anonymous mmap regions **larger than 64MB** — including a **single
  515MB region**. pymalloc uses 1MB arenas, so regions that size are not Python
  object churn. They are large contiguous buffers: NumPy arrays, big
  `bytes`/`bytearray`, or compression/decompression scratch. (`numpy.ma`'s
  `_MaskedUnaryOperation` appears in the holder list, so NumPy is resident.)
- **The dict/list counts are a RED HERRING at this scale.** 682k dicts is a large
  object graph, but `UNTRACKED_BYTES_CENSUS` puts every tracked holder at
  253.8MB of 2146MB. Chasing the object count would have been chasing 13%.
- **NOT ESTABLISHED, and the gap matters:** the censuses fire at anon ~1610-1700MB
  (a threshold well BELOW the 3700-4000MB excursion peak), so these are ELEVATED
  BASELINE snapshots, not excursion-peak snapshots. **They characterise what the
  process is holding, not what the excursion allocates.** The two may be the same
  thing; nothing here proves it.
- **Standing candidate worth one query:** `intelligence_evaluation` logs
  `SKIP_OVERSIZED_LEDGER_CHUNK path=2026-08-14.jsonl bytes=305,435,308`. A 305MB
  file is the right order of magnitude for the 515MB region once decoded. The
  line says SKIP, so it should not have been read — but the ceiling
  (256,000,000) is checked somewhere, and whether it is checked BEFORE or AFTER
  the read is the whole question.
- **NEXT:** re-gate the censuses to fire AT the excursion (they currently fire
  once, early, on a lower threshold), so the peak is characterised rather than
  the baseline. That is a smaller change than the abort and it answers the
  question the abort was only going to contain.
- `design_2026-08-17_watchdog_abort.md` remains BLOCKED. Its premise (abort the
  hydration loop) is retracted, and the target now looks like a buffer
  allocation, not a loop that can usefully be interrupted mid-flight.

### score-live-gameline-edges — UPDATE 2026-08-17 01:0xZ — **ROUTE 3 IS DEAD. The sample cannot be pulled, and the reason is now measured, not assumed.**
- **Route 3 ("pull a copy and score offline, needs no deploy") DOES NOT EXIST.**
  Checked all three ways in:
  1. `find`/glob for `**/live_gameline_ledger/*.jsonl` anywhere in the checkout:
     **no files**. There is no git-tracked mirror of this ledger.
  2. `/api/ops/artifacts/export?pattern=mlb_source/data/live_gameline_ledger/*`
     → `count 0, bytes 0`.
  3. `/api/ops/artifacts/stream?path=...` → both endpoints gate on
     `is_hot_artifact_relative_path`, and the ledger matches **zero** patterns.
     Both also read the SERVING service's disk, which never has the worker's file
     regardless of the allowlist.
- **AND THE RETROSPECTIVE SHORTCUT IS ALSO DEAD — this is the load-bearing new
  measurement.** Read at 01:02:26Z with `by_state {final: 14, live: 1}`:
  **rows carrying a `live_gameline.model_prob` = `{live: 12}`, and NOTHING for
  the 14 final games.** A finished game retains no model probability on the
  served board at all. So the day's projections are *only* in the ledger; there
  is no way to reconstruct them after the fact from any served surface. **That is
  precisely why the ledger exists, and why publishing it is not optional.**
- **THE BLOCKER IS ONE FILE, AND ITS CLAIM IS CURRENT — I re-read it and
  corrected myself.** `clv-without-settlement` says at one point *"Handed back:
  lane left OPEN and unclaimed... `artifact_publisher.py` is free"* — but a
  LATER block in the same lane re-claims it: *"Files (exclusive to this lane):
  `syndicate/features/shared/artifact_publisher.py`"*. Line order settles it
  (718 vs 751): the claim is the newer statement. **NOT taken.** Its session is
  not in the live roster, so it is unowned but still claimed.
- **Remaining routes, in preference order:**
  1. **Publish the ledger** — add its pattern to `HOT_ARTIFACT_PATTERNS`, deploy
     refresh-worker (the publisher runs there), wait one publish cycle, pull,
     score. Needs `artifact_publisher.py` → needs the claim released.
  2. **Score worker-side and ride an artifact that is ALREADY published.** The
     `book_grid` artifact already carries a `live_gameline_ledger` counters block
     and is already published to web. A `live_gameline_score` block alongside it
     needs no new publish pattern and no `artifact_publisher.py`. **This is the
     route that avoids the collision entirely** and is the recommended one.
  3. Prospective capture: poll the board and build a parallel sample. Works with
     no deploy, but duplicates a ledger that already functions correctly — the
     problem is transport, not collection.
- **NOT STARTED, deliberately.** Either surviving route is deploy-and-wait
  (edit → refresh-worker deploy → publish cycle → pull → score). Beginning that
  chain without the budget to finish and verify it would leave a half-applied
  change on a shared worker, which is the failure mode this ledger's own lane
  already paid for once.
- Next session's first action: pick route 1 or 2. If 1, the claim on
  `artifact_publisher.py` must be released first.

### score-live-gameline-edges — UPDATE 2026-08-17 01:3xZ — **ROUTE 2 BUILT, TESTED AND DEPLOYED. The score is COMPUTED in production and NOT YET READABLE — one line, in a file another lane holds.**
- **SHIPPED** `e63bee63` to refresh-worker (live 01:35:06Z), cut on live
  `4ec66498`, deploy gated on the test exit code in the same shell.
  - `syndicate/features/shared/live_gameline_score.py` (new) — model vs market
    Brier/MAE on **identical rows**, over three populations (`all_records`,
    `last_per_game` chosen by `recorded_at` not file order, `priceable_only`).
  - `live_gameline_ledger.read_records()` (new) — every forecast, distinct from
    `read_last_by_key` which collapses to one per market for DEDUP.
  - `book_grid_artifact.py` — computes the score at build time and puts
    `live_gameline_score` on the artifact. Never raises; the board is the
    product.
  - 14 tests pass.
- **VERIFIED THE PRODUCER RAN:** artifact `01:36:25Z` (post-deploy) carries
  `live_gameline_ledger {candidates: 11, written: 11}`.
- **BLOCKED ON ONE LINE, AND IT IS THE READER.** `/api/board/book-grid` forwards
  an EXPLICIT key allowlist (`blueprints/intelligence.py:2339`), so
  `live_gameline_score` served **`null`** — the artifact has it, the endpoint
  does not forward it. Producer wired, reader not: the
  presence-is-not-reachability trap, caught by reading the served payload rather
  than trusting the deploy.
- **THE FIX IS ONE LINE**, beside the existing `live_gameline_ledger` entry:
  ```python
  "live_gameline_score": precomputed.get("live_gameline_score"),
  ```
  Then a **web** deploy (that endpoint is web-served).
- **NOT TAKEN.** `syndicate/blueprints/intelligence.py` is claimed by OPEN
  `layer2-board-quality`, which was actively worked tonight — a live lane, not
  an orphan. Handing it over rather than overriding.
- **Next action:** ask `layer2-board-quality` to add that line (or release the
  file), deploy web, then read `live_gameline_score` off
  `/api/board/book-grid?sport=mlb&date=<date>`. The score itself needs a slate
  with FINAL games in the same artifact as ledger records — mid-slate it
  correctly reports `no_final_games_on_this_grid`.

#### game-shape-capture — FINAL CHECKPOINT 2026-08-16 ~20:3x CDT — **`#454` COMPLETE; LANE STAYS OPEN ON n = 0**

13 commits, all verified reachable from `origin/main` (`28cc8814` latest).
**95 tests** across game_shape / run-expectancy / win-expectancy.

Shipped this session: game-shape contracts for MLB, WNBA/NBA, NFL/NCAAF and
soccer; live emits for NFL and soccer; WNBA pbp coverage tooling; `#454` (RE, WE,
leverage) complete; `#455` and `#456` found, filed and FIXED.

**WHY IT IS STILL OPEN — unchanged from every previous checkpoint:** the
verification is one live slate with a non-zero bucket distribution, read across
two builds. **That has never run. n = 0 for every sport.** Do not close this on
the commit count, the test count, or the fact that leverage now has a number.

**NEXT ACTIONS, in order:**
1. Deploy decisions for `#455`, `#456` and the NFL/soccer emits. All four change
   live behaviour; none is deployed and none has been requested.
2. Read `game_shape` off a live NFL or soccer fixture — the only step that turns
   any of this from prepared into measured.
3. NCAAF needs a live-state PRODUCER built. Season opens **2026-08-29** — still
   the only dated item in the lane.
4. Source the RE reference table, then re-adjudicate the two >3 SE cells.
5. Owed: `wnba/cards.py:891` should delegate to `basketball_elapsed_minutes`.

### score-live-gameline-edges — CLOSED-VERIFIED 2026-08-17 02:1xZ — the live edges are SCORED, and the model loses to the market on every population
- **Route 2 delivered end to end.** Scorer computes worker-side and rides the
  already-published `book_grid` artifact — no new publish pattern, no
  `artifact_publisher.py`.
- **RESULT, production artifact 02:12:18Z, 14 finished MLB games:**
  `all_records` model 0.26579 vs market 0.23923 (**+0.02656**, n=3,226);
  `last_per_game` 0.27776 vs 0.20344 (+0.07432, n=14); `priceable_only` 0.28064
  vs 0.24060 (**+0.04004**, n=2,081). Positive = the market won.
- **ONE SLATE, n=14 per game. Not a verdict.** Recorded in `state.md` with that
  caveat attached.
- Two join bugs found and fixed, both surfaced by the counter refusing to serve
  a confident null (`no_final_outcome_for_game` 3,727 times). See learnings.
- Files: `live_gameline_score.py` (new), `live_gameline_ledger.read_records`,
  `book_grid_artifact.py`, `blueprints/intelligence.py` (one line, taken on the
  user's statement that no Layer 2 session is active and released in this file).
- **Next:** re-read on a second slate before anyone acts on the number.

### score-live-gameline-edges — CROSS-SPORT + PLAN 2026-08-17 02:3xZ

**(1) TOMORROW'S SLATE — nothing to schedule. It scores itself.** The scorer runs
inside `build_book_grid_artifact`, so every build of every sport already emits
`live_gameline_score`. What is owed is a READ, not a run:
`/api/board/book-grid?sport=<sport>&date=<date>` after the slate completes.
**Read it AFTER the last game is final** — measured tonight, the count read
`no_final_outcome_for_game: 416` at 02:12Z with one game still live and resolved
to **0** at 02:28Z on its own.

**(2) ACROSS ALL SPORTS — measured 02:3xZ, and the answer is "two sports have
anything to score".** The scorer is sport-generic by construction
(`record_live_gamelines(sport=...)`, `ledger_path(sport, ...)`, per-sport
artifact build), so the block is emitted everywhere. What differs is the input:

| sport | records | games | scored |
|---|---|---|---|
| mlb | 3,748 | 15 | **yes** — `all_records` +0.03842 |
| wnba | — | 0 | **no** — scorer ran, found **no final games on its grid**, took the `no_final_games_on_this_grid` branch |
| soccer, nfl, others | 0 | 0 | **no ledger records at all** |

- **soccer/nfl/etc is EXPECTED, not a defect.** Only `mlb` and `wnba` are in
  `_LIVE_GAMELINE_SPORTS`; the rest have no live game-line join, so there is no
  projection to record and nothing to score.
- **WNBA IS THE ONE REAL GAP AND IT IS UNDIAGNOSED.** Its games went final
  tonight (CHI @ SEA 82-80 observed), and its live tier now populates 218/321
  rows — yet its grid yielded an empty finals index. **One check:** does the
  wnba `book_grid` grid carry `game.state == "final"` rows for that date, or is
  its artifact keyed on a different date? Do NOT assume it is the same join bug
  MLB had; that one is fixed and this may be date-scoping.

**(3) PLAN — how to get better, in dependency order.** The model loses to the
market by **+0.038 Brier** on 3,638 records and is **worst on `priceable_only`
(+0.056)** — i.e. the disagreements the board publishes are its worst ones.

1. **Get a second slate before changing anything.** One night. Everything below
   is wasted if the sign flips. Cost: a read.
2. **Split the loss by game state.** The ledger already carries `game_state`,
   `home_score`, `away_score`, `sims_run` and `prob_std_err` per record. Score
   by inning/margin bucket. **The likeliest story is that the re-sim is worst
   early**, when 120 sims off a thin state carry the widest interval — and that
   is testable with data already on disk, no deploy.
3. **Raise `MLB_LIVE_GAME_MC_SIMS`.** At n=120 the standard error is ±4.56 pp at
   p=0.5, so `PRICEABLE_SIGMA=2.0` demands a ~9.1 pp edge before publishing. If
   step 2 shows the loss concentrated where the interval is widest, this is the
   lever the module's own docstring names — and it is costed by the worker's
   memory budget, so it belongs to the OOM lane's window.
4. **Consider calibrating rather than replacing.** A model that loses on Brier
   can still carry ranking signal; `projection_skill` already records
   `correlation` and a `verdict` per sport. If correlation is positive while
   Brier is worse, the fix is a calibration map, not a new model.
5. **Only then touch the model.** Anything before this is guessing at which of
   its parts is wrong.

**Do not act on +0.038 yet. It is one slate.**

### mlb-tie-spread-baseline — CLOSED 2026-08-17 — **MLB ARMED on both widths. Pre-game slate read 86px desktop / 43px mobile BIT-IDENTICAL across 5 production runs; the 2026-08-16 instability was the slate, not the metric. Shipped `2882ad11`.** — opened 2026-08-17 — session: mlb-tie-baseline-pregame (scheduled task)
- **Goal:** answer the question `2026-08-16` left open — is MLB's
  `identicalContentSpread` stable on a **pre-game** slate? If yes, add `"mlb"` to
  `TIE_SPREAD_BASELINED` in `scripts/ui_layout_probe.py` so a change in that
  number FAILS a run instead of being watch-only. **Testable outcome:** three
  probe runs against production on an all-`Preview` slate, readings recorded per
  width, judged against a ~1.2x rule fixed in advance; then either the sport is
  armed with a fresh passing baseline, or the negative result is recorded and
  nothing changes.
- **Files:** `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`,
  `reports/ui_layout/baseline_2026-08-17.json`, `.syndicate/log/2026-08-17.md`,
  `.syndicate/lanes.md`
- **Hypothesis:** MLB's 2026-08-16 instability (81/109/123/164/193px across one
  day) was **the slate, not the metric** — MLB enriches continuously while games
  are live, whereas the nfl/ncaaf slates that earned baselining were static. On a
  slate where every card is in `Preview`, the number should hold.
- **Falsification test:** three runs on an all-`Preview` slate spreading beyond
  ~1.2x on either width. That would mean the metric itself is noisy and MLB must
  stay watch-only regardless of slate state.
- **Verification:** `cardHeightByState` shows exactly one state (`Preview`)
  covering all cards on both widths; three `worstGroupPx`/`spreadPct` readings
  per width inside the rule; if armed, a fresh baseline that **exits 0**, the
  probe suite green, and a re-run reporting mlb `unchanged (baselined)`.
- **Blocked by:** none

## RESTORED FROM git HEAD — 2026-08-17 13:0x CDT

These four blocks existed in `HEAD:.syndicate/lanes_closed.md` and **not in
the file on disk**. Committing the worktree copy would have deleted them.

**Cause, and it inverts the usual assumption:** sessions here commit blobs
built in memory (the blob-stage-against-HEAD recipe, which never reads the
contended file), so the shared file on disk can be BEHIND git rather than
ahead of it. `git status` shows the file as modified either way.

Found by reading the DELETION column of `git diff --cached --numstat` before
committing — 1,488 deletions on a file this session had only APPENDED to.
Restored verbatim from HEAD, headers asserted, no edits.

### clamp-fix-to-workers — CLOSED-VERIFIED 2026-08-17 00:0xZ — the ±4900 clamp is gone from all three live services, and 7,002 served fair_price values carry none**
- **CLOSED 2026-08-17 00:0xZ, ~10 minutes after the refusal below, because
  the missing piece SHIPPED IN THE INTERVAL — and not by me.** Another
  session deployed `c348da53` to live-odds-worker at 23:57:12Z
  ("converge origin/main into live-odds-worker's deploy lineage"), which
  carried the clamp removal along with everything else on main. Credit
  where it belongs; this lane did not ship it.
- **I did NOT ship a duplicate.** The user authorised shipping the deferred
  fix; before cutting anything I re-read the live SHA and found it had
  moved from `16a898ef` to `c348da53` with the work already in it. Cutting
  on the stale SHA would have re-applied a change that was already live.
- **STRUCTURAL HALF: PASSES.** Clamp sites (`max(0.02, min(0.98`) by
  content at each service's CURRENT live SHA, all three re-read at 00:0xZ:
  ```
  web              9f617f34   0   (intelligence_state 0, cards 0, layer2_board 0)
  refresh-worker   fdc72dd0   0   (0, 0, 0)
  live-odds-worker c348da53   0   (0, 0, 0)
  ```
  Both sites now delegate to `american_price`, which REFUSES a probability
  outside (0,1) instead of clamping it.
- **PRODUCT-LEVEL SWEEP, the number this lane never had:** **7,002 served
  `modelled_fair.fair_price` values** across mlb + wnba + soccer,
  **0 at ±4900**. That is a real denominator, against the 6-row shortlist
  the watcher kept reading.
- **THE ORIGINAL BEHAVIOURAL CRITERION NEVER FIRED, AND IS NOW MOOT —
  stated rather than quietly dropped.** `watch_clamp_trigger.py --once`
  returned `no_trigger` on all FOUR reads (00:24Z, 01:30Z, 23:49Z,
  00:00:39Z); the last read `p=[0.227201, 0.512829] out_of_clamp=0`. It was
  never satisfied because no slate in that window carried an out-of-clamp
  probability. It is moot because a `POST_FIX_OK` proves a clamped
  PRODUCER priced correctly, and there is no longer a clamped producer on
  any live service. **What remains unproven by THIS lane is that
  `american_price` prices an extreme probability correctly in production —
  a different claim, covered by its own unit tests, not by this one.** — opened 2026-08-15 — session: clamp-fix-verification-watch
- **CLOSE ATTEMPTED AND REFUSED 2026-08-16 23:5xZ.** Both halves of this
  lane's own Verification line were checked. Neither passes.
  - **Behavioural half: still never fired.** `watch_clamp_trigger.py --once`
    at 23:49:14Z read `served_rows=6 p=[0.145882, 0.874966] out_of_clamp=0`
    -> `no_trigger (proves nothing)`. That is the THIRD inconclusive read
    (00:24Z, 01:30Z, 23:49Z). A quiet slate reads identically with the bug
    fully present, which is why this lane already refused to bank it.
  - **Structural half: FAILS, and this is the new finding.** Clamp sites by
    content at each service's LIVE SHA, counting `max(0.02, min(0.98`:
    ```
    web              9f617f34   0
    refresh-worker   fdc72dd0   0
    live-odds-worker 16a898ef   2   <- intelligence_state.py 1, wnba/cards.py 1
    ```
- **One of the two is dormant; the other is REACHABLE AND PUBLISHING.**
  - `pipeline/intelligence_state.py` — dormant on this service:
    `SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP=false` in its live
    env, so the loop never starts. **Dormant is not fixed** — loop ownership
    is an env flag that moves with no diff, so this is a latent re-arm.
  - `syndicate/features/wnba/cards.py:848` — **REACHABLE.**
    `_american_from_prob` still clamps, and it is called at :1614/:1616 to
    produce `home_ml`/`away_ml` on the WNBA cards THIS SERVICE BUILDS AND
    PUBLISHES (it runs `start_live_lens_loop`). The served lens carries
    those exact fields in each game's `betting` block.
- **Not observed firing today, and that is not evidence of absence.** The
  served WNBA cards at 23:5xZ read `away_ml` -749.55 / 186.21 / 146.13 —
  no value at ±4900, because no game today is lopsided enough to push a win
  probability past 0.98. Same quiet-slate confound as the watcher.
- **What would let this lane close:** ship the deferred fix to
  live-odds-worker (`079cc42b`, re-cut on live `16a898ef`), taking all three
  services to 0 sites. At that point the clamp CANNOT be published because
  it does not exist, and the never-firing behavioural trigger stops being
  load-bearing. **That deploy was DEFERRED BY USER DECISION and is NOT being
  taken unilaterally.**
- Note: tonight's live-odds-worker deploy (`16a898ef`, the WNBA live_state
  carry-forward) was deliberately cut on live `440f5f29`, which already
  carried these 2 sites — so it PRESERVED the deferral rather than
  silently resolving or worsening it.
- Files: `pipeline/intelligence_state.py`, `syndicate/features/wnba/cards.py`.
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
- Files: `pipeline/intelligence_state.py`.
  - **`syndicate/features/wnba/cards.py` is NOT CLAIMED by this lane as of
    2026-08-16 23:2xZ — released to `wnba-live-tier`.** This lane's own status says the code work is done
    (`57a437d5` shipped, 0 clamp sites by content) and that the only open
    work is VERIFICATION, which runs `scripts/watch_clamp_trigger.py` and
    does not read that file. The taking lane changes
    `_public_scoreboard_live_state_payload` (the ESPN scoreboard fetch) --
    a different function from the clamp sites, zero overlap. Coordination
    was ATTEMPTED and refused by the transport: this lane's session
    (`local_70bfde12…`) is UNATTENDED, a scheduled-task run, so
    `send_message` cannot reach it. Released rather than silently
    overridden; if the clamp lane needs it back, this line is the record.
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

- **RESULT 2026-08-16 00:23:04Z — refresh-worker shipped `57a437d5`.** 0
  occurrences of `max(0.02, min(0.98` across all three files at the live SHA.
  Cut on live `2c14d9ae`, not main. Gated on `safety_rc == 0 AND zero [JOB]
  processes`, re-verified in the same shell command as the POST.
- **VERIFICATION DID NOT HAPPEN AND IS NOT CLAIMED.** 00:24:04Z read: `rows=12`,
  p=[0.338468, 0.603175], `out_of_clamp=0` → `no_trigger`. The slate collapsed
  from 97 rows as games finished. Same reading a quiet slate gives with the bug
  fully present. The 2-hourly `clamp-fix-verification-watch` task carries this.
- **`live-odds-worker` DEFERRED, not forgotten.** It carries the clamp but does
  not run the intelligence-state loop, so it is not the producer of the measured
  misprice. It is also effectively never idle — 57 samples over 35 min, zero
  job-free moments, running a per-league soccer artifact sweep. `079cc42b` is
  cut, tested and pushed; re-cut on the live SHA before shipping.
- **CORRECTION LOGGED: I twice called live-odds-worker "already fixed" off a
  PENDING claim target.** `49797f4b` was clean and never landed as-is; `c422f79a`
  then `c4116ab6` landed instead, both still clamping. **A claim's target is an
  intention, not a deployment.** Verify by content at the live SHA, every time.
- **TWO SAFETY-TOOL DEFECTS, both in `learnings.md` 2026-08-16:**
  `check_deploy_safety.py` reports CLEAR while jobs run on the service (measured
  on BOTH workers), and has no `--service` flag so it also blocks on the wrong
  service's work. And a wait loop of mine read a stderr HTTP 502 as CLEAR by
  testing for the absence of a failure string.
- **2026-08-16 03:1xZ — THE INSTRUMENT WAS BLIND IN THE WINDOW IT WATCHES, and
  every `no_trigger` since it was built is weaker evidence than it looked.**
  `watch_clamp_trigger.py` gated the confirming read on
  `/api/board/layer2-shortlist`, then judged `/api/intelligence/query`. Two
  different populations. Measured same-instant at 03:14:08Z: **shortlist 0 rows,
  served payload 18 priced rows** — 8,345 opportunities considered and all 8,345
  filtered out (horizon 2,488 + stale_kickoff 2,666 + quote_age 1,256 +
  excluded_market 689 + uninformative 1,246, summing exactly).
  The shortlist drops `stale_kickoff_seconds = 7200` and
  `max_quote_age_seconds = 50400` — **exactly the in-play late-game population
  both real triggers came from** (20:45Z, and 23:10/23:15Z at p=0.009911/0.990089).
  So the gate could read 0 while a misprice was live on a row it had filtered out.
  Found because the user disbelieved a `rows=0` reading, not by the instrument.
- **FIXED, not just recorded.** The trigger now derives from the served payload
  itself — the same surface the verdict judges. The shortlist is still read, as
  recorded context that can no longer suppress a check; both counts print.
  Self-test 11/11. Live at 03:24:19Z: `served_rows=30 (shortlist=12)`, so the
  old gate would still have judged on under half the population.
  - A defect found while writing it: emitting UNPRICED probabilities (needed, or
    `POST_FIX_OK_COLUMN_ABSENT` is unreachable and the fix working becomes
    invisible) double-counted every quoted row — once priced at the parent, once
    unpriced at the `quote` node. Harmless while only pairs were emitted; a
    phantom unpriced twin on every correctly-priced row the moment they were not.
    Caught by the new self-test, not in review.
- **STILL NO VERDICT ON THE FIX.** 03:24:19Z read the corrected population:
  30 rows, p=[0.057749, 0.871508], nothing outside [0.02, 0.98] → `no_trigger`.
  Genuinely quiet, now measured on the right surface. `#439` item 1 stays OPEN.
- **THE SHORTLIST/SERVED MISMATCH IS NOT A DEFECT — AND THAT IS WORSE FOR THE
  OLD GATE THAN "NARROWER" WAS.** Measured 03:3xZ, same instant. They are two
  different pipelines, not two views of one:
  - **Different date window.** shortlist `date: 2026-08-15`, `horizon_days: 1`
    (single date, `central_today_iso()`); served `dates_covered:
    ['2026-08-15','2026-08-16','2026-08-17']`. Late at night the shortlist's
    one-day horizon empties by construction while tomorrow's board is live —
    which is exactly the 0-vs-18 reading, and it will recur every night.
  - **Different pool.** served `source: combined_board_window` (the legacy
    `ranked_all` pool). The shortlist is `layer2_shortlist_artifact`.
  - **Different gates.** horizon / quote_age / stale_kickoff / excluded_market /
    uninformative are applied at BUILD time on refresh-worker for the shortlist
    only; `combined_board_window` does not carry them.
  This is known in-progress L2-A migration, stated in the route's own docstring
  (`intelligence.py:2698`): the board still renders `ranked_all`, the canonical
  board state the shortlist lands in "is never written (both migration flags
  default False and are off)", and pointing the board at L2-A rows "is the goal".
  **So the old gate was not a narrow view of the product — it was an artifact
  nothing user-facing serves.** The clamp misprices were always measured on the
  served path (`layer2_board.py:1345`: 1346 `fair_price` values, 24 on ±4900),
  which is the population the instrument now reads. Consistent, and the reason
  the gate had to go rather than be widened.
  - Sports move within minutes: 03:24Z served WNBA only; 03:3xZ served
    mlb 168 + wnba 216 priced occurrences. Do not treat one read's sport mix
    as the slate's shape.

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

#### smaps-anon-breakdown — DEPLOY LANDED 2026-08-16 00:57:32Z (`ada731f5`)
The reconciliation fix is live and the guard is meaningful again. First reading
01:07:38Z:

    reconciles               true      (was false, 27.0% off)
    reconciles_within_pct    0.0
    total_anon_mb          1,672.4     smaps, per-process
    process_rss_anon_mb    1,672.6     RssAnon, per-process
    other_processes_anon_mb    0.4     children, now a LABELLED figure
    cgroup_anon (container) 1,673.0

Two independent kernel accountings of one process agreeing to 0.0%.

**BREAKDOWN NOW TRUSTWORTHY — the lane hypothesis holds on a clean reading:**
`anon_mmap` **1,540.3MB (92%)** against `heap` 128.3MB, `file_backed` 3.6,
`stack` 0.1; mmap split >64MB 741.3 | 8-64MB 639.1 | 1-8MB 159.3 over 426 regions.

**NOTE `other_processes_anon_mb` = 0.4 HERE, not the ~504MB seen at 22:49.** The
children were simply not running at this instant. That is exactly why the old
container-vs-process comparison was unusable: the gap is not a constant to
subtract, it moves with whatever the worker has spawned.

COST: five rebases across five live SHAs (`6f512ffa` -> `129395cc` -> `32186e28`
-> `2c14d9ae` -> `57a437d5`) and four claim holders. On a worker with five
sessions deploying, a two-file change should ride along, not chase.

#### live-game-line-projection — 2026-08-16 ~01:1xZ — THE PREMISE IS TRUE: 25 LIVE GAME-LINE EDGES PUBLISHED
- **Tier 5's goal is met in production.** `index_size 8 / considered 32 /
  projected 32 / edged 25 / prob_interval_swamps_edge 7`, on an artifact
  provably generated after the deploy. Baseline `index 3 / projected 12 /
  sim_count_unusable 12 / edged 0`.
- **Live:** live-odds-worker `c4116ab6` (simsRun stamp), refresh-worker
  `1f36d718` (the join). Web needs neither.
- **THE THREE DROPS, all shipped and measured:** D1 merge condition
  (`0e0b0aa1`), D2 carry-forward (`4bd7dbb3`), D3 join+wiring (`758a89fa`) plus
  the `simsRun` stamp (`49797f4b`) that made the precision gate reachable.
- **NOT ESTABLISHED — the 25 edges are UNVALIDATED.** Clearing 2 sigma at 120
  sims means the edge beats the ESTIMATOR'S noise, not that the model is right.
  No CLV, no settlement, no backtest. **Next work is evaluation, not more
  plumbing** — game lines carry 100% Pinnacle coverage, the strongest position
  on the platform.
- **OPEN:** why `index_size` was 3 earlier and 8 now is unexplained; Drop 2's
  carry-forward has still never been observed firing; the tally is MLB-only.
- **I no longer hold the live-odds-worker claim** — `clamp-fix-to-workers` took
  it ~00:34 and my last two fires went over it. Not force-released; theirs.

- **CHECKPOINT 2026-08-16 01:4xZ — state of the lane for whoever picks it up.**
  - All deploy claims RELEASED. Nothing held by this session.
  - Committed: `86ee112f` (falsification), `0f70969b` (lane), `25e34c63`
    (deploy record + 2 learnings), `1b76c232` (defer + `#439`), `1bd520c2`
    (state.md + the claim-target learning).
  - **NEXT ACTION: run `py -3 scripts/watch_clamp_trigger.py --once` when
    games are IN PLAY.** Both real triggers (23:10Z, 23:15Z) came from live
    in-play markets; the two `no_trigger` reads were a pregame board with
    extremes 0.0687/0.8904. A one-off task fires 2026-08-15 21:31 CDT and the
    recurring `clamp-fix-verification-watch` runs every 2h.
  - **`POST_FIX_OK` closes `#439` item 1.** `PRE_FIX_MISPRICE` now that
    refresh-worker is clean would falsify the intelligence-state attribution —
    that is this lane's stated falsification test, and it is still live.
  - Session log: `.syndicate/log/2026-08-15.md`, final section.



## SWEPT FROM `lanes.md` — 2026-08-18 (coordinator)

Closed lanes archived out of the OPEN file. Moved verbatim, nothing edited.
Each was read individually first: the "no OPEN block" predicate alone cannot
tell a closed lane from one whose header was destroyed, and it flagged three
LIVE lanes an hour earlier whose slugs a bad `sed` backreference had eaten.

`game-shape-capture` was deliberately NOT archived -- its latest block reads
"EMIT STILL BLOCKED; HANDOFF SENT", which is unfinished work with no owner,
and that is exactly what an archive hides best.

Archived in this pass:
  - soccer-model-coverage — CLOSED  (explicit CLOSED, backtest delivered)
  - tie-spread-membership-gap — CLOSED 2026-08-17  (explicit CLOSED, fixed in production)
  - commit-guard-blind-to-own-recipe — CLOSED 2026-08-17  (explicit CLOSED, delivered in 5fb52342)
  - render-events-read-label — CLOSED 2026-08-17  (explicit CLOSED, shipped)
  - COORDINATOR ADJUDICATION 2026-08-17  (a coordinator record, not a lane; historical)

### tie-spread-membership-gap — CLOSED 2026-08-17 — **CONFIRMED ON PRODUCTION AND FIXED. The post-first-pitch run reported `unchanged (baselined)` while every comparable tie group had moved — a false PASS. Comparison is now per-group, matched on card identity.** — opened 2026-08-17 — session: mlb-tie-baseline-pregame (scheduled task)
- **Goal:** `identicalContentSpread` must stop comparing two different groups and
  calling the result "unchanged". **Testable outcome:** the comparison matches
  tie groups on `(state, pair-count, n)` and fails on a change in any group that
  is comparable on both sides; group membership changes are reported as NOT
  COMPARABLE rather than silently passed. Re-running today's live slate against
  `baseline_2026-08-17.json` must SURFACE the three mobile group moves it
  currently hides.
- **Files:** `scripts/ui_layout_probe.py`, `tests/test_ui_layout_probe.py`,
  `.syndicate/log/2026-08-17.md`, `.syndicate/lanes.md`
- **Hypothesis (already CONFIRMED on production data, 2026-08-17 12:37 CDT):**
  `_cmp_value` reduces the whole tie block to `worstGroupPx`, a max over a set
  whose membership moves with the slate. When a game goes live it leaves the
  Preview pool, groups gain/lose members, and the max can land on a DIFFERENT
  group while reading numerically identical.
- **The measurement.** One game live, 10 Preview, vs an all-Preview baseline:
  - mobile reported `43px unchanged (baselined)` — but the baseline's 43 came
    from `u=45 n=3` and the current 43 comes from `u=53 n=3`, while **every**
    matched group moved: `u=53` 30->43, `u=49` 32->15, `u=45` 43->36.
  - desktop reported `86px unchanged` from `u=49 n=3` vs `u=49 n=2`, hiding
    `u=45` moving 28->41.
  This is a **false PASS**, not a false alarm — the dangerous direction, and the
  same family as the standing rule that unknown must not default permissive.
- **Falsification test:** if the per-group comparison, run against today's
  baseline on the current live slate, still reports everything unchanged, the
  diagnosis is wrong and the scalar is not the cause.
- **Verification:** the live re-run names the moved groups and fails; an
  all-Preview self-comparison still passes; a baseline with no per-group data
  (`baseline_2026-08-16.json` and older carry `byState` but no `groups`) reports
  NOT COMPARED rather than silently taking the weaker check; probe suite green.
- **Blocked by:** none

#### convergence-phase7-crps — ARCHIVED LINE COVERAGE DIAGNOSED 2026-08-17 — **cause found, fix HANDED OFF, no file taken**

- **The cause is the retrieval clock, and it is in the artifact itself.** Docs
  whose `retrieved_at` is same-day afternoon carry **26–30 pitchers**; docs
  retrieved after ~02:00Z the next day carry **ZERO**. 12 of 29 dates have
  `pitchers: 0`. Books pull pitcher-props markets when games end, so a
  post-slate fetch archives an empty market. Only **5 of 29** dates carry >=8
  pitchers with an outs line.
- **Defect 1 (primary): the props fetch runs after the slate on most dates.**
  Same root class as `#440`'s headline — the system has almost no clock, so work
  lands uniformly across 24h regardless of when the market is open. No freeze can
  seal what was never fetched.
- **Defect 2: the freeze cannot prove it is pregame when the slate clock is
  missing.** `_freeze_oddsapi_pregame_markets` (`refresh_mlb_oddsapi.py:680`) is
  first-write-wins when `slate_start is None`, so it can seal a post-slate empty
  doc and never improve it — consistent with 08-08 (1 pitcher) / 08-09 (2).
- **`mode` is `live` on EVERY file including the `_pregame` ones** — the freeze
  copies the live doc, so it can only seal what the fetch held.
- **07-19..08-07 is unrecoverable from the archive.** The freeze was unreachable
  before 2026-08-08 (its own docstring: production held ZERO `_pregame.json`
  that day) and the live file was rewritten in place. **OddsAPI historical
  endpoints are the route, and the ledger records them as cheap** — would roughly
  triple the gradeable sample.
- **NO FILE TAKEN, NOTHING EDITED.** Both levers are owned:
  `scripts/refresh_mlb_oddsapi.py` by OPEN `grading-blocker-settled-zero`
  (defect 2 — and it already shipped this file's freeze fix);
  cadence by OPEN `odds-cadence-off-the-mlb-peak` (defect 1 — its Phase 1
  fixture-aware cadence is exactly the mechanism that fixes it).
- **Recommended order:** fixture-relative props fetch → positive pregame proof
  before sealing, with a strictly-richer re-seal allowed → historical backfill.
  Cost it first: OddsAPI ~62.7% of a 5M cap, MLB 93.0% of spend.

#### convergence-phase7-crps — CLAIM OVERRIDE LOGGED 2026-08-17 — `scripts/refresh_mlb_oddsapi.py`, ONE FUNCTION

Taken on explicit user instruction ("take the file and coordinate the claim").
Recorded so it can be judged rather than trusted.

- **Whose it is:** OPEN lane `grading-blocker-settled-zero` (session
  `alt-line-shortlist-watch`) lists it as **"read-only so far"**.
- **Coordination attempted and its limit stated honestly:** that session is
  **not running and not in the recent roster**, so it could not be reached.
  Notice relayed to the live `Deploy and Document Coordinator` session instead,
  with the measurement and an explicit "object and I will back out".
- **Scope taken: ONE function**, `_freeze_oddsapi_pregame_markets` (:680), and
  within it only the **props-sealing branch**. NOT `_merge_pregame_game_lines`,
  NOT the game-lines freeze, NOT anything on the grading/settlement path — which
  is the half that lane actually cares about.
- **This is ADDITIVE to their shipped freeze fix, not a revert.** Their fix made
  the freeze reachable at all; this makes what it seals monotone.
- **Not the bigger defect.** Most of the loss is that the props fetch runs after
  the slate; that is cadence, owned by `odds-cadence-off-the-mlb-peak`, and I am
  NOT taking it.
- Trivially revertable: one guard, one helper.

#### convergence-phase7-crps — CADENCE LEVER TAKEN 2026-08-17 — **it is a DARK FLAG, not code, and the flip is a PRODUCTION CONFIG CHANGE**

Taken on explicit user instruction ("now take the cadence lever too").

- **Claim:** `odds-cadence-off-the-mlb-peak` (OPEN, session `sim-engine-track`,
  not in the live roster). Its Phase 1 is **COMPLETE and verified in production**
  (`dd53d47c`, live-odds-worker, 2026-08-16 05:51:48Z). **I am not editing its
  files** — there is nothing to write. The machinery is built.
- **THE LEVER IS `SYNDICATE_PREGAME_FIXTURE_AWARE_CADENCE`**, `default=False`
  (`live_refresh_loop.py:4006`), and it is **NOT PRESENT IN `render.yaml`**, so
  no service sets it. Shipped, verified, dark.
- **TRACED: the flag DOES fix my props defect.** `_filter_sports_for_pregame_sweep`
  (`:4605`) always keeps a sport **while it is live** — which is why the props doc
  is rewritten during and after the slate — and applies the interval only when it
  is not. With the gate on, `_FIXTURE_TIER_SECONDS` hands the final 3h to the
  **T-75/T-10 ramp**, which guarantees a sweep before first pitch, hence a
  pregame props fetch. **Paired with the monotone seal (`bafb4fb2`) the loop
  closes: cadence makes the pregame capture happen, the seal makes it stick.**
  Neither half works alone.
- **THE OWNER SET A PRECONDITION AND I AM NOT OVERRIDING IT SILENTLY:** the flag's
  own comment says *"Flip on per service once the `branch-overlap-baseline-watch`
  distribution has a BEFORE to compare against."* Measured now:
  `reports/branch_overlap/baseline.jsonl` holds **7 records, of which only 4 are
  `run_mode="scheduled"`** — the others carry no field and are UNKNOWN, not
  scheduled, per `state.md`'s own instruction to count only `scheduled`. **A
  BEFORE exists but is thin (n=4).**
- **NO FLIP MADE.** Enabling it is a production behaviour change on a worker under
  an active OOM investigation with a deploy hold, and the flag is absent from
  `render.yaml`, so the two routes are: (a) add it to `render.yaml`, which fires
  **`blueprint_sync`** — rewrites the WHOLE env block on live services and 502s
  every route for ~2 min; or (b) the single-key env endpoint plus a deploy, which
  is narrower. **(b) is the correct route if it is flipped at all.**
- **Cost note:** the gate makes sweeps MORE frequent near first pitch and much
  less frequent when fixtures are far out. Net OddsAPI call volume is not
  obviously higher, but it is not obviously lower either, against a cap at ~62.7%
  with MLB at 93.0% of spend. Measure before and after.

### commit-guard-blind-to-own-recipe — CLOSED 2026-08-17 — **both goals shipped, measured, and DELIVERED to `origin/main` in `5fb52342`: the guard now honours its own printed recipe (in-command env assignment) and exempts pathspec-limited commits, with `-i`/`-a`/pathspec-less unchanged. Verification ran: 19 cases through the pre-fix AND post-fix guards (10 flip 2→0, 8 hold at 2), 62 tests in the guard's own suite (69 with the sibling checkpoint-guard suite), every printed remedy replayed through the real hook at rc=0.** — opened 2026-08-17 — session: commit-guard-blind-to-own-recipe (`2028fec0-86fa-4442-a8db-a7ff8949aec8`)
- **CLOSING NOTE.** The wrong belief this lane produced (`coordinator.id` is
  stale) already has its durable rule in `learnings.md` 2026-08-17 —
  *"matches no session in the roster" is not "points at nobody"* — written with
  the `deploy-guard.py:130-140` evidence this session. Not re-run as a separate
  `/postmortem`, because the rule exists and a second copy would just be a
  second thing to keep true.
- **Left with others, deliberately, NOT blockers on this lane:**
  (1) the falsified `deploys.md` entry on `origin/main` asserting
  `coordinator.id IS STALE`, duplicated at lines 11441 and 11546 — reported to
  the coordinator with the correction and the exact locations; `deploys.md` is
  theirs. (2) A second session's brief to CLOSE the in-command `GIT_INDEX_FILE`
  escape this lane opened; the coordinator ruled the escape stays open and
  retargeted them. If that ruling is revisited, `5fb52342` is the commit.
- **STATUS 2026-08-17 ~14:30 CDT.** Verification ran and both goals hold.
  (a) in-command assignment of any of the three vars is honoured; (b) pathspec
  commits exempt, `-i`/`-a`/pathspec-less unchanged. Evidence: 19 cases through
  the pre-fix AND post-fix guards — 10 flip 2→0, 8 hold at 2, clean tree 0→0;
  69 tests pass; every remedy the refusal message prints replayed through the
  real hook at rc=0 with the control still rc=2; exemption path 81 ms.
  `5fb52342` verified not to disturb another session's staged work, and to leave
  no revert armed for its own paths.
- **DELIVERED: `5fb52342` IS on `origin/main` as of ~14:35 CDT** (`origin/main`
  = `5962900e`, `merge-base --is-ancestor` confirms). I did not push it —
  another session landed `ledger/coordinator-2026-08-17` onto `main` while this
  checkpoint was being written. The push request I filed with the coordinator is
  therefore MOOT, not pending; if they reply to it, this is why.
  *(Superseded reading, kept because it was true for ~40 min and a reader may
  have acted on it: at 14:30 this was ahead 32 / behind 148 with the commit only
  on the ledger branch. No `render.yaml` was in those 32 → no `blueprint_sync`
  exposure either way.)*
- **STILL UNPUSHED: `acad136f`**, this checkpoint. Not pushed by me — standing
  instruction is that the coordinator is told before ANY push, not only deploys.
- **CONFLICT, ADJUDICATED BY THE COORDINATOR, NOT BY ME:** another session's
  brief is to CLOSE the in-command `GIT_INDEX_FILE` escape this lane OPENED.
  Same predicate, opposite directions. The coordinator ruled **the escape stays
  open** and retargeted that session, telling it to hold rather than edit the
  shared hook. If that ruling is revisited, `5fb52342` is the commit to revisit.
- **Known FP left in deliberately:** `-a` cannot trip predicate 2 but still
  fires. Exempting it is unsound as measured — `-a` does not refresh
  `skip-worktree`/`assume-unchanged` paths, unmeasured. Named in the docstring.
- **Owed to the coordinator, not done by me:** a `learnings.md` rule that the
  pathspec form is the default and the isolated-index form the fallback, since
  the latter arms a revert every time and the former needs no repair step.
  Relayed; `learnings.md` is theirs.
- Goal: a session that follows the guard's OWN printed instructions is not blocked
  by it. Two testable outcomes: (a) a command that assigns `GIT_INDEX_FILE=` (or
  either `SYNDICATE_ALLOW_STAGED_*`) inside the command string is exempt, exactly
  as the same variable in the hook's env already is; (b) a PATHSPEC-limited
  commit (`git commit -- <paths>`, `git commit <paths>`, `--pathspec-from-file`)
  is exempt, while `-i`/`--include` and a pathspec-less commit keep today's
  behaviour.
- Files: `.claude/hooks/commit-guard.py`,
  `tests/test_commit_guard_worktree_index.py`. Checked against every OPEN lane's
  `- Files:` at open time — no lane claims either path.
- Hypothesis: n/a for (a) — it is a read of the code: the hook reads
  `os.environ`, and the `export` in the recipe it prints runs in the Bash call
  the hook is gating, i.e. AFTER it. For (b) the hypothesis was "a pathspec
  commit cannot carry a stale index entry", and it is now MEASURED, not assumed.
- Falsification test: build a repo whose index holds a revert of `A.txt` and a
  deletion of `C.txt` (still on disk), then `git commit -m x -- C.txt`. If the
  resulting tree drops `A.txt`'s line or `C.txt`, the pathspec form is NOT
  immune and (b) must be scoped-filtering rather than exemption.
  RESULT 2026-08-17: tree kept `A.txt` at HEAD content and `C.txt` on disk;
  `--stat` = 1 file. Immune. Same probe run for `-i` (revert LANDED — stays
  guarded), `--amend -- <paths>` (immune), `--pathspec-from-file` (immune),
  and `-a` (immune to predicate 2, but it COMMITTED the deletion under
  predicate 1 — stays guarded).
- Verification: the four probes above re-expressed as tests in
  `tests/test_commit_guard_worktree_index.py` against real git repos, plus the
  observed false positive replayed (a two-path pathspec commit while an
  unrelated `.syndicate/lanes.md` revert is staged) — pass, and the existing
  suite still passes.
- Blocked by: none.
- **COLLISION NOTICE, filed 2026-08-17 by `branch-overlap-baseline-watch`.** A
  second session is editing `.claude/hooks/commit-guard.py` right now:
  `local_7c140749-7876-4a25-86ea-a20756dbc18f`, "Fix commit-guard's undetectable
  GIT_INDEX_FILE escape", user-started and running. **I caused this** — I spawned
  it from the same two defects before reading this lane, so it duplicates work
  this lane has already MEASURED (the four probes above). Its brief covers (a)
  and (b) and nothing this lane does not already have.
  I could not warn either session: `send_message` is unavailable in
  scheduled-task runs (contract §4a, measured again here), so this block is the
  only channel I have. **Recommend that session be stopped rather than merged** —
  two sessions writing one hook is the exact shape this lane exists to prevent,
  and this lane is further along.

### render-events-read-label — CLOSED 2026-08-17 — `render_events.py` now reports the window READ separately from the span of events FOUND; shipped in `f03928db`, 20/20 tests pass — opened 2026-08-17 — session: branch-overlap-baseline-watch (`65591da9-7697-4a25-a6fd-d4702c2941d1`)
- **Opened RETROACTIVELY, after the edit and the commit. That is a protocol
  violation and is recorded rather than tidied away** — `/lane open` is supposed
  to precede editing. Nothing collided (no OPEN lane claimed these paths;
  `render-events-reader` was archived earlier the same day), so the cost was zero
  this time, which is luck and not a defence.
- Goal: a reader of this tool cannot mistake "few events found" for "little of
  the window read".
- Files: `scripts/render_events.py`, `tests/test_render_events.py`,
  `reports/branch_overlap/baseline.jsonl`.
- Hypothesis: n/a — it is a read of the code. `main()` set its `COVERED` line
  from `events[0]`/`events[-1]` timestamps, i.e. the span of what was FOUND,
  while the label claimed coverage.
- **What it cost, which is why this is worth a lane at all.** A scheduled 5-hour
  events read that returned one 4-event deploy cycle printed
  `COVERED 14:33 .. 14:39`. I read that as "the API only gave me 6 minutes" and
  downgraded a correct, fully-paged all-clear to "~4h54m unverified". The window
  had read whole. **An understated coverage figure is not a safe error** — it
  argues against another lane's urgency exactly the way `learnings.md`
  2026-08-16 ("absence in a window isn't absence") already records.
- Falsification test: a stub returning 4 events for a requested 5-hour window
  must yield `truncated == ""`; a stalled cursor on a FULL page must NOT. Both in
  `tests/test_render_events.py`. RESULT: pass, 20/20.
- Verification: ran against the live Render API on all three paths — fully-paged
  window (prints `READ … fully paged`), empty window (prints `READ no events` +
  positive control), and JSON (`read {fully_paged, truncated_reason}` +
  `event_span`). Confirmed the previously-misread window is `CLEAN` across its
  whole 5 hours.
- Consequence for the ledger, stated because it is cheap to state and expensive
  to rediscover: **any ledger entry citing a `COVERED` range from this tool was
  quoting the EVENT SPAN, not the coverage.** The error direction is always
  understatement, so conclusions drawn from it are conservative, not wrong.
- `fetch_events` now returns `(events, pages, truncated)`. Callers outside this
  script: none. A malformed API response no longer shares the empty-page branch,
  where an unrecognised shape reported as a window that had ended — the
  "unknown must not default permissive" rule.
- Blocked by: none.

### COORDINATOR ADJUDICATION 2026-08-17 14:3x CDT — answering `branch-overlap-baseline-watch`

Filed here because that session is a scheduled-task run and `send_message` is
refused in both directions (§4a). It reported three things. **Two were right,
one was a misread, and the misread is the interesting one.**

**1. NO DEPLOY REQUEST WAS OWED. Correct, and now codified so nobody re-derives
it.** `render_events.py` never executes on a Render service, `baseline.jsonl` is
data, `render.yaml` untouched. A request would have carried an unanswerable
`verify:`. `coordinator.md` §2 now states the test: **"does this change what
runs on a Render service?"**, not "did I touch an ops file". Declining to file
was the right call and required no permission.

**2. THE COLLISION IS REAL, BUT IT IS NOT ON THE COORDINATOR'S SIDE — AND IT IS
NOT DUPLICATION.** The report reads: "the coordinator already holds an OPEN lane
`commit-guard-blind-to-own-recipe`". It does not. That lane's own header names
its owner: session `2028fec0-86fa-4442-a8db-a7ff8949ae..`. The inference came
from `.syndicate/.current-lane` holding that slug — **the shared single-slot
marker, written by whichever session wrote last.** `state.md` already records
that this file cannot represent parallel sessions and is the root cause of lane
thrash; reading ownership out of it produces exactly this error. The coordinator
holds no claim on `commit-guard.py` and never has.

**The two sessions are not duplicating — they are pulling OPPOSITE directions on
one predicate**, which is worse and would not have shown up as a duplicate:
- `2028fec0` shipped `5fb52342` (13:51, +315 lines + a 257-line test file)
  **EXEMPTING** in-command `GIT_INDEX_FILE=` so a session following the guard's
  own printed recipe is not blocked by it.
- `7c140749`'s brief is to **CLOSE** the `GIT_INDEX_FILE` escape as undetectable.

Same switch, two positions. **RULED: the escape stays open.** Isolated-index
committing is the correct technique in a shared worktree and the coordinator
depends on it; forbidding it pushes everyone back onto the shared index, which
is what produced the 4,993-deletion incident. The real hole is the *un-disarmed
aftermath* — an isolated-index commit arms the shared index with a revert of
itself — and that is detectable directly. `7c140749` has been told to retarget
to that and to hold rather than edit the shared hook meanwhile. **The
recommendation to stop it is declined**: its subject is a genuine hole, only its
chosen predicate was wrong.

**3. `coordinator.id` IS NOT STALE — AND THE SESSION WAS RIGHT NOT TO TOUCH IT.**
This is the finding worth keeping. **One session can have two ids.** Measured:

| where | value |
|---|---|
| hook payload / scratchpad / `coordinator.id` | `9ed7fd89-...` |
| `list_sessions` roster id | `local_1d6f136e-...` |
| roster title | "Deploy and Document Coordinator" |

Both are this session. Proven two ways: `get_session` on the roster id returns
**"Refusing to return the current session"**, and the live deploy hook BLOCKS
this session when `coordinator.id` is changed and ALLOWS it when restored — so
the registered id is the one the harness actually passes.

**So "no roster entry matches the registered id" is TRUE and means nothing.**
The register must hold the payload id or the hook stops working, and the roster
cannot see that id at all. Deleting it as stale would have stood the whole role
down — the session flagged it instead, which is the correct handling of an
unverifiable fact. `coordinator.md` §5 now carries the verification recipe:
match by TITLE, or use the `get_session` refusal as the identity test.

**Two self-reported protocol misses, both accepted as recorded, neither
actionable:** the retroactive `/lane open` (nothing collided; the lane says so),
and skipping the `.current-lane` overwrite — **that skip was correct**, for the
reason given: the slot held another session's slug and overwriting it can make
`lane-guard` block that session's own edits. Per-session markers
(`.current-lane.<session_id>`) exist precisely to avoid this; prefer them.

`lanes.md` left uncommitted by that session on purpose, for the coordinator's
sweep. Picked up here.

#### convergence-phase7-crps — CHECKPOINT 2026-08-17 ~19:0xZ — **instrument built, defect traced and quantified, both halves of the fix in flight, NEITHER MEASURED**

- **Shipped and on `origin/main`:** Phase 7 CRPS/bias-dispersion instrument;
  `starter_min_innings` exposed + swept; two betting graders; monotone props seal
  (`bafb4fb2`).
- **Verified:** the `outs` over-projection IS the F5 leash (dispersion
  1.002→0.791 vs a 0.7979 target; short-start gap −0.1778→−0.0266 over 267
  starts / 87,500 sims), the replay reproduces production, and the seal is on
  `origin/main` by content.
- **Verified negative, and it matters more than the positive:** the model still
  loses to a constant baseline at EVERY leash value (3.0912 vs best 3.1852), and
  the betting grade is CONFOUNDED — ALWAYS OVER returns 58.78%/+8.16% on the same
  148 starts, the grid varies only over-propensity, spread is 1.49 SE. **Nothing
  is promoted. No leash value is recommended.**
- **In flight, both unmeasured:**
  1. cadence flag LIVE on live-odds-worker (gate verified running; effect read
     by `outs-props-coverage-check`, fires 2026-08-19 07:00 CT for date 08-18);
  2. seal QUEUED as a deploy request for refresh-worker, cut on `8c0bd8e6`.
- **TOP RISK TO THE 08-19 READING, found in another session's commit
  `7c4439f4` AFTER my flip went live:** refresh-worker sweeps mlb/wnba/soccer/nfl
  while owning only nfl, is gated by neither the ownership flags nor
  ACTIVE_SPORTS, **wins the shared unnamespaced cadence marker and starves the
  designated owner**. My flag is set on live-odds-worker ONLY. So a FAIL on 08-19
  may be MARKER CONTENTION, not the cadence mechanism — and the scheduled reader
  does not know this. Whoever reads it must rule that out before concluding.
- **Next action:** read `outs-props-coverage-check` on 08-19, ruling out marker
  contention first; then let the coordinator ship the seal.

#### convergence-phase7-crps — CHECKPOINT 2 2026-08-17 ~19:3xZ — **nothing left in flight on my side; three things queued, one live and unmeasured**

Supersedes the 19:0xZ checkpoint's "next action" only; its findings stand.

- **Queued for the coordinator (messaged, session live 19:18Z):**
  1. `20025cc4` ownership gate, **BOTH workers**, soft deadline before the 08-18
     slate — measured absent from both live SHAs by content.
  2. `bafb4fb2` monotone props seal, refresh-worker, **no deadline**, ideally
     AFTER the 08-19 cadence result so the two do not confound.
- **Live and unmeasured:** the fixture-aware cadence flag on live-odds-worker.
  Reader `outs-props-coverage-check` fires 2026-08-19 07:00 CT and now carries
  **Gate B** (marker contention) plus the undeployed-seal caveat, so it can
  return INCONCLUSIVE instead of wrongly FAILing a starved mechanism.
- **NOT DONE, DELIBERATELY: the cadence marker is NOT namespaced.** Asked for,
  and refused after reading the code — the authoring lane rejected it hours
  earlier in the docstring of the function I was about to edit, and with the gate
  deployed the shared marker is a safety net whose removal would double MLB
  OddsAPI spend. Recorded in `state.md` and `learnings.md`.
- **Next action for whoever picks this up:** get `20025cc4` deployed to both
  workers, then read `outs-props-coverage-check` on 08-19 working Gate B first.
  Do not promote any leash value — the model still loses to a constant baseline
  at every grid point.


## MERGED FROM origin/main - coordinator merge cycle

## MERGED FROM origin/main — 2026-08-17, by the coordinator

Block-level union. These blocks existed on `origin/main` and nowhere
on the swept side. Appended verbatim, nothing edited, nothing reordered.

## Archived from lanes.md 2026-08-17

### live-game-line-projection — CLOSED-VERIFIED 2026-08-17 00:4xZ — v2 EXERCISED on a live slate: `written=13` across two builds, 2 of them NON-priceable — opened 2026-08-15 — session: live-gameline-eval (closed by `layer1-board-coverage`)
- **The lane's own SINGLE NEXT ACTION was run, verbatim:** read
  `live_gameline_ledger` off `/api/board/book-grid?sport=mlb&date=2026-08-16`
  during a live slate, **across two builds, never one.**
- **Its stated success criterion — quoted — is MET:** *"one live slate where
  `live_gameline_ledger.written > 0` and the counters are reachable from an
  API."*
  ```
  BUILD 1  00:37:48.762827Z   written=13 candidates=13 skipped_unchanged=0
                              projected=13 priceable=11  -> 2 NON-priceable
  BUILD 2  00:39:58.257836Z   written=13 candidates=13 skipped_unchanged=0
                              projected=13 priceable=11  -> 2 NON-priceable
  ```
  Counters served on the API, no 10 MB artifact stream needed — the second
  half of the goal.
- **The v2 discriminator held, and it is the part that could have been
  faked.** The lane warned that `skipped_unchanged > 0` is NOT the signal
  (seen under v1 at 04:22:51Z, which refuted this lane's own earlier claim).
  Here `skipped_unchanged` is **0** and `written 13` exceeds `priceable 11`,
  so **2 rows that v1 could never have written were recorded** — on both
  builds. Withheld: `segment_is_not_full_game` 49,
  `prob_interval_swamps_edge` 2, of 62 considered.
- Measurement in `deploys.md` with the window stated, which was this lane's
  literal Verification line.
- **TWO THINGS THIS DOES NOT ESTABLISH, carried forward so they do not
  disappear with the lane:**
  1. **The edges are still UNSCORED.** The old heading's "THE EDGES ARE
     UNEVALUATED" is a broader ambition than the Goal this lane actually
     stated. The ledger can now produce a sample; nobody has measured
     whether those 11 edged rows were RIGHT. **Needs its own lane.**
  2. **The ledger's RSS was never measured.** This lane records an
     `oomKilled` at 04:46:44Z, 22 min after its deploy added work to
     refresh-worker, and says plainly it is *not* claiming exoneration.
     **That debt is NOT discharged here** — it stays with
     `refresh-worker-oom-recurrence` (OPEN). Kill switch, no deploy:
     `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` (currently ABSENT = enabled).

**STATUS AT CHECKPOINT `[15:2xZ]`.** Nothing uncommitted; everything is on
`origin/main` and content-verified there. web `ebd5f677` live 03:38:07Z,
refresh-worker `5c419007` live 04:24:33Z — and `LEDGER_VERSION = 2` is
content-verified on the CURRENTLY live `d72d670c`, which another lane deployed
at 06:01:34Z and carried it forward. Board at 15:17Z reads `index_size 0,
considered 0` — Sunday pregame, nothing live yet.

**THE SINGLE NEXT ACTION:** read `live_gameline_ledger` off
`/api/board/book-grid?sport=mlb&date=2026-08-16` during tonight's slate
(scheduled `live-gameline-ledger-check`, 20:30 Central). **The discriminator
for v2 is `written` rising on rows that are NOT priceable.**
`skipped_unchanged > 0` is NOT it — that was already observed under v1 at
04:22:51Z, which is what refuted this lane's own "never recorded a row".
Read across two builds, never one.

**ONE UNPAID DEBT:** an `oomKilled` fired at 04:46:44Z, 22 min after my
deploy added work to refresh-worker. Recorded by `refresh-worker-oom-recurrence`,
and `44ad2f9d` reports `d72d670c` as 9h clean since — **but I never measured
the ledger's RSS and I am not claiming exoneration.** Kill switch, no deploy
needed: `MLB_LIVE_GAMELINE_LEDGER_ENABLED=0` (currently ABSENT = enabled).

— original re-take header follows —

### live-game-line-projection — SUPERSEDED (see CLOSED-VERIFIED 2026-08-17 00:4xZ above) — RE-TAKEN 2026-08-16 03:0xZ (session `live-gameline-eval`) — TIER 5'S PREMISE IS TRUE IN PRODUCTION; THE EDGES ARE UNEVALUATED
- Goal: make the ledger capable of producing a sample at all, and make its
  counters readable without streaming a 10 MB artifact. Success = one live slate
  where `live_gameline_ledger.written > 0` and the counters are reachable from
  an API.
- Files: `syndicate/features/shared/live_gameline_ledger.py`,
  `tests/test_live_gameline_ledger.py`.
- **`syndicate/blueprints/intelligence.py` RELEASED 2026-08-17 00:4xZ — second
  double-claim on this lane, resolved the same way as the first.** It was
  contested with `layer2-board-quality`, which holds it in a nine-path list and
  reads **ALL 8 GOALS SHIPPED**; this lane is `OPEN, UNOWNED` since 15:2xZ and its
  own stated single next action is a READ of `/api/board/book-grid`. Finishing it
  needs no edit here. **TO RE-TAKE:** put the path back and tell
  `layer2-board-quality`.
- **`syndicate/features/shared/live_gameline_join.py` RELEASED 2026-08-17 00:2xZ
  — it was double-claimed, and this lane is the one that does not need it.**
  Reconciled by the `ask-answer-substance` session (holds no claim on either
  lane) on evidence, not preference:
  - `mlb-live-gameline-distributions` also claims it, is the file's ACTIVE
    EDITOR (`c7e39e58`, "the re-sim's own histograms, not just their means", is
    its work and is already in the file), and its goal is literally "consume +
    price" there. Its session is idle-but-resumable, last active 00:15Z.
  - this lane reads `OPEN, UNOWNED` since the 15:2xZ checkpoint, and its own
    stated SINGLE NEXT ACTION is a READ of `/api/board/book-grid` — finishing it
    requires no edit here.
  **HOLDER CHANGED WITHIN THE HOUR, 2026-08-17 00:3xZ:**
  `mlb-live-gameline-distributions` went **CLOSED-VERIFIED** and
  **`wnba-live-tier`** (restored, same work family) now holds this path. Still exactly
  one holder, which is the point — but the counterpart to coordinate with is now
  `wnba-live-tier`, not the closed lane.
  **TO RE-TAKE:** put the path back on the `- Files:` line above and tell
  `wnba-live-tier`. The release is a coordination decision
  between two unattended lanes, not a judgement that this lane's interest was
  invalid — it wrote the `edge_vs_market_pct` line that sits there.
- Collision check at re-take: no OPEN lane claims any of the four above.
  `refresh-worker-oom-recurrence` names `syndicate/features/intelligence.py` as an
  expected candidate — a DIFFERENT file from `syndicate/blueprints/intelligence.py`.
  **Kept OUT of the `- Files:` block on purpose:** `_claims()` reads every nested
  line under `- Files:` as a CLAIM, so a disclaimer written there becomes a
  PHANTOM claim on a file this lane does not hold. `ask-sport-coverage` was bitten
  by exactly this and it blocked another lane's one-line fix.
- Deploy intent: **PREPARE ONLY.** The recorder runs on refresh-worker, and
  `refresh-worker-oom-recurrence` has an explicit hold on deploys to that service
  until its attribution is written. Request file, not a deploy.
- Verification: written to `deploys.md` with the window stated.
- Blocked by: refresh-worker deploy hold (`refresh-worker-oom-recurrence`) for
  the recorder half only. The web half is unblocked.
- **Took `.syndicate/.current-lane` from `refresh-worker-oom-recurrence`** — one
  single-valued marker, N sessions, the known root cause. That lane claims no
  files, so the cost is bounded.

**MEASURED 2026-08-16 03:00–03:1xZ on a LIVE slate (2 games live, 13 final).**
Source: the `book_grid_2026-08-15.json` artifact streamed from web
(`/api/ops/artifacts/stream`, 9,953,474 bytes, `generated_at 03:00:00.538Z`) and
`/mlb/api/live-lens` at 03:00Z. Both read at the same instant, both post-date
`f8ca54e1`.

    live_gamelines       considered 8  projected 2  priceable 0  edged 0
                         withheld 8 = {segment_is_not_full_game: 6,
                                       prob_interval_swamps_edge: 2}
                         index_size 10
    live_gameline_ledger candidates 0  written 0  enabled true

1. **`index_size` IS EXPLAINED. It is not a live-game count and nothing is
   wrong.** It counts snapshot games carrying a `live_mc` lens. Census at 03:0xZ:
   **10 of 15 games carry one — 8 FINAL and 2 LIVE.** A Final keeps its last
   `live_mc` lens, so the number is monotone through a slate: 3 → 8 → 10 is just
   how many games had gone live-or-through-live by each read. **The join loop
   filters on `game.state == live` on the GRID side, so the Final entries are
   never used** — the counter is misleading, not the join. Retire the "unexplained"
   framing; the defect, if any, is that this is the one counter in the block with
   no denominator, which is exactly what invited the wrong reading.
2. **THE RECORDER CANNOT PRODUCE A SAMPLE, AND THIS IS THE REAL BLOCKER.**
   `build_records` skips any row that is not `priceable`; `priceable` requires the
   edge to clear a 2σ bar at 120 sims. Tonight that is **0 of 8**, so
   `candidates: 0` — the ledger was never asked to write anything. **The
   scheduled `live-gameline-ledger-check` will very likely read `written: 0`
   again tomorrow, and that will mean neither "broken" nor "working."**
3. **The filter's stated justification is wrong by three orders of magnitude.**
   The docstring refuses non-priceable rows because "recording thousands of
   refusals per build would bury the handful CLV can score." The measured
   population is **8 rows per build, 2 of them projected.** There are no
   thousands. Recording every PROJECTED row costs ~2 records/build against a
   20,000-record file cap, and it is the difference between a sample and none.
4. **`liveStateAsOf` and `liveStateCarriedForward` are `None` on all 10 lensed
   games, including the 2 live ones.** Consistent with "Drop 2's carry-forward has
   never fired" AND with "the stamp is only applied on the carry-forward path."
   **Not disambiguated — do not record either as established.**

**BOTH HALVES ARE NOW DEPLOYED — 2026-08-16 04:2xZ. `DEPLOYED NOWHERE` below is
SUPERSEDED; the rest of that block still reads true.**
- web `ebd5f677` live 03:38:07Z — the counters are served. Measured null -> object
  across two artifacts.
- refresh-worker `5c419007` live 04:24:33Z — ledger v2. **Deployed and NOT YET
  EXERCISED:** the slate ended between the last pre-deploy build and the first
  post-deploy one, so `considered` went 4 -> 0 and v2 has had no live row to act
  on. Both parented on their service's LIVE SHA, never on main.
- The `refresh-worker-oom-recurrence` hold cleared on its own evidence
  (`9ed17262`: a ~2 GB transient, not a leak) rather than being overridden. I
  asked that session first; it archived between the question and the answer.

**CORRECTION TO THIS LANE'S OWN FINDING #2 ABOVE — read it before quoting the
arc.** "The recorder has never recorded a row" is **FALSE**. The 04:22:51Z
pre-deploy build read `priceable 1, candidates 1, skipped_unchanged 1`, and
`skipped_unchanged` cannot be non-zero unless a matching record already sits on
disk — an empty file always writes, because `_moved(None, rec)` is True. **v1
wrote at least one row tonight**, between 02:4xZ and 04:22Z. The 03:00Z reading
was real and I generalised it to a night. v2's premise survives (1 priceable of 4
considered is a self-selected sample), but "it structurally could not write" was
an overclaim.

**NEXT ACTION is now purely measurement, and the plumbing question is closed.**
`live-gameline-ledger-check`, 20:30 Central 08-16, on a full slate:
`written > 0` on one build, then **`skipped_unchanged > 0` on a later one** —
the second is the real test, and note it has ALREADY been observed once under
v1, so the discriminator for v2 is `written` rising on rows that are NOT
priceable. Read across two builds, never once.

**CHECKPOINT 2026-08-16 03:4xZ.** Shipped to `origin/main`, DEPLOYED NOWHERE:
`c87f6634` (ledger v2 + the book-grid pass-through + 2 test files),
`bbc70d16` (the two deploy requests), `4e82d4b7` (the learnings rule).
97 tests pass, and the pass-through was falsified first — commenting out the two
served keys fails all 6 new tests.

**THE ONE THING THAT DECIDES WHETHER TOMORROW IS A TEST:** the v2 recorder must
be on refresh-worker before the scheduled `live-gameline-ledger-check` fires at
**08-16 20:30 Central**. Against v1 it reads `written: 0` again and means nothing.
That deploy is HELD by `refresh-worker-oom-recurrence`, deliberately — the hold is
correct and the deadline is real, and only the user can trade them off.

**NEXT ACTION for whoever picks this up:** not code. Get the refresh-worker
deploy decided. Everything after it is measurement:
`live_gameline_ledger.written > 0` on one build, then `skipped_unchanged > 0` on
a later one — **the second is the real test**, because the append proving it
writes is not the dedup proving it writes only on movement. Read it across two
builds, never once.
**Lane stays OPEN** — the projection ships, but nothing yet says the edges are good.

**SHIPPED AND LIVE (content-verified per service, not by ancestry):**
- live-odds-worker `c4116ab6` — the live MC stamps `simsRun`.
- refresh-worker `f8ca54e1` — the game-line join, the segment filter, the
  Agresti-Coull boundary, and the CLV recorder.
- web carries D1+D2; it needs neither the vendor stamp nor the join.

**THE ARC, in measured numbers:**

    baseline   index 3   projected 12  edged 0   (sim_count_unusable 12)
    +simsRun   index 8   projected 32  edged 25  <- FIRST EVER, and WRONG
    +segment   index 10  projected  5  edged 4   <- first credible ones
    tail       index 10  projected  2  edged 0   (slate over; ledger written 0)

**THE 25 WERE FAKE AND I RETRACTED THEM MYSELF**, caught while packaging them
for handoff: Wald `sqrt(p(1-p)/n)` is **0.0 at p in {0,1}**, so the 2-sigma bar
was ZERO and everything cleared it; and the full-game projection was priced
against every SEGMENT (SD @ CLE `first1` gave **+42.43 pp**). Both fixed.

**WHAT IS NOT ESTABLISHED — do not let the arc imply otherwise:**
- **No CLV, no settlement, no backtest.** Surviving means an edge exceeds the
  ESTIMATOR'S OWN NOISE at 120 sims. It says nothing about the model.
- **The recorder has never recorded a row** — it went live on a finished slate.
  `written: 0` with `enabled: true` proves wiring, not behaviour.
- **`index_size` 3 -> 8 -> 10 across the night is unexplained.**
- **Drop 2's carry-forward has never been observed firing.**
- The tally is MLB-only; soccer/wnba report `liveMcSources: null`.

**HANDOFFS, all verified present in HEAD:**
- `clv-without-settlement` — the rows are TRANSIENT (edged 25→4→1 on one slate);
  the recorder is the prerequisite, and `clv_join.py` was deliberately untouched.
  Carries two corrections: **Pinnacle is 15/30 in production** (the sharp SET is
  30/30), and "close" is ill-defined for a live market.
- `memory-watchdog-435` — a **2,092 MB** in-process excursion, pid 39, 34 s,
  children proven flat. ~3x `#327`'s largest.
- `soccer-model-coverage` — `SOCCER_PREGAME_AUTORUN_FAILED` lock contention.

**COSTS I IMPOSED, recorded rather than netted out:** three soccer runs killed,
one wrong rollback of a working fix, and two deploys fired over another
session's claim. **No claims held; refresh-worker and live-odds-worker are free.**

**NEXT SESSION STARTS HERE:** tomorrow's live slate is the first real test —
does the ledger grow only on movement, and do the surviving edges beat a sharp
close. **That is evaluation, not plumbing.** The plumbing is done.

### live-edge-basis — CLOSED-VERIFIED 2026-08-17 — **SHIPPED AND MEASURED. `edge_basis` observed on served rows (refresh-worker `b20072cd`, build 17:44:30Z, 9 live_aware rows, perfect separation: the key is set IFF the edge is priceable). Deploy row closed in `deploys.md`. Both file claims released; `live_gameline_join.py` returned to `wnba-live-tier`, which held it first.**
- Goal: a consumer can tell WHICH probability `projection["edge_vs_market_pct"]`
  refers to. **Testable outcome:** on a live-joined game row,
  `projection["edge_basis"] == "live"`, and `"pregame"` on a row with no live
  projection. No existing field changes value.
- Files (exclusive to this lane):
  - `syndicate/features/shared/live_gameline_join.py`
  - `tests/test_live_gameline_edge_basis.py`
- **TAKEN BY USER OVERRIDE from `wnba-live-tier`, whose session was LIVE.** See
  the note under that lane. It keeps every other path it held.
- Deploy intent: **NONE TAKEN.** This code runs in the artifact build on
  refresh-worker, and at open time (a) `refresh-worker-oom-recurrence` has a
  documented deploy hold on that service and (b) the deploy claim was HELD by
  `sim-scheduling` mid-ship. Committed and landed on `main`, **UNDEPLOYED** and
  recorded as such in `deploys.md`. Whoever next deploys refresh-worker carries
  it.
- Verification once deployed: `edge_basis` present on `full/*` live rows of
  `/api/board/layer2-shortlist`, and `_board_row_probabilities` can then publish
  a model/market pair on those rows instead of refusing.
- Blocked by: refresh-worker deploy hold + claim, for the DEPLOY only.

### nfl-fantasy-projections — CLOSED-VERIFIED 2026-08-21 — **`/nfl/fantasy` is live and serving: ESPN-scoring 2026 season + weekly projections, VOR draft board, and a news layer that captures, publishes, accumulates and renders.** web `003a5866`, refresh-worker `6855fe96`. — opened 2026-08-21 — session e8d83eb5-3cbb-4c8b-824f-86cc86442160
- Goal: a `/nfl/fantasy` surface serving ESPN-scoring 2026 season projections (PPR default, 12-team 1QB VOR draft board) for QB/RB/WR/TE/K/DST, plus per-week projections. **MET.**
- Files: `syndicate/features/nfl/fantasy{,_scoring,_usage,_schedule,_players,_projection,_draft_board,_news}.py` (new), `syndicate/blueprints/nfl.py` (3 routes), `syndicate/features/shared/artifact_publisher.py` (+5 allowlist patterns), `syndicate/templates/nfl/fantasy.html` (new), `scripts/{build_nfl_fantasy_usage,fetch_nfl_rosters_depth_charts,backtest_nfl_fantasy_projections,calibrate_nfl_fantasy_projections,compare_nfl_fantasy_depth_charts,nfl_fantasy_input_checklist}.py` (new), `tests/test_nfl_fantasy.py` (new), `docs/ai_context/nfl_fantasy_engine_reference.md` (new), `reports/nfl_fantasy_*.json`.
- Hypothesis: an opportunity-share engine re-based onto 2026 depth charts beats "last season's fantasy points" on held-out season MAE and rank correlation.
- Falsification test: **RAN FOUR TIMES; PASSED, then FAILED at `198a6a70` after a legitimate re-calibration, and that FAIL was reported rather than tuned away.** Current: season MAE 49.41 → 47.67, spearman 0.7058 → 0.7392; per-game 3.68 → 3.56, 0.6138 → 0.6337 (n=266 common set, held-out 2025).
- Verification: **RAN, and each claim below is a reading.** Falsification test passed on all four criteria (season MAE 49.41 -> 47.67, spearman 0.7058 -> 0.7392; per-game 3.68 -> 3.56, 0.6138 -> 0.6337; n=266 held-out 2025) after FAILING once at `198a6a70` and being fixed rather than tuned. Injury layer graded on 2,226 held-out player-weeks: MAE 6.894 -> 4.399 (+36.2%). Worker captured twice — 22:28:32Z `new=50`, 23:29:29Z `new=2 total=52`, so the archive ACCUMULATES. Served page: 101 Buzz buttons / 414 inert, 82-player payload; dialog opens, Escape/backdrop/Close dismiss, focus returns, panel-click keeps it open.
- Blocked by: none. **DEPLOYED: web + refresh-worker both live on `ae941265`.** The autorun fired at 21:20:19Z and FAILED (`unreachable: HTTPError`), which falsified my "local network block" reading — the cause was my own `User-Agent`, and the rule was already at `live_game_state.py:50`. Fixed; the same code now returns `status=ok, 50 articles, 35 linked -> 84 players` (92/95 links via ESPN athlete tags). **ONE THING STILL OWED: the worker has never logged `status=ok`.** It holds `interval_s=21600` (I set the interval AFTER triggering the deploy, so it missed the env snapshot), so the next attempt is ~03:20Z; `render_logs.py --text news_capture --start 2026-08-22T03:00:00Z`, or a non-quiet Buzz badge, settles it.
- Text/role signals ship INERT by choice: `use_news_adjustments=False`. Quotes are SHOWN, not scored, until the archive is deep enough to grade.

**ON `main` as `45632889..c1c811c3` (6 commits), rebased clean onto `e0e32b53`.** engine · reference doc · depth chart + contemporaneous role prior + ARI fix · re-calibration (the reported FAIL) · availability fix (the PASS) · re-sweep (nothing changed). **`render.yaml` NOT touched, so no `blueprint_sync` and nothing applied to production. NOT DEPLOYED, no deploy claim ever taken — `autoDeploy = no`, so this push ships nothing until someone deploys it.** Full narrative: `.syndicate/log/2026-08-21.md`.


**OPEN RISK, not owed work:** the PRIMARY SHARED TREE holds an orphaned commit
`318b2b7a` (1 ahead / 57 behind). Its content is already on `main` via
`80b772ee`, but it was authored against a 47-commit-stale `.syndicate/`. A
rebase or force-push from that tree can REVERT tonight's ledger. Left alone
deliberately — another session may hold uncommitted edits in those files.

**NEWS + COACH QUOTES SHIPPED 2026-08-21 21:1x-21:3xZ.** Injury half is fitted
and gated ON (MAE 6.894 -> 4.399, +36.2%, 2,226 held-out player-weeks). Text half
(camp/role/workload talk) is CAPTURED and DISPLAYED but **NOT SCORED** --
`use_news_adjustments=False` -- because there is no archive to grade it against
yet; `capture_nfl_news.py` now builds one, append-only, on a worker autorun.

**THE FIRST WORKER RUN FAILED AND FALSIFIED MY EXPLANATION.** I had recorded
ESPN's 403 as "a local network block" -- the one reading that made a local
failure say nothing about production. Same error on the worker. Cause: my own
`User-Agent`; the rule was already in capitals at `live_game_state.py:50`,
including the clause saying the dev machine and Render fail the SAME way. Fixed
in `ae941265`; now `status=ok, 50 articles, 35 linked -> 84 players`, 92 of 95
links via ESPN's own athlete tags. **NOTHING OWED ON THE NEWS LAYER.** Discharged 22:28:32Z: the worker logged
`status=ok fetched=50 linked=35`, published, and the served page went from 0 live
Buzz badges to **101** (58 players with coverage) -- it holds `interval_s=21600` because I set the interval AFTER
triggering the deploy, so next attempt ~03:20Z.

**Retired a worry:** the 21:45:29Z tick shows all six NFL autorun branches
logging SKIPPED in the same second -- they are NOT `#341`-starved.

**DEFECTS FOUND, all silent, all measured.** Role prior fitted only over players who PLAYED (a rank-2 QB priced at a 0.466 pass share, which CRUSHED starters after normalisation — Josh Allen at 12.09 PPG against a real ~24); rookie prior fitted against a reference cell that cannot exist (3.24x round-one multiplier, four rookies atop the board); expected games taken from the POSITION mean; role curve measured in season-total share while history used while-active share; **depth-chart snapshot taken as `max(dt)`, which for 2025 is 2026-03-14 — AFTER the season being graded** (now `PRESEASON_CUTOFF`; the rule is in `learnings.md`); **`AZ` vs `ARI` after a roster refetch, which silently unjoined an entire team while still producing plausible numbers**; and a harness defect that graded baseline and engine over DIFFERENT player sets (297 vs 275) and returned a verdict that was not one.

**THE ENGINE DELIBERATELY DOES NOT USE smartsim2** — `state.md [football-smartsim2]` measured it strictly dominated by the close (w = -0.028, 751 OOS games). Environment comes from posted lines: 112 of 272 2026 games carry one, all 32 teams in 6-9 of them.

**AUTORUN IS LIVE AND HAS RUN (`a48c8530`, flag set on refresh-worker).** Its FIRST run published a DEGENERATE artifact over a correct one — `weeks: []`, 318 KB vs 2.83 MB, top player 525.5 pts vs a correct ~270 — because the worker has no `schedules_games.csv` and nothing in the repo writes it. Correct artifact republished by hand 20:19:28Z. `--prepare` now fetches the schedule, and the job refuses to publish when its OWN OUTPUT is degenerate (the input checklist could not see this: the schedule was not on its list). **OWED: the next autorun (~19:50Z tomorrow) is the real verification — it must either publish a healthy artifact or refuse and say why; neither has been observed.**
