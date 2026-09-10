"""NCAAF registry: OddsAPI spellings that failed to resolve (2026-09-10).

Measured on production's `/api/board/layer2-shortlist` and `/api/portfolio/plan`:
7 of 142 NCAAF team names failed the registry, all UNKNOWN, none ambiguous, and
43 NCAAF orders read `ncaaf_team_not_in_registry_or_ambiguous`, a refusal that
never resolves with time. The rows below are copied from the real registry, so
these tests run without the mirrored data.
"""

from __future__ import annotations

import csv

import pytest

from syndicate.features.shared import ncaaf_team_registry

_COLUMNS = ["team_id", "canonical_team_name", "abbreviation", "aliases", "display_name", "school_name", "mascot_name"]
_ROWS = [
    ["2026", "App State", "APP", "app|app state|mountaineers", "App State", "App State", "Mountaineers"],
    ["2241", "Gardner-Webb", "GWEB", "gardner-webb|gweb|runnin' bulldogs", "Gardner-Webb", "Gardner-Webb", "Runnin' Bulldogs"],
    ["62", "Hawai'i", "HAW", "haw|hawaii|rainbow warriors", "Hawai'i", "Hawai'i", "Rainbow Warriors"],
    ["309", "Louisiana", "UL", "louisiana|ragin' cajuns|ul", "Louisiana", "Louisiana", "Ragin' Cajuns"],
    ["2348", "Louisiana Tech", "LT", "bulldogs|louisiana tech|lt", "Louisiana Tech", "Louisiana Tech", "Bulldogs"],
    ["113", "Massachusetts", "MASS", "mass|massachusetts|minutemen", "Massachusetts", "Massachusetts", "Minutemen"],
    ["379", "UMass Dartmouth", "MAS", "corsairs|mas|umass dartmouth", "UMass Dartmouth", "UMass Dartmouth", "Corsairs"],
    ["2534", "Sam Houston", "SHSU", "bearkats|sam houston|shsu", "Sam Houston", "Sam Houston", "Bearkats"],
    ["2572", "Southern Miss", "USM", "golden eagles|southern miss|usm", "Southern Miss", "Southern Miss", "Golden Eagles"],
    ["61", "Georgia", "UGA", "georgia|uga|bulldogs", "Georgia", "Georgia", "Bulldogs"],
]


@pytest.fixture
def registry(tmp_path, monkeypatch):
    def install(rows=_ROWS):
        path = tmp_path / "ncaaf_team_registry.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(_COLUMNS)
            writer.writerows(rows)
        monkeypatch.setattr(ncaaf_team_registry, "registry_path", lambda: path)
        ncaaf_team_registry.unambiguous_team_index.cache_clear()
        return ncaaf_team_registry.resolve_ncaaf_team_id

    yield install
    ncaaf_team_registry.unambiguous_team_index.cache_clear()


@pytest.mark.parametrize(
    "board_name, team_id",
    [
        # The seven names production's board and plan carried on 2026-09-10.
        ("Appalachian State Mountaineers", "2026"),
        ("Gardner-Webb Runnin Bulldogs", "2241"),
        ("Hawaii Rainbow Warriors", "62"),
        ("Louisiana Ragin Cajuns", "309"),
        ("Sam Houston State Bearkats", "2534"),
        ("Southern Mississippi Golden Eagles", "2572"),
        ("UMass Minutemen", "113"),
        # ESPN's `shortDisplayName` for Massachusetts, which also failed.
        ("UMass", "113"),
    ],
)
def test_the_seven_ODDSAPI_names_resolve_to_the_right_team(registry, board_name, team_id):
    assert registry()(board_name) == team_id


@pytest.mark.parametrize(
    "espn_name, team_id",
    [
        # What ESPN sends must still resolve, apostrophes included.
        ("Hawai'i Rainbow Warriors", "62"),
        ("Louisiana Ragin' Cajuns", "309"),
        ("Gardner-Webb Runnin' Bulldogs", "2241"),
        ("App State Mountaineers", "2026"),
        ("Massachusetts Minutemen", "113"),
        ("Hawai\u02bbi Rainbow Warriors", "62"),  # the okina
        ("Louisiana Ragin\u2019 Cajuns", "309"),  # a curly apostrophe
    ],
)
def test_the_ESPN_forms_still_resolve(registry, espn_name, team_id):
    assert registry()(espn_name) == team_id


def test_UMASS_DARTMOUTH_is_not_swallowed_by_the_umass_variant(registry):
    resolve = registry()
    assert resolve("UMass Dartmouth") == "379"
    assert resolve("UMass") == "113"


def test_LOUISIANA_TECH_is_not_louisiana(registry):
    resolve = registry()
    assert resolve("Louisiana Tech Bulldogs") == "2348"
    assert resolve("Louisiana Ragin Cajuns") == "309"


def test_a_variant_that_COLLIDES_is_dropped_not_picked(registry):
    # If another team also owned "umass", the key must refuse for both: the
    # supplement enters the same ambiguity-dropping index as every other key,
    # unlike the odds join, which lets it override.
    rows = _ROWS + [["999", "Other U", "OTH", "umass", "Other U", "Other U", "Owls"]]
    assert registry(rows)("UMass") is None
    assert registry(rows)("Massachusetts") == "113"


def test_a_bare_shared_mascot_still_refuses(registry):
    # "Bulldogs" is Louisiana Tech's AND Georgia's: the pre-existing refusal.
    assert registry()("Bulldogs") is None


def test_the_names_come_from_the_ODDS_JOINS_supplement_not_a_second_list(registry):
    # The long/short forms resolve BECAUSE `oddsapi_lines` lists them. Take the
    # supplement away and they must stop resolving: there is no second list.
    from syndicate.features.shared import ncaaf_team_registry as reg

    resolve = registry()
    assert resolve("Sam Houston State Bearkats") == "2534"
    original = reg._odds_name_supplement
    try:
        reg._odds_name_supplement = lambda: []
        reg.unambiguous_team_index.cache_clear()
        assert reg.resolve_ncaaf_team_id("Sam Houston State Bearkats") is None
        # The apostrophe half does not depend on it.
        assert reg.resolve_ncaaf_team_id("Hawaii Rainbow Warriors") == "62"
    finally:
        reg._odds_name_supplement = original
        reg.unambiguous_team_index.cache_clear()


def test_no_supplement_entry_ever_resolves_to_a_DIFFERENT_team():
    # Against the real registry: an entry may refuse (a collision), but it must
    # never land on a team other than the one it names.
    from syndicate.features.shared import ncaaf_team_registry as reg

    reg.unambiguous_team_index.cache_clear()
    if reg.registry_path() is None:
        pytest.skip("no mirrored registry in this checkout")
    rows = list(csv.DictReader(reg.registry_path().open(encoding="utf-8", newline="")))
    by_canonical = {}
    for row in rows:
        by_canonical.setdefault(reg._norm(row.get("canonical_team_name")), set()).add(reg._norm(row.get("team_id")))
    wrong = []
    for alias, canonical in reg._odds_name_supplement():
        got = reg.resolve_ncaaf_team_id(alias)
        if got is not None and got not in by_canonical.get(reg._norm(canonical), set()):
            wrong.append((alias, canonical, got))
    assert wrong == []


def test_the_real_registry_resolves_all_seven_when_it_is_present():
    ncaaf_team_registry.unambiguous_team_index.cache_clear()
    if ncaaf_team_registry.registry_path() is None:
        pytest.skip("no mirrored registry in this checkout")
    resolve = ncaaf_team_registry.resolve_ncaaf_team_id
    assert [resolve(n) for n in (
        "Appalachian State Mountaineers", "Gardner-Webb Runnin Bulldogs", "Hawaii Rainbow Warriors",
        "Louisiana Ragin Cajuns", "Sam Houston State Bearkats", "Southern Mississippi Golden Eagles",
        "UMass Minutemen",
    )] == ["2026", "2241", "62", "309", "2534", "2572", "113"]
