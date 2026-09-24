"""`#688` -- REACHABILITY BEFORE CORRECTNESS.

`live_tier_coverage_check` exits 0 on today's tree. A guard that has never been
seen to fail is indistinguishable from a guard that cannot fail, and this repo
has shipped four inert fixes in one session on exactly that confusion
(`learnings.md`, `presence is not reachability`). So every rule below is proved
to FIRE on a synthetic bad config before any of them is trusted to pass.

The `R2` test is not generic: it reconstructs the specific mistake of
2026-09-24, where `nfl` -- whose lens is pregame-carried by its own docstring --
was recommended for board wiring. That recommendation would have shipped `#340`,
and this test is the thing that makes it impossible to repeat silently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.live_tier_coverage_check import (  # noqa: E402
    DECLARATIONS,
    LIVE_PROJECTION,
    LIVE_RESIM,
    NONE,
    PREGAME_CARRIED,
    PROPS_ABSENT,
    PROPS_NONE,
    PROPS_WIRED,
    Declaration,
    Registries,
    evaluate,
    load_registries,
)


def _registries(**overrides) -> Registries:
    """A consistent baseline, so a test's single override is what fires a rule."""
    base = dict(
        lens=frozenset({"mlb"}),
        builders=frozenset({"mlb"}),
        validators=frozenset({"mlb"}),
        snapshot_paths=frozenset({"mlb"}),
        props=frozenset({"mlb"}),
        gameline=frozenset({"mlb"}),
        sources=frozenset({"mlb"}),
        allowlisted=frozenset({"mlb"}),
    )
    base.update({k: frozenset(v) for k, v in overrides.items()})
    return Registries(**base)


_MLB_OK = {
    "mlb": Declaration(gameline=LIVE_RESIM, props=PROPS_WIRED, evidence="test baseline"),
}


def _rules(findings, level="FAIL") -> set[str]:
    return {f.rule for f in findings if f.level == level}


# --------------------------------------------------------------- the baseline

def test_baseline_is_clean_so_a_firing_rule_is_attributable():
    # If this ever fails, every other test in the file is measuring two things.
    assert _rules(evaluate(_registries(), _MLB_OK)) == set()


# ------------------------------------------------------------- rules must fire

def test_r1_fires_when_a_registry_names_an_undeclared_sport():
    findings = evaluate(_registries(gameline={"mlb", "ncaab"}), _MLB_OK)
    assert "R1_UNDECLARED" in _rules(findings)


def test_r2_fires_for_the_real_nfl_declaration_added_to_the_gameline_gate():
    # THE 2026-09-24 MISTAKE, reconstructed from the REAL declaration rather
    # than a synthetic one, so the test tracks the actual nfl row.
    declarations = dict(_MLB_OK)
    declarations["nfl"] = DECLARATIONS["nfl"]
    assert declarations["nfl"].gameline == PREGAME_CARRIED

    clean = evaluate(_registries(lens={"mlb", "nfl"}), declarations)
    assert "R2_PREGAME_UNDER_LIVE_LABEL" not in _rules(clean), (
        "nfl is correct as-is today: it ticks and is absent from the gate"
    )

    wired = evaluate(_registries(lens={"mlb", "nfl"}, gameline={"mlb", "nfl"}), declarations)
    assert "R2_PREGAME_UNDER_LIVE_LABEL" in _rules(wired)


def test_r2_fires_for_a_sport_declaring_no_gameline_probability():
    declarations = dict(_MLB_OK)
    declarations["nba"] = Declaration(gameline=NONE, props=PROPS_NONE, evidence="t")
    findings = evaluate(_registries(lens={"mlb", "nba"}, gameline={"mlb", "nba"}), declarations)
    assert "R2_PREGAME_UNDER_LIVE_LABEL" in _rules(findings)


def test_r3_fires_when_the_gate_is_open_and_nothing_produces():
    declarations = dict(_MLB_OK)
    declarations["ncaab"] = Declaration(gameline=LIVE_RESIM, props=PROPS_NONE, evidence="t")
    findings = evaluate(_registries(gameline={"mlb", "ncaab"}), declarations)
    assert "R3_GATE_WITHOUT_PRODUCER" in _rules(findings)


def test_r3_is_silenced_by_a_declared_alternate_producer():
    # ncaaf and soccer are legitimately off the lens tick. Without this field
    # the rule would flag two correct rows, which is the false-positive half of
    # the lane's own falsification criterion.
    declarations = dict(_MLB_OK)
    declarations["ncaaf"] = Declaration(
        gameline=LIVE_RESIM, props=PROPS_NONE, evidence="t",
        alternate_producer="ncaaf/live_resim.py",
    )
    findings = evaluate(_registries(gameline={"mlb", "ncaaf"}, sources={"mlb", "ncaaf"}), declarations)
    assert "R3_GATE_WITHOUT_PRODUCER" not in _rules(findings)


def test_r4_fires_when_the_prop_gate_is_open_and_the_producer_is_absent():
    declarations = dict(_MLB_OK)
    declarations["wnba"] = Declaration(gameline=LIVE_PROJECTION, props=PROPS_ABSENT, evidence="t")
    findings = evaluate(
        _registries(lens={"mlb", "wnba"}, props={"mlb", "wnba"}, gameline={"mlb", "wnba"}),
        declarations,
    )
    assert "R4_PROP_GATE_WITHOUT_PRODUCER" in _rules(findings)


def test_r5_fires_on_lens_source_config_for_a_sport_the_board_never_joins():
    declarations = dict(_MLB_OK)
    declarations["nhl"] = Declaration(gameline=LIVE_RESIM, props=PROPS_NONE, evidence="t")
    findings = evaluate(
        _registries(lens={"mlb", "nhl"}, sources={"mlb", "nhl"}, gameline={"mlb"}),
        declarations,
    )
    assert "R5_SOURCES_WITHOUT_GATE" in _rules(findings)


def test_r6_fires_on_a_live_producer_the_board_never_reads():
    # NHL's actual state for most of 2026-09-24: a working re-sim, inert.
    declarations = dict(_MLB_OK)
    declarations["nhl"] = Declaration(gameline=LIVE_RESIM, props=PROPS_NONE, evidence="t")
    findings = evaluate(
        _registries(lens={"mlb", "nhl"}, gameline={"mlb"}, sources={"mlb"}),
        declarations,
    )
    assert "R6_LIVE_PRODUCER_WITHOUT_GATE" in _rules(findings)


def test_r7_fires_when_the_three_lens_registries_disagree():
    findings = evaluate(_registries(builders={"mlb", "nhl"}), _MLB_OK)
    assert "R7_LENS_REGISTRY_SKEW" in _rules(findings)


# ------------------------------------------------------- the allowlist is INFO

def test_allowlist_without_builder_is_info_and_never_fails_the_run():
    # Encoding the allowlist as a hard rule is exactly the belief that produced
    # the wrong recommendation. It must stay visible and unscored.
    declarations = dict(_MLB_OK)
    declarations["nba"] = Declaration(gameline=NONE, props=PROPS_NONE, evidence="t")
    findings = evaluate(
        _registries(lens={"mlb"}, builders={"mlb"}, validators={"mlb"},
                    snapshot_paths={"mlb"}, allowlisted={"mlb", "nba"}),
        declarations,
    )
    assert "I1_ALLOWLIST_WITHOUT_BUILDER" in _rules(findings, level="INFO")
    assert _rules(findings) == set()


# --------------------------------------------------------- against the real tree

def test_every_sport_in_a_real_registry_is_declared():
    """The gate itself: no sport may be wired without stating what it publishes."""
    try:
        reg = load_registries()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"registries unavailable in this tree: {exc!r}")
    in_any = (reg.lens | reg.builders | reg.validators | reg.snapshot_paths
              | reg.props | reg.gameline | reg.sources | reg.allowlisted)
    assert in_any <= set(DECLARATIONS), sorted(in_any - set(DECLARATIONS))


def test_real_tree_has_no_failing_row():
    try:
        reg = load_registries()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"registries unavailable in this tree: {exc!r}")
    assert _rules(evaluate(reg, DECLARATIONS)) == set()


def test_every_declaration_carries_evidence():
    for sport, decl in DECLARATIONS.items():
        assert decl.evidence.strip(), f"{sport} declares provenance with no evidence"
