"""NBA ARM RETIRED 2026-10-19 (lane nba-vendor-deletion-prep): syndicate/features/nba/live_tick/ is frozen source (syndicate/features/basketball_engine/FROZEN_FROM_VENDOR.md).
This generator now produces the WNBA package only.

Generator for syndicate/features/<league>/live_tick/ -- Syndicate's port of the vendored basketball live-lens tick.

Lane nba-live-tick-native (2026-10-12; WNBA added the same day at the user's request). `syndicate/features/<league>/
live_lens.py` used to import the whole vendored Flask app (`vendor/<league>_betting_repo/app.py`, 45-47k lines) on
every live-lens loop tick to reach `_live_lens_tick_payload`. This script extracts that function and EVERYTHING it
reaches into a Syndicate-owned package:

  * from app.py: the tick, the four routes it calls in-process through `app.test_client()`
    (`/api/live_lens_tuning`, `/api/live_lines`, `/api/live_pbp_stats`, `/api/live_player_lens`), and their closures;
  * from the vendored `<league>_betting` package: the closure of every name the generated code imports from it
    (`odds_api`, `teams`, `player_names`, `odds_bovada`, and for WNBA `league`), solved to a fixed point;
  * from `tools/daily_live_lens_audit.py`: the three helpers `_ll_enrich_signal_tags` loads.

METHOD. The closure is computed scope-correctly with `symtable` (a local variable named like a module function is NOT
a reference to it), and the top-level statements that define closure names are copied VERBATIM in source order.
  * app.py's imports are replaced by a hand-written header (LEAGUES below), which also carries the data-root
    block -- the only place the port's behaviour is written by hand.
  * A package module keeps its own top-level imports verbatim; a relative import keeps only the names the
    closure uses, and those names become that sibling module's roots.
  * Inside copied functions, every `from <league>_betting.<mod> import` becomes `from .<mod> import`, and the
    audit-module loader is replaced (AUDIT_LOADER_*).
Every module is validated before it is written: each global a function reads must be bound, and no import of the
vendored app, package or tools dir may remain. `--check` regenerates in memory and fails if the package on disk
differs, so a hand edit to a generated file is caught.

Usage:
  py -3 scripts/port_basketball_live_tick.py --league nba            # write syndicate/features/nba/live_tick/
  py -3 scripts/port_basketball_live_tick.py --league all --check    # exit 1 if any package differs
"""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import re
import symtable
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TICK_ROOTS = [
    "_live_lens_tick_payload",
    # Reached through app.test_client() inside the tick -- invisible to a name closure, so listed explicitly.
    "api_live_lens_tuning",
    "api_live_lines",
    "api_live_pbp_stats",
    "api_live_player_lens",
]
VENDORED_IMPORT_ROOTS = {"vendor", "nba_betting", "wnba_betting", "daily_live_lens_audit"}
AUDIT_MODULE = "live_lens_audit"
AUDIT_ROOTS = ["_live_stat_key", "_flag_adjustments", "_derive_tags"]

#: Names the VENDORED code reads but never binds. Copied as-is so the port raises exactly where the vendored code
#: raises; each one is a vendored defect, kept for parity and listed here so it is a decision, not an accident.
#: Names the VENDORED source reads but never binds. The closure pass reads the vendored source, so it tolerates them;
#: the generated text must not need them unless --without-fixes (each one is cured by a FIXES entry below).
KNOWN_UNDEFINED: dict[str, set[str]] = {"wnba": {"current_last_updates"}}

#: DELIBERATE departures from the vendored code: defects fixed in the port. Each is an anchored edit that must match
#: exactly once. Everything else is copied verbatim, so `--without-fixes` regenerates the parity-proven text, and
#: tests/test_basketball_live_tick_fixes.py pins that the two differ by exactly these edits.
FIXES: dict[str, list[tuple[str, str, str]]] = {
    "wnba": [
        (
            # User decision 2026-10-12 ("fix the wnba registry bug too"). The WNBA copy of the nested
            # `_live_oddsapi_player_props_for_game._update_registry_bucket` lost its `current_last_updates` keyword
            # parameter (the NBA copy has it) while its body reads that name and all three callers pass it. Every
            # call raised TypeError, the enclosing `try` swallowed it, and the WNBA live-props registry
            # (processed/live_lens_registry/oddsapi_props_<date>_<event>.json: first/last seen, first/last line and
            # price, observations) was never written, so those `out[...]` maps were always absent.
            "wnba-registry-current-last-updates",
            "        current_prices: dict[str, Any],\n        default_observed_at: Any,\n    ) -> None:",
            "        current_prices: dict[str, Any],\n        current_last_updates: dict[str, Any],  # FIX wnba-registry-current-last-updates\n        default_observed_at: Any,\n    ) -> None:",
        ),
    ],
}
APPLY_FIXES = True

_HEADER_COMMON = '''\
from typing import Any, Callable, Dict, List, Optional, Tuple
from functools import lru_cache

import pandas as pd
import numpy as np
import math
import json
import os
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request
import sys
import time
import threading
import re
import requests
from pathlib import Path
import traceback

from .odds_api import (
    OddsApiConfig as _OddsApiConfig,
    list_events_current as _oddsapi_list_events_current,
    discover_event_market_keys as _oddsapi_discover_event_market_keys,
    fetch_event_odds_current as _oddsapi_fetch_event_odds_current,
    normalize_bookmaker_key as _normalize_bookmaker_key,
    resolve_player_prop_bookmakers as _resolve_player_prop_bookmakers,
)
from .teams import to_tricode as _to_tricode
'''

_HEADER_TAIL = '''\
DATA_DIR = _DATA_ROOT_P
DATA_PROCESSED_DIR = DATA_DIR / "processed"
# EDIT: the vendored "repo-committed data" dir (<vendored repo>/data) is the data root itself. Every reader of it
# (_live_lens_artifact_candidates, _live_latest_adjustments_optimized_path, _load_smart_sim_files_for_date)
# de-duplicates against the active dir, and the vendored dir on the fleet holds none of the files they look for
# (live_lens_*, smart_sim_*; checked 2026-10-12), so the output is unchanged.
REPO_DATA_DIR = DATA_DIR
REPO_DATA_PROCESSED_DIR = REPO_DATA_DIR / "processed"

# EDIT: a private Flask app carrying ONLY the four routes the tick calls through `app.test_client()`. The vendored
# app's `before_request` minimal-UI allowlist admits all four, so it is not ported.
app = Flask(__name__)
'''

_WNBA_DATA_ROOT = '''from .league import LEAGUE, season_label_from_date

# ---- Data root (EDIT: replaces the vendored BASE_DIR / wnba_betting.config block) ----
# Vendored: DATA_DIR = wnba_betting.config.paths.data_root = $WNBA_BETTING_DATA_ROOT, else the legacy
# $NBA_BETTING_DATA_ROOT, else /opt/render/project/data when it is a directory, else <vendored repo>/data. The same
# order here, with Syndicate's own WNBA source data dir as the last fallback. The vendored import-time
# `reconcile_repo_data_to_active()` copy is NOT run.
_DATA_ROOT = (os.environ.get(getattr(LEAGUE, "data_root_env", "WNBA_BETTING_DATA_ROOT")) or "").strip()
_CONFIG_DATA_ROOT_ENV = (os.environ.get(LEAGUE.data_root_env) or os.environ.get(LEAGUE.legacy_data_root_env) or "").strip()
if _CONFIG_DATA_ROOT_ENV:
    _DATA_ROOT_P = Path(_CONFIG_DATA_ROOT_ENV)
elif Path("/opt/render/project/data").is_dir():
    _DATA_ROOT_P = Path("/opt/render/project/data")
else:
    _DATA_ROOT_P = Path(__file__).resolve().parents[4] / "data" / "wnba_source" / "data"

# EDIT: the vendored repo root. Two WNBA closure functions read it: `_find_predictions_for_date` (a legacy
# <repo>/predictions_<date>.csv) and `_load_team_maps` (<repo>/web/assets/teams_wnba.json). Neither file exists in
# the vendored tree (checked locally and on the fleet 2026-10-12), so both reads take their missing-file path; a
# directory that does not exist keeps that path without pointing at the vendor tree.
BASE_DIR = Path(__file__).resolve().parent / "_no_vendored_repo_root"
WEB_DIR = BASE_DIR / "web"
# NOTE (WNBA only): the vendored `game_odds_` / `predictions_` / `closing_lines_` / `odds_` / `market_` and
# `smart_sim_` readers prefer <vendored repo>/data/processed. Every such file in the vendored tree is dated
# 2026-05-25..05-28 or 2026-10-01 (checked 2026-10-12); a live tick reads the slate in progress, so for any later
# date the data root is the only place either arm can find them.
'''

_HEADER_NAMES_COMMON = {
    "Any", "Callable", "Dict", "List", "Optional", "Tuple", "lru_cache", "pd", "np", "math", "json", "os",
    "datetime", "timedelta", "timezone", "Flask", "jsonify", "request", "sys", "time", "threading", "re",
    "requests", "Path", "traceback", "_OddsApiConfig", "_oddsapi_list_events_current",
    "_oddsapi_discover_event_market_keys", "_oddsapi_fetch_event_odds_current", "_normalize_bookmaker_key",
    "_resolve_player_prop_bookmakers", "_to_tricode", "_DATA_ROOT", "_DATA_ROOT_P", "DATA_DIR",
    "DATA_PROCESSED_DIR", "REPO_DATA_DIR", "REPO_DATA_PROCESSED_DIR", "app",
    # Only reachable through the replaced data-root block / Flask(static_folder=WEB_DIR):
    "BASE_DIR", "WEB_DIR", "_PathEarly", "_paths", "_reconcile_repo_data_to_active",
}


@dataclass(frozen=True)
class League:
    code: str
    pkg: str
    header: str
    header_names: frozenset

    @property
    def vendor(self) -> Path:
        return ROOT / "vendor" / f"{self.code}_betting_repo"

    @property
    def out(self) -> Path:
        return ROOT / "syndicate" / "features" / self.code / "live_tick"


LEAGUES = {
    "wnba": League("wnba", "wnba_betting", _HEADER_COMMON + _WNBA_DATA_ROOT + _HEADER_TAIL,
                   frozenset(_HEADER_NAMES_COMMON | {"LEAGUE", "season_label_from_date", "_CONFIG_DATA_ROOT_ENV"})),
}

# The vendored loader puts <vendored repo>/tools on sys.path and imports the audit script from there.
AUDIT_LOADER_RE = re.compile(
    r"(?P<i>[ ]+)import sys as _sys\n\n"
    r"(?P=i)tools_dir = BASE_DIR / \"tools\"\n"
    r"(?P=i)if str\(tools_dir\) not in _sys\.path:\n"
    r"(?P=i)    _sys\.path\.insert\(0, str\(tools_dir\)\)\n"
    r"(?P=i)import daily_live_lens_audit as _audit  # type: ignore\n"
)
AUDIT_LOADER_NEW = "\\g<i># EDIT: the vendored tools/daily_live_lens_audit.py, ported as .live_lens_audit (closure only).\n\\g<i>from . import live_lens_audit as _audit\n"


def _segment(lines: list[str], node: ast.stmt) -> str:
    start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
    return "\n".join(lines[start - 1 : node.end_lineno])


def _module_refs(seg: str, own: str | None) -> set[str]:
    """Every name `seg` (one top-level statement) reads from module scope."""
    out: set[str] = set()

    def walk(tbl: symtable.SymbolTable) -> None:
        for sym in tbl.get_symbols():
            name = sym.get_name()
            if tbl.get_type() == "module":
                if sym.is_referenced() and name != own:
                    out.add(name)
            elif sym.is_global() or sym.is_declared_global():
                out.add(name)
        for child in tbl.get_children():
            walk(child)

    walk(symtable.symtable(textwrap.dedent(seg), "<seg>", "exec"))
    return out


def _bound_names(node: ast.stmt) -> set[str]:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {node.name}
    out: set[str] = set()
    if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
            out |= {n.id for n in ast.walk(target) if isinstance(n, ast.Name)}
    elif isinstance(node, (ast.Import, ast.ImportFrom)):
        out |= {(a.asname or a.name).split(".")[0] for a in node.names}
    elif isinstance(node, (ast.Try, ast.If)):
        for sub in ast.walk(node):
            if sub is not node and isinstance(sub, (ast.Assign, ast.AnnAssign, ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)):
                out |= _bound_names(sub)
    return out


def _is_import_stmt(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.Try):
        return all(isinstance(s, (ast.Import, ast.ImportFrom)) for s in node.body)
    return False


def _closure(src: Path, roots: list[str], header_names: set[str], undefined: frozenset = frozenset()) -> tuple[list[str], dict[int, ast.stmt], set[str], ast.Module]:
    raw = src.read_text(encoding="utf-8-sig")
    lines = raw.split("\n")
    tree = ast.parse(raw)
    binders: dict[str, list[ast.stmt]] = {}
    for node in tree.body:
        if _is_import_stmt(node):
            continue
        for name in _bound_names(node):
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
            if hasattr(builtins, name) or name in {"__file__", "__name__"} or name in undefined:
                continue
            raise SystemExit(f"[{src.name}] unresolved module name {name!r}")
        if isinstance(nodes[-1], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes = [nodes[-1]]  # the LAST def wins at import time
        for node in nodes:
            if isinstance(node, (ast.Try, ast.If)):
                raise SystemExit(f"[{src.name}] {name!r} is bound by a try/if at line {node.lineno}: put it in the header")
            selected[node.lineno] = node
            own = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            stack.extend(_module_refs(_segment(lines, node), own))
    return lines, selected, used_header, tree


def _rewrite_body(body: str, league: League) -> str:
    body = re.sub(rf"\bfrom {league.pkg}\.(\w+) import ", r"from .\1 import ", body)
    return AUDIT_LOADER_RE.sub(AUDIT_LOADER_NEW, body)


def _relative_demands(text: str) -> dict[str, set[str]]:
    """{sibling module: names} for every `from .<mod> import ...` in generated text (any depth)."""
    out: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:
                out.setdefault(node.module, set()).update(a.name for a in node.names)
            else:
                for a in node.names:
                    out.setdefault(a.name, set())
    return out


def _doc(src: Path, n: int) -> str:
    sha = hashlib.sha256(src.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]  # LF-normalised: a Windows (CRLF) and a Linux checkout must stamp the same hash, or --check fails on one of them
    return (
        '"""GENERATED by scripts/port_basketball_live_tick.py -- do not edit by hand (`--check` fails on a hand edit).\n\n'
        f"Source: {src.relative_to(ROOT).as_posix()} (sha256 {sha}...), {n} top-level statements, copied verbatim\n"
        "except for the import header, the rewrites and the FIXES listed in the generator.\n"
        '"""\n'
    )


def _future(tree: ast.Module) -> str:
    has = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body)
    return "from __future__ import annotations\n\n" if has else ""


def generate_tick(league: League) -> str:
    src = league.vendor / "app.py"
    lines, selected, _used, tree = _closure(src, TICK_ROOTS, set(league.header_names), frozenset(KNOWN_UNDEFINED.get(league.code, ())))
    body = "\n\n\n".join(_segment(lines, selected[k]) for k in sorted(selected))
    body = _rewrite_body(body, league)
    if APPLY_FIXES:
        for name, old, new in FIXES.get(league.code, []):
            if body.count(old) != 1:
                raise SystemExit(f"[{league.code}] FIX {name}: anchor matched {body.count(old)}x (vendored source changed?)")
            body = body.replace(old, new)
    return _doc(src, len(selected)) + _future(tree) + league.header + "\n\n" + body + "\n"


def generate_package_module(league: League, src: Path, roots: set[str]) -> str:
    raw_tree = ast.parse(src.read_text(encoding="utf-8-sig"))
    raw_lines = src.read_text(encoding="utf-8-sig").split("\n")
    import_stmts = [n for n in raw_tree.body if _is_import_stmt(n) and not (isinstance(n, ast.ImportFrom) and n.module == "__future__")]
    header_names = set().union(*[_bound_names(n) for n in import_stmts]) if import_stmts else set()
    lines, selected, used_header, tree = _closure(src, sorted(roots), header_names)
    header_parts: list[str] = []
    for node in import_stmts:
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            keep = [a for a in node.names if (a.asname or a.name) in used_header]
            if keep:  # EDIT: a relative import keeps only what the closure uses (the rest may not be ported)
                header_parts.append(f"from {'.' * node.level}{node.module or ''} import " + ", ".join(
                    a.name + (f" as {a.asname}" if a.asname else "") for a in keep))
            continue
        header_parts.append(_segment(raw_lines, node))
    body = "\n\n\n".join(_segment(lines, selected[k]) for k in sorted(selected))
    body = _rewrite_body(body, league)
    return _doc(src, len(selected)) + _future(tree) + "\n".join(header_parts) + "\n\n\n" + body + "\n"


def _validate(out_name: str, text: str, undefined: frozenset = frozenset()) -> None:
    """Every global a generated function reads is bound, and nothing vendored is imported."""
    tree = ast.parse(text)
    bound: set[str] = set()
    for node in tree.body:
        bound |= _bound_names(node)
    missing: set[str] = set()

    def walk(tbl: symtable.SymbolTable) -> None:
        for sym in tbl.get_symbols():
            name = sym.get_name()
            if tbl.get_type() == "module":
                hit = sym.is_referenced() and not sym.is_assigned() and not sym.is_imported()
            else:
                hit = (sym.is_global() or sym.is_declared_global()) and sym.is_referenced()
            if hit and name not in bound and not hasattr(builtins, name) and name not in {"__file__", "__name__"} and name not in undefined:
                missing.add(f"{tbl.get_name()}:{name}")
        for child in tbl.get_children():
            walk(child)

    walk(symtable.symtable(text, out_name, "exec"))
    if missing:
        raise SystemExit(f"[{out_name}] unbound globals in generated module: {sorted(missing)}")
    vendored = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            vendored += [a.name for a in node.names if a.name.split(".")[0] in VENDORED_IMPORT_ROOTS]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and (node.module or "").split(".")[0] in VENDORED_IMPORT_ROOTS:
            vendored.append(node.module)
    if vendored:
        raise SystemExit(f"[{out_name}] vendored imports left in generated module: {vendored}")


def generate_league(league: League) -> dict[str, str]:
    outputs: dict[str, str] = {"tick.py": generate_tick(league)}
    sources = {AUDIT_MODULE: league.vendor / "tools" / "daily_live_lens_audit.py"}
    demands: dict[str, set[str]] = {AUDIT_MODULE: set(AUDIT_ROOTS)}
    done: dict[str, frozenset] = {}
    pending = [outputs["tick.py"]]
    while True:
        for text in pending:
            for mod, names in _relative_demands(text).items():
                demands.setdefault(mod, set()).update(names)
        pending = []
        todo = [m for m in demands if done.get(m) != frozenset(demands[m])]
        if not todo:
            break
        for mod in todo:
            src = sources.get(mod) or (league.vendor / "src" / league.pkg / f"{mod}.py")
            if not src.exists():
                raise SystemExit(f"[{league.code}] generated code imports .{mod}, and {src} does not exist")
            text = generate_package_module(league, src, demands[mod])
            outputs[f"{mod}.py"] = text
            done[mod] = frozenset(demands[mod])
            pending.append(text)
    for name, text in outputs.items():
        _validate(f"{league.code}/{name}", text, frozenset() if APPLY_FIXES else frozenset(KNOWN_UNDEFINED.get(league.code, ())))
    outputs["__init__.py"] = (
        f'"""Syndicate port of the vendored {league.code.upper()} live-lens tick (lane nba-live-tick-native, 2026-10-12).\n\n'
        "GENERATED by scripts/port_basketball_live_tick.py. `tick._live_lens_tick_payload(date)` is the vendored\n"
        f"`vendor/{league.code}_betting_repo/app.py::_live_lens_tick_payload`, with its closure, the four routes it calls through\n"
        f"`app.test_client()`, and the `{league.pkg}` package / `tools/daily_live_lens_audit.py` code it imports. Parity with\n"
        "the vendored function: scripts/basketball_live_tick_parity.py and tests/test_basketball_live_tick_parity.py.\n"
        '"""\n'
    )
    return outputs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", choices=("wnba", "all"), default="all")  # NBA arm retired, lane nba-vendor-deletion-prep
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--without-fixes", action="store_true", help="the parity-proven verbatim text (FIXES off); needs --print-dir")
    ap.add_argument("--print-dir", help="write the packages under <dir>/<league>/ instead of the repo")
    args = ap.parse_args()
    global APPLY_FIXES
    if args.without_fixes:
        if not args.print_dir:
            ap.error("--without-fixes needs --print-dir (the repo always carries the fixed port)")
        APPLY_FIXES = False
    rc = 0
    for code in (("wnba",) if args.league == "all" else (args.league,)):
        league = LEAGUES[code]
        if not (league.vendor / "app.py").exists():
            print(f"{code}: vendor tree absent, nothing to generate from")
            continue
        outputs = generate_league(league)
        for name, text in sorted(outputs.items()):
            print(f"{code:4s} {name:22s} {text.count(chr(10)):6d} lines")
        if args.check:
            # A Windows checkout may be CRLF; the generated text is LF.
            bad = [n for n, t in outputs.items() if not (league.out / n).exists()
                   or (league.out / n).read_bytes().replace(b"\r\n", b"\n") != t.encode("utf-8")]
            extra = sorted(p.name for p in league.out.glob("*.py") if p.name not in outputs) if league.out.exists() else []
            if bad or extra:
                print(f"{code}: CHECK FAILED: differs={sorted(bad)} unexpected={extra}")
                rc = 1
            else:
                print(f"{code}: CHECK OK")
            continue
        out_dir = Path(args.print_dir) / code if args.print_dir else league.out
        out_dir.mkdir(parents=True, exist_ok=True)
        for stale in out_dir.glob("*.py"):
            if stale.name not in outputs:
                stale.unlink()
        for name, text in outputs.items():
            (out_dir / name).write_bytes(text.encode("utf-8"))
        print(f"{code}: wrote {len(outputs)} files to {out_dir}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
