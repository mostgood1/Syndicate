"""The stored MLB live-lens snapshot must fit its keyvalue key, and its slim
`page_context["games"]` must give the board's lens join the SAME answer.

Lane `mlb-live-lens-payload-dup` (2026-09-13). Measured on live-odds-worker:
`KeyValuePayloadTooLarge` for `live/mlb_live_lens.json` on 57 of 61
`live_lens_tick_after_mlb` samples 00:14-04:03Z, 10,803,367 B against the
8,388,608 B ceiling, because `games` (5,548,330 B for 15 games, one copy) was
stored twice: at `page_context["games"]` and at top level.

The fix stores `page_context["games"]` as a projection of exactly the fields its
one reader -- `board_enrichment.attach_live_game_state_from_lens` -- reads. These
tests pin the two things that make that safe: the projection keeps those
fields, and the join's corrections are identical on slim and full copies.
"""

from __future__ import annotations

import json

import pytest

from syndicate.features.mlb import live_lens as mlb_live_lens
from syndicate.features.shared import board_enrichment


def _heavy_game(game_pk: int, away: dict, home: dict, abstract: str, detailed: str, score: dict) -> dict:
    """A production-shaped game: the join fields plus the heavy payload it never reads."""
    heavy_list = [{"player": f"p{i}", "market": "hits", "line": 0.5, "edge": 0.01 * i} for i in range(200)]
    return {
        "gamePk": game_pk,
        "status": {"abstract": abstract, "detailed": detailed, "codedGameState": "I", "extra": "x" * 50},
        "home": dict(home),
        "away": dict(away),
        "matchup": {"score": dict(score), "inning": 7, "outs": 2},
        "archivedLiveProps": heavy_list,
        "gameMarkets": {"totals": heavy_list},
        "liveProps": heavy_list,
        "props": heavy_list,
        "trackedProps": heavy_list,
        "gameLens": [{"k": i} for i in range(50)],
    }


def _games() -> list[dict]:
    return [
        _heavy_game(1, {"name": "Athletics", "abbr": "ATH"}, {"name": "Seattle Mariners", "abbr": "SEA"},
                    "Final", "Final", {"home": 4, "away": 7}),
        _heavy_game(2, {"name": "St. Louis Cardinals", "abbr": "STL"}, {"name": "Los Angeles Dodgers", "abbr": "LAD"},
                    "Live", "Top 9th", {"home": 2, "away": 1}),
        # Matched on ABBR only: the name spelling differs from the grid's, so the
        # projection must keep `abbr` or this row silently stops correcting.
        _heavy_game(3, {"name": "NY Yankees (alt)", "abbr": "NYY"}, {"name": "BOS Red Sox (alt)", "abbr": "BOS"},
                    "Final", "Final", {"home": 3, "away": 5}),
    ]


# ---------------------------------------------------------------------------
# 1. THE PROJECTION KEEPS EXACTLY WHAT THE JOIN READS
# ---------------------------------------------------------------------------


def test_projection_keeps_the_join_fields_and_drops_the_rest():
    projected = mlb_live_lens._board_state_games_projection(_games())
    assert [g["gamePk"] for g in projected] == [1, 2, 3]
    first = projected[0]
    assert set(first) == {"gamePk", "status", "home", "away", "matchup"}
    assert first["status"] == {"abstract": "Final", "detailed": "Final"}
    assert first["home"] == {"name": "Seattle Mariners", "abbr": "SEA"}
    assert first["away"] == {"name": "Athletics", "abbr": "ATH"}
    assert first["matchup"] == {"score": {"home": 4, "away": 7}}


def test_projection_is_small_against_the_full_copy():
    games = _games()
    full = len(json.dumps(games))
    slim = len(json.dumps(mlb_live_lens._board_state_games_projection(games)))
    # The heavy lists are the point: production measured 5,548,330 B -> 3,399 B.
    assert slim * 50 < full, (slim, full)


def test_projection_tolerates_malformed_games():
    projected = mlb_live_lens._board_state_games_projection([None, "x", {"gamePk": 9}])
    assert projected == [{"gamePk": 9, "status": {"abstract": None, "detailed": None},
                          "home": {}, "away": {}, "matchup": {"score": None}}]


# ---------------------------------------------------------------------------
# 2. THE BOARD'S LENS JOIN GIVES THE SAME ANSWER ON SLIM AND FULL
# ---------------------------------------------------------------------------


def _grid() -> list[dict]:
    def row(away: str, home: str, state: str) -> dict:
        return {"away_team": away, "home_team": home,
                "game": {"matchup": f"{away} @ {home}", "state": state, "away_score": None, "home_score": None}}
    return [
        row("Athletics", "Seattle Mariners", "live"),        # -> final
        row("St. Louis Cardinals", "Los Angeles Dodgers", "pregame"),  # -> live
        row("New York Yankees", "Boston Red Sox", "live"),   # -> final, via abbr
    ]


@pytest.fixture
def patched_lens(monkeypatch):
    """Swap the keyvalue-backed snapshot read for an in-memory payload -- the real
    path is a Redis key, so patch the READER (same shape as
    `test_board_enrichment_lens_date_gate.py`)."""

    def _install(snapshot):
        import syndicate.features.shared.refresh_state_store as store

        monkeypatch.setattr(store, "read_json_file", lambda *_a, **_k: snapshot)

    return _install


def _join(patched_lens, page_games: list[dict]) -> tuple[dict, list[dict]]:
    grid = _grid()
    patched_lens({"page_context": {"date": "2026-09-12", "games": page_games}, "games": _games()})
    result = board_enrichment.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-12")
    return result, grid


def test_join_on_slim_equals_join_on_full(patched_lens):
    full_result, full_grid = _join(patched_lens, _games())
    slim_result, slim_grid = _join(patched_lens, mlb_live_lens._board_state_games_projection(_games()))

    # THE CONTROL FIRST: the full copy really corrects rows, including the
    # abbr-only one, so equality below cannot be two empty answers agreeing.
    assert full_result["rows_corrected"] >= 2, full_result
    assert slim_result["rows_corrected"] == full_result["rows_corrected"]
    assert slim_result.get("transitions") == full_result.get("transitions")
    assert [r["game"] for r in slim_grid] == [r["game"] for r in full_grid]


# ---------------------------------------------------------------------------
# 3. THE REAL BUILDER STORES THE SLIM COPY -- reachability, not just the helper
# ---------------------------------------------------------------------------


def test_builder_stores_slim_page_context_games_and_full_top_level(monkeypatch):
    """Drives `build_live_lens_snapshot_internal` itself (same harness as
    `test_archives.py::test_mlb_live_lens_game_rows_preserve_structured_status`),
    so a helper that exists but is never assigned fails here."""
    heavy = [{"player": f"p{i}", "market": "hits", "line": 0.5} for i in range(300)]
    report = {
        "generatedAt": "2026-05-09T16:25:51-05:00",
        "counts": {"games": 2, "live": 1, "final": 1, "pregame": 0, "props": 0},
        "games": [
            {
                "gamePk": 822820,
                "status": {"abstract": "Live", "detailed": "In Progress"},
                "matchup": {
                    "away": {"abbr": "LAA", "name": "Los Angeles Angels"},
                    "home": {"abbr": "TOR", "name": "Toronto Blue Jays"},
                    "score": {"away": 0, "home": 9},
                },
                "liveProps": heavy,
                "archivedLiveProps": heavy,
            },
            {
                "gamePk": 822821,
                "status": {"abstract": "Final", "detailed": "Final"},
                "matchup": {
                    "away": {"abbr": "ATH", "name": "Athletics"},
                    "home": {"abbr": "SEA", "name": "Seattle Mariners"},
                    "score": {"away": 7, "home": 4},
                },
                "liveProps": heavy,
                "archivedLiveProps": heavy,
            },
        ],
    }
    monkeypatch.setattr(mlb_live_lens, "load_json_file", lambda *_a, **_k: report)

    snapshot = mlb_live_lens.build_live_lens_snapshot_internal("2026-05-09")

    top = snapshot["games"]
    page_games = snapshot["page_context"]["games"]
    assert len(top) == 2 and len(page_games) == 2
    # Top level is the FULL copy -- every other reader depends on it.
    assert json.dumps(top) != json.dumps(page_games)
    # The page copy is exactly the projection of the full copy...
    assert page_games == mlb_live_lens._board_state_games_projection(top)
    # ...carries only the join fields...
    assert all(set(g) == {"gamePk", "status", "home", "away", "matchup"} for g in page_games)
    # ...and is a small fraction of the full copy.
    assert len(json.dumps(page_games)) * 20 < len(json.dumps(top)), (len(json.dumps(page_games)), len(json.dumps(top)))
    # The validator and the served payload still see full top-level games.
    assert mlb_live_lens.validate_live_lens_snapshot(snapshot)
    assert len(mlb_live_lens._snapshot_games(snapshot)) == 2


def test_deleting_page_context_games_would_break_the_join(patched_lens):
    """WHY A PROJECTION, NOT A DELETE: with the key gone the join reads 'no games'."""
    grid = _grid()
    patched_lens({"page_context": {"date": "2026-09-12"}, "games": _games()})
    result = board_enrichment.attach_live_game_state_from_lens(grid, sport="mlb", selected_date="2026-09-12")
    assert result["rows_corrected"] == 0
    assert result["reason"] == "snapshot carries no games"
