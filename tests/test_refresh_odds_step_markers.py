"""Allowlisted child-stdout marker lines survive the odds job's stdout blanking.

Lane `odds-step-stdout-markers` (2026-10-08). `build_soccer_artifacts.py` prints
`SOCCER_CONFIRMED_LINEUPS ... sides_confirmed=X/Y` on every run, but `_run_command`
captures the child's stdout and `_compact_step_result` blanks it. Measured 10-08:
0 of those lines in 3 days of `data/reports/migration_runs`, so whether confirmed
lineups ever reach the soccer sim was unmeasurable (findings_2026-10-08_soccer_last_scorer_lineup.md).
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_LINE = "[build_soccer_artifacts] SOCCER_CONFIRMED_LINEUPS league=epl date=2026-10-04 sides_confirmed=4/20 home=2/10 away=2/10"


@pytest.fixture(scope="module")
def module():
    path = Path(__file__).resolve().parents[1] / "scripts" / "refresh_odds_sources.py"
    spec = importlib.util.spec_from_file_location("test_refresh_odds_step_markers_mod", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(module, stdout, capsys):
    step = module.RefreshStep(name="soccer_epl_artifacts", phases=("pregame",), cwd=Path("."),
                              command=("python", "child.py"), env_updates=None, description="t")
    completed = subprocess.CompletedProcess(args=list(step.command), returncode=0, stdout=stdout, stderr="")
    with patch.object(module.subprocess, "run", return_value=completed), \
            patch.object(module, "_log_memory", return_value=None), \
            patch.object(module, "_dump_child_runtime_state", return_value=None), \
            patch.object(module, "_record_step_in_sim_ledger", return_value=None):
        result = module._run_command(step)
    return result, capsys.readouterr().err


def test_the_lineup_line_survives_blanking(module, capsys):
    result, err = _run(module, f"noise\n{_LINE}\nmore noise\n", capsys)
    assert f"STEP_MARKER name=soccer_epl_artifacts {_LINE}" in err
    module._compact_step_result(result)
    assert result["stdout"] == ""  # the blanking itself is unchanged
    view = module._compact_step_result_view(result)
    assert view["stdout_markers"] == [_LINE]


def test_off_is_not_on_without_the_marker_nothing_is_kept(module, capsys):
    """Reachability: an ordinary stdout yields no marker field and no STEP_MARKER line,
    so the field above is the allowlist's doing."""
    result, err = _run(module, "noise\nSOCCER_SOMETHING_ELSE x=1\n", capsys)
    assert "STEP_MARKER" not in err
    module._compact_step_result(result)
    assert "stdout_markers" not in module._compact_step_result_view(result)


def test_the_marker_list_is_bounded(module, capsys):
    long_line = _LINE + " " + "x" * 2000
    result, _ = _run(module, "\n".join([long_line] * 500), capsys)
    markers = result["stdout_markers"]
    assert len(markers) == module._STEP_MARKER_MAX_LINES
    assert all(len(m) <= module._STEP_MARKER_MAX_CHARS for m in markers)
