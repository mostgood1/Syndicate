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
            "game": copy.deepcopy(final["gameData"]["game"]),
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


# --- card settler (generated native/tools/eval/settle_locked_policy_cards.py) ---------

from syndicate.features.mlb.native.tools.eval import settle_locked_policy_cards as slp  # noqa: E402


def _card(tmp_path: Path, date: str) -> Path:
    card = {
        "date": date,
        "markets": {
            "totals": {
                "recommendations": [
                    {"market": "totals", "game_pk": 849817, "selection": "under", "market_line": 7.5,
                     "stake_u": 1.0, "odds": -110},
                ]
            },
            "ml": {
                "recommendations": [
                    {"market": "ml", "game_pk": 849817, "selection": "away", "market_line": 0.0,
                     "stake_u": 1.0, "odds": 120},
                ]
            },
        },
    }
    path = tmp_path / f"daily_summary_{date.replace('-', '_')}_locked_policy.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    return path


def _settle_with(monkeypatch, tmp_path, date, feed):
    monkeypatch.setattr(slp, "_load_feed", lambda d, pk, **kw: copy.deepcopy(feed))
    return slp._settle_card(_card(tmp_path, date))


def _reasons(out) -> list[str]:
    return [row.get("reason") for row in out.get("unresolved_recommendations") or []]


def test_card_settler_refuses_a_postponed_game_instead_of_grading_0_0(monkeypatch, tmp_path):
    assert slp._feed_is_final(_postponed_feed()) is False
    out = _settle_with(monkeypatch, tmp_path, SLATE, _postponed_feed())
    assert out["settled_n"] == 0
    assert _reasons(out) == ["game not final", "game not final"]


def test_card_settler_never_grades_the_slate_on_the_makeup_game(monkeypatch, tmp_path):
    out = _settle_with(monkeypatch, tmp_path, SLATE, _rescheduled_final_feed())
    assert out["settled_n"] == 0
    assert _reasons(out) == ["game rescheduled off slate date"] * 2


def test_card_settler_reachability_grades_on_the_day_it_was_played(monkeypatch, tmp_path):
    """off != on: the same card dated the makeup day settles (TB 3, CLE 1)."""
    out = _settle_with(monkeypatch, tmp_path, "2026-10-18", _rescheduled_final_feed())
    assert out["settled_n"] == 2
    results = sorted((row["market"], row["result"]) for row in out["_settled_rows"])
    assert results == [("ml", "win"), ("totals", "win")]


def test_load_feed_never_caches_the_makeup_game_under_the_slate_date(monkeypatch, tmp_path):
    stale = tmp_path / "feed_live" / SLATE / "849817.json.gz"
    monkeypatch.setattr(slp, "_feed_live_path", lambda date, pk: tmp_path / "feed_live" / date / f"{pk}.json.gz")
    monkeypatch.setattr(slp, "TRACKED_DATA_ROOT", tmp_path / "tracked")
    import syndicate.features.mlb.sim_engine.data.statsapi as statsapi

    monkeypatch.setattr(statsapi.StatsApiClient, "with_default_cache", classmethod(lambda cls, **kw: object()))
    monkeypatch.setattr(statsapi, "fetch_game_feed_live", lambda client, pk: _rescheduled_final_feed())
    with pytest.raises(FileNotFoundError):
        slp._load_feed(SLATE, 849817)
    assert not stale.exists()
    # Reachability: the makeup day's own path IS written.
    assert slp._load_feed("2026-10-18", 849817)["gameData"]["status"]["detailedState"] == "Final"
    assert (tmp_path / "feed_live" / "2026-10-18" / "849817.json.gz").exists()


# --- evaluation-ledger grader (shared/graded_outcomes.py) -------------------------------

from syndicate.features.shared import graded_outcomes as go  # noqa: E402


@pytest.fixture
def ledger_slate(monkeypatch):
    feeds: dict[str, dict] = {}
    monkeypatch.setattr(go, "_mlb_slate_game_pks", lambda date: {849817})
    monkeypatch.setattr(go, "_load_cached_mlb_feed", lambda date, pk: copy.deepcopy(feeds.get(date)))
    monkeypatch.setattr(
        go,
        "_mlb_card_graded_rows_for_date",
        lambda date: [{"game_pk": 849817, "market": "totals", "result": "win", "date": date}],
    )
    return feeds


@pytest.mark.parametrize("feed_fn", [_postponed_feed, _rescheduled_final_feed], ids=["postponed", "makeup-game"])
def test_ledger_grader_emits_nothing_for_a_game_not_played_on_the_slate_date(ledger_slate, feed_fn):
    ledger_slate[SLATE] = feed_fn()
    rows = go._mlb_graded_rows_for_date(SLATE)
    assert rows == []  # no score rows, no box row, and the card's invented row is dropped
    diag = go.score_row_diagnostics("mlb", SLATE)
    assert diag["games_not_played_on_date"] == 1
    assert diag["games_graded"] == 0


def test_ledger_grader_reachability_grades_the_makeup_day(ledger_slate):
    ledger_slate["2026-10-18"] = _rescheduled_final_feed()
    rows = go._mlb_graded_rows_for_date("2026-10-18")
    assert any(go.is_score_row(row) for row in rows)
    assert any(row.get("market") == "totals" and row.get("result") == "win" for row in rows)
    assert go.score_row_diagnostics("mlb", "2026-10-18")["games_not_played_on_date"] == 0
