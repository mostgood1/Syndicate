"""Capture is a data layer, so its tests are about LOSS and DUPLICATION.

This exists because an empirical live prop model needs per-quarter player
production and ESPN cannot supply it historically -- `participants` is absent on
every play, and `boxscore.players` is final-only. `live_player_box` fetches
exactly the right rows during a live game and caches them IN MEMORY ONLY, so
every slate generates the dataset and discards it. There is no backfill.

That makes the failure modes asymmetric, and the tests follow the asymmetry:

  * A MISSED snapshot is permanent. So capture defaults ON, and a failure is
    swallowed and printed rather than raised -- losing an observation must never
    cost the tick its board.
  * A DUPLICATED snapshot silently reweights the fit. A game sits at "end of Q2"
    for the whole of halftime while the loop comes round every tick, so
    idempotence per (event, period) is not an optimisation.
  * An UNATTRIBUTABLE row pollutes a per-player fit permanently, so a row with
    no player name is dropped rather than given a synthetic key.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl import live_prop_capture as cap  # noqa: E402


def _rows():
    return [
        {"player": "P.Mahomes", "team": "KC", "pass_yards": 180.0, "pass_td": 1.0,
         "rush_yards": 12.0, "total_yards": 192.0, "td_scored": 0.0},
        {"player": "T.Kelce", "team": "KC", "rec_yards": 64.0, "receptions": 5.0,
         "rec_td": 1.0, "total_yards": 64.0, "td_scored": 1.0},
    ]


# --------------------------------------------------------------------------
# duplication -- the one that silently corrupts a fit
# --------------------------------------------------------------------------

def test_a_boundary_is_captured_ONCE_however_many_ticks_see_it(tmp_path):
    """Halftime lasts many ticks. Without idempotence one game would be
    weighted dozens of times in the fit, and nothing would look wrong."""
    for _ in range(5):
        cap.record_quarter_snapshot(tmp_path, event_id="E1", period=2,
                                    date_str="2026-09-27", player_rows=_rows())
    path = cap.capture_path(tmp_path, "2026-09-27")
    lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(lines) == 2, f"captured {len(lines)} rows for one boundary, expected 2"


def test_DIFFERENT_periods_and_events_are_separate_snapshots(tmp_path):
    cap.record_quarter_snapshot(tmp_path, event_id="E1", period=1,
                                date_str="2026-09-27", player_rows=_rows())
    cap.record_quarter_snapshot(tmp_path, event_id="E1", period=2,
                                date_str="2026-09-27", player_rows=_rows())
    cap.record_quarter_snapshot(tmp_path, event_id="E2", period=1,
                                date_str="2026-09-27", player_rows=_rows())
    path = cap.capture_path(tmp_path, "2026-09-27")
    recs = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(recs) == 6
    assert {(r["event_id"], r["period"]) for r in recs} == {("E1", 1), ("E1", 2), ("E2", 1)}


# --------------------------------------------------------------------------
# loss -- a capture must never cost the tick its board
# --------------------------------------------------------------------------

def test_a_FAILING_write_is_swallowed_and_named_not_raised(tmp_path, capfd):
    """Losing an observation is a lost row. Raising would be a lost board."""
    written = cap.record_quarter_snapshot(
        tmp_path / "nope" / "\0bad", event_id="E1", period=2,
        date_str="2026-09-27", player_rows=_rows())
    assert written == 0
    assert "CAPTURE_FAILED" in capfd.readouterr().out


def test_capture_defaults_ON_because_a_MISSED_slate_is_permanent(monkeypatch):
    """absent != off. There is no backfill for a slate nobody captured."""
    monkeypatch.delenv("SYNDICATE_NFL_PROP_CAPTURE", raising=False)
    assert cap.capture_enabled() is True


@pytest.mark.parametrize("raw", ["off", "0", "false", "NO"])
def test_it_can_be_switched_off_without_a_deploy(monkeypatch, tmp_path, raw):
    monkeypatch.setenv("SYNDICATE_NFL_PROP_CAPTURE", raw)
    assert cap.capture_enabled() is False
    assert cap.record_quarter_snapshot(tmp_path, event_id="E1", period=2,
                                       date_str="2026-09-27", player_rows=_rows()) == 0
    assert not cap.capture_path(tmp_path, "2026-09-27").exists()


# --------------------------------------------------------------------------
# what gets captured
# --------------------------------------------------------------------------

def test_a_row_with_NO_PLAYER_is_dropped_not_given_a_synthetic_key(tmp_path):
    """An unattributable row pollutes a per-player fit permanently."""
    rows = _rows() + [{"team": "KC", "rec_yards": 20.0}]
    n = cap.record_quarter_snapshot(tmp_path, event_id="E1", period=2,
                                    date_str="2026-09-27", player_rows=rows)
    assert n == 2


def test_only_the_QUARTER_BOUNDARIES_a_model_is_asked_about_are_captured(tmp_path):
    """Q4's boundary is the final score, which the box score already gives us;
    capturing it would duplicate a source that is not lossy."""
    assert cap.snapshot_rows(event_id="E1", period=4, date_str="d",
                             player_rows=_rows()) == []
    assert cap.snapshot_rows(event_id="E1", period=0, date_str="d",
                             player_rows=_rows()) == []
    assert len(cap.snapshot_rows(event_id="E1", period=3, date_str="d",
                                 player_rows=_rows())) == 2


def test_the_snapshot_carries_the_SCOREBOARD_not_just_the_stats(tmp_path):
    """Game script is the whole reason a uniform rescale is wrong, so the fit
    must be able to condition on the score the production happened under."""
    cap.record_quarter_snapshot(tmp_path, event_id="E1", period=2,
                                date_str="2026-09-27", player_rows=_rows(),
                                home_score=21, away_score=3)
    rec = json.loads(cap.capture_path(tmp_path, "2026-09-27")
                     .read_text(encoding="utf-8").splitlines()[0])
    assert rec["home_score_at"] == 21
    assert rec["away_score_at"] == 3
    assert rec["period"] == 2
    assert rec["schema_version"] == cap.CAPTURE_SCHEMA_VERSION


def test_it_writes_JSONL_so_a_restart_mid_slate_loses_at_most_one_line(tmp_path):
    """refresh-worker terminated 8 times in 16.8 h on 2026-09-27. A partially
    written JSON array is unreadable; a partial JSONL loses its last line."""
    cap.record_quarter_snapshot(tmp_path, event_id="E1", period=2,
                                date_str="2026-09-27", player_rows=_rows())
    path = cap.capture_path(tmp_path, "2026-09-27")
    assert path.suffix == ".jsonl"
    text = path.read_text(encoding="utf-8")
    assert text.endswith("\n")
    for line in text.splitlines():
        json.loads(line)   # every line independently parseable


def test_the_WORKER_tick_actually_calls_the_capture():
    """REACHABILITY. A collector nothing calls collects nothing.

    Asserted on the compiled code object, not the source text: the comment
    above the call names the function, so a grep would pass with the call
    deleted. Same mistake caught in an NCAAF test on 2026-09-27.

    The hook is on `build_live_lens_snapshot` (refresh-worker) and NOT on
    `nfl_player_box_index`, because that is called only from the web blueprint
    in a request path -- it would write to a disk the worker cannot read, and
    only when somebody loaded the cards page.
    """
    from syndicate.features.nfl import live_resim as lr

    names = lr.build_live_lens_snapshot.__code__.co_names
    assert "_maybe_capture_prop_snapshot" in names, (
        "the live tick no longer captures; tonight's player boxes would be discarded"
    )
    inner = lr._maybe_capture_prop_snapshot.__code__.co_names
    assert "record_quarter_snapshot" in inner
    assert "fetch_player_stat_rows" in inner


def test_captures_are_written_to_the_WRITE_root_not_the_probing_READ_root():
    """`#389`/`#441`, and this shipped wrong once already.

    `default_nfl_source_root()` decides a root by PROBING for
    `upcoming_recs_*.csv` -- an unrelated family the repo mirror ships and the
    mounted disk does not -- so it resolves to `/opt/render/project/src/data`,
    the CHECKOUT, which every deploy replaces. Projections were written there
    for days while the guard read the mounted disk.

    A capture is the worst thing to put in an ephemeral location: the data
    cannot be regenerated, so a wipe is not a stale artifact, it is a lost
    slate. Asserted on the code object because a comment naming the right
    function is exactly what was there while the wrong one was being called.
    """
    from syndicate.features.nfl import live_prop_capture as c

    names = c.default_capture_dir.__code__.co_names
    assert "nfl_artifact_output_root" in names, "capture is using a probing READ root"
    assert "default_nfl_source_root" not in names


def test_the_worker_hook_uses_the_capture_modules_own_root_helper():
    from syndicate.features.nfl import live_resim as lr

    names = lr._maybe_capture_prop_snapshot.__code__.co_names
    assert "default_capture_dir" in names


def test_capture_fires_at_HALFTIME_when_the_game_is_not_simulatable(monkeypatch, tmp_path):
    """The flaw that cost a live slate, pinned as behaviour.

    The first version gated on `isinstance(resolved, NflLiveGameState)` -- on
    the game being SIMULATABLE. `live_state_from_row` refuses a game that is
    not "in progress", and a game AT a quarter boundary is in a break.
    Measured 22:07Z: LV@NO sat at `Q2 0:00` while the tick reported
    `live_resimmed 3` against 4 live games. The capture returned silently at
    exactly the moments it exists for.

    So the hook must read the RAW row and must NOT care what the sim made of
    it: a game at halftime has already produced the Q2 production.
    """
    from syndicate.features.nfl import live_resim as lr

    calls = {}
    monkeypatch.setattr(lr, "PROP_CAPTURE_CLOCK_SECONDS", 120)
    import syndicate.features.nfl.live_player_box as box
    monkeypatch.setattr(box, "fetch_player_stat_rows",
                        lambda e: [{"player": "T.Kelce", "rec_yards": 64.0}])
    import syndicate.features.nfl.live_prop_capture as cap
    monkeypatch.setattr(cap, "record_quarter_snapshot",
                        lambda root, **kw: calls.update(kw) or 1)

    # A halftime row: period 2, clock 0, and a REFUSAL from the sim side.
    row = {"state": "pre", "period": 2, "clock_seconds": 0,
           "home_score": 13, "away_score": 13, "event_id": "401772999"}
    refusal = lr.NflResimRefusal("game_not_in_progress", "halftime")
    lr._maybe_capture_prop_snapshot(row, refusal, date_str="2026-09-27")

    assert calls.get("event_id") == "401772999", (
        "halftime was skipped -- the capture is still gated on simulatability"
    )
    assert calls.get("period") == 2
    assert calls.get("clock_seconds") == 0


def test_a_FINAL_game_is_not_captured_as_a_boundary(monkeypatch):
    """Q4's end is the final box, which is not lossy and is fetched elsewhere."""
    from syndicate.features.nfl import live_resim as lr

    calls = {}
    import syndicate.features.nfl.live_prop_capture as cap
    monkeypatch.setattr(cap, "record_quarter_snapshot", lambda root, **kw: calls.update(kw))
    lr._maybe_capture_prop_snapshot(
        {"state": "final", "period": 3, "clock_seconds": 0, "event_id": "E9"},
        None, date_str="2026-09-27")
    assert not calls
