# College quote-order check, re-measured against the last score change (2026-11-08)

Lane `ncaab-live-resim-capacity`, session c3107f70. Read-only. User: "Yes, measure it here", answering "Re-measure the quote-order check against the last score change?". Written 2026-11-08 11:12 AM CST.

## Why this was measured

- Workers=2 (deploys.md 2026-11-08 03:28:10Z) made college lanes fresh: 18-40 s old at the board build.
- After that, NCAAB priced 0 rows on both builds. Every full-game row that reached the quote checks was refused, most as `quote_older_than_the_score_the_model_saw`.
- That check (`live_gameline_join.quote_behind_score_verdict`, lane `wncaab-module`, `59638f001`) refuses a quote taken more than 30 s before the lane's `as_of`.
  - For college, `as_of` is the time the state was FETCHED (`ncaab/live_resim.py:562`).
  - NCAAB odds refresh about every 240 s, so a fresh lane is newer than nearly every quote.
- The check rests on a measured table (11-03..11-05): the model "beat" the market only where the quote predated the score, "an edge nobody can take".
- **Question:** is that edge from SCORE CHANGES between the quote and the state? If so, judging the quote against the last score change would keep the protection and refuse far fewer rows.

## Method

- **Records:** fleet live-gameline ledgers, copied read-only. ncaab 11-02..11-06 graded, wncaab 11-03..11-06. Records written before the gate loaded (2026-11-07 16:29:14Z); after that, refused rows leave the ledger.
- **Population:** priceable full-game spreads, totals and h2h.
- **Grading:** ESPN finals (completed games only).
  - Spreads: the ledger's `line` is a threshold on the HOME margin, P(home margin > line). The model's own margin agrees with that reading in 8,971 of 8,986 priced ncaab records.
- **Score-change times:** each scoring play's ESPN `wallclock` from the game summary.
- **Brier diff:** (model − y)² − (de-vigged market − y)². Negative = the model beat the market.
- **SE:** clustered by game, because records within a game are correlated.
- **Buckets** by quote time minus `live_state_as_of`: older than 30 s / within 30 s / newer than 30 s.
  - The "older" bucket is split into **A**, no scoring play in (quote, as_of], and **B**, at least one.
  - Plays count only up to `as_of − lag`, with lag 0 / 20 / 45 s, because the state holds only plays ESPN had published. Results are stable across the three; lag 20 is shown below.
- **Reproduces the gate's table** on its own window (11-03..11-05):
  - wncaab spreads older / within / newer: −0.0556 / +0.0090 / +0.0130, against the table's −0.0562 / +0.0090 / +0.0146.
  - ncaab spreads: −0.0125 / +0.0124 / +0.0275, against −0.0177 / +0.0061 / +0.0247.
  - ncaab totals: +0.0093 / +0.0430 / +0.0376, against −0.0015 / +0.0319 / +0.0326. Within one SE.
  - 10 men's games did not match by name, so I have about 20% fewer men's records.
- **Script:** `scripts/college_quote_order_by_score_change.py`. Its first version graded spreads with the wrong sign, and the reproduction above caught it.

## Result (Brier model − market, ± game-clustered SE; n records / games)

| | older: A, no score change | older: B, score changed | within 30 s | newer: quote saw a newer score | newer: quote saw no new score |
|---|---|---|---|---|---|
| ncaab spreads | **−0.0043 ± 0.0100** (1,223 / 150) | **−0.0221 ± 0.0083** (4,974 / 172) | +0.0078 ± 0.0093 (1,173 / 151) | +0.0368 ± 0.0090 (6,557 / 193) | +0.0254 ± 0.0112 (1,145 / 144) |
| ncaab totals | +0.0206 ± 0.0131 (2,178 / 156) | +0.0018 ± 0.0107 (5,468 / 174) | +0.0305 ± 0.0125 (1,680 / 151) | +0.0476 ± 0.0109 (9,076 / 193) | +0.0117 ± 0.0108 (1,800 / 150) |
| ncaab h2h | +0.0191 ± 0.0147 (87 / 45) | +0.0136 ± 0.0107 (186 / 67) | +0.0632 ± 0.0326 (83 / 42) | +0.0395 ± 0.0085 (705 / 125) | +0.0119 ± 0.0153 (114 / 55) |
| wncaab spreads | −0.0180 ± 0.0160 (159 / 28) | **−0.0601 ± 0.0104** (1,047 / 28) | +0.0047 ± 0.0207 (162 / 26) | +0.0373 ± 0.0285 (176 / 26) | −0.0488 ± 0.0215 (77 / 23) |
| wncaab totals | −0.0260 ± 0.0324 (408 / 29) | −0.0366 ± 0.0264 (1,393 / 29) | −0.0214 ± 0.0247 (308 / 28) | −0.0109 ± 0.0344 (266 / 27) | −0.0143 ± 0.0204 (130 / 28) |

1. **The hypothesis survives.** Where the model "beat" the market, it was where a score changed between the quote and the state:
   - ncaab spreads: −0.0221 with a score change, −0.0043 ± 0.0100 without (the market's level).
   - wncaab spreads: −0.0601 with, −0.0180 ± 0.0160 without (not distinguishable from 0).
   - Totals and h2h show no edge in either part.
   - So comparing the quote with the last score change keeps the check's protection.
2. **The rows it would re-admit (A) carry no measured edge.** In no fair comparison does the MEN's model beat the market: A, within 30 s, or newer with no new score.
   - spreads −0.0043 / +0.0078 / +0.0254;
   - totals +0.0206 / +0.0305 / +0.0117;
   - h2h +0.0191 / +0.0632 / +0.0119.
   - Re-admitting them restores coverage (priced rows, and the board's live number), not value.
3. **The largest group the old slow loop priced was its worst.** In 43-45% of all priced men's spreads and totals records, the quote had seen a newer score than the model (spreads 6,557 of 15,072; totals 9,076 of 20,202). There the model lost:
   - spreads +0.0368;
   - totals +0.0476;
   - h2h +0.0395.
   - Fresh lanes (workers=2) should remove most of that group, since lanes measured 18-40 s old after the load. The buckets themselves have not been measured since.

## Engine read: the men's live totals run low

Mean points, game-clustered:

| ncaab totals | model total − final | book line − final |
|---|---|---|
| within 30 s (1,680 / 151) | **−3.41 ± 1.10** | −1.15 ± 1.09 |
| older (7,646 / 179) | −2.57 ± 0.92 | −0.23 ± 0.95 |
| newer (10,876 / 193) | −1.43 ± 1.00 | +0.37 ± 0.91 |

- The men's live re-sim projects totals about 2.3 points BELOW the books on the same rows, and 2.6-3.4 below the final.
  - That is consistent with live totals being its weakest market here (Brier +0.012 to +0.048 in every bucket).
- Women's is the reverse: the model sits +0.3 to +1.1 points from the final, while the books are +3.7 to +4.2 high.
  - That matches the women's totals Brier at −0.01 to −0.04, but with 29 games the SE (~0.03) is too large to claim it.
- Season-phase caveat: 11-02..11-06 is the first week of the season, a different population from mid-season.

## Limits

- Ledger records are deduped on line movement, so counts are lower bounds and games with more line moves weigh more.
- 26 of 219 men's and 4 of 33 women's game keys did not match ESPN by name (e.g. "Arizona St" against "Arizona State"). Those games are left out.
- `quote_updated_at` is the quote's own time from the grid. A quote can stay posted after it, which this cannot see.
- Women's is 29 games; its rows are not evidence on their own.

## What changing the check would take (not done)

- **The lane** must publish its last score-change time, from the last scoring play's ESPN wallclock already parsed in `pbp.reconstruct`, in `ncaab/live_resim.py`.
- **The check** (`live_gameline_join.py:611-642`, lane `wncaab-module`) would compare the quote with that time instead of `as_of`. The 600 s ceiling and the lane-age gate stay.
- **Alternative:** keep pricing refused and show the live number only, as NBA does (`LIVE_DISPLAY_SPORTS = frozenset({"nba"})`, `live_gameline_join.py:1234`). Finding 2 says the men's rows carry no edge, so that would cost no value.
