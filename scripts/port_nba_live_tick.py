"""Generator for syndicate/features/nba/live_tick/ -- the Syndicate port of the vendored NBA live-lens tick.

Lane nba-live-tick-native (2026-10-12). `syndicate/features/nba/live_lens.py` used to import the 45,799-line vendored
Flask app (`vendor/nba_betting_repo/app.py`) on every live-lens loop tick to reach `_live_lens_tick_payload`. This
script extracts that function and EVERYTHING it reaches into a Syndicate-owned package:

  * from app.py: the tick, the four routes it calls in-process through `app.test_client()`
    (`/api/live_lens_tuning`, `/api/live_lines`, `/api/live_pbp_stats`, `/api/live_player_lens`), and their closures;
  * from vendor/nba_betting_repo/src/nba_betting: the closures it imports from `odds_api`, `teams`, `player_names`
    and `odds_bovada`;
  * from vendor/nba_betting_repo/tools/daily_live_lens_audit.py: the three helpers `_ll_enrich_signal_tags` loads.

METHOD. The closure is computed scope-correctly with `symtable` (a local variable named like a module function is NOT
a reference to it), the top-level statements that define closure names are copied VERBATIM in source order, and the
module imports are replaced by a hand-written header. The exact edits are listed in EDITS and HEADERS below; every
edit is anchored and must match exactly once. `--check` regenerates in memory and fails if the package on disk
differs, so a hand edit to a generated file is caught.

The generated package is validated before it is written: every global a generated function reads must be bound
in its module (or be a builtin).

Usage:
  py -3 scripts/port_nba_live_tick.py            # write syndicate/features/nba/live_tick/
  py -3 scripts/port_nba_live_tick.py --check    # exit 1 if the package on disk is not what this script generates
"""
from __future__ import annotations

import argparse
import ast
import builtins
import hashlib
import symtable
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "vendor" / "nba_betting_repo"
PKG = VENDOR / "src" / "nba_betting"
OUT = ROOT / "syndicate" / "features" / "nba" / "live_tick"

TICK_ROOTS = [
    "_live_lens_tick_payload",
    # Reached through app.test_client() inside the tick -- invisible to a name closure, so listed explicitly.
    "api_live_lens_tuning",
    "api_live_lines",
    "api_live_pbp_stats",
    "api_live_player_lens",
]


@dataclass
class Spec:
    out_name: str
    src: Path
    roots: list[str]
    header: str
    header_names: set[str]
    edits: list[tuple[str, str, str]] = field(default_factory=list)  # (function, old, new)


_TICK_HEADER = '''\
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

# ---- Data root (EDIT: replaces the vendored BASE_DIR / nba_betting.config block) ----
# Vendored: DATA_DIR = nba_betting.config.paths.data_root = Path($NBA_BETTING_DATA_ROOT), else <vendored repo>/data.
# Here the fallback is Syndicate's own NBA source data dir; with the env var set (every fleet role sets it) the
# value is identical. The vendored import-time `reconcile_repo_data_to_active()` copy is NOT run.
_DATA_ROOT = (os.environ.get("NBA_BETTING_DATA_ROOT") or "").strip()
try:
    _DATA_ROOT_P = Path(_DATA_ROOT) if _DATA_ROOT else (Path(__file__).resolve().parents[4] / "data" / "nba_source" / "data")
except Exception:
    _DATA_ROOT_P = Path(__file__).resolve().parents[4] / "data" / "nba_source" / "data"
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

_TICK_HEADER_NAMES = {
    "Any", "Callable", "Dict", "List", "Optional", "Tuple", "lru_cache", "pd", "np", "math", "json", "os",
    "datetime", "timedelta", "timezone", "Flask", "jsonify", "request", "sys", "time", "threading", "re",
    "requests", "Path", "traceback", "_OddsApiConfig", "_oddsapi_list_events_current",
    "_oddsapi_discover_event_market_keys", "_oddsapi_fetch_event_odds_current", "_normalize_bookmaker_key",
    "_resolve_player_prop_bookmakers", "_to_tricode", "_DATA_ROOT", "_DATA_ROOT_P", "DATA_DIR",
    "DATA_PROCESSED_DIR", "REPO_DATA_DIR", "REPO_DATA_PROCESSED_DIR", "app",
    # Only reachable through the replaced data-root block / Flask(static_folder=WEB_DIR):
    "BASE_DIR", "WEB_DIR", "_PathEarly", "_paths", "_reconcile_repo_data_to_active",
}

_TICK_EDITS = [
    (
        "_norm_player_name",
        "from nba_betting.player_names import normalize_player_name_key as _normalize_player_name_key  # type: ignore",
        "from .player_names import normalize_player_name_key as _normalize_player_name_key  # type: ignore",
    ),
    (
        "_short_player_key",
        "from nba_betting.player_names import short_player_key as _shared_short_player_key  # type: ignore",
        "from .player_names import short_player_key as _shared_short_player_key  # type: ignore",
    ),
    (
        "_live_load_period_lines_map",
        "from nba_betting.odds_bovada import fetch_bovada_period_lines_current as _fbplc  # type: ignore",
        "from .odds_bovada import fetch_bovada_period_lines_current as _fbplc  # type: ignore",
    ),
    (
        "_ll_load_audit_module",
        '''    import sys as _sys

    tools_dir = BASE_DIR / "tools"
    if str(tools_dir) not in _sys.path:
        _sys.path.insert(0, str(tools_dir))
    import daily_live_lens_audit as _audit  # type: ignore
''',
        '''    # EDIT: the vendored tools/daily_live_lens_audit.py, ported as .live_lens_audit (closure only).
    from . import live_lens_audit as _audit
''',
    ),
]

_ODDS_API_HEADER = '''\
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Optional
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

import pandas as pd
import requests
import numpy as np
from tenacity import retry, stop_after_attempt, wait_exponential_jitter, retry_if_exception_type

from .teams import normalize_team
'''

_ODDS_BOVADA_HEADER = '''\
import pandas as pd
import requests
from datetime import datetime
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore
from typing import Any

from .teams import normalize_team
'''

_AUDIT_HEADER = '''\
import argparse
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
'''

SPECS = [
    Spec("tick", VENDOR / "app.py", TICK_ROOTS, _TICK_HEADER, _TICK_HEADER_NAMES, _TICK_EDITS),
    Spec(
        "odds_api",
        PKG / "odds_api.py",
        ["OddsApiConfig", "list_events_current", "discover_event_market_keys", "fetch_event_odds_current",
         "normalize_bookmaker_key", "resolve_player_prop_bookmakers"],
        _ODDS_API_HEADER,
        {"os", "dataclass", "datetime", "timedelta", "Iterable", "Optional", "ZoneInfo", "pd", "requests", "np",
         "retry", "stop_after_attempt", "wait_exponential_jitter", "retry_if_exception_type", "normalize_team",
         "paths"},
    ),
    Spec("teams", PKG / "teams.py", ["to_tricode", "normalize_team"], "", set()),
    Spec("player_names", PKG / "player_names.py", ["normalize_player_name_key", "short_player_key"],
         "from typing import Any\n\nimport unicodedata\n", {"Any", "unicodedata"}),
    Spec("odds_bovada", PKG / "odds_bovada.py", ["fetch_bovada_period_lines_current"], _ODDS_BOVADA_HEADER,
         {"pd", "requests", "datetime", "ZoneInfo", "Any", "normalize_team"}),
    Spec("live_lens_audit", VENDOR / "tools" / "daily_live_lens_audit.py", ["_live_stat_key", "_flag_adjustments", "_derive_tags"],
         _AUDIT_HEADER,
         {"argparse", "json", "math", "os", "re", "dataclass", "_date", "datetime", "timedelta", "Path", "Any",
          "Iterable", "pd"}),
]


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


def generate(spec: Spec) -> tuple[str, dict]:
    raw = spec.src.read_text(encoding="utf-8-sig")
    lines = raw.split("\n")
    tree = ast.parse(raw)
    binders: dict[str, list[ast.stmt]] = {}
    for node in tree.body:
        for name in _bound_names(node):
            binders.setdefault(name, []).append(node)

    selected: dict[int, ast.stmt] = {}
    seen: set[str] = set()
    stack = list(spec.roots)
    while stack:
        name = stack.pop()
        if name in seen or name in spec.header_names:
            continue
        seen.add(name)
        nodes = binders.get(name)
        if not nodes:
            if hasattr(builtins, name) or name in {"__file__", "__name__"}:
                continue
            raise SystemExit(f"[{spec.out_name}] unresolved module name {name!r}")
        if isinstance(nodes[-1], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes = [nodes[-1]]  # the LAST def wins at import time
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.Try, ast.If)):
                raise SystemExit(f"[{spec.out_name}] {name!r} is bound by an import/try/if at line {node.lineno}: put it in the header")
            selected[node.lineno] = node
            own = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            stack.extend(_module_refs(_segment(lines, node), own))

    chunks: dict[str, str] = {}
    body_parts: list[str] = []
    for lineno in sorted(selected):
        node = selected[lineno]
        seg = _segment(lines, node)
        name = getattr(node, "name", None)
        if name:
            chunks[name] = seg
        body_parts.append(seg)
    body = "\n\n\n".join(body_parts)
    for fn, old, new in spec.edits:
        seg = chunks.get(fn)
        if seg is None:
            raise SystemExit(f"[{spec.out_name}] edit target {fn!r} is not in the closure")
        if seg.count(old) != 1 or body.count(old) != 1:
            raise SystemExit(f"[{spec.out_name}] edit anchor in {fn!r} matched {seg.count(old)}x in the function, {body.count(old)}x overall")
        body = body.replace(old, new)

    has_future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body)
    future = "from __future__ import annotations\n\n" if has_future else ""
    sha = hashlib.sha256(spec.src.read_bytes()).hexdigest()[:16]
    rel = spec.src.relative_to(ROOT).as_posix()
    doc = (
        f'"""GENERATED by scripts/port_nba_live_tick.py -- do not edit by hand (`--check` fails on a hand edit).\n\n'
        f"Source: {rel} (sha256 {sha}...), {len(selected)} top-level statements, copied verbatim\n"
        f"except for the header and the anchored EDITS listed in the generator.\n"
        f'"""\n'
    )
    text = doc + future + (spec.header + "\n\n" if spec.header else "") + body + "\n"
    _validate(spec.out_name, text)
    defs = sorted(n for n in (getattr(selected[k], "name", None) for k in selected) if n)
    return text, {"statements": len(selected), "defs": len(defs), "lines": text.count("\n"), "source_sha": sha}


def _validate(out_name: str, text: str) -> None:
    """Every global a generated function reads must be bound at module level (or be a builtin)."""
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
            if hit and name not in bound and not hasattr(builtins, name) and name not in {"__file__", "__name__"}:
                missing.add(f"{tbl.get_name()}:{name}")
        for child in tbl.get_children():
            walk(child)

    walk(symtable.symtable(text, out_name, "exec"))
    if missing:
        raise SystemExit(f"[{out_name}] unbound globals in generated module: {sorted(missing)}")


INIT = '''"""Syndicate port of the vendored NBA live-lens tick (lane nba-live-tick-native, 2026-10-12).

GENERATED by scripts/port_nba_live_tick.py. `tick._live_lens_tick_payload(date)` is the vendored
`vendor/nba_betting_repo/app.py::_live_lens_tick_payload`, with its closure, the four routes it calls through
`app.test_client()`, and the `nba_betting` package / `tools/daily_live_lens_audit.py` helpers it imports. Parity with
the vendored function: scripts/nba_live_tick_parity.py and tests/test_nba_live_tick_parity.py.
"""
'''


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    outputs = {"__init__.py": INIT}
    for spec in SPECS:
        text, stats = generate(spec)
        outputs[f"{spec.out_name}.py"] = text
        print(f"{spec.out_name:16s} {stats}")
    if args.check:
        bad = [name for name, text in outputs.items() if not (OUT / name).exists() or (OUT / name).read_bytes().replace(b"\r\n", b"\n") != text.encode("utf-8")]  # a Windows checkout may be CRLF
        extra = sorted(p.name for p in OUT.glob("*.py") if p.name not in outputs) if OUT.exists() else []
        if bad or extra:
            print(f"CHECK FAILED: differs={bad} unexpected={extra}")
            return 1
        print("CHECK OK")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in outputs.items():
        (OUT / name).write_bytes(text.encode("utf-8"))
    print(f"wrote {len(outputs)} files to {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
