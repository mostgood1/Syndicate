"""NFL's live STATUS source, wired 2026-09-28.

Measured that evening with PHI @ CHI in Q2:

    LIVE_GAME_STATE_JOIN sport=nfl supported=False corrected=0
      reason="no live status source wired for nfl"

so every NFL board row stayed `pregame` and no live projection or actual-so-far
could attach. The source was never missing -- `poll_nfl_live_state` parsed that
game correctly on demand (`period=2`, `status="2:24 - 2nd"`, both scores). What
was missing was a WRITER: the only caller was settlement's lazy capture, which
fetches ONLY when the record is absent or has no games --

    if not isinstance(record, Mapping) or not record.get("games"):

-- never when it is merely STALE, so a capture written before kickoff sat
unrefreshed for the whole game. And `board_enrichment._read_nfl_capture` must not
fetch (board cycle, OOM history `#241`). A reader that cannot fetch plus a writer
that cannot refresh is no source at all.

`test_an_unstamped_capture_is_treated_as_stale` is the important one. NFL's poller
did not stamp `fetched_at` and NCAAF's always has; the football arm skips any
capture whose age it cannot establish, so admitting `nfl` to
`_LIVE_GAME_STATE_SPORTS` without adding that stamp would have changed NOTHING
while looking fully wired.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from syndicate.features.shared import board_enrichment as be

_DATE = "2026-09-28"
_KICKOFF = "2026-09-29T00:15:00Z"


def _capture(*, in_progress=True, final=False, stamped=True, age_s=5.0, status="2:24 - 2nd"):
    record = {
        "date": _DATE,
        "count": 1,
        "finals": 1 if final else 0,
        "games": [{
            "event_id": "401872963",
            "home_team": "Chicago Bears", "away_team": "Philadelphia Eagles",
            "home_abbr": "CHI", "away_abbr": "PHI",
            "home_score": 7, "away_score": 0,
            "period": 2, "in_progress": in_progress, "final": final,
            "status": status, "start_time": _KICKOFF,
        }],
    }
    if stamped:
        record["fetched_at"] = time.time() - age_s
    return record


def _row():
    return {
        "kind": "prop", "sport": "nfl", "commence_time": _KICKOFF,
        "home_team": "Chicago Bears", "away_team": "Philadelphia Eagles",
        "game": {"matchup": "PHI @ CHI", "state": "pregame", "status_token": "7:15P CT"},
        "game_state": "pregame",
    }


def _run(grid, record, *, sport="nfl"):
    """Drive the real join with a patched capture read -- the reader is read-only
    by design, so patching it is the whole seam."""
    games = [g for g in (record.get("games") or [])] if record else []
    fetched_at = record.get("fetched_at") if record else None
    with patch.object(be, "_read_nfl_capture", return_value=(games, fetched_at)):
        return be.attach_live_game_state_from_lens(grid, sport=sport, selected_date=_DATE)


def test_the_capture_reader_returns_games_and_its_stamp() -> None:
    rec = _capture()
    with patch("syndicate.features.shared.refresh_state_store.read_json_file", return_value=rec):
        games, fetched_at = be._read_nfl_capture(_DATE)
    assert len(games) == 1
    assert fetched_at == pytest.approx(rec["fetched_at"])


def test_the_reader_survives_a_missing_or_malformed_record() -> None:
    for bad in (None, [], "x", 3, {"games": "nope"}):
        with patch("syndicate.features.shared.refresh_state_store.read_json_file", return_value=bad):
            games, fetched_at = be._read_nfl_capture(_DATE)
        assert games == []


def test_nfl_is_admitted_to_the_supported_set() -> None:
    """`off != on`: this is the line whose absence produced
    `supported=False reason="no live status source wired for nfl"`."""
    assert "nfl" in be._LIVE_GAME_STATE_SPORTS
    assert "ncaaf" in be._LIVE_GAME_STATE_SPORTS  # unchanged


def test_without_nfl_in_the_set_the_join_refuses_BY_NAME(monkeypatch: pytest.MonkeyPatch) -> None:
    """The pre-fix behaviour, reproduced. Also confirms the refusal was always
    ATTRIBUTED -- which is why wiring this was not forbidden by the
    'no second fix without an instrument' rule."""
    monkeypatch.setattr(be, "_LIVE_GAME_STATE_SPORTS", frozenset({"mlb", "soccer", "ncaaf"}))
    out = be.attach_live_game_state_from_lens([_row()], sport="nfl", selected_date=_DATE)
    assert out["supported"] is False
    assert out["reason"] == "no live status source wired for nfl"


def test_an_unstamped_capture_is_treated_as_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE INERTNESS GUARD. NFL's poller did not stamp `fetched_at`. An unstamped
    record fails the age test identically to an ancient one, so the whole wiring
    would have been silently inert. This asserts the arm does NOT accept it -- and
    `test_the_poller_stamps_fetched_at` asserts the stamp now exists, so the pair
    together is what makes the source real."""
    out = _run([_row()], _capture(stamped=False))
    assert out.get("supported") is True
    assert out.get("rows_corrected") in (0, None)
    assert "nfl capture" in str(out.get("reason") or "")


def test_a_capture_older_than_the_bound_is_refused() -> None:
    out = _run([_row()], _capture(age_s=be._LENS_STATE_MAX_AGE_SECONDS + 60))
    assert "nfl capture" in str(out.get("reason") or "")


def test_the_refusal_names_NFL_not_ncaaf() -> None:
    """The arm now serves both football codes, so a hardcoded 'ncaaf' would
    misattribute an NFL miss. A reason string that misattributes is worse than
    none."""
    out = _run([_row()], _capture(stamped=False))
    reason = str(out.get("reason") or "")
    assert reason.startswith("nfl "), reason
    assert "ncaaf" not in reason


def test_the_poller_stamps_fetched_at() -> None:
    """Paired with the inertness guard above: the reader requires this stamp and
    NFL's poller never wrote one until 2026-09-28."""
    import scripts.poll_nfl_live_state as poller

    payload = {"events": []}
    with patch.object(poller, "_fetch_scoreboard", return_value=payload):
        record = poller.poll_nfl_live_state(_DATE, persist=False)
    assert "fetched_at" in record
    assert record["fetched_at"] == pytest.approx(time.time(), abs=30)


def test_the_capture_tick_is_wired_into_the_nfl_live_lens_tick() -> None:
    """REACHABILITY for the writer. A tick that exists and is never called is the
    same as no tick -- and nothing else refreshes this capture."""
    from syndicate.features.shared import live_lens_loop as loop

    assert hasattr(loop, "_persist_nfl_live_state")
    import inspect
    body = inspect.getsource(loop._nfl_build_wrapper)
    assert "_persist_nfl_live_state(date_str)" in body, "the wrapper must call the tick"


def test_the_capture_tick_soft_fails(capsys: pytest.CaptureFixture[str]) -> None:
    """A capture is an enrichment; it must never take down the tick carrying it."""
    from syndicate.features.shared import live_lens_loop as loop

    with patch("scripts.poll_nfl_live_state.poll_nfl_live_state", side_effect=RuntimeError("espn down")):
        loop._persist_nfl_live_state(_DATE)  # must not raise
    assert "NFL_LIVE_STATE_CAPTURE status=error" in capsys.readouterr().out


def test_a_FRESH_capture_actually_corrects_a_frozen_pregame_row_to_live() -> None:
    """THE POINT OF THE WHOLE CHANGE, and the one assertion the other ten do not
    make. Everything else here proves the refusals are attributed and the pieces
    are connected; this proves the board row MOVES.

    Production's exact shape: a chip frozen at `pregame` / `7:15P CT` for PHI @ CHI
    while ESPN had it in Q2 7-0.
    """
    rows = [_row()]
    out = _run(rows, _capture())

    assert out.get("supported") is True
    assert out.get("rows_corrected") == 1, out
    assert rows[0]["game"]["state"] == "live"

    # NOT the top-level `game_state`, and that is CORRECT rather than a shortfall.
    # I asserted it first and it failed; the control settled it -- NCAAF, which has
    # been wired and working since 2026-09-10, behaves IDENTICALLY (`game.state`
    # 'live', top-level `game_state` still 'pregame'), and this function never
    # assigns that key for any sport. It is owned downstream in the shortlist
    # pipeline. Pinned here so nobody "fixes" NFL to diverge from NCAAF.
    assert rows[0].get("game_state") == "pregame"


def test_a_final_capture_drives_the_row_to_final() -> None:
    """The other half of what "no live status source" cost: a finished game left
    reading `pregame` is exactly the row `#340`'s live-edge guard keys on."""
    rows = [_row()]
    out = _run(rows, _capture(in_progress=False, final=True, status="Final"))

    assert out.get("rows_corrected") == 1, out
    assert rows[0]["game"]["state"] == "final"


def test_a_pregame_capture_corrects_nothing() -> None:
    """Only in-play and finished games are offered; a pregame capture has nothing
    to correct, and must not report a correction it did not make."""
    rows = [_row()]
    out = _run(rows, _capture(in_progress=False, final=False, status="7:15 PM ET"))

    assert out.get("rows_corrected") in (0, None)
    assert rows[0]["game"]["state"] == "pregame"
