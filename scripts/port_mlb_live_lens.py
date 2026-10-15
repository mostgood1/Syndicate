"""Generator for syndicate/features/mlb/live_lens_port/ -- Syndicate's port of the MLB live lens (PHASE 1: the app slice).

Lane mlb-live-lens-native-p1 (user decision 2026-10-15: "Phase it: app slice first"). Two entry points in the vendored
21k-line Flask app vendor/mlb_bettingv2/tools/web/flask_frontend.py feed production:

  * `_live_lens_reports_payload(date, include_archive=..., slim=...)` -- scripts/refresh_mlb_oddsapi.py loads the
    vendored app by path to build the MLB live-lens reports;
  * `start_live_lens_background_loop()` -- scripts/run_live_odds_refresh_worker.py imports it from the vendored app.

This copies their closure into one module, `app_slice.py`, with the method of scripts/port_basketball_live_tick.py
(whose helpers it imports): a scope-correct `symtable` closure, every selected top-level statement copied VERBATIM in
source order, behind the vendored module's own import header.

PHASE 1 keeps the vendored `sim_engine` / `tools` packages: the header still imports them, from vendor/mlb_bettingv2
(the same tree the vendored app put on sys.path). Phase 2 ports them. So the only hand-written behaviour is EDITS:
  * the app's `_ROOT` / `_WEB_DIR` (and every other `Path(__file__)`-relative root in the closure) point at the vendored
    repo exactly as the vendored file resolved them, because this module lives elsewhere;
  * a private Flask app replaces the vendored one -- the closure uses only `app.logger`.

Usage:
  py -3 scripts/port_mlb_live_lens.py            # write the package
  py -3 scripts/port_mlb_live_lens.py --check    # exit 1 if the package on disk differs
  py -3 scripts/port_mlb_live_lens.py --report   # closure size, header use, and every Path(__file__) site
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_tick_gen", ROOT / "scripts" / "port_basketball_live_tick.py")
_tg = importlib.util.module_from_spec(_spec)
sys.modules["_tick_gen"] = _tg
_spec.loader.exec_module(_tg)

VENDOR = ROOT / "vendor" / "mlb_bettingv2"
SRC = VENDOR / "tools" / "web" / "flask_frontend.py"
OUT = ROOT / "syndicate" / "features" / "mlb" / "live_lens_port"
ROOTS = ["_live_lens_reports_payload", "start_live_lens_background_loop"]

#: The header: the vendored module's own top-level import statements (copied verbatim, see `_header`), then this.
_HEADER_ROOTS = '''
# EDIT (phase 1): the vendored app put its own repo root on sys.path so `sim_engine` / `tools` import; this module lives
# in Syndicate, so the same vendored root is named explicitly. Phase 2 ports those packages and drops this.
_ROOT = Path(__file__).resolve().parents[4] / "vendor" / "mlb_bettingv2"
_WEB_DIR = _ROOT / "tools" / "web"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
'''

#: The closure's `Path(__file__)`-relative roots, rewritten to what the vendored file resolved them to.
#: (anchor, replacement); each must match exactly once in the generated body.
EDITS: list[tuple[str, str]] = [
    # In the vendored file parents[2] of tools/web/flask_frontend.py IS vendor/mlb_bettingv2 -- the header's _ROOT.
    ("_ROOT_DIR = Path(__file__).resolve().parents[2]\n",
     "_ROOT_DIR = _ROOT  # EDIT: the vendored repo root, as Path(__file__).parents[2] resolved it there\n"),
]


#: Top-level `try:` / `if:` statements the closure may copy verbatim (the shared walker refuses them by default), by the
#: name they bind. `_USER_TIMEZONE` (a 4-line try around ZoneInfo with a fallback) is the only one the closure reaches;
#: the module's other two are the sys.path `if` (replaced by the header EDIT) and `if __name__ == "__main__":`.
ALLOWED_TRY_IF = {"_USER_TIMEZONE"}


def _closure(lines: list[str], tree: ast.Module, roots: list[str], header_names: set[str]) -> tuple[dict[int, ast.stmt], set[str]]:
    """scripts/port_basketball_live_tick.py's `_closure`, plus the ALLOWED_TRY_IF statements."""
    import builtins

    binders: dict[str, list[ast.stmt]] = {}
    for node in tree.body:
        if _tg._is_import_stmt(node):
            continue
        for name in _tg._bound_names(node):
            binders.setdefault(name, []).append(node)
    selected: dict[int, ast.stmt] = {}
    used_header: set[str] = set()
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        if name in header_names:
            used_header.add(name)
            continue
        nodes = binders.get(name)
        if not nodes:
            if hasattr(builtins, name) or name in {"__file__", "__name__"}:
                continue
            raise SystemExit(f"[{SRC.name}] unresolved module name {name!r}")
        if isinstance(nodes[-1], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes = [nodes[-1]]  # the LAST def wins at import time
        for node in nodes:
            if isinstance(node, (ast.Try, ast.If)) and name not in ALLOWED_TRY_IF:
                raise SystemExit(f"[{SRC.name}] {name!r} is bound by a try/if at line {node.lineno}: allow it in ALLOWED_TRY_IF")
            selected[node.lineno] = node
            own = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            stack.extend(_tg._module_refs(_tg._segment(lines, node), own))
    return selected, used_header


def _atexit_registrations(tree: ast.Module, lines: list[str], selected: dict[int, ast.stmt]) -> dict[int, ast.stmt]:
    """Top-level `atexit.register(<fn>)` statements whose <fn> touches module state the closure selected. They bind no
    name, so the walk never reaches them -- yet they are the module's own exit behaviour for state it carries
    (`_release_live_lens_process_lock` unlocks and closes the background loop's `_LIVE_LENS_PROCESS_LOCK_HANDLE`)."""
    bound = set().union(*[_tg._bound_names(n) for n in selected.values()])
    defs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    found: dict[int, ast.stmt] = {}
    for node in tree.body:
        call = node.value if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) else None
        if not (call is not None and isinstance(call.func, ast.Attribute) and call.func.attr == "register"
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "atexit"
                and call.args and isinstance(call.args[0], ast.Name) and call.args[0].id in defs):
            continue
        target = defs[call.args[0].id]
        if set(_tg._module_refs(_tg._segment(lines, target), target.name)) & bound:
            found[node.lineno] = node
    return found


def _source() -> tuple[str, list[str], ast.Module]:
    raw = SRC.read_text(encoding="utf-8-sig")
    return raw, raw.split("\n"), ast.parse(raw)


def _header(lines: list[str], tree: ast.Module) -> tuple[str, set[str]]:
    """Every top-level import statement, verbatim and in order (the sim_engine/tools ones only after the sys.path EDIT)."""
    plain, vendored = [], []
    for node in tree.body:
        if not _tg._is_import_stmt(node) or (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            continue
        inner = [s for s in ast.walk(node) if isinstance(s, (ast.Import, ast.ImportFrom))]  # a `try:` of imports too
        mods = [(s.module or "") if isinstance(s, ast.ImportFrom) else s.names[0].name for s in inner]
        is_vendored = any(m.split(".")[0] in {"sim_engine", "tools"} for m in mods)
        (vendored if is_vendored else plain).append(_tg._segment(lines, node))
    names = set().union(*[_tg._bound_names(n) for n in tree.body if _tg._is_import_stmt(n)])
    text = "\n".join(plain) + "\n" + _HEADER_ROOTS + "\n" + "\n".join(vendored) + "\n\n# EDIT: a private Flask app; the closure uses only app.logger.\napp = Flask(__name__)\n"
    return text, names | {"_ROOT", "_WEB_DIR", "app"}


def generate() -> tuple[str, dict]:
    raw, lines, tree = _source()
    header, header_names = _header(lines, tree)
    selected, used_header = _closure(lines, tree, ROOTS, header_names)
    exits = _atexit_registrations(tree, lines, selected)
    if exits:  # their targets join the roots, so each target's own closure comes along
        selected, used_header = _closure(lines, tree, ROOTS + [n.value.args[0].id for n in exits.values()], header_names)
        selected.update(exits)
    body = "\n\n\n".join(_tg._segment(lines, selected[k]) for k in sorted(selected))
    for old, new in EDITS:
        if body.count(old) != 1:
            raise SystemExit(f"EDIT anchor matched {body.count(old)}x: {old[:80]!r}")
        body = body.replace(old, new)
    sha = hashlib.sha256(SRC.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]
    doc = ('"""GENERATED by scripts/port_mlb_live_lens.py -- do not edit by hand (`--check` fails on a hand edit).\n\n'
           f"Source: {SRC.relative_to(ROOT).as_posix()} (sha256 {sha}...), {len(selected)} top-level statements, copied verbatim\n"
           "except for the import header and the EDITS listed in the generator. PHASE 1: still imports the vendored\n"
           "sim_engine / tools packages.\n"
           '"""\n')
    text = doc + "from __future__ import annotations\n\n" + header + "\n\n" + body + "\n"
    report = {
        "selected": len(selected),
        "body_lines": body.count("\n") + 1,
        "header_names_used": sorted(used_header),
        "file_sites": [(selected[k].lineno, ln.strip()[:110]) for k in sorted(selected)
                       for ln in _tg._segment(lines, selected[k]).split("\n") if "__file__" in ln],
    }
    return text, report


def outputs() -> dict[str, str]:
    text, _ = generate()
    _tg._validate("mlb/live_lens_port/app_slice.py", text)
    return {
        "app_slice.py": text,
        "__init__.py": ('"""Syndicate port of the vendored MLB live lens (phase 1: the app slice of\n'
                        "vendor/mlb_bettingv2/tools/web/flask_frontend.py). GENERATED by scripts/port_mlb_live_lens.py\n"
                        "(lane mlb-live-lens-native-p1). Parity: scripts/mlb_live_lens_parity.py.\n"
                        '"""\n'),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if not SRC.exists():
        print("vendor tree absent: nothing to generate from")
        return 0
    if args.report:
        _, report = generate()
        print(f"selected top-level statements: {report['selected']}, body lines: {report['body_lines']}")
        print(f"header names used: {report['header_names_used']}")
        print(f"Path(__file__) sites in the closure ({len(report['file_sites'])}):")
        for lineno, ln in report["file_sites"]:
            print(f"  stmt@{lineno}: {ln}")
        return 0
    files = outputs()
    if args.check:
        bad = [n for n, t in files.items() if not (OUT / n).exists() or (OUT / n).read_bytes().replace(b"\r\n", b"\n") != t.encode("utf-8")]
        extra = sorted(p.name for p in OUT.glob("*.py") if p.name not in files) if OUT.exists() else []
        print("CHECK OK" if not bad and not extra else f"CHECK FAILED differs={bad} unexpected={extra}")
        return 0 if not bad and not extra else 1
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (OUT / name).write_bytes(text.encode("utf-8"))
    print(f"wrote {len(files)} files to {OUT} ({files['app_slice.py'].count(chr(10))} lines in app_slice.py)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
