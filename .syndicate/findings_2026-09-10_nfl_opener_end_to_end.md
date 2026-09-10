# FINDINGS — NFL opener (NE @ SEA, 2026-09-09) end to end: the sim's game leans won, its props lost to the market, nothing was staked, and NFL props CANNOT BE GRADED

`[2026-09-10, lane nfl-opener-review. Measurement only; no code, no deploy. All times Central.]`

**n = 1 game. Nothing below is evidence of skill in either direction.** Prop lines within
one game are correlated; treat every rate here as a description of one night.

## The game

NE @ SEA, Lumen Field, kickoff **Wed Sep 9, 7:20 PM CDT**. Final **NE 10 – SEA 13**.

| | SmartSim 2.0 | market (close) | actual |
|---|---|---|---|
| margin | NE by 0.5 (sd 13.3) | SEA −3.5 | **SEA by 3** |
| total | 42.6 (sd 11.0) | 44.5 | **23** |
| P(SEA win) | 46.7% | — | SEA won |

- **Both of the sim's against-the-market leans won:** NE +3.5 (`away_cover` 0.617) and UNDER 44.5 (`total_under` 0.568).
- Its straight-up lean (NE 53.3%) lost — a near coin flip.
- **Margin:** market error 0.5 pts, sim 3.5. The market was much closer.
- **Total:** both far off (sim 19.6, market 21.5). 23 points sits ~1.8 sd below the sim's mean.

## Props — the model against the outcome AND against the market

Source: `nfl_prop_projections_2026_wk1.json` (rebuilt 7:09 PM CDT, 11 min before kickoff),
115 rows / 13 players for this game, graded against the card's `live_player_box`.

- **5 of 9 markets gradeable** from that box (pass/rush/rec yards, pass TDs, anytime TD).
  Receptions, rush/pass attempts and interceptions are NOT in the reduced box row and were
  left UNGRADED, not guessed. 6 rows were for players absent from the box and were counted
  UNKNOWN, **not zero**.
- **89 graded player-lines.** Model lean correct **52.8%**. Mean model P(over) **0.488**
  against a realised over-rate **0.337** — a **+0.151 lean toward overs**, the direction
  `#651` warns about.

**Against the market's own de-vigged price** (pregame `nfl_source/tracking/book_quotes`,
1,565 quotes; closing quote per book, de-vigged per book, then averaged; 78 lines had a
two-sided price):

| | Brier |
|---|--:|
| **model** | **0.2612** |
| market | 0.2461 |
| coin flip (0.5) | 0.2500 |

**On this game the model was worse than the market AND worse than a coin flip.** Where it
disagreed with the market by 5 points or more, its side was right **24 of 53**.

| market | n | model | market |
|---|--:|--:|--:|
| receiving_yards | 36 | **0.2096** | 0.2467 |
| rushing_yards | 22 | **0.2283** | 0.2373 |
| passing_yards | 18 | 0.3993 | **0.2623** |
| passing_tds | 2 | 0.3070 | **0.1856** |

**It BEAT the market on receiving and rushing yards and lost all of that on passing.** The
passing loss is one event: **Sam Darnold was projected for 238 passing yards and threw 13;
Drew Lock threw 187 and had NO projection at all.** A QB change that prior-season rates
cannot see — `#651`'s residual, exactly. Anytime TD is quoted "yes" only, cannot be
de-vigged, and was excluded from the comparison rather than mixed in.

An earlier draft of this analysis compared the model with "a constant at the realised
over-rate" (0.2235). **That baseline uses hindsight and is unfair**; it is replaced here by
the coin flip and the market.

## Opportunities — nothing was staked

- **Zero NFL positions pregame.** Paper settlement's 22 committed rows for 09-09 contain no
  NFL; the 7:11 PM CDT plan refused `no_model_edge_pct` on **1,503 NFL rows**.
- **The opener ran on the PRE-JOIN board.** The NFL prop join went live at **9:11 PM CDT,
  1h51m after kickoff.** So props could not have been staked for this game whatever their
  quality.
- **Why the sim's two winning GAME leans were not staked cannot be reconstructed** from what
  is persisted: the 7:11 PM plan's position list has been overwritten (the served 09-09 plan
  is a 10:22 PM CDT rewrite), and refusal counts are not broken out per game. Pregame
  `LAYER2_BOARD_HEALTH sport=nfl` showed `edged=63`, so some NFL game rows DID carry an edge.
  **Stated as a gap, not a finding.**
- **The live lane was blind to NFL.** `board_enrichment._LIVE_GAME_STATE_SPORTS = {"mlb",
  "soccer"}`, logged throughout the game as `LIVE_GAME_STATE_JOIN sport=nfl supported=False
  reason=no live status source wired for nfl`. **`scripts/poll_nfl_live_state.py` EXISTS** —
  the poller is built and simply not registered with the board's live-state join. The game
  card had live scores (ESPN scoreboard); the decision path did not.

## THE FINDING THAT MATTERS MOST: NFL PLAYER PROPS CANNOT BE GRADED

`bet_status_nfl.py` refuses **every** NFL player prop — `REASON_PROPS =
"nfl_props_not_gradeable_from_scoreboard"` — and calls it "a PERMANENT refusal", because the
scoreboard capture carries team scores and nothing per-player.

- **It is already firing:** `BET_STATUS orders=313 ... nfl_props_not_gradeable_from_scoreboard: 1`
  at 6:00 AM and 7:21 AM CDT, and `SETTLED date=2026-09-10` lists it as ungraded. That order
  is not in the portfolio plan or paper rows for 09-10 (both 0 NFL, `execution_mode=paper`);
  it sits in another book the resolver sweeps. **Its venue is not identified here, so no
  claim is made about real money.**
- **Therefore the 18 settled NFL rows are all game lines** — the grader refuses every prop,
  so no prop can have settled.
- **CONSEQUENCE: the 2026-09-09 decision to leave NFL props stakeable "and let the Sunday
  card grade them" cannot produce a production grade.** Venues settle the money; paper
  settlement records nothing. Scheduled task `nfl-prop-settled-grade` (09-15) has been
  rewritten to check this first and, if the grader still refuses, to grade the props itself
  from ESPN's summary rather than report "no data".

**THE "PERMANENT" PREMISE IS NOW STALE.** `nfl/live_player_box.py` reads ESPN's summary
(`site.api.espn.com/.../football/nfl/summary?event=`) and parses per-player passing, rushing
AND receiving groups — including receptions and attempts. It is cached IN-PROCESS on web
only (`_cache`, TTL, never persisted), so a grader on refresh-worker cannot read it today.
But a FINAL game's box never changes, so `bet_status_nfl` could fetch the summary itself and
grade props. **That is the fix, and it gates the whole NFL-prop staking decision.**

## Side lead, not investigated

The same `SETTLED date=2026-09-10` line shows `ncaaf_team_not_in_registry_or_ambiguous: 37`.
Unlike `game_not_in_ncaaf_live_state` (264, consistent with games not yet played), a
registry miss does not resolve with time.

## CORRECTION (2026-09-10 ~9:15 AM CDT, same session)

The "PERMANENT premise is now stale" paragraph above says `live_player_box.py` parses
per-player groups "including receptions and attempts". **That was false when written.** It
read those groups, but its reduced row kept only yards and TDs (as the grading section above
correctly says), and it dropped every player with no yards and no TD, so a 0-catch receiver
vanished instead of reading 0. As written it could not have graded receptions, attempts or
interceptions.

The fix extended that parser rather than trusting it. `2259edf8` adds an unfiltered
`player_stat_rows_from_summary` (receptions, targets, rush/pass attempts, completions, and
interceptions THROWN, read from the `passing` group only, because ESPN's `interceptions`
group holds picks CAUGHT under the same key), and `bet_status_nfl` now grades props from it,
with a player absent from a FINAL box as a named refusal, never a zero. The card's rows are
unchanged. It went live on refresh-worker at 2026-09-10 9:09 AM CDT; the production reading
is in `deploys.md` under that date. Scheduled task `nfl-prop-settled-grade` was rewritten
to use the production grader and cross-check it, and it no longer names the card parser.
