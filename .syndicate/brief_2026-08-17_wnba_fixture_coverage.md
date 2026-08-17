# SE§ION BRIEF - WNBA fixture coverage, and the live-edge score

> Written 2026-08-17 by the `layer1-board-coverage` session at the end of its
> context. **This brief is an input, not a finding.** Every claim is either
> VERIFIED with evidence or marked UNPROVEN. Re-verify anything you build on:
> three of my own conclusions were overturned in one session, and §4 says how.

## 0. Protocol
1. Read `.syndicate/state.md`, `lanes.md`, `learnings.md`.
2. `wnba-live-tier` is OPEN and holds this work. Take it over; do not duplicate.
3. `/preflight` before any deploy. `/checkpoint` every ~30 min.
4. Commit through an isolated `GIT_INDEX_FILE`, and **assert your own marker
   against the STAGED BLOB** (`git show :<path> | grep -qF "<marker>"`). A
   deletion-count guard is blind to a REPLACEMENT - that cost me a lane entry.

## 1. Live right now
| service | SHA | carries |
|---|---|---|
| refresh-worker | `9bff3cc1` | live game-line scorer + both join fixes |
| web | `685ab3e9` | the `live_gameline_score` reader line |
| live-odds-worker | `cc0f7605` | WNBA final-precedence fix (defect 3) |

`origin/main` matches all three **BY CONTENT** - checked, because three commits
once ran in production for an hour while `main` lacked them.

## 2. VERIFIED
- **The live game-line model loses to the market.** Full 15-game MLB slate,
  artifact 02:28:13Z: `all_records` model Brier 0.27725 vs market 0.23883
  (**+0.03842**, n=3,638); `last_per_game` +0.05778 (n=15); `priceable_only`
  **+0.05624** (n=2,409). Positive = market better. **Worst on the rows the board
  publishes.** Read it from `live_gameline_score` on
  `/api/board/book-grid?sport=<s>&date=<d>`. **ONE SLATE - do not act on it.**
- **WNBA `game_cards_<date>.csv` on the worker holds 1 of 3 fixtures.** Via
  `/api/ops/artifacts/export`: `game_cards_2026-08-16.csv` = 1 row
  (`game_id='1'`, POR@PHX). Chip builder, `is_active_today` and provider code all
  EXONERATED by measurement.
- **RETRACTED 2026-08-17 15:4xZ - see lanes.md.** `game_odds_*` does not exist
  for ANY date, so the odds branch cannot discriminate between fixtures, and the
  sim ran for ALL THREE games. The writer is still `export_game_cards_cmd`, but
  the MECHANISM is unknown again. Thread 1 in §5 is superseded: read the rest of
  that function and check `boxscores_2026-08-16.csv`.
- ~~The writer is `export_game_cards_cmd`,
  `vendor/wnba_betting_repo/src/wnba_betting/cli.py:9581`, and it walks
  `game_odds_<date>.csv`** - odds, not schedule - with an EMPTY frame fallback.
  A fixture with no odds row does not exist.

## 3. UNPROVEN - do not repeat as fact
- **Defect 3 is deployed and its behavioural test has NEVER RUN.** 2026-08-17 had
  one WNBA game (DAL @ GSV, 02:00Z tip); the finished-overtime case could not
  occur before ~04:30Z.
- Whether the worker's `game_odds_2026-08-16.csv` really holds one row.
- Whether `export_game_cards_cmd` has a later fallback that re-adds fixtures.
  I read ~45 lines of a long function.

## 4. FOUR TRAPS THIS SURFACE SPRANG
1. **A local run is not production.** I measured WNBA chips locally, got "3
   games, all final", and declared the chips correct. Production had **1 chip,
   pregame**. Local takes a stored-snapshot branch; the worker hits live ESPN.
   **The user caught it, not me.**
2. **`a or b` is not a fallback when `a` is reliably present and reliably
   wrong.** `rec.get("game_pk") or rec.get("event_id")` chose the one key the
   index never held, on all 3,727 records. Use
   `next(k for k in candidates if k in index)`.
3. **Presence is not reachability.** The scorer shipped and served `null`:
   `/api/board/book-grid` forwards an EXPLICIT key allowlist, so a new artifact
   key is invisible until named. Read the served payload; never trust the deploy.
4. **A deploy branch that never returns to `main` is a regression waiting for the
   next deploy.** Verify with `git show origin/main:<file> | grep -c <marker>`;
   ancestry is the wrong test for cherry-picks.

## 5. THE THREE THREADS, in order
1. **One export call - cheapest, and it can INVALIDATE the rest. Do it first.**
   Export `wnba_source/data/processed/game_odds_2026-08-16.csv`; count rows.
   **1 row confirms the whole attribution in §2. 3 rows means the loss happens
   INSIDE `export_game_cards_cmd` and my read is incomplete.**
2. **Defect-3 behavioural check.** After a WNBA game finishes, read
   `/wnba/api/live-lens`; expect `final=True, in_progress=False`. If it ends in
   regulation and reports `Final`, that confirms NO REGRE§ION only - the OT path
   stays unproven until an overtime game occurs. Easy to misread as a pass.
3. **The writer fix - one change closes TWO defects.** Walk
   `vendor/wnba_betting_repo/data/processed/schedule_2026.csv` (git-tracked,
   complete) and LEFT-JOIN odds: one row per real fixture, market columns blank
   where odds are missing. **The same function emits `pred_margin`/`pred_total`
   as MEANS** (outstanding #3), starving every WNBA alt line and the
   double/triple-double props; publish the 2,000-sim arrays instead.
   Verification needs a WNBA sim re-run AND a multi-game slate.

## 6. Standing cautions
- **`_looks_terminal_status_text` matches "final" as a SUBSTRING**, so
  "Semifinal" reads as finished. Pinned as a strict `xfail` in
  `tests/test_wnba_scoreboard_carry_forward.py`. Shared helper, every sport uses
  it. **Not fixed.**
- The WNBA scoreboard carry-forward (`16a898ef`) has never fired in production.
  Kill switch, no deploy: `WNBA_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS=0`.

## Opening prompt

    Read .syndicate/brief_2026-08-17_wnba_fixture_coverage.md and follow it.

    You own WNBA fixture coverage. Start with §5 thread 1 - export the worker's
    game_odds_2026-08-16.csv and count rows, because that one call either
    confirms the whole attribution in §2 or breaks it. Then threads 2 and 3.

    Take over lane wnba-live-tier (already OPEN; do not duplicate it). Everything
    in §3 is UNPROVEN and must not be repeated as fact. §4 lists four traps
    that already cost this surface real time - the first is that a local run is
    not production, and the user caught it, not me.
