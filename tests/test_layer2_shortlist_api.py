"""`/api/board/layer2-shortlist` — L2-A served as a PURE READ of the artifact.

L2-A cannot be a serve-time pivot the way L1-A (`/api/board/book-grid`) is: a
board recomputed per request cannot be SETTLED. S6 needs a record of what was
recommended and at what price, so the rows are built on refresh-worker inside
`_build_candidate_pool`, persisted, and only read here.

SOURCE ORDER MATTERS, and getting it wrong was a real mistake caught before it
shipped. The rows were first plumbed ONLY onto the canonical board state --
which is written exclusively under `canonical_board_state_enabled()` or the
shadow-compare flag, BOTH default False. Measured on production 2026-08-08:
`read_intelligence_board_state` returned None for every date, while the board
actually serves from `combined_board_window`. The shortlist would have been
built correctly, threaded through three hops correctly, and deposited in a file
nothing writes and nothing reads.

So L2-A now has its OWN artifact and that is the primary source; the board-state
key remains a fallback for whenever the canonical migration lands.

This endpoint exists before the main board switches to L2-A deliberately. The
board currently renders `ranked_all` (the legacy pool: 229 game + 18 prop rows
against Layer 1's 2,726 priced instances). Pointing the template at L2-A rows is
the goal, but the shapes differ, and swapping the data source blind is how a
"working" board renders blank.
"""

from __future__ import annotations

import pytest

from syndicate.app import app


@pytest.fixture
def client():
    return app.test_client()


def _row(sport="mlb", side="home", score=1.5, kind="game"):
    return {
        "sport": sport,
        "event_id": f"evt-{sport}",
        "kind": kind,
        "market": "h2h",
        "side": side,
        "quote": {"price": -110, "bookmaker": "draftkings"},
        "score": {"score": score},
        "board_lane": "opportunity",
    }


def _state(**overrides):
    state = {
        "selected_date": "2026-08-08",
        "layer2_shortlist": {
            "rows": [_row("mlb", "home", 2.0), _row("mlb", "away", 1.0), _row("wnba", "home", 1.5)],
            "per_sport": {"mlb": {"selected": 2}, "wnba": {"selected": 1}},
            "per_sport_ingest": {"mlb": {"quote_rows": 6}, "wnba": {"quote_rows": 4}},
            "active_sports": ["mlb", "wnba"],
            "per_sport_limit": 100,
            "kind_floor": 30,
            "horizon_days": 1,
            "rows_beyond_horizon": 7,
            "opportunities_considered": 42,
        },
    }
    state.update(overrides)
    return state


def _patch_state(monkeypatch, value):
    # Standalone artifact is the primary source now; force the fallback path
    # so these cases still exercise the board-state key.
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: None)
    monkeypatch.setattr(
        "pipeline.intelligence_state.read_intelligence_board_state",
        lambda date: value,
    )


def test_serves_the_persisted_rows(client, monkeypatch):
    _patch_state(monkeypatch, _state())
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()

    assert payload["ok"] is True
    assert payload["shortlist_present"] is True
    assert payload["total_rows"] == 3
    assert len(payload["rows"]) == 3


def test_each_row_carries_the_price_it_recommends(client, monkeypatch):
    """Settlement needs what was recommended at what price. Without this the
    endpoint serves a ranking that cannot be graded."""
    _patch_state(monkeypatch, _state())
    row = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()["rows"][0]

    assert row["quote"]["price"] is not None
    assert row["quote"]["bookmaker"]
    assert row["side"] in {"home", "away"}


def test_sport_filter(client, monkeypatch):
    _patch_state(monkeypatch, _state())
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08&sport=mlb").get_json()

    assert payload["total_rows"] == 2
    assert {row["sport"] for row in payload["rows"]} == {"mlb"}


def test_limit_bounds_rows_but_reports_the_true_total(client, monkeypatch):
    """`returned` vs `total_rows`: a truncated board that reports only what it
    shows reads as complete. #S5 shipped exactly this bug ("2000 of 2726")."""
    _patch_state(monkeypatch, _state())
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08&limit=1").get_json()

    assert payload["returned"] == 1
    assert payload["total_rows"] == 3
    assert len(payload["rows"]) == 1


def test_missing_board_state_is_distinguishable_from_an_empty_shortlist(client, monkeypatch):
    """ABSENT MUST NEVER RENDER AS A VALUE (postmortem rule 6).

    A board state written before this shipped, or an aborted build, carries no
    shortlist. Returning an empty rows list alone would read identically to
    "the gate rejected everything today" -- a missing value wearing a number's
    clothes, which is worse than a blank because it looks authoritative.
    """
    _patch_state(monkeypatch, None)
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()

    assert payload["shortlist_present"] is False
    assert payload["reason"] == "no_shortlist_artifact"
    assert payload["rows"] == []


def test_state_without_the_key_reports_its_own_reason(client, monkeypatch):
    """Distinct from no_board_state: the build ran, the key did not survive.
    That is the exact failure the pool->response->state chain almost shipped."""
    _patch_state(monkeypatch, {"selected_date": "2026-08-08"})
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()

    assert payload["shortlist_present"] is False
    assert payload["reason"] == "no_layer2_shortlist_key"


def test_both_halves_of_the_accounting_are_served(client, monkeypatch):
    """`per_sport` is what was SELECTED, `per_sport_ingest` is what came IN.
    Together they make a sport showing zero attributable to its slate rather
    than to a broken read."""
    _patch_state(monkeypatch, _state())
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()

    assert payload["per_sport"]["mlb"]["selected"] == 2
    assert payload["per_sport_ingest"]["mlb"]["quote_rows"] == 6
    assert payload["rows_beyond_horizon"] == 7
    assert payload["opportunities_considered"] == 42


def test_a_read_failure_does_not_500(client, monkeypatch):
    def _boom(_date):
        raise RuntimeError("artifact unreadable")

    # BOTH reads must be patched. The endpoint tries the standalone artifact
    # FIRST and only falls back to the board state, so patching the fallback
    # alone left this test at the mercy of whatever `reports/intelligence/`
    # happened to hold: with a real `layer2_shortlist_<date>.json` on disk it
    # failed with `shortlist_present is True`, and with an empty reports root it
    # passed. A test whose result depends on the local disk is measuring the
    # disk, not the endpoint.
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", _boom)
    monkeypatch.setattr("pipeline.intelligence_state.read_intelligence_board_state", _boom)
    response = client.get("/api/board/layer2-shortlist?date=2026-08-08")

    assert response.status_code == 200
    assert response.get_json()["shortlist_present"] is False


def test_bad_limit_falls_back_rather_than_erroring(client, monkeypatch):
    _patch_state(monkeypatch, _state())
    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08&limit=notanumber").get_json()
    assert payload["ok"] is True
    assert payload["total_rows"] == 3


# ---------------------------------------------------------------------------
# The PRIMARY source: L2-A's own artifact, independent of the migration flags.
# ---------------------------------------------------------------------------


def _shortlist_payload():
    return {
        "selected_date": "2026-08-08",
        "rows": [_row("mlb", "home", 2.0), _row("wnba", "home", 1.5)],
        "per_sport": {"mlb": {"selected": 1}, "wnba": {"selected": 1}},
        "per_sport_ingest": {"mlb": {"quote_rows": 6}},
        "active_sports": ["mlb", "wnba"],
        "opportunities_considered": 11,
    }


def test_standalone_artifact_is_the_primary_source(client, monkeypatch):
    """Read the artifact FIRST. If this regresses to board-state-first, L2-A
    goes dark in production, because that state is never written there."""
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: _shortlist_payload())

    def _should_not_be_called(_date):
        raise AssertionError("board state was read while the artifact existed")

    monkeypatch.setattr("pipeline.intelligence_state.read_intelligence_board_state", _should_not_be_called)

    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()
    assert payload["shortlist_present"] is True
    assert payload["source"] == "layer2_shortlist_artifact"
    assert payload["total_rows"] == 2


def test_falls_back_to_board_state_when_the_artifact_is_absent(client, monkeypatch):
    """The fallback exists so this keeps working either way once the canonical
    migration lands -- not as the main path."""
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: None)
    monkeypatch.setattr("pipeline.intelligence_state.read_intelligence_board_state", lambda date: _state())

    payload = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()
    assert payload["shortlist_present"] is True
    assert payload["source"] == "board_state"


def test_artifact_read_failure_falls_back_rather_than_500(client, monkeypatch):
    def _boom(_date):
        raise RuntimeError("keyvalue unavailable")

    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", _boom)
    monkeypatch.setattr("pipeline.intelligence_state.read_intelligence_board_state", lambda date: _state())

    response = client.get("/api/board/layer2-shortlist?date=2026-08-08")
    assert response.status_code == 200
    assert response.get_json()["source"] == "board_state"


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    """The artifact must survive the write/read pair it is served through."""
    from pipeline import intelligence_state as istate

    monkeypatch.setattr(istate, "reports_root", lambda: tmp_path)
    written = istate.write_layer2_shortlist("2026-08-08", {"rows": [_row()], "active_sports": ["mlb"]})

    assert written["selected_date"] == "2026-08-08"
    assert written["written_at"]

    back = istate.read_layer2_shortlist("2026-08-08")
    assert back is not None
    assert len(back["rows"]) == 1
    assert back["active_sports"] == ["mlb"]


def test_write_requires_a_date(tmp_path, monkeypatch):
    from pipeline import intelligence_state as istate

    monkeypatch.setattr(istate, "reports_root", lambda: tmp_path)
    assert istate.write_layer2_shortlist("", {"rows": []}) is None
    assert istate.read_layer2_shortlist("") is None


def test_a_shortlist_write_failure_never_breaks_the_pool():
    """The pool must survive a failed shortlist write. Layer 2 is additive to a
    board that already works."""
    import inspect

    from pipeline import intelligence_state as istate

    source = inspect.getsource(istate.IntelligenceStateService._build_candidate_pool)
    assert "LAYER2_SHORTLIST_WRITE_FAILED" in source, "the write is not wrapped"


def test_written_at_is_served(client, monkeypatch):
    """Without a build timestamp, a reading taken after a deploy cannot be told
    apart from one taken before -- so no ranking or wiring change can be
    verified in production. A watcher armed for exactly that polled for ten
    minutes against a pre-fix artifact and could never have known."""
    payload = dict(_shortlist_payload())
    payload["written_at"] = "2026-08-08T02:31:00+00:00"
    payload["cards"] = [_row()]
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: payload)

    served = client.get("/api/board/layer2-shortlist?date=2026-08-08").get_json()
    assert served["written_at"] == "2026-08-08T02:31:00+00:00"
    assert served["cards_present"] == 1


def test_written_at_is_stamped_by_the_writer(tmp_path, monkeypatch):
    from pipeline import intelligence_state as istate

    monkeypatch.setattr(istate, "reports_root", lambda: tmp_path)
    istate.write_layer2_shortlist("2026-08-08", {"rows": [], "cards": []})
    assert istate.read_layer2_shortlist("2026-08-08")["written_at"]


# ---------------------------------------------------------------------------
# `layer2-prior-date-live-carryover`: a FROZEN build must not serve rows as live.
# Measured 2026-09-13: `?sport=ncaaf&date=2026-09-12` served the 04:58:55Z build
# at 13:23:59Z with 28 rows still `live`, five of their six games final for hours.
# ---------------------------------------------------------------------------


def _stamp(seconds_ago):
    from datetime import datetime, timedelta, timezone

    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _live_board(written_at):
    live = _row("ncaaf", "home", 2.0)
    live.update({"game_state": "live", "is_live": True, "market_state": "live", "game": {"state": "live", "matchup": "NMS @ HAW"}})
    pregame = _row("ncaaf", "away", 1.0)
    pregame.update({"game_state": "pregame", "is_live": False, "market_state": "pregame", "game": {"state": "pregame"}})
    return {"selected_date": "2026-09-12", "written_at": written_at, "rows": [live, pregame], "active_sports": ["ncaaf"]}


def test_live_rows_from_a_frozen_build_are_not_served_as_live(client, monkeypatch):
    monkeypatch.delenv("SYNDICATE_LAYER2_LIVE_STATE_MAX_BUILD_AGE_SECONDS", raising=False)
    board = _live_board(_stamp(8 * 3600))
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: board)

    served = client.get("/api/board/layer2-shortlist?date=2026-09-12&sport=ncaaf").get_json()
    live, pregame = served["rows"]

    assert live["game_state"] == "unknown"
    assert live["game_state_at_build"] == "live"
    assert live["live_state_stale"] is True
    assert live["is_live"] is None
    assert live["market_state"] == "unknown"
    assert live["game"]["state"] == "unknown"
    assert live["game"]["state_at_build"] == "live"
    assert live["game"]["matchup"] == "NMS @ HAW"
    assert pregame["game_state"] == "pregame"
    assert "live_state_stale" not in pregame
    assert served["rows_live_state_stale"] == 1
    assert served["build_age_seconds"] > 1800
    assert served["live_state_max_build_age_seconds"] == 1800.0
    # The artifact read is shared; relabelling must copy, never mutate it.
    assert board["rows"][0]["game_state"] == "live"
    assert board["rows"][0]["game"]["state"] == "live"


def test_live_rows_from_a_fresh_build_stay_live(client, monkeypatch):
    monkeypatch.delenv("SYNDICATE_LAYER2_LIVE_STATE_MAX_BUILD_AGE_SECONDS", raising=False)
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: _live_board(_stamp(60)))

    served = client.get("/api/board/layer2-shortlist?date=2026-09-13&sport=ncaaf").get_json()

    assert served["rows"][0]["game_state"] == "live"
    assert served["rows"][0]["is_live"] is True
    assert "live_state_stale" not in served["rows"][0]
    assert served["rows_live_state_stale"] == 0


def test_the_ceiling_is_env_tunable_and_zero_disables_it(client, monkeypatch):
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: _live_board(_stamp(120)))
    monkeypatch.setenv("SYNDICATE_LAYER2_LIVE_STATE_MAX_BUILD_AGE_SECONDS", "60")
    assert client.get("/api/board/layer2-shortlist?date=2026-09-13").get_json()["rows_live_state_stale"] == 1

    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: _live_board(_stamp(8 * 3600)))
    monkeypatch.setenv("SYNDICATE_LAYER2_LIVE_STATE_MAX_BUILD_AGE_SECONDS", "0")
    served = client.get("/api/board/layer2-shortlist?date=2026-09-12").get_json()
    assert served["rows_live_state_stale"] == 0
    assert served["rows"][0]["game_state"] == "live"


def test_an_unreadable_build_stamp_does_not_vouch_for_live_rows(client, monkeypatch):
    monkeypatch.delenv("SYNDICATE_LAYER2_LIVE_STATE_MAX_BUILD_AGE_SECONDS", raising=False)
    monkeypatch.setattr("pipeline.intelligence_state.read_layer2_shortlist", lambda date: _live_board(None))

    served = client.get("/api/board/layer2-shortlist?date=2026-09-12").get_json()

    assert served["build_age_seconds"] is None
    assert served["rows"][0]["game_state"] == "unknown"
    assert served["rows_live_state_stale"] == 1
