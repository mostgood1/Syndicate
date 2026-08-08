"""A posted lineup must move the sim-input fingerprint.

THE DEFECT (docs/ai_context/audit_sim_invalidation_rules.md, finding 2):
`_mlb_sim_input_fingerprint_by_game` hashed four inputs, and the lineup one --
`lineups_last_known_by_team.json` -- is written by `daily_update.py` ITSELF, the
run the fingerprint is supposed to trigger:

    sim runs -> lineups rewritten -> fingerprint matches -> no resim
             -> lineups never refresh -> no resim

So a posted lineup could not move the fingerprint that would cause it to be
read. Detection was incidental, riding on odds churn -- which #48 deliberately
damped to stop it firing on every refresh.

`_fetch_mlb_injuries` is the precedent for the fix; the same fix was never
applied to lineups. These tests pin the corrected behaviour, and in particular
the two things a careless implementation gets wrong: firing on status churn
(re-introducing the over-simming just removed), and treating a failed fetch as
a lineup retraction.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared.mlb_lineup_state import lineup_slice_for_game


def _payload(**games):
    return {"date": "2026-08-07", "games": games}


_NOT_POSTED = {
    "status": "Scheduled",
    "lineups_posted": False,
    "home_batting_order": [],
    "away_batting_order": [],
    "home_probable_pitcher": 543037,
    "away_probable_pitcher": 519242,
}

_POSTED = {
    "status": "Pre-Game",
    "lineups_posted": True,
    "home_batting_order": [1, 2, 3, 4, 5, 6, 7, 8, 9],
    "away_batting_order": [11, 12, 13, 14, 15, 16, 17, 18, 19],
    "home_probable_pitcher": 543037,
    "away_probable_pitcher": 519242,
}


def test_posting_a_lineup_changes_the_slice():
    """The headline. Before this input existed, this transition was invisible."""
    before = lineup_slice_for_game(_payload(**{"823514": _NOT_POSTED}), "823514")
    after = lineup_slice_for_game(_payload(**{"823514": _POSTED}), "823514")
    assert before != after, "a posted lineup did not move the fingerprint input"
    assert before["lineups_posted"] is False
    assert after["lineups_posted"] is True


def test_a_changed_starter_changes_the_slice():
    """Start changes are half the named concern, and pitcher props key off the
    starter."""
    swapped = {**_POSTED, "home_probable_pitcher": 999999}
    assert lineup_slice_for_game(_payload(**{"823514": _POSTED}), "823514") != lineup_slice_for_game(
        _payload(**{"823514": swapped}), "823514"
    )


def test_a_reordered_lineup_changes_the_slice():
    reordered = {**_POSTED, "home_batting_order": [9, 8, 7, 6, 5, 4, 3, 2, 1]}
    assert lineup_slice_for_game(_payload(**{"823514": _POSTED}), "823514") != lineup_slice_for_game(
        _payload(**{"823514": reordered}), "823514"
    )


def test_status_churn_does_NOT_change_the_slice():
    """Deliberate exclusion.

    `status` walks Scheduled -> Pre-Game -> Warmup -> In Progress on its own
    schedule. Hashing it would fire a resim on every transition -- exactly the
    over-simming that `fddb82fd` just removed from the tip-off window.
    """
    a = lineup_slice_for_game(_payload(**{"823514": {**_POSTED, "status": "Pre-Game"}}), "823514")
    b = lineup_slice_for_game(_payload(**{"823514": {**_POSTED, "status": "In Progress"}}), "823514")
    assert a == b, "status churn leaked into the fingerprint -- this re-introduces over-simming"


def test_absent_game_hashes_a_stable_empty_shape():
    """Not None, and not a varying shape: a game missing from the payload must
    hash identically every time, or the fingerprint jitters between 'absent'
    and 'empty' and resims forever."""
    one = lineup_slice_for_game(_payload(), "823514")
    two = lineup_slice_for_game(_payload(**{"999": _POSTED}), "823514")
    assert one == two
    assert one["lineups_posted"] is False


def test_half_posted_is_not_posted():
    """Both sides required. Treating a half-posted slate as posted would retire
    the resim that should fire when the second team posts."""
    from syndicate.features.shared.mlb_lineup_state import fetch_mlb_lineup_state  # noqa: F401

    half = {**_POSTED, "away_batting_order": [], "lineups_posted": False}
    assert lineup_slice_for_game(_payload(**{"823514": half}), "823514")["lineups_posted"] is False


def test_garbage_payload_does_not_raise():
    for junk in (None, [], "nope", {"games": "nope"}, {}):
        assert lineup_slice_for_game(junk, "823514")["lineups_posted"] is False


# ---------------------------------------------------------------------------
# The refresh itself must not write an empty payload on failure.
# ---------------------------------------------------------------------------


def test_failed_fetch_does_not_overwrite_state(monkeypatch, tmp_path):
    """An empty games map is indistinguishable from 'lineups not posted yet'.

    Writing one on a transport failure would read as a lineup RETRACTION and
    move the fingerprint the wrong way -- firing a resim that un-learns a
    posted lineup. Same class of error as a swallowed timeout reading as 'no
    games', which this audit kept tripping over.
    """
    from syndicate.features.shared import live_refresh_loop

    wrote = []
    monkeypatch.setattr(live_refresh_loop, "write_json_file", lambda p, v: wrote.append((p, v)))
    monkeypatch.setattr(
        "syndicate.features.shared.mlb_lineup_state.fetch_mlb_lineup_state",
        lambda *_a, **_k: (_ for _ in ()).throw(TimeoutError("statsapi slow")),
    )
    assert live_refresh_loop._fetch_mlb_lineup_state("2026-08-07") is False
    assert wrote == [], "a failed fetch wrote state anyway"


def test_empty_games_response_does_not_overwrite_state(monkeypatch):
    from syndicate.features.shared import live_refresh_loop

    wrote = []
    monkeypatch.setattr(live_refresh_loop, "write_json_file", lambda p, v: wrote.append((p, v)))
    monkeypatch.setattr(
        "syndicate.features.shared.mlb_lineup_state.fetch_mlb_lineup_state",
        lambda *_a, **_k: {"date": "2026-08-07", "games": {}, "games_total": 0},
    )
    assert live_refresh_loop._fetch_mlb_lineup_state("2026-08-07") is False
    assert wrote == []


def test_successful_fetch_writes_state(monkeypatch):
    from syndicate.features.shared import live_refresh_loop

    wrote = []
    monkeypatch.setattr(live_refresh_loop, "write_json_file", lambda p, v: wrote.append((p, v)))
    monkeypatch.setattr(
        "syndicate.features.shared.mlb_lineup_state.fetch_mlb_lineup_state",
        lambda *_a, **_k: {"date": "2026-08-07", "games": {"823514": _POSTED},
                           "games_total": 1, "games_with_posted_lineups": 1},
    )
    assert live_refresh_loop._fetch_mlb_lineup_state("2026-08-07") is True
    assert len(wrote) == 1


# ---------------------------------------------------------------------------
# End to end: the fingerprint itself.
# ---------------------------------------------------------------------------


class _Event:
    def __init__(self, event_id):
        self.event_id = event_id
        self.home = "Home Team"
        self.away = "Away Team"
        self.home_team_id = None
        self.away_team_id = None


def test_fingerprint_moves_when_lineups_post(monkeypatch, tmp_path):
    """The whole point: the per-game hash must differ before and after posting."""
    from syndicate.features.shared import live_refresh_loop

    monkeypatch.setattr(live_refresh_loop, "data_root", lambda: tmp_path)
    events = [_Event("823514")]

    state = {"doc": _payload(**{"823514": _NOT_POSTED})}
    monkeypatch.setattr(
        live_refresh_loop,
        "_read_json_file_lenient",
        lambda p: state["doc"] if "mlb_lineup_state" in str(p) else {},
    )
    before = live_refresh_loop._mlb_sim_input_fingerprint_by_game("2026-08-07", events)

    state["doc"] = _payload(**{"823514": _POSTED})
    after = live_refresh_loop._mlb_sim_input_fingerprint_by_game("2026-08-07", events)

    assert before["823514"] != after["823514"], (
        "posting a lineup left the fingerprint unchanged -- the resim would never fire"
    )
