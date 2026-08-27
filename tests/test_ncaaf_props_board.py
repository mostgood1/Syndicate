"""NCAAF captured props -> the board's `shared_prop_rows`.

Pins the four things that were each individually capable of making this
feature look present and render nothing, all found while building it:

1. The allowlisted PATH. Writing the capture one directory shallower means it
   can never cross from the worker to web, and the failure is a silently empty
   panel rather than an error.
2. The NAME JOIN. Board team names are school-only ("TCU"); OddsAPI's carry
   the mascot ("TCU Horned Frogs"). An equality join matched 0 of 6 openers.
3. The PREFIX rule in that join. "North Carolina" is a prefix of "North
   Carolina State" and both teams are on this very slate, so containment
   would put UNC's props on an NC State card.
4. The ROW SHAPE. `_build_prop_rows` maps `value <- tier or line or price`,
   so a row whose `tier` holds a book count renders a player and a market with
   no number on it.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path
from syndicate.features.shared import game_board_contract as contract


ROSTER_ROWS = [
    {"player_name": "Benjamin Hall", "team_id": "2628", "season": "2025"},
    {"player_name": "Jordan Shipp", "team_id": "153", "season": "2025"},
    {"player_name": "Wolfpack Player", "team_id": "152", "season": "2025"},
    {"player_name": "Nobody Atall", "team_id": "9999", "season": "2025"},
]

REGISTRY_ROWS = [
    {"team_id": "2628", "school_name": "TCU", "canonical_team_name": "TCU", "display_name": "TCU", "abbreviation": "TCU", "mascot_name": "Horned Frogs"},
    {"team_id": "153", "school_name": "North Carolina", "canonical_team_name": "North Carolina", "display_name": "North Carolina", "abbreviation": "UNC", "mascot_name": "Tar Heels"},
    {"team_id": "152", "school_name": "North Carolina State", "canonical_team_name": "NC State", "display_name": "NC State", "abbreviation": "NCST", "mascot_name": "Wolfpack"},
]

PROP_ROWS = [
    # Same selection at three books, deliberately disagreeing.
    {"player": "Benjamin Hall", "market": "Anytime TD", "line": "", "over_price": "160", "under_price": "", "book": "draftkings", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"},
    {"player": "Benjamin Hall", "market": "Anytime TD", "line": "", "over_price": "185", "under_price": "", "book": "fanduel", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"},
    {"player": "Benjamin Hall", "market": "Anytime TD", "line": "", "over_price": "140", "under_price": "", "book": "bovada", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"},
    {"player": "Jordan Shipp", "market": "Receiving Yards", "line": "34.5", "over_price": "-110", "under_price": "-120", "book": "draftkings", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"},
    # On an NC State roster; must NOT appear on this card at all.
    {"player": "Wolfpack Player", "market": "Anytime TD", "line": "", "over_price": "300", "under_price": "", "book": "fanduel", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"},
    # Not on any roster of either team.
    {"player": "Nobody Atall", "market": "Anytime TD", "line": "", "over_price": "500", "under_price": "", "book": "fanduel", "home_team": "TCU Horned Frogs", "away_team": "North Carolina Tar Heels"},
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture()
def ncaaf_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path))
    processed = tmp_path / "source_artifacts" / "data" / "processed"
    _write_csv(processed / "roster" / "ncaaf_roster_snapshot.csv", ROSTER_ROWS)
    _write_csv(processed / "team_registry" / "ncaaf_team_registry_snapshot.csv", REGISTRY_ROWS)
    _write_csv(tmp_path / "data" / "processed" / "oddsapi_player_props_2026_wk1.csv", PROP_ROWS)

    from syndicate.features.ncaaf import props as ncaaf_props

    ncaaf_props.reset_caches()
    yield ncaaf_props
    ncaaf_props.reset_caches()


def test_capture_path_is_already_allowlisted():
    """The whole reason the file is written under `data/processed/`.

    One directory shallower and the capture cannot reach web at all, and it
    fails as an empty props panel rather than as an error.
    """
    assert is_hot_artifact_relative_path("ncaaf_source/data/processed/oddsapi_player_props_2026_wk1.csv")
    assert not is_hot_artifact_relative_path("ncaaf_source/data/oddsapi_player_props_2026_wk1.csv")
    assert not is_hot_artifact_relative_path("ncaaf_source/source_artifacts/oddsapi_player_props_2026_wk1.csv")


def test_sources_path_matches_the_allowlisted_shape(ncaaf_root, tmp_path):
    from syndicate.features.ncaaf.sources import ncaaf_player_props_path

    path = ncaaf_player_props_path(2026, 1)
    assert path.parent.name == "processed"
    assert path.name == "oddsapi_player_props_2026_wk1.csv"
    assert path.exists()


def test_board_names_join_to_oddsapi_names(ncaaf_root):
    """"TCU" must find "TCU Horned Frogs". Equality matched 0 of 6 openers."""
    recs = ncaaf_root.prop_recommendations_for_game(
        season=2026, week=1, home_team="TCU", away_team="North Carolina"
    )
    assert recs, "board names failed to join to the captured OddsAPI names"
    assert {r["player"] for r in recs["home"]} == {"Benjamin Hall"}
    assert {r["player"] for r in recs["away"]} == {"Jordan Shipp"}


def test_a_prefix_team_name_does_not_steal_the_other_teams_player(ncaaf_root):
    """NC State's player must not land on a North Carolina card."""
    recs = ncaaf_root.prop_recommendations_for_game(
        season=2026, week=1, home_team="TCU", away_team="North Carolina"
    )
    everyone = {row["player"] for side in recs.values() for row in side}
    assert "Wolfpack Player" not in everyone


def test_unattributable_players_are_dropped_not_guessed(ncaaf_root):
    recs = ncaaf_root.prop_recommendations_for_game(
        season=2026, week=1, home_team="TCU", away_team="North Carolina"
    )
    everyone = {row["player"] for side in recs.values() for row in side}
    assert "Nobody Atall" not in everyone

    rows = ncaaf_root._find_captured_game(
        ncaaf_root._rows_by_game(2026, 1), home_team="TCU", away_team="North Carolina"
    )
    _sides, diagnostics = ncaaf_root.build_game_props(rows, home_team="TCU", away_team="North Carolina")
    assert diagnostics["dropped_unattributed_players"] >= 1


def test_best_price_across_books_wins_and_names_the_book(ncaaf_root):
    """Price shopping is the point of keeping every bookmaker."""
    recs = ncaaf_root.prop_recommendations_for_game(
        season=2026, week=1, home_team="TCU", away_team="North Carolina"
    )
    hall = next(row for row in recs["home"] if row["player"] == "Benjamin Hall")
    assert hall["tier"] == "+185"
    assert hall["book"] == "fanduel"
    # TWO, not three. bovada quoted this selection at +140 and is filtered as
    # unbettable before the count is taken, so the card never advertises a
    # book count the reader cannot act on.
    assert "2 books" in hall["display_pick"]


def test_unbettable_books_are_excluded_by_default(ncaaf_root):
    """`bovada` is quoted here and is not a book the operator holds."""
    rows = ncaaf_root._find_captured_game(
        ncaaf_root._rows_by_game(2026, 1), home_team="TCU", away_team="North Carolina"
    )
    _sides, diagnostics = ncaaf_root.build_game_props(rows, home_team="TCU", away_team="North Carolina")
    assert diagnostics["dropped_unbettable_rows"] >= 1


def test_rows_survive_the_shared_board_contract_with_a_number_on_them(ncaaf_root):
    """The end of the pipe. `value` must not come out blank.

    `_build_prop_rows` maps `value <- tier or line or price`, which is why
    `tier` carries the price rather than the book count.
    """
    recs = ncaaf_root.prop_recommendations_for_game(
        season=2026, week=1, home_team="TCU", away_team="North Carolina"
    )
    game = {
        "home": {"abbr": "TCU", "name": "TCU"},
        "away": {"abbr": "UNC", "name": "North Carolina"},
        "prop_recommendations": recs,
        "panels": [],
    }
    rows = contract._build_prop_rows(game)
    assert rows, "prop_recommendations produced no shared_prop_rows"
    assert all(row["value"] not in ("", None, contract.NULL_PLACEHOLDER) for row in rows), (
        f"a row rendered with no number: {[r for r in rows if not r['value']]}"
    )
    # A real per-row status table, not the panel-scrape fallback.
    assert contract._build_prop_status_rows(rows) == rows
    headings = {row["heading"] for row in rows}
    assert headings == {"TCU props", "UNC props"}


def test_nothing_captured_yields_an_absent_block_not_an_empty_one(ncaaf_root):
    """`{}` reads as "nothing captured"; `{"away": [], "home": []}` does not."""
    assert ncaaf_root.prop_recommendations_for_game(
        season=2026, week=1, home_team="Ohio State", away_team="Michigan"
    ) == {}


def test_both_ncaaf_card_paths_attach_the_block():
    """Wiring only the live path means props vanish when a game moves paths."""
    source = (REPO_ROOT / "syndicate" / "features" / "ncaaf" / "cards.py").read_text(encoding="utf-8")
    assert source.count('"prop_recommendations": ncaaf_props.prop_recommendations_for_game(') == 2


def test_accented_school_names_join(ncaaf_root, monkeypatch):
    """`San Jose State` / `San Jose State Spartans` / `San Jose State`.

    Three spellings of one school across three systems: the team registry
    stores the accented form, the CFBD-derived board sends the unaccented one,
    and OddsAPI sends accented-plus-mascot. Stripping the accent as
    non-alphanumeric turns the registry form into `san jos state` and the
    school stops matching itself -- measured on the real 2026 wk1 slate, where
    San Jose State's entire props panel vanished with no error anywhere.
    """
    assert ncaaf_root._norm("San Jos\u00e9 State") == "san jose state"
    assert ncaaf_root._norm("San Jose State") == "san jose state"
    assert ncaaf_root._norm("San Jos\u00e9 State Spartans") == "san jose state spartans"
    assert ncaaf_root._norm("Hawai\u02bbi") == ncaaf_root._norm("Hawai'i")


def test_current_season_roster_wins_for_a_transfer(ncaaf_root, tmp_path):
    """A transfer is on two rosters; only the current season should count.

    The roster snapshot accumulates seasons in one file. Without a season
    preference a transfer resolves to two team ids, reads as ambiguous, and
    this module drops ambiguity -- deleting from the panel exactly the players
    most likely to be freshly quoted.
    """
    processed = tmp_path / "source_artifacts" / "data" / "processed"
    _write_csv(processed / "roster" / "ncaaf_roster_snapshot.csv", [
        {"player_name": "Portal Guy", "team_id": "153", "season": "2025"},
        {"player_name": "Portal Guy", "team_id": "2628", "season": "2026"},
    ])
    _write_csv(processed / "team_registry" / "ncaaf_team_registry_snapshot.csv", REGISTRY_ROWS)
    ncaaf_root.reset_caches()

    assert ncaaf_root._side_for_player("Portal Guy", home="TCU", away="North Carolina", season=2026) == "home"
    assert ncaaf_root._side_for_player("Portal Guy", home="TCU", away="North Carolina", season=2025) == "away"
