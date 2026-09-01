"""Which artifact root a WNBA card came from, and whether its lines are real.

**READ THIS BEFORE EVALUATING ANYTHING OFF `/wnba/api/cards`.**

That endpoint serves from either of two roots, resolved per requested file
(`#309`):

    wnba_source/data/processed/          Syndicate-owned
    wnba_source/source_artifacts/...     vendor bundle

They are not two qualities of the same data. Measured 2026-08-31 against ESPN
over 2026-05-17..08-30 (lane `wnba-accuracy-assessment`):

    root        n    Brier skill    AUC     corr(MARKET line, actual margin)
    Syndicate  106      +16.53%   0.7631                             +0.6785
    vendor      79      -72.36%   0.4018                             -0.0396

**The decisive column is the MARKET's, not the model's.** A real book line
correlates ~+0.68 with the final margin. On the vendor root it is -0.04 — and a
market cannot be uninformative about its own game, so those rows are mis-joined
at source and nothing computed from them means anything. Corroborating: spreads
reaching **55.0** and totals reaching **253.0**, neither of which exists in WNBA
basketball.

**Why this module exists rather than a note.** Pooled across both roots the sim
measures Brier skill **-21.5%**, AUC 0.595 — "worse than climatology, delete
it". Split on the root it is **+16.5%**, AUC 0.763, the best pregame asset on
the platform. *The first pass of the assessment that discovered this reported the
pooled number.* A rule in a ledger did not stop that and would not stop the next
one; a function the evaluation actually calls has a chance.

Usage in any WNBA evaluation:

    rows = [r for r in rows if root_of(r["source_path"]) == SYNDICATE]
    # or, keeping both and reporting the split, which is better:
    report(split_by_root(rows))
"""
from __future__ import annotations

from typing import Any, Iterable

SYNDICATE = "syndicate"
VENDOR = "vendor"
UNKNOWN = "unknown"

# The marker that identifies the vendor bundle in a resolved path.
_VENDOR_MARKER = "source_artifacts"

# WNBA reality, used only to catch values that cannot be book lines at all.
# Deliberately WIDE: the point is to catch 55.0 and 253.0, not to second-guess a
# real line. A blowout spread of 20 and a total of 145 are both real.
MAX_PLAUSIBLE_ABS_SPREAD = 20.5
MIN_PLAUSIBLE_TOTAL = 145.0
MAX_PLAUSIBLE_TOTAL = 200.0


def root_of(source_path: Any) -> str:
    """`syndicate`, `vendor`, or `unknown` for a card payload's `source_path`.

    `unknown` is returned rather than defaulting to `syndicate`: an unknown
    provenance must not silently join the trusted pile, which is the
    unknown-defaults-permissive failure this repo treats as forbidden.
    """
    text = str(source_path or "").strip().replace("\\", "/")
    if not text:
        return UNKNOWN
    return VENDOR if _VENDOR_MARKER in text else SYNDICATE


def implausible_line_reasons(betting: dict[str, Any] | None) -> list[str]:
    """Why this row's market lines cannot be real, if they cannot.

    Returns [] for a plausible row. Checks the LINE, not the model -- a model
    can be wrong, a book line cannot be 55 points.
    """
    reasons: list[str] = []
    if not isinstance(betting, dict):
        return reasons

    spread = betting.get("home_spread")
    try:
        if spread is not None and abs(float(spread)) > MAX_PLAUSIBLE_ABS_SPREAD:
            reasons.append(f"spread {float(spread):+.1f} exceeds +/-{MAX_PLAUSIBLE_ABS_SPREAD}")
    except (TypeError, ValueError):
        pass

    total = betting.get("total")
    try:
        if total is not None and not (MIN_PLAUSIBLE_TOTAL <= float(total) <= MAX_PLAUSIBLE_TOTAL):
            reasons.append(
                f"total {float(total):.1f} outside {MIN_PLAUSIBLE_TOTAL:.0f}-{MAX_PLAUSIBLE_TOTAL:.0f}"
            )
    except (TypeError, ValueError):
        pass

    for field in ("home_spread_price", "away_spread_price", "total_over_price",
                  "total_under_price", "home_ml", "away_ml"):
        value = betting.get(field)
        try:
            if value is not None and -100.0 < float(value) < 100.0:
                # No American price lives strictly between -100 and +100; this is
                # the arithmetic-averaging artefact fixed in refresh_wnba_oddsapi_props.
                reasons.append(f"{field} {float(value):.2f} is not an American price")
        except (TypeError, ValueError):
            continue
    return reasons


def split_by_root(rows: Iterable[dict[str, Any]], *, source_path_key: str = "source_path") -> dict[str, list]:
    """Partition rows by provenance. Every evaluation should report this."""
    buckets: dict[str, list] = {SYNDICATE: [], VENDOR: [], UNKNOWN: []}
    for row in rows:
        buckets[root_of((row or {}).get(source_path_key))].append(row)
    return buckets


def coverage_note(buckets: dict[str, list]) -> str:
    """One line naming what was excluded, so a filtered sample says it is filtered.

    A silently filtered sample reads as a complete one -- which is how a
    43%-contaminated archive produced a confident wrong verdict.
    """
    total = sum(len(v) for v in buckets.values())
    if not total:
        return "0 rows"
    parts = [f"{name} {len(rows)} ({100 * len(rows) / total:.1f}%)"
             for name, rows in buckets.items() if rows]
    return f"{total} rows: " + ", ".join(parts)


# --------------------------------------------------------------------------
# Confidence hygiene, applied at READ time as well as at production.
#
# The producer's clamp (refresh_wnba_oddsapi_props) fixes what it WRITES. But
# `p_win` and `ev_pct` are baked into `recommendations_slate_*.json` and copied
# verbatim by the card builder, so every artifact already on disk keeps whatever
# it was written with -- and WNBA does not rebuild until 2026-09-17. Measured on
# the served payload 2026-09-01, AFTER the producer fix deployed: a 2026-08-30
# card still showed `p_win = 1.0`.
#
# So the same rule is applied on the way out. Not belt-and-braces for its own
# sake: a fix that only affects future artifacts is not in force on anything a
# reader can currently see.
CONFIDENCE_FLOOR, CONFIDENCE_CEILING = 0.01, 0.99
MAX_PLAUSIBLE_EV_PCT = 100.0


def sane_win_probability(value: Any) -> float | None:
    """Refuse certainty. A pregame WNBA bet is never 100%.

    Measured 2026-08-31: 36 of 466 recommendations claimed `p_win = 1.000` on a
    board realizing 47.62%.
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return max(CONFIDENCE_FLOOR, min(CONFIDENCE_CEILING, numeric))


def sane_ev_pct(value: Any) -> float | None:
    """Absence, not a clamped value, for an EV that cannot be real.

    A refused EV renders as an em dash, which is true. A clamped one renders as
    exactly 100.0%, which is a number nobody computed and reads as a real edge.
    The measured outlier was 2264.8%.
    """
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return None if abs(numeric) > MAX_PLAUSIBLE_EV_PCT else numeric
