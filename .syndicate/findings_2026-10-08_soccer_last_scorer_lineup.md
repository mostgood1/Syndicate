# Last goalscorer with the confirmed lineup known — 2026-10-08

Lane `soccer-last-scorer-lineup` (session b9bb5f37). The hypothesis and ship rule were pre-registered in
lanes.md (`2243e188`) before any run. Script: `scripts/soccer_season_audit/last_scorer_lineup_test.py`.
Same data, split and pricing/void rules as `findings_2026-10-05_soccer_last_scorer.md`. The data are the
10-02 props cache and ESPN summaries. Fit is before 2026-09-16; scoring is on/after, post-09-07 builds
only: **8 dates / 81 matches / 1,817 priced lines, 57 winners**.

## Why this test

The 10-05 study ended: "the fix that would matter is knowing the bench". The pipeline already knows it
within ~1 h of kickoff. `features/lineups.attach_confirmed_starters` runs inside
`build_soccer_artifacts.py`, and `player_props.build_usage_profiles` then gives starters >=0.75 minutes
share and bench players 0.15x of their season share.

There is also a second fact: a last-scorer bet on a player who does not take part is VOID. The price is
therefore for "if he plays". The board prices a bench player unconditionally, with his chance of not
appearing still counted against him.

## Method

Three races over the same players, rates and lines:
- `board`: `scorer_race`, timing-blind; this is what the board prices.
- `timed`: the 10-05 race, with the role guessed from `expected_minutes_share`.
- `lineup`: the timed race with the role KNOWN from ESPN's matchday sheet.
  - Starting XI: the starter on-pitch curve.
  - Bench: the substitute curve, and the last-scorer probability divided by P(bench player comes on) =
    0.4675 (fitted before the split on 11,742 bench entries).
  - Not in the squad: removed; their rate goes to the unlisted residual.

ESPN's `starter` flag stands in for the lineup published ~1 h before kickoff, so this is an UPPER BOUND
(warm-up changes are ignored). 20 lines were lost to name matching: the player appeared but did not match
the ESPN sheet, so the lineup race dropped him. That is small against 1,817.

## Results

Calibration, realised / expected, over appeared players on the scored matches:

| | board | timed | lineup |
|---|---|---|---|
| starters | 0.802 | 0.842 | **0.917** |
| substitutes | 3.338 | 2.948 | **0.874** |

At the price (EV>0, best price, 1u flat):

| | EV>0 bets (wins) | ROI [95% CI] | log-loss |
|---|---|---|---|
| board | 198 (7) | -55.7% [-89.3, -10.0] | 0.13829 |
| timed | 167 (6) | -51.4% [-90.1, +3.6] | 0.13544 |
| lineup | 252 (11) | -21.0% [-71.1, +44.7] | 0.13230 |

Differences:
- Log-loss, lineup minus timed: [-0.00885, +0.00262].
- Log-loss, lineup minus board: [-0.01306, +0.00089].
- ROI, lineup minus board: [-6.4, +93.3] points.

By role (lineup; EXPLORATORY, not pre-registered):
- starters: 143 bets, 6 wins, -43.3% [-88.4, +20.6];
- bench: 109 bets, 5 wins, +8.3% [-82.5, +137.4].

The board and timed races placed 2 bench bets each. Neither could see the bench price as anything but
long, because it priced bench players unconditionally.

## Verdict (against the pre-registration)

- **H1 FALSIFIED as written.** The log-loss gain vs the time-aware race has a CI including 0 (and vs the
  board too). The MECHANISM is right: the substitute miss goes from 3.34x to 0.87x, and the starters'
  from 0.80x to 0.92x. The test has too few matches to resolve it in log-loss; 81 matches have one last
  scorer each.
- **H2 / SHIP: NO.** The ROI difference vs the board has a CI including 0, and the point ROI is
  negative. Nothing changes on the board. Last scorer stays registered `loses_to_market`.
- The bench subgroup is the only cell with positive ROI. It was not pre-registered, it rests on 5 wins,
  and its CI is above. Its CI, [-82.5, +137.4], says nothing either way: a lead for a larger sample, not a result.

## Could it reach the board at all? (not measurable today)

- `SOCCER_CONFIRMED_LINEUPS` is printed by `build_soccer_artifacts.py` on every run, but the odds job
  captures the step's stdout and `_compact_step_result` blanks it. The line survives nowhere: 0 hits in 3
  days of `data/reports/migration_runs`. The instrument exists and is unreadable.
- Past dates' `recommendations*_<date>.json` (incl. the `prekickoff` freezes) are pruned; the oldest
  kept on 10-08 is 09-30. The share of priced last-scorer lines built with a confirmed XI therefore
  cannot be measured for past slates.
- It CAN be measured forward: this weekend's freezes (`recommendations_prekickoff_2026-10-09..12`) will
  hold each match's last pre-kickoff build. A side priced with a confirmed XI shows 10-11 players at
  >=0.75 minutes share.

## What would change the verdict

A larger out-of-sample window (more dates of the same race), and a measured reach. Shipping would mean
adding a lineup role and an appear-conditional bench price to `soccer_scorer_markets`, under
`model_engine_standard.md`: an input checklist, a pipeline trace, and a reachability test (off != on).
