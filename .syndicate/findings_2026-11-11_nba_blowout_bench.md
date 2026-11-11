# NBA blowouts: when the bench comes in, what it does to scoring, and whether our live re-sim misses it (todo #788)

2026-11-11, lane `nba-pbp-blowout-bench`, session 63276f7e. READ-ONLY study; no capture change was needed.

User asked, 2026-11-11: "take a look at all the game shape work NCAAB/WNCAAB session (the layer 2 rail session just
did) - do this for NBA now". That work is todo `#787` (`.syndicate/findings_2026-11-11_college_blowout_bench.md`).

Script: `scripts/nba_blowout_bench_study.py`, the college study on NBA geometry.
- Q1 and Q2 use the 4th quarter (12 of 48 minutes) against the first 36 minutes. The college study used the last 10 of 40 against the first 30.
- Q1 weights each stint by its seconds inside each minutes-left bucket. NBA stints are cut at every period, so the college rule (whole stint under its start) would drop every stint starting at the 4th-quarter tip.
- Q3 reads the re-sim's own tick history (`nba_source/data/processed/live_resim_history/`, kept since 2026-10-16), not `live_evidence/` (NBA's starts 11-09).
- Q3 adds a split by the ENGINE's own blowout flag (`basketball_engine/engine.py`): period >= 3 and |margin| >= 18, or the 4th and >= 15. Under it the engine scales turnovers x0.94 and efficiency x0.96. The leader's bench rest (`blowout_bench_rest`) is OFF in production.
- Tests: `tests/test_nba_blowout_bench_study.py` (14). 6 source mutations, each caught.
- Run on the fleet data root at nice 19, at 2026-11-11 21:0xZ (3:0x PM CST). Season types: regular, play-in, playoffs (preseason rotations are not game rotations).

## What is saved (verified on the fleet 2026-11-11)

Unlike WNCAAB, nothing was missing. The nightly `basketball-rotation-stints` job has covered `nba` all along.

| store | NBA |
|---|---|
| full play-by-play incl. substitutions (`processed/pbp_events/<season>/`) + lineup / player stints | 2025-26: 1,401 games, 1,395 reproduce the official score. 2026-27 through 11-10: 227 games, 225 match (the 2 misses are preseason) |
| the live re-sim's per-tick history (`live_resim_history/`) | 10-16..11-11: 8,526 fresh re-sim rows, 172 games |
| live re-sim per tick in `live_evidence/nba/` | since 11-09 only |

- Cross-check: all **160 of 160** regular-season games the live re-sim saw (10-20..11-10) are archived, and all 160 match the official score.
- 11-11's games are archived by tonight's 11:45Z job.

## NBA, 2025-26 season (1,321 score-matched graded games, regulation only)

**Q1: when starters leave.** The LEADING team's starters on the floor (seconds-weighted), by lead (rows) x minutes left in the 4th (columns):

| lead | 12-10 | 10-8 | 8-6 | 6-4 | 4-2 | 2-0 |
|---|---|---|---|---|---|---|
| <10 | 2.34 | 2.61 | 2.99 | 3.49 | 3.89 | 3.90 |
| 10-14 | 2.32 | 2.55 | 3.04 | 3.51 | 3.85 | 3.35 |
| 15-19 | 2.22 | 2.47 | 2.97 | 3.30 | 2.98 | 1.26 |
| 20-24 | 2.20 | 2.37 | 2.62 | 2.35 | 1.13 | 0.41 |
| 25+ | 1.66 | 1.51 | 1.19 | 0.69 | 0.33 | 0.20 |

- The 4th opens with ~2.3 starters on the floor even in close games (staggered rotations); they return by 4 min left.
- The bench takes over at about 25 with ~8 min left, about 20 with ~4 min left, and about 15 in the last 2 min. That is EARLIER and at smaller leads than NCAAB (25 with ~6 min left).
- The trailing team empties its bench a little later. At 25+: 1.54 at 8-6, 0.82 at 4-2.

**Q2: what the bench does to scoring.** Both teams' points per minute in the leading team's 4th-quarter stints, as a ratio to that game's own rate over its first 36 minutes. Game-clustered 95%:

| lead | bench (<= 1 starter on) | mixed (2) | starters (>= 3 on) |
|---|---|---|---|
| <10 | 0.95 +- 0.09 (212 games) | 1.11 +- 0.20 (419) | 1.06 +- 0.05 (766) |
| 10-14 | **0.85 +- 0.08 (119)** | 0.95 +- 0.06 (213) | **1.02 +- 0.04 (458)** |
| 15-19 | **0.88 +- 0.06 (222)** | 0.90 +- 0.07 (162) | **0.99 +- 0.04 (334)** |
| 20-24 | 0.94 +- 0.07 (200) | 1.04 +- 0.15 (118) | 1.01 +- 0.07 (171) |
| 25+ | 0.95 +- 0.03 (237) | 1.00 +- 0.07 (96) | 0.98 +- 0.08 (83) |

- NBA 4th quarters barely speed up over the game's own pace: close games with starters on, 1.06. NCAAB is 1.34, WNCAAB 1.11.
- Bench lineups score SLOWER than starters at the same lead. At 10-14 and 15-19 the gap is 12-17%, and the intervals do not overlap. At 20+ it is 3-6%, and the intervals overlap.
- So, as in college, the bench does not speed an NBA blowout up.

## NBA, 2026-27 so far (160 games, 10-20..11-10): does our live re-sim miss it?

Remaining-points error (actual final total - projected total; overtime included on both sides) on 4th-quarter re-sim ticks, game-clustered. Selected cells: the 10-19 bench and mixed cells are -0.6 to +2.2 with CIs of 2.2-4.0; the full table is in the script's JSON.

| lead x leader's lineup at the tick | error | games (ticks) |
|---|---|---|
| close (< 10) | +1.6 +- 1.6 | 101 (971) |
| 10-14, starters | +1.0 +- 1.7 | 72 (250) |
| 15-19, starters | +0.8 +- 2.2 | 55 (161) |
| 20-24, bench | -0.3 +- 1.3 | 34 (90) |
| 20-24, starters | -0.9 +- 2.2 | 35 (107) |
| **25+, bench** | **-1.7 +- 1.4** | 35 (174) |
| 25+, starters | -0.7 +- 2.9 | 14 (32) |

By the engine's own blowout flag:

| | 12-6 min left | 6-0 min left |
|---|---|---|
| engine blowout | -0.4 +- 1.8 (78 games) | -0.4 +- 1.2 (77) |
| no flag | +0.8 +- 1.7 (113) | **+2.4 +- 1.4 (109)** |

**The close / no-flag late miss is overtime, all of it.** 8 of the 160 games went to overtime:

| | no OT (152 games) | OT only (8 games) |
|---|---|---|
| close, 4th quarter | -0.1 +- 1.2 (93) | +20.9 +- 5.0 |
| no flag, 6-0 min left | +0.9 +- 1.0 (101) | +21.6 +- 4.0 |
| engine blowout, 6-0 | -0.4 +- 1.2 (77) | n/a |

No level bias across the game (every regulation tick, by period):

| Q1 | Q2 | Q3 | Q4 |
|---|---|---|---|
| -1.1 +- 2.8 (152) | -0.6 +- 2.4 (159) | -0.7 +- 1.8 (160) | +0.7 +- 1.2 (159) |

## Verdict

**NBA: the live re-sim's blowout handling is EXONERATED on this data, with one small signal.**
- Where the engine's blowout flag is on, the late error is -0.4 +- 1.2 to 1.8.
- One cell leans: at 25+ leads with the leader's bench on, the re-sim projects 1.7 +- 1.4 points too many (35 games). That fits Q2, where the bench slows scoring and the production engine does not rest the leader's starters (`blowout_bench_rest` off).
  - It goes to lane `basketball-scenario-calibration`, whose `#4b` bench-rest result (b = 3) is waiting on the user (leads.md 2026-11-11).
  - No engine change was made here.
- The late miss in close games is OVERTIME, not endgame fouling: the 8 OT games err by +21 each; without them close games err by -0.1 +- 1.2.
  - So the open question is whether the re-sim's P(overtime) late in close games is right. That needs the per-sim regulation tie rate, which the history does not keep (leads.md 2026-11-11).
- No level bias (Q1-Q4 all within +-1.1, every CI covers 0). The ~+3 rest-of-game over-projection `#695` noted on 10-13 (P3's backtest gate) does not show in the 2026-27 live ticks.

**Pre-registered falsification, by the letter:**
1. "A 20+ lead bench cell whose CI excludes 0 by more than 1.5 points": **NOT met**. 25+ bench is [-3.2, -0.3]; it excludes 0 by 0.3.
2. "Engine-blowout ticks erring in a different direction from non-blowout ticks beyond both CIs": **MET by the letter**.
   - In the last 6 min the two intervals are [-1.6, +0.9] vs [+1.0, +3.8].
   - The no-flag side's excess is the 8 OT games. Without them it is [-0.2, +1.9], overlapping. So the clause fired on overtime, not on blowouts.
   - The clause was too loose: it compared two states without saying which one is wrong. Recorded, not explained away.

## Compared with college (#787)

| | NCAAB | WNCAAB | NBA |
|---|---|---|---|
| bench takes over (lead, min left) | 25, ~6 | 25, ~6 | 25 at ~8, 20 at ~4, 15 in the last 2 |
| bench vs starters at 25+ (x own pace) | 1.08 vs 1.16 | 0.97 vs 1.05 | 0.95 vs 0.98 (10-19 leads: 0.85-0.88 vs 0.99-1.02) |
| late close games vs own pace | 1.34 | 1.11 | 1.06 |
| re-sim late-blowout error | ~0 | ~0 (7 games) | ~0 under the engine flag; 25+ bench -1.7 +- 1.4 |
| re-sim late close-game error | +3.0 +- 2.7 (endgame) | n/a | +1.6 +- 1.6, all of it overtime |

Re-run: `python scripts/nba_blowout_bench_study.py --start 2026-10-20 --end <date> --evidence --data-root ~/syndicate-prod/data`. The Q3 sample doubles in about three weeks.
