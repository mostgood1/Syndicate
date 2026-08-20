# learnings.md — entries consolidated 2026-08-20

Moved VERBATIM from `learnings.md` by lane `football-model-owner`, which WROTE
all five, when the file stood at 184KB against a 117KB cap and therefore
arrived LOSSY at every session start.

They are five descriptions of ONE error — validating against a proxy, the wrong
unit, or the wrong metric instead of the objective — and they replaced each
other's shelf space rather than reinforcing. `learnings.md` now carries a single
consolidated entry citing every measurement below. Nothing was summarised away;
the full originals are here.

ONLY THIS LANE'S OWN ENTRIES WERE TOUCHED. Compressing another lane's prose is
that lane's call — the same rule `state_archive_2026-08-19.md` states.

---

## 2026-08-19 — OVERTURNED: a model matching the market's DISPERSION is not a model that can BEAT it

**Applies to every sport lane in this repo, not just NCAAF.** Several are
currently tuning models by comparing spread-of-predictions against
spread-of-market, and that is the belief this overturns.

**What was believed.** Earlier the same day I moved NCAAF margins from SD 1.74
to 15.37 against a market SD of 14.46 — ratio 1.06 — and reported it as the
margin model being fixed. It was a real improvement: the previous state priced
every college game as a coin flip. But "fixed" was the wrong word and the
language implied something never tested.

**What is true.** Dispersion is a PROXY. A model can spread its predictions
exactly like the market's and still put them in the wrong places. Measured
against realised results:

    full 2025 season, 2,530 rows / 888 games / 3 books
      vs CLOSING line  n=2235  model MAE 15.294  market 11.876  +3.419  t=+16.33
      vs OPENING line  n=2175  model MAE 15.231  market 11.872  +3.358  t=+16.08

The model was *calibrated* and *not competitive*, and only the first had ever
been measured. It also loses to all three books individually, so it is not an
artefact of one sharp book.

**The same error was sitting one layer down**, which is what makes this a class
rather than an incident: `SP_RATING_SCALE=10` had been chosen because it made
dispersion match. Scored for ACCURACY the optimum is ~13 — but paired, that is
dMAE −0.168, SE 0.225, **t=−0.74, not significant**, so the constant stayed. Two
numbers chosen against a proxy, one real problem underneath both.

**Also overturned, and it is a widely-held betting belief:** "beat the OPENING
line first, it is softer." The open here is **0.06 MAE softer than the close**
and the model loses to both by ~3.4. There is no easier target hiding behind the
close; this is an accuracy problem, not a timing one. Worth one query, and now
answered — do not re-derive it.

**The rule going forward.** Before reporting any model quantity as fixed,
improved, or good, name the thing it was scored AGAINST. If the answer is
another model quantity (dispersion, calibration, a residual correlation, an
internal consistency check) rather than a REALISED OUTCOME, say so in the same
sentence. Proxy agreement and accuracy are different claims and the first is
routinely mistaken for the second — four times in one session here.

**Cost:** a "margins fixed" claim carried for hours; NCAAF picks served live in
production for that whole window on a model measured, once anyone looked, to
lose to the closing line at 16 sigma. Fixed by a default-DENY serving gate
(`syndicate/features/football/pick_gate.py`) plus the Stage 0 ledger
(`pick_ledger.py`) that makes the accuracy question answerable at all.



## 2026-08-19 — a 5.8σ result against a PROXY did not transfer to the objective

**The strongest-evidenced model input I tested all session failed, and the prior
that recommended it was not weak — it was rigorous and it was measured against
the wrong thing.**

Returning production for NCAAF. Two independent checks passed before anything
was built: it is NOT already inside preseason SP+ (r=+0.035, incremental R²
+0.000, with recruiting at +0.482 through the identical residual as a POSITIVE
CONTROL proving the probe could detect an ingredient), and it DOES predict
year-over-year SP+ movement — pooled **r=+0.207, n=786, ~5.8σ, positive in all
six seasons independently.**

Wired through the strong lever (ratings, 17.2% of margin SD, not the 4.1%
payload). Reachability passed: 50 of 51 margins moved.

Then the objective test, paired, leak-free, identical games and seeds:

    2024   n=749   dMAE -0.149  t=-1.58
    2025   n=758   dMAE +0.023  t=+0.22   <- OPPOSITE SIGN
    pooled n=1507  dMAE -0.062  t=-0.89   NOT SIGNIFICANT

**The chain had two links and only the first held:**

    returning production -> SP+ MOVEMENT      HELD, 5.8 sigma
    SP+ movement -> MARGIN ACCURACY           FAILED

**What makes this worth its own entry.** The session already records "calibrated
is not competitive" — matching market dispersion said nothing about accuracy.
This is the same failure with a much better disguise: the proxy relationship was
not a hand-wave, it was multi-season, positive-controlled and 5.8 sigma.
**Rigour in validating a proxy does not convert it into the target.** A proxy
measured to ten decimal places is still a proxy.

**And the 2024 arm nearly sold it.** At t=-1.58 with the right sign and a strong
prior, the temptation to ship was real and I nearly framed it as
"under-powered, needs more data" indefinitely. One more independent season cost
~100 minutes and flipped the sign. **A single-season backtest with a favourable
prior is the most dangerous kind of result**, because prior plus direction feels
like corroboration when it is one sample.

**The rule going forward.** Before building an input on the strength of a
correlation, ask what that correlation was measured AGAINST. If it is anything
other than the quantity the model is judged on, the measurement is a reason to
RUN the objective test, never a substitute for it. And require a second
independent sample before shipping anything whose first sample is under |t|=2 —
the second sample is where noise separates from signal.

**Cost:** ~3 hours of compute and one near-miss. Cheap, and only because the
objective test was run before shipping rather than after.


## 2026-08-20 — MAE IS NOT PLAYABILITY. The model loses to a mindless side bet.

**I spent most of a session measuring the wrong quantity.** Every NCAAF and NFL
verdict up to this point graded **MAE** — how close the projected margin lands.
That is an ENGINE diagnostic. It is not a betting decision, and the two can
disagree: a model can carry worse MAE and still be playable if its
DISAGREEMENTS with the market are directionally right.

The user asked to "serve the ones that show playable". Testing that properly —
ATS, against the **52.4% breakeven at −110**, not 50% — produced a harder answer
than any MAE result had:

    NCAAF 2024, clean out-of-sample, 751 games
        |edge| >= 0    46.8% ATS      |edge| >= 10   45.2% ATS
    Filtering HARDER makes it WORSE. There is no threshold where a playable
    subset appears; the "only serve strong picks" instinct fails in the
    direction opposite to the one that would help.

**THE TEST THAT MATTERED, and it nearly went unrun.** An under-dispersed model
always says "closer than the market thinks", so it always fades the favourite —
making its apparent edge indistinguishable from a blind underdog bet unless you
check. NFL preseason had just read 54.7% ATS and looked positive:

                           always bet the dog   the model   model adds
        NFL preseason            58.9%            54.7%      -4.2 pts
        NCAAF 2024               51.2%            46.8%      -4.4 pts

**The model is WORSE THAN IGNORING IT.** The NFL "edge" was riding a dog fade
and DEGRADING it. Two sports, two models, two sample sizes, near-identical
subtraction — wherever the model's opinion is strong enough to deviate from the
naive side, it is wrong more often than not.

**The generalisable rule: always benchmark a model against the dumbest strategy
that produces the same BETS**, not just against the market. "Beats the close"
and "beats always-bet-X" are different bars, and a systematically biased model
clears neither while appearing to clear the first on a favourable sample. The
`dog%` column is the tell: 92–100% means the threshold is selecting a SIDE, not
a signal.

**Also recorded:** per-book rows overstated significance **3.4x** on the NFL
grade (t=+4.00 → +0.87 once collapsed to one row per game), because the same
game repeats across 14 books. Store per-provider — price shopping is worth +2.79
ROI points — but ANALYSE per game.

**Acted on, not just noted:** `pick_gate.LIFT_CONDITION` now requires beating the
naive baseline, a CI lower bound above 52.4%, out-of-sample pre-specified
subsets, and denominators in bets. `scripts/grade_football_playability.py`
measures it, and `LiftConditionTests` pins it so it cannot be quietly weakened.



## 2026-08-20 — TEST THE MARKET'S ERROR BEFORE BUILDING A FEATURE. Two minutes vs hours.

**The question is never "does X affect the game". It is "does the MARKET
MISPRICE X".** Those are different claims and only the second is worth building.

Asked to wire situational factors into NCAAF (rest, travel, altitude, timezone,
neutral site, dome, kick time, conference), I regressed the MARKET'S OWN ERROR on
each one FIRST, on 1,746 games:

    market_residual = realised_margin - market_margin

    rest_diff -0.64   travel_km +1.57   elev_gain +0.93   tz_shift -0.90
    neutral   -0.56   is_dome   +0.88   conference -1.32  kick_hour -1.82

**Not one reaches |t|=2.** The market prices all of it. Building those eight
features would have re-derived information already in the line — landing in the
model's SHARED variance, not the missing part — which is exactly how the
returning-production feature failed after a 5.8-sigma prior.

**Cost: two minutes.** The returning-production equivalent cost a build, two
full-season backtests, a revert and ~3 hours of compute to reach the same kind
of answer. The ordering is the entire lesson.

**THE POSITIVE CONTROL IS NOT OPTIONAL, and it nearly went unrun again.** Eight
nulls in a row should immediately raise "can this test detect anything?" The
residual's own mean answers it: **+0.983, SE 0.365, t=+2.70** — the market really
does under-price home teams, so the instrument works and the nulls are real
absences. Without that line the whole table would have been worthless, the same
way recruiting at +0.482 was what made the SP+/returning-production null usable.

**A statistically real bias is still not automatically playable.** That same home
bias: 1,713 bets, **51.4% ATS, CI [49.0%, 53.7%]** against a 52.4% breakeven.
Significant in the regression and unbettable in practice, because +0.98 points on
a 15.2-point residual SD moves the cover rate ~2.6 points — onto the vig.
"Significant" and "profitable" are different tests and the second is stricter.

**The standing practice.** For any proposed model input, in this order:
1. Regress the market residual on it. Null -> STOP, do not build.
2. Include a positive control in the same table, or the null proves nothing.
3. If it survives, check it is PLAYABLE (ATS vs breakeven), not merely
   significant.
4. Only then build, with a reachability test.

`scripts/test_ncaaf_situational_edge.py` is the reusable harness.

---


## 2026-08-20 — a regression slope IMPLIES an edge; only the ATS test DEMONSTRATES one. They disagree.

Testing whether the NFL market misprices injuries, the weighted burden measure
came back at **t=−1.81 with the intuitive sign**. Extrapolating that slope:
0.508 points per unit × a burden SD of 2.63 = **1.34 points**, which converts to
roughly **53.5% ATS** — above the 52.4% breakeven. A tidy, plausible,
build-worthy result.

**Then I bet it.** Same games, betting the less-injured side:

    |weighted_diff| >= 1 : 189 bets   54.5% ATS  CI [47.4, 61.4]
    |weighted_diff| >= 2 : 118 bets   50.0% ATS  CI [41.1, 58.9]
    |weighted_diff| >= 4 :  36 bets   58.3% ATS  CI [42.2, 72.9]

Every CI spans 52.4%, and the sequence is **NON-MONOTONIC**. A real effect
strengthens as the edge filter tightens; this wanders. The implied 53.5% never
materialised because it came from extrapolating a slope that was not significant
in the first place.

**Why a slope can lie about betting.** A regression fits the WHOLE distribution
and is dominated by the many small-differential games; a bet is placed only on
the tail. Fitting the middle and extrapolating to the tail assumes a linearity
nobody checked. And converting "points of edge" to "ATS%" via a rule of thumb
compounds it.

**MY OWN OUTPUT INVITED THE ERROR.** The first version of the harness printed
`-> COULD clear it IF real` from the slope alone. That is a conditional that
reads as encouragement, and I wrote it. A tool that reports the flattering
half of an analysis will eventually persuade its author. The ATS table is now
printed unconditionally beside every regression in
`scripts/test_nfl_injury_market_edge.py`.

**The rule:** for any claim about betting, the regression is the SCREEN and the
ATS record on the bets you would actually place is the TEST. Never report the
first without the second, and never convert one into the other with a
coefficient.

**Related, same day:** this is the third distinct way a plausible number nearly
shipped — after (1) a 5.8σ proxy that did not transfer to the objective, and
(2) per-book rows overstating significance 3.4× versus per-game. All three were
caught by asking "what would I actually bet, and how many independent bets is
that?"
