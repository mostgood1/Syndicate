"""The live-lens tick can no longer emit BET on a model line — the `#626`(e) fix.

MEASURED (lane `wnba-accuracy-assessment`, 2026-08-31): 701 of 1,777 live prop
signals were priced against the model's OWN line and "hit" 91.21% — the single
largest contributor to a fictional +41% live ROI. The API layer has refused
those rows since 2026-05-25 (`line_source in {None, "model"}` forces klass to
NONE), but the JSONL tick writer RE-DERIVES klass from tuning thresholds and
skipped that constraint, so refused rows came back as BET in the signals file.

These tests avoid importing the 40k-line vendor Flask modules: the gate function
is extracted from each file's AST and compiled alone (behaviour), and the call
site is verified structurally (reachability) — the gate must WRAP the `_klass`
re-derivation inside `_live_lens_tick_payload`, in BOTH vendor repos, because
the NBA tick is a mirror of the WNBA one and a fix applied to only one file is
the platform's documented copy-drift failure mode.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
VENDOR_APPS = [
    REPO_ROOT / "vendor" / "wnba_betting_repo" / "app.py",
    REPO_ROOT / "vendor" / "nba_betting_repo" / "app.py",
]


def _load_gate(path: Path):
    """Compile only `_tick_prop_klass_line_gate` out of the vendor module."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "_tick_prop_klass_line_gate":
            module = ast.Module(body=[node], type_ignores=[])
            namespace: dict = {}
            exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 — own repo source
            return namespace["_tick_prop_klass_line_gate"]
    raise AssertionError(f"_tick_prop_klass_line_gate not found in {path}")


@pytest.mark.parametrize("path", VENDOR_APPS, ids=lambda p: p.parent.name)
def test_model_line_rows_are_forced_to_none(path):
    gate = _load_gate(path)
    assert gate("BET", "model") == "NONE"
    assert gate("WATCH", "model") == "NONE"
    assert gate("BET", None) == "NONE"


@pytest.mark.parametrize("path", VENDOR_APPS, ids=lambda p: p.parent.name)
def test_real_market_lines_pass_through_unchanged(path):
    """Off-is-not-on: the gate must not flatten legitimate signals."""
    gate = _load_gate(path)
    assert gate("BET", "oddsapi") == "BET"
    assert gate("WATCH", "pregame") == "WATCH"
    assert gate("NONE", "oddsapi") == "NONE"


@pytest.mark.parametrize("path", VENDOR_APPS, ids=lambda p: p.parent.name)
def test_gate_wraps_the_klass_rederivation_at_the_call_site(path):
    """Reachability, structurally: inside `_live_lens_tick_payload` there is a
    call `_tick_prop_klass_line_gate(_klass(...), ...)`. Presence of the helper
    alone proves nothing — the defect WAS a derivation that skipped the gate."""
    tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    tick = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_live_lens_tick_payload"),
        None,
    )
    assert tick is not None, f"_live_lens_tick_payload not found in {path}"
    for node in ast.walk(tick):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_tick_prop_klass_line_gate"
            and node.args
            and isinstance(node.args[0], ast.Call)
            and isinstance(node.args[0].func, ast.Name)
            and node.args[0].func.id == "_klass"
        ):
            return
    raise AssertionError(f"no _tick_prop_klass_line_gate(_klass(...)) call inside the tick in {path}")
