"""Settlers for the Layer 2 priced population BEYOND `bucket_search`'s own grading.

Lane `model-scorecard-cron` `[2026-09-17, user: "lets get a plan together and execute it
ASAP" -- a scheduled scorecard for game lines AND props, pregame AND live]`.

`scripts/bucket_search.py::grade_population` grades full-game h2h / spreads / totals from
final scores and MLB props from statsapi box scores, and counts everything else ungraded.
Measured on the 2026-09-15/16 production records that left ungraded: every non-MLB prop
(NFL 2,621, NCAAF 2,558, soccer 16,607), every segment row, and the alternate / 3-way
markets. Each sport's settler lives in its own module:

    population_outcomes_mlb      segments first1/3/5, alt and 3-way markets (statsapi)
    population_outcomes_soccer   scorer / shots / assists props, h1, corners (live_state)
    population_outcomes_espn     NFL, NCAAF, WNBA props and period segments (ESPN)

`build_extra_settler` composes whichever are importable into ONE `extra_settler(shaped,
view)` for `grade_population`: the first settler that HANDLES a record decides it, and a
record none handles takes `grade_population`'s existing path unchanged.

A SETTLER THAT RAISES IS COUNTED, NEVER SWALLOWED INTO A RESULT. It returns
`(None, "<name>_error")`, so the failure is an ungraded reason in the published scorecard
instead of a crashed cron or -- worse -- a record quietly passed to the old path and
counted as something it is not.
"""

from __future__ import annotations

import collections
import importlib
import inspect
from collections.abc import Callable, Mapping
from typing import Any

SETTLER_MODULES: tuple[tuple[str, str, str], ...] = (
    ("mlb", "syndicate.features.shared.population_outcomes_mlb", "MlbPopulationSettler"),
    ("soccer", "syndicate.features.shared.population_outcomes_soccer", "SoccerPopulationSettler"),
    ("espn", "syndicate.features.shared.population_outcomes_espn", "EspnPopulationSettler"),
)


class CompositeSettler:
    """First settler that handles a record decides it. Counts what each one did."""

    def __init__(self, settlers: list[tuple[str, Callable[..., Any], str]], unavailable: Mapping[str, str] | None = None):
        self.settlers = list(settlers)
        self.unavailable = dict(unavailable or {})
        self.handled: collections.Counter[str] = collections.Counter()
        self.errors: collections.Counter[str] = collections.Counter()
        self.first_error: dict[str, str] = {}

    @property
    def versions(self) -> dict[str, str]:
        return {name: version for name, _settler, version in self.settlers}

    def __call__(self, shaped: Mapping[str, Any], view: Mapping[str, Any]) -> tuple[str | None, str | None] | None:
        for name, settler, _version in self.settlers:
            try:
                handled = settler(shaped, view)
            except Exception as exc:  # counted and named, see the module docstring
                self.errors[name] += 1
                self.first_error.setdefault(name, f"{type(exc).__name__}: {exc}"[:300])
                return None, f"{name}_error"
            if handled is not None:
                self.handled[name] += 1
                return handled
        return None

    def report(self) -> dict[str, Any]:
        return {
            "versions": self.versions,
            "unavailable": self.unavailable,
            "handled": dict(self.handled),
            "errors": dict(self.errors),
            "first_error": dict(self.first_error),
        }


def build_extra_settler(**resources: Any) -> CompositeSettler:
    """Every importable sport settler, constructed with the resources its signature accepts.

    `resources` may carry `fetch_json`, `fetch_export`, `cache_dir` -- each settler takes the
    subset its `__init__` names, so the modules can grow independently.
    """
    settlers: list[tuple[str, Callable[..., Any], str]] = []
    unavailable: dict[str, str] = {}
    for name, module_name, class_name in SETTLER_MODULES:
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name)
        except Exception as exc:
            unavailable[name] = f"{type(exc).__name__}: {exc}"[:200]
            continue
        accepted = inspect.signature(cls.__init__).parameters
        kwargs = {key: value for key, value in resources.items() if key in accepted and value is not None}
        try:
            instance = cls(**kwargs)
        except Exception as exc:
            unavailable[name] = f"init {type(exc).__name__}: {exc}"[:200]
            continue
        settlers.append((name, instance, str(getattr(module, "GRADER_VERSION", "unversioned"))))
    return CompositeSettler(settlers, unavailable)
