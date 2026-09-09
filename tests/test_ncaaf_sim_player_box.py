"""The NCAAF card's PER-PLAYER sim box.

The defect family these guard against is always the same shape: a panel that
renders, whose tests pass, and which is showing the wrong thing -- last
season's roster, a projection wearing an actuals chip, or an empty table that
says nothing about why.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from syndicate.features.ncaaf import cards as ncaaf_cards
from syndicate.features.ncaaf import player_projections as pp
from syndicate.features.ncaaf import prop_model
from syndicate.features.ncaaf import props as ncaaf_props


ROSTER_COLUMNS = [
    "player_id",
    "player_name",
    "team_id",
    "position",
    "season",
    "roster_status",
    "source_system",
    "source_snapshot_date",
]

GAME_LOG_COLUMNS = [
    "game_id",
    "season",
    "week",
    "player_id",
    "player_name",
    "team",
    "anytime_td",
]

REGISTRY_COLUMNS = ["team_id", "school_name", "mascot_name", "abbreviation"]


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@pytest.fixture()
def fixture_root(tmp_path, monkeypatch):
    """A miniature NCAAF artifact tree: registry, roster, game logs.

    Two teams. `Home State` has a 2026 skill player with real 2025 history
    (projectable) plus one with too little; `Away Tech` has a player who is
    ONLY on the 2025 roster -- the row a 2026 card must never show.
    """
    roster = tmp_path / "roster.csv"
    logs = tmp_path / "logs.csv"
    registry = tmp_path / "registry.csv"

    _write_csv(
        registry,
        REGISTRY_COLUMNS,
        [
            {"team_id": "1", "school_name": "Home State", "mascot_name": "Owls", "abbreviation": "HOME"},
            {"team_id": "2", "school_name": "Away Tech", "mascot_name": "Jets", "abbreviation": "AWAY"},
        ],
    )
    _write_csv(
        roster,
        ROSTER_COLUMNS,
        [
            {"player_id": "p1", "player_name": "Real Runner", "team_id": "1", "position": "RB",
             "season": "2026", "roster_status": "active", "source_system": "cfbd",
             "source_snapshot_date": "2026-09-01"},
            {"player_id": "p2", "player_name": "Thin Sample", "team_id": "1", "position": "WR",
             "season": "2026", "roster_status": "active", "source_system": "cfbd",
             "source_snapshot_date": "2026-09-01"},
            {"player_id": "p3", "player_name": "Big Blocker", "team_id": "1", "position": "OL",
             "season": "2026", "roster_status": "active", "source_system": "cfbd",
             "source_snapshot_date": "2026-09-01"},
            # 2025 ONLY. A 2026 card must not list him.
            {"player_id": "p4", "player_name": "Departed Senior", "team_id": "2", "position": "RB",
             "season": "2025", "roster_status": "active", "source_system": "cfbd",
             "source_snapshot_date": "2025-09-01"},
        ],
    )
    log_rows = []
    for week in range(1, 7):
        log_rows.append({"game_id": f"g{week}", "season": "2025", "week": str(week),
                         "player_id": "p1", "player_name": "Real Runner", "team": "Home State",
                         "anytime_td": "1"})
    log_rows.append({"game_id": "g1", "season": "2025", "week": "1", "player_id": "p2",
                     "player_name": "Thin Sample", "team": "Home State", "anytime_td": "0"})
    for week in range(1, 7):
        log_rows.append({"game_id": f"h{week}", "season": "2025", "week": str(week),
                         "player_id": "p4", "player_name": "Departed Senior", "team": "Away Tech",
                         "anytime_td": "1"})
    _write_csv(logs, GAME_LOG_COLUMNS, log_rows)

    missing = tmp_path / "does_not_exist.csv"
    monkeypatch.setattr(pp, "roster_snapshot_path", lambda: roster)
    monkeypatch.setattr(pp, "_checkout_roster_path", lambda: missing)
    monkeypatch.setattr(prop_model, "_game_stats_path", lambda: logs)
    monkeypatch.setattr(prop_model, "_checkout_game_stats_path", lambda: missing)
    monkeypatch.setattr(ncaaf_props, "_team_registry_rows",
                        lambda: [dict(row) for row in csv.DictReader(registry.open(encoding="utf-8"))])
    # No capture unless a test writes one.
    monkeypatch.setattr(ncaaf_props, "load_prop_rows", lambda season, week: [])

    pp.reset_caches()
    ncaaf_props.reset_caches()
    yield tmp_path
    pp.reset_caches()
    ncaaf_props.reset_caches()


def _game() -> dict:
    return {
        "away": {"abbr": "AWAY", "name": "Away Tech"},
        "home": {"abbr": "HOME", "name": "Home State"},
        "ncaaf_card": {"scoreboard": {"away_points": 21.0, "home_points": 27.5,
                                      "source_label": "SmartSim 2.0"}},
    }


def _projection_sections(sections: list[dict]) -> list[dict]:
    return [s for s in sections if str(s.get("title", "")).endswith("player projections")]


def test_squad_projections_only_lists_the_cards_own_season(fixture_root):
    home = pp.squad_projections(season=2026, week=2, team_name="Home State",
                                home_team="Home State", away_team="Away Tech")
    away = pp.squad_projections(season=2026, week=2, team_name="Away Tech",
                                home_team="Home State", away_team="Away Tech")

    assert [row["player_name"] for row in home["rows"]] == ["Real Runner"]
    # `Departed Senior` is projectable and on the 2025 roster only. Listing him
    # under a 2026 card is the exact defect `_ncaaf_player_box_section` refuses
    # for actuals.
    assert away["rows"] == []
    assert away["roster"] == 0
    # And an OL is never a row, however many games he played.
    assert "Big Blocker" not in {row["player_name"] for row in home["rows"]}


def test_history_season_falls_back_when_this_season_cannot_fit(fixture_root):
    result = pp.squad_projections(season=2026, week=2, team_name="Home State",
                                  home_team="Home State", away_team="Away Tech")
    assert result["history_season"] == 2025
    assert result["history_is_fallback"] is True
    # Refusal is counted, not hidden: `Thin Sample` has one prior game.
    assert result["refused"] == 1


def test_sections_are_chipped_sim_even_when_the_game_is_final(fixture_root):
    game = _game()
    game["live_state"] = {"final": True, "status": "Final"}
    sections = ncaaf_cards._ncaaf_box_sections(game, season=2026, week=2)
    projections = _projection_sections(sections)

    assert len(projections) == 2
    assert {s["chip"] for s in projections} == {"Sim"}
    assert [s["title"] for s in projections] == ["AWAY player projections", "HOME player projections"]


def test_projections_never_merge_into_the_actuals_panel(fixture_root):
    sections = ncaaf_cards._ncaaf_box_sections(_game(), season=2026, week=2)
    titles = [s["title"] for s in sections]

    # Both panels exist, separately, and the actuals one is not chipped Sim.
    assert "Player box" in titles
    player_box = next(s for s in sections if s["title"] == "Player box")
    assert player_box["chip"] != "Sim"
    assert "Real Runner" not in str(player_box.get("table_rows") or [])

    projections = _projection_sections(sections)
    assert all("PROJECTED, not played" in s["body"] for s in projections if s.get("table_rows"))


def test_team_level_sim_box_is_kept_beside_the_player_tables(fixture_root):
    sections = ncaaf_cards._ncaaf_box_sections(_game(), season=2026, week=2)
    titles = [s["title"] for s in sections]
    # Adding player detail must not delete the team projection somebody reads.
    assert "Sim box" in titles
    assert len(_projection_sections(sections)) == 2


def test_market_columns_are_absent_when_nothing_was_captured(fixture_root):
    sections = ncaaf_cards._ncaaf_box_sections(_game(), season=2026, week=2)
    home = next(s for s in _projection_sections(sections) if s["title"].startswith("HOME"))
    assert home["columns"] == ["Player", "Pos", "Sim TD%", "Prior G", "Prior TD"]
    # Never padded with blanks -- every row is exactly as wide as the header.
    assert all(len(row) == len(home["columns"]) for row in home["table_rows"])


def test_market_columns_appear_only_for_this_season_and_week(fixture_root, monkeypatch):
    captured = [
        {"home_team": "Home State", "away_team": "Away Tech", "player": "Real Runner",
         "market": "Anytime TD", "line": "", "over_price": "+150", "under_price": "",
         "book": "draftkings"},
    ]
    monkeypatch.setattr(ncaaf_props, "load_prop_rows",
                        lambda season, week: captured if (season, week) == (2026, 2) else [])
    ncaaf_props.reset_caches()

    week2 = ncaaf_cards._ncaaf_box_sections(_game(), season=2026, week=2)
    home2 = next(s for s in _projection_sections(week2) if s["title"].startswith("HOME"))
    assert home2["columns"][-2:] == ["Mkt TD%", "Best price"]
    assert "+150" in str(home2["table_rows"])

    ncaaf_props.reset_caches()
    week3 = ncaaf_cards._ncaaf_box_sections(_game(), season=2026, week=3)
    home3 = next(s for s in _projection_sections(week3) if s["title"].startswith("HOME"))
    # Week 3 must not borrow week 2's prices.
    assert "Mkt TD%" not in home3["columns"]


def test_unresolved_team_gets_a_stated_empty_state(fixture_root):
    game = _game()
    game["away"] = {"abbr": "ZZZ", "name": "Nowhere University"}
    sections = ncaaf_cards._ncaaf_box_sections(game, season=2026, week=2)
    away = next(s for s in _projection_sections(sections) if s["title"].startswith("ZZZ"))
    assert away["chip"] == "Sim"
    assert away.get("table_rows") is None
    assert "team registry could not resolve" in away["body"]


def test_empty_roster_names_what_is_missing(fixture_root):
    sections = ncaaf_cards._ncaaf_box_sections(_game(), season=2026, week=2)
    away = next(s for s in _projection_sections(sections) if s["title"].startswith("AWAY"))
    assert away["chip"] == "Sim"
    assert "roster snapshot carries no skill-position players" in away["body"]
    assert "build_ncaaf_roster_snapshot.py" in away["body"]
