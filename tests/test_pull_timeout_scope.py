"""The hot-artifact pull timeout is 90 s for the board build and 30 s for the live-lens tick.

MEASURED 2026-09-16 (lane `web-export-timeout`). refresh-worker's dated pulls timed
out 10 of 12 between 15:46Z and 16:27Z at the 30 s client timeout, and tomorrow's
board artifacts sat on a 15:11:37Z floor. On the exact failing request web's
directory walk ALONE took 54.20 s and 78.86 s. The default was raised to 90 s.

But the same function is called INLINE by the live-lens loop, before each ~60 s
tick on live-odds-worker. At 90 s, two slow date patterns could hold that tick back
for minutes and stale the soccer live aggregate the Layer 2 chips read. So that one
caller passes 30 s explicitly.

These tests pin the three facts the split depends on. They inspect the call SITES
through the AST, not by grepping text, so a reformatted call still matches and a
renamed keyword does not.
"""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

from syndicate.features.shared import artifact_publisher

_REPO = Path(__file__).resolve().parents[1]


def _pull_calls(relative: str, *, within: str | None = None) -> list[ast.Call]:
    tree = ast.parse((_REPO / relative).read_text(encoding="utf-8"))
    scope: ast.AST = tree
    if within is not None:
        matches = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == within]
        assert matches, f"{within} not found in {relative}"
        scope = matches[0]
    calls = []
    for node in ast.walk(scope):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name == "pull_hot_artifacts":
                calls.append(node)
    return calls


def _timeout_keyword(call: ast.Call):
    for kw in call.keywords:
        if kw.arg == "timeout_seconds":
            return kw.value
    return None


def test_the_board_build_default_is_90_seconds() -> None:
    default = inspect.signature(artifact_publisher.pull_hot_artifacts).parameters["timeout_seconds"].default
    assert default == 90, f"the board pull timeout is {default}s; 30s timed out 10 of 12 refresh-worker pulls"


def test_the_live_lens_tick_pulls_with_an_EXPLICIT_30_seconds() -> None:
    """Without this, the 90 s default reaches a loop that must tick every ~60 s."""
    calls = _pull_calls("syndicate/features/shared/live_lens_loop.py", within="_live_lens_background_loop")
    assert len(calls) == 1, f"expected one pull in the live-lens loop, found {len(calls)}"
    value = _timeout_keyword(calls[0])
    assert value is not None, "the live-lens pull takes the 90 s board default -- it can stall the tick"
    assert isinstance(value, ast.Constant) and value.value == 30, f"live-lens pull timeout is {ast.dump(value)}"


def test_refresh_workers_board_pulls_take_the_default_and_do_not_override_it() -> None:
    """The fix reaches refresh-worker ONLY through the default. A caller that passes
    its own timeout there silently puts the 10-of-12 failure back."""
    calls = _pull_calls("pipeline/intelligence_state.py")
    assert calls, "refresh-worker's board build no longer calls pull_hot_artifacts -- this test is guarding nothing"
    overridden = [c.lineno for c in calls if _timeout_keyword(c) is not None]
    assert not overridden, f"board-build pulls override the timeout at lines {overridden}"
