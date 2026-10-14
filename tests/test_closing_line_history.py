"""Each past game's own main closing line on the board's prop bars (lane past-line-overlays, 2026-10-14)."""

from __future__ import annotations

import csv
import os

import pytest

from syndicate.features import intelligence_recent_matchup as rm
from syndicate.features.shared import closing_line_history as clh
from syndicate.features.shared.layer2_board import _chart_columns

_COLS = ["actual", "away_team", "book_updated_at", "captured_at", "closing_bookmaker", "closing_line", "closing_price",
         "date", "event_id", "home_team", "line", "market", "player_name", "result", "segment", "selection", "sport"]


def _write(root, day, rows):
    folder = root / "settlement_inputs"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / f"closing_lines_{day}.csv").open("w", encoding="utf-8", newline="") as handle:
        w = csv.DictWriter(handle, fieldnames=_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in _COLS})


def _r(player, market, line, price, selection="over", sport="nhl", segment="full"):
    return {"sport": sport, "player_name": player, "market": market, "closing_line": line, "line": line,
            "closing_price": price, "selection": selection, "segment": segment}


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    clh._CACHE.clear()
    clh._WINDOW.clear()
    rm.RECENT_VALUES.clear()
    return tmp_path


def test_single_line_and_exact_date(root):
    _write(root, "2026-10-08", [_r("Bo Horvat", "SOG", 2.5, -115), _r("Bo Horvat", "SOG", 2.5, -105, "under")])
    assert clh.past_main_lines("nhl", "Bo Horvat", "SOG", ["2026-10-08", "2026-10-07"]) == [2.5, None]


def test_main_line_is_the_over_price_closest_to_even(root):
    _write(root, "2026-10-08", [_r("Bo Horvat", "SOG", 2.5, -180), _r("Bo Horvat", "SOG", 3.5, 105), _r("Bo Horvat", "SOG", 4.5, 260)])
    assert clh.past_main_lines("nhl", "bo horvat", "sog", ["2026-10-08"]) == [3.5]


def test_a_tie_or_no_priced_over_is_no_line(root):
    _write(root, "2026-10-08", [_r("A", "SOG", 2.5, -110), _r("A", "SOG", 3.5, -110),
                                _r("B", "SOG", 2.5, -110, "under"), _r("B", "SOG", 3.5, -110, "under")])
    assert clh.past_main_lines("nhl", "A", "SOG", ["2026-10-08"]) == [None]
    assert clh.past_main_lines("nhl", "B", "SOG", ["2026-10-08"]) == [None]


def test_alternate_markets_and_interval_segments_are_skipped(root):
    _write(root, "2026-10-08", [_r("A", "player_points_alternate", 9.5, -110, sport="wnba"),
                                _r("A", "player_points", 12.5, -110, sport="wnba", segment="h1")])
    assert clh.past_main_lines("wnba", "A", "player_points_alternate", ["2026-10-08"]) == [None]
    assert clh.past_main_lines("wnba", "A", "player_points", ["2026-10-08"]) == [None]


def test_week_labels_and_sport_mismatch_are_no_line(root):
    _write(root, "2026-10-04", [_r("Josh Allen", "Passing Yards", 245.5, -110, sport="nfl")])
    assert clh.past_main_lines("nfl", "Josh Allen", "Passing Yards", ["26-W5", "2026-10-04"]) == [None, 245.5]
    assert clh.past_main_lines("ncaaf", "Josh Allen", "Passing Yards", ["2026-10-04"]) == [None]


def test_names_fold_diacritics(root):
    _write(root, "2026-10-08", [_r("Lukáš Dostál", "SAVES", 27.5, -110)])
    assert clh.past_main_lines("nhl", "Lukas Dostal", "SAVES", ["2026-10-08"]) == [27.5]


def test_a_rewritten_file_is_reread(root):
    _write(root, "2026-10-08", [_r("A", "SOG", 2.5, -110)])
    assert clh.past_main_lines("nhl", "A", "SOG", ["2026-10-08"]) == [2.5]
    path = root / "settlement_inputs" / "closing_lines_2026-10-08.csv"
    _write(root, "2026-10-08", [_r("A", "SOG", 3.5, -110)])
    os.utime(path, ns=(path.stat().st_atime_ns, path.stat().st_mtime_ns + 1_000_000))
    assert clh.past_main_lines("nhl", "A", "SOG", ["2026-10-08"]) == [3.5]


def test_window_start_is_the_first_file(root):
    _write(root, "2026-10-01", [])
    _write(root, "2026-09-30", [])
    assert clh.window_start() == "2026-09-30"


def test_reachable_through_chart_columns(root):
    """REACHABILITY: a recorded dated form + a closing file produce `recent_lines` on the card."""
    _write(root, "2026-09-30", [])
    _write(root, "2026-10-08", [_r("Bo Horvat", "SOG", 3.5, -105)])
    row = {"kind": "prop", "sport": "nhl", "player_name": "Bo Horvat", "market": "SOG", "line": 2.5, "side": "over",
           "home_team": "A", "away_team": "B"}
    rm._record_values(row, [4, 2], ["2026-10-08", "2026-10-06"], ["v BOS", "@ NYR"])
    out = _chart_columns(row)
    assert out["recent_values"] == [4.0, 2.0]
    assert out["recent_lines"] == [3.5, None]
    assert out["recent_lines_from"] == "2026-09-30"


def test_no_line_on_any_bar_emits_nothing(root):
    _write(root, "2026-10-08", [_r("Someone Else", "SOG", 3.5, -105)])
    row = {"kind": "prop", "sport": "nhl", "player_name": "Bo Horvat", "market": "SOG", "line": 2.5, "side": "over"}
    rm._record_values(row, [4], ["2026-10-08"], ["v BOS"])
    out = _chart_columns(row)
    assert "recent_lines" not in out and "recent_lines_from" not in out


def test_week_labelled_bars_join_through_game_dates(root):
    """NFL / NCAAF bars are labelled '26-W5': the join goes through the aligned `game_dates`."""
    _write(root, "2026-10-04", [_r("Josh Allen", "Passing Yards", 245.5, -110, sport="nfl")])
    row = {"kind": "prop", "sport": "nfl", "player_name": "Josh Allen", "market": "Passing Yards", "line": 250.5,
           "side": "over", "home_team": "A", "away_team": "B"}
    rm._record_values(row, [301, 198], ["26-W5", "26-W4"], ["@NE", "vs MIA"], ["2026-10-04", "2026-09-28"])
    out = _chart_columns(row)
    assert out["recent_dates"] == ["26-W5", "26-W4"]
    assert out["recent_lines"] == [245.5, None]


def test_misaligned_game_dates_are_not_used(root):
    _write(root, "2026-10-04", [_r("Josh Allen", "Passing Yards", 245.5, -110, sport="nfl")])
    row = {"kind": "prop", "sport": "nfl", "player_name": "Josh Allen", "market": "Passing Yards", "line": 250.5, "side": "over"}
    rm._record_values(row, [301, 198], ["26-W5", "26-W4"], None, ["2026-10-04"])
    assert "recent_lines" not in _chart_columns(row)


def test_nfl_game_dates_from_the_schedule(root):
    from syndicate.features.shared.prop_evidence import football as fb

    folder = root / "nfl_source"
    folder.mkdir()
    (folder / "schedule_2026.csv").write_text("game_id,week,gameday,away_team,home_team\n2026_05_BUF_NE,5,2026-10-04,BUF,NE\n", encoding="utf-8")
    fb._GAME_DATE_CACHE.clear()
    lines = [{"season": 2026, "week": 5, "game_id": "2026_05_BUF_NE"}, {"season": 2026, "week": 4, "game_id": "2026_04_MIA_BUF"}]
    assert fb._nfl_game_dates(lines) == ["2026-10-04", ""]


def test_ncaaf_game_dates_are_the_central_day_of_the_utc_kickoff(root):
    import gzip
    import json

    from syndicate.features.shared.prop_evidence import football as fb

    folder = root / "ncaaf_source" / "historical_truth"
    folder.mkdir(parents=True)
    games = [{"id": 401, "startDate": "2026-10-04T00:30:00.000Z"}, {"id": 402, "startDate": "2026-10-03T16:00:00Z"}]
    with gzip.open(folder / "games_2026.json.gz", "wt", encoding="utf-8") as fh:
        json.dump(games, fh)
    fb._GAME_DATE_CACHE.clear()
    rows = [{"season": 2026, "game_id": "401"}, {"season": 2026, "game_id": "402"}, {"season": 2026, "game_id": "999"}]
    # 00:30Z on 10-04 is 7:30 PM CDT on 10-03 -- the Saturday slate, not Sunday.
    assert fb._ncaaf_game_dates(rows) == ["2026-10-03", "2026-10-03", ""]
