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
    KNOWN_OPEN,
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


def test_r2_fires_for_a_pregame_carried_producer_added_to_the_gameline_gate():
    """`#340`: a pregame probability published under a live label.

    THIS TEST USED TO KEY OFF `nfl`'s REAL DECLARATION, and that was wrong in a
    way worth recording. `nfl/live_lens.py` genuinely is pregame-carried and
    says so -- but it is the LENS PAGE builder, not the sport's live tier.
    `nfl/live_resim.py` is, so nfl's declaration is `live_resim` and this test
    can no longer borrow it. The rule is unchanged; only my example was wrong.
    """
    declarations = dict(_MLB_OK)
    declarations["carried"] = Declaration(
        gameline=PREGAME_CARRIED, props=PROPS_NONE,
        evidence="synthetic: a lens that overlays live score onto a pregame number",
    )

    clean = evaluate(_registries(lens={"mlb", "carried"}), declarations)
    assert "R2_PREGAME_UNDER_LIVE_LABEL" not in _rules(clean), (
        "a pregame-carried producer is fine while it stays out of the gate"
    )

    wired = evaluate(
        _registries(lens={"mlb", "carried"}, gameline={"mlb", "carried"}), declarations
    )
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


def test_real_tree_failures_are_exactly_the_known_open_defects():
    try:
        reg = load_registries()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"registries unavailable in this tree: {exc!r}")
    actual = {(f.rule, f.sport) for f in evaluate(reg, DECLARATIONS) if f.level == "FAIL"}
    assert actual == set(KNOWN_OPEN), (
        f"unexpected: {sorted(actual - set(KNOWN_OPEN))} | fixed (remove the waiver): "
        f"{sorted(set(KNOWN_OPEN) - actual)}"
    )


def test_r8_does_not_fire_for_nhl_which_registers_its_own_resim_resolver():
    """The false positive caught on R8's first run, pinned so it cannot return.

    `nhl` publishes to the same path from the lens loop AND from
    `nhl/live_resim.py` -- but they are the SAME FUNCTION, imported as an alias.
    One producer. Flagging it would be a row that is correct as-is, which this
    lane's falsification criterion forbids.
    """
    try:
        reg = load_registries()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"registries unavailable in this tree: {exc!r}")
    offenders = {f.sport for f in evaluate(reg, DECLARATIONS)
                 if f.rule == "R8_SNAPSHOT_PATH_COLLISION"}
    assert "nhl" not in offenders


def test_r8_fires_where_two_distinct_producers_share_a_path(monkeypatch):
    """R8 must stay REACHABLE now that no real sport collides.

    It fired on `nfl` until 2026-09-24, when lane `nfl-live-resim-activation`
    gave the re-sim its own `nfl_live_resim.json`. With the real collision gone,
    asserting against the live tree would only prove the rule is quiet -- which
    is indistinguishable from a rule that stopped working. So the two producers
    are simulated instead, and `_loop_resolver_is_the_resim` is forced False to
    say they are genuinely distinct rather than one function under two names.
    """
    import scripts.live_tier_coverage_check as mod

    shared = "/opt/render/project/data/live/collide_live_lens.json"
    monkeypatch.setattr(mod, "loop_snapshot_path", lambda sport: shared)
    monkeypatch.setattr(mod, "resim_snapshot_path", lambda sport: shared)
    monkeypatch.setattr(mod, "_loop_resolver_is_the_resim", lambda sport: False)

    findings = evaluate(_registries(), _MLB_OK)
    assert "R8_SNAPSHOT_PATH_COLLISION" in _rules(findings)


def test_r8_is_silent_when_one_producer_wears_two_names(monkeypatch):
    """Same path, same function: one producer. This is `nhl`'s real shape."""
    import scripts.live_tier_coverage_check as mod

    shared = "/opt/render/project/data/live/mlb_live_lens.json"
    monkeypatch.setattr(mod, "loop_snapshot_path", lambda sport: shared)
    monkeypatch.setattr(mod, "resim_snapshot_path", lambda sport: shared)
    monkeypatch.setattr(mod, "_loop_resolver_is_the_resim", lambda sport: True)

    findings = evaluate(_registries(), _MLB_OK)
    assert "R8_SNAPSHOT_PATH_COLLISION" not in _rules(findings)


def test_every_waiver_names_an_owning_lane():
    """A waiver with no owner is an unfixed defect wearing a fixed one's costume."""
    for key, reason in KNOWN_OPEN.items():
        assert "lane `" in reason, f"{key} is waived with no owning lane"


def test_the_waived_findings_are_exactly_the_ones_that_still_fire():
    """The rot-check, from the other side: no waiver may outlive its fix.

    `main()` turns a stale waiver into R0_STALE_WAIVER and a non-zero exit. This
    asserts the same invariant at the unit level so the failure is attributable
    to a rule rather than to a gate run.
    """
    try:
        reg = load_registries()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"registries unavailable in this tree: {exc!r}")
    fired = {(f.rule, f.sport) for f in evaluate(reg, DECLARATIONS) if f.level == "FAIL"}
    stale = sorted(set(KNOWN_OPEN) - fired)
    assert not stale, f"waived but no longer firing -- delete these: {stale}"
