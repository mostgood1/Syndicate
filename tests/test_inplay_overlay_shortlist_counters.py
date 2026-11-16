"""The in-play overlay logs WHY `select_shortlist` dropped its opportunities (lane `wncaab-overlay-zero-cards`).

Measured 2026-11-16: every WNCAAB in-play overlay build 21:04-21:58Z published `cards=0` from 6-22
opportunities, and the INPLAY_OVERLAY line said nothing about why. `_build_inplay_overlay` kept only
`select_shortlist(...)["rows"]` and discarded its refusal counters. A read-only replay found the cause:
`rows_below_value_floor` refused 5 of 5. These tests hold the counters on the overlay and on its log line.
Selection itself does not change: the chosen rows and cards are exactly what they were.
"""
from __future__ import annotations

import json

import pytest

from syndicate.features.shared import book_grid_artifact as bga


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ("SYNDICATE_INPLAY_OVERLAY", "SYNDICATE_INPLAY_OVERLAY_BUILD_CONTEXT", "SYNDICATE_BUILD_LOOKUP_SCOPE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture()
def chain(monkeypatch):
    """build -> select -> cards, with `select`'s result set per test (default: everything chosen, nothing refused)."""
    from syndicate.features.shared import layer2_board

    state = {"select_result": None, "select_calls": 0, "cards_got": []}

    def build(rows):
        return {"opportunities": [{"event_id": r["event_id"], "market": "spread", "kind": "game"} for r in rows]}

    def select(opps):
        state["select_calls"] += 1
        if state["select_result"] is not None:
            return state["select_result"](opps)
        return {"rows": list(opps), "rows_total_budget": 1600, "rows_per_game": 6, "rows_bytes": 2,
                "rows_below_value_floor": 0}

    def cards(rows, openings=None, price_trail=None, row_context=None, openings_by_line=None):
        state["cards_got"].append(list(rows))
        return [{"sport": "wncaab", "event_id": r["event_id"], "source": "layer2_shortlist"} for r in rows]

    monkeypatch.setattr(layer2_board, "build_layer2_rows", build)
    monkeypatch.setattr(layer2_board, "select_shortlist", select)
    monkeypatch.setattr(layer2_board, "layer2_rows_to_board_cards", cards)
    return state


def _floor_refuses_all(opps):
    """The 11-16 WNCAAB shape: every opportunity under the value floor, plus the budget keys a real result carries."""
    return {"rows": [], "rows_total_budget": 1600, "rows_per_game": 6, "rows_bytes": 2, "rows_pct_of_keyvalue_max": 0.0,
            "rows_allocated_by_sport": {}, "rows_below_value_floor": len(opps), "rows_beyond_quote_age": 0,
            "rows_beyond_quote_age_by_sport": {"wncaab": 0}, "rows_stale_quote_sample": [],
            "rows_admitted_by_blend": 3, "rows_admitted_by_movement": 1}


# --- the helper ------------------------------------------------------------------------------------------


def test_the_helper_keeps_only_positive_refusal_counts():
    got = bga.inplay_overlay_shortlist_refusals({
        "rows": [{"x": 1}], "rows_below_value_floor": 5, "rows_stale_quote": 2, "rows_beyond_quote_age": 0,
        "rows_total_budget": 1600, "rows_per_game": 6, "rows_bytes": 2, "rows_pct_of_keyvalue_max": 3.5,
        "rows_admitted_by_blend": 4, "rows_admitted_by_movement": 1, "rows_allocated_by_sport": {"wncaab": 6},
        "rows_beyond_quote_age_by_sport": {"wncaab": 2}, "rows_stale_quote_sample": [1], "rows_flag": True,
        "candidates": 9, "rows_no_market_price": 1.0,
    })
    assert got == {"rows_below_value_floor": 5, "rows_no_market_price": 1, "rows_stale_quote": 2}


@pytest.mark.parametrize("shortlist", [None, {}, {"rows": []}])
def test_the_helper_is_empty_for_nothing(shortlist):
    assert bga.inplay_overlay_shortlist_refusals(shortlist) == {}


def test_the_real_select_shortlist_refuses_nothing_from_nothing():
    """Guard: any positive `rows_*` count the REAL selector reports for empty input is a budget or a size,
    never a refusal, so it must be in the exclusion set. A new budget key added to `select_shortlist`
    fails here instead of showing up as a refusal on every INPLAY_OVERLAY line."""
    from syndicate.features.shared.layer2_board import select_shortlist

    assert bga.inplay_overlay_shortlist_refusals(select_shortlist([])) == {}


# --- the overlay carries them (reachability through the public entry) -------------------------------------


def test_a_floor_refused_build_carries_the_reason(chain):
    chain["select_result"] = _floor_refuses_all
    rows = [{"event_id": f"e{i}"} for i in range(5)]
    overlay = bga.build_inplay_overlay("wncaab", "2026-11-16", rows)
    assert overlay["opportunities"] == 5 and overlay["cards"] == []
    # Admissions (`rows_admitted_by_*`), budgets and per-sport dicts are not refusals.
    assert overlay["shortlist_refused"] == {"rows_below_value_floor": 5}


def test_a_build_that_chooses_everything_refuses_nothing(chain):
    overlay = bga.build_inplay_overlay("wncaab", "2026-11-16", [{"event_id": "e1"}, {"event_id": "e2"}])
    assert overlay["shortlist_refused"] == {}
    assert [c["event_id"] for c in overlay["cards"]] == ["e1", "e2"]


def test_off_is_not_on_the_counters_follow_the_selector(chain):
    """off != on: the same rows give a different `shortlist_refused` only because the selector refused."""
    rows = [{"event_id": "e1"}, {"event_id": "e2"}]
    chosen = bga.build_inplay_overlay("wncaab", "2026-11-16", rows)
    chain["select_result"] = _floor_refuses_all
    refused = bga.build_inplay_overlay("wncaab", "2026-11-16", rows)
    assert chosen["shortlist_refused"] != refused["shortlist_refused"]
    assert (len(chosen["cards"]), len(refused["cards"])) == (2, 0)


def test_selection_is_unchanged_the_cards_step_gets_exactly_the_chosen_rows(chain):
    def pick_one(opps):
        return {"rows": opps[:1], "rows_beyond_game_cap": len(opps) - 1, "rows_total_budget": 1600}

    chain["select_result"] = pick_one
    overlay = bga.build_inplay_overlay("wncaab", "2026-11-16", [{"event_id": "e1"}, {"event_id": "e2"}])
    assert chain["cards_got"] == [[{"event_id": "e1", "market": "spread", "kind": "game", "sport": "wncaab"}]]
    assert overlay["shortlist_refused"] == {"rows_beyond_game_cap": 1}


def test_no_rows_means_no_select_call_and_no_refusals(chain):
    overlay = bga.build_inplay_overlay("wncaab", "2026-11-16", [])
    assert chain["select_calls"] == 0
    assert overlay["shortlist_refused"] == {} and overlay["opportunities"] == 0


# --- the log line -----------------------------------------------------------------------------------------


def _overlay_line(chain, capsys, monkeypatch, tmp_path, rows):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(bga, "_publish_inplay_overlay", lambda path: True)
    bga._write_inplay_overlay_best_effort("wncaab", "2026-11-16", {"generated_at": "G", "rows": rows})
    return [l for l in capsys.readouterr().out.splitlines() if "INPLAY_OVERLAY sport=wncaab" in l][0]


def _live(event_id):
    return {"event_id": event_id, "game": {"state": "live"}, "seen_age_seconds": 10}


def test_the_log_line_carries_the_refusals_as_its_last_space_free_token(chain, capsys, monkeypatch, tmp_path):
    chain["select_result"] = _floor_refuses_all
    line = _overlay_line(chain, capsys, monkeypatch, tmp_path, [_live("e1"), _live("e2")])
    assert "cards=0" in line
    tokens = line.split()
    assert tokens[-1] == 'refused={"rows_below_value_floor":2}'
    assert json.loads(tokens[-1].split("=", 1)[1]) == {"rows_below_value_floor": 2}
    # Every token after the tag still parses as key=value, the way the fleet readers split it.
    assert all("=" in t for t in tokens[tokens.index("INPLAY_OVERLAY") + 1:])


def test_the_log_line_says_refused_empty_when_nothing_was_refused(chain, capsys, monkeypatch, tmp_path):
    line = _overlay_line(chain, capsys, monkeypatch, tmp_path, [_live("e1")])
    assert "cards=1" in line and line.split()[-1] == "refused={}"


def test_the_lookups_pair_stays_adjacent_and_ahead_of_refused(chain, capsys, monkeypatch, tmp_path):
    """The nba-overlay-card-cost lane reads `lookups_resolved=N lookups_reused=M` as an adjacent pair."""
    chain["select_result"] = _floor_refuses_all
    line = _overlay_line(chain, capsys, monkeypatch, tmp_path, [_live("e1")])
    tokens = line.split()
    names = [t.split("=", 1)[0] for t in tokens]
    if "lookups_resolved" in names:
        at = names.index("lookups_resolved")
        assert names[at + 1] == "lookups_reused"
        assert at + 1 < names.index("refused")
    else:
        assert "lookup_scope" in names and names.index("lookup_scope") < names.index("refused")
    assert names[-1] == "refused"
