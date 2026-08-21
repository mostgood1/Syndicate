"""No function-local import may shadow a module-level name in live_lens_loop.

MEASURED IN PRODUCTION 2026-08-21 18:49Z, mid-slate, two soccer matches in play:

    latestTick.ok = false
    mlb    -> UnboundLocalError: cannot access local variable 'write_json_file'
    soccer -> UnboundLocalError: cannot access local variable 'write_json_file'

A WNBA live-box capture block added a function-local
`from ... import data_root, write_json_file`. Python binds that name as LOCAL
for the WHOLE function, so the snapshot write further down -- which every sport
reaches, and which for mlb/soccer runs without the WNBA block ever executing --
raised before assignment. No live-lens snapshot was written for ANY sport, and
every downstream live join then read an absent artifact and correctly reported
zero. Three consumers looked broken; one import was.

This is a STATIC test on purpose: reproducing it needs a live slate, and by the
time a live slate exists it is too late to find out.
"""
from __future__ import annotations

import ast
import pathlib


MODULE = pathlib.Path(__file__).resolve().parents[1] / "syndicate" / "features" / "shared" / "live_lens_loop.py"


def _module_level_names(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                names.add(alias.asname or alias.name.split(".")[0])
    return names


def _conditional_imports(func):
    """Imports nested inside control flow -- i.e. ones that MAY NOT RUN.

    An unconditional import at the top of a function is harmless even when it
    shadows: it always executes before any use. The dangerous shape is a shadow
    bound inside an `if`/`try`/loop, because the name is local for the whole
    function while the binding only happens on one path. That is exactly the
    2026-08-21 defect -- the WNBA branch never ran for mlb/soccer.
    """
    out = []
    for node in ast.walk(func):
        if not isinstance(node, (ast.If, ast.Try, ast.For, ast.While, ast.With)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, (ast.Import, ast.ImportFrom)):
                out.append(inner)
    return out


def test_no_conditional_local_import_shadows_a_module_level_import():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    top = _module_level_names(tree)
    offenders = []
    for func in ast.walk(tree):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in _conditional_imports(func):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                if bound in top:
                    offenders.append(
                        f"{func.name}() conditionally rebinds module-level "
                        f"'{bound}' at line {node.lineno}"
                    )
    assert not offenders, (
        "a CONDITIONAL function-local import shadows a module-level name for "
        "the WHOLE function, so any use on a path that skips it raises "
        "UnboundLocalError: "
        + "; ".join(offenders)
        + " -- alias it (`import x as _local_x`) or drop the redundant import."
    )
