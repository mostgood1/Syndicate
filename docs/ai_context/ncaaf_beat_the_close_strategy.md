# NCAAF: how to earn the right to serve picks again

**Status 2026-08-19: picks SUPPRESSED at the serving layer.** Projections still
generate, publish and display; the *recommendation to bet them* is withheld.
Gate: `syndicate/features/football/pick_gate.py`.

---

## 0. The measurement that closed the board

    n=220 games, prior-season 2024 SP+ -> realised 2025 margins (leak-free),
    40 seeds/game, closing spread on the SAME games as the benchmark.

        model MAE 13.763        market MAE 11.586
        paired dMAE +2.176, SE 0.518, t = +4.20      SIGNIFICANT

Every scale from 6 to 24 loses (best 13.595, still +2.0). **The gap is a
property of the model, not of a tuning constant** — which is why the response is
a serving gate rather than another parameter sweep.

### Why "calibrated" was never the same as "competitive"

Earlier this session NCAAF margins went from SD 1.74 to 15.37 against a market
14.46 — a ratio of 1.06. That was real and worth doing: the old state priced
every college game as a coin flip. But **matching the market's DISPERSION says
nothing about being RIGHT.** A model can spread its predictions exactly like the
market's and still put them in the wrong places. Dispersion was a proxy, accuracy
is the thing, and until 2026-08-19 only the proxy had ever been measured.

The same error sat one layer down: `SP_RATING_SCALE=10` was chosen because it
matched market dispersion. Scored for accuracy, the MAE-optimal scale is ~13 —
but paired, that difference is **dMAE −0.168, SE 0.225, t=−0.74: not
significant.** The constant stays at 10. Two proxy-optimised numbers, one real
problem underneath both.

---

## 1. Why the model loses, ranked by how much gap each could plausibly close

The market is not smarter in the abstract — it *knows things the model is not
told*. Ranked by expected points of MAE, most promising first:

| # | What the market has | What the model has | Est. gap share |
|---|---|---|---|
| 1 | **Injuries / availability** — starting QB out is worth 7–14 pts in CFB | nothing; no injury input exists anywhere in the pipeline | large |
| 2 | **In-season updating** — reprices every week on results | SP+ refetched per run, but no in-week signal | medium, see §2 |
| 3 | **Situational** — rest days, travel, lookahead/letdown, weather, altitude | none | medium |
| 4 | **Personnel depth** — portal churn, suspensions, opt-outs | data BUILT (rosters, transfers, continuity) and **unwired** | unknown |
| 5 | **Motivation/context** — rivalry, bowl positioning, coach hot seat | none | small |

Two of these are unusually cheap here: **#4 is already built and merely
unplumbed**, and returning production is now *measured* to be non-redundant with
SP+ (see `ncaaf_data_pipeline.md` §7 — pooled r=+0.207, n=786, 5.8σ against
year-over-year movement, positive in all six seasons).

---

## 2. The load-bearing caveat in my own measurement

**The harness scored STATIC prior-season ratings across an entire following
season.** By week 12 those ratings are 15 months old. Production is not that
stale: it refetches `/ratings/sp?year=<current season>`, which CFBD updates
in-season.

So the measurement is a **fair proxy for week 1** — where preseason ratings
genuinely are the input — and **pessimistic afterwards**. This is being resolved
by a per-week split of the same gap (`scratchpad/gap_by_week.py`):

- **gap flat across weeks** → staleness is not the driver; the model is simply
  worse, and in-season updating will not save it. Attack §1 #1/#3.
- **gap grows with week** → staleness IS the driver; production is better than
  this number implies, the week-1 suppression still stands on its own evidence,
  and in-season updating is the highest-value lever.

**The week-1 suppression holds either way**, which is what matters with the
opener on 2026-08-29. Anyone lifting the gate for later weeks must read this
split first.

---

## 3. The strategy

### Stage 0 — instrument, now, before the opener *(prerequisite for everything)*

The gate cannot open on evidence that is never collected. Generation deliberately
continues under suppression for exactly this reason: **a gate that blinds its own
exit criterion never opens.**

Record for every NCAAF game, every week: model margin, closing line, opening
line, realised margin. That single table answers every question below and costs
nothing but a writer. Without it, the 2026 season passes and the gate is still
closed in January on 2025 evidence.

### Stage 1 — beat the OPENING line before trying to beat the close

The closing line is the hardest target in sports betting; it absorbs every
injury report and every sharp bet. **The opening line is materially softer.**
A model that cannot beat the open has no business being pointed at the close,
and a model that beats the open but not the close is a *timing* problem, not an
*accuracy* problem — a completely different and much easier fix.

This reframes the exit criterion usefully: measure against **both** lines and
learn which gap is real.

### Stage 2 — fix what is already built but unplumbed *(cheapest real work)*

Rosters, transfers, coach continuity and returning production exist as artifacts
and reach nothing. Returning production is now measured non-redundant with SP+.
**But** it arrives through the `feature_generation_payload` lever, worth ~4.1% of
margin SD against the ratings lever's ~17.2% — and the NFL payload experiment on
that same lever returned a measured NULL.

**So wire it as a RATING ADJUSTMENT, not a payload key.** ≈1.7 SP+ points per SD
of returning production, applied to the SP+ input, goes through the 17.2% lever.
Gate it on a paired margin test against realised results — the same test that
closed the board — not on the residual correlation that merely made it
interesting.

### Stage 3 — injuries, the biggest single lever

Nothing in the pipeline knows a starting quarterback is out. In college football
that is routinely a double-digit swing, and it is a large part of what the
closing line is pricing that the model is not. This is the item most likely to
close the gap on its own, and also the most work: it needs a source, a
depth-chart join, and a positional value model.

### Stage 4 — stop trying to beat the close on EVERY game

**This is the strategically important one, and it changes the target.**

Beating the close *on average across all games* is the wrong bar. Betting does
not require being better everywhere — it requires being better **on the games you
actually bet**. A model with worse overall MAE can still be profitable if it can
identify a subset where it is better.

Plausible subsets where a ratings model may genuinely beat a thin market:
non-conference mismatches, low-total games, games with little public attention,
early-season games before the market has in-season data either.

**The discipline this demands, stated plainly because it is the standard way
people fool themselves here:** searching subsets for one where the model wins
will *always* find one. That is data mining. A subset counts only if it is
specified in advance, tested out-of-sample on a season not used to find it, and
survives with an honest denominator. Absent that, a subset result is noise
wearing a hypothesis costume.

### Stage 5 — the honest fallback: blend toward the market

If the model cannot beat the close alone, `w*model + (1-w)*market` with small `w`
fitted out-of-sample will not lose to it either, and any real signal shows up as
`w > 0` with the blend beating the market. This is a legitimate product — but be
clear about what it is: **mostly the market's opinion**, and the "edge" it
produces is correspondingly small. It should never be presented as an independent
model.

---

## 4. The exit criterion, precisely

A market opens in `_SERVING_REGISTRY` when **all** hold:

1. **Paired** model-vs-market comparison on **realised** results, same games,
   same period — the paired SE is what governs, not two independent MAEs.
2. Model error **at or below** the closing line's, with the difference not
   inside noise (the +2.176 gap was 4.2σ; the scale-13 "improvement" was 0.7σ
   and was correctly rejected).
3. **Out-of-sample**: measured on a season not used to build or tune it.
4. Honest denominator: report the number of games it rests on, and if the claim
   is about a subset, the subset's own n.

Then update `_SERVING_REGISTRY` **with that measurement attached**. Never by
loosening the default — the default-deny is the only thing standing between an
unmeasured market and the board.

---

## 5. What NOT to do, with evidence

- **Do not retune `SP_RATING_SCALE`.** Every scale 6..24 loses to the close;
  10 vs the MAE-optimal 13 is 0.7σ. This lever is exhausted.
- **Do not retry the three dead scalar fixes** — index clamp, yardage-weight
  asymmetry, `scoring_environment` asymmetry. All measured, all dead
  (`.syndicate/log/2026-08-19.md`).
- **Do not add a mechanism without re-fitting what already absorbs it.**
  `model_engine_standard.md` §4.4: two mechanisms together produced a NEGATIVE
  interaction in 4 of 4 markets.
- **Do not lift the gate because the board looks empty.** It is supposed to.
  The empty state states the reason and the numbers precisely so nobody
  "repairs" it.
- **Do not treat totals as a smaller version of this problem.** They are worse:
  1.67x market dispersion, never scored against the close at all. Over-dispersion
  actively *manufactures* edges — an inflated spread of projected totals crosses
  more lines by further, so it reads as conviction.
