# Soccer season-to-date market audit — every market, every league, and game shape

**2026-09-15, lane `soccer-season-market-audit`, session abacd435.** Analysis only: no
engine, board or deploy change. Harness: `scripts/soccer_season_audit/` (re-runs from
its cache). Numbers: `reports/soccer_backtest/season_market_audit_2026-09-15.json`.

## Answer to "have we done this?"

**Not before today — only in pieces.** The 2026-09-14 accuracy assessment pooled 1X2,
totals, AH and BTTS over two weeks (08-31..09-13) with no per-league cut, no props and
no ROI. It called corners "unmeasurable". The 2026-08-31 lane measured shots means only.
The 2026-08-22 momentum study used last season. This file is the first season-to-date,
per-league, every-market reading.

## Sources and coverage

| family | source | window |
|---|---|---|
| model | production `soccer_source/*/api/recommendations/recommendations_*.json`, 218 files | 07-22..09-14 |
| pre-kickoff control | the same artifacts as cached on 2026-09-02 (150 files, built before kickoff for 09-02..09-09) | 09-02..09-09 |
| outcomes | ESPN box scores (score, team corners/shots/SOT, player shots/SOT/goals), 584 of 586 completed | 07-22..09-14 |
| 1X2 / O/U 2.5 / AH prices | football-data.co.uk 2026-27 CLOSING average ("typical") and maximum ("best"); MLS closing 1X2 only | 08-07..09-14 |
| BTTS / corners prices | production `props/game_markets_*.json`, last capture BEFORE kickoff | 08-22..09-14 |
| prop prices | production `props/<date>.csv`, one-sided OVER, 8 US books | 08-01..09-14 |
| momentum | FotMob, 589 current-season matches (this session) + the committed 5,552-match 2-year cache | 2024-08-09..2026-09-14 |

Player-level capture validates at **1.00** (sum of player shots / team shots and SOT) in all
ten leagues, including Belgium, where commentary capture was 0.13 on 2026-08-31. ESPN and
football-data final scores disagree on **0** matches.

| league | predicted | with outcome | FD close | BTTS/corners capture | dates |
|---|---|---|---|---|---|
| epl | 50 | 40 | 40 | 34 | 08-21..09-14 (14) |
| championship | 95 | 81 | 74 | 58 | 08-14..09-13 (17) |
| la_liga | 70 | 51 | 42 | 36 | 08-15..09-14 (25) |
| bundesliga | 36 | 27 | 21 | 24 | 08-28..09-13 (9) |
| serie_a | 50 | 40 | 40 | 36 | 08-22..09-14 (15) |
| ligue_1 | 45 | 36 | 29 | 26 | 08-21..09-13 (13) |
| eredivisie | 63 | 53 | 53 | 30 | 08-07..09-13 (19) |
| primeira_liga | 63 | 53 | 47 | 27 | 08-07..09-14 (24) |
| belgian_pro_league | 63 | 54 | 48 | 29 | 08-07..09-13 (20) |
| mls | 165 | 149 | 149 | 59 | 07-22..09-13 (17) |

**Per-league samples are 21-149 matches.** A per-league verdict below is a direction with
its CI, not a licence to optimise. Ten leagues at 95% produce about one false "significant"
cell per table by chance.

## H7 — the post-match rebuild is NOT a material leak (retires the 09-14 caveat's magnitude)

The final artifacts are rebuilt after kickoff, which the 09-14 assessment flagged as a
possible leak capping every "parity". The 09-02 cache holds genuine pre-kickoff builds.
- **1X2 on 163 matches: snapshot Brier 0.6273, final 0.6259, market 0.6023.**
- Snapshot vs final on 136 matches: 101 have identical 1X2; mean |Δ home win| 0.0067,
  |Δ total goals| 0.019, |Δ player shots| 0.071.

The rebuild moves the model by less than a tenth of its gap to the market. **Parity verdicts
are real parity, not an upper bound.** The defect itself (the published number is not
archived) still stands; it happens to be near-identical.

## 1X2 — LOSES, in the direction the ledger predicted, and worse after the 09-07 inputs

Multiclass Brier, market = de-vigged closing average (MLS Pinnacle close where present):

| group | n | model | market | diff [95% CI] |
|---|---|---|---|---|
| **ALL** | 543 | 0.6219 | 0.5943 | **+0.0276 [+0.0147, +0.0409] LOSES** |
| championship | 74 | 0.6780 | 0.6185 | **+0.0595 [+0.0146, +0.1055] LOSES** |
| belgian_pro_league | 48 | 0.5900 | 0.5311 | **+0.0589 [+0.0012, +0.1248] LOSES** |
| la_liga | 42 | 0.5698 | 0.5313 | +0.0384 [−0.0036, +0.0807] |
| primeira_liga | 47 | 0.5737 | 0.5440 | **+0.0297 [+0.0025, +0.0576] LOSES** |
| mls | 149 | 0.6700 | 0.6414 | **+0.0285 [+0.0073, +0.0494] LOSES** |
| ligue_1 | 29 | 0.6925 | 0.6693 | +0.0232 [−0.0156, +0.0638] |
| eredivisie | 53 | 0.5924 | 0.5812 | +0.0111 [−0.0217, +0.0446] |
| bundesliga | 21 | 0.5717 | 0.5790 | −0.0073 [−0.0974, +0.0747] |
| serie_a | 40 | 0.5021 | 0.5086 | −0.0066 [−0.0411, +0.0284] |
| epl | 40 | 0.6225 | 0.6312 | −0.0088 [−0.0568, +0.0457] |

- **H1 NOT FALSIFIED.** No league shows a model win whose CI excludes zero; EPL, Serie A and
  Bundesliga are parity. Log loss agrees (ALL +0.0426 [+0.0238, +0.0629]).
- **By version:** built after 2026-09-07 20:12Z **+0.0479 [+0.0187, +0.0780]** (n=125); before
  +0.0215 [+0.0077, +0.0361] (n=418). The ESPN match-stats inputs did not help. Different
  matches, so the version gap itself is not proven.
- **The favourite defect replicates on the full season.** 114 matches with a market favourite
  ≥ 0.60: **model 0.626, market 0.710, actual 0.737.** The model is under-dispersed, and the
  market is right.
- Draw rate: model 0.239, market 0.242, actual 0.273.
- **Game shape names the missing information.** A team's pre-kickoff 365-day FotMob momentum
  press gap, home minus away, correlates with the MODEL's home-win residual (r +0.079
  [−0.005, +0.164]) and not with the MARKET's (−0.011). Prior xG-difference gap: model +0.066,
  market +0.023. The market prices team dominance that the model's rating spread leaves out.

## Totals — O/U 2.5 narrowly LOSES; the model lags this season's scoring in four leagues

| group | n | model | market | diff [95% CI] | goals actual / model / market-implied |
|---|---|---|---|---|---|
| **ALL (Europe)** | 394 | 0.2377 | 0.2296 | **+0.0081 [+0.0005, +0.0151] LOSES** | 3.09 / 2.83 / 2.92 |
| championship | 74 | 0.2716 | 0.2451 | **+0.0265 [+0.0053, +0.0491] LOSES** | 2.96 / **2.39** / 2.76 |
| primeira_liga | 47 | 0.2482 | 0.2351 | +0.0131 [−0.0005, +0.0272] | 2.70 / 2.62 / 2.66 |
| la_liga | 42 | 0.2218 | 0.2069 | +0.0149 [−0.0154, +0.0414] | 3.00 / 2.83 / 2.84 |
| epl | 40 | 0.2516 | 0.2437 | +0.0079 [−0.0155, +0.0310] | 2.85 / 3.14 / 2.95 |
| serie_a | 40 | 0.2401 | 0.2342 | +0.0059 [−0.0105, +0.0226] | 3.02 / 2.68 / 2.68 |
| eredivisie | 53 | 0.1837 | 0.1903 | −0.0066 [−0.0176, +0.0049] | 3.91 / 3.39 / 3.45 |
| belgian_pro_league | 48 | 0.2509 | 0.2536 | −0.0027 [−0.0248, +0.0184] | 3.08 / 2.70 / 2.94 |
| bundesliga | 21 | 0.1775 | 0.1818 | −0.0043 [−0.0220, +0.0154] | 3.67 / 3.50 / 3.46 |
| ligue_1 | 29 | 0.2546 | 0.2551 | −0.0004 [−0.0236, +0.0217] | 2.69 / 2.85 / 2.83 |

- **H2 PARTLY FALSIFIED:** totals are not parity overall, though the loss is small.
- **Total-goals bias (actual − model):** Championship **+0.57**, Eredivisie **+0.52**, Belgian
  +0.39, Serie A +0.35, La Liga +0.17, Bundesliga +0.16, Primeira +0.09, Ligue 1 −0.16, EPL
  −0.29. All 584 matches incl. MLS: +0.105 [−0.038, +0.248].
- **This is a SCORING-ENVIRONMENT lag, and FotMob says it is league-wide.** Current season
  3.07 goals/match [2.92, 3.21] vs 2.79 over the prior two seasons. Eredivisie 3.91 vs 3.18,
  Bundesliga 3.85 vs 3.18, Serie A 3.02 vs 2.49. The market lags too (implied 2.92 vs 3.09),
  but less.
- **Prior xG environment** (both teams' 365-day FotMob xG for+against) correlates with the
  goals residual of BOTH the model (r +0.169 [+0.057, +0.275]) and the market (+0.150
  [+0.034, +0.253]) on the same 266 European rows. It is a shared blind spot, found
  post hoc: **a forward-test candidate, not a shippable rule.**

## Asian handicap (closing main line) — LOSES; betting returns the vig

ALL n=368: model 0.2658 vs market 0.2480, **+0.0178 [+0.0045, +0.0320] LOSES**. No league
significant either way. Betting edge ≥ 2..8 pp: −3.2% to −5.0% at the typical price, CIs
spanning zero; LODO held-out −5.5% [−15.7, +3.9]. That is the book's margin, not an edge.

## BTTS — parity with a stale market, and no betting edge

- vs the captured BTTS market (median **13.8 h** before kickoff, p90 21.0 h, 3.4 books):
  ALL n=359 **+0.0039 [−0.0023, +0.0107] parity**. Championship loses (+0.0176 [+0.0007, +0.0350]).
- vs a Poisson benchmark implied from the CLOSING 1X2 + O/U 2.5 (n=394): +0.0047
  [−0.0019, +0.0110] parity. Championship loses (+0.0226). Belgium "wins" (−0.0154
  [−0.0301, −0.0024], n=48). That is 1 cell of 10 — read it as the chance cell until it
  replicates.
- Rate: model 0.595, actual 0.601.
- Betting: every threshold negative at the median price; edge ≥ 8 pp −2.1% [−24.1, +19.0]
  on 77 bets.

## Team goals — LOSES to the market-implied split; away goals under-predicted

Per team-match, market = Poisson λ implied from closing 1X2 + O/U 2.5 (Europe, n=394):
- log loss **+0.0447 [+0.0239, +0.0658] LOSES** (Championship +0.0954, Belgian +0.0718).
- P(team ≥ 2) Brier **+0.0098 [+0.0038, +0.0158] LOSES**.
- Bias on all 584: home +0.011 [−0.092, +0.112]; **away +0.094 [−0.000, +0.187]**.
  The model under-scores away sides.

No team-total price is captured anywhere (`game_markets` holds only BTTS and match-total
corners), so there is no ROI to measure.

## Corners — the match-total mean carries NO information

| group | n | actual | model | bias [95% CI] | MAE model | MAE last-season league mean | r(model, actual) |
|---|---|---|---|---|---|---|---|
| **ALL** | 584 | 10.01 | 10.40 | **−0.39 [−0.69, −0.10]** | 2.92 | **2.84** | **0.02** |
| mls | 149 | 9.98 | 11.37 | **−1.39 [−1.92, −0.82]** | 3.02 | 2.82 | −0.05 |
| epl | 40 | 9.12 | 10.40 | **−1.27 [−2.16, −0.29]** | 2.77 | 2.62 | 0.09 |
| primeira_liga | 53 | 8.75 | 9.88 | **−1.13 [−2.05, −0.08]** | 3.13 | 3.01 | 0.05 |
| bundesliga | 27 | 11.44 | 10.26 | +1.19 [−0.01, +2.43] | 2.75 | 2.93 | −0.00 |

- **H3 NOT FALSIFIED, and it is worse than "biased".** The model's match-total corners
  correlate with the actual count at r = 0.02, and a constant (last season's league mean)
  beats it on MAE. It is noise around a level that is too high in MLS, EPL and Portugal.
- Team corners carry a little: r 0.30, MAE 2.24 vs baseline 2.29. The model knows WHICH side
  wins corners, not how many are in the game.
- Main line (captured, 3.9 books; mean line 9.63 vs model 10.31 vs actual 10.01): Brier
  +0.0104 [−0.0021, +0.0229], parity. EPL loses (+0.0254).
- Betting: edge ≥ 2 pp −14.7% [−27.7, −1.3]; edge ≥ 8 pp +1.1% [−17.5, +18.6] on 93 bets.
  LODO picks 8 pp and returns the same +1.1%. **No evidence of an edge.**
- In-match intensity explains the miss (see game shape). Corners follow PRESSURE, and the
  pregame model has no pressure term: bottom intensity tercile −1.61 corners vs model, top
  +0.63.
- No team-corners price is captured.

## Team shot VOLUME is under-predicted

Model vs ESPN, 584 matches: shots ratio **0.92** (Bundesliga and Serie A 0.84, Primeira 0.99),
SOT ratio 0.93. Contrast with the player props below, where the per-player means run high.

## Player props — the SQUADS are stale, and that, not the level, is the defect

Accuracy covers 10,523 appeared (player, match) rows over 524 matches, 07-22..09-14, from
ESPN box scores, with names bound one-to-one per side. Held-out means dates ≥ 08-22
(8,378 rows); the shrink is fitted only before that date.

**Roster coverage: how much of the REAL team shot volume comes from players the model
lists at all.**

| league | predicted players / team | ESPN matchday squad / team | real shots attributable to a listed player |
|---|---|---|---|
| championship | 15.5 | 20.0 | **36%** |
| primeira_liga | 19.2 | 22.5 | **53%** |
| belgian_pro_league | 21.6 | 20.2 | **56%** |
| eredivisie | 21.4 | 22.2 | 62% |
| bundesliga | 24.2 | 20.0 | 68% |
| ligue_1 | 28.3 | 20.0 | 69% |
| serie_a | 27.4 | 24.1 | 71% |
| la_liga | 24.7 | 22.8 | 76% |
| epl | 25.0 | 20.0 | 81% |
| mls | 21.6 | 19.9 | 87% |

The unbound names are what a stale list looks like: a 2026-27 Bayern list still carries
Thomas Müller, who left in 2025, beside several other absent names, while that day's
shooters are unlisted. In the Championship **two thirds of the shots are taken by players
the model does not know exist.**

**Shots and SOT means** (held-out, appeared players, `*_if_playing`):
- ALL: predicted 0.80 vs real 0.91, **ratio 0.87**; SOT 0.85. MAE 0.812 vs a constant 0.946,
  so the model still beats a constant by 14%.
- By league: Ligue 1 0.62, Bundesliga 0.68, Serie A 0.68, EPL 0.73, La Liga 0.81, Belgian
  0.94, Eredivisie 0.99, MLS 1.03, Championship 1.07, Primeira 1.09.
- **By `expected_minutes_share`: < 0.5 → 1.08, 0.5–0.85 → 0.86, ≥ 0.85 → 0.68.** Regular
  starters are under-predicted by a third; fringe players are over-predicted.
- **H4 FALSIFIED as stated.** The model does not over-predict in every league; it
  under-predicts the players who actually play, and the error is minutes/role allocation
  on top of missing players.

**This CORRECTS `[soccer-shots-prop-skill]` (2026-08-31, ratio 1.40, "ship a 1.33 divisor").**
On this data that lane's method gives **1.09–1.13**. The method was an unconditional mean
over every predicted row, with unmatched or absent players scored as zero shots, and no
view of shots taken by unlisted players. So it read the roster defect as a level error.
The train-window divisor is 1.23 on appeared rows before 08-22, yet the held-out ratio after
08-22 is 0.87. **A scalar divisor now hurts the leagues props are bet on** — MAE EPL
0.828 → 0.831, Serie A 0.835 → 0.839 — and helps only where fringe over-prediction
dominates. Do not ship it.

**Anytime scorer** (held-out, appeared):
- Predicted 0.099 vs real 0.091. Brier 0.0795 vs base rate 0.0826, only 4% better.
- Top decile predicted 0.369 vs real 0.266 (**1.39× over**).
- **The two bottom deciles are predicted exactly 0.000 and score 5.4% and 3.0%.** Players
  with no scoring history get zero, which is why log loss explodes in the Championship
  (0.78), Primeira (0.69) and Belgium (0.48).
- MLS over-predicts: 0.124 vs 0.086.

**Props vs offered prices** (one-sided OVER, 8 US books, void if the player did not appear):

| market | player-lines / matches | model Brier | implied Brier (with vig) | bet EVERY over, best price | model-edge rules, LODO held-out |
|---|---|---|---|---|---|
| shots | 20,258 / 320 | 0.1470 | 0.1741 | −50.4% [−53.2, −47.3] | raw **−31.9% [−46.1, −15.1]**; shrunk −8.3% [−42.3, +33.9] |
| SOT | 11,046 / 321 | 0.1266 | 0.1332 | −42.9% [−46.7, −39.0] | raw +28.6% [−25.9, +89.8] (47 bets); shrunk −16.7% [−46.9, +18.6] |
| anytime | 5,957 / 321 | 0.0832 | 0.0846 | −37.8% [−44.3, −30.5] | raw +47.5% [−58.8, +188.1] (46 bets); shrunk +23.6% [−67.8, +155.9] |

- The model's Brier beats the raw implied probability only because that probability carries
  the book's margin; overs on alternate lines hold 40–50%. **That is not an edge. ROI is the
  test**: raw-edge shots bets lose 25–32% at every threshold ≤ 10 pp, CIs excluding zero.
- **H5 NOT FALSIFIED for props.** The positive SOT and anytime cells are under 50 bets with
  CIs ±80–140 points.
- The same stale-squad problem appears from the market side: **18,463 priced lines had no
  model player** at all, and 13,037 were void or unbound to a box score.

## Betting — no pre-registered rule survives in any game market

| market | market-lean baseline (typical price) | best in-sample rule | LODO held-out (typical) |
|---|---|---|---|
| 1X2 | −8.0% [−16.4, +0.3] | edge ≥ 2 pp −12.5% | **−12.5% [−24.0, −0.1]** |
| O/U 2.5 | −4.3% [−12.5, +3.5] | edge ≥ 6 pp −14.2% | **−18.4% [−31.7, −4.0]** |
| AH | — | edge ≥ 2 pp −3.2% | −5.5% [−15.7, +3.9] |
| BTTS | — | edge ≥ 8 pp −2.1% | −2.1% [−24.3, +18.9] |
| corners main line | — | edge ≥ 8 pp +1.1% | +1.1% [−17.6, +18.8] |

- **H5 NOT FALSIFIED for game markets.**
- 1X2 by leg at ≥ 4 pp: home **−31.5% [−48.6, −12.3]**, away −13.4%, draw +4.1%
  [−48.4, +62.1] (64 bets). The home leg is where under-dispersion bites.
- Per league at 4 pp, every CI spans zero except MLS 1X2 (−34%), Primeira 1X2 (−65%),
  Championship O/U (−32%) and EPL corners (−42%), all negative.
- "Best price" (the maximum across ~40 European books) lifts ROI 3-5 points and changes no
  verdict. It is not reachable from a US book set anyway.

## Game shape — FotMob momentum by league

6,008 matches with momentum (5,419 prior two seasons, 589 current). Sign check: r(tilt, home
goal difference) = +0.305, so positive = home pressure.

**Prior two seasons (the reliable sample):**

| league | n | goals/match | draw% | 2H goal share | 76'+ goal share | next-goal AUC [95% CI] | dominant side wins |
|---|---|---|---|---|---|---|---|
| primeira_liga | 608 | 2.62 | 26.6 | 58.3 | 19.9 | **0.679 [0.648, 0.708]** | 69.0% |
| serie_a | 760 | 2.49 | 27.2 | 59.3 | 19.5 | 0.620 [0.593, 0.645] | 62.7% |
| bundesliga | 612 | 3.18 | 25.0 | 57.8 | 20.9 | 0.617 [0.588, 0.642] | 63.0% |
| eredivisie | 305 | 3.18 | 26.2 | 58.1 | 21.1 | 0.617 [0.577, 0.657] | 63.2% |
| la_liga | 758 | 2.65 | 25.1 | 60.0 | 22.6 | 0.613 [0.586, 0.638] | 62.5% |
| epl | 759 | 2.84 | 26.0 | 58.6 | 22.0 | 0.611 [0.586, 0.635] | 60.6% |
| ligue_1 | 610 | 2.91 | 22.3 | 59.8 | 21.7 | 0.605 [0.572, 0.633] | 60.9% |
| belgian_pro_league | 239 | 2.62 | 25.9 | 56.2 | 22.2 | 0.580 [0.530, 0.622] | 52.4% |
| championship | 550 | 2.61 | 26.5 | 56.4 | 19.2 | 0.569 [0.534, 0.599] | 58.9% |
| **mls** | 218 | 3.30 | 22.0 | 58.3 | 22.2 | **0.521 [0.469, 0.569]** | 51.0% |
| **ALL** | 5,419 | 2.79 | 25.5 | 58.5 | 21.1 | **0.611 [0.603, 0.620]** | 61.6% |

"Next-goal AUC" = mean momentum tilt over the 10 minutes before a goal, as a predictor of
which side scores it.

1. **Momentum's next-goal signal is LEAGUE-SPECIFIC, and absent in MLS.** MLS 0.521 sits
   below the pooled CI; Primeira Liga 0.679 sits above it. The current season agrees in
   direction (MLS 0.578, Primeira 0.700; n 154 / 53). A single global momentum weight
   over-trusts MLS and under-trusts Portugal.
2. **Late-goal timing is NOT meaningfully league-specific.** 76'+ share 19.2%–22.6% with
   overlapping CIs; second-half share 56–60%. Keep the global
   `second_half_shot_multiplier`, consistent with the 2026-08-21 finding.
3. **Momentum intensity does NOT predict goals or corners before kickoff.** Every
   combined-intensity correlation includes zero (goals: model +0.035, market +0.090;
   corners: +0.045). **H6 is falsified for momentum as a pregame input.** The xG part is
   the exception, above.
4. **In-match shape is a strong LIVE covariate.** On 564 current matches, by full-match
   intensity tercile: goals vs model **−0.19 / +0.06 / +0.43**, corners **−1.61 / −0.36 /
   +0.63**. High-|tilt| (one-sided) matches: corners +0.40 vs −1.00. A live totals/corners
   re-sim that ignores running intensity leaves this on the table.
5. **The scoring environment moved.** 3.07 vs 2.79 goals/match, and the model tracks last
   season (see Totals).

## Defects found

1. **`fotmob_match_id.py:42,44,45` pins LAST SEASON's FotMob league ids** for eredivisie
   (900368), championship (900638) and belgian_pro_league (900433). FotMob lists the
   2026-27 competitions as **937276, 938218 and 937988**. The resolver filters on
   `league_id`, so live momentum cannot resolve for those three leagues this season. The
   2-year harvest file `reports/soccer_backtest/fotmob_league_ids.json` carries the same
   stale ids, which is why the first season harvest silently returned 7 leagues. MLS
   913550 is also season-scoped and will break in 2027.
   **MEASURED on production's own resolver against the live vendor:**
   `resolve_fotmob_match_id(league=..., home_team=..., away_team=..., iso_date='2026-09-12')`
   returned None for **3/3 championship, 3/3 eredivisie and 3/3 belgian_pro_league**
   fixtures, and real ids for **3/3 each of EPL, La Liga and MLS** (e.g. Bournemouth v
   Brentford → 5795445). A first run passed arguments positionally into a keyword-only
   signature and read None on the controls too; it was discarded, not quoted. Reading past
   `live_state` files cannot show this at all: a finished date keeps only `match_box`, never
   `games[].momentum`. Fix handed to a separate session (task chip), not this lane.
2. **The player substrate is last season's.** Predicted lists miss 13–64% of real shots by
   league (table above) and carry departed players. Every props number inherits it.
3. **Players with no scoring history get an anytime probability of exactly 0.000**
   (two full deciles), and 3–5% of them score.
4. **No team-totals, team-corners or player-prop UNDER prices are captured**, so those
   markets can be graded for accuracy but never priced two-sided. MLS has no closing
   totals/AH source here either.
5. **BTTS/corners captures are ~14 h stale at kickoff** (median). Any ROI on them is at a
   price that may not have survived to the close.

## Verdicts on the pre-registered hypotheses

| | hypothesis | verdict |
|---|---|---|
| H1 | 1X2 loses, on favourites; no league wins | **NOT FALSIFIED** — +0.028 Brier; favourites 0.626 / 0.710 / 0.737 |
| H2 | totals, BTTS, team goals at parity | **PARTLY FALSIFIED** — BTTS parity; O/U 2.5 (+0.008) and team goals (+0.045 log loss) narrowly lose |
| H3 | corners biased, no edge | **NOT FALSIFIED, and worse** — the match total carries no information (r 0.02) |
| H4 | shots/SOT over-predict > 1.2 everywhere | **FALSIFIED** — appeared players are under-predicted (0.87); starters 0.68, fringe 1.08; stale squads |
| H5 | no rule survives held out | **NOT FALSIFIED** in any game or prop market |
| H6 | shape differs by league and explains residuals | **SPLIT** — next-goal signal is league-specific (MLS 0.52 → Primeira 0.68); momentum is not a pregame input; in-match intensity is a strong live covariate; prior xG environment is a blind spot the market shares |
| H7 | post-kickoff rebuild bounds the verdicts | **FALSIFIED as material** — pre-kickoff vs final Brier differs by 0.0014 |

## Learnings to implement, ranked by what they unblock

Each names the change it implies. None was made here. Every one is a mechanism change to a
calibrated engine, so it needs `model_engine_standard.md` and a held-out re-fit.

1. **Rebuild the player substrate from current-season matchday data** (props). Build lists
   from ESPN lineups and rosters (`espn_lineups` already fetches them), not last season's
   aggregates. Gate props per team on coverage: a list covering < 90% of that team's recent
   real shots withholds its props. Today the Championship would withhold everything.
2. **Fix minutes/role allocation, and RETIRE the 1.33 shots divisor.** Condition on the
   confirmed starting XI when lineups post (~1 h before kickoff). Re-fit the per-90 → match
   allocation so regular starters stop losing a third of their shots to fringe players. A
   scalar now hurts EPL and Serie A.
3. **Anytime scorer: a positional prior instead of 0, and shrink the top decile** (1.39×
   over). Recalibrate the MLS level (0.124 vs 0.086).
4. **1X2 favourite dispersion.** Feed the rating spread a prior-365d xG-difference / press
   term: the market's residual shows no trace of it and the model's does. Re-fit in the
   leak-free 1,112-match harness. 1X2 edges stay unpublished until it beats the close.
5. **In-season league scoring baseline.** Goals are +0.28/match on the prior two seasons,
   and the model trails in the Championship (+0.57), Eredivisie (+0.52), Belgium (+0.39) and
   Serie A (+0.35). Update the league baseline in-season with shrinkage; test it
   leave-one-date-out. Forward-test prior xG environment as a totals input: pre-register
   now, grade on matches after 2026-09-15.
6. **Corners: stop pricing the match total.** Rebuild from team corner rates plus a pressure
   term; in-match intensity terciles swing the corners residual from −1.61 to +0.63. Fix the
   MLS level (−1.39). Publish no corners edge meanwhile.
7. **Live model:**
   - per-league momentum weight — zero in MLS (AUC 0.52), strongest in Primeira (0.68);
   - condition live totals and corners on running intensity;
   - keep the global second-half multiplier (late-goal share is uniform, 19–23%).
8. **Restore live momentum in three leagues** — defect 1 (separate task).
9. **Capture:**
   - pull BTTS/corners nearer kickoff (median now 13.8 h);
   - capture team totals and team corners if they are ever to be priced;
   - note that prop UNDERs do not exist in the current feed.
10. **Betting posture: no soccer market has a demonstrated edge season to date.** The only
    non-negative held-out cells are corners ≥ 8 pp (+1.1%, 93 bets), SOT raw ≥ 15 pp (47 bets)
    and anytime raw ≥ 15 pp (46 bets). All are watch-list items to pre-register and grade
    forward, not stakes.

## Not covered here

- **Live markets:** the 2026-09-14 assessment's live 1X2 parity on fresh quotes stands and
  was not re-scored.
- **Venues:** Kalshi/Polymarket soccer prices.
- **Platform ledger:** its paper orders (09-14 read game_line −44.3% on 31 settled, and
  game_total +15.3% on 33, which that assessment already judged unsupported).
- **Other markets:** first/last scorer, cards and assists.
