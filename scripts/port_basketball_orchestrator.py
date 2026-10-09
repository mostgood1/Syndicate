"""Regenerate the native smart-sim ORCHESTRATOR from the vendored source (plan P6).

ONE-SHOT PORT TOOL (lane basketball-native-orchestrator, 2026-10-09). It writes
``syndicate/features/basketball_engine/orchestrator/{smart_sim,quarters,...}.py``
from ``vendor/wnba_betting_repo/src/wnba_betting`` and CHECKS every emitted
definition against ``vendor/nba_betting_repo/src/nba_betting``, and it keeps the
record of HOW the port was derived, so a reviewer checks edits instead of
trusting 3,300 hand-copied lines. ``port_basketball_engine.py`` (P1) is the
model.

WHAT IS PORTED. Not whole modules: the CLOSURE of what production executes.
Roots are ``simulate_smart_game`` plus the helpers the bridge's ports read off
the module (``view.VIEW_NAMES``). The closure follows every name across the
vendored package, and stops at the 29 names Syndicate replaced
(``hooks.HOOK_NAMES``): their vendored bodies never ran in production.

WHY THE WNBA SOURCE. The WNBA fork already reads its league numbers from
``LEAGUE``; the NBA fork inlines NBA literals in the same places. Starting from
the WNBA text, every NBA literal becomes a field of the NBA
``OrchestratorLeague`` (runtime.py).

THE CHECK AGAINST NBA. Every emitted definition must be textually identical in
the two forks (package names normalised), unless it is listed in DIVERGENT with
the reason. A divergence nobody listed aborts the port.

EDITS, in order:
  1. ANCHORED text edits (EDITS): each anchor must match exactly the expected
     number of times inside its definition, or nothing is written.
  2. AST-positioned edits, mechanical and counted:
       * a global ``paths`` / ``LEAGUE`` read -> ``orch.paths`` / ``orch.league``;
       * a function that needs either (directly, or through a callee, or because
         it calls a hook) gets a keyword-only ``orch`` parameter, and every call
         to such a function gets ``orch=orch``;
       * a relative import inside a function is re-pointed at the native module.

Once the switch has landed the generated files are the source of truth and
this tool is history: re-running it would discard any later native edit.
``--check`` regenerates in memory and exits 1 if anything differs from disk.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = {
    "wnba": ROOT / "vendor" / "wnba_betting_repo" / "src" / "wnba_betting",
    "nba": ROOT / "vendor" / "nba_betting_repo" / "src" / "nba_betting",
}
PKG = {"wnba": "wnba_betting", "nba": "nba_betting"}
DST = ROOT / "syndicate" / "features" / "basketball_engine" / "orchestrator"

# vendored module (relative to the package) -> generated module name
MODULES: dict[str, str] = {
    "sim.smart_sim": "smart_sim",
    "sim.quarters": "quarters",
    "sim.connected_game": "connected_game",
    "boxscores": "boxscores",
    "prob_calibration": "prob_calibration",
    "prop_ladders": "prop_ladders",
    "roster_files": "roster_files",
    "player_names": "player_names",
    "player_priors": "player_priors",
}
# Vendored names that resolve OUTSIDE the generated modules.
EXTERNAL_IMPORTS: dict[tuple[str, str], tuple[str, str]] = {
    # SmartSimConfig.event_cfg's default factory. Production always passes the bridge's own
    # EventSimConfigLocal, so this default is never built there; P1's native config stands in.
    ("sim.events", "EventSimConfig"): ("..engine", "EventSimConfig"),
}
GLOBALS_TO_ORCH = {"paths": "orch.paths", "LEAGUE": "orch.league"}

# ---------------------------------------------------------------------------
# The definitions that differ between the forks, and why the WNBA text (after
# EDITS) is right for both. Parity (scripts/basketball_orchestrator_parity.py)
# is what proves it.
DIVERGENT: dict[tuple[str, str], str] = {
    ("sim.smart_sim", "simulate_smart_game"): (
        "NBA inlines 98.0 / 112.0 / 90.0 (= 98 - 8) / 240-minute / 12x60s periods where WNBA reads LEAGUE; "
        "the possession clip is (88, 112) in NBA and (bp - 8, bp + 10) in WNBA -> poss_clip_lo/hi; "
        "WNBA alone prunes the pregame pool, records ctx.pregame_rotation_pool and stamps team/opponent "
        "-> prune_pregame_pool / stamp_team_opponent; WNBA logs a warning when the period summary fails (log only)"
    ),
    ("sim.smart_sim", "_scale_minutes_to_target"): "default total_target 240.0 (NBA) vs LEAGUE.regulation_team_minutes",
    ("sim.smart_sim", "_cap_and_redistribute_minutes"): "default total_target 240.0 (NBA) vs LEAGUE.regulation_team_minutes",
    ("sim.smart_sim", "_regularize_rotation_minutes"): "total_target=240.0 (NBA) vs LEAGUE.regulation_team_minutes",
    ("sim.smart_sim", "_rotation_minutes_signal_guardrail"): "total_target=240.0 (NBA) vs LEAGUE.regulation_team_minutes",
    ("boxscores", "_tri_to_espn"): "team-code table per league -> OrchestratorLeague.espn_tri_fix",
    ("boxscores", "_espn_to_tri"): "team-code table per league -> OrchestratorLeague.espn_abbr_fix",
    ("boxscores", "_espn_scoreboard"): "sports/basketball/nba literal vs LEAGUE.espn_sport_path",
    ("boxscores", "_espn_summary"): "sports/basketball/nba literal vs LEAGUE.espn_sport_path",
    ("boxscores", "_http_get_json"): "'nba-betting/1.0' literal vs LEAGUE.user_agent_product",
}
# Emitted, and present only in the WNBA fork.
WNBA_ONLY: dict[tuple[str, str], str] = {
    ("sim.smart_sim", "_stamp_team_opponent"): "called only when OrchestratorLeague.stamp_team_opponent (WNBA)",
    ("sim.smart_sim", "logger"): "the WNBA fork's module logger (log only)",
}


@dataclass(frozen=True)
class Edit:
    module: str
    name: str
    old: str
    new: str
    count: int = 1
    why: str = ""


EDITS: list[Edit] = [
    # --- smart_sim: the possession clip (NBA 88/112 is not WNBA's formula) ---------------------------------------
    Edit(
        "sim.smart_sim", "simulate_smart_game",
        "float(np.clip(base_poss * pm, LEAGUE.baseline_pace - 8.0, LEAGUE.baseline_pace + 10.0))",
        "float(np.clip(base_poss * pm, LEAGUE.poss_clip_lo, LEAGUE.poss_clip_hi))",
        why="NBA fork clips at (88.0, 112.0), WNBA at (baseline - 8, baseline + 10): per-league fields",
    ),
    # --- smart_sim: WNBA-only pregame pool prune -------------------------------------------------------------------
    Edit(
        "sim.smart_sim", "simulate_smart_game",
        "    pregame_pool_diag: dict[str, Any] = {\"home\": None, \"away\": None}\n"
        "    market_player_names = _market_player_names_for_matchup(\n",
        "    pregame_pool_diag: dict[str, Any] = {\"home\": None, \"away\": None}\n"
        "    market_player_names = {} if not LEAGUE.prune_pregame_pool else _market_player_names_for_matchup(\n",
        why="the NBA fork neither reads market player names nor prunes",
    ),
    Edit(
        "sim.smart_sim", "simulate_smart_game",
        "    try:\n        home_raw, home_pool_diag = _prune_pregame_rotation_pool(\n",
        "    try:\n        if not LEAGUE.prune_pregame_pool:\n            raise _NoPregamePrune\n"
        "        home_raw, home_pool_diag = _prune_pregame_rotation_pool(\n",
        why="NBA: skip the prune; the except branch leaves pregame_pool_diag at its initial value, as WNBA's failure path does",
    ),
    Edit(
        "sim.smart_sim", "simulate_smart_game",
        "        if isinstance(pregame_pool_diag, dict) and pregame_pool_diag:\n",
        "        if LEAGUE.prune_pregame_pool and isinstance(pregame_pool_diag, dict) and pregame_pool_diag:\n",
        why="the NBA fork has no ctx.pregame_rotation_pool key",
    ),
    # --- smart_sim: WNBA-only team/opponent stamp ---------------------------------------------------------------------
    Edit(
        "sim.smart_sim", "simulate_smart_game",
        "            home_tri=home_tri,\n            away_tri=away_tri,\n        ),\n    }",
        "            home_tri=home_tri,\n            away_tri=away_tri,\n            enabled=LEAGUE.stamp_team_opponent,\n        ),\n    }",
        why="the NBA fork returns the players block unstamped",
    ),
    Edit(
        "sim.smart_sim", "_stamp_team_opponent",
        "def _stamp_team_opponent(players: Dict[str, List[Dict[str, Any]]], *, home_tri: str, away_tri: str) -> Dict[str, List[Dict[str, Any]]]:",
        "def _stamp_team_opponent(players: Dict[str, List[Dict[str, Any]]], *, home_tri: str, away_tri: str, enabled: bool = True) -> Dict[str, List[Dict[str, Any]]]:",
        why="league switch (OrchestratorLeague.stamp_team_opponent)",
    ),
    Edit(
        "sim.smart_sim", "_stamp_team_opponent",
        "    home_u, away_u = str(home_tri or \"\").upper().strip(), str(away_tri or \"\").upper().strip()\n",
        "    if not enabled:\n        return players\n"
        "    home_u, away_u = str(home_tri or \"\").upper().strip(), str(away_tri or \"\").upper().strip()\n",
        why="NBA: the same dict object, untouched",
    ),
    # --- smart_sim: LEAGUE in DEFAULT arguments (evaluated at import; orch is a call argument) ----------------------
    Edit(
        "sim.smart_sim", "_scale_minutes_to_target",
        "def _scale_minutes_to_target(mins: pd.Series, total_target: float = LEAGUE.regulation_team_minutes) -> pd.Series:\n",
        "def _scale_minutes_to_target(mins: pd.Series, total_target: Optional[float] = None) -> pd.Series:\n"
        "    if total_target is None:\n        total_target = LEAGUE.regulation_team_minutes\n",
        why="default argument -> per-call league value",
    ),
    Edit(
        "sim.smart_sim", "_cap_and_redistribute_minutes",
        "    total_target: float = LEAGUE.regulation_team_minutes,\n",
        "    total_target: Optional[float] = None,\n",
        why="default argument -> per-call league value (resolved on the first body line, below)",
    ),
    # --- boxscores: per-league ESPN tables -----------------------------------------------------------------------------
    Edit(
        "boxscores", "_tri_to_espn",
        "    fix = {\n        \"GSV\": \"GS\",\n        \"LVA\": \"LV\",\n        \"LAS\": \"LA\",\n        \"NYL\": \"NY\",\n    }\n",
        "    fix = dict(LEAGUE.espn_tri_fix)\n",
        why="team-code table per league",
    ),
    Edit(
        "boxscores", "_espn_to_tri",
        "    fix = {\n        \"GS\": \"GSV\",\n        \"LV\": \"LVA\",\n        \"LA\": \"LAS\",\n        \"NY\": \"NYL\",\n        \"WSH\": \"WSH\",\n    }\n",
        "    fix = dict(LEAGUE.espn_abbr_fix)\n",
        why="team-code table per league",
    ),
    # --- prob_calibration: the caches are per data root; the vendored repo tree is not read -----------------------
    Edit(
        "prob_calibration", "_PROB_CALIBRATION_INDEX",
        "_PROB_CALIBRATION_INDEX: Optional[list[tuple[pd.Timestamp, Any]]] = None",
        "_PROB_CALIBRATION_INDEX: dict[Any, list[tuple[pd.Timestamp, Any]]] = {}",
        why="one index per data root (the vendored global assumed one root per process)",
    ),
    Edit(
        "prob_calibration", "_PROB_CALIBRATION_CACHE",
        "_PROB_CALIBRATION_CACHE: dict[str, Optional[dict[str, Any]]] = {}",
        "_PROB_CALIBRATION_CACHE: dict[tuple[Any, str], Optional[dict[str, Any]]] = {}",
        why="keyed by (data root, date)",
    ),
    Edit(
        "prob_calibration", "_load_prob_calibration_for_date",
        "    key = str(target.date())\n",
        "    key = (paths, str(target.date()))\n",
        why="cache key includes the data root",
    ),
    Edit(
        "prob_calibration", "_load_prob_calibration_for_date",
        "    global _PROB_CALIBRATION_INDEX\n    if _PROB_CALIBRATION_INDEX is None:\n",
        "    if _PROB_CALIBRATION_INDEX.get(paths) is None:\n",
        why="per-root index",
    ),
    Edit(
        "prob_calibration", "_load_prob_calibration_for_date",
        "        _PROB_CALIBRATION_INDEX = sorted(idx, key=lambda t: t[0])\n",
        "        _PROB_CALIBRATION_INDEX[paths] = sorted(idx, key=lambda t: t[0])\n",
        why="per-root index",
    ),
    Edit(
        "prob_calibration", "_load_prob_calibration_for_date",
        "        for dt, fp in _PROB_CALIBRATION_INDEX or []:\n",
        "        for dt, fp in _PROB_CALIBRATION_INDEX.get(paths) or []:\n",
        why="per-root index",
    ),
    Edit(
        "prob_calibration", "_calibration_period_prob_paths",
        "    roots = [paths.repo_data_processed, paths.data_processed]\n",
        "    roots = [paths.data_processed]\n",
        why=(
            "the vendored repo tree (vendor/<pkg>_repo/data/processed) is no longer read. "
            "Measured 2026-10-09 on the fleet: it holds 0 calibration_period_probs_*.json for either league"
        ),
    ),
]

# Applied to the first body line of _cap_and_redistribute_minutes after the signature edit above.
CAP_BODY_ANCHOR = '    """'


# ---------------------------------------------------------------------------
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _norm(text: str) -> str:
    return text.replace("wnba_betting", "PKG").replace("nba_betting", "PKG")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _resolve(curmod: str, node: ast.ImportFrom) -> str:
    parts = curmod.split(".")[:-1]
    if node.level:
        base = parts[: len(parts) - (node.level - 1)] if node.level > 1 else parts
        return ".".join(base + ([node.module] if node.module else []))
    return node.module or ""


@dataclass
class VMod:
    rel: str
    text: str
    tree: ast.Module
    defs: dict[str, ast.stmt] = field(default_factory=dict)
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # local name -> (abs-in-package module, name)
    top_imports: list[ast.stmt] = field(default_factory=list)

    @classmethod
    def load(cls, league: str, rel: str) -> "VMod":
        path = SRC[league] / (rel.replace(".", "/") + ".py")
        text = _read(path)
        tree = ast.parse(text)
        m = cls(rel=rel, text=text, tree=tree)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                m.defs[node.name] = node
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for t in targets:
                    if isinstance(t, ast.Name):
                        m.defs[t.id] = node
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                m.top_imports.append(node)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                mod = _resolve(rel, node)
                for a in node.names:
                    m.imports.setdefault(a.asname or a.name, (mod, a.name))
        return m

    def source(self, name: str) -> str:
        node = self.defs[name]
        lines = self.text.split("\n")
        start = node.decorator_list[0].lineno if getattr(node, "decorator_list", None) else node.lineno
        return "\n".join(lines[start - 1 : node.end_lineno])


class Package:
    def __init__(self, league: str):
        self.league = league
        self.mods: dict[str, VMod] = {}

    def mod(self, rel: str) -> VMod:
        if rel not in self.mods:
            self.mods[rel] = VMod.load(self.league, rel)
        return self.mods[rel]


def _names(node: ast.AST) -> set[str]:
    return {x.id for x in ast.walk(node) if isinstance(x, ast.Name)}


def closure(pkg: Package, roots: list[tuple[str, str]], hooks: set[str]) -> dict[tuple[str, str], None]:
    """Ordered set of (module, name) the roots reach, stopping at hooks (smart_sim) and external imports."""
    need: dict[tuple[str, str], None] = {}
    stack = list(roots)
    while stack:
        rel, name = stack.pop()
        if (rel, name) in need:
            continue
        if rel == "sim.smart_sim" and name in hooks:
            continue
        if (rel, name) in EXTERNAL_IMPORTS:
            continue
        if rel not in MODULES and rel != "league" and rel != "config":
            raise SystemExit(f"closure reached an unmapped vendored module: {rel}.{name}")
        if rel in ("league", "config"):
            if (rel, name) not in (("league", "LEAGUE"), ("config", "paths")):
                raise SystemExit(f"emitted code reaches {rel}.{name}; only LEAGUE / paths are replaced by `orch`")
            continue
        m = pkg.mod(rel)
        if name not in m.defs:
            if name in m.imports:
                stack.append(m.imports[name])
                continue
            raise SystemExit(f"cannot resolve {rel}.{name}")
        need[(rel, name)] = None
        for nm in _names(m.defs[name]):
            if nm == name:
                continue
            if nm in m.defs:
                stack.append((rel, nm))
            elif nm in m.imports:
                tgt = m.imports[nm]
                if rel == "sim.smart_sim" and nm in hooks:
                    continue
                stack.append(tgt)
    return need


def apply_anchor_edits(rel: str, name: str, text: str, log: list[str]) -> str:
    for e in EDITS:
        if (e.module, e.name) != (rel, name):
            continue
        n = text.count(e.old)
        if n != e.count:
            raise SystemExit(f"ANCHOR MISMATCH {rel}.{name}: expected {e.count}, found {n}:\n{e.old}")
        text = text.replace(e.old, e.new)
        log.append(f"{rel}.{name}: {e.why}")
    if (rel, name) == ("sim.smart_sim", "_cap_and_redistribute_minutes"):
        # Resolve the per-call default on the first body line, after the docstring if there is one.
        tree = ast.parse(text)
        fn = tree.body[0]
        first = fn.body[0]
        is_doc = isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant) and isinstance(first.value.value, str)
        lines = text.split("\n")
        insert_at = (first.end_lineno if is_doc else first.lineno - 1)
        lines.insert(insert_at, "    if total_target is None:\n        total_target = LEAGUE.regulation_team_minutes")
        text = "\n".join(lines)
        log.append(f"{rel}.{name}: default total_target resolved per call")
    return text


def _bound_names(fn: ast.AST) -> set[str]:
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.arg):
            out.add(n.arg)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            out.add(n.id)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n is not fn:
            out.add(n.name)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(n, ast.Global):
            out.update(n.names)
    return out


def _line_offsets(text: str) -> list[int]:
    offs, total = [0], 0
    for line in text.split("\n"):
        total += len(line) + 1
        offs.append(total)
    return offs


@dataclass
class Gen:
    rel: str
    name: str
    text: str


def thread_and_rewrite(gen: Gen, threaded: set[tuple[str, str]], resolve_name, stats: dict[str, int], globals_map: dict[str, str] | None = None) -> str:
    """Apply the mechanical AST edits to one definition's text."""
    text = gen.text
    tree = ast.parse(text)
    node = tree.body[0]
    offs = _line_offsets(text)

    def pos(lineno: int, col: int) -> int:
        return offs[lineno - 1] + col

    gmap = GLOBALS_TO_ORCH if globals_map is None else globals_map
    edits: list[tuple[int, int, str]] = []
    is_fn = isinstance(node, ast.FunctionDef)
    bound = _bound_names(node) if is_fn else set()
    if is_fn:
        for g in list(gmap) + ["orch"]:
            if g in bound:
                raise SystemExit(f"{gen.rel}.{gen.name} binds {g!r} locally; threading would be ambiguous")

    calls_func_ids: set[int] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
            tgt = resolve_name(gen.rel, n.func.id)
            if tgt in threaded:
                calls_func_ids.add(id(n.func))
                # insert the keyword after the last argument, before the closing paren
                close = pos(n.end_lineno, n.end_col_offset) - 1
                assert text[close] == ")", (gen.rel, gen.name, text[close - 20 : close + 1])
                if any(isinstance(a, ast.GeneratorExp) for a in n.args) and len(n.args) == 1 and not n.keywords:
                    raise SystemExit(f"{gen.rel}.{gen.name}: bare generator argument to {n.func.id}")
                ins = len(text[:close].rstrip())
                prev = text[:ins]
                new = "orch=orch" if prev.endswith("(") else (" orch=orch," if prev.endswith(",") else ", orch=orch")
                edits.append((ins, ins, new))
                stats["call_sites"] += 1
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            if n.id in gmap:
                edits.append((pos(n.lineno, n.col_offset), pos(n.end_lineno, n.end_col_offset), gmap[n.id]))
                stats["global_reads"] += 1
            elif id(n) not in calls_func_ids and resolve_name(gen.rel, n.id) in threaded and n.id != gen.name:
                raise SystemExit(f"{gen.rel}.{gen.name}: threaded function {n.id} used as a VALUE, not called")
        if isinstance(n, ast.ImportFrom) and n.level and n is not node and gen.rel in MODULES:
            mod = _resolve(gen.rel, n)
            names = []
            for a in n.names:
                key = (mod, a.name)
                if key in EXTERNAL_IMPORTS:
                    raise SystemExit(f"function-local import of external {key} not handled")
                if mod not in MODULES:
                    raise SystemExit(f"{gen.rel}.{gen.name}: function-local import from unmapped {mod}")
                names.append(a.name + (f" as {a.asname}" if a.asname else ""))
            if mod == "sim.smart_sim":
                raise SystemExit("function-local import from smart_sim")
            new = f"from .{MODULES[mod]} import {', '.join(names)}"
            edits.append((pos(n.lineno, n.col_offset), pos(n.end_lineno, n.end_col_offset), new))
            stats["local_imports"] += 1
    if is_fn and (gen.rel, gen.name) in threaded:
        a = node.args
        if a.kwarg is not None:
            raise SystemExit(f"{gen.rel}.{gen.name}: **kwargs signature not handled")
        # insert after the last parameter
        last = None
        for x in list(a.posonlyargs) + list(a.args) + ([a.vararg] if a.vararg else []) + list(a.kwonlyargs):
            last = x
        defaults = list(a.defaults) + [d for d in a.kw_defaults if d is not None]
        end_candidates = [(x.end_lineno, x.end_col_offset) for x in ([last] if last else [])] + [(d.end_lineno, d.end_col_offset) for d in defaults]
        if end_candidates:
            ln, col = max(end_candidates)
            at = pos(ln, col)
            star = "" if (a.vararg or a.kwonlyargs) else "*, "
            edits.append((at, at, f", {star}orch"))
        else:
            # def f(): -> def f(*, orch):
            m = re.search(r"\bdef\s+" + re.escape(gen.name) + r"\s*\(", text)
            at = m.end()
            edits.append((at, at, "*, orch"))
        stats["signatures"] += 1
    for start, end, new in sorted(edits, key=lambda e: (e[0], e[1]), reverse=True):
        text = text[:start] + new + text[end:]
    return text


def build() -> tuple[dict[str, str], list[str]]:
    view_names = _literal_tuple("view.py", "VIEW_NAMES")
    hooks = set(_literal_tuple("hooks.py", "HOOK_NAMES"))
    wn, nb = Package("wnba"), Package("nba")
    roots = [("sim.smart_sim", "simulate_smart_game"), ("sim.smart_sim", "SmartSimConfig"), ("prop_ladders", "build_exact_ladder_payload")]
    roots += [("sim.smart_sim", n) for n in view_names]
    need = closure(wn, roots, hooks)
    need_nba = closure(nb, [r for r in roots if r != ("sim.smart_sim", "_stamp_team_opponent")], hooks)
    log: list[str] = []

    # 1) closures and per-definition text must agree, except where declared.
    only_w = set(need) - set(need_nba)
    only_n = set(need_nba) - set(need)
    if only_n:
        raise SystemExit(f"NBA reaches definitions the WNBA port does not: {sorted(only_n)}")
    if only_w - set(WNBA_ONLY):
        raise SystemExit(f"WNBA-only definitions not declared in WNBA_ONLY: {sorted(only_w - set(WNBA_ONLY))}")
    for key in need:
        rel, name = key
        if key in WNBA_ONLY:
            continue
        same = _norm(wn.mod(rel).source(name)) == _norm(nb.mod(rel).source(name))
        if not same and key not in DIVERGENT:
            raise SystemExit(f"UNDECLARED DIVERGENCE {rel}.{name}: NBA and WNBA differ")
        if same and key in DIVERGENT:
            raise SystemExit(f"DIVERGENT lists {rel}.{name} but the forks agree")
    for key in DIVERGENT:
        if key not in need:
            raise SystemExit(f"DIVERGENT lists {key}, which is not in the closure")
    for e in EDITS:
        if (e.module, e.name) not in need:
            raise SystemExit(f"EDIT targets {e.module}.{e.name}, which is not emitted")

    # 2) anchored edits, then which functions need `orch`.
    gens: dict[tuple[str, str], Gen] = {}
    for rel, name in need:
        gens[(rel, name)] = Gen(rel, name, apply_anchor_edits(rel, name, wn.mod(rel).source(name), log))

    def resolve_name(rel: str, nm: str):
        if rel == "sim.smart_sim" and nm in hooks:
            return ("hooks", nm)
        m = wn.mod(rel)
        if nm in m.defs:
            return (rel, nm)
        if nm in m.imports:
            tgt = m.imports[nm]
            if tgt[0] == "sim.smart_sim" and tgt[1] in hooks:
                return ("hooks", tgt[1])
            # follow re-exports (e.g. smart_sim imports _norm_player_key from player_priors)
            seen = set()
            while tgt not in need and tgt[0] in MODULES and tgt not in seen:
                seen.add(tgt)
                mm = wn.mod(tgt[0])
                if tgt[1] in mm.imports:
                    tgt = mm.imports[tgt[1]]
                else:
                    break
            return tgt
        return None

    threaded: set = {("hooks", n) for n in hooks}
    for key, g in gens.items():
        node = ast.parse(g.text).body[0]
        if isinstance(node, ast.FunctionDef) and (_names(node) & set(GLOBALS_TO_ORCH)):
            threaded.add(key)
    changed = True
    while changed:
        changed = False
        for key, g in gens.items():
            if key in threaded:
                continue
            node = ast.parse(g.text).body[0]
            if not isinstance(node, ast.FunctionDef):
                continue
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and resolve_name(key[0], n.func.id) in threaded:
                    threaded.add(key)
                    changed = True
                    break
    for key, g in gens.items():
        node = ast.parse(g.text).body[0]
        if not isinstance(node, ast.FunctionDef) and (_names(node) & set(GLOBALS_TO_ORCH)):
            raise SystemExit(f"module-level {key} reads paths/LEAGUE")

    # 3) mechanical edits.
    stats = {"call_sites": 0, "global_reads": 0, "local_imports": 0, "signatures": 0}
    for key, g in gens.items():
        g.text = thread_and_rewrite(g, threaded, resolve_name, stats)

    # 4) assemble modules.
    out: dict[str, str] = {}
    for rel, gname in MODULES.items():
        keys = [k for k in need if k[0] == rel]
        if not keys:
            continue
        m = wn.mod(rel)
        order = {name: m.defs[name].lineno for _, name in keys}
        keys.sort(key=lambda k: order[k[1]])
        body_text = "\n\n\n".join(gens[k].text for k in keys)
        # imports: vendored absolute top-level imports verbatim; package names regenerated.
        lines: list[str] = []
        for node in m.top_imports:
            if isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__"):
                continue
            seg = ast.get_source_segment(m.text, node)
            if seg and seg not in lines:
                lines.append(seg)
        used = set()
        for k in keys:
            used |= _names(ast.parse(gens[k].text))
        defined = {name for _, name in keys}
        rel_imports: dict[str, set[str]] = {}
        for nm in sorted(used - defined):
            tgt = resolve_name(rel, nm)
            if tgt is None:
                continue
            if tgt[0] == "hooks":
                rel_imports.setdefault(".hooks", set()).add(nm)
            elif tgt in EXTERNAL_IMPORTS:
                mod, name = EXTERNAL_IMPORTS[tgt]
                rel_imports.setdefault(mod, set()).add(name if name == nm else f"{name} as {nm}")
            elif tgt in need and tgt[0] != rel:
                src = "." + MODULES[tgt[0]]
                rel_imports.setdefault(src, set()).add(tgt[1] if tgt[1] == nm else f"{tgt[1]} as {nm}")
        if rel == "sim.smart_sim":
            rel_imports.setdefault(".runtime", set()).add("OrchestratorEnv")
        imp = "\n".join(lines)
        if rel_imports:
            imp += "\n\n" + "\n".join(f"from {mod} import {', '.join(sorted(names))}" for mod, names in sorted(rel_imports.items()))
        extra = ""
        if rel == "sim.smart_sim":
            th = sorted(n for (r, n) in threaded if r == rel)
            extra = (
                "\n\n\nclass _NoPregamePrune(Exception):\n"
                '    """Raised inside the pregame-pool try block when the league does not prune (NBA)."""\n'
                f"\n\n# Functions of this module that take the keyword `orch` (view.py binds them).\nORCH_THREADED = frozenset({th!r})\n"
            )
        header = _header(rel, gname, keys, stats if rel == "sim.smart_sim" else None)
        out[gname] = header + imp + extra + "\n\n\n" + body_text.rstrip() + "\n"

    # league_config: the vendored WNBA LeagueConfig + LEAGUE, by value (the ports' LEAGUE for WNBA).
    lg = VMod.load("wnba", "league")
    out["league_config"] = (
        _header("league", "league_config", [("league", n) for n in ("LeagueConfig", "LEAGUE") + LEAGUE_HELPERS], None)
        + "from dataclasses import dataclass\nfrom datetime import date, datetime\n\n\n"
        + "\n\n\n".join(lg.source(n) for n in ("LeagueConfig", "LEAGUE") + LEAGUE_HELPERS)
        + "\n"
    )
    out.update(build_builders(log))
    log.append(f"mechanical: {stats}")
    log.append(f"threaded functions: {len(threaded) - len(hooks)} native + {len(hooks)} hooks")
    log.append(f"emitted definitions: {len(need)} ({sum(1 for k in need if k[0] == 'sim.smart_sim')} in smart_sim)")
    return out, log


# ---------------------------------------------------------------------------
# PASS 2: the team-advanced-stats BUILDERS. The bridge imported them from the vendored package to build
# team_advanced_stats_<season>_asof_<date>.csv when that file is missing or stale
# (`_ensure_team_advanced_stats_asof_local`). Unlike the orchestrator, the two forks differ in ALGORITHM here
# (season filtering, the game-date map, a WNBA team filter), so a divergent definition is kept VERBATIM per
# fork (`<name>__nba`, `<name>__wnba`) behind a dispatcher that takes `fork`; the bridge picks the fork exactly
# as it picked the package. Identical definitions are emitted once. Only `paths` is threaded (`orch.paths`);
# the WNBA fork's `LEAGUE` and season helpers are fork constants, ported by value into league_config.py.
BUILDERS: dict[str, str] = {
    "advanced_stats_boxscores": "compute_team_advanced_stats_from_boxscores",
    "advanced_stats_player_logs": "compute_team_advanced_stats_from_player_logs",
}
BUILDER_EXTERNAL: dict[tuple[str, str], str] = {
    ("league", "LEAGUE"): ".league_config",
    ("league", "season_year_from_date"): ".league_config",
    ("league", "season_label_from_year"): ".league_config",
    ("teams", "TEAM_TRICODES"): ".wnba_teams",
}
LEAGUE_HELPERS = ("_coerce_date", "season_start_year_from_date", "season_year_from_date", "season_label_from_year")


def _module_closure(m: VMod, root: str) -> list[str]:
    seen: list[str] = []
    stack = [root]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.append(n)
        for nm in _names(m.defs[n]):
            if nm in m.defs and nm not in seen:
                stack.append(nm)
            elif nm in m.imports:
                tgt = m.imports[nm]
                if tgt == ("config", "paths"):
                    continue
                if tgt not in BUILDER_EXTERNAL:
                    raise SystemExit(f"builder {m.rel}.{n} reaches unmapped {tgt}")
    return seen


def _rename_def(text: str, old: str, new: str) -> str:
    m = re.search(r"\b(def|class)\s+" + re.escape(old) + r"\b", text)
    if not m:
        raise SystemExit(f"cannot rename {old}")
    return text[: m.start()] + m.group(1) + " " + new + text[m.end():]


def _rename_calls(text: str, mapping: dict[str, str]) -> str:
    tree = ast.parse(text)
    offs = _line_offsets(text)
    edits = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in mapping:
            a = offs[n.lineno - 1] + n.col_offset
            edits.append((a, a + len(n.id), mapping[n.id]))
    for a, b, new in sorted(edits, reverse=True):
        text = text[:a] + new + text[b:]
    return text


def _is_fn(text: str) -> bool:
    return isinstance(ast.parse(text).body[0], ast.FunctionDef)


def build_builders(log: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    stats = {"call_sites": 0, "global_reads": 0, "local_imports": 0, "signatures": 0}
    for rel, root in BUILDERS.items():
        mods = {lg: VMod.load(lg, rel) for lg in ("nba", "wnba")}
        clos = {lg: _module_closure(mods[lg], root) for lg in mods}
        union = list(dict.fromkeys(clos["wnba"] + clos["nba"]))
        order = {n: (mods["wnba"].defs[n].lineno if n in mods["wnba"].defs else mods["nba"].defs[n].lineno) for n in union}
        union.sort(key=lambda n: order[n])
        divergent = [n for n in union if n in clos["nba"] and n in clos["wnba"] and _norm(mods["nba"].source(n)) != _norm(mods["wnba"].source(n))]
        texts: list[tuple[str, str, str]] = []  # (emitted name, source fork, text)
        for n in union:
            if n in divergent:
                for lg in ("nba", "wnba"):
                    t = _rename_def(mods[lg].source(n), n, f"{n}__{lg}")
                    t = _rename_calls(t, {d: f"{d}__{lg}" for d in divergent if d != n})
                    texts.append((f"{n}__{lg}", lg, t))
            else:
                lg = "wnba" if n in clos["wnba"] else "nba"
                t = mods[lg].source(n)
                if _names(ast.parse(t)) & set(divergent):
                    raise SystemExit(f"shared {rel}.{n} calls a divergent definition")
                texts.append((n, lg, t))
        threaded = {name for name, _, t in texts if _is_fn(t) and "paths" in _names(ast.parse(t))}
        changed = True
        while changed:
            changed = False
            for name, _, t in texts:
                if name in threaded or not _is_fn(t):
                    continue
                if any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name) and c.func.id in threaded for c in ast.walk(ast.parse(t))):
                    threaded.add(name)
                    changed = True
        local = {name for name, _, _ in texts}

        def resolve(_rel, nm, _local=local, _rel_fixed=rel):
            return (_rel_fixed, nm) if nm in _local else None

        th = {(rel, n) for n in threaded}
        emitted = [thread_and_rewrite(Gen(rel, name, t), th, resolve, stats, globals_map={"paths": "orch.paths"}) for name, _, t in texts]
        for n in [d for d in divergent if d == root]:  # internal divergent helpers are reached through their fork's root
            if not isinstance(mods["wnba"].defs[n], ast.FunctionDef):
                raise SystemExit(f"divergent non-function {rel}.{n}")
            needs = f"{n}__nba" in threaded or f"{n}__wnba" in threaded
            emitted.append(
                f"def {n}(*args, fork: str{', orch' if needs else ''}, **kwargs):\n"
                f'    """`{n}` of the vendored fork the bridge chose: "nba" -> nba_betting, anything else -> wnba_betting."""\n'
                f'    impl = {n}__nba if fork == "nba" else {n}__wnba\n'
                f"    return impl(*args{', orch=orch' if needs else ''}, **kwargs)"
            )
        m = mods["wnba"]
        lines: list[str] = []
        for node in m.top_imports:
            if isinstance(node, ast.ImportFrom) and (node.level or node.module == "__future__"):
                continue
            seg = ast.get_source_segment(m.text, node)
            if seg and seg not in lines:
                lines.append(seg)
        used: set[str] = set()
        for t in emitted:
            used |= _names(ast.parse(t))
        ext: dict[str, set[str]] = {}
        for (_mod, name), target in BUILDER_EXTERNAL.items():
            if name in used:
                ext.setdefault(target, set()).add(name)
        imp = "\n".join(lines)
        if ext:
            imp += "\n\n" + "\n".join(f"from {mod} import {', '.join(sorted(v))}" for mod, v in sorted(ext.items()))
        header = (
            '"""GENERATED by scripts/port_basketball_orchestrator.py, PASS 2 (plan P6, lane basketball-native-orchestrator).\n\n'
            f"Native port of the team-advanced-stats builder `{root}` from\n"
            f"  vendor/nba_betting_repo/src/nba_betting/{rel}.py (sha256 {_sha(SRC['nba'] / (rel + '.py'))}...)\n"
            f"  vendor/wnba_betting_repo/src/wnba_betting/{rel}.py (sha256 {_sha(SRC['wnba'] / (rel + '.py'))}...)\n"
            f"The forks differ in ALGORITHM in: {', '.join(divergent)}. Each is kept VERBATIM per fork (`__nba`, `__wnba`)\n"
            "behind a dispatcher taking `fork`. Every other definition is identical in both forks and emitted once.\n"
            "Mechanical edits only: global `paths` -> `orch.paths` (a keyword-only `orch` where needed); the WNBA fork's\n"
            "`LEAGUE`, season helpers and `TEAM_TRICODES` come from league_config.py / wnba_teams.py (copied by value).\n"
            "PARITY: scripts/basketball_orchestrator_parity.py builders (DataFrame equality on real production data).\n"
            '"""\n\nfrom __future__ import annotations\n\n'
        )
        out[rel] = header + imp + "\n\n\n" + "\n\n\n".join(emitted).rstrip() + "\n"
        log.append(f"builders {rel}: {len(texts)} definitions emitted, divergent kept per fork: {divergent}")
    tm = VMod.load("wnba", "teams")
    need = sorted(_module_closure(tm, "TEAM_TRICODES"), key=lambda n: tm.defs[n].lineno)
    out["wnba_teams"] = (
        '"""GENERATED by scripts/port_basketball_orchestrator.py, PASS 2: the WNBA fork\'s TEAM_TRICODES\n'
        f"(vendor/wnba_betting_repo/src/wnba_betting/teams.py, sha256 {_sha(SRC['wnba'] / 'teams.py')}...), by value.\n"
        '"""\n\n' + "\n\n".join(tm.source(n) for n in need) + "\n"
    )
    log.append(f"builders mechanical: {stats}")
    return out


def _literal_tuple(filename: str, name: str) -> list[str]:
    # Read a literal without importing the package (it imports the generated modules).
    tree = ast.parse(_read(DST / filename))
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
            return list(ast.literal_eval(node.value))
    raise SystemExit(f"{name} not found in {filename}")


def _header(rel: str, gname: str, keys, stats) -> str:
    w = SRC["wnba"] / (rel.replace(".", "/") + ".py")
    n = SRC["nba"] / (rel.replace(".", "/") + ".py")
    src_line = f"vendor/wnba_betting_repo/src/wnba_betting/{rel.replace('.', '/')}.py (sha256 {_sha(w)}...)"
    nba_line = f"vendor/nba_betting_repo/src/nba_betting/{rel.replace('.', '/')}.py (sha256 {_sha(n)}...)" if n.exists() else "(no NBA twin)"
    div = [f"  * {name}: {DIVERGENT[(r, name)]}" for (r, name) in keys if (r, name) in DIVERGENT]
    div += [f"  * {name} (WNBA fork only): {WNBA_ONLY[(r, name)]}" for (r, name) in keys if (r, name) in WNBA_ONLY]
    edits = [f"  * {e.name}: {e.why}" for e in EDITS if e.module == rel]
    text = (
        f'"""GENERATED by scripts/port_basketball_orchestrator.py (plan P6, lane basketball-native-orchestrator).\n\n'
        f"Native port of the definitions production EXECUTES from\n  {src_line}\n"
        f"checked definition by definition against\n  {nba_line}\n"
        f"Ported: {', '.join(name for _, name in keys)}.\n"
    )
    if div:
        text += "\nWhere the two forks differ, and how one text serves both:\n" + "\n".join(div) + "\n"
    if edits:
        text += "\nAnchored edits:\n" + "\n".join(edits) + "\n"
    text += (
        "\nMechanical edits: global `paths` / `LEAGUE` reads -> `orch.paths` / `orch.league` (runtime.OrchestratorEnv);\n"
        "a keyword-only `orch` on every function that needs it, passed at every call; relative imports re-pointed\n"
        "at this package. Calls to the 29 names Syndicate replaced go to hooks.py.\n"
    )
    if stats:
        text += f"Counts for this package: {stats}.\n"
    text += (
        "\nPARITY: scripts/basketball_orchestrator_parity.py replays recorded REAL production games through this\n"
        "orchestrator and the vendored one, same seed, and compares every leaf of the output.\n"
        '"""\n\n'
    )
    if rel == "league":
        return text
    return text + "from __future__ import annotations\n\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="regenerate in memory; exit 1 if any generated file differs from disk")
    args = ap.parse_args(argv)
    out, log = build()
    if args.check:
        bad = [g for g, t in out.items() if not (DST / f"{g}.py").exists() or (DST / f"{g}.py").read_text(encoding="utf-8") != t]
        print("PORT_CHECK " + ("OK" if not bad else f"DIFFERS: {bad}"))
        return 1 if bad else 0
    DST.mkdir(parents=True, exist_ok=True)
    for g, t in out.items():
        (DST / f"{g}.py").write_text(t, encoding="utf-8", newline="\n")
        print(f"wrote {g}.py ({t.count(chr(10))} lines)")
    for line in log:
        print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
