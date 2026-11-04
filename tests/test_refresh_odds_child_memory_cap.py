"""A refresh_odds_sources child step that outgrows its RSS cap fails ALONE and loudly (lane nba-props-oom).

The cap runs a REAL child here: a mocked subprocess would prove the bookkeeping and
not that the tree is measured and killed, which is the whole point."""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
psutil = pytest.importorskip("psutil")


@pytest.fixture(scope="module")
def module():
    path = REPO_ROOT / "scripts" / "refresh_odds_sources.py"
    spec = importlib.util.spec_from_file_location("test_refresh_odds_child_memory_cap_mod", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _step(module, code: str):
    return module.RefreshStep(name="nba_oddsapi_props_job", phases=("live",), cwd=REPO_ROOT,
                              command=(sys.executable, "-c", code), env_updates=None, description="t")


def _run(module, step, env: dict[str, str], capsys):
    with patch.dict(module.os.environ, env), \
            patch.object(module, "_log_memory", return_value=None), \
            patch.object(module, "_dump_child_runtime_state", return_value=None), \
            patch.object(module, "_record_step_in_sim_ledger", return_value=None):
        result = module._run_command(step)
    return result, capsys.readouterr().err


# Grows to ~600 MB in 50 MB steps, then sleeps far past any poll; a cap of 200 MB must end it.
_GROW = "import time\nblocks=[]\nfor _ in range(12):\n    blocks.append(bytearray(50*1024*1024))\n    time.sleep(0.2)\ntime.sleep(60)\n"


def test_child_over_cap_is_killed_and_the_step_fails_loudly(module, capsys):
    started = time.monotonic()
    result, err = _run(module, _step(module, _GROW), {"SYNDICATE_ODDS_STEP_RSS_CAP_MB": "200"}, capsys)
    assert time.monotonic() - started < 30  # killed, not left to its 60 s sleep
    assert result["ok"] is False
    assert result["return_code"] != 0
    assert result["memory_cap"]["cap_mb"] == 200
    assert result["memory_cap"]["rss_mb"] > 200
    assert "STEP_FAIL name=nba_oddsapi_props_job status=memory_cap" in err
    assert "STEP_END name=nba_oddsapi_props_job status=memory_cap" in err


def test_child_under_cap_runs_untouched(module, capsys):
    result, err = _run(module, _step(module, "print('fine')"), {"SYNDICATE_ODDS_STEP_RSS_CAP_MB": "4096"}, capsys)
    assert result["ok"] is True and result["memory_cap"] is None
    assert "fine" in result["stdout"]
    assert "memory_cap" not in err


def test_cap_setting(module):
    with patch.dict(module.os.environ, {}, clear=True):
        assert module._step_rss_cap_mb() == module._STEP_RSS_CAP_DEFAULT_MB  # absent is the default, never off
    for off in ("0", "off", "false"):
        with patch.dict(module.os.environ, {"SYNDICATE_ODDS_STEP_RSS_CAP_MB": off}):
            assert module._step_rss_cap_mb() is None
    with patch.dict(module.os.environ, {"SYNDICATE_ODDS_STEP_RSS_CAP_MB": "6144"}):
        assert module._step_rss_cap_mb() == 6144
    with patch.dict(module.os.environ, {"SYNDICATE_ODDS_STEP_RSS_CAP_MB": "junk"}):
        assert module._step_rss_cap_mb() == module._STEP_RSS_CAP_DEFAULT_MB
