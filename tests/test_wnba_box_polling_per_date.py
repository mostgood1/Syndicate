"""The two WNBA box-score polls to web skip a DATE the schedule lists no game on.

Lane wnba-boxscore-polling-per-date (2026-11-17). Measured on the fleet's web.log,
10-31..11-17: these two routes were 29,449 of 100,005 web requests (29.4%); on 11-17
1,614 of 2,408 (67.0%), with no WNBA game on any of those dates.

  * live capture  -- `live_lens_loop._run_live_lens_tick_for_sport("wnba", D)` ->
                     `GET /wnba/api/live_player_boxscore?date=D`
  * settlement    -- `intelligence_state._refresh_wnba_boxscores(D)` ->
                     `GET /wnba/api/final_player_boxscore?date=D&count_only=1`

REACHABILITY FIRST (`model_engine_standard.md`): the same code on the same day
must make the request when the schedule has a game and must not when it has none --
`off != on` -- before anything about logs or reasons is worth asserting.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest import mock

import pytest

from syndicate.features.wnba import slate_schedule

REPO_ROOT = Path(__file__).resolve().parents[1]
GAME_DAY = "2026-06-05"
EMPTY_DAY = "2026-11-17"

HEADER = "game_id,date_utc,date_est,home_tricode,away_tricode\n"


def _schedule(root: Path, *dates: str) -> None:
    path = root / "wnba_source" / "data" / "processed" / "schedule_2026.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "".join(f"{i},{d},{d},NYL,IND\n" for i, d in enumerate(dates)), encoding="utf-8")


@pytest.fixture
def data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    slate_schedule._clear_memo_for_tests()
    # Isolate from whatever this machine has published; the override itself is
    # covered in test_wnba_slate_schedule.py.
    monkeypatch.setattr(slate_schedule, "_cards_context_game_count", lambda _d: None)
    yield tmp_path
    slate_schedule._clear_memo_for_tests()


# ---------------------------------------------------------------------------
# Live capture (live-odds-worker's live-lens tick)
# ---------------------------------------------------------------------------

def _tick(date_str: str, fetch: mock.MagicMock) -> dict:
    from syndicate.features.shared import live_lens_loop

    snapshot = {"ok": True, "date": date_str, "rank_cards": [], "games": []}
    with mock.patch.dict(live_lens_loop._LIVE_LENS_BUILDERS, {"wnba": lambda _d: snapshot}), \
         mock.patch.dict(live_lens_loop._LIVE_LENS_VALIDATORS, {"wnba": lambda _s: True}), \
         mock.patch.dict(live_lens_loop._LIVE_LENS_SNAPSHOT_PATHS,
                         {"wnba": lambda: Path("/tmp/does-not-matter.json")}), \
         mock.patch.object(live_lens_loop, "write_json_file"), \
         mock.patch.object(live_lens_loop, "log_and_persist_process_memory"), \
         mock.patch.object(live_lens_loop, "_wnba_live_lens_headroom_snapshot", return_value=None), \
         mock.patch("scripts.poll_basketball_momentum.poll", return_value={"count": 0, "with_series": 0}), \
         mock.patch("scripts.capture_wnba_live_player_box.fetch", fetch):
        return live_lens_loop._run_live_lens_tick_for_sport("wnba", date_str)


def _empty_box(*_a, **_k):
    return {"games": []}


def test_live_capture_reachability_off_is_not_on(data_root):
    """Same code, same date, one schedule row apart: a request, then none."""
    fetch = mock.MagicMock(side_effect=_empty_box)
    _schedule(data_root, EMPTY_DAY)
    _tick(EMPTY_DAY, fetch)
    with_game = fetch.call_count

    slate_schedule._clear_memo_for_tests()
    _schedule(data_root, GAME_DAY)  # EMPTY_DAY no longer listed
    _tick(EMPTY_DAY, fetch)
    assert with_game == 1, "a date with a game must still be polled"
    assert fetch.call_count == 1, "a date with no game must not be polled"


def test_live_capture_skips_a_no_game_date_and_says_so(data_root, capsys):
    fetch = mock.MagicMock(side_effect=_empty_box)
    _schedule(data_root, GAME_DAY)
    meta = _tick(EMPTY_DAY, fetch)
    fetch.assert_not_called()
    out = capsys.readouterr().out
    assert f"WNBA_LIVE_BOX_SKIPPED date={EMPTY_DAY} reason=schedule_has_no_games games=0" in out
    assert "WNBA_LIVE_BOX_EMPTY" not in out
    assert meta.get("ok") is not False, "skipping the capture must not fail the tick"


def test_live_capture_polls_a_game_date(data_root, capsys):
    fetch = mock.MagicMock(side_effect=_empty_box)
    _schedule(data_root, GAME_DAY)
    _tick(GAME_DAY, fetch)
    fetch.assert_called_once()
    assert fetch.call_args.args[1] == GAME_DAY
    assert "WNBA_LIVE_BOX_SKIPPED" not in capsys.readouterr().out


def test_live_capture_polls_when_the_schedule_is_unknown(data_root, capsys):
    """No schedule file at all: poll as before, and NAME the reason."""
    fetch = mock.MagicMock(side_effect=_empty_box)
    _tick(EMPTY_DAY, fetch)
    fetch.assert_called_once()
    assert f"WNBA_LIVE_BOX_SLATE_UNKNOWN date={EMPTY_DAY} reason=schedule_absent" in capsys.readouterr().out


def test_live_capture_polls_when_the_verdict_itself_fails(data_root, capsys, monkeypatch):
    fetch = mock.MagicMock(side_effect=_empty_box)
    monkeypatch.setattr(slate_schedule, "wnba_slate_verdict", mock.MagicMock(side_effect=RuntimeError("boom")))
    _tick(EMPTY_DAY, fetch)
    fetch.assert_called_once()
    assert "WNBA_LIVE_BOX_SLATE_UNKNOWN" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Settlement pass (refresh-worker's intelligence-state build)
# ---------------------------------------------------------------------------

@pytest.fixture
def box(monkeypatch):
    import scripts.build_wnba_boxscores as build

    calls: list[tuple[str, bool]] = []

    def _fetch(base, date_str, count_only=False):
        calls.append((date_str, count_only))
        return {"ok": True, "games": 0, "rows": []}

    monkeypatch.setattr(build, "fetch_via_web", _fetch)
    monkeypatch.setattr(build, "build_date", mock.MagicMock())
    return calls


def test_settlement_reachability_off_is_not_on(data_root, box):
    import pipeline.intelligence_state as istate

    _schedule(data_root, GAME_DAY)
    istate._refresh_wnba_boxscores(GAME_DAY)
    istate._refresh_wnba_boxscores(EMPTY_DAY)
    assert box == [(GAME_DAY, True)], "only the date with a game may reach web"


def test_settlement_skips_a_no_game_date_and_says_so(data_root, box, capsys):
    import pipeline.intelligence_state as istate

    _schedule(data_root, GAME_DAY)
    istate._refresh_wnba_boxscores(EMPTY_DAY)
    assert box == []
    assert (f"WNBA_BOXSCORES_COUNT_SKIPPED date={EMPTY_DAY} reason=schedule_has_no_games"
            in capsys.readouterr().out)


def test_settlement_asks_web_when_the_schedule_is_unknown(data_root, box, capsys):
    import pipeline.intelligence_state as istate

    istate._refresh_wnba_boxscores(EMPTY_DAY)
    assert box == [(EMPTY_DAY, True)]
    assert f"WNBA_BOXSCORES_SLATE_UNKNOWN date={EMPTY_DAY} reason=schedule_absent" in capsys.readouterr().out


def test_ungraded_wnba_orders_overrule_an_empty_schedule(data_root, box, capsys):
    """The ledger holding an ungraded WNBA order on the date is evidence the slate
    HAD games. Settlement needs that box; the schedule does not get the last word."""
    import pipeline.intelligence_state as istate

    _schedule(data_root, GAME_DAY)
    istate._refresh_wnba_boxscores(EMPTY_DAY, holds_ungraded_wnba=True)
    assert box == [(EMPTY_DAY, True)]
    assert f"WNBA_BOXSCORES_SCHEDULE_DISAGREES date={EMPTY_DAY}" in capsys.readouterr().out


def test_every_settlement_call_site_passes_the_ledger_evidence():
    """AST, not a text index: the default `holds_ungraded_wnba=False` lets the
    schedule skip, so a call site that forgot the keyword would silently drop the
    ledger's evidence for straggler dates."""
    tree = ast.parse((REPO_ROOT / "pipeline" / "intelligence_state.py").read_text(encoding="utf-8"))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_refresh_wnba_boxscores"
    ]
    assert calls, "the settlement pass no longer calls _refresh_wnba_boxscores"
    for call in calls:
        assert any(kw.arg == "holds_ungraded_wnba" for kw in call.keywords), ast.unparse(call)


# ---------------------------------------------------------------------------
# The suite itself must never reach the fleet's web for these
# ---------------------------------------------------------------------------

def test_the_suite_cannot_reach_the_fleet_through_either_box_client():
    """Both clients fall back to http://127.0.0.1:10000 -- the live fleet -- when
    unset. `conftest.py` pins them to a refusing port; this fails if that goes."""
    from scripts.build_wnba_boxscores import web_base_url
    from syndicate.features.shared.live_lens_loop import _wnba_live_box_base_url

    assert os.environ.get("SYNDICATE_WNBA_LIVE_BOX_BASE_URL") == "http://127.0.0.1:9"
    for url in (web_base_url(), _wnba_live_box_base_url()):
        assert ":10000" not in url, url
