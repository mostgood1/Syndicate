#!/usr/bin/env python3
"""Differential test over every PURE probability<->odds converter in the tree.

Program plan Tier 3a. The board-engine audit counted 42 sites that define or
convert a probability -- 18 prob<->odds conversions and 9 `implied_probability`
functions among them. That count is a duplication finding. This harness turns it
into a correctness finding: run every implementation over ONE shared price grid
and diff the results.

**Any disagreement between two implementations at the same input is a live
pricing bug, not a style difference.** Two surfaces can quote the same market and
publish different implied probabilities from the same price, and nothing in the
test suite would notice, because each implementation is only ever tested (if at
all) against the prices its own caller happens to send.

The harness is deliberately I/O-free and import-only. It does not need a slate,
an artifact mirror, or a deployed service, so it stays runnable after this pass
-- the same property that kept `scripts/ask_syndicate_regression.py` useful.

Usage:
    python scripts/probability_differential.py            # table + exit 1 on disagreement
    python scripts/probability_differential.py --json     # machine-readable
    python scripts/probability_differential.py --concept american_to_probability
    python scripts/probability_differential.py --quiet    # disagreements only

Exit code is 1 when any concept has more than one behaviour cluster, so this can
gate a future consolidation. It is NOT wired into `migration_gate.py` yet: the
disagreements it currently reports are real and unfixed, so it would fail the
gate for a condition nobody has agreed to fix.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------
# Every value the plan named, plus the two that separate "returns None" from
# "raises": a bare string and a float where an int is expected.
#
# `0` is not a real American price -- there is no such quote -- so the only
# defensible answers are None or a raised exception. An implementation that
# returns a NUMBER at 0 is publishing a probability for a price that does not
# exist, and several do.
#
# The decimal-odds rows (2.5, 1.5) are the cross-convention probe. Decimal 2.5
# is +150 in American; read AS American, +2.5 is a 97.6% favourite. No converter
# can distinguish them from the value alone, so the question is only whether the
# implementation refuses out-of-range American input or silently prices it.

AMERICAN_GRID: list[tuple[str, Any]] = [
    ("zero", 0),
    ("plus_100", 100),
    ("minus_100", -100),
    ("plus_150", 150),
    ("minus_150", -150),
    ("plus_10000", 10000),
    ("minus_10000", -10000),
    ("none", None),
    ("empty_string", ""),
    ("str_plus_150", "+150"),
    ("str_minus_150", "-150"),
    ("dec_2.5_as_amer", 2.5),
    ("dec_1.5_as_amer", 1.5),
    ("float_-110.5", -110.5),
]

# For the inverse direction. 0.0 and 1.0 are the degenerate ends (no finite fair
# price exists at either); 50.0 is the percent-vs-fraction confusion, which is a
# real hazard here because `confidence` is stored 0-100 and probability 0-1 in
# the same rows.
PROBABILITY_GRID: list[tuple[str, Any]] = [
    ("zero", 0.0),
    ("p_0.01", 0.01),
    ("p_0.02", 0.02),
    ("p_0.40", 0.40),
    ("p_0.50", 0.50),
    ("p_0.5238", 0.5238),
    ("p_0.98", 0.98),
    ("p_0.99", 0.99),
    ("one", 1.0),
    ("none", None),
    ("empty_string", ""),
    ("str_0.5", "0.5"),
    ("percent_50.0", 50.0),
]


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Impl:
    """One implementation of one concept."""

    concept: str
    module: str
    attr: str
    note: str = ""
    # Some implementations are vectorized (pandas). The adapter turns them into
    # f(value) without changing what they compute.
    adapter: Callable[[Any, Any], Any] | None = field(default=None, compare=False)

    @property
    def label(self) -> str:
        return f"{self.module}:{self.attr}"


def _series_adapter(fn: Any, value: Any) -> Any:
    """Vectorized converter -> scalar. Preserves the implementation's own
    coercion (`pd.to_numeric(errors='coerce')`), which is the point of testing
    it: that coercion is a behaviour, not a wrapper detail."""
    import pandas as pd  # local import so the harness degrades without pandas

    out = fn(pd.Series([value], dtype="object"))
    result = out.iloc[0]
    try:
        if result is None or (isinstance(result, float) and math.isnan(result)):
            return None
    except TypeError:
        pass
    return float(result)


AMERICAN_TO_PROBABILITY: list[Impl] = [
    Impl("american_to_probability", "syndicate.features.shared.opportunity_signals", "implied_probability",
         "float() coercion + zero guard"),
    Impl("american_to_probability", "syndicate.features.shared.quote_enrichment", "_implied_probability",
         "body identical to opportunity_signals, copied not imported"),
    Impl("american_to_probability", "syndicate.features.shared.odds_book_quotes", "_implied_probability",
         "typed `price: int -> float`; NO coercion, NO zero guard"),
    Impl("american_to_probability", "syndicate.features.shared.odds_lifecycle", "_implied_probability_from_american_odds"),
    Impl("american_to_probability", "syndicate.features.shared.odds_refresh_tracking", "_implied_probability_from_american"),
    Impl("american_to_probability", "syndicate.features.shared.intelligence_evaluation", "_implied_probability_from_american"),
    Impl("american_to_probability", "syndicate.features.shared.prop_projections", "_implied"),
    Impl("american_to_probability", "syndicate.features.prediction_ledger", "_implied_from_american"),
    Impl("american_to_probability", "syndicate.features.bankroll_manager", "_implied_probability_from_odds",
         "NO zero guard"),
    Impl("american_to_probability", "syndicate.features.intelligence", "odds_to_implied_probability",
         "public wrapper of `_american_implied_probability`; NO zero guard"),
    Impl("american_to_probability", "syndicate.features.intelligence", "_american_implied_probability",
         "NO zero guard"),
    Impl("american_to_probability", "syndicate.features.mlb.cards", "_american_implied_prob",
         "int(str(value)) -- rejects any non-integer text"),
    Impl("american_to_probability", "syndicate.features.mlb.hr_targets", "_american_odds_implied_prob",
         "int(value) on the raw object -- TRUNCATES a float"),
    Impl("american_to_probability", "syndicate.features.nba.cards", "_implied_prob_from_american"),
    Impl("american_to_probability", "syndicate.features.wnba.cards", "_implied_prob_from_american"),
    Impl("american_to_probability", "syndicate.features.ncaab.mirror_export", "_american_to_probability",
         "compares the raw argument to 0 -- no coercion"),
    Impl("american_to_probability", "syndicate.features.nhl.sim_engine.hockeysim.adapters", "american_to_implied",
         "routes through american_to_decimal: 1/decimal, not the direct form"),
    Impl("american_to_probability", "syndicate.features.nhl.sim_engine.hockeysim.features.market_lines", "_american_to_prob"),
    Impl("american_to_probability", "syndicate.features.shared.basketball_props_tracking", "_american_to_implied",
         "pandas Series in/out", adapter=_series_adapter),
    Impl("american_to_probability", "syndicate.features.shared.recommendation_engine", "_parse_american_odds",
         "NAME SAYS PARSE, BODY RETURNS A PROBABILITY"),
    Impl("american_to_probability", "scripts.refresh_nba_oddsapi_props", "_american_price_to_prob"),
    Impl("american_to_probability", "scripts.refresh_wnba_oddsapi_props", "_american_price_to_prob"),
    Impl("american_to_probability", "scripts.build_soccer_picks", "_american_to_implied_prob"),
    Impl("american_to_probability", "scripts.validate_soccer_vs_market", "_american_to_prob",
         "NO zero guard; 0 falls through the `> 0` branch"),
    Impl("american_to_probability", "scripts.fetch_mlb_oddsapi_local", "_american_implied_prob"),
    Impl("american_to_probability", "scripts.regrade_mlb_game_markets", "_american_to_implied",
         "int(price), no guards at all"),
]

AMERICAN_TO_DECIMAL: list[Impl] = [
    Impl("american_to_decimal", "syndicate.features.bankroll_manager", "_american_to_decimal"),
    Impl("american_to_decimal", "syndicate.features.intelligence", "_american_to_decimal",
         "NO zero guard"),
    Impl("american_to_decimal", "syndicate.features.shared.live_lens_local", "_american_to_decimal"),
    Impl("american_to_decimal", "syndicate.features.nhl.sim_engine.hockeysim.adapters", "american_to_decimal"),
    Impl("american_to_decimal", "scripts.build_soccer_picks", "_american_to_decimal"),
    Impl("american_to_decimal", "scripts.regrade_mlb_game_markets", "_american_to_decimal",
         "int(price) then 100/abs(price) -- ZeroDivisionError at 0"),
]

def _backfill_card_adapter(fn: Any, value: Any) -> Any:
    """`pipeline/intelligence_state.py::_backfill_layer2_board_columns` carries
    the prob->american formula INLINE -- no named function, so no function-level
    audit counts it and no consolidation would find it. It is still a producer
    of the `fair_price` the board renders, so it is tested through its real
    entry point rather than left out."""
    card: dict[str, Any] = {"quote": {"fair_probability": value}}
    fn(card)
    return card.get("fair_price")


PROBABILITY_TO_AMERICAN: list[Impl] = [
    Impl("probability_to_american", "syndicate.features.shared.opportunity_signals", "american_price",
         "strict 0<p<1; returns int"),
    Impl("probability_to_american", "pipeline.intelligence_state", "_backfill_layer2_board_columns",
         "INLINE copy of the clamped formula; found by tracing the `fair_price` "
         "field, not by grepping for a def", adapter=_backfill_card_adapter),
    Impl("probability_to_american", "syndicate.features.shared.layer2_board", "_american_from_probability",
         "clamps to [0.02, 0.98]"),
    Impl("probability_to_american", "syndicate.features.wnba.cards", "_american_from_prob",
         "clamps to [0.02, 0.98]"),
    Impl("probability_to_american", "syndicate.features.nhl.sim_engine.hockeysim.features.market_lines", "_prob_to_american",
         "clamps to [1e-4, 1-1e-4]"),
]

REGISTRY: list[Impl] = AMERICAN_TO_PROBABILITY + AMERICAN_TO_DECIMAL + PROBABILITY_TO_AMERICAN

GRIDS: dict[str, list[tuple[str, Any]]] = {
    "american_to_probability": AMERICAN_GRID,
    "american_to_decimal": AMERICAN_GRID,
    "probability_to_american": PROBABILITY_GRID,
}

# Known non-importable implementations of the same concepts. Recorded rather
# than silently dropped: a converter defined inside a function body is invisible
# to every consolidation and to this harness alike, which is itself a finding.
NOT_REACHABLE: list[tuple[str, str]] = [
    ("scripts/refresh_wnba_oddsapi_props.py `_implied` (nested)",
     "defined inside a function; not importable, so untestable and unshareable"),
    ("syndicate/features/intelligence_audit.py `decimal_to_american` (nested)",
     "defined inside a function; decimal->american, no module-level twin"),
]


# ---------------------------------------------------------------------------
# Coverage: catching the 27th implementation before it ships
# ---------------------------------------------------------------------------
# A one-off differential is a snapshot. What makes this worth keeping is the
# sweep below: any NEW module-level function whose name looks like a converter
# must be either registered above or listed here with a reason. Otherwise the
# next duplicate lands silently and the whole exercise repeats.

_DEF_RE = None  # compiled lazily; `re` is only needed for the sweep

# Converter-SHAPED names that are not scalar prob<->odds converters. Each needs
# a reason, so that "it isn't one" is a claim someone made and not an omission.
NOT_A_SCALAR_CONVERTER: dict[str, str] = {
    "scripts/build_soccer_picks.py:_devig": "normalizes a probability dict; not scalar",
    "scripts/fetch_mlb_oddsapi_local.py:_american_str": "formats a price for display",
    "scripts/probability_differential.py:reference_american_to_probability": "this harness's own reference",
    "scripts/probability_differential.py:reference_american_to_decimal": "this harness's own reference",
    "syndicate/features/intelligence.py:_extract_american_odds_range": "parses a range out of free text",
    "syndicate/features/intelligence.py:_american_odds_match": "preference matcher, returns bool",
    "syndicate/features/intelligence.py:_american_odds_value": "coerces text to a price; the GUARD in front of the unguarded converters",
    "syndicate/features/intelligence.py:_decimal_to_american": "decimal->american; SOLE module-level impl of that direction, so no differential is possible",
    "syndicate/features/ncaaf/cards.py:_format_decimal": "display formatting",
    "syndicate/features/nhl/sim_engine/hockeysim/features/market_lines.py:_consensus_american": "takes a list",
    "syndicate/features/nhl/sim_engine/hockeysim/market_anchoring.py:devig_two_way_home_prob": "two-sided devig",
    "syndicate/features/prediction_reconciliation.py:_american_profit": "price->profit, not price->probability (3 impls; see the report)",
    "syndicate/features/shared/evaluation_settlement.py:_american_profit": "price->profit (3 impls; see the report)",
    "syndicate/features/shared/ledger_bridge.py:_american_profit": "price->profit (3 impls; see the report)",
    "syndicate/features/shared/layer2_board.py:_implied_book_total_pct": "ev_pct->book total, a different concept",
    "syndicate/features/shared/market_inventory.py:join_odds_to_sim": "a join, not a conversion",
    "syndicate/features/shared/opportunity_signals.py:devig": "sequence in, sequence out",
    "syndicate/features/shared/opportunity_signals.py:fair_probability_by_book": "book-keyed, not scalar",
    "syndicate/features/shared/opportunity_signals.py:consensus_fair_probability": "book-keyed, not scalar",
    "syndicate/features/shared/prop_projections.py:_no_vig_over_probability": "takes a row Mapping",
    "syndicate/features/shared/recommendation_engine.py:_market_fair_probability": "takes a candidate Mapping",
    "syndicate/features/shared/recommendation_engine.py:_fair_probability": "takes a candidate Mapping",
    "syndicate/features/soccer/features/market_anchoring.py:devig_decimal_odds": "dict in, dict out",
    "syndicate/features/soccer/props.py:_american_odds_text": "display formatting",
}

_NAME_HINT = ("implied", "american", "decimal", "devig", "no_vig", "novig",
              "fair_prob", "prob_to", "odds_to")


def discover_unregistered(root: str = ROOT) -> list[str]:
    """Module-level converter-shaped defs that are neither registered nor
    explicitly excused. Empty is the passing state."""
    import re

    global _DEF_RE
    if _DEF_RE is None:
        _DEF_RE = re.compile(r"^def ([_a-zA-Z][_a-zA-Z0-9]*)\s*\(", re.MULTILINE)

    registered = {f"{i.module.replace('.', '/')}.py:{i.attr}" for i in REGISTRY}
    unregistered = []
    for sub in ("syndicate", "pipeline", "scripts"):
        base = os.path.join(root, sub)
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames
                           if d not in {"__pycache__", "node_modules", ".venv", "venv"}]
            for filename in filenames:
                if not filename.endswith(".py"):
                    continue
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, root).replace("\\", "/")
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    continue
                for name in _DEF_RE.findall(text):
                    if not any(h in name.lower() for h in _NAME_HINT):
                        continue
                    key = f"{rel}:{name}"
                    if key in registered or key in NOT_A_SCALAR_CONVERTER:
                        continue
                    unregistered.append(key)
    return sorted(unregistered)


# ---------------------------------------------------------------------------
# The reference, and the requirements an owner has to meet
# ---------------------------------------------------------------------------
# A cluster count says implementations differ. It does not say which is right,
# and "the biggest cluster wins" is a vote, not evidence. So the harness carries
# an explicit reference form and an explicit requirement list, and the owner is
# whichever implementation satisfies the requirements. Anyone who disagrees with
# the recommendation has to argue with a named requirement.


def reference_american_to_probability(price: float) -> float:
    """The textbook form, for a price already known to be a valid American
    quote. Deliberately unguarded -- what to do with invalid input is the whole
    argument, and answering it here would prejudge it."""
    return 100.0 / (price + 100.0) if price > 0 else abs(price) / (abs(price) + 100.0)


def reference_american_to_decimal(price: float) -> float:
    return 1.0 + (price / 100.0 if price > 0 else 100.0 / abs(price))


# Each requirement is (name, grid input, expected normalized result, why).
#
# The "why" is the load-bearing part: every one of these is a case the codebase
# actually produces, not a hypothetical.
REQUIREMENTS: dict[str, list[tuple[str, str, Any, str]]] = {
    "american_to_probability": [
        ("refuses_zero", "zero", None,
         "0 is not a quotable American price. Returning a NUMBER here publishes a "
         "probability for a price that does not exist, and 0.0 in particular makes "
         "`model_prob - market_prob` equal the entire model probability."),
        ("refuses_none", "none", None,
         "a missing price must render as absent, not raise -- the board-contract "
         "rule shipped as web 932a1f71 / a86eb4ed."),
        ("refuses_empty_string", "empty_string", None,
         "empty strings arrive from CSV mirrors and from OddsAPI payloads with a "
         "null price; raising takes out the whole row, not the one cell."),
        ("accepts_string_price", "str_plus_150", 0.4,
         "prices arrive as strings from JSON artifacts and CSV mirrors; '+150' is "
         "the wire format, not an edge case."),
        ("accepts_float_price", "float_-110.5", 0.5249406175,
         "consensus/averaged prices are floats. Truncating to int silently "
         "reprices; returning None silently blanks a card."),
    ],
    "american_to_decimal": [
        ("refuses_zero", "zero", None, "as above, and here it is a ZeroDivisionError risk too."),
        ("refuses_none", "none", None, "as above."),
        ("refuses_empty_string", "empty_string", None, "as above."),
        ("accepts_string_price", "str_plus_150", 2.5, "as above."),
        ("accepts_float_price", "float_-110.5", 1.9049773756, "as above."),
    ],
    "probability_to_american": [
        ("refuses_none", "none", None, "a missing probability has no fair price."),
        ("refuses_empty_string", "empty_string", None, "as above."),
        ("refuses_zero", "zero", None,
         "p=0 has no finite fair price. Returning one prints a number on the board "
         "claiming value on an impossibility."),
        ("refuses_one", "one", None, "p=1 likewise."),
        ("refuses_percent_scale", "percent_50.0", None,
         "THE live hazard: `confidence` is stored 0-100 and probability 0-1 in the "
         "same rows. An implementation that CLAMPS turns a unit error into a "
         "plausible-looking price instead of a refusal."),
    ],
}

# Round-trip probes for the inverse direction: f(p) must price back to p.
# A clamp breaks this and a unit error breaks it harder, so it separates the
# implementations without anyone having to prefer one.
ROUNDTRIP_PROBES: list[float] = [0.01, 0.05, 0.25, 0.40, 0.5238, 0.75, 0.95, 0.98, 0.99]
ROUNDTRIP_TOL = 5e-3  # generous: these round to whole American prices


def roundtrip() -> dict[str, dict[str, Any]]:
    """For each probability->american impl, price each probe and read it back
    through the reference. Reports the worst absolute error and where."""
    out: dict[str, dict[str, Any]] = {}
    for impl in PROBABILITY_TO_AMERICAN:
        fn, err = _resolve(impl)
        if err is not None:
            continue
        worst: dict[str, Any] = {"probe": None, "priced": None, "recovered": None, "error": None}
        failures: list[dict[str, Any]] = []
        for probe in ROUNDTRIP_PROBES:
            try:
                priced = impl.adapter(fn, probe) if impl.adapter is not None else fn(probe)
            except Exception as exc:  # noqa: BLE001
                failures.append({"probe": probe, "priced": f"RAISED {type(exc).__name__}"})
                continue
            if priced is None or float(priced) == 0:
                failures.append({"probe": probe, "priced": priced, "recovered": None})
                continue
            recovered = reference_american_to_probability(float(priced))
            err_abs = abs(recovered - probe)
            if worst["error"] is None or err_abs > worst["error"]:
                worst = {"probe": probe, "priced": float(priced),
                         "recovered": round(recovered, 6), "error": round(err_abs, 6)}
            if err_abs > ROUNDTRIP_TOL:
                failures.append({"probe": probe, "priced": float(priced),
                                 "recovered": round(recovered, 6), "error": round(err_abs, 6)})
        out[impl.label] = {"worst": worst, "failures": failures,
                           "passed": len(ROUNDTRIP_PROBES) - len(failures),
                           "probes": len(ROUNDTRIP_PROBES)}
    return out


def scorecard(results: dict[str, dict[str, Any]], concept: str) -> list[dict[str, Any]]:
    """Which implementations meet every stated requirement."""
    reqs = REQUIREMENTS.get(concept, [])
    rows = []
    for label, row in results.items():
        if row.get("_concept") != concept or row.get("_error"):
            continue
        failed = []
        for name, grid_input, expected, _why in reqs:
            actual = row.get(grid_input)
            if isinstance(expected, float) and isinstance(actual, float):
                ok = abs(actual - expected) < 1e-9
            else:
                ok = actual == expected
            if not ok:
                failed.append({"requirement": name, "expected": expected, "actual": actual})
        rows.append({"impl": label, "met": len(reqs) - len(failed),
                     "total": len(reqs), "failed": failed})
    rows.sort(key=lambda r: (-r["met"], r["impl"]))
    return rows


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
_SENTINEL_IMPORT_FAILED = "IMPORT_FAILED"


def _resolve(impl: Impl) -> tuple[Any | None, str | None]:
    try:
        module = importlib.import_module(impl.module)
    except Exception as exc:  # noqa: BLE001 - reporting, not handling
        return None, f"{type(exc).__name__}: {exc}"
    fn = getattr(module, impl.attr, None)
    if fn is None:
        return None, f"AttributeError: {impl.attr} not found in {impl.module}"
    return fn, None


def _normalize(value: Any) -> Any:
    """Round floats so 0.5238095238095238 and 0.52380952380952384 cluster."""
    if isinstance(value, bool):
        return f"bool:{value}"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return round(value, 10)
    if isinstance(value, int):
        return float(value)
    if value is None:
        return None
    if isinstance(value, str):
        return f"str:{value}"
    return f"{type(value).__name__}:{value}"


def run(registry: Iterable[Impl] = REGISTRY) -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    import_errors: dict[str, str] = {}

    for impl in registry:
        fn, err = _resolve(impl)
        if err is not None:
            import_errors[impl.label] = err
            results[impl.label] = {"_concept": impl.concept, "_error": _SENTINEL_IMPORT_FAILED}
            continue
        row: dict[str, Any] = {"_concept": impl.concept, "_note": impl.note}
        for name, value in GRIDS[impl.concept]:
            try:
                out = impl.adapter(fn, value) if impl.adapter is not None else fn(value)
                row[name] = _normalize(out)
            except Exception as exc:  # noqa: BLE001 - a raise IS the result
                row[name] = f"RAISED {type(exc).__name__}"
        results[impl.label] = row

    return {"results": results, "import_errors": import_errors}


def cluster(results: dict[str, dict[str, Any]], concept: str) -> list[dict[str, Any]]:
    """Group implementations by identical behaviour across the whole grid."""
    grid_names = [n for n, _ in GRIDS[concept]]
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for label, row in results.items():
        if row.get("_concept") != concept or row.get("_error"):
            continue
        key = tuple(json.dumps(row.get(n), sort_keys=True) for n in grid_names)
        buckets[key].append(label)
    out = []
    for key, labels in buckets.items():
        out.append({
            "members": sorted(labels),
            "size": len(labels),
            "behaviour": {n: json.loads(v) for n, v in zip(grid_names, key)},
        })
    out.sort(key=lambda b: (-b["size"], b["members"][0]))
    return out


def disagreements(results: dict[str, dict[str, Any]], concept: str) -> list[dict[str, Any]]:
    """Per grid point, the distinct answers and who gives each."""
    out = []
    for name, value in GRIDS[concept]:
        by_answer: dict[str, list[str]] = defaultdict(list)
        for label, row in results.items():
            if row.get("_concept") != concept or row.get("_error"):
                continue
            by_answer[json.dumps(row.get(name), sort_keys=True)].append(label)
        if len(by_answer) > 1:
            out.append({
                "input": name,
                "value": repr(value),
                "answers": [
                    {"result": json.loads(k), "count": len(v), "impls": sorted(v)}
                    for k, v in sorted(by_answer.items(), key=lambda kv: -len(kv[1]))
                ],
            })
    return out


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _short(label: str) -> str:
    """`syndicate.features.shared.foo:bar` -> `shared.foo:bar` for the matrix."""
    module, _, attr = label.partition(":")
    parts = module.split(".")
    if parts[:2] == ["syndicate", "features"]:
        parts = parts[2:]
    if len(parts) > 3:
        parts = parts[-3:]
    return ".".join(parts) + ":" + attr


def _fmt(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def report(payload: dict[str, Any], concepts: list[str], quiet: bool = False) -> int:
    results = payload["results"]
    failures = 0

    for concept in concepts:
        rows = [lbl for lbl, r in results.items() if r.get("_concept") == concept]
        ok = [lbl for lbl in rows if not results[lbl].get("_error")]
        clusters = cluster(results, concept)
        diffs = disagreements(results, concept)
        if len(clusters) > 1:
            failures += 1

        print(f"\n{'=' * 100}")
        print(f"CONCEPT: {concept}")
        print(f"  implementations: {len(rows)}   runnable: {len(ok)}   "
              f"behaviour clusters: {len(clusters)}   disagreeing inputs: {len(diffs)}")
        print("=" * 100)

        if not quiet and ok:
            grid_names = [n for n, _ in GRIDS[concept]]
            width = max(len(_short(lbl)) for lbl in ok)
            print("impl".ljust(width) + " | " + " ".join(n[:13].rjust(13) for n in grid_names))
            print("-" * (width + 3 + 14 * len(grid_names)))
            for lbl in sorted(ok, key=_short):
                row = results[lbl]
                cells = " ".join(_fmt(row.get(n))[:13].rjust(13) for n in grid_names)
                print(_short(lbl).ljust(width) + " | " + cells)

        print(f"\n  -- behaviour clusters ({len(clusters)}) --")
        for i, group in enumerate(clusters, 1):
            print(f"  [{i}] {group['size']} impl(s)")
            for member in group["members"]:
                print(f"        {member}")

        if diffs:
            print(f"\n  -- DISAGREEMENTS ({len(diffs)} grid points) --")
            for diff in diffs:
                print(f"  input {diff['input']} = {diff['value']}")
                for answer in diff["answers"]:
                    impls = [_short(i) for i in answer["impls"]]
                    shown = impls if len(impls) <= 4 else impls[:4] + [f"(+{len(impls) - 4} more)"]
                    print(f"      -> {_fmt(answer['result']):<20} x{answer['count']:<3} {', '.join(shown)}")

        card = scorecard(results, concept)
        reqs = REQUIREMENTS.get(concept, [])
        if card and reqs:
            survivors = [r["impl"] for r in card if r["met"] == r["total"]]
            print(f"\n  -- REQUIREMENTS ({len(reqs)}) --")
            for name, grid_input, expected, why in reqs:
                print(f"  {name}: {grid_input} -> {_fmt(expected)}")
                print(f"      {why}")
            print(f"\n  -- SCORECARD: {len(survivors)}/{len(card)} meet every requirement --")
            for row in card:
                mark = "PASS" if row["met"] == row["total"] else "fail"
                detail = "" if row["met"] == row["total"] else "  <- " + ", ".join(
                    f"{f['requirement']}={_fmt(f['actual'])}" for f in row["failed"])
                print(f"  [{mark}] {row['met']}/{row['total']}  {_short(row['impl'])}{detail}")
            if len(survivors) == 1:
                print(f"\n  OWNER (unique survivor): {survivors[0]}")
            elif survivors:
                print(f"\n  OWNER: {len(survivors)} implementations tie on requirements; "
                      "pick by module ownership, not by behaviour -- they are identical.")
            else:
                print("\n  OWNER: NONE of the current implementations meets every "
                      "requirement. The owner has to be written, not chosen.")

        if concept == "probability_to_american":
            trips = roundtrip()
            print(f"\n  -- ROUND TRIP (price it, read it back through the reference) --")
            for label, res in sorted(trips.items(), key=lambda kv: _short(kv[0])):
                worst = res["worst"]
                print(f"  {res['passed']}/{res['probes']} within {ROUNDTRIP_TOL}  {_short(label)}")
                if worst["error"] is not None:
                    print(f"        worst: p={worst['probe']} -> {_fmt(worst['priced'])} "
                          f"-> {worst['recovered']} (err {worst['error']})")

    if payload["import_errors"]:
        print(f"\n{'=' * 100}\nIMPORT FAILURES ({len(payload['import_errors'])}) "
              f"-- these implementations were NOT tested\n{'=' * 100}")
        for label, err in sorted(payload["import_errors"].items()):
            print(f"  {label}\n      {err}")

    if NOT_REACHABLE:
        print(f"\n-- not module-level, cannot be imported or shared ({len(NOT_REACHABLE)}) --")
        for where, why in NOT_REACHABLE:
            print(f"  {where}\n      {why}")

    missing = discover_unregistered()
    if missing:
        print(f"\n-- UNREGISTERED converter-shaped functions ({len(missing)}) --")
        print("   Add each to REGISTRY, or to NOT_A_SCALAR_CONVERTER with a reason.")
        for key in missing:
            print(f"  {key}")
        failures += 1
    else:
        print("\n-- coverage: every converter-shaped function is registered or excused --")

    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    parser.add_argument("--quiet", action="store_true", help="skip the full value matrix")
    parser.add_argument("--concept", action="append", choices=sorted(GRIDS),
                        help="restrict to one concept (repeatable)")
    args = parser.parse_args(argv)

    concepts = args.concept or sorted(GRIDS)
    payload = run([i for i in REGISTRY if i.concept in concepts])

    if args.json:
        out = {
            "grids": {c: [n for n, _ in GRIDS[c]] for c in concepts},
            "results": payload["results"],
            "import_errors": payload["import_errors"],
            "clusters": {c: cluster(payload["results"], c) for c in concepts},
            "disagreements": {c: disagreements(payload["results"], c) for c in concepts},
            "requirements": {c: [
                {"name": n, "input": i, "expected": e, "why": w}
                for n, i, e, w in REQUIREMENTS.get(c, [])] for c in concepts},
            "scorecard": {c: scorecard(payload["results"], c) for c in concepts},
            "roundtrip": roundtrip() if "probability_to_american" in concepts else {},
            "not_reachable": [{"where": w, "why": y} for w, y in NOT_REACHABLE],
        }
        print(json.dumps(out, indent=2, sort_keys=True, default=str))
        failures = sum(1 for c in concepts if len(cluster(payload["results"], c)) > 1)
    else:
        failures = report(payload, concepts, quiet=args.quiet)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
