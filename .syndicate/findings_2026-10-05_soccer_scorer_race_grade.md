# First / last goalscorer, graded at the price — 2026-10-05

Lane `soccer-scorer-race-grade` (session b9bb5f37). Script:
`scripts/soccer_season_audit/grade_scorer_race.py`, run with
`SOCCER_AUDIT_CACHE=C:/tmp/soccer-lpb/cache` (the 10-02 props backtest's cache) and ESPN
summaries cached in `%TEMP%/espn_shots_cache` (715 matches, 712 full time).

## What was graded

- **Model:** the probability the board serves: production `scorer_race(player_props,
  match_expected_goals=total_mean)` on PRE-KICKOFF builds only (`load_recs(prekickoff_only=True)`).
  Last scorer uses the same number, which is the board's own time-reversal assumption.
- **Outcome:** ESPN `keyEvents` scoring plays, ordered by (period, clock). Own goals and
  shootout goals are excluded. A player who did not appear is void. A tied order at first
  or last refuses the match (4 matches).
- **Price:** `props/<run-date>.csv` has no capture time, so a match is priced only from the
  latest file whose run date is STRICTLY BEFORE its kickoff date (Central). Those prices can't
  be in-play; they are early prices (the day before or earlier), not closes. Prices are
  one-sided (yes only), so they're compared to the raw implied probability WITH vig. Bets are
  1u flat at the best price on the model's EV>0 side.

## Coverage: what the result rests on

| family | dates |
|---|---|
| pre-kickoff builds | 25 |
| ESPN outcomes | 24 |
| price files | 61 |
| matches priced pre-kickoff | 22 |
| **intersection** | **22 dates, 07-22..09-30, 200 matches** |

Dropped: 96 matches not priced pre-kickoff; 4,158 priced players not in the model's race (the
sim lists fewer players than the books price); 2,927 player-lines void (did not appear).

## Results (CI = 95% match bootstrap)

| market | player-lines / matches | hit rate | mean p model / implied | EV>0 bets (wins) | ROI EV>0, best price | ROI at median price |
|---|---|---|---|---|---|---|
| first scorer | 3,575 / 200 | 3.27% | 2.93% / 6.20% | 305 (17) | **-34.8% [-69.9%, +12.6%]** | -41.2% |
| last scorer | 3,309 / 177 | 3.17% | 2.89% / 6.21% | 264 (7) | **-66.8% [-92.4%, -31.5%]** | -68.4% |

- **Last scorer: an ESTABLISHED loss at the price** (CI wholly below zero). On the registry's
  rule, `established_loss_rel` = 0.315, which ranks and sizes at the 0.5 floor.
- **First scorer: no established loss** (CI reaches +12.6%). The point estimate is -34.8%, so
  the 2026-10-05 sizing rule (point estimate) stakes it at the 0.5 floor. Ranking would be
  unchanged (parity).
- **The probability itself is reasonable:** the model's mean (2.9%) sits close to the realised
  hit rate (3.2-3.3%) and well under the vig-loaded implied (6.2%). Its Brier is lower than the
  raw implied's (first -0.00128 [-0.00187, -0.00068]; last -0.00085 [-0.00144, -0.00023]). That
  is NOT evidence of beating the book: raw implied carries roughly 2x overround on these
  longshots, and there is no "no" side to de-vig. The bets are what matter, and they lose.
- **Last scorer loses more than first** although the number is the same. That fits the
  time-reversal assumption being wrong for last scorer (late goals favour substitutes and
  chasing sides). It is a lead, not tested here.
- Pooled across model versions (pre-09-07 1,553 / post 2,022 first-scorer lines). Not split.

## Not done

- Registry entries: `measured_market_skill.py` is on loan to lane `layer2-unmeasured-per-line`
  (user decision 2026-10-05). The numbers above were handed to that lane; they are not
  registered here.
