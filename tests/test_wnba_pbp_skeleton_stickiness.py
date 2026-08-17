"""`#455` — a WNBA pbp skeleton must never be served over real data, or stored.

MEASURED IN PRODUCTION 2026-08-16. On a slate the user could see was two games
FINAL and one LIVE, `/wnba/api/live_pbp_stats` returned three all-null records
with `ok: True`, and `generated_at` read 16:14:21 CDT — still 16:14:21 on a
`ttl=1` refetch three hours later.

The mechanism was `bool(games)`: the skeleton carries one entry per event id, so
a skeleton written pregame satisfied the stored-payload short-circuit and was
served in preference to real data for the rest of the day.
"""

from __future__ import annotations

from typing import Any

import pytest

from syndicate.features.wnba import cards


def _skeleton_game(event_id: str = "401857148") -> dict[str, Any]:
    """Byte-for-byte the shape `build_live_pbp_stats_payload` emits."""
    return {
        "event_id": event_id,
        "game_id": event_id,
        "home": None,
        "away": None,
        "pbp_attempts": {"home": {}, "away": {}, "unknown": {}, "total": {}},
        "pbp_attempts_periods": {},
        "pbp_possessions": {"home": {}, "away": {}, "unknown": {}, "total": {}},
        "pbp_possessions_periods": {},
        "pbp_quarters": {"q_totals": {"q1": None, "q2": None, "q3": None, "q4": None},
                         "current": {"period": None, "q_total": None}},
        "pbp_recent": {"window_sec": 180, "points_total": None, "attempts": None,
                       "possessions": None,
                       "current_scoring_run": {"team": None, "points": None},
                       "seconds_since_score": None},
    }


def _real_game(event_id: str = "PHX@TOR") -> dict[str, Any]:
    game = _skeleton_game(event_id)
    game["pbp_possessions"] = {
        "home": {"poss_est": 0.0}, "away": {"poss_est": 0.0},
        "PHX": {"poss_est": 73.0, "tov": 11, "oreb": 7},
        "TOR": {"poss_est": 73.04, "tov": 12, "oreb": 9},
        "total": {"poss_est": 146.04},
    }
    game["pbp_quarters"] = {"q_totals": {"q1": 38, "q2": 44, "q3": 45, "q4": 36},
                            "current": {"period": 4, "q_total": 36}}
    return game


# --------------------------------------------------------------------------
# the predicate
# --------------------------------------------------------------------------


def test_the_production_skeleton_has_no_signal():
    assert cards._has_pbp_signal(_skeleton_game()) is False


def test_a_real_record_has_signal():
    assert cards._has_pbp_signal(_real_game()) is True


def test_zero_valued_home_and_away_are_not_signal():
    """The tricode trap: home/away read 0.0 on 17 of 17 populated records."""
    game = _skeleton_game()
    game["pbp_possessions"] = {"home": {"poss_est": 0.0}, "away": {"poss_est": 0.0},
                               "total": {"poss_est": 0.0}}
    assert cards._has_pbp_signal(game) is False


def test_the_key_filter_is_load_bearing_independently_of_the_value_check():
    """The test above passes for the WRONG REASON; this one fixes that.

    Caught by mutation (W3): removing `home`/`away` from `_PBP_NON_TEAM_KEYS`
    changed nothing, because `poss_est > 0` already rejects the 0.0 they carry
    on real data. So that test pinned the value check, not the key filter, and
    the key filter could have been deleted silently.

    The separating case is NON-ZERO values under `home`/`away` with no tricode
    entries — which is what a producer emitting only the aggregate side would
    look like. Counting it would make a record with no per-team data read as
    real, and `total` would then be double-counted against the tricodes
    whenever both were present.

    **This is the second time this exact vacuity appeared in this session** (the
    first was `scripts/wnba_pbp_possessions.py`), which is why it is written out
    rather than just fixed.
    """
    game = _skeleton_game()
    game["pbp_possessions"] = {
        "home": {"poss_est": 73.0}, "away": {"poss_est": 71.0},
        "total": {"poss_est": 144.0}, "unknown": {"poss_est": 5.0},
    }
    assert cards._has_pbp_signal(game) is False, (
        "home/away/total/unknown must be excluded BY KEY, not merely by value"
    )


def test_signal_comes_from_any_of_three_sources():
    """They populate at different moments; possessions-only would drop early ticks."""
    early = _skeleton_game()
    early["pbp_quarters"]["current"]["period"] = 1
    assert cards._has_pbp_signal(early) is True

    attempts = _skeleton_game()
    attempts["pbp_attempts"] = {"PHX": {"fg2_att": 12, "fg3_att": 5, "ft_att": 3},
                                "home": {}, "away": {}, "total": {}}
    assert cards._has_pbp_signal(attempts) is True


def test_predicate_never_raises():
    """It runs on every record of every request; a raise here is an outage."""
    for bad in (None, {}, "", 0, [], object(), {"pbp_possessions": "banana"},
                {"pbp_quarters": {"q_totals": "nope"}}):
        assert cards._has_pbp_signal(bad) is False


# --------------------------------------------------------------------------
# the stored-payload short-circuit
# --------------------------------------------------------------------------


@pytest.fixture
def stub(monkeypatch):
    """Isolate `build_live_pbp_stats_payload` from context + persistence."""
    state = {"persisted": []}

    def install(stored):
        monkeypatch.setattr(cards, "build_cards_page_context",
                            lambda date, **kw: {"date": date})
        monkeypatch.setattr(cards, "_filtered_local_live_snapshot_payload",
                            lambda kind, date, ids: stored)
        monkeypatch.setattr(cards, "_attach_odds_refresh_timestamp", lambda payload: payload)

        def fake_persist(kind, date, payload):
            state["persisted"].append(payload)
            return payload

        monkeypatch.setattr(cards, "_maybe_persist_current_day_live_snapshot_artifact",
                            fake_persist)
        return state

    return install


def test_a_stored_skeleton_is_not_served_over_real_data(stub):
    """THE DEFECT. Before the fix this returned the STORED skeleton.

    **This assertion needs a sentinel and the first version did not have one.**
    Caught by mutation (W1): reverting the short-circuit to `bool(games)` left
    every assertion passing, because a replayed skeleton and a freshly built one
    are both all-null — "no signal" cannot tell them apart. The stored payload
    therefore carries a marker no freshly built payload can have, and the test
    asserts the marker is ABSENT from the output.
    """
    stored = {"games": [_skeleton_game("401857148")], "date": "2026-08-16",
              "stored_sentinel": "this-came-from-the-snapshot-store"}
    state = stub(stored)
    out = cards.build_live_pbp_stats_payload("2026-08-16", ["401857148"], ttl=20)

    assert "stored_sentinel" not in out, (
        "the stored skeleton was replayed instead of being rejected"
    )
    assert all(cards._has_pbp_signal(g) is False for g in out["games"])
    # ...and it must not have been written back either.
    assert state["persisted"] == []


def test_a_stored_payload_with_real_signal_is_still_served(stub):
    """Guards against the fix breaking the healthy path."""
    stub({"games": [_real_game("PHX@TOR")], "date": "2026-08-16", "ok": True})
    out = cards.build_live_pbp_stats_payload("2026-08-16", ["PHX@TOR"], ttl=20)
    assert [g["game_id"] for g in out["games"]] == ["PHX@TOR"]
    assert cards._has_pbp_signal(out["games"][0]) is True


def test_a_partially_real_stored_payload_is_served(stub):
    """One real game among skeletons is still real data and must not be discarded."""
    stub({"games": [_skeleton_game("a"), _real_game("PHX@TOR")], "date": "2026-08-16"})
    out = cards.build_live_pbp_stats_payload("2026-08-16", [], ttl=20)
    assert len(out["games"]) == 2


# --------------------------------------------------------------------------
# the persist gate -- what made it sticky
# --------------------------------------------------------------------------


def test_the_skeleton_is_never_persisted(stub):
    """Writing it is what made the defect sticky.

    Once stored, the skeleton satisfied the short-circuit on every later
    request, so the endpoint could never recover within the day.
    """
    state = stub(None)
    out = cards.build_live_pbp_stats_payload("2026-08-16", ["401", "402"], ttl=20)
    assert len(out["games"]) == 2
    assert all(cards._has_pbp_signal(g) is False for g in out["games"])
    assert state["persisted"] == [], "a skeleton was written to the snapshot store"


def test_an_empty_event_id_list_yields_no_games_and_no_write(stub):
    state = stub(None)
    out = cards.build_live_pbp_stats_payload("2026-08-16", [], ttl=20)
    assert out["games"] == []
    assert state["persisted"] == []

def test_pbp_recent_is_a_signal_source_but_window_sec_alone_is_not():
    """The gap the existing suite caught, and the trap inside the fix for it.

    `test_live_pbp_stats_payload_uses_local_snapshot` stores a real snapshot
    whose games carry ONLY `pbp_recent.points_total`. Ignoring `pbp_recent`
    rejected that snapshot -- so it is a fourth signal source.

    But the skeleton hardcodes `window_sec: 180`, so counting THAT would make
    every skeleton read as real and silently undo the entire change. These two
    assertions have to hold together.
    """
    real = _skeleton_game()
    real["pbp_recent"] = {"window_sec": 180, "points_total": 14, "attempts": None,
                          "possessions": None,
                          "current_scoring_run": {"team": None, "points": None},
                          "seconds_since_score": None}
    assert cards._has_pbp_signal(real) is True

    # The untouched skeleton already carries window_sec: 180 and nothing else.
    assert _skeleton_game()["pbp_recent"]["window_sec"] == 180
    assert cards._has_pbp_signal(_skeleton_game()) is False


def test_a_nested_scoring_run_counts_as_signal():
    game = _skeleton_game()
    game["pbp_recent"]["current_scoring_run"] = {"team": "PHX", "points": 7}
    assert cards._has_pbp_signal(game) is True
