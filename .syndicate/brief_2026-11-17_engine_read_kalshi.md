# Brief to the live sim owners: what Kalshi's price says the re-sims get wrong (2026-11-17)

From lane `engine-learner`, umbrella #736. The reading is `.syndicate/findings_2026-11-17_engine_read_kalshi.md` (dev slates, live full-game lines, measured against
Kalshi's in-play mid). Measured against the books, a re-sim can look fine while losing to the market we trade. Against
Kalshi, the live re-sims never forecast better in any sport, market or clock bucket, and the learner finds no weight to
give them (`findings_2026-11-17_kalshi_prior_learner.md`). The fixes below are the specific inputs and settings.

| todo | owner | what is wrong | the knob | how to tell it worked |
|---|---|---|---|---|
| `#834` | NBA live re-sim | its pregame total starts ~2 pts (about 1%) above Kalshi's, so its totals lean to the over until late | the pregame total or scoring rate it starts from | 0-25% gap within +/-0.5 pts |
| `#835` | NCAAF live re-sim | its spread of final totals is ~20% too narrow (sd ratio 0.75-0.85), and it expects a catch-up in slow games | the scoring variance (~1.2x), and the rest-of-game reversion | sd ratio 0.95-1.05; calibration slope >= 0.8 |
| `#836` | every live re-sim / the evidence cadence | in the last 5% of a game its state is often over 30 s old, and then it loses badly (a fresh state beats Kalshi) | faster refresh late, or refuse when the state is older than 30 s | the 95-100% log-loss gap |

**The queue** of the biggest disagreements Kalshi won, one row per game, is in `.syndicate/findings_2026-11-17_engine_read_kalshi.md`, for looking at games by hand.

**Limits:** five dev nights; NCAAF rests on one Saturday. A re-run on 11-09..11-22 is scheduled for 11-24 at 6 PM CST,
after M2's read. The kit is reproducible: `C:\tmp\elp\engine_read` (`totals_ladder.py`, `ladder_analysis.py`, `staleness.py`).
