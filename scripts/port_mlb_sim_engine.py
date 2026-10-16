"""Generator for syndicate/features/mlb/sim_engine/ and syndicate/features/mlb/tools_port/ -- the MLB engine off vendor.

Lane mlb-sim-engine-native-p2 (user decision 2026-10-16: "Native engine package"). Phase 1
(scripts/port_mlb_live_lens.py) moved the live lens's slice of the vendored Flask app into Syndicate but left it importing
the vendored `sim_engine` / `tools` packages. This generates both natively:

  * syndicate/features/mlb/sim_engine/ -- the WHOLE vendored package vendor/mlb_bettingv2/sim_engine/, every module
    copied verbatim (one package, so the daily sim can later switch to it and there is one engine, not two);
  * syndicate/features/mlb/tools_port/<module>.py -- for each vendored `tools.*` module the live lens imports from, the
    `symtable` closure of exactly the names imported (scripts/port_basketball_live_tick.py's method, whose helpers this
    imports), statements copied verbatim in source order behind the module's own import statements; a `tools.*` import
    that closure keeps is ported the same way, recursively.

The only hand-written behaviour is EDITS, all mechanical and listed here:
  * VENDORED FILE: in a module that calls `Path(__file__)`, that call becomes `Path(_VENDORED_FILE)`, defined as the
    path the module has in the vendored tree. Every `.resolve().parents[k]` therefore lands on exactly the directory it
    did in vendor/ -- the copy sits at a different depth, so a plain `__file__` would silently move every data root
    (`parents[4] / "data"` in sim_engine/data/ is the Syndicate repo's own data dir, for instance).
  * IMPORT PATHS: `sim_engine...` -> `syndicate.features.mlb.sim_engine...` and `tools.<pkg>.<module>` ->
    `syndicate.features.mlb.tools_port.<module>` in every import statement, indented ones included.
  * `sim_engine/data/roster_artifact.py`'s one absolute `from sim_engine.models import` becomes the relative
    `from ..models import`, as every other intra-package import already is: an absolute path would load a SECOND copy
    of `models` and two class hierarchies.

Usage:
  py -3 scripts/port_mlb_sim_engine.py            # write both packages
  py -3 scripts/port_mlb_sim_engine.py --check    # exit 1 if either package on disk differs
  py -3 scripts/port_mlb_sim_engine.py --report   # per-module sizes, EDIT sites, and the tools closure sizes
"""
from __future__ import annotations

import argparse
import ast
import builtins
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
SIM_SRC = VENDOR / "sim_engine"
SIM_OUT = ROOT / "syndicate" / "features" / "mlb" / "sim_engine"
TOOLS_OUT = ROOT / "syndicate" / "features" / "mlb" / "tools_port"
NATIVE_SIM = "syndicate.features.mlb.sim_engine"
NATIVE_TOOLS = "syndicate.features.mlb.tools_port"
#: The vendored app whose top-level `tools.*` imports seed the tools closures (the live lens's own import header).
APP = VENDOR / "tools" / "web" / "flask_frontend.py"
VENDORED_ROOTS = {"sim_engine", "tools"}

#: Per-file EDITS beyond the mechanical ones: {path relative to sim_engine/: [(anchor, replacement)]}; each anchor must
#: match exactly once.
SIM_EDITS: dict[str, list[tuple[str, str]]] = {
    "data/roster_artifact.py": [
        ("from sim_engine.models import (\n",
         "from ..models import (  # EDIT: relative, as every other intra-package import is (one `models`, not two)\n"),
    ],
}

#: Top-level `try:` / `if:` statements a tools closure may copy verbatim, by the name they bind (the shared walker
#: refuses them by default). Filled only from a measured need.
ALLOWED_TRY_IF: set[str] = set()

_IMPORT_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<kw>from|import)[ \t]+(?P<mod>(?:sim_engine|tools)(?:\.[A-Za-z0-9_]+)*)\b",
                        re.M)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def _tools_module_name(dotted: str) -> str:
    """`tools.eval.build_season_eval_manifest` -> `build_season_eval_manifest` (flat; uniqueness is asserted)."""
    return dotted.split(".")[-1]


def _rewrite_imports(text: str, where: str) -> str:
    def sub(m: re.Match) -> str:
        mod, kw = m.group("mod"), m.group("kw")
        if kw != "from":
            raise SystemExit(f"[{where}] `import {mod}` binds a vendored top-level name; only `from ... import` is rewritten")
        if mod.split(".")[0] == "sim_engine":
            return f"{m.group('indent')}from {NATIVE_SIM}{mod[len('sim_engine'):]}"
        return f"{m.group('indent')}from {NATIVE_TOOLS}.{_tools_module_name(mod)}"

    return _IMPORT_RE.sub(sub, text)


def _vendored_file_edit(text: str, out_rel: Path, vendored_rel: Path) -> str:
    """`Path(__file__)` -> `Path(_VENDORED_FILE)`, `_VENDORED_FILE` being this module's path in the vendored tree."""
    n = text.count("Path(__file__)")
    if not n:
        return text
    if text.count("__file__") != n:
        raise SystemExit(f"[{out_rel}] __file__ used outside Path(__file__); extend the EDIT rule deliberately")
    up = len(out_rel.parts) - 1  # parents[up] of the copy is the Syndicate repo root
    parts = ", ".join(repr(p) for p in ("vendor", "mlb_bettingv2", *vendored_rel.parts))
    line = (f"_VENDORED_FILE = str(__import__(\"pathlib\").Path(__file__).resolve().parents[{up}].joinpath({parts}))"
            f"  # EDIT: this module's path in vendor/, so every Path(_VENDORED_FILE).parents[k] is the vendored one\n")
    tree = ast.parse(text)
    insert_after = 0
    for i, node in enumerate(tree.body):
        is_doc = i == 0 and isinstance(node, ast.Expr) and isinstance(getattr(node, "value", None), ast.Constant) \
            and isinstance(node.value.value, str)
        is_future = isinstance(node, ast.ImportFrom) and node.module == "__future__"
        if is_doc or is_future:
            insert_after = node.end_lineno
        else:
            break
    lines = text.split("\n")
    body = "\n".join(lines[insert_after:]).replace("Path(__file__)", "Path(_VENDORED_FILE)")
    head = "\n".join(lines[:insert_after])
    return (head + "\n" if head else "") + line + body


def _check_no_vendored_imports(name: str, text: str) -> None:
    left = [m.group(0).strip() for m in _IMPORT_RE.finditer(text)]
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in VENDORED_ROOTS:
            left.append(node.module)
    if left:
        raise SystemExit(f"[{name}] vendored imports left: {left}")


# ---------------------------------------------------------------------------------------------------------- sim_engine


def sim_outputs() -> dict[Path, str]:
    """{path relative to SIM_OUT: text} -- every module of the vendored package."""
    out: dict[Path, str] = {}
    seen_edits: set[str] = set()
    for src in sorted(SIM_SRC.rglob("*.py")):
        if "__pycache__" in src.parts:
            continue
        rel = src.relative_to(SIM_SRC)
        text = _read(src)
        for old, new in SIM_EDITS.get(rel.as_posix(), []):
            if text.count(old) != 1:
                raise SystemExit(f"[sim_engine/{rel.as_posix()}] EDIT anchor matched {text.count(old)}x: {old!r}")
            text = text.replace(old, new)
            seen_edits.add(rel.as_posix())
        text = _rewrite_imports(text, f"sim_engine/{rel.as_posix()}")
        out_rel = SIM_OUT.relative_to(ROOT) / rel
        text = _vendored_file_edit(text, out_rel, Path("sim_engine") / rel)
        compile(text, str(out_rel), "exec")
        _check_no_vendored_imports(str(out_rel), text)
        out[rel] = text
    missing = set(SIM_EDITS) - seen_edits
    if missing:
        raise SystemExit(f"SIM_EDITS name files that were not generated: {sorted(missing)}")
    return out


# ------------------------------------------------------------------------------------------------------------ tools


def _closure(src: Path, lines: list[str], tree: ast.Module, roots: list[str], header_names: set[str]) -> tuple[dict[int, ast.stmt], set[str]]:
    """scripts/port_mlb_live_lens.py's `_closure` (the shared walker plus ALLOWED_TRY_IF), for one tools module."""
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
            raise SystemExit(f"[{src.name}] unresolved module name {name!r}")
        if isinstance(nodes[-1], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes = [nodes[-1]]  # the LAST def wins at import time
        for node in nodes:
            if isinstance(node, (ast.Try, ast.If)) and name not in ALLOWED_TRY_IF:
                raise SystemExit(f"[{src.name}] {name!r} is bound by a try/if at line {node.lineno}: allow it in ALLOWED_TRY_IF")
            selected[node.lineno] = node
            own = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            stack.extend(_tg._module_refs(_tg._segment(lines, node), own))
    return selected, used_header


def _import_targets(node: ast.stmt) -> list[ast.ImportFrom | ast.Import]:
    return [s for s in ast.walk(node) if isinstance(s, (ast.Import, ast.ImportFrom))]


def _vendored_tools_deps(node: ast.stmt) -> dict[str, set[str]]:
    """{`tools.x.y`: real names} imported by one import statement (aliases resolved to the name the module defines)."""
    deps: dict[str, set[str]] = {}
    for s in _import_targets(node):
        if isinstance(s, ast.ImportFrom) and s.level == 0 and (s.module or "").split(".")[0] == "tools":
            deps.setdefault(s.module, set()).update(a.name for a in s.names)
    return deps


def _app_tools_roots() -> dict[str, set[str]]:
    """The vendored app's own top-level `tools.*` imports -- what the live lens's header asks the tools ports for."""
    tree = ast.parse(_read(APP))
    roots: dict[str, set[str]] = {}
    for node in tree.body:
        if _tg._is_import_stmt(node):
            for mod, names in _vendored_tools_deps(node).items():
                if mod.split(".")[1] == "web":
                    continue  # the app itself
                roots.setdefault(mod, set()).update(names)
    return roots


def _port_tools_module(dotted: str, roots: set[str]) -> tuple[str, dict[str, set[str]], dict]:
    src = VENDOR.joinpath(*dotted.split(".")).with_suffix(".py")
    raw = _read(src)
    lines, tree = raw.split("\n"), ast.parse(raw)
    import_nodes = [n for n in tree.body if _tg._is_import_stmt(n)]
    header_names = set().union(*[_tg._bound_names(n) for n in import_nodes]) if import_nodes else set()
    selected, used = _closure(src, lines, tree, sorted(roots), header_names)
    header_parts: list[str] = []
    deps: dict[str, set[str]] = {}
    for node in import_nodes:
        targets = _import_targets(node)
        if any(isinstance(s, ast.ImportFrom) and s.module == "__future__" for s in targets):
            continue
        mods = [(s.module or "") if isinstance(s, ast.ImportFrom) else s.names[0].name for s in targets]
        vendored = any(m.split(".")[0] in VENDORED_ROOTS for m in mods)
        if vendored and not (_tg._bound_names(node) & used):
            continue  # a vendored import the closure never reads: not carried, so nothing has to provide it
        header_parts.append(_tg._segment(lines, node))
        for mod, names in _vendored_tools_deps(node).items():
            deps.setdefault(mod, set()).update(names)
    body = "\n\n\n".join(_tg._segment(lines, selected[k]) for k in sorted(selected))
    # Lazy imports inside the selected functions may reach further tools modules too.
    for k in selected:
        for s in ast.walk(selected[k]):
            if isinstance(s, ast.ImportFrom) and s.level == 0 and (s.module or "").split(".")[0] == "tools":
                deps.setdefault(s.module, set()).update(a.name for a in s.names)
    vendored_rel = Path(*dotted.split(".")).with_suffix(".py")
    out_rel = TOOLS_OUT.relative_to(ROOT) / f"{_tools_module_name(dotted)}.py"
    doc = ('"""GENERATED by scripts/port_mlb_sim_engine.py -- do not edit by hand (`--check` fails on a hand edit).\n\n'
           f"Closure of {sorted(roots)} in vendor/mlb_bettingv2/{vendored_rel.as_posix()}: {len(selected)} top-level\n"
           "statements copied verbatim, behind that module's own import statements; EDITS (import paths, the vendored\n"
           "file path) are listed in the generator.\n"
           '"""\n')
    text = doc + "from __future__ import annotations\n\n" + "\n".join(header_parts) + "\n\n\n" + body + "\n"
    text = _rewrite_imports(text, out_rel.as_posix())
    text = _vendored_file_edit(text, out_rel, vendored_rel)
    _tg._validate(out_rel.as_posix(), text)
    _check_no_vendored_imports(out_rel.as_posix(), text)
    report = {"source_lines": len(lines), "statements": len(selected), "body_lines": body.count("\n") + 1}
    return text, deps, report


def tools_outputs() -> tuple[dict[str, str], dict[str, dict]]:
    """{file name in TOOLS_OUT: text}, ported to a fixed point over the tools-to-tools imports."""
    wanted = _app_tools_roots()
    done: dict[str, set[str]] = {}
    texts: dict[str, str] = {}
    reports: dict[str, dict] = {}
    while True:
        pending = {m: n for m, n in wanted.items() if not n <= done.get(m, set())}
        if not pending:
            break
        for mod, names in sorted(pending.items()):
            roots = done.get(mod, set()) | names
            text, deps, report = _port_tools_module(mod, roots)
            name = f"{_tools_module_name(mod)}.py"
            owner = next((m for m in done if m != mod and _tools_module_name(m) == _tools_module_name(mod)), None)
            if owner:
                raise SystemExit(f"two tools modules flatten to {name}: {owner}, {mod}")
            texts[name], reports[mod], done[mod] = text, report, roots
            for dep, dep_names in deps.items():
                wanted.setdefault(dep, set()).update(dep_names)
    texts["__init__.py"] = ('"""Closure ports of the vendored vendor/mlb_bettingv2/tools/* helpers the MLB live lens imports.\n'
                            "GENERATED by scripts/port_mlb_sim_engine.py (lane mlb-sim-engine-native-p2).\n"
                            '"""\n')
    return texts, reports


# ---------------------------------------------------------------------------------------------------------- driver


def outputs() -> dict[Path, str]:
    out = {SIM_OUT / rel: text for rel, text in sim_outputs().items()}
    texts, _ = tools_outputs()
    out.update({TOOLS_OUT / name: text for name, text in texts.items()})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if not SIM_SRC.exists():
        print("vendor tree absent: nothing to generate from")
        return 0
    if args.report:
        sims = sim_outputs()
        print(f"sim_engine: {len(sims)} modules, {sum(t.count(chr(10)) for t in sims.values())} lines")
        for rel, text in sims.items():
            if "_VENDORED_FILE" in text:
                print(f"  vendored-file EDIT: sim_engine/{rel.as_posix()} ({text.count('Path(_VENDORED_FILE)')} site(s))")
        _, reports = tools_outputs()
        for mod, r in sorted(reports.items()):
            print(f"tools_port: {mod}: {r['statements']} statements / {r['body_lines']} of {r['source_lines']} lines")
        return 0
    files = outputs()
    if args.check:
        bad = [str(p.relative_to(ROOT)) for p, t in files.items()
               if not p.exists() or p.read_bytes().replace(b"\r\n", b"\n") != t.encode("utf-8")]
        extra = sorted(str(p.relative_to(ROOT)) for d in (SIM_OUT, TOOLS_OUT) if d.exists()
                       for p in d.rglob("*.py") if "__pycache__" not in p.parts and p not in files)
        print("CHECK OK" if not bad and not extra else f"CHECK FAILED differs={bad} unexpected={extra}")
        return 0 if not bad and not extra else 1
    for path, text in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    print(f"wrote {len(files)} files ({sum(t.count(chr(10)) for t in files.values())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
