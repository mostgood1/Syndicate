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
            patch.object(module, "_record_step_in_sim_ledger", return_value=None), \
            patch.object(module, "_step_rss_cap_mb", return_value=None):
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


def test_an_api_key_in_a_failed_steps_stderr_is_masked(module):
    """Lane `soccer-live-lane-priority` (2026-10-09): a 502 on `soccer_championship_props`
    put the Odds API key in clear into `stderr_tail` / `failureSummary` on the fleet."""
    url = "requests.exceptions.HTTPError: 502 for url: https://api.example.test/v4/sports/x/odds?apiKey=SECRETVALUE123&regions=us"
    result = {"name": "soccer_championship_props", "ok": False, "return_code": 1,
              "stdout": "", "stderr": "Traceback ...\n" + url, "stdout_markers": []}
    module._compact_step_result(result)
    view = module._compact_step_result_view(result)
    assert "SECRETVALUE123" not in view["stderr_tail"]
    assert "apiKey=***" in view["stderr_tail"]
    assert "regions=us" in view["stderr_tail"]  # only the credential is masked


def test_the_nfl_gameline_shard_line_the_writer_prints_survives_blanking(module, capsys, monkeypatch, tmp_path):
    """Lane `nfl-gameline-kickoff-shard` (todo #817, 2026-11-16). The NFL game-line writer
    prints which shard basis ran and the rows per shard date; at the 22:31Z load that line
    was blanked here, so the load could be verified only on the shard rows. This drives the
    REAL writer (filing line, then its FAILED line) and feeds what it printed through the
    real `_run_command`, so a renamed token on either side fails here."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.delenv("SYNDICATE_WEB_PUBLISH_URL", raising=False)
    monkeypatch.delenv("SYNDICATE_NFL_GAMELINE_QUOTES_KICKOFF_SHARD", raising=False)
    path = Path(__file__).resolve().parents[1] / "scripts" / "fetch_nfl_team_odds_local.py"
    spec = importlib.util.spec_from_file_location("test_refresh_odds_step_markers_nfl_writer", path)
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    from datetime import datetime, timezone

    stamp = "2026-11-17T01:40:00Z"
    mnf = {"id": "mnf-lac-bal", "sport_key": "americanfootball_nfl", "commence_time": "2026-11-17T01:15:00Z",
           "home_team": "Baltimore Ravens", "away_team": "Los Angeles Chargers",
           "bookmakers": [{"key": "draftkings", "title": "DraftKings", "last_update": stamp, "markets": [
               {"key": "h2h", "last_update": stamp, "outcomes": [
                   {"name": "Baltimore Ravens", "price": -150}, {"name": "Los Angeles Chargers", "price": 130}]}]}]}
    in_play = datetime(2026, 11, 17, 1, 40, tzinfo=timezone.utc)

    assert writer._append_nfl_team_book_quotes([mnf], now=in_play)["shards"] == {"2026-11-16": 2}
    import syndicate.features.shared.odds_book_quotes as obq

    def _boom(*_args, **_kwargs):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(obq, "bucket_quote_rows_by_kickoff_date", _boom)
    assert writer._append_nfl_team_book_quotes([mnf], now=in_play) is None
    printed = capsys.readouterr().out
    filing, failed = [text for text in printed.splitlines() if "NFL_GAMELINE_QUOTE_SHARD" in text]
    assert "basis=kickoff_central" in filing and "shards=2026-11-16:2" in filing
    assert "FAILED" in failed and "disk gone" in failed

    step = module.RefreshStep(name="nfl_oddsapi_refresh", phases=("live",), cwd=Path("."),
                              command=("python", "refresh_nfl_oddsapi.py"), env_updates=None, description="t")
    completed = subprocess.CompletedProcess(args=list(step.command), returncode=0,
                                            stdout=f"noise\n{printed}more noise\n", stderr="")
    with patch.object(module.subprocess, "run", return_value=completed), \
            patch.object(module, "_log_memory", return_value=None), \
            patch.object(module, "_dump_child_runtime_state", return_value=None), \
            patch.object(module, "_record_step_in_sim_ledger", return_value=None), \
            patch.object(module, "_step_rss_cap_mb", return_value=None):
        result = module._run_command(step)
    err = capsys.readouterr().err
    assert f"STEP_MARKER name=nfl_oddsapi_refresh {filing.strip()}" in err
    assert f"STEP_MARKER name=nfl_oddsapi_refresh {failed.strip()}" in err
    module._compact_step_result(result)
    assert result["stdout"] == ""
    assert module._compact_step_result_view(result)["stdout_markers"] == [filing.strip(), failed.strip()]
