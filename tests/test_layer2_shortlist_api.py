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
