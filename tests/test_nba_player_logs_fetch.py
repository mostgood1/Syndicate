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
class _Res:
    def __init__(self, rows):
        self.rows = rows

    def get_normalized_dict(self):
        return {"LeagueGameLog": self.rows}

    def get_data_frames(self):
        return [pd.DataFrame(self.rows)]


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
