"""Every profile field must survive the roster artifact.

WHY THIS EXISTS (2026-09-07). `roster_to_dict` serialises via an EXPLICIT dict
literal, not a `dataclasses.fields()` walk -- and its own comment warns that "a
new field that is not added here survives in memory and vanishes through the
artifact". `conditional_arsenal_source` did exactly that: `conditional_mix.py`
set it, `de_pitcher` read it back, and the serializer never wrote it. It was set
in memory, expected on load, and zero in every artifact -- invisible because the
default is `""` and nothing raised.

This test is the `dataclasses.fields()` walk the serializer is not. It sets each
field to a distinctive value, round-trips through the artifact, and fails if the
value does not come back.

It deliberately does NOT read the serializer's source to learn key types -- that
would re-break whenever the serializer is refactored. Instead each dict field is
probed with EVERY key shape the module supports, and is only reported lost when
NONE of them survives. That keeps the test about "is this field persisted at
all", which is the bug class, rather than about how it is encoded.
"""
from __future__ import annotations

import dataclasses
import enum
import pathlib
import sys

import pytest

_VENDOR = pathlib.Path(__file__).resolve().parents[1] / "vendor" / "mlb_bettingv2"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

sim_models = pytest.importorskip("sim_engine.models")
roster_artifact = pytest.importorskip("sim_engine.data.roster_artifact")

BatterProfile = sim_models.BatterProfile
Handedness = sim_models.Handedness
Lineup = sim_models.Lineup
ManagerProfile = sim_models.ManagerProfile
PitchType = sim_models.PitchType
PitcherProfile = sim_models.PitcherProfile
Player = sim_models.Player
Team = sim_models.Team
TeamRoster = sim_models.TeamRoster

roster_from_dict = roster_artifact.roster_from_dict
roster_to_dict = roster_artifact.roster_to_dict

# A field that is deliberately NOT persisted goes here, WITH a reason. Empty on
# purpose: as of 2026-09-07 all 69 probed fields round-trip. Adding a name here
# is a decision to let that field be recomputed per sim -- not a way to silence
# the test.
ALLOW_UNPERSISTED: dict[str, str] = {}

# Every key domain the serializer supports. A dict field is fine if ANY of these
# survives; it is lost only when all of them come back empty/changed.
_DICT_PROBES = (
    {PitchType.FF: 0.4242},          # _ser_pitchtype_map
    {1: 0.4242},                     # _ser_intkey_map
    {"LHB": 0.4242},                 # {str(k): float(v)}
    {1: {"a": 0.4242}},              # _ser_intkey_nested_map
    {"0-0": {PitchType.FF: 1.0}},    # conditional_arsenal
)


def _player(pid: int, name: str, pos: str) -> Player:
    return Player(
        mlbam_id=pid,
        full_name=name,
        primary_position=pos,
        bat_side=Handedness.R,
        throw_side=Handedness.R,
    )


def _roster(pitcher: PitcherProfile, batter: BatterProfile) -> TeamRoster:
    return TeamRoster(
        team=Team(team_id=147, name="Test", abbreviation="TST"),
        manager=ManagerProfile(),
        lineup=Lineup(batters=[batter], pitcher=pitcher),
    )


def _scalar_probe(current, name: str):
    """A distinctive value shaped like the field's default, or None to skip."""
    if isinstance(current, bool):
        return not current
    if isinstance(current, int):
        return 7
    if isinstance(current, float):
        return 0.4242
    if isinstance(current, str):
        return "PROBE_" + name
    return None


def _survives(field_name, value, build, pick) -> bool:
    """Set one field to `value`, round-trip, and report whether it came back."""
    obj = build()
    try:
        setattr(obj, field_name, value)
    except Exception:
        return True  # not settable -- not this test's concern
    other = _player(2, "Other", "1B")
    if isinstance(obj, PitcherProfile):
        roster = _roster(obj, BatterProfile(player=other))
    else:
        roster = _roster(PitcherProfile(player=other), obj)
    try:
        restored = pick(roster_from_dict(roster_to_dict(roster)))
    except Exception:
        # A wrong-SHAPED probe can raise inside the serializer -- e.g. a flat
        # {PitchType: float} fed to `conditional_arsenal`, whose serializer maps
        # `_ser_pitchtype_map` over the INNER values. That means "this key shape
        # is not this field's shape", not "this field is broken", so it counts
        # as this probe failing and the remaining shapes are still tried. A
        # scalar field has exactly one shape, so a raise there still reports it
        # lost -- which is the correct verdict.
        return False
    return getattr(restored, field_name, "<<missing>>") == value


def _lost_fields(build, pick) -> list[str]:
    lost = []
    for field in dataclasses.fields(build()):
        if field.name == "player" or field.name in ALLOW_UNPERSISTED:
            continue
        current = getattr(build(), field.name, None)
        if current is None or isinstance(current, enum.Enum):
            continue
        if isinstance(current, dict):
            if not any(_survives(field.name, p, build, pick) for p in _DICT_PROBES):
                lost.append(field.name)
            continue
        if isinstance(current, (list, tuple, set)):
            continue
        probe = _scalar_probe(current, field.name)
        if probe is None:
            continue
        if not _survives(field.name, probe, build, pick):
            lost.append(field.name)
    return sorted(lost)


def test_pitcher_profile_fields_survive_the_artifact():
    lost = _lost_fields(
        lambda: PitcherProfile(player=_player(1, "Test Pitcher", "P")),
        lambda roster: roster.lineup.pitcher,
    )
    assert not lost, (
        "PitcherProfile field(s) set in memory but LOST through the roster "
        f"artifact: {lost}. roster_to_dict serialises an explicit list -- add "
        "the field there, or document it in ALLOW_UNPERSISTED with a reason."
    )


def test_batter_profile_fields_survive_the_artifact():
    lost = _lost_fields(
        lambda: BatterProfile(player=_player(2, "Test Batter", "1B")),
        lambda roster: roster.lineup.batters[0],
    )
    assert not lost, (
        "BatterProfile field(s) set in memory but LOST through the roster "
        f"artifact: {lost}. roster_to_dict serialises an explicit list -- add "
        "the field there, or document it in ALLOW_UNPERSISTED with a reason."
    )


def test_conditional_arsenal_source_specifically_round_trips():
    """The 2026-09-07 regression, pinned by name.

    `conditional_mix.py` sets `conditional_arsenal` and `conditional_arsenal_source`
    together, so the pair is the thing that must survive -- a source string with
    no arsenal beside it is the shape of a half-applied fix.
    """
    pitcher = PitcherProfile(player=_player(1, "Test Pitcher", "P"))
    pitcher.conditional_arsenal = {"0-0": {PitchType.FF: 0.6, PitchType.SL: 0.4}}
    pitcher.conditional_arsenal_source = "statcast_conditional_mix"

    roster = _roster(pitcher, BatterProfile(player=_player(2, "Test Batter", "1B")))
    payload = roster_to_dict(roster)

    assert "conditional_arsenal_source" in payload["lineup"]["pitcher"], (
        "conditional_arsenal_source is missing from the SERIALISED dict -- this "
        "is the exact write-side omission that made the field read 0.0% in "
        "production while being set in memory."
    )

    restored = roster_from_dict(payload).lineup.pitcher
    assert restored.conditional_arsenal_source == "statcast_conditional_mix"
    assert restored.conditional_arsenal, "arsenal lost while its source survived"
