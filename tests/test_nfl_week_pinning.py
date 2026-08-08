"""NFL's board was date-blind: the same game for every date.

MEASURED on production 2026-08-07: `/api/board/game-chips?sports=nfl` returned
the SAME game_key 401873271 (CAR @ ARI) for 08-05, 08-06, 08-07, 08-08 AND
08-12. Two defects stacked:

1. `_HomeSportDataProviderBase.resolve_context` packs the requested date into
   `context_label` and leaves `week=None`. `_NFLDataProvider.games()` is
   WEEK-KEYED and never read the date at all.
2. With `week=None` it takes the preseason branch, where
   `preseason_target_week` returns `min(weeks whose status != "final")`. Nothing
   rewrites that status column -- `fetch_nfl_preseason_schedule.py` is a manual
   CLI wired into no pipeline -- so it returns 1 forever, and preseason week 1
   contains exactly one game.

Consequence beyond a wrong chip: with no date-correct schedule, NFL
`game.state` never populates, which silently disables `opportunity_gate`'s
dead-market rule and blocks the S2 cadence tiers (they key on game state).
"""

from __future__ import annotations

import pytest

from syndicate.blueprints.home import _nfl_games_on_requested_date


def _games():
    return [
        {"gamePk": "401873271", "label": "CAR@ARI"},   # preseason wk1, played 08-06
        {"gamePk": "401873272", "label": "DET@CIN"},   # preseason wk2, 08-13
    ]


def _fake_events(monkeypatch, ids):
    class _E:
        def __init__(self, event_id):
            self.event_id = event_id

    monkeypatch.setattr(
        "syndicate.features.shared.schedule_adapter.fetch_schedule_for_date",
        lambda sport, date_str, **_k: [_E(i) for i in ids],
    )


def test_only_the_games_on_that_date_survive(monkeypatch):
    _fake_events(monkeypatch, ["401873271"])
    out = _nfl_games_on_requested_date(_games(), "2026-08-06")
    assert [g["label"] for g in out] == ["CAR@ARI"]


def test_a_different_date_yields_a_different_game(monkeypatch):
    """The actual defect: every date returned the same game."""
    _fake_events(monkeypatch, ["401873272"])
    out = _nfl_games_on_requested_date(_games(), "2026-08-13")
    assert [g["label"] for g in out] == ["DET@CIN"]


def test_a_date_with_no_nfl_games_returns_empty(monkeypatch):
    """08-07 genuinely had no NFL games. Returning yesterday's is the bug."""
    _fake_events(monkeypatch, [])
    assert _nfl_games_on_requested_date(_games(), "2026-08-07") == []


def test_a_schedule_failure_leaves_the_board_ALONE(monkeypatch):
    """Fails closed. This is a display filter -- a network blip must not blank
    a board that has real cards."""
    def _boom(*_a, **_k):
        raise RuntimeError("espn unreachable")

    monkeypatch.setattr("syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", _boom)
    out = _nfl_games_on_requested_date(_games(), "2026-08-13")
    assert len(out) == 2


def test_espn_listing_games_we_do_not_have_returns_EMPTY(monkeypatch):
    """The wrong-week case, and the first version got this backwards.

    MEASURED across five dates after deploying that version: 08-13 and 08-14
    both re-served the stale 401873271. ESPN correctly listed 6 and 3 week-2
    games; the card set was preseason WEEK 1 (preseason_target_week still pins
    to 1), so nothing matched and the fall-open branch re-served exactly the
    stale row this function exists to remove.

    If ESPN answered and listed games, an empty match means THE WEEK IS WRONG,
    which we know -- not that ids are incompatible, which we would not. Falling
    open was worse than falling closed.
    """
    _fake_events(monkeypatch, ["999999999"])
    out = _nfl_games_on_requested_date(_games(), "2026-08-13")
    assert out == []


def test_we_only_fall_open_when_espn_CANNOT_ANSWER(monkeypatch):
    """The genuine unknown is handled upstream: no events at all -> unfiltered.
    That is the only case where "we do not know" is true."""
    def _boom(*_a, **_k):
        raise RuntimeError("espn unreachable")

    monkeypatch.setattr("syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", _boom)
    assert len(_nfl_games_on_requested_date(_games(), "2026-08-13")) == 2


@pytest.mark.parametrize("date_value", ["", None, "   "])
def test_no_date_means_no_filtering(monkeypatch, date_value):
    _fake_events(monkeypatch, ["401873271"])
    assert len(_nfl_games_on_requested_date(_games(), date_value)) == 2


def test_empty_input_is_a_no_op(monkeypatch):
    _fake_events(monkeypatch, ["401873271"])
    assert _nfl_games_on_requested_date([], "2026-08-06") == []


@pytest.mark.parametrize("label", ["2026 Preseason", "2026 Regular Season", "latest"])
def test_a_NON_DATE_LABEL_must_not_wipe_the_board(monkeypatch, label):
    """MEASURED 2026-08-08 on the shipped code, and it deleted every card.

    `_build_sport_overview` sets `context_label = f"{season} Preseason"` and
    passes it down as `requested_date`. ESPN answers a garbage date with an
    EMPTY scoreboard rather than an error, so the confirmed-empty-slate branch
    returned no games at all for the home overview and the intelligence layer.

    A label that never denoted a date is the same "we cannot answer" case as no
    date at all -- so it must not filter, exactly like the empty-string guard.
    """
    _fake_events(monkeypatch, [])
    assert len(_nfl_games_on_requested_date(_games(), label)) == 2


# ---------------------------------------------------------------------------
# preseason_target_week: keyed on `gameday`, not the never-refreshed `status`.
# ---------------------------------------------------------------------------


def _schedule(tmp_path, rows, monkeypatch):
    import csv as _csv

    from syndicate.features.nfl import sources

    path = tmp_path / "schedule_preseason_2026.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["week", "gameday", "status"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    monkeypatch.setattr(sources, "real_preseason_schedule_path", lambda season: path)
    return sources


def test_a_stale_status_column_no_longer_pins_the_week(tmp_path, monkeypatch):
    """THE BUG. Nothing rewrites `status` -- fetch_nfl_preseason_schedule.py is
    a manual CLI in no pipeline -- so every row read "Scheduled" and
    min(unplayed) returned 1 forever, even after week 1 had been played."""
    s = _schedule(tmp_path, [
        {"week": "1", "gameday": "2026-08-07", "status": "Scheduled"},   # already past
        {"week": "2", "gameday": "2026-08-13", "status": "Scheduled"},
    ], monkeypatch)
    monkeypatch.setattr(s, "central_today_iso", lambda: "2026-08-08", raising=False)
    import syndicate.features.shared.timezone as tz
    monkeypatch.setattr(tz, "central_today_iso", lambda: "2026-08-08")
    assert s.preseason_target_week(2026) == 2


def test_a_week_playing_TODAY_is_the_target(tmp_path, monkeypatch):
    """>= today, not > today: a week whose games are today is the week we are
    preparing for, and the old status rule agreed."""
    s = _schedule(tmp_path, [{"week": "2", "gameday": "2026-08-13", "status": "Scheduled"}], monkeypatch)
    import syndicate.features.shared.timezone as tz
    monkeypatch.setattr(tz, "central_today_iso", lambda: "2026-08-13")
    assert s.preseason_target_week(2026) == 2


def test_all_games_past_means_preseason_is_over(tmp_path, monkeypatch):
    s = _schedule(tmp_path, [{"week": "4", "gameday": "2026-08-29", "status": "Scheduled"}], monkeypatch)
    import syndicate.features.shared.timezone as tz
    monkeypatch.setattr(tz, "central_today_iso", lambda: "2026-09-10")
    assert s.preseason_target_week(2026) is None


def test_a_file_with_no_gamedays_falls_back_to_the_status_rule(tmp_path, monkeypatch):
    """Separates "preseason is over" from "this file cannot answer by date".
    Without it, a dateless schedule would silently report preseason finished."""
    s = _schedule(tmp_path, [
        {"week": "3", "gameday": "", "status": "Scheduled"},
        {"week": "4", "gameday": "", "status": "Scheduled"},
    ], monkeypatch)
    import syndicate.features.shared.timezone as tz
    monkeypatch.setattr(tz, "central_today_iso", lambda: "2026-08-08")
    assert s.preseason_target_week(2026) == 3


def test_a_missing_file_is_still_None(tmp_path, monkeypatch):
    from syndicate.features.nfl import sources

    monkeypatch.setattr(sources, "real_preseason_schedule_path", lambda season: tmp_path / "nope.csv")
    assert sources.preseason_target_week(2026) is None


# ---------------------------------------------------------------------------
# preseason_week_for_date: the week must follow the REQUESTED date, not the
# global "week we are preparing for".
#
# MEASURED on production 2026-08-08, after the date filter above had shipped:
# chips were right on 15 of 20 dates in 08-05..08-24, and the 5 misses were an
# exact pattern -- every date OUTSIDE the resolved target week returned 0.
# target_week was 2, so 08-06 (week 1, ESPN 1 game) and 08-20..08-23 (week 3,
# ESPN 2/3/10/1 games) all served nothing. Strictly better than the original
# stale-game-everywhere defect, still date-blind.
# ---------------------------------------------------------------------------


def _dated_schedule(tmp_path, rows, monkeypatch):
    import csv as _csv

    from syndicate.features.nfl import sources

    path = tmp_path / "schedule_preseason_2026.csv"
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = _csv.DictWriter(fh, fieldnames=["game_id", "week", "gameday", "status"])
        w.writeheader()
        for r in rows:
            w.writerow(r)
    monkeypatch.setattr(sources, "real_preseason_schedule_path", lambda season: path)
    return sources


_REAL_ROWS = [
    {"game_id": "401873271", "week": "1", "gameday": "2026-08-07", "status": "Scheduled"},
    {"game_id": "401873272", "week": "2", "gameday": "2026-08-13", "status": "Scheduled"},
    {"game_id": "401873285", "week": "3", "gameday": "2026-08-20", "status": "Scheduled"},
]


def test_a_week_3_date_resolves_to_week_3(tmp_path, monkeypatch):
    """THE MEASURED MISS. 08-20 served 0 chips because the card set was week 2."""
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)
    _fake_events(monkeypatch, ["401873285"])
    assert s.preseason_week_for_date(2026, "2026-08-20") == 3


def test_a_past_week_1_date_still_resolves_to_week_1(tmp_path, monkeypatch):
    """The other measured miss: 08-06 is behind the target week, not ahead."""
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)
    _fake_events(monkeypatch, ["401873271"])
    assert s.preseason_week_for_date(2026, "2026-08-06") == 1


def test_the_UTC_vs_LOCAL_day_offset_cannot_bite(tmp_path, monkeypatch):
    """CAR @ ARI is `2026-08-07` in the CSV and `08-06` to ESPN -- a 00:00Z
    kickoff. Resolving by game_id rather than by comparing dates is what makes
    that difference structurally unable to produce an off-by-one day."""
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)
    _fake_events(monkeypatch, ["401873271"])
    assert s.preseason_week_for_date(2026, "2026-08-06") == 1


@pytest.mark.parametrize("date_value", ["", None, "   "])
def test_no_date_cannot_resolve_a_week(tmp_path, monkeypatch, date_value):
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)
    _fake_events(monkeypatch, ["401873271"])
    assert s.preseason_week_for_date(2026, date_value) is None


def test_a_date_with_no_games_falls_back(tmp_path, monkeypatch):
    """None, not a guess -- the caller then uses preseason_target_week() and the
    date filter drops the cards, which is how an empty slate stays empty."""
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)
    _fake_events(monkeypatch, [])
    assert s.preseason_week_for_date(2026, "2026-08-08") is None


def test_espn_unreachable_falls_back(tmp_path, monkeypatch):
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)

    def _boom(*_a, **_k):
        raise RuntimeError("espn unreachable")

    monkeypatch.setattr("syndicate.features.shared.schedule_adapter.fetch_schedule_for_date", _boom)
    assert s.preseason_week_for_date(2026, "2026-08-20") is None


def test_ids_absent_from_the_schedule_fall_back(tmp_path, monkeypatch):
    s = _dated_schedule(tmp_path, _REAL_ROWS, monkeypatch)
    _fake_events(monkeypatch, ["999999999"])
    assert s.preseason_week_for_date(2026, "2026-08-20") is None


def test_a_missing_schedule_file_cannot_resolve_a_week(tmp_path, monkeypatch):
    from syndicate.features.nfl import sources

    monkeypatch.setattr(sources, "real_preseason_schedule_path", lambda season: tmp_path / "nope.csv")
    _fake_events(monkeypatch, ["401873271"])
    assert sources.preseason_week_for_date(2026, "2026-08-06") is None


def test_a_mixed_date_takes_the_majority_week(tmp_path, monkeypatch):
    """A rescheduled game must not let one stray row pick the whole card set."""
    s = _dated_schedule(tmp_path, _REAL_ROWS + [
        {"game_id": "401873286", "week": "3", "gameday": "2026-08-20", "status": "Scheduled"},
    ], monkeypatch)
    _fake_events(monkeypatch, ["401873285", "401873286", "401873272"])
    assert s.preseason_week_for_date(2026, "2026-08-20") == 3
