# FINDINGS: cheat-sheet sections, judged per sport against the fair and against matched non-members

Lane `cheat-sheet-section-optimization` (session 35bdf3a7), 2026-11-13, 7:30-8:45 AM CT. Read-only on the fleet: every
fleet read ran `nice -n 19`, there was no odds fetch, and nothing changed in env, code or data. This assessment asks a
different question from the daily review (`reviews/latest.md`). The review asks whether a section's W-L is beyond noise.
This one asks whether the section's SELECTION beats the price it was taken at. It also asks whether its members beat
props the section did NOT pick, in the same sport, on the same side and in the same price band.

## What the numbers rest on

- **Window:** official days only, `play_cards.OFFICIAL_START` 2026-10-15 through the 11-12 sheets (reconciled at 6:50 AM CT
  11-13). That is 29 sheet dates. No sport covers all 29:

  | sport | featured bets (dates / games) | graded sheet rows (dates / games) | window |
  |---|---|---|---|
  | NBA | 1,643 (25 / 180) | 6,053 (23 / 174) | 10-15..11-12 (rows from 10-20) |
  | NHL | 1,405 (29 / 201) | 1,991 (29 / 199) | 10-15..11-12 |
  | NFL | 672 (13 / 58) | 4,936 (13 / 58) | 10-15..11-12 |
  | NCAAF | 663 (21 / 169) | 2,395 (21 / 170) | 10-15..11-12 |
  | soccer | 261 (24 / 175) | 2,929 (21 / 274), only 51 two-sided | 10-16..11-08 |
  | WNBA | 280 (7 / **7**) | 1,112 (7 / 7) | 10-17..10-31, season over |
  | MLB | 364 (9 / **10**) | 1,148 (9 / 10) | 10-15..10-28, season over |
  | NCAAB | 87 (11 / 73), game lines only | 0 | 11-02..11-12 |

- **Featured bets:** `<sport>/<date>.postmortem.jsonl` on the fleet holds every graded featured bet, one line per card per
  day, 5,445 lines. It agrees with `record.json` section by section (Value 871, Skater vs goalie 564, Consistency 1,586 in
  both).
- **Population:** every row of each day's final sheet build (`<sport>/<date>.json` `rows`: the built pool, every rung, both
  sides), graded from `<date>.reconciled.json` `props` by `cheat_sheets.prop_result_key`. That gives 20,564 rows.
- **Excess** = y - `check.p_market`, the publish fair the sheet itself shows. **ROI** is 1 u at `check.price`, the sheet's
  best book.
- **Matched control:** for each member, the mean outcome of NON-members in the same sport x side x price band x
  fair-method stratum (primary, featurable rows), with 10+ controls required.
- **Intervals:** 95% from 2,000 bootstrap resamples over games (`event_id`). Same-game props are correlated, and the
  naive z-scores in the working files overstate significance.
- Scripts and outputs: `C:\tmp\edge-analyses\cheat-sheet-sections\2026-11-13\` (`extract_population.py` runs on the
  fleet with `~/.venvs/syndicate` from `~/Syndicate`; `bootstrap.txt` holds the interval table below).

## 1. Existing sections, per sport (featured bets, ROI and excess over the fair, 95% CI by game)

| section | bets / games | ROI | excess over fair (pts) | verdict |
|---|---|---|---|---|
| **Matchups, NBA + WNBA** (vs-opponent clause) | 253 / 50 | **+19.7% [+9.0, +30.8]** | **+10.4 [+4.6, +16.1]** | the one section that beats the price beyond noise |
| Matchups, NFL (DvP clause) | 159 / 41 | -9.6% [-24.5, +5.3] | -4.1 [-11.7, +4.2] | no value; its OVERS 65 bets -32.8%, -17 pts |
| Matchups, NHL (vs-opponent) | 379 / 147 | -1.4% [-10.2, +7.2] | -0.3 [-5.4, +4.5] | no value |
| Consistency, all | 1,586 / 483 | +2.0% [-2.5, +6.5] | +1.8 [-0.7, +4.2] | positive, within noise; vs matched controls +2.5 pts (z ~2.0 naive) |
| Consistency, NHL | 322 / 140 | +7.8% [-2.0, +17.1] | +3.8 [-1.9, +9.4] | best single cell; `findings_2026-11-09` read +3.5% on the 10-23..11-08 slice |
| Hot streaks, all | 1,346 / 417 | +2.8% [-2.2, +7.9] | +2.4 [-0.3, +5.0] | positive, within noise; NCAAF +7.9%, NFL +5.7%, NBA/MLB ~0 |
| **Value at the best price** | 871 / 352 | -5.2% [-12.3, +1.9] | **-4.0 [-7.4, -0.5]** | its bets hit BELOW the fair that makes them "value" |
| Skater vs goalie (NHL) | 564 / 178 | -7.0% [-14.9, +0.5] | -3.8 [-8.0, +0.2] | no value; largest player-vs-player section |
| Defenders on his targets (NFL) | 128 / 43 | -9.9% [-27.1, +6.0] | -4.9 [-14.1, +3.2] | no value |
| Defender matchups (NBA) | 170 / 54 | -3.0% [-15.9, +11.2] | -2.0 [-8.5, +4.7] | no value |
| QB vs this secondary (NFL) | 105 / 58 | +5.0% [-10.7, +21.7] | +3.5 [-5.4, +11.8] | unresolved |
| Batter vs pitcher / Pitcher vs lineup (MLB) | 70 / 14 bets | +0.9% / 3-11 | -1.0 / - | unresolved; season over |
| Goalie vs this team (NHL) | 1 bet in 29 days | - | - | no volume |
| **Hot form, one-sided** (soccer) | 42 / 35 | **-36.1% [-57.2, -14.9]** | **-13.1 [-24.8, -1.8]** | loses beyond noise |
| **Picks + price plays priced above +250** | 124 / 120 | **-42.1% [-72.0, -3.4]** | -4.9 [-10.0, +1.1] | soccer / NCAAB moneyline longshots; picks at <= +250 are +0.1% on 1,317 |

## 2. Why: the mechanisms

**The fair leans OVER in NBA and NFL props** (all graded two-sided rows):

| | rows / games | ROI at best price | excess over fair |
|---|---|---|---|
| NBA overs | 3,227 / 173 | -7.5% [-13.0, -2.0] | -3.9 [-6.3, -1.5] |
| NBA unders | 2,823 / 174 | +6.1% [+0.8, +11.4] | +3.1 [+0.3, +5.7] |
| NFL overs | 2,342 / 58 | -7.9% [-14.7, -1.5] | -2.3 [-5.7, +1.2] |
| NFL unders | 2,478 / 58 | +1.3% [-5.3, +7.9] | +3.0 [-0.2, +6.4] |

MLB, NHL, NCAAF and WNBA show no side bias beyond noise. This is the board's quote fair
(`layer2_board._resolve_fair`), not something the sheet computes.

**"Best price beats the fair" is adverse selection.** Two-sided rows whose best price claims EV +2..+5% hit 3.1 pts
BELOW the fair [-5.3, -0.8] (1,791 rows / 385 games). Rows claiming EV below -5% hit +2.0 pts ABOVE it. Where Bovada
supplies the EV >= 2 price, the rows hit -4.2 pts [-8.3, -0.5] (913 / 212). An off-consensus price is usually the book
that knows, or the book that is stale. Value's "beats the close" (ev_close +2.8%, 86% beat) is measured against the SAME
consensus fair, so it is circular: the outcome does not confirm it. `primary_lines` also picks a group's side by this
EV, so every featured section inherits a mild version of the bias.

**One-sided fairs are overstated.** Rows whose fair assumes a hold (`book_margin_model` / `one_sided` /
`assumed_hold`) hit 3.9 pts below it [-5.0, -2.7] and return -38.7% ROI (3,556 rows / 343 games). That fits the
2026-09-21 measurement of 8.5 pts. Hot form, one-sided is built on exactly these rows.

**Player-vs-player sections never use their history to pick a side.** `sections()` admits a row when a history EXISTS
(2+ meetings, 40+ possessions, 2+ plays) and sorts by sample size. The side is whichever `primary_lines` chose by EV.
Where there is volume to test whether the history is directional, it is not: NHL SOG per game vs today's goalie, minus
the line, toward the side, gives -2.1 / -3.3 / +3.3 / -1.6 pts across four bins (387 rows), with no trend.

**The vs-opponent record is directional in basketball and nowhere else.** On the same line, 3+ meetings, >= 80% toward
the side: NBA +21.9 pts (61 rows). NHL and NFL are flat. NBA and WNBA have no defense-rank data, so their Matchups section
is the vs-opponent clause alone, and that is why it wins there and not in NFL (DvP clause) or NHL.

## 3. Evidence that predicts beyond the price: candidate new sections

**SmartSim projection vs the MAIN line, side = the sim's side, edge >= 5% of the line** (featurable, two-sided):

| sport | rows / games | ROI [95% by game] | excess | first half / second half ROI | rows/day |
|---|---|---|---|---|---|
| **NBA** | 1,251 / 122 | **+8.0% [+2.1, +14.0]** | +4.0 [+1.0, +7.0] | +7.8% / +8.2% | 54 |
| **WNBA** | 318 / 7 | +15.4% [+4.6, +23.6] | +9.3 [+3.6, +14.2] | +13.0% / +21.1% | 45 |
| NCAAF | 863 / 163 | +2.9% [-3.0, +9.1] | +4.3 [+1.1, +7.4] | +4.2% / +1.8% | 43 |
| NHL | 755 / 174 | +0.5% [-5.5, +6.6] | +0.9 | +1.0% / +0.2% | 27 |
| NFL | 924 / 57 | -5.7% [-11.1, +0.3] | -1.3 | -4.5% / -6.6% | 77 |
| MLB | 366 / 8 | +1.2% [-9.3, +12.1] | +1.5 | - | 46 |

- NBA + WNBA pooled: +9.5% [+4.1, +14.5] on 1,569 rows / 129 games. Thresholds of 3% and 10% give the same picture
  (NBA +5.8% / +8.2%), so 5% is not a tuned cliff.
- NBA's edge sits in the UNDERS (+14.5%, z 3.9 naive, 630) against overs +1.5% (621). That fits the over-leaning fair.
  By market, threes, assists, PRA and R+A carry it; points and P+R are flat.
- 755 of the 1,251 NBA rows sit in NO existing featured section. This is new content, not a re-sort.
- The board's blended `p_model` barely moves off the market in NBA props (3,719 of 4,375 rows within 3 pts). The RAW
  `projected` carries the signal.
- Leakage check: `build_cheat_sheets.py:190` takes `game_state == pregame` rows only, and a started game keeps its
  last pregame rows (`merge_record`). So the projection and the price are both pregame.

**Value with the sim's agreement** (EV >= 2 and sim edge >= 5% toward the side): NBA +11.9% on 225 (z 1.75 naive),
against Value alone -2.0%. In NHL it is -9.0% on 105.

**Form on the exact line:** L10 >= 80% shows NBA +4.7 pts and NCAAF +9.7 pts in the population. At section scale
(primary rows) it is within noise. The existing Consistency rule (>= 70%) already captures it, so no new section is
needed.

## 4. What is NOT shown

- 29 days. NBA has 122-180 games and is the only sport with enough data for a sport-level verdict on a new rule. WNBA
  rests on 7 games, MLB on 10, and both seasons are over: their numbers are readings for 2027.
- Many rules were tested. Only results whose game-clustered interval excludes 0 are called real above: basketball
  matchups, NBA sim edge, the NBA over/under fair lean, Value's sub-fair hit rate, one-sided fairs, Hot form, and picks
  above +250.
- The population is the BUILT POOL (`groups_built`), not the whole board. For NHL that is about 47 of about 852 groups
  per day, so a matched control is "a pool row the section did not feature", not "any prop".
- Closing prices were not used as the outcome. For Value they are circular, as shown in section 2.

## 5. Proposals (a person decides; the 2026-10-05 prime directive applies)

The prime directive forbids any rule that removes a row, pick or stake because of its MARKET, market family, or a
(sport, market) model verdict. A gate must be a property of the LINE. Every row stays on "Every prop on the board"
whatever a featured section does.

1. **Picks on the sheet: apply the featured price band (-250..+250)** that every other featured section has used since
   the user's 10-15 "sanity cap" decision. This gates on price, a line property. Evidence: -42.1% [-72.0, -3.4] on 124.
2. **Retire "Hot form, one-sided"** as a featured section: -36.1% [-57.2, -14.9]. Its premise, form where no fair exists,
   rests on rows measured at -38.7% ROI.
3. **New section "Sim vs the line"**: the main line, the side SmartSim projects, edge >= 5%, ordered by edge, top 25,
   with the sport's measured record printed in its header (label, never hide).
4. **Value at the best price: stop calling it value.** Either require the sim to agree (it then folds into 3), or show it
   as best-price information only.
5. **Player-vs-player sections:** keep each history as an evidence line on every row (`pvp_point` already does this).
   EITHER retire them as featured bet sections OR admit a row only when its own history points to the side, on
   probation under the review.
6. **Matchups:** in sports where a row has a same-line vs-opponent record, admit on that record. The DvP-rank-only
   clause is the one that loses (NFL overs -32.8%).
7. **Daily review:** add excess-over-fair and matched-control lift per section beside W-L, with game-clustered CIs.
   Today a section can be flagged "winning" on noise, and Value reads healthy because its close is measured against the
   same fair it is selected on.
8. **For the fair owners, not this lane:** NBA and NFL prop fairs lean OVER by 2-4 pts, and Bovada's off-consensus
   prices are a trap. Route this to the fair lanes (`fair-price-v2` / `syndicate-fair-v1`).

## 6. Follow-up 11-13: rank NHL "Sim vs the line" by the model's chance instead of the gap? NO

Asked by the user ("Measure it") after reading the 11-13 NHL picks. The section's gap is (projection - line) /
max(line, 1). On a 0.5 line the projection is a MEAN, and a mean above 0.5 does not make the over likelier (Poisson: only
above 0.693). Two of that day's 19 picks had the model's own chance well under the fair: Forsberg Over 0.5 points
(51.2 vs 60.1) and Stamkos Under 0.5 goals (64.2 vs 69.7). Hypothesis: ranking by chance minus fair beats the gap in NHL.

- NHL `check.p_model` IS Poisson(`projected`) for the row's side: 1,937 of 1,939 replay rows within 0.2 pts (MLB: 9%).
- Replay with the section 3 population and filters (official 10-15..11-12, main line, featurable, two-sided; ROI at
  the best price; excess = y - fair; 95% CI by game, 2,000 resamples):

| NHL rule | bets / games | hit vs fair | ROI | excess (pts) |
|---|---|---|---|---|
| shipped: gap >= 5% | 755 / 174 | 59.7 vs 58.8 | +0.5% [-5.6, +6.4] | +0.9 [-2.6, +4.6] |
| gap >= 5% AND chance >= fair | 545 / 163 | 59.4 vs 58.8 | +0.3% [-7.0, +7.5] | +0.7 [-3.7, +4.9] |
| what that filter drops (chance < fair) | 210 / 112 | 60.5 vs 58.9 | +1.2% [-9.9, +12.5] | +1.5 [-5.5, +8.2] |
| chance - fair > 0, either side | 904 / 186 | 54.4 vs 54.6 | -1.4% [-7.7, +4.8] | -0.2 [-3.5, +3.1] |
| chance - fair > 5 pts | 467 / 160 | 52.9 vs 54.3 | -4.9% [-13.1, +3.9] | -1.4 [-6.1, +3.2] |
| chance - fair > 10 pts | 172 / 104 | 53.5 vs 53.0 | -1.8% [-15.3, +12.1] | +0.5 [-6.5, +7.6] |
| gap rule, 0.5 lines | 487 / 158 | 63.2 vs 61.2 | +3.2% [-4.3, +10.5] | +2.1 [-2.4, +6.6] |
| gap rule, lines >= 1 (mostly SOG) | 268 / 124 | 53.4 vs 54.5 | -4.3% [-14.4, +5.2] | -1.2 [-6.4, +3.9] |

- Weight the outcomes put on the model beyond the fair (fit w in logit p = logit fair + w * (logit p_model - logit
  fair), one row per main-line group, CI by game): NHL w = +0.28 [-0.14, +0.69], although the model and the fair sit 5+
  pts apart on 52% of groups. The NHL model's disagreements with the price are mostly noise.
- The same chance filter on the shipped rule, other sports: NCAAF, the rows it would DROP did better, excess +8.1
  [+0.8, +15.0] (167) vs kept +3.4 [-0.6, +7.3] (696). NBA kept +6.1 [+2.4, +9.8] (492) vs dropped +2.7 [-1.2, +7.1]
  (759), within noise of each other. NFL kept -0.5 vs dropped -5.9 (137), within noise. MLB (8 games) and WNBA (7 games)
  are readings only.
- For the model owners, not this lane: NBA `p_model` is the market blend (only 3% of groups 5+ pts from the fair), and
  its w = +2.50 [+0.93, +4.01] says the blend shrinks the model toward the market too hard.

**Verdict: no change.** Neither the gap nor the model's chance beats the price in NHL. The 0.5-line rows the hypothesis
blamed are the better half, within noise. In NCAAF a chance filter would have cut the better rows. The mean-vs-chance
mismatch on 0.5 lines is real arithmetic but costs nothing measurable, because the NHL chance carries little beyond the
fair. The NHL header keeps printing that the section has not beaten the price. About 40 cells were read; the few
intervals that exclude 0 (e.g. NHL SOG rows the filter drops, -24.3% on 50, one of 15 market cells) are treated as noise.
Scripts and outputs: `C:\tmp\edge-analyses\nhl-sim-chance\` (`replay.py`, `sports.py`, `replay_nhl.txt`, `sports.txt`).
