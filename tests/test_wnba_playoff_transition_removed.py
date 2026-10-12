"""The WNBA refresh no longer imports the vendored playoff transition (lane wnba-playoff-transition-off-vendor).

Measured 2026-10-12 on the fleet with the exact copy production imported (<data root>/wnba_source/src, identical to
vendor/wnba_betting_repo/src/wnba_betting/playoff_transition.py): resolve_regular_season_window raised "No
regular-season schedule rows found" for every 2026 date tried (05-20 .. 10-12), because it keys on NBA game ids
("002...") and "YYYY-YY" season strings while the WNBA schedule carries ESPN ids ("040...") and "YYYY". The step
returned "skipped" every run and never wrote a receipt or a model. Removing it is behaviour-identical.
"""

from __future__ import annotations

import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "refresh_wnba_oddsapi_props.py"


def test_refresh_has_no_playoff_transition_runner_or_import():
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "_run_playoff_transition_if_needed" not in names
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            assert "wnba_betting.playoff_transition" not in n.value, n.lineno
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant):
            assert n.slice.value != "playoff_transition", n.lineno  # no state["playoff_transition"] written


def test_the_vendored_transition_could_not_match_wnba_game_ids():
    """The reason it never fired, pinned from the vendored source itself: it only accepts NBA regular-season ids."""
    vendored = Path(__file__).resolve().parents[1] / "vendor" / "wnba_betting_repo" / "src" / "wnba_betting" / "playoff_transition.py"
    if not vendored.exists():
        return
    text = vendored.read_text(encoding="utf-8-sig")
    assert 'game_id.startswith("002")' in text
    assert 'f"{season_start}-{(season_start + 1) % 100:02d}"' in text
