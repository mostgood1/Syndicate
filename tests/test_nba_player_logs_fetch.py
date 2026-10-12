"""NBA season player-log fetch is Syndicate's own (lane nba-live-tick-native, 2026-10-12).

syndicate/features/shared/nba_player_logs_fetch.py is a verbatim copy of two functions from the vendored
nba_betting/player_logs.py. Pinned three ways:
  * the two functions are AST-identical to the vendored source (while the vendor tree exists);
  * behaviour, on the same mocked LeagueGameLog, for both copies: rows -> a frame with SEASON stamped; an empty
    response retried then raised; an exception retried then raised -- with identical results and calls;
  * nba_history_refresh's default fetch reaches the Syndicate copy, never the vendored package.
"""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pytest

from syndicate.features.shared import nba_player_logs_fetch as native

ROOT = Path(__file__).resolve().parents[1]
VENDORED = ROOT / "vendor" / "nba_betting_repo" / "src" / "nba_betting" / "player_logs.py"
FUNCS = ("_configure_stats_headers", "_fetch_season_player_logs")


def _funcs(path: Path) -> dict[str, str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {n.name: ast.dump(n) for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in FUNCS}


def test_functions_are_ast_identical_to_the_vendored_source():
    if not VENDORED.exists():
        pytest.skip("vendor tree removed")
    assert _funcs(Path(native.__file__)) == _funcs(VENDORED)


def _vendored_module():
    """The two vendored functions compiled alone, with the vendored module's own imports for them."""
    if not VENDORED.exists():
        pytest.skip("vendor tree removed")
    tree = ast.parse(VENDORED.read_text(encoding="utf-8"))
    keep = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in FUNCS]
    ns: dict = {"pd": pd, "time": __import__("time"), "leaguegamelog": native.leaguegamelog, "nba_http": native.nba_http}
    exec(compile(ast.Module(body=keep, type_ignores=[]), str(VENDORED), "exec"), ns)  # noqa: S102 -- own repo source
    return ns


class _Res:
    def __init__(self, rows):
        self.rows = rows

    def get_normalized_dict(self):
        return {"LeagueGameLog": self.rows}

    def get_data_frames(self):
        return [pd.DataFrame(self.rows)]


def _scenario(fn_ns, monkeypatch, responses):
    calls, sleeps = [], []
    seq = list(responses)

    def fake_lgl(**kw):
        calls.append(kw)
        r = seq.pop(0)
        if isinstance(r, Exception):
            raise r
        return _Res(r)

    monkeypatch.setattr(native.leaguegamelog, "LeagueGameLog", fake_lgl)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    try:
        out = fn_ns["_fetch_season_player_logs"]("2026-27", max_attempts=2)
        result = ("ok", out.to_dict("list"))
    except Exception as exc:  # noqa: BLE001
        result = ("raised", type(exc).__name__, str(exc))
    return result, calls, sleeps


@pytest.mark.parametrize("responses", [
    [[{"GAME_ID": "0022600001", "PLAYER_ID": 1, "PTS": 30}]],
    [[], [{"GAME_ID": "0022600001", "PLAYER_ID": 1, "PTS": 30}]],
    [[], []],
    [RuntimeError("stats.nba timed out"), RuntimeError("again")],
], ids=["rows", "empty-then-rows", "empty-twice", "errors"])
def test_same_behaviour_as_the_vendored_copy(responses, monkeypatch):
    vend = _vendored_module()
    nat = {"_fetch_season_player_logs": native._fetch_season_player_logs}
    got_native = _scenario(nat, monkeypatch, responses)
    got_vendored = _scenario(vend, monkeypatch, responses)
    assert got_native == got_vendored
    if got_native[0][0] == "ok":
        assert got_native[0][1]["SEASON"] == ["2026-27"]
    assert got_native[1][0]["season_type_all_star"] == "Regular Season"


def test_history_refresh_default_fetch_is_the_syndicate_copy(monkeypatch):
    from syndicate.features.shared import nba_history_refresh as h

    seen = []
    monkeypatch.setattr(native, "_fetch_season_player_logs", lambda season, max_attempts=3: seen.append((season, max_attempts)) or pd.DataFrame())
    before = set(sys.modules)
    h._vendor_fetch()("2026-27")
    assert seen == [("2026-27", 2)]
    assert not any(m == "nba_betting" or m.startswith("nba_betting.") for m in set(sys.modules) - before)
    src = Path(h.__file__).read_text(encoding="utf-8")
    assert "nba_betting_repo" not in src and "from nba_betting" not in src
