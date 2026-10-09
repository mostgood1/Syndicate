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


def thread_and_rewrite(gen: Gen, threaded: set[tuple[str, str]], resolve_name, stats: dict[str, int]) -> str:
    """Apply the mechanical AST edits to one definition's text."""
    text = gen.text
    tree = ast.parse(text)
    node = tree.body[0]
    offs = _line_offsets(text)

    def pos(lineno: int, col: int) -> int:
        return offs[lineno - 1] + col

    edits: list[tuple[int, int, str]] = []
    is_fn = isinstance(node, ast.FunctionDef)
    bound = _bound_names(node) if is_fn else set()
    if is_fn:
        for g in list(GLOBALS_TO_ORCH) + ["orch"]:
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
            if n.id in GLOBALS_TO_ORCH:
                edits.append((pos(n.lineno, n.col_offset), pos(n.end_lineno, n.end_col_offset), GLOBALS_TO_ORCH[n.id]))
                stats["global_reads"] += 1
            elif id(n) not in calls_func_ids and resolve_name(gen.rel, n.id) in threaded and n.id != gen.name:
                raise SystemExit(f"{gen.rel}.{gen.name}: threaded function {n.id} used as a VALUE, not called")
        if isinstance(n, ast.ImportFrom) and n.level and n is not node:
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
        _header("league", "league_config", [("league", "LeagueConfig"), ("league", "LEAGUE")], None)
        + "from dataclasses import dataclass\n\n\n"
        + lg.source("LeagueConfig")
        + "\n\n\n"
        + lg.source("LEAGUE")
        + "\n"
    )
    log.append(f"mechanical: {stats}")
    log.append(f"threaded functions: {len(threaded) - len(hooks)} native + {len(hooks)} hooks")
    log.append(f"emitted definitions: {len(need)} ({sum(1 for k in need if k[0] == 'sim.smart_sim')} in smart_sim)")
    return out, log


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
