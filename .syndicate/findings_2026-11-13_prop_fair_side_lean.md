# The board's prop fair leans OVER in NBA -- measured, mechanism, and a correction (2026-11-13)

Lane `prop-fair-side-lean` (session 35bdf3a7). Started from the cheat-sheet section assessment
(`findings_2026-11-13_cheat_sheet_section_assessment.md` §2). Hypotheses were registered in the lane BEFORE the
quote-level run (`916605f1e`).

**Verdict:**
- **Real, NBA only.** Overs hit 3.5 pts below the board's fair (−3.48 [−4.82, −1.95], 174 games). It reproduces out
  of sample.
- **The cause is not a de-vig or pricing artifact.** The market, Pinnacle included, has set NBA scoring lines too high
  this season. It holds at the close and on game totals too.
- **A side shift removes the lean,** but it missed its registered held-out bar (log-loss CI includes 0).
- **Not proposed for the fleet yet.** It is frozen for a forward read.

## 1. The lean, on the board's own graded population

**Population:**
- **Source:** the suggested-grade pulls. They grade `score_ranking_backtest` rows through a local reader, over every
  opportunity-lane record, taking the earliest sighting per identity and phase. Files: `out_1017_1101`, `out_1023_1108`
  under `C:\tmp\edge-analyses\suggested-grade`, plus `out_1108_1112` (graded today) under
  `C:\tmp\edge-analyses\prop-fair-lean`.
- **Rows kept:** pregame rows with a two-sided `consensus` fair (Shin since 10-13) and y in {0, 1}.
- **Framing:** one row per (game, market, player, line), framed on the OVER, so an over and its under count once.
- **Lean** = mean(y_over − fair_over) in points. The 95% interval is a bootstrap over GAMES.

| sport | groups / games (10-17..11-12) | lean |
|---|---|---|
| NBA | 67,830 / 174 | **−3.48 [−4.82, −1.95]** |
| NFL | 18,142 / 57 | −1.53 [−5.10, +3.32] |
| NHL (10-17..11-08) | 12,132 / 162 | +0.18 [−1.29, +1.44] |
| NCAAF (10-17..11-08) | 9,675 / 158 | −0.47 [−3.06, +2.12] |

MLB (8 games) and WNBA (7) are too thin to read. NFL is not separable from 0, so there is nothing to correct there.

**NBA is broad, not a corner** (over rows, 10-17..11-08):
- **Every market:** points −3.6, PRA −4.3, P+R −4.0, P+A −3.9, R+A −2.7, assists −2.6, threes −3.0, rebounds −1.4
  [−3.2, +0.6].
- **Every fair level:** fp 0.20-0.35 −2.5, 0.35-0.45 −2.6, 0.45-0.50 −4.0, 0.50-0.55 −2.8, 0.55-0.65 −4.0,
  0.65-0.80 −4.2.
- **Every pricing book:** Bovada −3.6, FanDuel −2.9, DraftKings −3.5, BetRivers −3.7, BetMGM −3.7.
- **Every week, with no decay:** week of 10-19 −3.0, 10-26 −4.0, 11-02 −3.0, and 11-09..11-12 −4.0 [−7.2, −0.8].
- **Fresh quotes too:** book age under 1 h carries 54,671 of 56,428 rows, at −3.35.

## 2. Mechanism: rebuilt from the raw book quotes

`scripts/prop_fair_side_lean.py extract` rebuilt each graded group's fair from `book_quotes`, using `fair_price_eval`'s
windows and PRODUCTION `opportunity_signals.devig`:
- NBA 54,063 of 56,804 groups; NFL 17,214; NHL 12,132.
- **The rebuild matches the board exactly:** the median |Shin rebuilt − board fp| is 0.0 pts, with the same lean (−3.23).

| NBA (54,063 groups / 146 games) | at sighting | at the close (46,758 / 141) |
|---|---|---|
| multiplicative | −3.20 [−4.91, −1.54] | −2.59 [−4.19, −0.82] |
| power | −3.26 [−4.97, −1.60] | −2.62 [−4.23, −0.85] |
| Shin (the board) | −3.23 [−4.95, −1.58] | −2.61 [−4.21, −0.84] |
| under's price at face | +0.13 [−1.58, +1.79] | +0.75 [−0.86, +2.52] |
| over's price at face | −6.60 [−8.32, −4.95] | −5.97 [−7.58, −4.20] |

The registered hypotheses:

- **H-A (de-vig method): NOT the cause.** The three methods agree within 0.06 pts (falsification bar 1 pt). At prices
  near evens every de-vig returns the same number, so no choice of de-vig can move this lean.
- **H-C (book mix): FALSIFIED.**
  - Pinnacle's own two-sided fair leans −4.62 [−7.74, −1.73] (668 groups / 44 games), the same as the consensus on
    those rows (−4.68).
  - The book count does not matter either: 1 book −3.56, 2 books −1.75, 3-4 books −3.37, 5+ books −2.69.
- **H-D (margin loaded on the over): FALSIFIED as registered.**
  - The lean SHRINKS as the hold grows: slope +250 pts per unit of hold [+81, +392]. Hold 5-7% gives −3.42; hold 7-9%
    gives −1.00.
  - It is present whichever side carries the juice: over juiced −3.50, even −4.39, under juiced −2.78.
  - The "under's price at face" fair cancels it only because NBA prop holds cluster at 5-7%, so hold/2 ≈ the lean.
  - That fair is badly wrong in NHL (+3.68 [+2.20, +4.93]) and is not a general fix.
- **H-E (the line itself is too high): SUPPORTED.** The lean holds at the close (−2.61, CI excludes 0), at the sharp
  book, in every market and at every fair level.
- **The same thing shows on NBA game totals,** a sharp market that public over-betting does not explain:
  - quarter and half totals: overs −4.91 [−9.26, −0.62] (3,197 / 146 games);
  - full-game totals: −5.92 [−13.86, +1.58] (1,135 / 144);
  - the NBA sim-lean read of 10-20..11-01 (`lean_1017_1101.txt`) had games going under 52, over 40.
- **NFL game totals show nothing:** full +5.1, segments −3.5, both noise.

**Reading:** so far this season NBA scoring has come in below what the whole market, props and totals and the close,
priced in. That is a level error in the lines, not a pricing quirk of the props. It may fade as books adapt. Through
11-12 it has not: the latest four days read −4.0.

## 3. The correction, and the held-out check

`syndicate/features/shared/prop_fair_side.py`, a pure module:
- **The shift:** `logit(p_over') = logit(p_over) + delta`, with the under as its complement.
- **The fit:** `delta` is the ML intercept with the fair as an offset.
- **Shrinkage:** toward 0 under a N(0, 0.10²) prior, after inflating the se by the measured design effect (NBA 15-17:
  props of one game move together).
- **Tests:** off is the identity; on moves the over down and the under up, and they stay a fair pair.

**Registered bar:** fitted on kickoffs before 11-02, the shift must cut log loss on 11-02..11-12 with a game-clustered
CI below 0 in NBA.

```
python scripts/prop_fair_side_lean.py holdout --graded <props pulls> --sports nba,nfl --fit 2026-10-01..2026-11-01 --test 2026-11-02..2026-11-12
```

| sport | delta (fit to 11-01) | test groups / games | lean before → after | dLL [95% by game] | bar |
|---|---|---|---|---|---|
| NBA | −0.150 | 31,908 / 82 | −3.38 [−5.34, −1.21] → +0.19 | −0.00239 [−0.00534, +0.00086] | **MISSED** |
| NFL | −0.065 | 6,105 / 17 | −1.45 → +0.11 | −0.00043 [−0.00579, +0.00478] | missed |

A second read on the cheat sheets' graded rows (11-02..11-12, NBA 1,988 groups / 82 games) gives the same picture:
- the lean: −3.98 [−7.22, −0.41];
- dLL −0.00324 [−0.00811, +0.00213].

**Why it misses although the lean reproduces:** with delta fixed, the log-loss gain is about
−delta × lean − ½delta²·p(1−p). The gain clears 0 only when the held-out lean is beyond about −1.9 pts with
confidence, which is a stricter bar than "lean ≠ 0". On 82 games the lean's interval reaches −1.21.

**Fit on everything (10-17..11-12):**
- NBA delta = −0.146, clustered se 0.031, shrunk −0.134. That is ~3.6 pts at evens.
- By market: points −0.143, PRA −0.184, P+R −0.183, P+A −0.158, R+A −0.138, assists −0.116, rebounds −0.084,
  threes −0.075.
- NFL −0.063 ± 0.089, which is nothing.

## 4. What it would change on the board (NBA, 10-17..11-08, both sides, realised ROI at the board's best price)

| set | rows / games | realised ROI |
|---|---|---|
| EV ≥ 2 today | 1,181 / 117 | +7.0% [+1.2, +11.9] |
| … of which overs | 611 / 98 | −0.8% [−15.0, +12.3] |
| … of which unders | 570 / 89 | +15.4% [+4.0, +25.6] |
| overs that would LEAVE EV ≥ 2 | 391 / 98 | −6.8% [−21.1, +7.3] |
| unders that would JOIN EV ≥ 2 | 7,090 / 146 | +2.9% [−1.0, +6.5] |
| EV ≥ 2 corrected | 7,880 / 146 | +4.0% [+0.4, +7.8] |

The shift moves every NBA over's EV about −7.0 points and every under's about +7.3. The EV ≥ 2 set would grow about
6.7×, almost all of it unders, and would claim far more EV than those unders realised.

**Where it would be wired:** the board's fair, `layer2_board.build_layer2_rows` right after `_resolve_fair`. That
function sits next to lane `fair-price-v2`'s claimed section. No order path was found that prices player props from
this fair: a grep of `execution_guard` / `*_orders.py` for prop / player found nothing. The effect would be on the
board's EV, rank, Suggested picks and the cheat sheets' EV.

## 5. Proposal and decision

**DECISION 2026-11-13 (user, in chat): "Forward read first".** Nothing is wired. The NBA shift is frozen at −0.146 and is read on kickoffs 11-13..11-26 on or after 11-27:

```
nice -n 19 ~/.venvs/syndicate/bin/python scripts/prop_fair_side_lean.py pull --data-root ~/syndicate-prod/data --start 2026-11-12 --end 2026-11-26 --sports nba,nfl --out <dir>/props_1112_1126.jsonl.gz
python3 scripts/prop_fair_side_lean.py holdout --graded <dir>/props_1112_1126.jsonl.gz --sports nba --delta -0.146 --test 2026-11-13..2026-11-26
```

The `pull` reproduces the weekly suggested-grade pull exactly: NBA props for 11-12, 8,200 of 8,200 rows with the same outcome, fair and sighting time. A one-time scheduled task (`prop-fair-forward-read`, 9:00 AM CST 11-27) runs it.

The options as they were put:

1. **Recommended: a forward read, with no fleet change.** The corrected fair is a pure function of the recorded `fp`,
   so it can be scored offline from any later pull.
   - **Frozen now:** NBA delta = −0.146 (fit 10-17..11-12).
   - **Read:** kickoffs 11-13..11-26, from a pull taken on or after 11-27:
     `holdout --delta -0.146 --test 2026-11-13..2026-11-26`.
   - **Same bar:** dLL CI below 0.
   - **If it passes:** shadow-stamp it on the board (coordinated with `fair-price-v2`), then flip.
2. **Alternative:** wire a shadow stamp now (`quote.fair_side_adjusted` on NBA prop rows) so the board shows both.
   That needs `fair-price-v2`'s owner and a worker restart, and it measures nothing the offline read cannot.
3. **Either way:**
   - Because the mechanism is a season-level line error, a fixed constant is the wrong long-run shape. If adopted,
     delta should be a trailing-window estimate, re-fit weekly and shrunk, the way the daily optimizer refits its
     calibration.
   - It is NBA only; NFL, NHL and NCAAF get no shift.

Scratch (not in git): `C:\tmp\edge-analyses\prop-fair-lean` holds `props_all.jsonl.gz` (535,238 graded prop rows),
`quotes_rows.jsonl.gz` (83,409 rebuilt groups), `mechanism.json`, `impact.py`, `totals_lean.py` and `drift.py`.
