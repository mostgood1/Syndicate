"""The sim engine's serializer caches each dataclass TYPE's field names.

`_serialize` used to call `dataclasses.fields(value)` once per VALUE, which on a
live tick is ~100k calls per in-play match, and `fields()` raised
`SystemError: Objects/tupleobject.c:927: bad argument to internal function`
eight times on live-odds-worker between 2026-09-13 and 2026-09-20, each one
killing a whole league's poll for that tick. These tests pin the two things the
cache must not change (the serialized output) and the one thing it exists for
(the call is made once per TYPE).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from syndicate.features.soccer.sim_engine.soccersim import contracts
from syndicate.features.soccer.sim_engine.soccersim.contracts import SoccerSimSimulationInput
from syndicate.features.soccer.sim_engine.soccersim.match_simulator import simulate_match

MODULE_PATH = "syndicate/features/soccer/sim_engine/soccersim/contracts.py"


def _pre_change_module():
    """origin/main's OWN contracts.py, loaded as a separate module.

    The golden has to come from the code being replaced, not from a copy of it
    written by hand here -- a hand-written expectation only proves this file
    agrees with itself.
    """
    src = subprocess.run(
        ["git", "show", f"origin/main:{MODULE_PATH}"],
        capture_output=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    ).stdout
    assert src, "could not read origin/main's contracts.py"
    path = Path(tempfile.mkdtemp()) / "contracts_pre_change.py"
    path.write_bytes(src)
    spec = importlib.util.spec_from_file_location("contracts_pre_change", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["contracts_pre_change"] = module          # dataclasses resolve their own module
    spec.loader.exec_module(module)
    return module


class Colour(str, Enum):
    RED = "red"


@dataclass(frozen=True)
class Leaf:
    name: str
    score: float


@dataclass(frozen=True)
class Nest:
    leaf: Leaf
    colour: Colour
    tagged: dict[str, Leaf]
    steps: tuple[Leaf, ...]
    history: list[Leaf] = field(default_factory=list)
    nothing: Any = None


class SerializeFieldCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pre = _pre_change_module()
        contracts._FIELD_NAMES.clear()

    def tearDown(self) -> None:
        contracts._FIELD_NAMES.clear()

    # --- the output must not move ------------------------------------------

    def test_whole_match_serializes_exactly_as_before(self) -> None:
        """The hot path is INSIDE the simulation, not at the end of it.

        `_run_half` calls `to_dict()` on every possession and every step as it
        goes, so by the time a match result exists its logs are already plain
        dicts. Serializing the finished result would exercise one call. This
        runs the whole simulation through origin/main's own `_serialize` and
        then through the new one, same seed, and compares the two dicts.
        """
        simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=11)

        real = contracts._serialize
        contracts._serialize = self.pre._serialize
        try:
            old = simulate_match(simulation_input).to_dict()
        finally:
            contracts._serialize = real

        new = simulate_match(simulation_input).to_dict()

        self.assertEqual(new, old)
        self.assertGreaterEqual(len(new["possession_log"]), 1)
        self.assertGreaterEqual(len(new["event_log"]), 1)

    def test_nested_shapes_serialize_exactly_as_before(self) -> None:
        value = Nest(
            leaf=Leaf(name="a", score=1.5),
            colour=Colour.RED,
            tagged={"k": Leaf(name="b", score=-0.25)},
            steps=(Leaf(name="c", score=0.0),),
            history=[Leaf(name="d", score=9.75)],
        )

        self.assertEqual(contracts._serialize(value), self.pre._serialize(value))

    def test_two_instances_of_one_type_keep_their_own_values(self) -> None:
        """A cache keyed on anything but the TYPE would serve the first one twice."""
        first = contracts._serialize(Leaf(name="a", score=1.0))
        second = contracts._serialize(Leaf(name="b", score=2.0))

        self.assertEqual(first, {"name": "a", "score": 1.0})
        self.assertEqual(second, {"name": "b", "score": 2.0})

    # --- the reason the cache exists ---------------------------------------

    def test_fields_is_called_once_per_type_and_not_again(self) -> None:
        real = contracts.fields
        calls: list[Any] = []

        def counting(cls_or_instance):
            calls.append(cls_or_instance)
            return real(cls_or_instance)

        contracts.fields = counting
        try:
            simulation_input = SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=11)
            simulate_match(simulation_input).to_dict()
            first_pass = len(calls)
            cached_types = len(contracts._FIELD_NAMES)

            simulate_match(simulation_input).to_dict()
            second_pass = len(calls) - first_pass
        finally:
            contracts.fields = real

        # One call per distinct dataclass TYPE, and a whole second match adds none.
        self.assertEqual(first_pass, cached_types)
        self.assertEqual(second_pass, 0)
        self.assertGreater(cached_types, 0)
        # The old code called it once per VALUE: a match serializes far more than
        # a dozen objects, so this is the bound that would fail before the fix.
        self.assertLess(first_pass, 50)

    def test_without_the_cache_fields_is_called_per_value(self) -> None:
        """The falsification: with storing disabled, the same match makes the
        pre-change volume of calls. If it did not, the calls this fix removes
        would not be on this code path at all.
        """

        class _NeverStores(dict):
            def __setitem__(self, key, value):  # noqa: D401 - a cache that forgets
                return None

        real_fields = contracts.fields
        real_cache = contracts._FIELD_NAMES
        calls: list[Any] = []

        def counting(cls_or_instance):
            calls.append(cls_or_instance)
            return real_fields(cls_or_instance)

        contracts.fields = counting
        contracts._FIELD_NAMES = _NeverStores()
        try:
            simulate_match(SoccerSimSimulationInput(home_team="ARS", away_team="LIV", seed=11)).to_dict()
        finally:
            contracts.fields = real_fields
            contracts._FIELD_NAMES = real_cache

        self.assertGreater(len(calls), 500)

if __name__ == "__main__":
    unittest.main()
