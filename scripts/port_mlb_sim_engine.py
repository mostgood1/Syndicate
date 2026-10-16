"""Generator for syndicate/features/mlb/sim_engine/ and syndicate/features/mlb/native/tools/ -- the MLB engine off vendor.

Lanes mlb-sim-engine-native-p2 (user decision 2026-10-16: "Native engine package") and mlb-daily-sim-native-p3 ("Native
tools mirror"). Generates, from vendor/mlb_bettingv2/:

  * syndicate/features/mlb/sim_engine/ -- the WHOLE vendored package sim_engine/, every module copied verbatim;
  * syndicate/features/mlb/native/tools/<same tree> -- every vendored tools/ file the MLB daily sim, the refresh-worker's
    season-manifest launcher and the live lens reach (imports at any depth plus `"tools"`-rooted script launches,
    followed to a fixed point), each copied WHOLE and verbatim: they are scripts as much as modules. One copy each.
    tools/web/flask_frontend.py is not copied: its names come from the live lens's app slice
    (syndicate/features/mlb/live_lens_port/app_slice.py, scripts/port_mlb_live_lens.py), which roots them.

The only hand-written behaviour is EDITS, all mechanical, each counted:
  * VENDORED FILE: `Path(__file__)` -> `Path(_VENDORED_FILE)`, the module's path in the vendored tree, so every
    `.resolve().parents[k]` DATA root lands where it did in vendor/ (the copy sits at a different depth).
  * NATIVE SCRIPTS: a script path rooted at the repo root (`_ROOT_DIR / "tools" / ...`, `_ROOT / "tools" / ...`) is
    CODE, so it becomes `_NATIVE_ROOT / "tools" / ...` -- the native copy, never the vendored script. The same
    `_ROOT_DIR` stays the vendored root everywhere else (data, subprocess cwd).
  * SYS.PATH: each script's `if str(<root>) not in sys.path: sys.path.insert(0, str(<root>))` puts the SYNDICATE repo
    root on sys.path instead of the vendored one, so the rewritten imports resolve and a missed vendored import fails
    loudly instead of silently loading vendor.
  * IMPORT PATHS: `sim_engine...` -> `syndicate.features.mlb.sim_engine...`; `tools.web.flask_frontend` ->
    `syndicate.features.mlb.live_lens_port.app_slice`; `tools.<x>` -> `syndicate.features.mlb.native.tools.<x>`, in
    every import statement, indented ones included. (Text inside string literals is not an import statement and is
    left verbatim -- e.g. daily_update.py's Windows-only `.venv_x64` web-helper fallback.)
  * `sim_engine/data/roster_artifact.py`'s one absolute `from sim_engine.models import` becomes relative (one `models`).
`"tool": "tools/<x>.py"` provenance labels are DATA written into outputs and stay verbatim.

Usage:
  py -3 scripts/port_mlb_sim_engine.py            # write both trees
  py -3 scripts/port_mlb_sim_engine.py --check    # exit 1 if either tree on disk differs
  py -3 scripts/port_mlb_sim_engine.py --report   # sizes and every EDIT site
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

VENDOR = ROOT / "vendor" / "mlb_bettingv2"
SIM_SRC = VENDOR / "sim_engine"
SIM_OUT = ROOT / "syndicate" / "features" / "mlb" / "sim_engine"
NATIVE_OUT = ROOT / "syndicate" / "features" / "mlb" / "native"
NATIVE_SIM = "syndicate.features.mlb.sim_engine"
NATIVE_TOOLS = "syndicate.features.mlb.native.tools"
WEB_MODULE = "tools.web.flask_frontend"
WEB_SLICE = "syndicate.features.mlb.live_lens_port.app_slice"
#: The vendored app (its top-level `tools.*` imports are what the live lens's header asks for).
APP = VENDOR / "tools" / "web" / "flask_frontend.py"
#: Entry points that RUN vendored tools today: the daily sim (scripts/run_mlb_daily_sim_job.py) and the refresh-worker's
#: season-manifest launcher (scripts/run_refresh_worker.py).
ENTRY_SCRIPTS = ["tools/daily_update.py", "tools/eval/build_season_betting_cards_manifest.py"]
VENDORED_ROOTS = {"sim_engine", "tools"}

#: Per-file EDITS beyond the mechanical ones, for sim_engine: {path relative to sim_engine/: [(anchor, replacement)]}.
SIM_EDITS: dict[str, list[tuple[str, str]]] = {
    "data/roster_artifact.py": [
        ("from sim_engine.models import (\n",
         "from ..models import (  # EDIT: relative, as every other intra-package import is (one `models`, not two)\n"),
    ],
}

#: Per-file EDITS for the tools copies, applied AFTER the mechanical ones: {path relative to vendor/mlb_bettingv2: [...]}.
TOOLS_EDITS: dict[str, list[tuple[str, str]]] = {
    # A provenance LABEL written into daily_summary_<date>_profile_bundle.json. `daily_update_py` is now the native
    # script (NATIVE SCRIPTS rule), which `_rel` cannot make relative to the vendored `_ROOT`, so it would record an
    # absolute path where production records "tools/daily_update.py" -- the same relative path the native tree mirrors.
    # Measured by scripts/mlb_daily_sim_parity.py 2026-10-16 as the ONE leaf beyond the noise floor; no reader exists.
    "tools/daily_update_multi_profile.py": [
        ('"daily_update_tool": _rel(daily_update_py),',
         '"daily_update_tool": _rel(_ROOT / "tools" / "daily_update.py"),  # EDIT: the label production records'),
    ],
}

_IMPORT_RE = re.compile(r"^(?P<indent>[ \t]*)(?P<kw>from|import)[ \t]+(?P<mod>(?:sim_engine|tools)(?:\.[A-Za-z0-9_]+)*)\b",
                        re.M)
_SCRIPT_JOIN_RE = re.compile(r"\b(?:_ROOT_DIR|_ROOT|REPO_ROOT)(?P<sep>\s*/\s*)\"tools\"")
_SCRIPT_TARGET_RE = re.compile(r"\b(?:_ROOT_DIR|_ROOT|REPO_ROOT)\s*/\s*\"tools\"((?:\s*/\s*\"[A-Za-z0-9_.]+\")+)")
_SYS_PATH_RE = re.compile(r"^(?P<i>[ \t]*)if str\((?P<r>_ROOT_DIR|_ROOT|REPO_ROOT)\) not in sys\.path:\n"
                          r"(?P=i)[ \t]+sys\.path\.insert\(0, str\((?P=r)\)\)\n", re.M)


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")


def _rewrite_imports(text: str, where: str) -> str:
    def sub(m: re.Match) -> str:
        mod, kw = m.group("mod"), m.group("kw")
        if kw != "from":
            raise SystemExit(f"[{where}] `import {mod}` binds a vendored top-level name; only `from ... import` is rewritten")
        if mod.split(".")[0] == "sim_engine":
            return f"{m.group('indent')}from {NATIVE_SIM}{mod[len('sim_engine'):]}"
        if mod == WEB_MODULE:
            return f"{m.group('indent')}from {WEB_SLICE}"
        if mod in ("tools", "tools.web"):
            raise SystemExit(f"[{where}] `from {mod} import ...` -- a package-level import the mapping does not cover")
        return f"{m.group('indent')}from {NATIVE_TOOLS}{mod[len('tools'):]}"

    return _IMPORT_RE.sub(sub, text)


def _insert_header(text: str, lines_to_insert: list[str]) -> str:
    """Insert lines after the module docstring and `from __future__` imports (before anything that could use them)."""
    if not lines_to_insert:
        return text
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
    return "\n".join(lines[:insert_after] + lines_to_insert + lines[insert_after:])


def _path_line(name: str, out_rel: Path, target: tuple[str, ...], *, as_str: bool, why: str) -> str:
    up = len(out_rel.parts) - 1  # parents[up] of the copy is the Syndicate repo root
    expr = f"__import__(\"pathlib\").Path(__file__).resolve().parents[{up}]"
    if target:
        expr += ".joinpath(" + ", ".join(repr(p) for p in target) + ")"
    return f"{name} = {'str(' + expr + ')' if as_str else expr}  # EDIT: {why}"


def _edit_module(text: str, out_rel: Path, vendored_rel: Path, report: dict) -> str:
    """The mechanical EDITS, in an order where none can see another's output."""
    header: list[str] = []
    # NATIVE SCRIPTS (before VENDORED FILE, which leaves _ROOT_DIR / _ROOT on the vendored root).
    joins = len(_SCRIPT_JOIN_RE.findall(text))
    if joins:
        for m in _SCRIPT_TARGET_RE.finditer(text):
            parts = tuple(re.findall(r"\"([A-Za-z0-9_.]+)\"", m.group(1)))
            report.setdefault("script_targets", []).append((vendored_rel.as_posix(), "tools/" + "/".join(parts)))
        text = _SCRIPT_JOIN_RE.sub(lambda m: f"_NATIVE_ROOT{m.group('sep')}\"tools\"", text)
        header.append(_path_line("_NATIVE_ROOT", out_rel, ("syndicate", "features", "mlb", "native"), as_str=False,
                                 why="CODE root -- vendored `tools` scripts run from their native copies"))
        report["script_joins"] = report.get("script_joins", 0) + joins
    # SYS.PATH
    n_sys = len(_SYS_PATH_RE.findall(text))
    if n_sys:
        if n_sys != 1:
            raise SystemExit(f"[{out_rel}] {n_sys} sys.path blocks; the rule expects at most one per file")
        text = _SYS_PATH_RE.sub(lambda m: (f"{m.group('i')}if _SYNDICATE_ROOT not in sys.path:\n"
                                           f"{m.group('i')}    sys.path.insert(0, _SYNDICATE_ROOT)\n"), text)
        header.append(_path_line("_SYNDICATE_ROOT", out_rel, (), as_str=True,
                                 why="the Syndicate repo root goes on sys.path, never the vendored one"))
        report["sys_path"] = report.get("sys_path", 0) + 1
    if re.search(r"^\s*sys\.path\.(insert|append)\(", text, re.M) and "_SYNDICATE_ROOT" not in text:
        raise SystemExit(f"[{out_rel}] a sys.path edit outside the known two-line shape")
    # IMPORT PATHS
    text = _rewrite_imports(text, out_rel.as_posix())
    # VENDORED FILE
    n_file = text.count("Path(__file__)")
    if n_file:
        if text.count("__file__") != n_file:
            raise SystemExit(f"[{out_rel}] __file__ used outside Path(__file__); extend the EDIT rule deliberately")
        text = text.replace("Path(__file__)", "Path(_VENDORED_FILE)")
        header.insert(0, _path_line("_VENDORED_FILE", out_rel, ("vendor", "mlb_bettingv2", *vendored_rel.parts),
                                    as_str=True, why="this module's path in vendor/, so every DATA root resolves there"))
        report["vendored_file"] = report.get("vendored_file", 0) + n_file
    text = _insert_header(text, header)
    compile(text, str(out_rel), "exec")
    _check_no_vendored_imports(out_rel.as_posix(), text)
    return text


def _check_no_vendored_imports(name: str, text: str) -> None:
    left = [m.group(0).strip() for m in _IMPORT_RE.finditer(text)]
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in VENDORED_ROOTS:
            left.append(node.module)
        elif isinstance(node, ast.Import):
            left += [a.name for a in node.names if a.name.split(".")[0] in VENDORED_ROOTS]
    if left:
        raise SystemExit(f"[{name}] vendored imports left: {left}")


# ---------------------------------------------------------------------------------------------------------- sim_engine


def sim_outputs(report: dict | None = None) -> dict[Path, str]:
    """{path relative to SIM_OUT: text} -- every module of the vendored package."""
    report = {} if report is None else report
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
        out[rel] = _edit_module(text, SIM_OUT.relative_to(ROOT) / rel, Path("sim_engine") / rel, report)
    missing = set(SIM_EDITS) - seen_edits
    if missing:
        raise SystemExit(f"SIM_EDITS name files that were not generated: {sorted(missing)}")
    return out


# ------------------------------------------------------------------------------------------------------------ tools


def _module_file(dotted: str) -> Path | None:
    p = VENDOR.joinpath(*dotted.split("."))
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    return p / "__init__.py" if (p / "__init__.py").is_file() else None


def _tools_refs(src: Path) -> set[Path]:
    """Vendored tools files `src` imports (any depth, any form) or launches by a `"tools"`-rooted path."""
    text = _read(src)
    refs: set[Path] = set()
    for node in ast.walk(ast.parse(text)):
        mods: list[str] = []
        if isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] == "tools":
            mods.append(node.module)
            mods += [f"{node.module}.{a.name}" for a in node.names]  # `from tools.eval import some_module`
        elif isinstance(node, ast.Import):
            mods += [a.name for a in node.names if a.name.split(".")[0] == "tools"]
        for mod in mods:
            if mod == WEB_MODULE or mod.startswith(WEB_MODULE + "."):
                continue
            f = _module_file(mod)
            if f is not None:
                refs.add(f)
    for m in _SCRIPT_TARGET_RE.finditer(text):
        parts = re.findall(r"\"([A-Za-z0-9_.]+)\"", m.group(1))
        f = VENDOR.joinpath("tools", *parts)
        if parts and parts[-1].endswith(".py"):
            if not f.is_file():
                raise SystemExit(f"[{src.relative_to(VENDOR)}] launches tools/{'/'.join(parts)}, which does not exist")
            refs.add(f)
    return refs


def tools_reach() -> list[Path]:
    seeds = {VENDOR / s for s in ENTRY_SCRIPTS} | _tools_refs(APP)
    seen: set[Path] = set()
    stack = sorted(seeds)
    while stack:
        f = stack.pop()
        if f in seen or f == APP:
            continue
        seen.add(f)
        stack.extend(sorted(_tools_refs(f) - seen))
    return sorted(seen)


def tools_outputs(report: dict | None = None) -> dict[Path, str]:
    """{path relative to NATIVE_OUT: text}: the reached tools files, whole, plus a docstring `__init__` per package."""
    report = {} if report is None else report
    out: dict[Path, str] = {}
    for src in tools_reach():
        vendored_rel = src.relative_to(VENDOR)  # tools/...
        out_rel = NATIVE_OUT.relative_to(ROOT) / vendored_rel
        text = _edit_module(_read(src), out_rel, vendored_rel, report)
        for old, new in TOOLS_EDITS.get(vendored_rel.as_posix(), []):  # AFTER the mechanical pass, which they must outlive
            if text.count(old) != 1:
                raise SystemExit(f"[{vendored_rel.as_posix()}] TOOLS_EDITS anchor matched {text.count(old)}x: {old!r}")
            text = text.replace(old, new)
            report.setdefault("tools_edits", []).append(vendored_rel.as_posix())
        out[vendored_rel] = text
        report.setdefault("tools_lines", {})[vendored_rel.as_posix()] = _read(src).count("\n") + 1
    missing = {k for k in TOOLS_EDITS} - set(report.get("tools_edits", []))
    if missing:
        raise SystemExit(f"TOOLS_EDITS name files that were not generated: {sorted(missing)}")
    packages = {Path()} | {p for rel in list(out) for p in rel.parents if p != Path()}
    for pkg in sorted(packages):
        init = pkg / "__init__.py"
        if init not in out:
            vendored_init = VENDOR / init
            out[init] = (_edit_module(_read(vendored_init), NATIVE_OUT.relative_to(ROOT) / init, init, report)
                         if vendored_init.is_file() and pkg != Path() else
                         '"""Native copies of the vendored vendor/mlb_bettingv2/' + (pkg.as_posix() + "/" if pkg != Path() else "")
                         + ' files the MLB daily sim and live lens reach.\nGENERATED by scripts/port_mlb_sim_engine.py '
                           '(lane mlb-daily-sim-native-p3).\n"""\n')
    return out


# ---------------------------------------------------------------------------------------------------------- driver


def outputs(report: dict | None = None) -> dict[Path, str]:
    out = {SIM_OUT / rel: text for rel, text in sim_outputs(report).items()}
    out.update({NATIVE_OUT / rel: text for rel, text in tools_outputs(report).items()})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    if not SIM_SRC.exists():
        print("vendor tree absent: nothing to generate from")
        return 0
    report: dict = {}
    files = outputs(report)
    if args.report:
        tl = report.get("tools_lines", {})
        print(f"sim_engine: {sum(1 for p in files if SIM_OUT in p.parents)} modules; "
              f"native tools: {len(tl)} files / {sum(tl.values())} lines")
        for rel, n in sorted(tl.items(), key=lambda kv: -kv[1]):
            print(f"  {n:6d}  {rel}")
        print(f"EDIT counts: vendored-file {report.get('vendored_file', 0)}, script joins {report.get('script_joins', 0)}, "
              f"sys.path {report.get('sys_path', 0)}")
        for src, target in report.get("script_targets", []):
            print(f"  script launch: {src} -> native {target}")
        return 0
    if args.check:
        bad = [str(p.relative_to(ROOT)) for p, t in files.items()
               if not p.exists() or p.read_bytes().replace(b"\r\n", b"\n") != t.encode("utf-8")]
        extra = sorted(str(p.relative_to(ROOT)) for d in (SIM_OUT, NATIVE_OUT) if d.exists()
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
