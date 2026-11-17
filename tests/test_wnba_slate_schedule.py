"""`wnba_slate_verdict`: the per-date answer to "does the WNBA schedule put a game on DATE?".

Lane wnba-boxscore-polling-per-date (2026-11-17). Only a READABLE schedule that lists
no game on the date may skip; every other outcome is UNKNOWN and polls. These tests
pin both halves, because an under-count would skip a live game and an over-cautious
gate would leave ~1,600 empty requests a day on web.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from syndicate.features.wnba import slate_schedule as mod

# Captured before the autouse fixture stubs it, for the one test that reads the real one.
_REAL_CONTEXT_COUNT = mod._cards_context_game_count

HEADER = (
    "game_id,season_type_slug,game_status_text,date_utc,time_utc,date_est,time_est,"
    "home_tricode,away_tricode\n"
)


def _row(game_id: str, date_est: str, date_utc: str | None = None) -> str:
    return f"{game_id},regular-season,Scheduled,{date_utc or date_est},23:00,{date_est},19:00,NYL,IND\n"


def _write(root: Path, year: str, body: str) -> Path:
    path = root / "wnba_source" / "data" / "processed" / f"schedule_{year}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _fresh_memo(monkeypatch):
    mod._clear_memo_for_tests()
    # The cards-context cross-check is exercised on its own below; elsewhere it must
    # not depend on whatever this machine has published.
    monkeypatch.setattr(mod, "_cards_context_game_count", lambda _d: None)
    yield
    mod._clear_memo_for_tests()


def test_a_date_with_games_is_polled(tmp_path):
    _write(tmp_path, "2026", HEADER + _row("1", "2026-06-05") + _row("2", "2026-06-05"))
    verdict = mod.wnba_slate_verdict("2026-06-05", data_root=tmp_path)
    assert (verdict.games, verdict.skip, verdict.reason) == (2, False, "schedule_has_games")


def test_a_date_the_schedule_lists_nothing_on_is_skipped(tmp_path):
    _write(tmp_path, "2026", HEADER + _row("1", "2026-06-05") + _row("2", "2026-10-31"))
    verdict = mod.wnba_slate_verdict("2026-11-17", data_root=tmp_path)
    assert (verdict.games, verdict.skip, verdict.reason) == (0, True, "schedule_has_no_games")
    assert verdict.schedule_rows == 2
    assert "reason=schedule_has_no_games" in verdict.log_fields()


def test_an_evening_game_counts_on_both_its_eastern_and_its_utc_date(tmp_path):
    """9 PM ET on 06-05 is 01:00Z on 06-06. Counting both dates over-polls by one
    date at worst; counting only one could skip a live game."""
    _write(tmp_path, "2026", HEADER + _row("1", "2026-06-05", date_utc="2026-06-06"))
    assert mod.wnba_slate_verdict("2026-06-05", data_root=tmp_path).games == 1
    assert mod.wnba_slate_verdict("2026-06-06", data_root=tmp_path).games == 1
    assert mod.wnba_slate_verdict("2026-06-07", data_root=tmp_path).skip


@pytest.mark.parametrize(
    "body, reason",
    [
        (None, "schedule_absent"),
        (HEADER, "schedule_empty"),
        ("game_id,home_tricode\n1,NYL\n", "schedule_no_date_columns"),
        (HEADER + _row("1", "2026-06-05") + "2,regular-season,TBD,,,,,NYL,IND\n", "schedule_undated_rows"),
    ],
)
def test_unknown_never_skips(tmp_path, body, reason):
    """Absent, empty, schema-drifted or partly undated: UNKNOWN, which polls.
    An unreadable slate must not turn polling off for a date that has games."""
    if body is not None:
        _write(tmp_path, "2026", body)
    verdict = mod.wnba_slate_verdict("2026-11-17", data_root=tmp_path)
    assert verdict.games is None and verdict.unknown and not verdict.skip
    assert verdict.reason == reason


def test_an_unreadable_file_is_unknown_not_a_crash(tmp_path):
    path = _write(tmp_path, "2026", "")
    path.write_bytes(b"\xff\xfe\x00garbage-not-utf8\x80\x81")
    verdict = mod.wnba_slate_verdict("2026-11-17", data_root=tmp_path)
    assert (verdict.games, verdict.reason) == (None, "schedule_unreadable")


def test_a_bad_date_is_unknown(tmp_path):
    verdict = mod.wnba_slate_verdict("not-a-date", data_root=tmp_path)
    assert (verdict.games, verdict.reason) == (None, "bad_date")


def test_the_year_of_the_date_picks_the_file(tmp_path):
    """There is no carry-over from last season's file: 2027 with no schedule_2027.csv
    is UNKNOWN, not "empty because 2026 ended"."""
    _write(tmp_path, "2026", HEADER + _row("1", "2026-06-05"))
    verdict = mod.wnba_slate_verdict("2027-01-05", data_root=tmp_path)
    assert (verdict.games, verdict.reason) == (None, "schedule_absent")
    assert verdict.schedule_path.endswith("schedule_2027.csv")


def test_a_rewritten_schedule_is_reread(tmp_path):
    """`fetch-schedule` rewrites the file on every refresh; a game added to a date
    must un-skip that date on the next call, not after a restart."""
    path = _write(tmp_path, "2026", HEADER + _row("1", "2026-06-05"))
    assert mod.wnba_slate_verdict("2026-10-09", data_root=tmp_path).skip
    path.write_text(HEADER + _row("1", "2026-06-05") + _row("2", "2026-10-09"), encoding="utf-8")
    later = time.time() + 5
    os.utime(path, (later, later))
    assert mod.wnba_slate_verdict("2026-10-09", data_root=tmp_path).games == 1


def test_a_published_slate_with_games_overrules_an_empty_schedule(tmp_path, monkeypatch):
    """The cards context can only UN-skip. A schedule that missed a game (say a
    playoff game added after its last fetch) must not silence that date."""
    _write(tmp_path, "2026", HEADER + _row("1", "2026-06-05"))
    monkeypatch.setattr(mod, "_cards_context_game_count", lambda d: 2 if d == "2026-10-09" else 0)
    verdict = mod.wnba_slate_verdict("2026-10-09", data_root=tmp_path)
    assert (verdict.games, verdict.reason, verdict.skip) == (2, "cards_context_has_games", False)
    # ...and an EMPTY context never causes a skip on its own: it is only consulted
    # once the schedule has already said "none".
    assert mod.wnba_slate_verdict("2026-11-17", data_root=tmp_path).skip


def test_the_cards_context_reader_ignores_another_dates_slate(monkeypatch):
    import syndicate.features.wnba.cards as cards

    monkeypatch.setattr(
        cards, "load_published_cards_page_context",
        lambda d: ({"date": "2026-11-16", "games": [{"event_id": "x"}]}, 10.0, False),
    )
    assert _REAL_CONTEXT_COUNT("2026-11-17") is None
    monkeypatch.setattr(
        cards, "load_published_cards_page_context",
        lambda d: ({"date": d, "games": [{"event_id": "x"}]}, 10.0, False),
    )
    assert _REAL_CONTEXT_COUNT("2026-11-17") == 1
    monkeypatch.setattr(cards, "load_published_cards_page_context", lambda d: (None, None, False))
    assert _REAL_CONTEXT_COUNT("2026-11-17") is None
