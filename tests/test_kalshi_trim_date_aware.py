"""The GLOBAL trim spends its 6,000 slots on the board's games, not on order.

`fa6c4c19` made the PER-SERIES cap date-aware and `_trim_to_storage_bounds`
immediately re-applied the identical date-blind slice one level up: both of its
passes truncate with `markets[:room]`, i.e. in ARRIVAL order, on the set
`select_markets_for_cap` had just chosen by date.

MEASURED by replaying the mirrored production artifact of the
2026-09-09T22:20:23Z tick (46 series, 6,132 markets offered) through both modes
with the production demand shape and `board_dates=['2026-09-09']`:

    budget  arrival cut_in_window   date_aware cut_in_window   retained
     6000        0 / 132                0 / 132               6000 = 6000
     4000     1011 / 2132             926 / 2132              4000 = 4000
     3000     1964 / 3132            1879 / 3132              3000 = 3000
     2000     2704 / 4132            2407 / 4132              2000 = 2000

The retained COUNT is identical on every row -- `MAX_STORED_MARKETS` and
`PER_SPORT_FLOOR_MARKETS` are untouched, because removing the 6,000 bound is a
~2.5x worker-CPU change on a join already at 20-26s and that decision is not
this one. What changes is WHICH markets fill the slots.

THE RESIDUAL IS A BUDGET SHORTFALL, NOT A SELECTION DEFECT, and saying so is the
point: on that tick every remaining in-window cut is MLB, whose 2,963 rungs for
the board's own date exceed its demand-weighted cap of 1,375 on their own. The
counters now expose that rather than hiding it, which is exactly what
`PRECAP_SELECT` did for `KXMLBHRR` one level down.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from pipeline import kalshi_odds_refresh as mod


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_REPORTS_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    for name in (
        "SYNDICATE_KALSHI_TRIM_DATE_AWARE",
        "SYNDICATE_KALSHI_PRECAP_DATE_AWARE",
        "SYNDICATE_KALSHI_PRECAP_WINDOW_AHEAD_DAYS",
        "SYNDICATE_KALSHI_PRECAP_WINDOW_BACK_DAYS",
        "SYNDICATE_KALSHI_FORWARD_DATE_SPORTS",
        "SYNDICATE_KALSHI_SOCCER_FORWARD_DATES",
    ):
        monkeypatch.delenv(name, raising=False)
    (tmp_path / "intelligence").mkdir(parents=True, exist_ok=True)
    yield


@pytest.fixture(autouse=True)
def small_budget(monkeypatch):
    """1,000 slots with a 300 floor -- production's 6,000/300 ratio, small
    enough to reason about exactly. The same fixture the floor's own suite uses,
    so the two files are describing one system."""
    monkeypatch.setattr(mod, "MAX_STORED_MARKETS", 1000)
    monkeypatch.setattr(mod, "PER_SPORT_FLOOR_MARKETS", 300)


@pytest.fixture(autouse=True)
def sport_map(monkeypatch):
    mapping = {
        "KXMLBGAME": "mlb",
        "KXMLBTOTAL": "mlb",
        "KXSOCCER": "soccer",
        "KXWNBA": "wnba",
        "KXNCAAFTOTAL": "ncaaf",
    }
    from syndicate.features.shared import kalshi_catalogue

    monkeypatch.setattr(kalshi_catalogue, "sport_for_series", lambda s: mapping.get(str(s)))


BOARD_DAY = "2026-09-09"
BOARD_DATES = [BOARD_DAY]


def _event(day: str, teams: str) -> str:
    """Kalshi's own event segment: `26SEP09BALSTL`."""
    parsed = date.fromisoformat(day)
    return f"{parsed.strftime('%y%b%d').upper()}{teams}"


def _dated(series: str, day: str, n: int, teams: str = "BALSTL") -> list[dict]:
    event = _event(day, teams)
    return [
        {
            "ticker": f"{series}-{event}-{i}",
            "series": series,
            # A settlement deadline days after the game. Anything dating a
            # market off this field would put every market below on one date.
            "close_time": "2026-09-30T23:10:00Z",
        }
        for i in range(n)
    ]


def _undated(series: str, n: int) -> list[dict]:
    # A real shape: an event segment with no readable date, which is what an
    # unparseable player prop looks like to `game_date_from_ticker`.
    return [{"ticker": f"{series}-SEASON-{i}", "series": series} for i in range(n)]


def _days(offset: int) -> str:
    return (date.fromisoformat(BOARD_DAY) + timedelta(days=offset)).isoformat()


def _dates_of(markets):
    from syndicate.features.shared.kalshi_catalogue import game_date_from_ticker

    out: dict[str | None, int] = {}
    for m in markets:
        day = game_date_from_ticker(m["ticker"])
        out[day] = out.get(day, 0) + 1
    return out


def _trim(per_series, **kw):
    counters: dict = {}
    kept, trimmed, by_sport = mod._trim_to_storage_bounds(
        per_series, kw.pop("demand", None), counters=counters, **kw
    )
    return kept, trimmed, by_sport, counters


# --------------------------------------------------------------------------
# THE BUDGET. Asserted first, because a selection fix that grows the working
# set is a ~2.5x worker-CPU change wearing a coverage fix's clothes.
# --------------------------------------------------------------------------


@pytest.mark.parametrize("date_aware", [False, True])
def test_the_retained_count_is_the_same_budget_under_both_modes(date_aware):
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(30), 900)),
        (20.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 900)),
        (30.0, "KXSOCCER", _dated("KXSOCCER", BOARD_DAY, 400)),
    ]
    kept, trimmed, _by_sport, counters = _trim(
        per_series, board_dates=BOARD_DATES, date_aware=date_aware
    )
    assert len(kept) == mod.MAX_STORED_MARKETS == 1000
    assert trimmed == 2200 - 1000
    assert counters["kept"] + counters["cut"] == counters["offered"] == 2200


@pytest.mark.parametrize("date_aware", [False, True])
def test_under_the_budget_nothing_is_cut_in_either_mode(date_aware):
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(30), 100)),
        (20.0, "KXSOCCER", _dated("KXSOCCER", BOARD_DAY, 100)),
    ]
    kept, trimmed, _by_sport, counters = _trim(
        per_series, board_dates=BOARD_DATES, date_aware=date_aware
    )
    assert (len(kept), trimmed) == (200, 0)
    assert counters["cut"] == 0


def test_the_budget_is_identical_market_for_market_across_modes():
    """Not just the same count -- the same count on the SAME input, so a
    difference in `cut_in_window` cannot be a difference in how much was spent.
    """
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(21), 700) + _undated("KXMLBGAME", 50)),
        (20.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 600)),
        (30.0, "KXSOCCER", _dated("KXSOCCER", _days(3), 400)),
    ]
    off = _trim(per_series, board_dates=BOARD_DATES, date_aware=False)
    on = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert len(off[0]) == len(on[0]) == 1000
    assert off[1] == on[1]
    assert off[3]["kept"] == on[3]["kept"]
    assert off[3]["cut"] == on[3]["cut"]


# --------------------------------------------------------------------------
# THE SELECTION. Which 1,000, and the counter that proves it.
# --------------------------------------------------------------------------


def test_in_window_markets_survive_where_out_of_window_ones_are_cut():
    """THE DEFECT. The far-dated series is FRESHER, so arrival order spends the
    sport's whole allowance on games three weeks out."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(21), 900, teams="XXXYYY")),
        (99.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 900)),
    ]
    off_kept, _t, _b, off_counts = _trim(per_series, board_dates=BOARD_DATES, date_aware=False)
    on_kept, _t2, _b2, on_counts = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)

    assert len(off_kept) == len(on_kept) == 1000
    # Arrival order keeps the far-dated ladder and destroys the board's own day.
    assert _dates_of(off_kept).get(BOARD_DAY, 0) < _dates_of(on_kept)[BOARD_DAY]
    assert on_counts["cut_in_window"] < off_counts["cut_in_window"]
    assert on_counts["cut_in_window"] == 0
    assert on_counts["kept_in_window"] == 900


def test_off_is_not_on_and_the_counter_says_which_ran():
    """REACHABILITY. Both modes report `mode=` and the numbers differ, so a flag
    believed on and inert is a reading rather than an inference."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(21), 900, teams="XXXYYY")),
        (99.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 900)),
    ]
    off = _trim(per_series, board_dates=BOARD_DATES, date_aware=False)[3]
    on = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)[3]
    assert off["mode"] == "arrival"
    assert on["mode"] == "date_aware"
    assert off["cut_in_window"] != on["cut_in_window"]
    # And the by-sport split names WHICH slate paid, not just how much.
    assert off["cut_in_window_by_sport"] == {"mlb": off["cut_in_window"]}
    assert on["cut_in_window_by_sport"] == {}


def test_the_flag_is_off_when_absent(monkeypatch):
    monkeypatch.delenv("SYNDICATE_KALSHI_TRIM_DATE_AWARE", raising=False)
    assert mod.trim_date_aware_enabled() is False
    for raw in ("1", "true", "YES", "on"):
        monkeypatch.setenv("SYNDICATE_KALSHI_TRIM_DATE_AWARE", raw)
        assert mod.trim_date_aware_enabled() is True
    for raw in ("0", "off", "", "nope"):
        monkeypatch.setenv("SYNDICATE_KALSHI_TRIM_DATE_AWARE", raw)
        assert mod.trim_date_aware_enabled() is False


def test_the_arrival_mode_is_byte_identical_to_the_old_rule():
    """The flag's OFF branch must be the code that shipped, not a rewrite of it
    that happens to agree on counts."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(21), 900, teams="XXXYYY")),
        (99.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 900)),
    ]
    legacy = mod._trim_to_storage_bounds(per_series)
    flagged = mod._trim_to_storage_bounds(per_series, board_dates=BOARD_DATES, date_aware=False)
    assert [m["ticker"] for m in legacy[0]] == [m["ticker"] for m in flagged[0]]
    assert legacy[1:] == flagged[1:]


def test_the_kept_set_is_emitted_in_the_inputs_own_order():
    """A selection change that also reorders makes an unrelated regression
    impossible to attribute."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(21), 400, teams="XXXYYY")),
        (20.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 900)),
    ]
    kept = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)[0]
    order = [m["ticker"] for m in kept]
    offered = [m["ticker"] for _a, _s, ms in per_series for m in ms]
    assert order == [t for t in offered if t in set(order)]


# --------------------------------------------------------------------------
# THE FLOOR. Untouched, and it has to stay that way -- it is the only thing
# stopping a sport whose slate opens between cycles from a self-fulfilling zero.
# --------------------------------------------------------------------------


def test_the_per_sport_floor_still_holds_under_the_date_aware_rule():
    """MLB is fresher, far larger, AND entirely in-window; soccer is out of it.
    Relevance must not be allowed to evict a sport below its floor."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", BOARD_DAY, 2000)),
        (20.0, "KXSOCCER", _dated("KXSOCCER", _days(40), 500, teams="AAABBB")),
    ]
    kept, _t, by_sport, _c = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert by_sport["soccer"] == 300
    assert by_sport["mlb"] == 700
    assert len(kept) == 1000


def test_the_floor_is_a_guarantee_not_a_reservation_under_the_date_aware_rule():
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", BOARD_DAY, 2000)),
        (20.0, "KXSOCCER", _dated("KXSOCCER", _days(40), 40, teams="AAABBB")),
    ]
    _kept, _t, by_sport, _c = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert by_sport["soccer"] == 40
    assert by_sport["mlb"] == 960


def test_demand_weighted_caps_still_apply_under_the_date_aware_rule():
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", BOARD_DAY, 2000)),
        (20.0, "KXSOCCER", _dated("KXSOCCER", BOARD_DAY, 2000)),
    ]
    caps = mod._sport_slot_caps(["mlb", "soccer"], {"mlb": 400, "soccer": 100})
    _kept, _t, by_sport, _c = _trim(
        per_series,
        demand={"mlb": 400, "soccer": 100},
        board_dates=BOARD_DATES,
        date_aware=True,
    )
    assert by_sport["mlb"] == caps["mlb"]
    assert by_sport["soccer"] == caps["soccer"]


# --------------------------------------------------------------------------
# THE WINDOW. The blocker this fix had to solve: the trim runs BEFORE any join,
# so it cannot see the board's date and must never guess it from `today`.
# --------------------------------------------------------------------------


def test_a_forward_selected_date_keeps_that_date_rather_than_today(monkeypatch):
    """THE FRIDAY CASE. `selected_date` can be forward and is counted in
    Central, so a trim that assumed "today" would discard the very slate the
    board was about to price."""
    today = date.today().isoformat()
    forward = (date.today() + timedelta(days=5)).isoformat()
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", today, 900, teams="TODAYY")),
        (20.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", forward, 900, teams="FWDFWD")),
    ]
    kept, _t, _b, counters = _trim(per_series, board_dates=[forward], date_aware=True)
    seen = _dates_of(kept)
    assert seen[forward] == 900
    assert seen.get(today, 0) == 100
    assert counters["cut_in_window"] == 0
    assert counters["board_dates"] == [forward]


def test_the_board_records_the_date_it_built_for(monkeypatch, tmp_path):
    """THE PLUMBING. `join_to_board` is the only place that sees the board and
    the catalogue in one breath, so it WRITES the window the next trim reads --
    the same mechanism `board_demand` already uses for sports."""
    from syndicate.features.shared.refresh_state_store import read_json_file

    mod._record_board_demand([{"sport": "mlb"}], selected_date="2026-09-13")
    state = read_json_file(mod.markets_artifact_path()) or {}
    assert [s["date"] for s in state["board_date_samples"]] == ["2026-09-13"]
    assert mod.board_dates_from_state(state) == ["2026-09-13"]

    # A SECOND, DIFFERENT BUILD UNIONS RATHER THAN OVERWRITING. The builds
    # alternate between the full slate and a forward-date board; last-write-wins
    # would hand the trim a window that flips every few minutes, which is the
    # rotation this whole fix exists to stop, reintroduced in the plumbing.
    mod._record_board_demand([{"sport": "mlb"}], selected_date="2026-09-14")
    state = read_json_file(mod.markets_artifact_path()) or {}
    assert mod.board_dates_from_state(state) == ["2026-09-13", "2026-09-14"]


def test_a_board_date_ages_out_of_the_window():
    """It DECAYS on the same 6h clock as demand -- a finished slate must stop
    holding slots, or the window only ever grows."""
    import time

    stale = time.time() - (mod._DEMAND_WINDOW_SECONDS + 60)
    state = {
        "board_date_samples": [
            {"at": stale, "date": "2026-08-01"},
            {"at": time.time(), "date": "2026-09-09"},
        ]
    }
    assert mod.board_dates_from_state(state) == ["2026-09-09"]


def test_no_recorded_dates_falls_back_to_the_per_series_window():
    """Cold start, or a worker whose board has not joined in six hours. The
    fallback is WIDER than the truth, which is the safe direction -- it must
    never silently become "today only"."""
    (start, anchor), _ends = mod.trim_windows([], ["mlb"])
    assert (start, anchor) == mod.board_window_dates()
    assert start < anchor


def test_the_window_end_is_per_sport_and_uses_the_joins_own_horizon():
    """`kalshi_board_join._date_verdict` admits a forward fixture only for the
    sports on the forward list, inside THAT sport's horizon. A flat window would
    either strand soccer's +14 fixtures or drag every sport's far-dated
    catalogue inside it -- the 2,910-of-6,000 reading this fix exists to remove.
    """
    from syndicate.features.shared.kalshi_board_join import _FORWARD_HORIZON_DAYS

    (start, anchor), ends = mod.trim_windows(BOARD_DATES, ["mlb", "soccer", "ncaaf"])
    assert (start, anchor) == (BOARD_DAY, BOARD_DAY)
    # MLB plays the same fixture on consecutive days, so it is NOT on the
    # forward list and its window is the slate date exactly.
    assert ends["mlb"] == BOARD_DAY
    assert ends["soccer"] == _days(_FORWARD_HORIZON_DAYS["soccer"])
    # NCAAF has a horizon but is off the default forward list, so its markets
    # cannot join a forward date and the window must not pretend otherwise.
    assert ends["ncaaf"] == BOARD_DAY


def test_a_sport_on_the_forward_list_keeps_its_horizon_in_window(monkeypatch):
    monkeypatch.setenv("SYNDICATE_KALSHI_FORWARD_DATE_SPORTS", "soccer,ncaaf")
    _win, ends = mod.trim_windows(BOARD_DATES, ["ncaaf", "mlb"])
    assert ends["ncaaf"] == _days(7)
    assert ends["mlb"] == BOARD_DAY

    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(3), 900, teams="MLBFWD")),
        (20.0, "KXNCAAFTOTAL", _dated("KXNCAAFTOTAL", _days(3), 900, teams="WIUWIS")),
    ]
    _kept, _t, by_sport, counters = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    # NCAAF's +3 fixtures are joinable and MLB's are not, so the slots go to
    # NCAAF beyond its floor rather than being split on arrival order.
    assert by_sport["ncaaf"] > by_sport["mlb"]
    assert counters["kept_in_window"] == by_sport["ncaaf"]


def test_the_window_never_starts_before_the_earliest_board_date():
    """`_date_verdict` returns `wrong_date` for anything dated before the slate,
    so a back-day would spend relevance on markets that provably cannot join."""
    (start, _anchor), _ends = mod.trim_windows(["2026-09-09", "2026-09-11"], ["mlb"])
    assert start == "2026-09-09"


def test_yesterdays_markets_are_deprioritised_but_not_specially_destroyed():
    """Out of window is not a death sentence -- it is last in line. A market the
    board cannot use still takes a slot nobody else wants."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(-1), 400, teams="PASTPA")),
        (20.0, "KXMLBTOTAL", _dated("KXMLBTOTAL", BOARD_DAY, 400)),
    ]
    kept, trimmed, _b, _c = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert (len(kept), trimmed) == (800, 0)
    assert _dates_of(kept) == {_days(-1): 400, BOARD_DAY: 400}


# --------------------------------------------------------------------------
# UNDATED. Handled deliberately. The daily book counts `undated=569` every tick.
# --------------------------------------------------------------------------


def test_undated_markets_are_reserved_not_silently_destroyed():
    """PLAYER PROPS SKIP THE JOIN'S DATE CHECK ENTIRELY, so a prop whose ticker
    shape does not parse is joinable while being undatable. Evicting it would
    repeat this very defect in a new place -- the reason
    `PRECAP_UNDATED_RESERVE` is 40 and not 0, one level down."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", BOARD_DAY, 2000)),
        (20.0, "KXMLBTOTAL", _undated("KXMLBTOTAL", 500)),
    ]
    kept, _t, _b, counters = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert len(kept) == 1000
    # 10% of the budget, the same fraction the per-series reserve is (40 / 400).
    assert counters["kept_undated"] == mod._trim_undated_reserve(1000) == 100
    assert counters["cut_undated"] == 400


def test_a_wholly_undated_series_is_unaffected_by_the_reserve():
    """A futures ladder has no in-window markets to lose slots to, so it fills
    the budget regardless -- the reserve only bites on a MIXED set."""
    per_series = [(10.0, "KXMLBGAME", _undated("KXMLBGAME", 2000))]
    kept, _t, _b, counters = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert len(kept) == 1000
    assert counters["kept_undated"] == 1000


def test_undated_markets_outrank_a_far_future_ladder():
    """The far-dated series arrives FIRST and is fresher, so arrival order
    spends every slot on it and the undatable props -- which the join can still
    price -- are destroyed."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", _days(60), 1200, teams="FARFAR")),
        (20.0, "KXMLBTOTAL", _undated("KXMLBTOTAL", 50)),
    ]
    off = _trim(per_series, board_dates=BOARD_DATES, date_aware=False)
    on = _trim(per_series, board_dates=BOARD_DATES, date_aware=True)
    assert len(off[0]) == len(on[0]) == 1000
    assert off[3]["kept_undated"] == 0
    assert on[3]["kept_undated"] == 50


# --------------------------------------------------------------------------
# THE BOUND ITSELF. `MAX_STORED_MARKETS` is a CPU budget, NOT an artifact-size
# bound, and the comment that said otherwise was stale.
# --------------------------------------------------------------------------


def test_max_stored_markets_does_not_bound_what_durable_consumers_read():
    """CORRECTED 2026-09-09. The comment on `MAX_STORED_MARKETS` said "Total
    markets kept in the artifact ... the keyvalue store refuses at 8MB", and
    that stopped being true when `state.pop("markets", None)` removed the only
    place the merged list was persisted.

    VERIFIED against the mirrored artifact of the 2026-09-08T18:43:02Z tick:
    `markets_from_state` -> 5,450 across 78 series while `state["count"]` -- which
    IS `len(all_markets)` -- read 3,128. This pins the corrected reading so the
    stale one cannot come back: what is written is bounded per SERIES, and every
    durable consumer reads a set this constant does not describe.
    """
    state = {
        "count": mod.MAX_STORED_MARKETS,
        "series": {
            f"KXS{i}": {"markets": [{"ticker": f"KXS{i}-A-{j}"} for j in range(400)]}
            for i in range(10)
        },
    }
    assert len(mod.markets_from_state(state)) == 4000
    assert len(mod.markets_from_state(state)) > state["count"] - 3000
    # The point: nothing in the write path applies this constant to the series
    # entries, so the read-back set is free to exceed it.
    assert "markets" not in state


# --------------------------------------------------------------------------
# REACHABILITY, at the call site rather than at the function. `learnings.md`:
# presence is not reachability, and four inert fixes in one session were caught
# by an `off != on` test and by nothing else.
# --------------------------------------------------------------------------


def _run_and_read_trim_line(monkeypatch, capsys, markets_by_series):
    monkeypatch.setattr(mod, "sports_series", lambda: tuple(sorted(markets_by_series)))
    monkeypatch.setattr(
        mod,
        "fetch_series_markets",
        lambda series: {"markets": markets_by_series.get(series, []), "strategy": "series_filter"},
    )
    mod.run_kalshi_odds_refresh(force=True)
    line = ""
    for candidate in capsys.readouterr().out.splitlines():
        if "TRIM_SELECT" in candidate:
            line = candidate
    return line


def _far_and_near() -> dict[str, list[dict]]:
    """Four MLB series, each 150 far-forward rungs arriving BEFORE 150 on the
    board's own day. 1,200 markets into a 1,000 budget, and every one of them
    under the 400-per-series precap, so this exercises the GLOBAL trim alone.

    The board day comes from `board_window_dates()` rather than being
    hard-coded, so the assertion is against the window production would compute
    today. `board_dates=[]` in the log line is the honest reading of a worker
    whose board has not joined yet -- the fallback window, not the board's own.
    """
    start, _end = mod.board_window_dates()
    far = (date.fromisoformat(start) + timedelta(days=90)).isoformat()
    return {
        f"KXMLB{i}": _dated(f"KXMLB{i}", far, 150, teams="XXXYYY")
        + _dated(f"KXMLB{i}", start, 150)
        for i in range(4)
    }


@pytest.mark.parametrize(
    "flag,expected", [(None, "mode=arrival"), ("1", "mode=date_aware")]
)
def test_the_env_flag_reaches_the_trim_and_off_is_not_on(
    monkeypatch, capsys, flag, expected, sport_map
):
    from syndicate.features.shared import kalshi_catalogue

    monkeypatch.setattr(kalshi_catalogue, "sport_for_series", lambda s: "mlb")
    if flag is None:
        monkeypatch.delenv("SYNDICATE_KALSHI_TRIM_DATE_AWARE", raising=False)
    else:
        monkeypatch.setenv("SYNDICATE_KALSHI_TRIM_DATE_AWARE", flag)

    line = _run_and_read_trim_line(monkeypatch, capsys, _far_and_near())

    assert expected in line, line
    assert f"bound={mod.MAX_STORED_MARKETS}" in line
    assert "board_dates=[]" in line, "no join has run, so the fallback window is the honest read"
    # SAME BUDGET, DIFFERENT SELECTION -- both halves asserted on one line.
    assert " offered=1200 kept=1000 cut=200" in line, line
    if flag:
        assert " cut_in_window=0 " in line, line
    else:
        assert " cut_in_window=0 " not in line, line


def test_the_trim_counters_reconcile_with_their_own_total():
    """A breakdown that does not reconcile with its own total is the "count that
    looks like coverage" failure this module keeps naming -- and it was last
    found in the line written to prove the floor worked."""
    per_series = [
        (10.0, "KXMLBGAME", _dated("KXMLBGAME", BOARD_DAY, 700) + _undated("KXMLBGAME", 100)),
        (20.0, "KXSOCCER", _dated("KXSOCCER", _days(30), 600, teams="AAABBB")),
    ]
    for aware in (False, True):
        kept, trimmed, by_sport, c = _trim(per_series, board_dates=BOARD_DATES, date_aware=aware)
        assert c["kept"] == len(kept) == sum(by_sport.values())
        assert c["cut"] == trimmed
        assert c["kept"] + c["cut"] == c["offered"] == 1400
        assert c["kept_in_window"] + c["cut_in_window"] == 700
        assert c["kept_undated"] + c["cut_undated"] == 100
        assert sum(c["cut_in_window_by_sport"].values()) == c["cut_in_window"]
