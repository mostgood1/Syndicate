"""`#378` -- a capture that swept and wrote nothing looked exactly like one that worked.

MEASURED 2026-08-12. WNBA's board served 3 games and 848 rows priced off quotes
**7.6 hours old**, while every artifact downstream kept rebuilding on schedule --
`book_grid_2026-08-12.json` published at 14:53:46, live-lens ticking `wnba: True`.
The board looked entirely healthy. Only the prices were stale.

The cadence filter was not the cause. WNBA was KEPT on two ticks (those skip
lines read `nfl,soccer` only), and MLB published its sidecar at 11:09:23 and
13:12:01 off the SAME launches, while WNBA's last write stayed 07:18:51.

WHY IT WAS INVISIBLE. `launch_refresh_run` catches every exception into
`meta["error"]`, written to a JSON file on the worker's own disk and never
printed. The per-sport steps inside it log to a stderr file on that same disk --
confirmed unreachable during the la_liga trace, where `STEP_FAIL`/`STEP_END`
returned zero lines for SUCCESSFUL leagues too. refresh-worker serves no HTTP, so
from outside there is no difference between a sport that swept fine and one that
swept and produced nothing.

This is `#352`'s soccer-unit outcome check applied to odds capture, for the same
reason: the launch stamp says a sweep STARTED; only the artifact says it
FINISHED. `#352` is what eventually cracked la_liga after five wrong hypotheses.

MLB's 88-minute age is NOT a bug and must not be "fixed": the pregame sweep
interval is a deliberate 2h fallback (`_PREGAME_SWEEP_INTERVAL_FALLBACK`), and
its measured gaps were 107.5 / 108.6 / 108.2 minutes. I called it broken before
reading the interval; this test exists partly to stop the next person doing that.
"""

from __future__ import annotations

import importlib
import time

import pytest

MODULE = "syndicate.features.shared.live_refresh_loop"


@pytest.fixture
def loop(monkeypatch, tmp_path):
    mod = importlib.import_module(MODULE)
    monkeypatch.setattr(mod, "_meta_dir", lambda: tmp_path, raising=False)
    return mod


def _sidecar(mod, monkeypatch, tmp_path, *, sport: str, mtime: float | None):
    """Point `_state_path` at a temp file with a chosen mtime (None = absent)."""
    import syndicate.features.shared.odds_book_quotes as quotes

    path = tmp_path / f"{sport}.state.json"
    if mtime is not None:
        path.write_text("{}", encoding="utf-8")
        import os

        os.utime(path, (mtime, mtime))
    monkeypatch.setattr(quotes, "_state_path", lambda s, d, _p=path: _p, raising=False)
    return path


def test_a_sweep_that_wrote_nothing_is_reported(loop, monkeypatch, tmp_path, capsys):
    now = time.time()
    # Launched 10 minutes ago; sidecar last written 7.6 HOURS ago -- the WNBA case.
    loop._record_odds_sweep_launch(now - 600, ["wnba"])
    _sidecar(loop, monkeypatch, tmp_path, sport="wnba", mtime=now - 7.6 * 3600)
    loop._report_odds_sweep_outcomes("2026-08-12")
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if "ODDS_SWEEP_OUTCOME" in l)
    assert "sport=wnba" in line
    assert "wrote=False" in line, "a sweep that produced nothing must say so"
    assert "exists=True" in line, "the sidecar EXISTS but is stale -- a different fact from absent"


def test_a_healthy_sweep_reports_wrote_true(loop, monkeypatch, tmp_path, capsys):
    now = time.time()
    loop._record_odds_sweep_launch(now - 600, ["mlb"])
    _sidecar(loop, monkeypatch, tmp_path, sport="mlb", mtime=now - 300)  # written AFTER launch
    loop._report_odds_sweep_outcomes("2026-08-12")
    line = next(l for l in capsys.readouterr().out.splitlines() if "ODDS_SWEEP_OUTCOME" in l)
    assert "sport=mlb" in line and "wrote=True" in line


def test_a_just_launched_sweep_is_not_graded_yet(loop, monkeypatch, tmp_path, capsys):
    # The launch is DETACHED. Grading it immediately would mark every healthy
    # sweep as a failure, which is worse than the blindness being fixed.
    now = time.time()
    loop._record_odds_sweep_launch(now - 5, ["wnba"])
    _sidecar(loop, monkeypatch, tmp_path, sport="wnba", mtime=now - 9999)
    loop._report_odds_sweep_outcomes("2026-08-12")
    assert "ODDS_SWEEP_OUTCOME" not in capsys.readouterr().out


def test_an_absent_sidecar_is_distinguished_from_a_stale_one(loop, monkeypatch, tmp_path, capsys):
    now = time.time()
    loop._record_odds_sweep_launch(now - 600, ["nhl"])
    _sidecar(loop, monkeypatch, tmp_path, sport="nhl", mtime=None)
    loop._report_odds_sweep_outcomes("2026-08-12")
    line = next(l for l in capsys.readouterr().out.splitlines() if "ODDS_SWEEP_OUTCOME" in l)
    assert "exists=False" in line and "wrote=False" in line
    assert "sidecar_age_s=-1" in line, "no file means no age -- never a fabricated 0"


def test_the_reporter_is_actually_called_on_every_tick():
    """A diagnostic nothing invokes is indistinguishable from no diagnostic.

    This session produced several fixes that existed and never ran; the wiring
    gets asserted, not just the function.
    """
    import pathlib

    source = pathlib.Path(MODULE.replace(".", "/") + ".py").read_text(encoding="utf-8")
    assert "def _report_odds_sweep_outcomes" in source
    assert source.count("_report_odds_sweep_outcomes(") >= 2, "defined but never called"
    assert "_record_odds_sweep_launch(tick_started_epoch" in source, "launches are not stamped"


def test_the_reporter_cannot_break_the_tick(loop, monkeypatch, tmp_path, capsys):
    # It runs at the top of every tick. If it can raise, it can stop odds
    # refreshing entirely -- strictly worse than the problem it reports on.
    import syndicate.features.shared.odds_book_quotes as quotes

    def _boom(*_a, **_k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(quotes, "_state_path", _boom, raising=False)
    loop._record_odds_sweep_launch(time.time() - 600, ["wnba"])
    loop._report_odds_sweep_outcomes("2026-08-12")  # must not raise
    assert "unknown=1" in capsys.readouterr().out


def test_a_single_launch_reports_once_not_every_tick(loop, monkeypatch, tmp_path, capsys):
    """`#384` -- the unit of this report is a LAUNCH, not a tick.

    `#378` printed on every tick for every sport whose launch was older than
    120s. Measured 2026-08-12: 15 identical lines for ONE 17:22 wnba launch,
    which reads as 15 attempts -- and I mislabelled them exactly that way in a
    watcher an hour later. An unbounded stream of identical lines makes a log
    unreadable at the moment someone needs it.
    """
    loop._ODDS_SWEEP_REPORTED.clear()
    now = time.time()
    loop._record_odds_sweep_launch(now - 600, ["wnba"])
    _sidecar(loop, monkeypatch, tmp_path, sport="wnba", mtime=now - 7.6 * 3600)

    for _ in range(5):
        loop._report_odds_sweep_outcomes("2026-08-12")
    lines = [l for l in capsys.readouterr().out.splitlines() if "ODDS_SWEEP_OUTCOME" in l]
    assert len(lines) == 1, f"one launch produced {len(lines)} lines"
    assert "wrote=False" in lines[0]


def test_a_late_landing_subprocess_still_gets_reported(loop, monkeypatch, tmp_path, capsys):
    """Reporting once ONLY would be wrong -- the subprocess is detached.

    A launch judged at 120s can still be running and land later, so a single
    early report would publish a false wrote=False and never correct it.
    Reporting on TRANSITION keeps steady state quiet while a recovery prints.
    """
    loop._ODDS_SWEEP_REPORTED.clear()
    now = time.time()
    loop._record_odds_sweep_launch(now - 600, ["wnba"])
    _sidecar(loop, monkeypatch, tmp_path, sport="wnba", mtime=now - 7.6 * 3600)
    loop._report_odds_sweep_outcomes("2026-08-12")
    first = [l for l in capsys.readouterr().out.splitlines() if "ODDS_SWEEP_OUTCOME" in l]
    assert len(first) == 1 and "wrote=False" in first[0]

    # The subprocess lands: sidecar now written after the launch.
    _sidecar(loop, monkeypatch, tmp_path, sport="wnba", mtime=now - 60)
    loop._report_odds_sweep_outcomes("2026-08-12")
    second = [l for l in capsys.readouterr().out.splitlines() if "ODDS_SWEEP_OUTCOME" in l]
    assert len(second) == 1 and "wrote=True" in second[0], "a False->True recovery must print"


def test_a_new_launch_reports_again(loop, monkeypatch, tmp_path, capsys):
    # Each launch is its own event; a stalled sport launching every 2h should
    # report every 2h, which is signal rather than noise.
    loop._ODDS_SWEEP_REPORTED.clear()
    now = time.time()
    _sidecar(loop, monkeypatch, tmp_path, sport="wnba", mtime=now - 7.6 * 3600)
    loop._record_odds_sweep_launch(now - 600, ["wnba"])
    loop._report_odds_sweep_outcomes("2026-08-12")
    capsys.readouterr()
    loop._record_odds_sweep_launch(now - 300, ["wnba"])  # a fresh launch
    loop._report_odds_sweep_outcomes("2026-08-12")
    lines = [l for l in capsys.readouterr().out.splitlines() if "ODDS_SWEEP_OUTCOME" in l]
    assert len(lines) == 1, "a new launch must be reported"
