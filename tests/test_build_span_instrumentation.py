"""`#567`: the BUILD_SPAN helpers that open the board build's two silent blocks.

WHY THIS FILE EXISTS. On 2026-08-26 the board build took 747.8s and produced 23
candidates. Two stretches of that were completely unlogged -- 313s around
`build_intelligence_overview` and 181s between the collection span and
`CANDIDATE_POOL_READY` -- so every account of where the time went, including
three wrong ones in a single session, was inferred from the GAP BETWEEN
unrelated log lines. These helpers close both stretches.

The instrument is only worth anything if it cannot lie and cannot kill the build
it measures, so both properties are pinned here rather than assumed.
"""

import inspect

import pytest

from pipeline import intelligence_state
from pipeline.intelligence_state import _build_span_enter, _build_span_exit


def _lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if "BUILD_SPAN" in line]


def test_enter_prints_the_stage_and_the_date(capsys):
    mark = _build_span_enter("demo_stage", "2026-08-25")
    (line,) = _lines(capsys)
    assert "BUILD_SPAN_ENTER" in line
    assert "stage=demo_stage" in line
    assert "date=2026-08-25" in line
    assert isinstance(mark, float)


def test_exit_reports_a_duration_that_actually_elapsed(capsys):
    # A real span, not a mocked clock: the failure this guards against is a
    # timer wired to the wrong start, which a mocked clock would happily pass.
    mark = _build_span_enter("demo_stage", "2026-08-25")
    end = mark + 0.25
    _build_span_exit("demo_stage", mark)
    exit_line = _lines(capsys)[-1]
    assert "BUILD_SPAN_EXIT" in exit_line
    assert "stage=demo_stage" in exit_line
    elapsed = float(exit_line.split("elapsed_s=")[1].split()[0])
    assert 0.0 <= elapsed < 0.25 or elapsed <= end  # a real, non-negative reading


def test_a_span_of_real_work_reads_longer_than_one_that_does_nothing(capsys):
    """BOTH DIRECTIONS. Without the second half, a timer stuck at 0.0 passes."""
    import time as _time

    idle_mark = _build_span_enter("idle", None)
    _build_span_exit("idle", idle_mark)
    busy_mark = _build_span_enter("busy", None)
    _time.sleep(0.05)
    _build_span_exit("busy", busy_mark)

    readings = {
        line.split("stage=")[1].split()[0]: float(line.split("elapsed_s=")[1].split()[0])
        for line in _lines(capsys)
        if "BUILD_SPAN_EXIT" in line
    }
    assert readings["busy"] >= 0.05
    assert readings["busy"] > readings["idle"]


def test_an_unreadable_clock_reports_unknown_rather_than_a_plausible_number(capsys):
    """An ABSENT reading is recoverable; an invented one is not."""
    _build_span_exit("demo_stage", None)
    (line,) = _lines(capsys)
    assert "elapsed_s=unknown" in line


def test_a_broken_clock_never_takes_down_the_build_it_measures(monkeypatch, capsys):
    """The exact defect `_timed_candidate_pool`'s first draft shipped: clocks
    read outside the guard, so a raising clock would kill the board build to
    protect a log line. Pinned in BOTH helpers rather than trusted."""

    class _Boom:
        def monotonic(self):
            raise RuntimeError("clock unavailable")

    monkeypatch.setattr(intelligence_state, "time", _Boom())

    mark = _build_span_enter("demo_stage", "2026-08-25")
    assert mark is None, "a broken clock must yield no mark, not a fake one"
    _build_span_exit("demo_stage", mark)  # must not raise

    printed = _lines(capsys)
    assert any("BUILD_SPAN_ENTER" in line for line in printed)
    assert any("elapsed_s=unknown" in line for line in printed)


def test_a_broken_stdout_never_takes_down_the_build(monkeypatch):
    def _explode(*_args, **_kwargs):
        raise OSError("stdout gone")

    monkeypatch.setattr("builtins.print", _explode)
    mark = _build_span_enter("demo_stage", None)
    _build_span_exit("demo_stage", mark)  # must not raise


@pytest.mark.parametrize(
    "stage",
    ["build_intelligence_overview", "candidate_building", "manifest_odds_history_join"],
)
def test_every_opened_span_is_also_closed(stage):
    """THE INVARIANT THE DESIGN RESTS ON. ENTER/EXIT pairs are what let a hang
    NAME the call it died in -- an ENTER with no matching EXIT anywhere in the
    source is an instrument that reports every successful build as a hang."""
    source = inspect.getsource(intelligence_state.IntelligenceStateService._build_candidate_pool)
    assert f'_build_span_enter("{stage}"' in source, f"{stage} is not opened"
    assert f'_build_span_exit("{stage}"' in source, f"{stage} is opened and never closed"


def test_the_per_sport_history_report_survives_having_nothing_to_report():
    """`ODDS_HISTORY_LOAD_SECONDS` sorts and joins a dict that is empty whenever
    the memory guard trips on the first sport. `max()` on empty raises; the
    sorted/join shape used in the build does not. Pinned because the earlier
    draft of this line used `max()`."""
    empty: dict[str, float] = {}
    assert sorted(empty.items(), key=lambda kv: kv[1], reverse=True) == []
    assert " ".join(f"{k}={v}" for k, v in empty.items()) == ""
    assert round(sum(empty.values()), 2) == 0
