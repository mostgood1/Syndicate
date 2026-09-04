"""The last mile: does the MEASURED correlation actually get installed?

Three pieces existed and nothing joined them -- the engine's registry
(`af83addb`), the MLB joint resolver (`ee083bd0`), and a caller. This is the
caller, and these tests exist because the failure mode is silence: a resolver
that answers `None` for every pair is INDISTINGUISHABLE from one nobody
installed, and both look like a healthy build.

It is deliberately inert until a `sim_*.json` carries a `joint` block, which
needs a sim RUN and not just a deploy. So "not installed" is the EXPECTED state
today, and the tests pin that it is reported rather than hidden.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features import correlation_engine  # noqa: E402
from syndicate.features.shared import correlation_wiring  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_registry():
    correlation_engine.register_measured_correlation_resolver(None)
    yield
    correlation_engine.register_measured_correlation_resolver(None)


# --- it never raises ---------------------------------------------------------


def test_a_missing_date_does_not_raise_and_says_why():
    report = correlation_wiring.install_measured_correlation("")
    assert report["installed"] is False
    assert report["error"] == "no_date"


def test_a_date_with_no_artifact_degrades_quietly_to_the_heuristic():
    """Today's expected state. It must not raise, and it must NOT install."""
    report = correlation_wiring.install_measured_correlation("1999-01-01")
    assert report["installed"] is False
    assert correlation_engine.measured_correlation_resolver() is None


def test_a_resolver_that_explodes_is_reported_not_propagated(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("artifact tree unreadable")

    monkeypatch.setattr(
        "syndicate.features.mlb.sim_joint_correlation.build_measured_lookup", _boom
    )
    report = correlation_wiring.install_measured_correlation("2026-09-04")
    assert report["installed"] is False
    assert "RuntimeError" in str(report["error"])


# --- off != on ---------------------------------------------------------------


def test_it_INSTALLS_when_a_joint_exists(monkeypatch):
    """The reachability half. With a joint present, the registry must hold the
    resolver and `compute_correlation` must reach it with NO caller change."""

    class _Index:
        games_with_joint = 3
        reasons = {"ok": 3}

    monkeypatch.setattr(
        "syndicate.features.mlb.sim_joint_correlation.build_measured_lookup",
        lambda date_str, **k: ((lambda a, b: -0.42), _Index()),
    )
    report = correlation_wiring.install_measured_correlation("2026-09-04")
    assert report["installed"] is True
    assert report["games_with_joint"] == 3
    assert correlation_engine.measured_correlation_resolver() is not None

    got = correlation_engine.compute_correlation(
        {"sport": "mlb", "game_key": "g", "subject": "A", "market": "home_runs"},
        {"sport": "mlb", "game_key": "g", "subject": "A", "market": "total_bases"},
    )
    assert got["correlation_score"] == -0.42
    assert got["correlation_basis"] == correlation_engine.CORRELATION_BASIS_MEASURED


def test_ZERO_games_with_joint_does_NOT_install(monkeypatch):
    """An artifact of the wrong vintage carries no `joint`. Installing a
    resolver that can only answer `None` would look identical to a working one
    while telling the sizer nothing."""

    class _Index:
        games_with_joint = 0
        reasons = {"joint_field_absent": 15}

    monkeypatch.setattr(
        "syndicate.features.mlb.sim_joint_correlation.build_measured_lookup",
        lambda date_str, **k: ((lambda a, b: None), _Index()),
    )
    report = correlation_wiring.install_measured_correlation("2026-09-04")
    assert report["installed"] is False
    assert report["error"] == "no_joint_in_any_artifact"
    assert report["reasons"] == {"joint_field_absent": 15}
    assert correlation_engine.measured_correlation_resolver() is None


@pytest.mark.parametrize("date_str", ["", "1999-01-01"])
def test_a_failed_install_does_not_CLEAR_an_existing_resolver(date_str):
    """EVERY failure path, not just one. Clearing would be the same observable
    state reached by a different route, and it would stamp on a resolver another
    build installed.

    Parametrised because a mutation check exposed the single-date version as
    thin: injecting a `clear` into the `no_date` branch left it GREEN, since it
    only ever exercised the no-artifact branch.
    """
    correlation_engine.register_measured_correlation_resolver(lambda a, b: 0.5)
    report = correlation_wiring.install_measured_correlation(date_str)
    assert report["installed"] is False
    assert correlation_engine.measured_correlation_resolver() is not None


def test_a_RAISING_install_does_not_clear_either(monkeypatch):
    """The third failure path."""
    def _boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(
        "syndicate.features.mlb.sim_joint_correlation.build_measured_lookup", _boom
    )
    correlation_engine.register_measured_correlation_resolver(lambda a, b: 0.5)
    correlation_wiring.install_measured_correlation("2026-09-04")
    assert correlation_engine.measured_correlation_resolver() is not None


# --- the report is the instrument -------------------------------------------


def test_the_report_line_answers_is_it_live_without_a_second_query():
    line = correlation_wiring.format_report(
        {"installed": True, "date": "2026-09-04", "games_with_joint": 12,
         "reasons": {"ok": 12}, "error": None}
    )
    assert "installed=True" in line
    assert "games_with_joint=12" in line
    assert "2026-09-04" in line


def test_the_shortlist_builder_CALLS_the_installer():
    """Reachability at the call site, by AST -- the module-level tests above all
    pass with the call deleted from `build_layer2_shortlist`, which is the exact
    inert-feature shape this whole phase keeps producing."""
    import ast

    src = (REPO_ROOT / "pipeline" / "layer2_shortlist.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "build_layer2_shortlist"
    )
    called = {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "install_measured_correlation" in called, sorted(called)
