"""Live NFL props restated live on L2-A cards must stay live on the main board.

USER-REPORTED 2026-09-15 ~01:45Z (20:45 CT 09-14): "why are there no props for
the live nfl game right now", with DEN @ KC live (Q2).

MEASURED the same minutes:

    /api/board/layer2-shortlist?sport=nfl   113 live props, lane opportunity
    POST /api/intelligence/query (the page) 25 DEN @ KC props, ALL
        board_lane watchlist, market_state unknown, is_live None,
        gate reason no_game_state; NFL cards restated live: 0 (MLB: 209)

The scoreboard chip WAS live and its keys matched the cards exactly, so the
chip join in `_refresh_layer2_live_state` was not the miss.

`read_combined_intelligence_response` appends every per-date STATE row first and
the restated L2-A fallback cards after them, and `dedupe_recommendation_items`
keeps the FIRST copy of a pick. A state row written before kickoff (never
restated) therefore shadowed the live-restated card for the same prop, and the
serve-time re-gate (`opportunity_gate.annotate`) demoted the survivor to the
watchlist -- which the page's default Opportunity lane hides.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pipeline import intelligence_state as S  # noqa: E402
from syndicate.features.shared.opportunity_gate import annotate  # noqa: E402

CHIPS = "syndicate.features.shared.game_chip_scoreboard.build_game_chips"
DATE = "2026-09-14"
AWAY, HOME = "Denver Broncos", "Kansas City Chiefs"


def _prop(**overrides):
    row = {
        "sport": "nfl",
        "sport_slug": "nfl",
        "kind": "prop",
        "matchup": f"{AWAY} @ {HOME}",
        "away_team": AWAY,
        "home_team": HOME,
        "away_key": "denver broncos",
        "home_key": "kansas city chiefs",
        "player_name": "Travis Kelce",
        "market": "Receiving Yards",
        "selection": "over",
        "side": "over",
        "line": 55.5,
        "commence_time": "2026-09-15T00:15:00Z",
        "game_date": DATE,
        "lane": "pregame",
        "market_state": "pregame",
        "source": "layer2_shortlist",
        # What the production props carried at the time (Layer 2 API 01:48Z: book
        # age 172-705 s, fair_method consensus), so the re-gate is judged on the
        # live path rather than failing on `no_market_posted`.
        "quote": {
            "price": -110,
            "bookmaker": "draftkings",
            "book_age_seconds": 120.0,
            "quote_seen_age_seconds": 60.0,
            "fair_method": "consensus",
            "fair_probability": 0.5,
            "books_quoting": 3,
        },
    }
    row.update(overrides)
    return row


def _live_chip():
    return {
        "sport": "nfl",
        "state": "live",
        "away": {"name": AWAY, "abbr": "DEN", "key": "denver broncos", "score": "7"},
        "home": {"name": HOME, "abbr": "KC", "key": "kansas city chiefs", "score": "14"},
    }


@pytest.fixture
def board(monkeypatch):
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()
    # The per-date STATE carries the prop as it was written before kickoff.
    state = {DATE: {"state_last_updated": "2026-09-15T00:49:16Z", "by_sport": {"nfl": [_prop()]}}}
    monkeypatch.setattr(S, "_read_single_date_response_for_combining", lambda d: state.get(d))
    # The L2-A artifact carries the same prop as a card; the REAL fallback reader
    # runs, so its own live restate is exercised rather than stubbed.
    shortlist = {"written_at": "2026-09-15T01:50:02Z", "cards": [_prop()]}
    monkeypatch.setattr(S, "read_layer2_shortlist", lambda d: shortlist if d == DATE else None)
    monkeypatch.setattr(S, "board_l2a_fallback_enabled", lambda: True)
    yield
    S._COMBINED_INTELLIGENCE_RESPONSE_CACHE.clear()


def _served_kelce(out):
    rows = [r for r in out.get("top_opportunities") or [] if r.get("player_name") == "Travis Kelce"]
    assert len(rows) == 1, f"expected the prop once after dedupe, got {len(rows)}"
    return rows[0]


def test_a_live_game_prop_is_served_live_when_a_pre_kickoff_state_row_shadows_the_card(board):
    """THE REPORTED SYMPTOM. Fails while the state row's stale state wins the dedupe."""
    with patch(CHIPS, return_value=[_live_chip()]):
        out = S.read_combined_intelligence_response(dates=[DATE], sport="all")
    row = _served_kelce(out)
    assert row.get("is_live") is True, row
    assert row.get("market_state") == "live", row


def test_the_serve_time_regate_no_longer_demotes_it_for_missing_game_state(board):
    """What the page actually filters on: the gate the blueprint re-runs per request."""
    with patch(CHIPS, return_value=[_live_chip()]):
        out = S.read_combined_intelligence_response(dates=[DATE], sport="all")
    row = dict(_served_kelce(out))
    annotate(row)
    assert "no_game_state" not in (row.get("gate") or {}).get("reasons", []), row.get("gate")
    assert row.get("market_state") == "live", row.get("gate")


def test_a_pregame_chip_leaves_the_state_row_alone(board):
    """Restating reads the scoreboard; it must not manufacture a live game."""
    chip = _live_chip()
    chip["state"] = "pregame"
    with patch(CHIPS, return_value=[chip]):
        out = S.read_combined_intelligence_response(dates=[DATE], sport="all")
    row = _served_kelce(out)
    assert row.get("is_live") is not True
    assert row.get("market_state") != "live"
