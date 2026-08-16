"""`/api/board/book-grid` must serve every coverage block the writer persists.

Lane `live-game-line-projection`. This is a regression test for a bug that has
now happened TWICE in the same function, to two different coverage families:

1. `live_projections` / `live_game_state` were computed on refresh-worker,
   written to the artifact, and dropped by this response. The only way to read
   them was a raw artifact file on the worker's disk. The route carries a long
   comment about it.
2. Drop 3 then added `live_gamelines` and `live_gameline_ledger` to the same
   writer, and the same response dropped both. Measured 2026-08-16: reading
   `rows_live_gameline_edged` and the ledger's `written` counter required
   streaming a **9,953,474-byte** artifact through `/api/ops/artifacts/stream`.

A test naming each key individually would not have caught (2) — the key did not
exist when the test would have been written. So the load-bearing test here is
the LAST one: it asserts pass-through of the artifact's ungated coverage keys as
a SET, so the next family added to the writer fails here instead of going
unreadable for a week.
"""

from __future__ import annotations

import pytest

from syndicate.app import app

# Coverage keys this response gates on `has_enrichment` (`projections` and
# `game_state` both present). They are legitimately null for an old artifact, so
# the set-based test below excludes them and they are covered by their own
# assertions instead.
_ENRICHMENT_GATED = {"market_kinds", "game_state", "projections", "margin_model"}

_LIVE_GAMELINES = {
    "rows_live_gameline_considered": 8,
    "rows_live_gameline_projected": 2,
    "rows_live_gameline_priceable": 0,
    "rows_live_gameline_edged": 0,
    "rows_live_gameline_withheld": 8,
    "withheld_by_reason": {"prob_interval_swamps_edge": 2, "segment_is_not_full_game": 6},
    # NOT a live-game count: snapshot games carrying a `live_mc` lens. Measured
    # 2026-08-16 03:0xZ as 10 = 8 Final + 2 Live.
    "index_size": 10,
    "supported": True,
}

_LEDGER = {"candidates": 2, "written": 2, "skipped_unchanged": 0,
           "truncated_build_cap": 0, "truncated_file_cap": 0, "enabled": True}


def _artifact(**overrides):
    """The real production shape, trimmed. Values are from the 03:00:00.538Z
    build of `book_grid_2026-08-15.json`."""
    payload = {
        "version": 2,
        "sport": "mlb",
        "date": "2026-08-15",
        "generated_at": "2026-08-16T03:00:00.538267+00:00",
        "rows_total": 3249,
        "rows_truncated": 0,
        "summary": {"rows": 3249},
        "game_state": {"rows_with_game": 3249},
        "live_game_state": {"rows_live": 8},
        "projections": {"rows_with_projection": 120},
        "live_projections": {"rows_live_considered": 638, "rows_live_edged": 0},
        "live_gamelines": dict(_LIVE_GAMELINES),
        "live_gameline_ledger": dict(_LEDGER),
        "margin_model": {"rows": 0},
        "market_kinds": {"h2h": "game"},
        "rows": [{"market": "h2h", "kind": "game"}],
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def client():
    return app.test_client()


@pytest.fixture
def served(monkeypatch):
    """Serve a chosen artifact through the precomputed branch."""

    def _serve(payload):
        import syndicate.features.shared.book_grid_artifact as mod

        monkeypatch.setattr(mod, "read_book_grid_artifact", lambda *a, **k: payload)
        return payload

    return _serve


def _get(client):
    resp = client.get("/api/board/book-grid?sport=mlb&date=2026-08-15&limit=1")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body.get("source") == "precomputed_artifact", (
        "the test fell through to the serve-time branch, so it is asserting "
        "nothing about the artifact pass-through"
    )
    return body


class TestLiveGamelineCoverageIsServed:
    def test_the_gameline_coverage_block_reaches_the_api(self, client, served):
        served(_artifact())
        assert _get(client)["live_gamelines"] == _LIVE_GAMELINES

    def test_the_ledger_counters_reach_the_api(self, client, served):
        """Without this the only reader is a 10 MB ops stream."""
        served(_artifact())
        assert _get(client)["live_gameline_ledger"] == _LEDGER

    def test_the_two_families_stay_separate_keys(self, client, served):
        """Folding game lines into `live_projections` would make one family's
        zero look like the other's — the writer's own stated reason."""
        served(_artifact())
        body = _get(client)
        assert body["live_projections"] != body["live_gamelines"]

    def test_an_artifact_predating_the_join_serves_null_not_an_empty_dict(self, client, served):
        """ABSENT and EMPTY must not serialize the same way. `{}` would read as
        'we joined and found nothing'; null says 'this artifact predates it'."""
        payload = _artifact()
        payload.pop("live_gamelines")
        payload.pop("live_gameline_ledger")
        served(payload)
        body = _get(client)
        assert body["live_gamelines"] is None and body["live_gameline_ledger"] is None

    def test_the_live_tier_is_NOT_gated_on_has_enrichment(self, client, served):
        """These keys post-date the gate, so gating them would report null for
        an artifact that genuinely carries them."""
        payload = _artifact()
        payload.pop("projections")
        served(payload)
        body = _get(client)
        assert body["enriched"] is False
        assert body["live_gamelines"] == _LIVE_GAMELINES

    def test_EVERY_ungated_coverage_key_the_writer_persists_is_served(self, client, served):
        """The one that catches the NEXT family, rather than this one.

        Anything the writer adds alongside these blocks must either be served or
        be added to `_ENRICHMENT_GATED` with a reason. Silence is the failure
        mode: a computed, persisted, unreadable counter looks exactly like a
        counter that was never computed.
        """
        payload = _artifact()
        served(payload)
        body = _get(client)
        coverage_keys = {
            key for key, value in payload.items()
            if isinstance(value, dict) and key not in {"summary"}
        } - _ENRICHMENT_GATED
        missing = sorted(k for k in coverage_keys if body.get(k) != payload[k])
        assert not missing, f"the writer persists these and the API drops them: {missing}"
