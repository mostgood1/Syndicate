"""The soccer prop sim listed last season's squads. Lane `soccer-player-substrate`.

MEASURED 2026-09-15 before any of this was written, on production
`recommendations_*.json`, production `players_*.csv` and ESPN box scores
(07-22..09-14, 584 matches):
  * Real shots attributable to a listed player: championship 36%, primeira_liga
    53%, belgian_pro_league 56%, eredivisie 62%, bundesliga 68%, ligue_1 69%,
    serie_a 71%, la_liga 76%, epl 81%, mls 87%.
  * Whole fixture sides published with ZERO players carried 36% of championship
    shots and 27% of belgian. Six were club-name spelling gaps between the player
    files and ESPN.
  * The departed-player filter waited for the league's busiest player to reach
    450 minutes, so it was OFF in four of the big five. Prior-season-only
    players were most of the phantom rows.
  * A player who moved within the league stayed bound to his OLD club, because
    the dedupe keeps the max-minutes row and that row carries its own season's
    team.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.soccer.features import team_names
from syndicate.features.soccer.features.loaders import build_soccer_player_features
from syndicate.features.soccer.features.team_names import canonical_team_name

_REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def artifacts():
    name = "build_soccer_artifacts_substrate_under_test"
    spec = importlib.util.spec_from_file_location(name, _REPO / "scripts" / "build_soccer_artifacts.py")
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_roster(artifacts, monkeypatch):
    """The git-shipped roster seed must not decide these tests."""
    monkeypatch.setattr(artifacts, "_current_roster_names", lambda league, source_root=None: set())


def _rows(team: str, count: int, minutes: float, prefix: str, *, season: int, shots: float = 1.0) -> list[dict]:
    return [
        {
            "league": "epl",
            "season": season,
            "player_id": f"{prefix}{i}",
            "player_name": f"{prefix} player{i}",
            "team": team,
            "position": "M",
            "minutes": minutes,
            "shots_per90": shots,
        }
        for i in range(count)
    ]


def _write(root: Path, season: int, rows: list[dict]) -> None:
    target = root / "epl" / "players"
    target.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(target / f"players_{season}.csv", index=False)


# ---------------------------------------------------------------------------
# The club comes from the newest season
# ---------------------------------------------------------------------------


def test_a_player_who_MOVED_binds_to_his_NEW_club_and_keeps_his_bigger_sample(artifacts, tmp_path):
    _write(tmp_path, 2025, _rows("Arsenal", 12, 2000.0, "a", season=2025)
           + [{**_rows("Arsenal", 1, 2000.0, "mover", season=2025, shots=3.0)[0]}])
    _write(tmp_path, 2026, _rows("Arsenal", 12, 200.0, "a", season=2026)
           + _rows("Chelsea", 12, 200.0, "c", season=2026)
           + [{**_rows("Chelsea", 1, 200.0, "mover", season=2026, shots=1.0)[0]}])
    rows = {row["player_id"]: row for row in artifacts._load_player_rows("epl", tmp_path)}
    mover = rows["mover0"]
    assert mover["team"] == "Chelsea", "the max-minutes 2025 row carried Arsenal; the player now plays for Chelsea"
    assert float(mover["minutes"]) == 2000.0 and float(mover["shots_per90"]) == 3.0, "rates must stay with the bigger sample"
    assert mover["season_evidence"] == "current"
    assert artifacts._PLAYER_LOAD_AUDIT["club_from_newest_season"] == 1


# ---------------------------------------------------------------------------
# The departed filter is decided per club
# ---------------------------------------------------------------------------


def _two_clubs(tmp_path: Path, *, ready_minutes: float = 200.0, thin_minutes: float = 60.0) -> None:
    _write(tmp_path, 2025, _rows("Arsenal", 12, 2000.0, "a", season=2025) + _rows("Arsenal", 1, 2000.0, "arsenal_gone", season=2025)
           + _rows("Leeds", 12, 2000.0, "l", season=2025) + _rows("Leeds", 1, 2000.0, "leeds_gone", season=2025))
    _write(tmp_path, 2026, _rows("Arsenal", 12, ready_minutes, "a", season=2026) + _rows("Leeds", 12, thin_minutes, "l", season=2026))


def test_a_READY_club_loses_its_prior_only_player_while_a_THIN_club_keeps_its_own(artifacts, tmp_path):
    _two_clubs(tmp_path)
    latest = pd.read_csv(tmp_path / "epl" / "players" / "players_2026.csv")
    assert artifacts._busiest_player_minutes(latest) < artifacts._MIN_LATEST_SEASON_MINUTES, (
        "the OLD league-wide guard refuses this file outright, keeping both departed players"
    )
    rows = {row["player_id"]: row for row in artifacts._load_player_rows("epl", tmp_path)}
    assert "arsenal_gone0" not in rows, "Arsenal has two matches and an XI in the current file"
    assert "leeds_gone0" in rows, "Leeds' current rows are one short game deep: not ready, keep everyone"
    assert rows["leeds_gone0"]["season_evidence"] == "prior_only"
    audit = artifacts._PLAYER_LOAD_AUDIT
    assert audit["departed_filter"] == "per_club"
    assert (audit["clubs_ready"], audit["clubs_seen"], audit["dropped"]) == (1, 2, 1)


def test_REACHABILITY_no_club_ready_means_nothing_is_trimmed(artifacts, tmp_path, capsys):
    """`off != on` against the test above: same files, both clubs thin."""
    _two_clubs(tmp_path, ready_minutes=60.0)
    rows = {row["player_id"] for row in artifacts._load_player_rows("epl", tmp_path)}
    assert {"arsenal_gone0", "leeds_gone0"} <= rows
    assert artifacts._PLAYER_LOAD_AUDIT["departed_filter"] == "refused_no_club_ready"
    assert "clubs_ready=0/2" in capsys.readouterr().out


def test_a_club_needs_a_starting_XI_in_the_file_not_just_one_busy_player(artifacts, tmp_path):
    _write(tmp_path, 2025, _rows("Arsenal", 12, 2000.0, "a", season=2025) + _rows("Arsenal", 1, 2000.0, "gone", season=2025))
    _write(tmp_path, 2026, _rows("Arsenal", 10, 900.0, "a", season=2026))
    rows = {row["player_id"] for row in artifacts._load_player_rows("epl", tmp_path)}
    assert "gone0" in rows, "ten players with minutes is not yet a squad"


def test_the_roster_still_RESCUES_a_player_of_a_ready_club(artifacts, tmp_path, monkeypatch):
    _two_clubs(tmp_path)
    monkeypatch.setattr(artifacts, "_current_roster_names", lambda league, source_root=None: {"arsenal_gone player0"})
    rows = {row["player_id"] for row in artifacts._load_player_rows("epl", tmp_path)}
    assert "arsenal_gone0" in rows


def test_a_truncated_file_still_refuses_LEAGUE_WIDE(artifacts, tmp_path):
    """`too_few` is a property of the file, so a ready club must not override it."""
    _write(tmp_path, 2025, _rows("Arsenal", 60, 2000.0, "a", season=2025))
    _write(tmp_path, 2026, _rows("Arsenal", 12, 900.0, "a", season=2026))
    rows = artifacts._load_player_rows("epl", tmp_path)
    assert len(rows) == 60
    assert artifacts._PLAYER_LOAD_AUDIT["departed_filter"] == "refused_too_few"


def test_club_readiness_reads_the_ESPN_minutes_column_and_transfer_rows(artifacts):
    frame = pd.DataFrame(
        [{"player_id": f"p{i}", "team": "Ajax", "minutes_played": 270.0} for i in range(11)]
        + [{"player_id": "t", "team": "Ajax,PSV Eindhoven", "minutes_played": 90.0}]
    )
    ready, seen = artifacts._clubs_ready(frame)
    assert canonical_team_name("Ajax") in ready
    assert canonical_team_name("PSV Eindhoven") in seen and canonical_team_name("PSV Eindhoven") not in ready


def test_UNKNOWN_minutes_mean_no_club_is_ready(artifacts):
    assert artifacts._clubs_ready(pd.DataFrame([{"player_id": "a", "team": "Ajax"}])) == (set(), set())
    assert artifacts._clubs_ready(pd.DataFrame([{"player_id": "a", "minutes": 900}])) == (set(), set())


def test_a_single_season_league_is_tagged_as_such(artifacts, tmp_path):
    _write(tmp_path, 2026, _rows("Arsenal", 12, 900.0, "a", season=2026))
    rows = artifacts._load_player_rows("epl", tmp_path)
    assert {row["season_evidence"] for row in rows} == {"single_season"}
    assert artifacts._PLAYER_LOAD_AUDIT["departed_filter"] == "single_season"


# ---------------------------------------------------------------------------
# The published squad audit
# ---------------------------------------------------------------------------


def test_squad_audit_counts_listed_players_by_evidence_and_shows_an_empty_side(artifacts):
    rows = [
        {"player_id": "1", "season_evidence": "current"},
        {"player_id": "2", "season_evidence": "prior_only"},
        {"player_id": "3", "season_evidence": "current"},
    ]
    outputs = [
        {"player_id": "1", "side": "home", "match_id": "m1"},
        {"player_id": "2", "side": "home", "match_id": "m1"},
        {"player_id": "3", "side": "home", "match_id": "m1"},
    ]
    audit = artifacts._squad_audit(outputs, rows)
    assert audit["m1"]["home"] == {"listed": 3, "current": 2, "prior_only": 1, "single_season": 0}
    assert audit["m1"]["away"]["listed"] == 0, "the empty side is the signal"


# ---------------------------------------------------------------------------
# The six spelling gaps that published a side with zero players
# ---------------------------------------------------------------------------

# (ESPN fixture spelling, production player-file spelling), quoted.
SPELLING_GAPS = [
    ("RB Leipzig", "RasenBallsport Leipzig"),
    ("SC Paderborn 07", "Paderborn"),
    ("Parma", "Parma Calcio 1913"),
    ("Deportivo", "Deportivo La Coruna"),
    ("Deportivo La Coruña", "Deportivo La Coruna"),
    ("Stade Rennais", "Rennes"),
    ("OH Leuven", "Oud-Heverlee Leuven"),
]


def _bound(fixture: str, player_team: str) -> list[str]:
    features = build_soccer_player_features(
        [{"player_id": "p1", "player_name": "Somebody", "team": player_team}],
        league="x",
        date="2026-09-15",
        fixture_teams=[fixture, "Opponent FC"],
    )
    return [feature.team for feature in features]


@pytest.mark.parametrize("fixture,player_team", SPELLING_GAPS)
def test_each_spelling_gap_now_BINDS_the_player_to_the_fixture(fixture, player_team):
    assert _bound(fixture, player_team) == [fixture]


@pytest.mark.parametrize("fixture,player_team", SPELLING_GAPS[:1] + SPELLING_GAPS[2:3] + SPELLING_GAPS[5:])
def test_REACHABILITY_without_the_new_aliases_the_side_is_EMPTY(fixture, player_team, monkeypatch):
    new_keys = {"rasenballsport leipzig", "paderborn 07", "parma calcio 1913", "deportivo la coruna", "stade rennais", "oud heverlee leuven"}
    monkeypatch.setattr(team_names, "_ALIASES", {k: v for k, v in team_names._ALIASES.items() if k not in new_keys})
    assert _bound(fixture, player_team) == []


@pytest.mark.parametrize(
    "one,other",
    [("Deportivo", "Deportivo Alavés"), ("Stade Rennais", "Stade de Reims"), ("OH Leuven", "Leuven Bears"),
     ("RB Leipzig", "Lokomotive Leipzig"), ("Parma", "Palermo")],
)
def test_no_new_alias_merges_two_different_clubs(one, other):
    assert canonical_team_name(one) != canonical_team_name(other)


# ---------------------------------------------------------------------------
# Presence is not reachability: the fields must reach the WRITTEN artifact
# ---------------------------------------------------------------------------


class _FakeOutput:
    def __init__(self, match_outputs, player_outputs):
        self.match_outputs = match_outputs
        self.player_outputs = player_outputs


class _FakeAdapter:
    def simulate_props(self, _simulation_input):
        return _FakeOutput(
            [{"match_id": "e1", "matchup": {"home_team": "Arsenal", "away_team": "Leeds"}}],
            [
                {"player_id": "a0", "player_name": "a player0", "team": "Arsenal", "side": "home", "match_id": "e1"},
                {"player_id": "arsenal_gone0", "player_name": "gone", "team": "Arsenal", "side": "home", "match_id": "e1"},
            ],
        )


def test_the_squad_audit_and_player_substrate_reach_the_WRITTEN_artifact(artifacts, tmp_path, monkeypatch):
    """The builder runs as a child with stdout discarded, so these fields are the
    ONLY production instrument this lane adds. A helper that is tested but never
    written would be the inert-feature shape `model_engine_standard.md` §4.3
    exists for. Read back from DISK, not from the returned dict."""
    import json

    source_root = tmp_path / "source"
    _two_clubs(source_root)
    monkeypatch.setattr(artifacts, "_fetch_fixtures", lambda league, iso_date: [
        {"event_id": "e1", "home_team": "Arsenal", "away_team": "Leeds", "kickoff": "2026-09-19T14:00Z", "status_state": "pre"}
    ])
    monkeypatch.setattr(artifacts, "_load_team_ratings", lambda league, root, iso_date: {"Arsenal": {}, "Leeds": {}})
    monkeypatch.setattr(artifacts, "_attach_confirmed_starters", lambda league, iso_date, fixtures, rows: fixtures)
    monkeypatch.setattr(artifacts, "_apply_market_anchor", lambda league, root, fixtures, ratings: (ratings, {"state": "disabled"}))
    monkeypatch.setattr(artifacts, "build_soccer_simulation_input", lambda **kwargs: object())
    monkeypatch.setattr(artifacts, "build_soccer_simulation_adapter", lambda league: _FakeAdapter())

    out_root = tmp_path / "out"
    artifacts.build_artifacts("epl", "2026-09-19", source_root=source_root, out_root=out_root, simulations=10)
    written = next(out_root.rglob("recommendations_2026-09-19.json"))
    payload = json.loads(written.read_text(encoding="utf-8"))

    assert payload["player_substrate"]["departed_filter"] == "per_club"
    assert payload["player_substrate"]["clubs_ready"] == 1
    squad = payload["matches"][0]["squad_audit"]
    # `arsenal_gone0` was trimmed from the rows, so the audit cannot tag it --
    # it counts as listed but carries no evidence, which is exactly what a
    # stale list looks like from outside.
    assert squad["home"]["listed"] == 2 and squad["home"]["current"] == 1
    assert squad["away"] == {"listed": 0, "current": 0, "prior_only": 0, "single_season": 0}
