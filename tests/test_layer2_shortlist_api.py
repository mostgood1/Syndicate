"""`/api/board/layer2-shortlist` — L2-A served as a PURE READ of the artifact.

L2-A cannot be a serve-time pivot the way L1-A (`/api/board/book-grid`) is: a
board recomputed per request cannot be SETTLED. S6 needs a record of what was
recommended and at what price, so the rows are built on refresh-worker inside
`_build_candidate_pool`, persisted into the canonical board state, and only read
here.

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
    assert payload["reason"] == "no_board_state"
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
