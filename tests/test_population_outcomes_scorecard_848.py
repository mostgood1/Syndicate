"""Todo #848: the two suspected scorecard grading defects, each fixed per line.

BOTH SHIP DEFAULT-OFF behind `SYNDICATE_SCORECARD_848_GRADING` (absent = the old grading, `soccer/1` and
`nhl/1`): the version bump resets the sport's scorecard and optimizer history, and while it refills the
optimizer overlay's rank / stake factors for that sport drop out, which makes the load a betting change. So every
fix below is shown BOTH ways through the same code: switch on (fixed) and absent (exactly as before).

SOCCER (`population_outcomes_soccer`, `soccer/2`). A goal-scorer row settles on its OWN side. Until 2026-11-18
the side was never read, so `player_goal_scorer_anytime|<player>|full|no|` was graded as its `yes`: Erling
Haaland and Harry Kane, 0 goals each on 2026-11-07, had their `no` rows settled LOSS. Every test below on a
`no` row fails on `soccer/1` (off != on). The `yes` rows are pinned unchanged beside them.

The fixtures are `test_population_outcomes_soccer`'s REAL ones (Barcelona 7-2 Racing Santander, 2026-09-16):
Dani Olmo appeared and did not score, Lamine Yamal scored, Jules Kounde did not appear.
"""

from __future__ import annotations

import json

import pytest

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared import population_outcomes as po
from syndicate.features.shared import population_outcomes_nhl as pon
from syndicate.features.shared import population_outcomes_soccer as pos
from tests.test_population_outcomes_soccer import (  # noqa: F401  (the autouse fixture must be imported to run)
    BARCA,
    DEPOR,
    RECORDS,
    _no_team_artifacts,
    _settle,
    _settler,
    bs,
)

SWITCH = pos.GRADING_848_ENV


@pytest.fixture
def grading_on(monkeypatch):
    monkeypatch.setenv(SWITCH, "on")


@pytest.fixture
def grading_absent(monkeypatch):
    monkeypatch.delenv(SWITCH, raising=False)


ANYTIME = f"{BARCA}|player_goal_scorer_anytime|{{}}|full|yes|"
FIRST = f"{BARCA}|player_first_goal_scorer|{{}}|full|yes|"


# --- soccer: the side of a goal-scorer row ------------------------------------------------------------


def test_anytime_no_wins_for_a_player_who_played_and_did_not_score(grading_on):
    assert _settle(ANYTIME.format("dani olmo")) == ("loss", None)  # yes, unchanged
    assert _settle(ANYTIME.format("dani olmo"), side="no") == ("win", None)  # soccer/1 said loss


def test_anytime_no_loses_for_a_scorer(grading_on):
    assert _settle(ANYTIME.format("lamine yamal")) == ("win", None)
    assert _settle(ANYTIME.format("lamine yamal"), side="no") == ("loss", None)  # soccer/1 said win


def test_a_no_row_on_a_player_who_did_not_appear_is_still_void(grading_on):
    assert _settle(ANYTIME.format("jules kounde"), side="no") == (None, "dnp_void")


def test_first_and_last_scorer_no_sides_invert_too(grading_on):
    # First goal Joao Cancelo 8', last Lamine Yamal 89'.
    assert _settle(FIRST.format("maguette gueye")) == ("loss", None)
    assert _settle(FIRST.format("maguette gueye"), side="no") == ("win", None)
    last = f"{BARCA}|player_last_goal_scorer|lamine yamal|full|yes|"
    assert _settle(last, side="no") == ("loss", None)


def test_the_no_scorer_selection_respects_its_side(grading_on):
    no_scorer = ANYTIME.format("no scorer")
    assert _settle(no_scorer) == ("loss", None)  # nine goals were scored
    assert _settle(no_scorer, side="no") == ("win", None)


def test_an_unknown_side_on_a_scorer_row_refuses_rather_than_grading_as_yes(grading_on):
    assert _settle(ANYTIME.format("dani olmo"), side="over") == (None, "unsettleable_side_or_line")


def test_reachability_a_no_row_reaches_the_graded_population_as_a_win(grading_on):
    """Through `grade_population` itself, the scorecard's own path, not the settler alone."""
    record = dict(RECORDS[ANYTIME.format("dani olmo")])
    record["k"] = record["k"].replace("|full|yes|", "|full|no|")
    graded, ungraded = bs.grade_population([record], {}, extra_settler=_settler())
    assert len(graded) == 1 and graded[0]["y"] == 1.0, (graded, ungraded)


def test_absent_the_soccer_side_is_ignored_exactly_as_before(grading_absent):
    """off != on: the same rows, switch absent, grade the way `soccer/1` always did."""
    assert _settle(ANYTIME.format("dani olmo"), side="no") == ("loss", None)
    assert _settle(ANYTIME.format("lamine yamal"), side="no") == ("win", None)
    assert _settle(ANYTIME.format("dani olmo"), side="over") == ("loss", None)


def _reloaded_versions(monkeypatch, value):
    import importlib

    if value is None:
        monkeypatch.delenv(SWITCH, raising=False)
    else:
        monkeypatch.setenv(SWITCH, value)
    importlib.reload(pos)
    importlib.reload(pon)
    return pos.GRADER_VERSION, pon.GRADER_VERSION, po.build_extra_settler().sport_versions


@pytest.fixture
def restore_versions(monkeypatch):
    yield
    import importlib

    monkeypatch.delenv(SWITCH, raising=False)
    importlib.reload(pos)
    importlib.reload(pon)


def test_the_versions_move_only_with_the_switch(monkeypatch, restore_versions):
    soccer, nhl, sports = _reloaded_versions(monkeypatch, None)
    assert (soccer, nhl) == ("soccer/1", "nhl/1") and sports["soccer"] == "soccer/1" and sports["nhl"] == "nhl/1"
    for off in ("off", "0", "", "no"):
        assert _reloaded_versions(monkeypatch, off)[:2] == ("soccer/1", "nhl/1"), off
    soccer, nhl, sports = _reloaded_versions(monkeypatch, "on")
    assert (soccer, nhl) == ("soccer/2", "nhl/2") and sports["soccer"] == "soccer/2" and sports["nhl"] == "nhl/2"


# --- NHL: a live row is graded only if its own book was still quoting it --------------------------------
#
# REAL rows and state entries, copied from the fleet 2026-11-18 (trimmed to the keys the settler reads):
# - `2026-10-17__nhl__part000.jsonl`: Cole Caufield goals over 1.5, live, sighted 23:53:11Z at BetRivers +480
#   (the row's best price), graded WIN on the final; and Nick Suzuki goals over 0.5 at FanDuel +195.
# - `nhl_source/tracking/book_quotes/2026-10-17.state.json` ([line, price, last_seen]): BetRivers' +480 was last
#   seen 22:50:21Z, 25 minutes BEFORE puck drop, and never again; ESPN Bet quoted the same line live at +300 and
#   was last seen 01:20:57Z; FanDuel's Suzuki quote was last seen 23:28:17Z, after its row's sighting.

NHL_EVENT = "984292d22f1502fb5ec22d5619c3d12c"
CAUFIELD = {"at": "Buffalo Sabres", "ba": 24891.4, "bk": "betrivers", "bq": 1, "ct": "2026-10-17T23:15:36Z",
            "fm": "consensus", "fp": 0.3486, "gs": "live", "ht": "Montréal Canadiens",
            "k": f"{NHL_EVENT}|goals|cole caufield|full|over|1.5", "kind": "prop", "me": None, "mp": 0.1209,
            "px": 480, "sport": "nhl", "t": "2026-10-17T23:53:11Z"}
SUZUKI = {"at": "Buffalo Sabres", "ba": 15232.8, "bk": "fanduel", "bq": 3, "ct": "2026-10-17T23:10:00Z",
          "fm": "consensus", "fp": 0.3285, "gs": "live", "ht": "Montréal Canadiens",
          "k": f"{NHL_EVENT}|goals|nick suzuki|full|over|0.5", "kind": "prop", "me": None, "mp": 0.2789,
          "px": 195, "sport": "nhl", "t": "2026-10-17T23:17:17Z"}
QUOTE_STATE = json.dumps({
    f"nhl|prop|{NHL_EVENT}|betrivers|full|GOALS|over|Cole Caufield|1.5": [1.5, 480, "2026-10-17T22:50:21Z"],
    f"nhl|prop|{NHL_EVENT}|espnbet|full|GOALS|over|Cole Caufield|1.5": [1.5, 300, "2026-10-18T01:20:57Z"],
    f"nhl|prop|{NHL_EVENT}|fanduel|full|GOALS|over|Nick Suzuki|0.5": [0.5, 200, "2026-10-17T23:28:17Z"],
    # A pre-last-seen entry (two elements): unknown, never stale.
    f"nhl|prop|{NHL_EVENT}|hardrockbet|full|GOALS|over|Cole Caufield|1.5": [1.5, 450],
})
STATE_PATH = "nhl_source/tracking/book_quotes/2026-10-17.state.json"


class _Exports:
    def __init__(self, files):
        self.files, self.calls = dict(files), []

    def __call__(self, relative_path):
        self.calls.append(relative_path)
        return self.files.get(relative_path)


@pytest.fixture
def nhl_graded_win(monkeypatch):
    """The NHL API half is `test_population_outcomes_nhl`'s; here every row grades WIN without a read."""
    monkeypatch.setattr(pon.NhlPopulationSettler, "settle", lambda self, shaped: ("win", "nhl_box"))
    monkeypatch.setenv(SWITCH, "on")


def _nhl(record, exports=None, **changes):
    record = {**record, **changes}
    settler = pon.NhlPopulationSettler(fetch_export=exports or _Exports({STATE_PATH: QUOTE_STATE}))
    shaped, why = bs.scorecard_record(record)
    assert shaped is not None, why
    return settler(shaped, mbs.view_from_record(record)), settler


def test_a_live_row_priced_on_a_quote_its_book_stopped_returning_before_puck_drop_is_void(nhl_graded_win):
    (result, reason), settler = _nhl(CAUFIELD)
    assert (result, reason) == (None, "live_quote_unseen_at_sighting")  # nhl/1 graded it WIN at +480
    assert settler.counters["live_quote_unseen"] == 1


def test_the_same_line_at_a_book_still_quoting_live_is_graded(nhl_graded_win):
    assert _nhl(CAUFIELD, bk="espnbet")[0] == ("win", "nhl_box")
    assert _nhl(SUZUKI)[0] == ("win", "nhl_box")


def test_the_window_is_the_boards_300_seconds_before_the_sighting(nhl_graded_win):
    # BetRivers last seen 22:50:21Z: 299 s later still graded, 301 s later void.
    assert pon.LIVE_QUOTE_SEEN_MAX_SECONDS == 300.0
    assert _nhl(CAUFIELD, t="2026-10-17T22:55:20Z", gs="live")[0] == ("win", "nhl_box")
    assert _nhl(CAUFIELD, t="2026-10-17T22:55:22Z", gs="live")[0] == (None, "live_quote_unseen_at_sighting")


def test_a_pregame_row_is_never_checked(nhl_graded_win):
    exports = _Exports({STATE_PATH: QUOTE_STATE})
    (result, _), _settler_obj = _nhl(CAUFIELD, exports, gs="pregame", t="2026-10-16T12:00:00Z")
    assert result == "win" and exports.calls == []


def test_an_unknown_last_seen_is_graded_as_before_and_counted(nhl_graded_win):
    (result, _), settler = _nhl(CAUFIELD, bk="hardrockbet")  # two-element state entry
    assert result == "win" and settler.counters["live_quote_unknown:no_state_entry"] == 1
    (result, _), settler = _nhl(CAUFIELD, _Exports({}))  # no state file at all
    assert result == "win" and settler.counters["quote_state_missing"] >= 1


def test_a_view_without_the_sighting_fields_is_graded_as_before(nhl_graded_win):
    settler = pon.NhlPopulationSettler(fetch_export=_Exports({STATE_PATH: QUOTE_STATE}))
    shaped, _ = bs.scorecard_record(CAUFIELD)
    view = {key: value for key, value in mbs.view_from_record(CAUFIELD).items() if key not in ("sighted_at", "bookmaker")}
    assert settler(shaped, view) == ("win", "nhl_box")
    assert settler.counters["live_quote_unknown:no_view_fields"] == 1


def test_the_view_carries_the_sighting_and_the_book():
    view = mbs.view_from_record(CAUFIELD)
    assert view["sighted_at"] == "2026-10-17T23:53:11Z" and view["bookmaker"] == "betrivers"
    assert view["phase"] == "live"


def test_reachability_through_grade_population_and_the_composite(nhl_graded_win):
    """The scorecard's own wiring: `build_extra_settler` hands `fetch_export` to the NHL settler by signature."""
    exports = _Exports({STATE_PATH: QUOTE_STATE})
    composite = po.build_extra_settler(fetch_export=exports)
    graded, ungraded = bs.grade_population([CAUFIELD], {}, extra_settler=composite)
    assert graded == [] and ungraded == {"extra_live_quote_unseen_at_sighting": 1}
    graded, ungraded = bs.grade_population([{**CAUFIELD, "bk": "espnbet"}], {}, extra_settler=composite)
    assert len(graded) == 1 and graded[0]["y"] == 1.0 and not ungraded
    assert STATE_PATH in exports.calls


def test_absent_the_stale_live_row_grades_exactly_as_before_and_nothing_is_read(nhl_graded_win, monkeypatch):
    """off != on: the Caufield row, switch absent, is the WIN `nhl/1` graded -- and the sidecar is never read."""
    monkeypatch.delenv(SWITCH, raising=False)
    exports = _Exports({STATE_PATH: QUOTE_STATE})
    (result, reason), settler = _nhl(CAUFIELD, exports)
    assert (result, reason) == ("win", "nhl_box") and exports.calls == [] and not settler.counters
    graded, ungraded = bs.grade_population([CAUFIELD], {}, extra_settler=po.build_extra_settler(fetch_export=exports))
    assert len(graded) == 1 and graded[0]["y"] == 1.0 and not ungraded
