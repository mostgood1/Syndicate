"""A doubleheader's two games are priced against their OWN game lines.

Measured on production 2026-09-22, TB @ NYY doubleheader: G1 gamePk 823543
(StatsAPI 17:05Z) and G2 823494 (23:05Z). The OddsAPI game-lines file carried
both events -- 394e1e2b... at 17:06Z and 574050c1... at 23:06Z -- but
`_collect_game_recommendations` keyed its lookup on (away_team, home_team)
alone, so the second event overwrote the first and `/mlb/api/cards` served
`commence_time = 23:06Z` for BOTH games: G1's official picks were priced
against G2's lines.

These run the REAL collector over a two-event same-pair fixture shaped like the
production file. Each game is given distinct odds and totals lines so a pick
carrying the other game's row is visible in `odds` / `market_line`, not only
in `event_id`.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vendor.mlb_bettingv2.tools import daily_update_multi_profile as dump

REPO_ROOT = Path(__file__).resolve().parents[1]
SIM_WRITER = REPO_ROOT / "vendor" / "mlb_bettingv2" / "tools" / "daily_update.py"

AWAY = {"id": 139, "name": "Tampa Bay Rays", "abbreviation": "TB"}
HOME = {"id": 147, "name": "New York Yankees", "abbreviation": "NYY"}

G1_EVENT = "394e1e2b849c5b4eaf2b5984eaa74b79"
G2_EVENT = "574050c10d1acc2da7baf72384eeaa11"
G1_COMMENCE = "2026-09-22T17:06:00Z"
G2_COMMENCE = "2026-09-22T23:06:00Z"


def _odds_row(event_id: str, commence: str, *, home_odds: int, away_odds: int, total_line: float) -> dict:
    return {
        "event_id": event_id,
        "commence_time": commence,
        "home_team": HOME["name"],
        "away_team": AWAY["name"],
        "bookmaker": "draftkings",
        "markets": {
            "h2h": {"home_odds": home_odds, "away_odds": away_odds},
            "totals": {"line": total_line, "over_odds": -110, "under_odds": -110},
        },
    }


G1_ROW = _odds_row(G1_EVENT, G1_COMMENCE, home_odds=-150, away_odds=130, total_line=8.5)
G2_ROW = _odds_row(G2_EVENT, G2_COMMENCE, home_odds=120, away_odds=-140, total_line=7.5)


def _sim_record(game_pk: int, *, game_number, game_date=None, double_header="S") -> dict:
    schedule = {
        "game_type": "R",
        "double_header": double_header,
        "game_number": game_number,
        "series_game_number": 3,
        "status": {"abstract": "Preview", "detailed": "Scheduled"},
    }
    if game_date is not None:
        schedule["game_date"] = game_date
    return {
        "date": "2026-09-22",
        "season": 2026,
        "game_pk": game_pk,
        "schedule": schedule,
        "away": dict(AWAY),
        "home": dict(HOME),
        # Home 75% and a total centred near 10 runs: an ML home pick and a
        # totals over pick clear the default policy against EITHER game's
        # lines, so which row each pick was priced against is the only variable.
        "sim": {
            "sims": 1000,
            "segments": {
                "full": {
                    "home_win_prob": 0.75,
                    "away_win_prob": 0.25,
                    "total_runs_dist": {"6": 50, "10": 900, "12": 50},
                }
            },
        },
    }


def _write_fixture(tmp_path: Path, sims: dict, rows: list) -> tuple:
    sim_dir = tmp_path / "sims" / "2026-09-22"
    sim_dir.mkdir(parents=True)
    for name, record in sims.items():
        (sim_dir / name).write_text(json.dumps(record), encoding="utf-8")
    lines_path = tmp_path / "oddsapi_game_lines_2026_09_22.json"
    lines_path.write_text(json.dumps({"date": "2026-09-22", "games": rows}), encoding="utf-8")
    return sim_dir, lines_path


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    # The collector reads roster snapshots from _DATA_DIR; point it at an empty
    # tree so the fixture is the only input.
    monkeypatch.setattr(dump, "_DATA_DIR", tmp_path / "data_root")


def _collect(sim_dir: Path, lines_path: Path) -> dict:
    return dump._collect_game_recommendations(sim_dir, lines_path, dump._policy_with_overrides(None))


def _by_game(rows: list) -> dict:
    out = {}
    for row in rows:
        assert row["game_pk"] not in out, f"two picks for one game in one market: {row['game_pk']}"
        out[row["game_pk"]] = row
    return out


def _assert_priced_against(pick: dict, row: dict) -> None:
    assert pick["event_id"] == row["event_id"]
    assert pick["commence_time"] == row["commence_time"]


def test_doubleheader_games_get_their_own_event_by_start_time(tmp_path):
    sim_dir, lines_path = _write_fixture(
        tmp_path,
        {
            "sim_0_TB_at_NYY_pk823543_g1.json": _sim_record(823543, game_number=1, game_date="2026-09-22T17:05:00Z"),
            "sim_1_TB_at_NYY_pk823494_g2.json": _sim_record(823494, game_number=2, game_date="2026-09-22T23:05:00Z"),
        },
        [G1_ROW, G2_ROW],  # production order: the later event last, so it won the old dict
    )
    out = _collect(sim_dir, lines_path)

    ml = _by_game(out["ml"])
    assert set(ml) == {823543, 823494}
    _assert_priced_against(ml[823543], G1_ROW)
    _assert_priced_against(ml[823494], G2_ROW)
    assert ml[823543]["odds"] == -150
    assert ml[823494]["odds"] == 120

    totals = _by_game(out["totals"])
    assert set(totals) == {823543, 823494}
    _assert_priced_against(totals[823543], G1_ROW)
    _assert_priced_against(totals[823494], G2_ROW)
    assert totals[823543]["market_line"] == 8.5
    assert totals[823494]["market_line"] == 7.5


def test_start_time_outranks_game_number(tmp_path):
    """The scheduled start is the primary discriminator: a game_number that
    disagrees with it (e.g. a makeup game) does not override it."""
    sim_dir, lines_path = _write_fixture(
        tmp_path,
        {"sim_0_TB_at_NYY_pk823543_g2.json": _sim_record(823543, game_number=2, game_date="2026-09-22T17:05:00Z")},
        [G1_ROW, G2_ROW],
    )
    ml = _by_game(_collect(sim_dir, lines_path)["ml"])
    _assert_priced_against(ml[823543], G1_ROW)


def test_records_without_a_start_time_fall_back_to_game_number(tmp_path):
    """Sim records written before `schedule.game_date` existed (every record on
    disk on 2026-09-22) still resolve, via the pair's rows in commence order.
    The file lists G2 FIRST here, so file order cannot be what is matched."""
    sim_dir, lines_path = _write_fixture(
        tmp_path,
        {
            "sim_0_TB_at_NYY_pk823543_g1.json": _sim_record(823543, game_number=1),
            "sim_1_TB_at_NYY_pk823494_g2.json": _sim_record(823494, game_number=2),
        },
        [G2_ROW, G1_ROW],
    )
    ml = _by_game(_collect(sim_dir, lines_path)["ml"])
    _assert_priced_against(ml[823543], G1_ROW)
    _assert_priced_against(ml[823494], G2_ROW)


def test_single_event_pair_is_unchanged(tmp_path):
    """One row on the pair: returned as before, with no discriminator required
    (no game_date, no game_number)."""
    sim_dir, lines_path = _write_fixture(
        tmp_path,
        {"sim_0_TB_at_NYY_pk823543.json": _sim_record(823543, game_number=None, double_header="N")},
        [G1_ROW],
    )
    out = _collect(sim_dir, lines_path)
    _assert_priced_against(_by_game(out["ml"])[823543], G1_ROW)
    _assert_priced_against(_by_game(out["totals"])[823543], G1_ROW)


@pytest.mark.parametrize("game_number", [None, 0, 3, "1", True])
def test_no_discriminator_refuses_rather_than_guessing(tmp_path, game_number):
    """Two rows on the pair and nothing that says which is this game's: the
    game gets NO picks. Old behaviour priced it against whichever row came last."""
    sim_dir, lines_path = _write_fixture(
        tmp_path,
        {"sim_0_TB_at_NYY_pk823543.json": _sim_record(823543, game_number=game_number)},
        [G1_ROW, G2_ROW],
    )
    out = _collect(sim_dir, lines_path)
    assert out["ml"] == []
    assert out["totals"] == []


def test_identical_commence_times_refuse(tmp_path):
    """Neither a start time nor an index can split two rows at the same instant."""
    twin = dict(G2_ROW, commence_time=G1_COMMENCE)
    sim_dir, lines_path = _write_fixture(
        tmp_path,
        {"sim_0_TB_at_NYY_pk823543_g1.json": _sim_record(823543, game_number=1, game_date="2026-09-22T17:05:00Z")},
        [G1_ROW, twin],
    )
    assert _collect(sim_dir, lines_path)["ml"] == []


def test_sim_writer_records_the_scheduled_start():
    """Reachability: the start-time path only runs if the sim record carries
    it, and the record is written in daily_update.py's schedule block."""
    source = SIM_WRITER.read_text(encoding="utf-8-sig")
    schedule_block = source.split('"schedule": {', 1)[1].split("},", 1)[0]
    assert '"game_date": g.get("gameDate"),' in schedule_block
