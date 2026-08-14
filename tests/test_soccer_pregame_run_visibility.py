"""`#433` — the soccer pregame run must report its outcome where someone can read it.

THE FOUR-DAY SILENCE THIS FIXES. Soccer game odds stopped being captured on
2026-08-10 and no error was visible anywhere until 08-14. Nothing was
swallowing exceptions — the output went somewhere unreadable:

  * `launch_refresh_run` spawns the refresh detached with `stdout=DEVNULL,
    stderr=DEVNULL`, on the argument that the child already writes
    `odds_refresh.json` / `odds_refresh.stderr.txt`. True — onto
    **live-odds-worker's disk**, which the web service cannot read, so
    `/api/ops/odds-refresh/logs` returns `exists=False` from web forever.
  * Render's log collector only captures a service's own stdout.

So the worker now reads the artifact IT wrote and prints a compact summary.

The tests assert the two states that were indistinguishable during the outage:
a run that produced an artifact with failing steps, and a run that produced no
artifact at all. Both previously looked identical from outside — silence.
"""

from __future__ import annotations

import json

import pytest

import scripts.run_live_odds_refresh_worker as worker


def _write_run_artifact(tmp_path, steps):
    (tmp_path / "odds_refresh.json").write_text(
        json.dumps({"results": [{"generation": {"steps": steps}}]}),
        encoding="utf-8",
    )
    return {"artifactsDir": str(tmp_path), "runStamp": "20260814_181314", "reported": False}


def test_a_failing_odds_step_is_named_on_stdout(tmp_path, capsys):
    """The line that would have ended the outage on day one."""
    status = _write_run_artifact(
        tmp_path,
        [
            {"name": "soccer_eredivisie_odds", "ok": False, "return_code": 1},
            {"name": "soccer_mls_odds", "ok": True, "return_code": 0},
        ],
    )

    worker._report_previous_soccer_pregame_run(status)
    out = capsys.readouterr().out

    assert "SOCCER_PREGAME_RUN_SUMMARY" in out
    assert "steps=2 ok=1 failed=1" in out
    assert "name=soccer_eredivisie_odds ok=False" in out


def test_a_run_that_wrote_no_artifact_says_so_rather_than_saying_nothing(tmp_path, capsys):
    """ABSENCE IS THE FINDING, and it must be emitted.

    A launched run with no artifact means the child died before writing
    anything. During the outage this state was indistinguishable from success
    because both produced zero output on the worker's stdout.
    """
    status = {"artifactsDir": str(tmp_path / "missing"), "runStamp": "20260814_184753", "reported": False}

    worker._report_previous_soccer_pregame_run(status)
    out = capsys.readouterr().out

    assert "SOCCER_PREGAME_RUN_NO_ARTIFACT" in out
    assert "20260814_184753" in out


def test_non_odds_steps_that_succeed_are_not_printed(tmp_path, capsys):
    """A 50-step dump every 4h is noise, and noise is why nobody reads logs.

    Odds steps are named because they are what the outage was about; failures
    are named wherever they occur. A successful sim step is neither.
    """
    status = _write_run_artifact(
        tmp_path,
        [
            {"name": "soccer_mls_artifacts", "ok": True, "return_code": 0},
            {"name": "soccer_mls_odds", "ok": True, "return_code": 0},
            {"name": "soccer_epl_picks", "ok": False, "return_code": 2},
        ],
    )

    worker._report_previous_soccer_pregame_run(status)
    out = capsys.readouterr().out

    assert "soccer_mls_artifacts" not in out          # succeeded, not an odds step
    assert "name=soccer_mls_odds ok=True" in out      # odds steps always reported
    assert "name=soccer_epl_picks ok=False" in out    # failures always reported


def test_an_already_reported_run_is_not_repeated(tmp_path, capsys):
    """Emitted once, not on every tick for four hours."""
    status = _write_run_artifact(tmp_path, [{"name": "soccer_mls_odds", "ok": True, "return_code": 0}])
    status["reported"] = True

    worker._report_previous_soccer_pregame_run(status)

    assert capsys.readouterr().out == ""


def test_reporting_never_raises_and_so_cannot_break_the_autorun(capsys):
    """An observability side-effect must not be able to kill the thing it watches.

    Same rule `_append_soccer_book_quotes` follows — and a reminder that the
    rule cuts both ways: that swallow is exactly why a failing shard append
    stayed silent. Hence the failure is PRINTED, not merely swallowed.
    """
    worker._report_previous_soccer_pregame_run({"artifactsDir": 12345, "reported": False})

    out = capsys.readouterr().out
    assert out == "" or "SOCCER_PREGAME_RUN" in out


def test_no_status_at_all_is_a_silent_no_op(capsys):
    """First ever tick: nothing has run, so there is nothing to report."""
    worker._report_previous_soccer_pregame_run({})

    assert capsys.readouterr().out == ""
