"""A transient ESPN failure must not null a live WNBA slate.

WHY THIS EXISTS. `_public_scoreboard_live_state_payload` was
`except Exception: return None`, silently. Every caller then saw zero public
games, no live merge happened, and the published lens carried
`in_progress: False, clock: None, pts: None-None` for games genuinely in
progress -- at which point `cards.py`'s own source rule (`live_projection` only
when `is_live` AND `live_margin` AND `elapsed_min`) downgraded every game to
`pregame` and the Layer 1 board lost its whole live tier.

OBSERVED IN PRODUCTION 2026-08-16, end to end:

    22:50:31Z  board served 149 live-aware WNBA game rows
    22:57:22Z  same board served 309 game rows and ZERO, while CHI @ SEA and
               IND @ ATL were still live at 78-74 and 78-77
    22:57:43Z  lens read sources=['pregame'], in_progress=False, clock=None,
               pts=None-None for all three games
    23:19:10Z  recovered on its own, unchanged code

A blip, published as fact. These tests pin the smoothing AND its limits -- the
limits matter more, because a carried board that looked fresh, or one that
invented a slate, would be worse than the nulls being replaced.
"""

from __future__ import annotations

import json

import pytest

import syndicate.features.wnba.cards as cards


@pytest.fixture(autouse=True)
def _clean_store(monkeypatch):
    cards._clear_public_scoreboard_last_good()
    monkeypatch.delenv("WNBA_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS", raising=False)
    yield
    cards._clear_public_scoreboard_last_good()


def _store(date="2026-08-16", *, age_seconds=0.0, games=2):
    cards._PUBLIC_SCOREBOARD_LAST_GOOD[date] = (
        cards.time.monotonic() - age_seconds,
        "2026-08-16T22:50:31Z",
        {"date": date, "games": [{"event_id": str(i)} for i in range(games)]},
    )


def test_a_failed_fetch_carries_the_last_good_board():
    _store()
    out = cards._carried_forward_scoreboard("2026-08-16", reason="TimeoutError")
    assert out is not None
    assert len(out["games"]) == 2


def test_the_carried_board_is_MARKED_and_never_looks_fresh():
    """The single most important assertion here.

    A carried payload that presented as current would be a worse defect than
    the nulls it replaces -- it would put a stale score behind a live label
    with nothing saying so.
    """
    _store(age_seconds=42.0)
    out = cards._carried_forward_scoreboard("2026-08-16", reason="HTTPError")
    assert out["carried_forward"] is True
    assert out["carried_forward_age_seconds"] == pytest.approx(42.0, abs=1.0)
    assert out["carried_forward_reason"] == "HTTPError"
    assert out["carried_forward_from"] == "2026-08-16T22:50:31Z"


def test_past_the_age_bound_it_refuses_and_forgets():
    """An honest absence beats a stale score presented as current.

    The entry is also dropped, so a later failure cannot resurrect an even
    older board and the store cannot grow a tail of dead dates.
    """
    _store(age_seconds=999.0)
    assert cards._carried_forward_scoreboard("2026-08-16", reason="TimeoutError") is None
    assert "2026-08-16" not in cards._PUBLIC_SCOREBOARD_LAST_GOOD


def test_the_kill_switch_restores_the_old_behaviour_exactly(monkeypatch):
    monkeypatch.setenv("WNBA_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS", "0")
    _store()
    assert cards._carried_forward_scoreboard("2026-08-16", reason="X") is None


def test_a_negative_bound_is_a_typo_not_a_disable(monkeypatch):
    """Same rule as MLB's gate: a negative value must not read as "disabled",
    because that is the one misreading that silently turns the fix off."""
    monkeypatch.setenv("WNBA_LIVE_STATE_CARRY_FORWARD_MAX_AGE_SECONDS", "-5")
    assert cards._public_scoreboard_carry_max_age_seconds() == 180


def test_nothing_stored_is_not_an_error():
    assert cards._carried_forward_scoreboard("2026-08-16", reason="X") is None


def test_a_failed_fetch_uses_the_carry_and_a_success_refreshes_it(monkeypatch):
    """THE CALL PATH, not just the helper.

    This is the lesson from earlier in this same session: a helper verified
    with self-supplied arguments proves the FUNCTION, never that production
    reaches it. So this drives the real
    `_public_scoreboard_live_state_payload` with a patched urlopen.
    """
    _store(games=3)

    def _boom(*a, **k):
        raise TimeoutError("espn timed out")

    monkeypatch.setattr(cards.urllib_request, "urlopen", _boom)
    out = cards._public_scoreboard_live_state_payload("2026-08-16")
    assert out is not None, "a transient failure must not null a live slate"
    assert out["carried_forward"] is True
    assert len(out["games"]) == 3


def test_a_200_with_no_events_is_NOT_carried(monkeypatch):
    """Out of season, or a date with no slate, legitimately has no events.

    Carrying a previous board over that would INVENT a slate, which is a
    different and worse failure than the one being fixed. Only a FAILED fetch
    is smoothed.
    """
    _store(games=3)

    class _Resp:
        def read(self):
            return b'{"events": []}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(cards.urllib_request, "urlopen", lambda *a, **k: _Resp())
    assert cards._public_scoreboard_live_state_payload("2026-08-16") is None


def _espn(short_detail, state, completed):
    return json.dumps({"events": [{"id": "401857150", "competitions": [{"competitors": [
        {"homeAway": "away", "score": "95", "team": {"abbreviation": "IND"}},
        {"homeAway": "home", "score": "91", "team": {"abbreviation": "ATL"}}]}],
        "status": {"type": {"state": state, "completed": completed,
                            "shortDetail": short_detail, "period": 5}}}]}).encode()


class _R:
    def __init__(self, body): self._b = body
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False


@pytest.mark.parametrize(
    "short_detail,state,completed,want_final,want_live",
    [
        # THE PRODUCTION DEFECT, 2026-08-17 02:5xZ: IND @ ATL read
        # status='Final/OT' with final=False, in_progress=True -- the record
        # contradicted itself because ESPN flips its display text before its
        # state flags. A completed overtime game was published as in progress.
        ("Final/OT", "in", False, True, False),
        ("Final/2OT", "in", False, True, False),
        ("Final", "post", True, True, False),
        # A genuinely live game must be UNTOUCHED.
        ("9.7 - 4th", "in", False, False, True),
        ("6:08P CT", "pre", False, False, False),
        # KNOWN PRE-EXISTING BUG, SURFACED BY THIS TEST AND NOT FIXED HERE:
        # `_looks_terminal_status_text` matches "final" as a SUBSTRING, so
        # "Semifinal" reads as a finished game. My own ESPN-layer check uses
        # `startswith` and is not the culprit; the shared helper is, and it is
        # used by every sport. Marked xfail rather than silently dropped, and
        # rather than patching a shared predicate blind at the end of a session.
        pytest.param("Semifinal", "pre", False, False, False,
                     marks=pytest.mark.xfail(reason="_looks_terminal_status_text matches 'final' inside 'Semifinal' (shared helper, pre-existing)", strict=True)),
    ],
)
def test_final_text_corroborates_final_and_never_invents_live(
    monkeypatch, short_detail, state, completed, want_final, want_live
):
    """Text can only ADD `final`, never remove it and never add `in_progress`.

    A heuristic that could mark a game LIVE off prose is how soccer's board once
    showed every game live (`#160`), so this direction is deliberate.
    """
    monkeypatch.setattr(
        cards.urllib_request, "urlopen",
        lambda *a, **k: _R(_espn(short_detail, state, completed)),
    )
    out = cards._public_scoreboard_live_state_payload("2026-08-16")
    assert out is not None
    game = out["games"][0]
    assert bool(game["final"]) is want_final
    assert bool(game["in_progress"]) is want_live
