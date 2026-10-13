"""The NBA refresh no longer runs the vendored playoff transition (lane nba-source-cli-native, user decision 2026-10-13).

It loaded `<source_root>/src/nba_betting/playoff_transition.py`, a data-disk copy that does not exist on the fleet, so
every run returned "unavailable" and nothing was ever retrained. Had it run, it would have retrained the game and
props models, run four calibration scripts and rewritten the live-lens tuning override at the end of the regular
season. Retraining for the playoffs is a separate, deliberate decision; removing the step is behaviour-identical.
"""
from __future__ import annotations

import ast
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "refresh_nba_oddsapi_props.py"


def test_refresh_has_no_playoff_transition_runner_import_or_receipt_copy():
    src = SCRIPT.read_text(encoding="utf-8")
    tree = ast.parse(src)
    assert "_run_playoff_transition_if_needed" not in {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "playoff_transition" not in src  # no import, no state["playoff_transition"], no receipt glob/copy
