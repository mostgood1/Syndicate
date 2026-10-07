"""One list: status and Home read the Layer 2 board (lane intelligence-evidence-coverage)."""

from __future__ import annotations

import pytest

from syndicate.features import intelligence_layer2_view as view_mod

_L2 = [
    {"sport_slug": "wnba", "source": "layer2_shortlist", "pick_id": "l2_a", "player_name": "Naz Hillmon", "edge": 0.042, "market": "player_threes", "matchup": "NYL @ ATL"},
    {"sport_slug": "nhl", "source": "layer2_shortlist", "pick_id": "l2_b", "team": "PIT", "edge": 0.031, "market": "h2h", "matchup": "PIT @ WSH"},
]


@pytest.fixture()
def combined(monkeypatch):
    import pipeline.intelligence_state as state

    view_mod._VIEW_MEMO.clear()
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {})

    calls = []

    def fake(dates=None, *, sport="all", limit=None, _warm=False):
        calls.append((dates, sport, limit))
        return {"response": {"top_opportunities": list(_L2), "board_contract": {"schema": "intelligence_board_v1"}}}

    monkeypatch.setattr(state, "read_combined_intelligence_response", fake)
    return calls


def test_view_reads_the_combined_layer2_board(combined):
    view = view_mod.layer2_board_view("2026-10-07", limit=150)
    assert combined == [(["2026-10-07"], "all", 150)]
    assert view["candidate_count"] == 2 and view["layer2_rows"] == 2
    assert list(view["by_sport"]) == ["wnba", "nhl"]
    assert view["pick_list_source"] == "layer2_combined_board"


def test_view_is_empty_when_the_board_has_nothing(monkeypatch):
    import pipeline.intelligence_state as state

    view_mod._VIEW_MEMO.clear()
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {})

    monkeypatch.setattr(state, "read_combined_intelligence_response", lambda *a, **k: {"response": {"top_opportunities": []}})
    assert view_mod.layer2_board_view("2026-10-07") == {}


def test_view_never_raises(monkeypatch):
    import pipeline.intelligence_state as state

    view_mod._VIEW_MEMO.clear()
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {})

    def boom(*a, **k):
        raise RuntimeError("keyvalue down")

    monkeypatch.setattr(state, "read_combined_intelligence_response", boom)
    assert view_mod.layer2_board_view("2026-10-07") == {}


def test_overlay_replaces_pick_lists_and_keeps_build_fields(combined):
    legacy = {
        "recommendations": [{"source": None, "name": "MIN"}],
        "candidate_count": 77,
        "freshness": {"computed_at": "2026-10-07T16:33:44Z"},
        "layer2_shortlist": {"cards": []},
    }
    out = view_mod.overlay_pick_lists(legacy, view_mod.layer2_board_view("2026-10-07"))
    assert [r["pick_id"] for r in out["recommendations"]] == ["l2_a", "l2_b"]
    assert out["candidate_count"] == 2 and out["legacy_candidate_count"] == 77
    assert out["legacy_recommendations"] == [{"source": None, "name": "MIN"}]
    assert out["freshness"] == {"computed_at": "2026-10-07T16:33:44Z"} and "layer2_shortlist" in out


def test_overlay_without_a_view_changes_nothing():
    legacy = {"recommendations": [{"name": "MIN"}], "candidate_count": 77}
    assert view_mod.overlay_pick_lists(legacy, {}) == legacy


def test_home_board_rows_come_from_layer2_and_carry_source(combined):
    from syndicate.blueprints.home import _board_candidate_rows

    rows = _board_candidate_rows("2026-10-07", limit=16)
    assert [row["source"] for row in rows] == ["layer2_shortlist", "layer2_shortlist"]
    assert rows[0]["pick_id"] == "l2_a"


def test_view_is_in_board_order_layer2_first(monkeypatch):
    import pipeline.intelligence_state as state

    view_mod._VIEW_MEMO.clear()
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {})

    rows = [
        {"sport_slug": "nhl", "source": "data/props/player_props_lines/date=2026-10-07/oddsapi.csv", "candidate_type": "steam", "edge": 0.318},
        {"sport_slug": "nba", "source": "layer2_shortlist", "pick_id": "low", "board_score": 0.4},
        {"sport_slug": "nfl", "source": "layer2_shortlist", "pick_id": "high", "board_score": 2.1},
        {"sport_slug": "mlb", "source": "layer2_shortlist", "pick_id": "nested", "score": {"score": 1.0}},
    ]
    monkeypatch.setattr(state, "read_combined_intelligence_response", lambda *a, **k: {"top_opportunities": rows})
    view = view_mod.layer2_board_view("2026-10-07")
    assert [r.get("pick_id") for r in view["recommendations"]] == ["high", "nested", "low", None]


def test_stale_view_is_served_while_one_refresh_runs(monkeypatch):
    import threading
    import pipeline.intelligence_state as state

    view_mod._VIEW_MEMO.clear()
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {})
    gate = threading.Event()
    calls = []

    def slow(*a, **k):
        calls.append(1)
        if len(calls) > 1:
            gate.wait(5)
        return {"top_opportunities": [{"source": "layer2_shortlist", "pick_id": f"v{len(calls)}", "board_score": 1.0}]}

    monkeypatch.setattr(state, "read_combined_intelligence_response", slow)
    first = view_mod.layer2_board_view("2026-10-07")
    key = ("2026-10-07", "all", None)
    stamp, cached = view_mod._VIEW_MEMO[key]
    view_mod._VIEW_MEMO[key] = (stamp - 10_000, cached)  # age it past the TTL
    stale = view_mod.layer2_board_view("2026-10-07")
    again = view_mod.layer2_board_view("2026-10-07")
    assert stale is first and again is first  # served stale, not blocked
    gate.set()
    for _ in range(50):
        if not view_mod._REFRESHING:
            break
        threading.Event().wait(0.05)
    assert len(calls) == 2  # exactly one background refresh
    assert view_mod.layer2_board_view("2026-10-07")["recommendations"][0]["pick_id"] == "v2"


def test_shortlist_is_the_first_source(monkeypatch):
    import pipeline.intelligence_state as state

    view_mod._VIEW_MEMO.clear()
    called = []
    monkeypatch.setattr(state, "read_layer2_shortlist", lambda date: {"cards": [
        {"sport_slug": "nba", "source": "layer2_shortlist", "pick_id": "lo", "board_score": 0.2},
        {"sport_slug": "wnba", "source": "layer2_shortlist", "pick_id": "hi", "board_score": 1.9},
    ]})
    monkeypatch.setattr(state, "read_combined_intelligence_response", lambda *a, **k: called.append(1) or {})
    view = view_mod.layer2_board_view("2026-10-07")
    assert [r["pick_id"] for r in view["recommendations"]] == ["hi", "lo"]
    assert view["pick_list_source"] == "layer2_shortlist" and called == []
    sport_view = view_mod._layer2_board_view_uncached("2026-10-07", sport="wnba")
    assert [r["pick_id"] for r in sport_view["recommendations"]] == ["hi"]
