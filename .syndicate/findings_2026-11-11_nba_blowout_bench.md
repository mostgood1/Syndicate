# NBA blowouts: when the bench comes in, what it does to scoring, and whether our live re-sim misses it (todo #788)

2026-11-11, lane `nba-pbp-blowout-bench`, session 63276f7e. READ-ONLY study; no capture change was needed.

User asked, 2026-11-11: "take a look at all the game shape work NCAAB/WNCAAB session (the layer 2 rail session just
did) - do this for NBA now". That work is todo `#787` (`.syndicate/findings_2026-11-11_college_blowout_bench.md`).

> **CORRECTED the same day (todo #789, lane `nba-resim-overtime-prob`): the overtime miss below is mostly an OLD BUG,
> not a wrong overtime chance.** 7 of the 8 overtime games were played before `#763` reached live-odds-worker
> (2026-11-05 22:37:35Z). Until then the re-sim's projected total left overtime points out ENTIRELY, so those games
> erred by their whole overtime by construction. The 8th game, after the fix, is one game. See "Addendum (#789)" at
> the end. The blowout and bench results are unaffected: no overtime game was a blowout.

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
  - **CORRECTED (#789):** 7 of the 8 came before `#763` put overtime in the projected total (2026-11-05 22:37:35Z). Their +21 is that old omission, not a P(overtime) estimate. See the addendum.
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

## Addendum (#789, 2026-11-11, lane `nba-resim-overtime-prob`): the overtime miss was the pre-#763 projection

The user said "Yes, record it" to recording the re-sim's own overtime chance. Before building that, I dated the 8 overtime games against the two changes that decide what a history row can say about overtime:
- `d6a691168` (`#763`) put overtime points in the projected total. live-odds-worker loaded it at 2026-11-05 22:37:35Z (deploys.md). Before it, a simulated overtime counted as a regulation tie with no OT points.
- `3d376da7c` (`#762`) made the `h2` segment q3 + q4 + every overtime. It was loaded at 2026-11-06 15:51:30Z. On the fleet, 0 of 578 rows on 11-04/11-05 have `h2 - q3 - q4` above 0, against 256 of 403 on 11-06.

| | before #763 | after #763 |
|---|---|---|
| overtime games, late close ticks (6-0 min, lead < 10) | +21.2 +- 4.5 (7 games) | +24.7 (1 game, 401909942, 11-07 slate) |
| no-overtime games, same ticks | +0.7 +- 0.9 (65) | +1.6 +- 3.8 (17) |

- The 7 early games each erred by about their whole overtime (15-26 points). That is the omission, by construction: their late-close rows' `h2 - q3 - q4` reads 0.0.
- The one game after the fix had 5.5 expected overtime points across its late close ticks and scored 25 in overtime.
- **The lane's hypothesis ("P(OT) too low late in close games") is NOT SUPPORTED.** Its evidence was the old omission. After the fix it is undecided: one overtime game.

**The re-sim's expected overtime points against the real ones** (`q4_overtime.expected_ot_points`, rows since 3d376da7c, 37 games 11-06..11-10, game-clustered):

| tick | expected OT points | actual | games (OT games) |
|---|---|---|---|
| Q1-Q3, all ticks | 0.47 | 0.68 | 37 (1) |
| Q4 12-6 min, lead 0-2 | 1.30 | 3.13 | 8 (1) |
| Q4 6-0 min, lead 0-2 | 2.77 | 8.33 | 3 (1) |
| Q4 6-0 min, lead 3-5 | 1.00 | 0 | 12 (0) |
| Q4 6-0 min, lead 6-9 | 0.43 | 0 | 16 (0) |
| Q4, lead 10+ | 0.03-0.09 | 0 | 26-28 (0) |

- Summed over the 37 games' Q1-Q3 ticks: 17.3 overtime points expected and 25 scored (one game), about 0.8 overtime games expected at the 21.6 points the season's 8 overtimes averaged, against 1. Consistent.
- A rare event: with 0 or 1 overtime game a cell's interval only measures the expected side, so read the counts, not the ci95.

**What now records it:**
- `resim_live_game` counts the draws whose regulation ends level: `overtime_prob`, published on the lane as `modelOvertimeProb` and kept in `live_resim_history` as `p_ot`. ON MAIN; loading it on live-odds-worker is the user's decision.
- `q4_overtime.p_ot` grades it against whether each game went to overtime, on rows that carry it.
- Overtime is rare (8 of 160 games this season, 5%), so a decisive sample of late close ticks will take weeks of slates.

**Engine finding, not pinned (synthetic test inputs, 300 draws):**
- Tied, home ball: P(OT) is 1.0 at 2, 4 and 6 seconds left, 0.57 at 8, 0.48-0.52 at 10-20 and 0.36 at 30.
- So the engine scores nothing in the last 6 seconds, and its P(OT) for a tied game in that window is too HIGH. A real final possession sometimes scores.
- Few ticks land there (the re-sim ticks about once a minute). Routed to lane `basketball-scenario-calibration` (leads.md).

Re-run: `python scripts/nba_blowout_bench_study.py --start 2026-10-20 --end <date> --evidence --data-root ~/syndicate-prod/data` (`q4_overtime`).
