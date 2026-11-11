# College blowouts: when the bench comes in, what it does to scoring, and whether our live re-sim misses it (todo #787)

2026-11-11, lane `college-pbp-blowout-bench`, session 0f519972. READ-ONLY study plus one data-capture change.

User asked, 2026-11-11:
- "are we saving game shape data? 3 games today have already been wrong badly the latest being the WNCAAB game for South Alabama and Florida Atlantic";
- "the pbp should be looked at...and tendencies for when bench players come into a blowout".

Script: `scripts/college_blowout_bench_study.py`. It reads the nightly `basketball-rotation-stints` tables and `live_evidence/`. Run on the fleet data root at nice 19.

## What is saved (verified on the fleet 2026-11-11)

| store | NCAAB | WNCAAB |
|---|---|---|
| live re-sim per tick (`live_evidence/<sport>/<date>.jsonl`): score, period, clock, proj total / margin (anchored + raw), win prob, margin distribution | yes, since 11-09 | yes, since 11-09 (65 ticks for USA @ FAU) |
| final score per period (scoreboard) | yes | yes |
| pregame sim per-period histograms | yes | yes |
| full play-by-play incl. substitutions (`processed/pbp_events/<season>/<event>.jsonl.gz`) + lineup / player stints | yes: 6,275 games 2025-26, 588 games 2026-27 | **NO until this lane** (the job's `LEAGUES` lacked it) |

- The live momentum capture streams ESPN's full summary every 150 s, but keeps only scoring events and team fouls, in a file it overwrites.
- USA @ FAU's ESPN feed holds 504 plays, 148 of them substitutions; none of that was on our disk.

## The game the user named: South Alabama 57 @ Florida Atlantic 85 (WNCAAB, 11-11)

- **Pregame / tip:** market-anchored FAU -11.1, total 136.0; raw sim FAU -2.1. Final: FAU +28, total 142.
- **Late:**
  - At Q4 2:41 left, 48-76: projected total 132.9, i.e. 8.9 more points; 18 came.
  - At Q4 2:08 left, 49-79: projected 135.2, i.e. 7.2 more; 14 came.

## NCAAB, 2025-26 season (6,258 score-matched games, regulation only)

**Q1: when starters leave.** Duration-weighted starters on the floor for the LEADING team, by lead (rows) x minutes left (columns):

| lead | 10-8 | 8-6 | 6-4 | 4-2 | 2-0 |
|---|---|---|---|---|---|
| <10 | 3.48 | 3.67 | 3.67 | 3.79 | 3.63 |
| 10-14 | 3.44 | 3.66 | 3.64 | 3.70 | 3.33 |
| 15-19 | 3.30 | 3.49 | 3.41 | 3.23 | 2.10 |
| 20-24 | 3.10 | 3.25 | 2.87 | 1.82 | 0.91 |
| 25+ | 2.33 | 2.02 | 1.34 | 0.70 | 0.45 |

- The bench takes over at a lead of about 25 with ~6 min left, or about 20 with ~3 min left.
- The trailing team empties its bench a little later (25+: 2.02 at 6-4, 0.93 in the last 2 min).

**Q2: what the bench does to scoring.** Both teams' points per minute in the leading team's last-10-minute stints, as a ratio to that game's own rate over its first 30 minutes. Game-clustered 95%:

| lead | bench (<= 1 starter on) | mixed (2) | starters (>= 3 on) |
|---|---|---|---|
| <10 | 1.67 +- 0.86 (176 games) | 1.66 +- 0.20 (1,002) | 1.34 +- 0.03 (3,643) |
| 10-14 | 1.63 +- 0.38 (136) | 1.42 +- 0.10 (479) | 1.35 +- 0.04 (2,091) |
| 15-19 | 1.28 +- 0.13 (366) | 1.32 +- 0.15 (493) | 1.26 +- 0.09 (1,413) |
| 20-24 | 1.13 +- 0.05 (553) | 1.39 +- 0.21 (444) | 1.18 +- 0.07 (830) |
| 25+ | **1.08 +- 0.04 (1,150)** | 1.13 +- 0.05 (715) | **1.16 +- 0.04 (772)** |

- Every late state scores faster than the game's own early pace (endgame fouling, the clock).
- In a 25+ blowout, bench lineups score about 7% SLOWER than starter lineups at the same lead, and the intervals do not overlap. At 20-24 the two overlap.
- So the bench does not speed a men's blowout up.

## NCAAB, 2026-27 so far: does our live re-sim miss the bench?

586 games, of which those with live re-sim ticks since 11-09. Remaining-points error (actual - projected), ticks with < 10 min left, game-clustered:

| lead x leader's lineup at the tick | error | games (ticks) |
|---|---|---|
| close (< 10) | **+3.0 +- 2.7** | 41 (357) |
| 20-24, bench | +0.6 +- 1.6 | 10 (21) |
| 25+, bench | -0.7 +- 1.2 | 27 (130) |
| 25+, starters | -0.2 +- 2.3 | 22 (67) |

The broader cut over all of 11-09..11-11, by lead only, agrees (from this session's earlier pass):
- 20+ leads late: -0.3 to +0.1.
- Close games late: +5.1 (last 5 min) and +6.9 (5-10 min).

## Verdict

**NCAAB: EXONERATED, on this data, as a cause of our live misses.**
- The bench comes in at ~25-point leads with ~6 min left, and slightly SLOWS scoring.
- Our live re-sim's late-blowout error is ~0, with or without the bench on the floor.
- The systematic late miss is CLOSE games (+3 to +7 points still to come): endgame fouling and overtime. That is lane `ncaab-score-effect-load`'s problem (#768 / RC46, `solver_endgame_pts_per_team`).
- The NBA / WNBA engine's blowout bench-rest mechanism belongs to lane `basketball-scenario-calibration`.

**WNCAAB: same pattern, smaller sample; the bench is not what went wrong in USA @ FAU.**

Measured on 2026-27, 11-01..11-10: 573 games backfilled this session. The job's own verifier passes: 573 of 573 games reproduce the official score, and 11,978 of 12,572 player-games are within 1 minute of the box score.

- **Q1, when** (leader's starters on the floor):
  - 25+ lead: 2.21 (10-8 min left), 1.11 (6-4), 0.68 (4-2).
  - 20-24 lead: 1.36 (4-2), 0.82 (last 2).
- **Q2, effect:** at 25+, bench lineups score 0.97 +- 0.05 (267 games) vs starters 1.05 +- 0.06 (196) x the game's own first-30-min rate, i.e. slightly SLOWER. Women's late games barely speed up over their early pace (close games 1.11 +- 0.07, against the men's 1.34).
- **Q3, our model:** 25+ with the bench on: -0.6 +- 3.2 (7 games). Every 10-19-lead cell is 1-2 games, too few to read.
- **USA @ FAU (57-85):** FAU's 4th quarter went 40 points (17 + 23) against ~33 projected at its start. The bench in a blowout lowers the scoring rate on average, so it does not explain a late under-projection.
- **Re-read once the nightly job has archived ~2 more weeks of WNCAAB finals with live ticks:** `college_blowout_bench_study.py --league wncaab --evidence`.

## Capture change (this lane)

- `scripts/build_basketball_rotation_stints.py`: `LEAGUES` gains `wncaab`, and `WINDOWS["wncaab"]` gets the men's calendar.
- The nightly 11:45Z job runs the default list, so it now archives every WNCAAB final: pbp_events, stints, player_stints, the checks. That holds from the next fleet ff; the job runs from disk, so no restart is needed.
- Tests: 2 new in `tests/test_basketball_rotation_stints.py`.
- This season (11-01..11-10) was backfilled on the fleet from this lane's worktree: 579 games, 573 event logs, 736 s, 1 request/s at nice 19. 11-11 onward comes from the nightly job, once the fleet carries `3f11114c2`.
