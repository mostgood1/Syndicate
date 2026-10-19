"""A postponed or rescheduled MLB game never grades as final.

Incident: gamePk 849817, TB @ CLE, slate 2026-10-16. StatsAPI reported it
`abstractGameState: "Final"`, `codedGameState: "D"`, `detailedState:
"Postponed"`; the live lens logged `Preview -> Final` with a 0-0 score. Within a
day the SAME gamePk's `feed/live` described the rescheduled game (officialDate
2026-10-18), and after it was played, a TB 3-1 final.

Fixture: `tests/fixtures/mlb_postponed/statsapi_849817.json`, trimmed from the
fleet's StatsAPI payloads. The `feed/live` as it stood at the postponement was
never captured, so `_postponed_feed()` builds it from the REAL schedule status
block plus the 0-0 linescore StatsAPI serves for a game not played.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from syndicate.features.mlb import game_status
from syndicate.features.mlb import live_lens
from syndicate.features.shared import bet_status_mlb as bsm

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "mlb_postponed" / "statsapi_849817.json").read_text(encoding="utf-8")
)
SLATE = "2026-10-16"


def _postponed_feed() -> dict:
    schedule_game = FIXTURE["schedule_game_2026_10_16"]
    final = FIXTURE["feed_live_after_reschedule_final"]
    return {
        "gamePk": 849817,
        "gameData": {
            "status": copy.deepcopy(schedule_game["status"]),
            # At the postponement the game was still filed under its slate date.
            "datetime": {"dateTime": schedule_game["gameDate"], "officialDate": SLATE},
            "teams": copy.deepcopy(final["gameData"]["teams"]),
        },
        "liveData": {
            "linescore": {"innings": [], "teams": {"home": {"runs": 0}, "away": {"runs": 0}}}
        },
    }


def _rescheduled_final_feed() -> dict:
    return copy.deepcopy(FIXTURE["feed_live_after_reschedule_final"])


# --- the mapping itself -------------------------------------------------------


def test_the_fixture_is_the_trap_abstract_final_on_a_postponed_game():
    status = FIXTURE["schedule_game_2026_10_16"]["status"]
    assert status["abstractGameState"] == "Final"
    assert status["codedGameState"] == "D"


def test_postponed_is_not_final_from_feed_schedule_game_or_status_block():
    for payload in (_postponed_feed(), FIXTURE["schedule_game_2026_10_16"], FIXTURE["schedule_game_2026_10_16"]["status"]):
        assert game_status.not_played_reason(payload) == "postponed"
        assert game_status.is_final(payload) is False


def test_text_fallback_when_the_coded_state_is_absent():
    # The lens carries only abstract/detailed: no coded state.
    assert game_status.not_played_reason({"abstract": "Final", "detailed": "Postponed"}) == "postponed"
    assert game_status.not_played_reason({"abstract": "Final", "detailed": "Cancelled"}) == "cancelled"
    assert game_status.not_played_reason({"abstract": "Final", "detailed": "Final"}) is None


def test_a_played_final_is_final():
    assert game_status.is_final(_rescheduled_final_feed()) is True


def test_the_rescheduled_games_result_does_not_belong_to_the_original_slate():
    feed = _rescheduled_final_feed()
    assert game_status.grading_refusal(feed, SLATE) == game_status.REASON_RESCHEDULED
    assert game_status.grading_refusal(feed, "2026-10-18") is None
    assert game_status.grading_refusal(_postponed_feed(), SLATE) == game_status.REASON_NOT_PLAYED


# --- paper / portfolio settlement (bet_status_mlb) ------------------------------


@pytest.fixture
def slate(monkeypatch):
    """The 2026-10-16 schedule as StatsAPI serves it: the postponed game stays
    listed under its original date."""
    monkeypatch.setattr(
        "syndicate.features.mlb.cards._schedule_raw_games",
        lambda date: [copy.deepcopy(FIXTURE["schedule_game_2026_10_16"])],
    )
    feeds: dict[str, dict] = {}
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed",
        lambda date, game_pk, **kw: copy.deepcopy(feeds.get("feed")),
    )
    return feeds


def _order(market: str, **kw) -> dict:
    order = {
        "sport": "mlb",
        "game_pk": 849817,
        "market": market,
        "home_team": "Cleveland Guardians",
        "away_team": "Tampa Bay Rays",
        "commence_time": "2026-10-17T00:00:00Z",
    }
    order.update(kw)
    return order


@pytest.mark.parametrize(
    "order",
    [
        _order("totals", side="Under", line=7.5),
        _order("h2h", side="Tampa Bay Rays"),
        _order("batter_hits", side="Under", line=0.5, player_name="Junior Caminero"),
        _order("totals", segment="first5", side="Under", line=3.5),
    ],
    ids=["total", "moneyline", "prop", "first5"],
)
def test_a_postponed_game_is_refused_not_graded_0_0(slate, order):
    slate["feed"] = _postponed_feed()
    verdict = bsm.mlb_status_resolver(SLATE)(order)
    assert verdict.get("unavailable_reason") == game_status.REASON_NOT_PLAYED, verdict
    assert not verdict.get("is_final")


@pytest.mark.parametrize(
    "order",
    [_order("totals", side="Under", line=7.5), _order("h2h", side="Tampa Bay Rays")],
    ids=["total", "moneyline"],
)
def test_a_rescheduled_games_final_never_grades_the_original_slate(slate, order):
    slate["feed"] = _rescheduled_final_feed()
    verdict = bsm.mlb_status_resolver(SLATE)(order)
    assert verdict.get("unavailable_reason") == game_status.REASON_RESCHEDULED, verdict


def test_reachability_the_same_order_grades_on_the_day_it_was_played(monkeypatch):
    """off != on: the refusal is the guard, not a dead resolver."""
    game = copy.deepcopy(FIXTURE["schedule_game_2026_10_16"])
    game["status"] = {"abstractGameState": "Final", "codedGameState": "F", "detailedState": "Final"}
    game["gameDate"] = "2026-10-18T21:08:00Z"
    monkeypatch.setattr("syndicate.features.mlb.cards._schedule_raw_games", lambda date: [game])
    monkeypatch.setattr(
        "syndicate.features.mlb.box_score_stats.load_final_feed",
        lambda date, game_pk, **kw: _rescheduled_final_feed(),
    )
    verdict = bsm.mlb_status_resolver("2026-10-18")(
        _order("totals", side="Under", line=7.5, commence_time="2026-10-18T21:08:00Z")
    )
    assert verdict.get("unavailable_reason") is None, verdict
    assert verdict["is_final"] is True
    assert verdict["current_value"] == 4.0


def test_the_low_level_final_predicates_refuse_a_postponed_feed():
    feed = _postponed_feed()
    assert bsm._game_is_final(feed) is False
    assert bsm._game_has_started(feed) is False


# --- served live lens -----------------------------------------------------------


def test_the_lens_serves_postponed_not_final():
    # What the port writes into the report for 849817 (measured on the fleet's
    # live_lens_report_2026_10_16.json).
    row = {"gamePk": 849817, "status": {"abstract": "Final", "detailed": "Postponed"}}
    status = live_lens._structured_status(row, fallback_date=SLATE)
    assert status == {"abstract": "Postponed", "detailed": "Postponed"}
    assert live_lens._status_bucket_from_row(row) == "postponed"
    assert live_lens._status_bucket_from_row({"status": status}) == "postponed"


def test_a_real_final_still_buckets_final():
    row = {"status": {"abstract": "Final", "detailed": "Final"}}
    assert live_lens._status_bucket_from_row(row) == "final"
    assert live_lens._structured_status(row, fallback_date=SLATE)["abstract"] == "Final"
