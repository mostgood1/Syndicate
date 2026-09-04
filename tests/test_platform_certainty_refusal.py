"""The certainty refusal is PLATFORM-WIDE, and stays that way.

`#624` step 1 asked for a refusal of p in {0.0, 1.0} on MLB props. Measured on
the served board 2026-09-04, the defect was on three sports at once:

    mlb     1,447 rows w/ prob   16 EXACT 0.0    (null market price)
    ncaaf       2 rows w/ prob    1 EXACT 1.0    (a margin-model quality gate)
    soccer    466 rows w/ prob    8 EXACT 0.0    ("game is final")

Every one of the 25 was unpriced, and each by a DIFFERENT guard unrelated to
certainties. That is three accidents, not a rule -- none of them holds on a
pregame row of the same shape.

**`test_every_projection_writer_refuses` is the one that matters.** Eight
modules write `row["projection"]` directly and there is no shared assembly step,
so the only thing keeping a NINTH writer from reintroducing this is a test that
enumerates them. The first fix shipped into `_dist_prob_over` and covered 1 of
17 certainties, because that is the producer that happened to be visible.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.probability_refusal import (  # noqa: E402
    CERTAINTY_REFUSED,
    refuse_published_certainty,
)

SEARCH_ROOTS = ("syndicate", "pipeline")
GUARD = "refuse_published_certainty"


def _projection_writers() -> list[tuple[str, int, str]]:
    """Every `<expr>["projection"] = <rhs>` assignment, with its RHS source.

    AST rather than a grep: a grep matches the string inside a comment or a
    docstring, and several of these modules discuss `row["projection"]` in prose
    precisely because the direct-write design is deliberate.
    """
    found: list[tuple[str, int, str]] = []
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="replace")
            if '"projection"' not in text:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:  # pragma: no cover
                continue
            lines = text.splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if (isinstance(target, ast.Subscript)
                            and isinstance(target.slice, ast.Constant)
                            and target.slice.value == "projection"):
                        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                        src = lines[node.lineno - 1].strip()
                        found.append((rel, node.lineno, src))
    return found


def test_every_projection_writer_refuses():
    """A new `row["projection"] = ...` must route through the refusal.

    If this fails on a site you just added: call
    `refuse_published_certainty(...)` on the value. If the site genuinely cannot
    publish a probability, it still costs nothing -- the helper returns
    non-dicts and non-certainties untouched.
    """
    writers = _projection_writers()
    assert len(writers) >= 8, (
        "expected at least the 8 known projection writers, found %d -- if this "
        "dropped, the enumeration broke and is no longer guarding anything"
        % len(writers))
    unguarded = [(f, n, s) for f, n, s in writers if GUARD not in s]
    assert not unguarded, (
        "these write row['projection'] without refusing an exact certainty:\n"
        + "\n".join("  %s:%d  %s" % (f, n, s) for f, n, s in unguarded))


def test_the_enumeration_can_actually_fail():
    """OFF != ON for the structural test itself.

    A scanner that silently matches nothing passes forever. This proves the
    matcher finds a writer, and that the guard substring is what distinguishes a
    wired site from an unwired one.
    """
    writers = _projection_writers()
    files = {f for f, _, _ in writers}
    assert "syndicate/features/shared/prop_projections.py" in files
    assert "syndicate/features/shared/soccer_projections.py" in files
    assert "syndicate/features/ncaaf/game_projections.py" in files
    assert all(GUARD in s for _, _, s in writers)
    # ...and a hand-built unwired line is correctly judged unguarded.
    assert GUARD not in 'row["projection"] = projection'


# ---------------------------------------------------------------------------
# The rule itself.
# ---------------------------------------------------------------------------


def test_it_clears_the_edge_that_was_derived_from_the_certainty():
    """LOAD-BEARING. All eight writers PRICE BEFORE they assign, so the edge is
    already computed off the certainty by the time the refusal runs. Leaving it
    would be strictly worse than doing nothing: an edge with no probability
    behind it cannot be audited."""
    out = refuse_published_certainty({
        "model_prob_over": 0.0,
        "edge_vs_market_pct": 41.2,
        "model_edge_pct": 41.2,
        "edge_pct": 41.2,
        "projected": 1.7,
    })
    assert out["model_prob_over"] is None
    assert out["edge_vs_market_pct"] is None
    assert out["model_edge_pct"] is None
    assert out["edge_pct"] is None
    assert out["projected"] == 1.7, "the MEAN is real and survives"
    assert "certainty" in out["edge_unavailable_reason"]


def test_edge_vs_line_SURVIVES():
    """`edge_vs_line` is in LINE units and comes from the MEAN, not the
    probability -- it is exactly what soccer corners publish. Clearing it would
    delete a number the model did produce."""
    out = refuse_published_certainty({"model_prob_over": 1.0, "edge_vs_line": 2.4})
    assert out["edge_vs_line"] == 2.4


def test_an_existing_more_specific_reason_is_kept():
    """A row already unpriced for its own reason keeps it -- 'game is final' says
    more than the generic refusal does."""
    out = refuse_published_certainty({
        "model_prob_over": 0.0,
        "edge_vs_market_pct": None,
        "edge_unavailable_reason": "game is final: the market is settled",
    })
    assert out["edge_unavailable_reason"] == "game is final: the market is settled"
    assert out["model_prob_over"] is None, "the certainty still goes"


def test_a_real_probability_is_untouched():
    """Off != on. This refuses EXACTLY 0.0 and 1.0 -- not small, not large."""
    for value in (0.0001, 0.5, 0.9, 0.9999):
        out = refuse_published_certainty({"model_prob_over": value,
                                          "edge_vs_market_pct": 3.3})
        assert out["model_prob_over"] == value
        assert out["edge_vs_market_pct"] == 3.3
        assert "model_prob_over_refused" not in out


def test_the_original_value_is_retained():
    """A refusal to PRICE on a certainty, not the loss of one."""
    assert refuse_published_certainty(
        {"model_prob_over": 1.0})["model_prob_over_refused_value"] == 1.0
    assert refuse_published_certainty(
        {"model_prob_over": 0.0})["model_prob_over_refused_value"] == 0.0


def test_None_and_non_dicts_pass_through():
    assert refuse_published_certainty(None) is None
    assert refuse_published_certainty("nope") == "nope"


def test_booleans_are_left_alone():
    """`False == 0.0` in Python. A bool here is a different bug and rewriting it
    would hide it."""
    assert refuse_published_certainty({"model_prob_over": False})["model_prob_over"] is False


def test_the_refused_set_is_exact():
    assert CERTAINTY_REFUSED == frozenset({0.0, 1.0})
