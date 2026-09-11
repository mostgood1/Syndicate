"""The per-series cap keeps the rungs AT the board's lines, not the first 400.

`date_aware` chose the right DAY and then cut that day's ladder in arrival
order. Measured 2026-09-11 on production: `KXNCAAFSPREAD` fetched 2,541 and
`KXNCAAFTOTAL` 2,008, 400 kept each, and the Kalshi plan's 16 NCAAF Saturday
rows had 0 contracts. A replay over the full live ladders put this rule at
11/16 on the same 400, which is also what no cap at all gives.

Every test holds the budget fixed, because a selection change that grows the
payload is the 8MB write refusal again.
"""

from __future__ import annotations

import json
import time
from datetime import date

import pytest

from pipeline import kalshi_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    for name in (
        "SYNDICATE_KALSHI_REFRESH_INTERVAL_SECONDS",
        "SYNDICATE_KALSHI_SERIES",
        "SYNDICATE_KALSHI_SERIES_PER_TICK",
        "SYNDICATE_KALSHI_DORMANT_INTERVAL_SECONDS",
        "SYNDICATE_KALSHI_PRECAP_DATE_AWARE",
        "SYNDICATE_KALSHI_PRECAP_BOARD_LINES",
        "SYNDICATE_KALSHI_PRECAP_WINDOW_AHEAD_DAYS",
        "SYNDICATE_KALSHI_PRECAP_WINDOW_BACK_DAYS",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SYNDICATE_KALSHI_REQUEST_SPACING_MS", "0")
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


CAP = mod.MAX_MARKETS_PER_SERIES
WINDOW = ("2026-08-23", "2026-08-26")
# Texas AWAY at the White Sox, as Kalshi writes the event segment.
TEXCWS = "26AUG241940TEXCWS"
# A game that is not on our board, on the same date.
ELSEWHERE = "26AUG241940AAABBB"


def _spread(club: str, strike: float, code: str, event: str = TEXCWS) -> dict:
    return {
        "ticker": f"KXMLBSPREAD-{event}-{code}",
        "series": "KXMLBSPREAD",
        "title": f"{club} wins by over {strike} runs?",
        "yes_american": 150,
        "no_american": -170,
    }


def _total(strike: float, event: str = TEXCWS) -> dict:
    return {
        "ticker": f"KXMLBTOTAL-{event}-{int(strike + 0.5)}",
        "series": "KXMLBTOTAL",
        "title": f"Over {strike} runs",
        "yes_american": -110,
        "no_american": -110,
    }


def _fillers(n: int, event: str = ELSEWHERE) -> list[dict]:
    return [_spread("Alpha", i + 0.5, f"ALP{i}", event=event) for i in range(n)]


def _board_rows(spread: float = 3.5, total: float = 8.5) -> list[dict]:
    """TEX @ CHW, Texas favoured by `spread`: away -X and home +X, as a board writes it."""
    base = {
        "sport": "mlb",
        "event_id": "e1",
        "away_team": "TEX",
        "home_team": "CHW",
        "commence_time": "2026-08-24T23:40:00Z",
    }
    return [
        {**base, "market": "spreads", "line": -spread, "side": "away"},
        {**base, "market": "spreads", "line": spread, "side": "home"},
        {**base, "market": "totals", "line": total, "side": "over"},
        {**base, "market": "totals", "line": total, "side": "under"},
        {**base, "market": "h2h", "line": None, "side": "home"},
    ]


def _demand(rows: list[dict] | None = None) -> dict:
    return mod.merge_board_line_demand(
        {}, mod.board_line_entries(rows or _board_rows()), now=time.time()
    )


# --------------------------------------------------------------------------
# What the join records.
# --------------------------------------------------------------------------


def test_the_board_records_one_entry_per_game_with_spreads_home_relative():
    rows = _board_rows()
    entries = mod.board_line_entries(
        rows
        + [
            # A segment row's rung lives in its own series.
            {**rows[0], "segment": "first5", "line": -0.5},
            # No game identity: nothing to resolve a Kalshi blob against.
            {**rows[0], "event_id": ""},
            # A player prop keys on the player, not the game.
            {**rows[0], "market": "pitcher_strikeouts", "player_name": "X", "line": 6.5},
        ]
    )
    assert list(entries) == ["e1"]
    lines = entries["e1"]["l"]
    # away -3.5 and home +3.5 are ONE bet seen from two sides: home +3.5.
    assert lines["spreads"] == [3.5]
    assert lines["totals"] == [8.5]
    assert lines["h2h"] == [0.0]
    assert entries["e1"]["s"] == "mlb"


def test_the_recorded_demand_is_bounded_in_games_and_in_lines():
    now = time.time()
    fresh = {
        f"g{i}": {"h": "H", "a": "A", "t": None, "s": "ncaaf", "l": {"totals": [float(i)]}}
        for i in range(mod._BOARD_LINE_EVENT_LIMIT + 50)
    }
    assert len(mod.merge_board_line_demand({}, fresh, now=now)) == mod._BOARD_LINE_EVENT_LIMIT

    moved: dict = {}
    for step in range(12):
        moved = mod.merge_board_line_demand(
            moved, {"e1": {"h": "H", "a": "A", "l": {"spreads": [float(step)]}}}, now=now
        )
    # A moving line keeps its recent history, newest last, and no more.
    assert moved["e1"]["l"]["spreads"] == [float(s) for s in range(4, 12)]


def test_a_game_unseen_for_the_whole_window_ages_out():
    now = time.time()
    stale = {
        "old": {
            "h": "H",
            "a": "A",
            "l": {"totals": [8.5]},
            "at": now - mod._DEMAND_WINDOW_SECONDS - 1,
        }
    }
    assert "old" not in mod.merge_board_line_demand(stale, {}, now=now)
    assert mod.board_line_demand_from_state({"board_line_demand": stale}) == {}


def test_the_join_records_board_lines_only_with_the_flag_on(monkeypatch, capsys):
    """Off records NOTHING, so the stored document is byte-identical to today."""
    path = mod.markets_artifact_path()
    mod._record_board_demand(_board_rows(), selected_date="2026-08-24")
    assert "board_line_demand" not in json.loads(path.read_text(encoding="utf-8"))
    assert "line_events" not in capsys.readouterr().out

    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_BOARD_LINES", "1")
    mod._record_board_demand(_board_rows(), selected_date="2026-08-24")
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["board_line_demand"]["e1"]["l"]["spreads"] == [3.5]
    out = capsys.readouterr().out
    assert "line_events=1" in out and "line_bytes=" in out, out


# --------------------------------------------------------------------------
# Which rung is the board's. Orientation is asserted, because the mirror rung
# at the same magnitude is the OPPOSITE bet.
# --------------------------------------------------------------------------


def test_the_rung_naming_the_favourite_is_at_the_line_and_its_mirror_is_not():
    """"Texas wins by over 3.5" is the board's TEX -3.5 (and CHW +3.5).

    "Chicago White Sox wins by over 3.5" is the other club at the same
    magnitude. The join refuses it as `spread_line_orientation_mismatch`, so it
    must not take a slot as if it were this game's rung.
    """
    markets = [
        _spread("Texas", 3.5, "TEX4"),
        _spread("Chicago White Sox", 3.5, "CHW4"),
        _spread("Texas", 4.5, "TEX5"),
        _spread("Texas", 6.5, "TEX7"),
        _total(8.5),
        _total(10.5),
    ]
    assert mod.board_line_distances(markets, _demand()) == [0.0, 7.0, 1.0, 3.0, 0.0, 2.0]


def test_a_game_that_is_not_on_the_board_asks_for_nothing():
    assert mod.board_line_distances(_fillers(3), _demand()) == [None, None, None]


def test_no_recorded_demand_asks_for_nothing():
    assert mod.board_line_distances([_spread("Texas", 3.5, "TEX4")], {}) == [None]


# --------------------------------------------------------------------------
# The selection. Same budget; off keeps today's survivors exactly.
# --------------------------------------------------------------------------

AT = "KXMLBSPREAD-26AUG241940TEXCWS-TEX4"
NEAR = {"KXMLBSPREAD-26AUG241940TEXCWS-TEX5", "KXMLBSPREAD-26AUG241940TEXCWS-TEX3"}
FAR = "KXMLBSPREAD-26AUG241940TEXCWS-TEX10"


def _capped_slate() -> list[dict]:
    """450 rungs of a game we do not carry arrive FIRST, on the board game's date,
    so both existing rules spend the whole budget on them."""
    return _fillers(450) + [
        _spread("Texas", 3.5, "TEX4"),
        _spread("Texas", 4.5, "TEX5"),
        _spread("Texas", 2.5, "TEX3"),
        _spread("Texas", 9.5, "TEX10"),
    ]


@pytest.mark.parametrize("date_aware", [False, True])
def test_neither_existing_rule_keeps_the_boards_rung(date_aware):
    kept, _, counts = mod.select_markets_for_cap(
        _capped_slate(), CAP, WINDOW, date_aware=date_aware
    )
    assert AT not in {m["ticker"] for m in kept}
    assert "kept_at_line" not in counts, "no demand must add nothing to the counters"


@pytest.mark.parametrize("date_aware", [False, True])
def test_the_rung_at_the_line_and_its_neighbours_survive_on_the_same_budget(date_aware):
    markets = _capped_slate()
    distances = mod.board_line_distances(markets, _demand())
    kept, cut, counts = mod.select_markets_for_cap(
        markets, CAP, WINDOW, date_aware=date_aware, line_distance=distances
    )
    tickers = {m["ticker"] for m in kept}
    assert len(kept) == CAP and len(cut) == len(markets) - CAP, "the payload must not grow"
    assert AT in tickers
    assert NEAR <= tickers, "one point either side covers a line that moves"
    assert FAR not in tickers, "six points off is left to the date rule"
    assert counts["demand_rungs"] == 4
    assert counts["kept_at_line"] == 1 and counts["cut_at_line"] == 0
    assert counts["kept_adjacent"] == 2


def test_demand_that_resolves_nothing_selects_exactly_as_before():
    """A cold start, or a board with none of these games, changes nothing."""
    markets = _capped_slate()
    for date_aware in (False, True):
        before, _, _ = mod.select_markets_for_cap(markets, CAP, WINDOW, date_aware=date_aware)
        after, _, counts = mod.select_markets_for_cap(
            markets, CAP, WINDOW, date_aware=date_aware, line_distance=[None] * len(markets)
        )
        assert after == before
        assert counts["demand_rungs"] == 0


def test_under_the_cap_demand_changes_nothing():
    markets = [_spread("Texas", 3.5, "TEX4")] + _fillers(5)
    kept, cut, _ = mod.select_markets_for_cap(
        markets,
        CAP,
        WINDOW,
        date_aware=True,
        line_distance=mod.board_line_distances(markets, _demand()),
    )
    assert kept == markets and cut == []


def test_at_line_rungs_beyond_the_budget_are_counted_not_hidden():
    markets = [_spread("Texas", 3.5, f"T{i}") for i in range(5)] + _fillers(3)
    kept, _, counts = mod.select_markets_for_cap(
        markets, 3, WINDOW, date_aware=True, line_distance=[0.0] * 5 + [None] * 3
    )
    assert len(kept) == 3
    assert counts["kept_at_line"] == 3 and counts["cut_at_line"] == 2


def test_absent_flag_is_off(monkeypatch):
    assert mod.precap_board_lines_enabled() is False
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_BOARD_LINES", "1")
    assert mod.precap_board_lines_enabled() is True
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_BOARD_LINES", "off")
    assert mod.precap_board_lines_enabled() is False


# --------------------------------------------------------------------------
# off != on, through the real refresh, in the log AND in the artifact the plan
# reads (`markets_from_state`). A fix that stops at the working set ships nothing.
# --------------------------------------------------------------------------

_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def _event(day: date, teams: str) -> str:
    return f"{day.year % 100:02d}{_MONTHS[day.month - 1]}{day.day:02d}{teams}"


def _window_slate() -> tuple[list[dict], str]:
    """Dated from `board_window_dates()`, so the date rule cannot tell them apart."""
    day = date.fromisoformat(mod.board_window_dates()[0])
    board_event = _event(day, "1940TEXCWS")
    markets = _fillers(450, event=_event(day, "1940AAABBB")) + [
        _spread("Texas", 3.5, "TEX4", event=board_event)
    ]
    return markets, f"KXMLBSPREAD-{board_event}-TEX4"


def _seed_demand() -> None:
    mod.markets_artifact_path().write_text(
        json.dumps({"board_line_demand": _demand()}), encoding="utf-8"
    )


def _run_with(monkeypatch, capsys, markets_by_series) -> str:
    monkeypatch.setattr(mod, "sports_series", lambda: tuple(sorted(markets_by_series)))
    monkeypatch.setattr(
        mod,
        "fetch_series_markets",
        lambda series: {"markets": markets_by_series.get(series, []), "strategy": "series_filter"},
    )
    mod.run_kalshi_odds_refresh(force=True)
    out = capsys.readouterr().out
    line = ""
    for candidate in out.splitlines():
        if "PRECAP_SELECT" in candidate:
            line = candidate
    return line


def _persisted(series: str) -> set[str]:
    stored = json.loads(mod.markets_artifact_path().read_text(encoding="utf-8"))
    return {m["ticker"] for m in stored["series"][series]["markets"]}


@pytest.mark.parametrize("board_lines", [False, True])
def test_off_differs_from_on_in_the_log_and_in_the_stored_working_set(
    monkeypatch, capsys, board_lines
):
    markets, target = _window_slate()
    _seed_demand()
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "1")
    if board_lines:
        monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_BOARD_LINES", "1")
    line = _run_with(monkeypatch, capsys, {"KXMLBSPREAD": markets})
    persisted = _persisted("KXMLBSPREAD")

    assert len(persisted) == CAP, "the payload must not grow"
    if board_lines:
        assert "mode=board_lines" in line and "fill=date_aware" in line, line
        assert "demand_events=1" in line, line
        assert "kept_at_line_total=1" in line and "cut_at_line_total=0" in line, line
        assert target in persisted
    else:
        assert "mode=date_aware" in line and "kept_at_line_total" not in line, line
        assert target not in persisted


def test_flag_on_with_nothing_recorded_selects_as_before_and_says_so(monkeypatch, capsys):
    markets, target = _window_slate()
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "1")
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_BOARD_LINES", "1")
    line = _run_with(monkeypatch, capsys, {"KXMLBSPREAD": markets})
    assert "mode=board_lines" in line and "demand_events=0" in line, line
    assert "kept_at_line_total=0" in line
    assert target not in _persisted("KXMLBSPREAD")


def test_a_failing_board_line_pass_falls_back_and_still_writes(monkeypatch, capsys):
    """An optimisation must not cost the tick its write."""
    markets, _target = _window_slate()
    _seed_demand()
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_DATE_AWARE", "1")
    monkeypatch.setenv("SYNDICATE_KALSHI_PRECAP_BOARD_LINES", "1")

    def _boom(*_args, **_kwargs):
        raise RuntimeError("resolver exploded")

    monkeypatch.setattr(mod, "board_line_distances", _boom)
    monkeypatch.setattr(mod, "sports_series", lambda: ("KXMLBSPREAD",))
    monkeypatch.setattr(
        mod,
        "fetch_series_markets",
        lambda series: {"markets": markets, "strategy": "series_filter"},
    )
    mod.run_kalshi_odds_refresh(force=True)
    out = capsys.readouterr().out
    assert "PRECAP_BOARD_LINES_FAILED series=KXMLBSPREAD RuntimeError" in out, out
    assert len(_persisted("KXMLBSPREAD")) == CAP
