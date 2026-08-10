"""`#328` — the precomputed book grid must arrive ENRICHED, and say so honestly.

`#323` moved the L1-A pivot onto refresh-worker and taught web to prefer the
artifact. The artifact builder never called the three `board_enrichment` steps,
and web's artifact branch returned before the `_attach_*` calls the live-pivot
path still made. Measured on production 2026-08-10 16:5xZ, a served MLB row
carried no `game`, no `projection` and no `modelled_fair` — Proj, Edge, Date and
Game blank on every row of `/market-board/books`, and Fair blank on the 441
one-sided rows the margin model exists for.

Nothing raised. That is the whole difficulty: the columns were never populated,
and a blank column reads as "the model has no opinion" rather than "nobody asked
it". So these tests assert THE CALL HAPPENED, not that the output looks
populated — a fixture can produce plausible-looking rows down a path that never
touched the enrichment, and that failure would look like a pass.
"""

from __future__ import annotations

import json

import pytest

from syndicate.app import app
from syndicate.features.shared import board_enrichment, book_grid_artifact


@pytest.fixture
def client():
    return app.test_client()


def _quote(market="h2h", selection="home", price=-110, event_id="evt-1"):
    return {
        "sport": "mlb",
        "kind": "game",
        "event_id": event_id,
        "segment": "full_game",
        "market": market,
        "player_name": "",
        "selection": selection,
        "line": None,
        "price": price,
        "bookmaker": "draftkings",
        "home_team": "Baltimore Orioles",
        "away_team": "Los Angeles Angels",
        "commence_time": "2026-08-10T23:05:00Z",
        "snapshot_ts": "2026-08-10T19:55:00Z",
    }


class _Harness:
    """The shard stub plus the three enrichment spies.

    `quotes` is what the (stubbed) shard yields; `calls` is what each enrichment
    step was handed. Recording the grid LENGTH is what makes the pre-bound
    assertion below possible.
    """

    def __init__(self):
        self.quotes: list[dict] = []
        self.calls: dict[str, dict] = {}


@pytest.fixture
def harness(monkeypatch, tmp_path):
    state = _Harness()

    shard = tmp_path / "book_quotes_2026-08-10.jsonl"
    shard.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(book_grid_artifact, "book_quotes_path", lambda *a, **k: shard)
    monkeypatch.setattr(book_grid_artifact, "read_quote_last_seen", lambda *a, **k: {})
    # `iter_book_quotes`, not `read_book_quotes`: `#331` landed the streamed
    # reduction in this same file while this was being written. Patching the
    # seam that actually exists rather than the one that used to -- and leaving
    # `freshest_rows_for_grid` REAL, so these run through the same reduction
    # production does rather than around it.
    monkeypatch.setattr(book_grid_artifact, "iter_book_quotes", lambda *a, **k: iter(list(state.quotes)))

    def _spy(name, coverage):
        def _inner(grid, **kwargs):
            state.calls[name] = {"rows_seen": len(grid), "kwargs": kwargs}
            return dict(coverage)

        return _inner

    monkeypatch.setattr(board_enrichment, "attach_game_state", _spy("game_state", {"chips": 3, "rows_matched": 2}))
    monkeypatch.setattr(board_enrichment, "attach_projections", _spy("projections", {"supported": True, "rows_with_projection": 2}))
    monkeypatch.setattr(board_enrichment, "attach_margin_model", _spy("margin_model", {"rows_modelled": 1}))
    return state


def test_builder_calls_all_three_enrichment_steps(harness):
    # The regression in one assertion: the builder must REACH board_enrichment.
    # Checking the rows for a `projection` key instead would pass on a fixture
    # that never called anything, because absent and empty look identical there.
    harness.quotes = [_quote(selection="home"), _quote(selection="away", price=105)]

    payload = book_grid_artifact.build_book_grid_artifact("mlb", "2026-08-10")

    assert set(harness.calls) == {"game_state", "projections", "margin_model"}
    assert payload["game_state"] == {"chips": 3, "rows_matched": 2}
    assert payload["projections"] == {"supported": True, "rows_with_projection": 2}
    assert payload["margin_model"] == {"rows_modelled": 1}
    # Version is part of the wire contract across two independently deployed
    # services, so a bump that nobody notices is the #320 failure again.
    assert payload["version"] == 2


def test_enrichment_runs_on_the_full_grid_not_the_bounded_slice(harness):
    # `build_margin_profile` measures THIS slate's holds from its two-sided
    # markets. Profiling the truncated slice would fit the model to whatever
    # happened to survive the cut, and the bound exists precisely because a real
    # day can overflow it -- the 1500-row cap discarded 73% of 2026-08-09.
    for index in range(5):
        harness.quotes.append(_quote(market=f"market_{index}", selection="home"))
        harness.quotes.append(_quote(market=f"market_{index}", selection="away", price=105))

    payload = book_grid_artifact.build_book_grid_artifact("mlb", "2026-08-10", max_rows=2)

    assert payload["rows_total"] == 5
    assert payload["rows_truncated"] == 3
    assert len(payload["rows"]) == 2
    for step in ("game_state", "projections", "margin_model"):
        assert harness.calls[step]["rows_seen"] == 5, f"{step} was handed the bounded slice"


def test_market_kinds_is_served_so_both_kind_tabs_are_not_identical(harness):
    # Absent `market_kinds`, the client's kind selector falls back to an empty
    # map and BOTH tabs claim every market -- observed as "Game lines 14 /
    # Player props 14" on a 14-market slate.
    harness.quotes = [_quote(selection="home"), _quote(selection="away", price=105)]

    payload = book_grid_artifact.build_book_grid_artifact("mlb", "2026-08-10")

    assert payload["market_kinds"] == {"h2h": "game"}


def _write_artifact(monkeypatch, tmp_path, payload):
    path = tmp_path / "book_grid_2026-08-10.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    from syndicate.features.shared import book_grid_artifact as module

    monkeypatch.setattr(module, "book_grid_artifact_path", lambda *a, **k: path)
    return path


def test_endpoint_serves_the_artifacts_enrichment(client, monkeypatch, tmp_path):
    _write_artifact(
        monkeypatch,
        tmp_path,
        {
            "version": 2,
            "rows_total": 1,
            "rows_truncated": 0,
            "summary": {"rows": 1},
            "game_state": {"chips": 3, "rows_matched": 1},
            "projections": {"supported": True, "rows_with_projection": 1},
            "margin_model": {"rows_modelled": 1},
            "market_kinds": {"h2h": "game"},
            "rows": [{"market": "h2h", "kind": "game", "projection": {"projected": 0.61}}],
        },
    )

    body = client.get("/api/board/book-grid?sport=mlb&date=2026-08-10").get_json()

    assert body["source"] == "precomputed_artifact"
    assert body["enriched"] is True
    assert body["enrichment_state"] == "from_artifact"
    assert body["projections"] == {"supported": True, "rows_with_projection": 1}
    assert body["market_kinds"] == {"h2h": "game"}
    assert body["rows"][0]["projection"] == {"projected": 0.61}


def test_pre_328_artifact_reports_absent_enrichment_rather_than_empty(client, monkeypatch, tmp_path):
    # THE DEPLOY-WINDOW CASE. Web can ship before refresh-worker, and a cancelled
    # worker deploy silently keeps the old commit running -- so a v1 artifact is
    # a state that WILL occur, not a hypothetical.
    #
    # `null` here means "written before anything joined". Serving `{}` instead
    # would let it render as a slate the model has no opinion on, which is the
    # same misreading that let the original defect sit unnoticed.
    _write_artifact(
        monkeypatch,
        tmp_path,
        {
            "version": 1,
            "rows_total": 1,
            "rows_truncated": 0,
            "summary": {"rows": 1},
            "rows": [{"market": "h2h", "kind": "game"}],
        },
    )

    body = client.get("/api/board/book-grid?sport=mlb&date=2026-08-10").get_json()

    assert body["enriched"] is False
    assert body["enrichment_state"] == "artifact_predates_enrichment"
    assert body["projections"] is None
    assert body["game_state"] is None
    assert body["margin_model"] is None
    # Still serves the prices. A board that degrades to "no enrichment" is
    # useful; one that degrades to "no board" is not.
    assert body["rows"][0]["market"] == "h2h"
