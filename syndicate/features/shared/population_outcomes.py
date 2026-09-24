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
    population_outcomes_nhl      NHL game lines incl. OT/shootout, periods, player props (api-web.nhle.com)

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

# (name, module, class, sports it settles). The SPORTS column is what lets the scorecard reset
# ONE sport's history when that sport's settler changes, instead of every sport's.
SETTLER_MODULES: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
    ("mlb", "syndicate.features.shared.population_outcomes_mlb", "MlbPopulationSettler", ("mlb",)),
    ("soccer", "syndicate.features.shared.population_outcomes_soccer", "SoccerPopulationSettler", ("soccer",)),
    # `nba` added 2026-09-20 (lane `daily-accuracy-suite`); `ncaab` added 2026-09-23 (lane
    # `nhl-ncaab-club-maps`) once its one documented blocker -- no team registry -- was cleared
    # by `ncaab_team_registry.csv`. The reasoning lives at `population_outcomes_espn.HANDLED_SPORTS`.
    #
    # THIS TUPLE AND `HANDLED_SPORTS` ARE TWO LISTS NAMING ONE FACT, and they are read by
    # different things: the settler decides what it GRADES from `HANDLED_SPORTS`, while
    # `sport_versions` -- what the scorecard stamps itself with -- is built from the column
    # here. Moving one alone does not fail loudly; it produces a sport that is graded and not
    # advertised (or advertised and not graded), which reads as a quiet coverage change.
    # `tests/test_population_outcomes_basketball.py` pins them in agreement.
    ("espn", "syndicate.features.shared.population_outcomes_espn", "EspnPopulationSettler", ("nfl", "ncaaf", "wnba", "nba", "ncaab")),
    ("nhl", "syndicate.features.shared.population_outcomes_nhl", "NhlPopulationSettler", ("nhl",)),
)


class CompositeSettler:
    """First settler that handles a record decides it. Counts what each one did."""

    def __init__(self, settlers: list[tuple[str, Callable[..., Any], str]], unavailable: Mapping[str, str] | None = None,
                 sports: Mapping[str, tuple[str, ...]] | None = None):
        self.settlers = list(settlers)
        self.unavailable = dict(unavailable or {})
        self.sports = {name: tuple(values) for name, values in (sports or {}).items()}
        self.handled: collections.Counter[str] = collections.Counter()
        self.errors: collections.Counter[str] = collections.Counter()
        self.first_error: dict[str, str] = {}

    @property
    def versions(self) -> dict[str, str]:
        return {name: version for name, _settler, version in self.settlers}

    @property
    def sport_versions(self) -> dict[str, str]:
        """sport -> the version of the settler that owns it, or `unavailable:<name>`."""
        out: dict[str, str] = {}
        available = self.versions
        for name, sports in self.sports.items():
            version = available.get(name, f"unavailable:{name}")
            for sport in sports:
                out[sport] = version
        return out

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
    for name, module_name, class_name, _sports in SETTLER_MODULES:
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
    return CompositeSettler(settlers, unavailable, {name: sports for name, _m, _c, sports in SETTLER_MODULES})
