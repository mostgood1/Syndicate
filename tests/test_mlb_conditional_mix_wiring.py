"""The conditional mix must actually REACH production's roster build. `#440`.

REACHABILITY BEFORE CORRECTNESS. The engine standard requires an `off != on`
test for anything behind a flag, and this lane is why: `conditional_arsenal`
was declared in `models.py`, serialised by `roster_artifact.py`, and populatable
by `conditional_mix.py` -- and NOTHING IN THE BUILD PATH CALLED IT. Production's
`sim_input_report` read `conditional_arsenal 0.0%` on 2026-08-19 AND 2026-08-20
while the artifact was published and reachable the whole time. Every unit test
passed. A neutral default ({}) is indistinguishable from a working feature at
every level except the data.

These tests drive the REAL `apply_conditional_mix_to_rosters`, not a
reimplementation of its loop. A hand-rolled copy would pass while production
shipped the opposite -- the failure mode that nearly landed an INVERTED
roster-rebuild gate in this same lane.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
VENDOR = REPO / "vendor" / "mlb_bettingv2"
for pth in (str(REPO), str(VENDOR)):
    if pth not in sys.path:
        sys.path.insert(0, pth)


class _Player:
    def __init__(self, mlbam_id: int):
        self.mlbam_id = mlbam_id


class _Pitcher:
    """Stand-in carrying only what the consumer touches."""

    def __init__(self, mlbam_id: int):
        self.player = _Player(mlbam_id)
        self.conditional_arsenal: dict = {}
        self.count_bucket_map: dict = {}


class _Lineup:
    def __init__(self, pitcher, bullpen=None):
        self.pitcher = pitcher
        self.bullpen = list(bullpen or [])


class _Roster:
    def __init__(self, lineup):
        self.lineup = lineup


def _load_helper():
    """Import the REAL helper out of daily_update.py.

    daily_update.py is enormous and importing it wholesale drags in the vendor
    world, so the function is extracted by exec-ing just its source. It is still
    the SHIPPED source -- read from the file at test time, not copied here, so
    editing production without editing this test cannot leave it green.
    """
    import ast

    src = (VENDOR / "tools" / "daily_update.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    node = next(
        (n for n in tree.body
         if isinstance(n, ast.FunctionDef) and n.name == "apply_conditional_mix_to_rosters"),
        None,
    )
    assert node is not None, (
        "apply_conditional_mix_to_rosters is GONE from daily_update.py -- the "
        "conditional mix is unwired again and production will silently return "
        "to conditional_arsenal 0.0%"
    )
    mod = types.ModuleType("_du_extract")
    mod.__dict__["os"] = __import__("os")
    exec(compile(ast.Module(body=[node], type_ignores=[]), "<daily_update>", "exec"), mod.__dict__)
    return mod.apply_conditional_mix_to_rosters


@pytest.fixture()
def fake_artifact(monkeypatch):
    """Make the consumer's artifact load deterministic and non-empty."""
    import sim_engine.data.conditional_mix as cm

    art = {
        "pitchers": {"605488": {"ahead|R": {"FF": 0.6, "SL": 0.4}}},
        "count_to_bucket": {"0-2": "ahead", "1-2": "ahead"},
    }
    monkeypatch.setattr(cm, "load_conditional_mix", lambda season: art)
    return art


def test_on_populates_the_fields(fake_artifact):
    """The ON arm must actually write the fields the sim reads."""
    fn = _load_helper()
    pr = _Pitcher(605488)
    roster = _Roster(_Lineup(pr))

    applied = fn(roster, season=2026)

    assert applied == 1, "the covered pitcher was not counted as applied"
    assert pr.conditional_arsenal, "conditional_arsenal is STILL EMPTY -- exactly the production bug"
    assert pr.count_bucket_map, "count_bucket_map is still empty"
    assert pytest.approx(sum(pr.conditional_arsenal["ahead|R"].values()), rel=1e-6) == 1.0


def test_off_does_not(fake_artifact, monkeypatch):
    """OFF != ON. Without this the ON arm proves nothing: a field that is
    populated by something ELSE would make the test green with the wiring
    removed."""
    fn = _load_helper()
    monkeypatch.setenv("SYNDICATE_MLB_CONDITIONAL_MIX", "off")
    pr = _Pitcher(605488)

    applied = fn(_Roster(_Lineup(pr)), season=2026)

    assert applied == 0
    assert pr.conditional_arsenal == {}, "the kill switch did not actually stop it"


def test_bullpen_is_covered_not_just_the_starter(fake_artifact):
    """The starter is the easy case; a bullpen arm throws in the same game."""
    fn = _load_helper()
    starter, reliever = _Pitcher(1), _Pitcher(605488)
    applied = fn(_Roster(_Lineup(starter, bullpen=[reliever])), season=2026)
    assert applied == 1, "the covered reliever was skipped -- bullpen not walked"
    assert reliever.conditional_arsenal


def test_uncovered_pitcher_is_not_fatal_and_not_counted(fake_artifact):
    fn = _load_helper()
    pr = _Pitcher(999999)  # not in the artifact
    assert fn(_Roster(_Lineup(pr)), season=2026) == 0
    assert pr.conditional_arsenal == {}


def test_absent_artifact_degrades_instead_of_losing_the_slate(monkeypatch):
    """An absent artifact must return 0, NOT raise. A raise here would take
    down the whole game build for a feature that is meant to be additive."""
    import sim_engine.data.conditional_mix as cm

    monkeypatch.setattr(cm, "load_conditional_mix", lambda season: {})
    fn = _load_helper()
    pr = _Pitcher(605488)
    assert fn(_Roster(_Lineup(pr)), season=2026) == 0
    assert pr.conditional_arsenal == {}


def test_the_production_call_site_still_exists():
    """The helper being correct is worthless if main() stopped calling it.

    This is the ONLY assertion here that reads the file as text, and it is
    deliberate: the bug being prevented is a MISSING CALL, which no amount of
    testing the function itself can catch.
    """
    src = (VENDOR / "tools" / "daily_update.py").read_text(encoding="utf-8")
    calls = src.count("apply_conditional_mix_to_rosters(")
    assert calls >= 2, (
        f"expected the definition plus at least one call site, found {calls} "
        "occurrences -- production may no longer invoke the conditional mix"
    )
