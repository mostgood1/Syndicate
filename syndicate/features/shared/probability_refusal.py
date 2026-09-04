"""Refuse to PUBLISH a simulated probability of exactly 0.0 or 1.0.

`#624` step 1 asks for this by name -- "hard refusal of p in {0.0, 1.0}" -- and
it was written for MLB props. **It is a platform-wide defect.** Measured on the
served board 2026-09-04T04:39Z, across every sport that had rows:

    sport    rows w/ prob   EXACT 0.0   EXACT 1.0   suppressed by
    mlb             1,447          16           0   a null market price
    ncaaf               2           0           1   a margin-model quality gate
    soccer            466           8           0   "game is final"
    nfl               598           0           0
                                   --          --
                                   24           1   = 25 platform-wide

**WHY THIS IS A MODULE AND NOT A FUNCTION IN ONE SPORT'S FILE.** Eight modules
write `row["projection"]` directly, deliberately -- the WNBA code says so in a
comment ("because THIS function writes `row['projection']` directly"). There is
no shared assembly step to put this in, so the refusal has to be a shared thing
that each writer calls. The alternative, patching whichever producer someone
noticed, is what shipped first: a refusal sited in `_dist_prob_over` caught
**1 of the 17** MLB certainties, because 16 of them are threshold rungs read
from `p_hr_Nplus_cal` and never touch a distribution.

**A FINITE SIMULATION CANNOT ESTABLISH IMPOSSIBILITY.** N sims can bound a
probability and can never zero it, so an exact 0.0 or 1.0 is a statement about
the SAMPLE, not about the world. Published as a probability it is unbounded
downstream: LogLoss is infinite when the certainty is wrong, and the edge
against any quoted price is whatever that price implies.

**0.0 IS THE DANGEROUS SIGN, NOT 1.0.** `model_prob_over = 0.0` says the OVER
cannot happen, which makes the UNDER a 100%-confidence bet against whatever the
book pays -- and 24 of the 25 found were zeros.

**EVERY ONE OF THE 25 WAS UNPRICED, AND THAT IS THE ARGUMENT FOR FIXING IT, NOT
AGAINST.** Each was held back by a DIFFERENT guard that has nothing to do with
certainties: MLB's had no market price, soccer's game was final, NCAAF's margin
model is gated for losing to the closing line. Three unrelated accidents, none
of them a property of the rule, none of them present on a pregame row of the
same shape. A healthy reading that survives for a reason unconnected to the rule
you are relying on is not evidence that the rule exists.

**IT REFUSES, IT DOES NOT CLAMP.** Clamping to 0.001/0.999 keeps the row and
publishes a number the sim did not produce -- a fabricated edge. Blanking makes
the row unpriceable, which is the honest outcome.

**IT CLEARS THE DERIVED EDGE TOO, and that is load-bearing.** All eight writers
price BEFORE they assign `row["projection"]`, so by the time this runs the edge
has already been computed off the certainty. Leaving it would be strictly worse
than doing nothing: an edge with no probability behind it is one a reader cannot
audit. `edge_vs_line` is deliberately NOT cleared -- it is in LINE units and
comes from the MEAN, not the probability.
"""

from __future__ import annotations

from typing import Any

#: Exact, not a band. 0.9 from a real distribution is signal and survives
#: untouched; narrowing this to a range would discard what the sim does know.
CERTAINTY_REFUSED = frozenset({0.0, 1.0})

#: Fields computed FROM `model_prob_over`. When the probability is refused these
#: are unsupported and must go with it.
_DERIVED_EDGE_FIELDS = ("edge_vs_market_pct", "model_edge_pct", "edge_pct")

_REASON = (
    "the simulation returned an exact certainty, which is a statement about the "
    "sample rather than the world -- a finite sim cannot establish impossibility, "
    "so this row carries no probability to price against"
)


def refuse_published_certainty(projection: Any) -> Any:
    """Blank an exact 0.0/1.0 `model_prob_over`, and the edge derived from it.

    Mutates and returns `projection`. A non-dict passes straight through, so
    `None` -- the honest "no projection at all" -- stays `None` and never
    becomes a dict.

    **THE MEAN SURVIVES.** Only the probability and its derived edge go. The sim
    genuinely has a mean; what it cannot state is P(over the line) from a sample
    that never crossed it. Deleting the mean as well would discard a number the
    model really did produce.

    **THE BLANK IS LABELLED.** `test_a_genuine_zero_is_still_a_projection` (the
    HR ladder) pins that absence and zero must not collapse into each other, and
    it is right: an UNCOUNTED rung returns no row at all, a COUNTED zero returns
    a row. That distinction survives in the SHAPE, but a consumer should not have
    to infer it, so the original value is kept in
    `model_prob_over_refused_value`. This is a refusal to PRICE on a certainty,
    not the loss of one.
    """
    if not isinstance(projection, dict):
        return projection
    value = projection.get("model_prob_over")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        # A bool in this field is a DIFFERENT bug (`False == 0.0` in Python) and
        # silently rewriting it to None would hide it.
        return projection
    if float(value) not in CERTAINTY_REFUSED:
        return projection

    projection["model_prob_over"] = None
    projection["model_prob_over_refused"] = "exact_certainty"
    projection["model_prob_over_refused_value"] = float(value)

    cleared = False
    for key in _DERIVED_EDGE_FIELDS:
        if projection.get(key) is not None:
            projection[key] = None
            cleared = True
    if cleared or not projection.get("edge_unavailable_reason"):
        # Overwrite an existing reason only when we actually took an edge away;
        # otherwise fill a blank one. A row that was already unpriced for its own
        # reason keeps that reason, which is the more specific of the two.
        projection["edge_unavailable_reason"] = _REASON
    return projection
