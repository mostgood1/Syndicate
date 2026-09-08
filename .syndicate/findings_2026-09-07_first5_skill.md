# first5 HAS skill against climatology. It does NOT yet beat the market.

**2026-09-07, lane `mlb-live-segment-pricing`, session 3492626c.**
Scripts: `scripts/backtest_mlb_first5_skill.py`,
`scripts/analyze_mlb_first5_bias.py`,
`scripts/backtest_mlb_first5_vs_market.py`. Raw: `reports/first5_skill.json`.

## The question, and what could actually be measured

The live first-five readout (`70622e0b`) is not deployed, so there is no served
history to score. What IS scoreable is the **pregame** first5 block the daily sim
has written all season — `outputs[].first5.{home_win_prob, away_win_prob,
tie_prob}` — out of the same `simulate_game` engine, counting the same event over
the same trials from an initial state rather than a mid-game one.

So this answers a **necessary condition**, not the live question directly. Said
plainly rather than blurred: if the engine's five-inning modelling had no skill
from a pregame state, the live version built on it would be very unlikely to
acquire any.

Outcomes come from MLB StatsAPI (`schedule?hydrate=linescore`), not the local
mirror — production carries **no** `feed_live` and **no** `roster_objs`, so the
mirror could not have answered this at all.

## Result 1 — the segment models discriminate; the full-game model does not

Out-of-sample: dates split chronologically, earlier half fits nothing but the
bias shift, later half scores. Terciles by predicted probability, decisive games.

| segment | separation (top − bottom tercile) | sigma | n (test) |
|---|---|---|---|
| **first5** | **+0.2199** | **3.82** | 423 |
| first3 | +0.2177 | 3.63 | 372 |
| first1 | +0.1096 | 1.38 | 219 |
| **full** | **+0.0479** | **0.88** | 501 |

first5's top tercile wins **67.4%**, its bottom tercile **45.4%**. A bias shift
cannot create separation — only signal can.

**The inversion is the finding.** The segment nobody prices discriminates at
3.8 sigma; the full-game path that IS priced and bet separates at 0.88 sigma,
indistinguishable from noise on 501 games.

A plausible mechanism, offered as hypothesis and **not** as a measured cause:
over nine innings bullpens, pinch hitters and late variance wash out the
starting-pitcher matchup, while over five innings that matchup dominates — and
the starter is the component this engine models most heavily
(`pitcher_distributions`, `pitcher_so_model`, arsenal). Untested here.

## Result 2 — the tie probability is calibrated, which validates shipped code

`first5` predicted tie **0.1567** against actual **0.1557** over 1,015 games —
a gap of 0.001. `full` carries `tie_prob 0.0`, correctly.

This matters beyond bookkeeping: `live_gameline_join.segment_home_win_prob`
divides by `(1 − tie)` to match a two-way book's leg frame. That conditioning is
only sound if `tie_prob` is calibrated. It is.

The odds artifact independently confirms the frame distinction is real:
`markets.segments.first1.h2h` carries `is_3_way: true` with `draw_odds`, while
`first5` is quoted two-way.

## Result 3 — against the MARKET, no demonstrated edge, on a thin sample

| | Brier over the same 108 games |
|---|---|
| model | 0.25016 |
| market | 0.24653 |
| **delta** | **+0.00363 — the market is better** |

Betting the model's side where it disagrees: at edge ≥2%, n=80, win rate 0.4750
against market-expected 0.4452 (**+0.53 sigma**); at edge ≥5%, n=48, 0.4583
against 0.4228 (**+0.49 sigma**). Neither is significant. Every per-bucket
disagreement cell is n<30 and is reported UNMEASURED rather than as a rate.

**This rests on 12 dates, not 78.** The model family covers 2026-05-28..08-17;
the F5 market family covers only **2026-06-04..2026-07-08**, so the join
collapses to 12 dates and 108 games. That is the coverage trap `CLAUDE.md`
names, caught by printing coverage first.

Also: **one book per game**, not a consensus — `min_books=2` dropped 137 of 145
rows. A single book's de-vig carries that book's whole vig as noise.

## What this does and does not license

- **Does:** the first-five number carries real information. The three-hop
  pipeline (`70622e0b`, `d133ba6c`, `e5bfef89`) is pointed at the right target,
  and the tie-conditioning in it is empirically sound.
- **Does NOT:** justify turning `SYNDICATE_MLB_FIRST5_PRICING` on. Skill against
  climatology is not an edge against a book. 108 games over 12 dates cannot show
  an edge and cannot rule one out.

## The next measurement, and a decision it reverses

The blocker is F5 market history, and the reason we have so little is a choice I
made earlier today: the segment ledger rows shipped in `16b7ad1f` deliberately
carry **no** `market_fair_prob`, so they dedupe to one row per market per day and
cannot fill the file. That was right for a *counting* fix and is now the binding
constraint on the *measurement*.

With skill demonstrated, recording the segment market price has a measured
reason it did not have this morning. It needs its own file rather than this
one's headroom — `append_records` stops writing for the rest of the day at
`_MAX_RECORDS_PER_FILE`, and MLB already wrote 8,070 rows on 2026-08-21 against
that 20,000 cap.

Re-run the market comparison once that series has depth. Until then the flag
stays off.
