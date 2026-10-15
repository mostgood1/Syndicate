"""Generator for syndicate/features/<league>/source_cli/ -- Syndicate's port of the vendored `<league>_betting.cli` commands that
the props refreshes run (NBA since 2026-10-12; WNBA added 2026-10-13, `--league`). The NBA story below is the original;
the NBA props refresh's game-input bootstrap runs (lane nba-source-cli-native, 2026-10-12).

`scripts/refresh_nba_oddsapi_props.py::_ensure_source_game_inputs` (once per date, when predictions_<date>.csv is
missing) and the full export run `python -m nba_betting.cli <cmd>` from vendor/nba_betting_repo. This script extracts
those commands and everything they reach into a Syndicate package that MIRRORS the vendored module layout
(`nba_betting/<m>.py` -> `source_cli/<m>.py`, subpackages included), so every relative import stays valid as written.

METHOD (shared with scripts/port_basketball_live_tick.py, whose helpers it imports):
  * scope-correct `symtable` closure per module; top-level statements that define closure names are copied VERBATIM
    in source order;
  * each module keeps its own top-level imports verbatim, except that a relative import keeps only the names the
    closure uses (those become that sibling's roots, solved to a fixed point) and `nba_betting.<m>` absolute imports
    become relative; `from . import <module>` demands the whole module;
  * top-level statements that bind nothing (calls, `if __name__`, ...) are NOT copied; every one is listed in the
    `--report`, and the ones that matter are re-stated in EDITS;
  * EDITS are anchored, must match exactly once, and are the only hand-written behaviour: the repo root (models dir)
    points at Syndicate's own copy.
Every module is validated: each global a function reads is bound, and nothing vendored is imported.

Usage:
  py -3 scripts/port_basketball_source_cli.py            # write the package
  py -3 scripts/port_basketball_source_cli.py --check    # exit 1 if the package on disk differs
  py -3 scripts/port_basketball_source_cli.py --report   # closure sizes + dropped top-level statements
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

#: Per-league configuration; `configure(code)` installs one as the module globals the generator reads.
LEAGUES: dict[str, dict] = {}

_NBA_PKG_NAME = "nba_betting"

#: The commands the props refresh runs (`_ensure_source_game_inputs`, `_run_source_predict_date`, and the full export's
#: export-game-cards). update-pbp-espn-history and build-lineup-teammate-effects were dropped 2026-10-13: lineup
#: teammate effects were retired (user decision; bf5718d3 removed their only reader) and the refreshes no longer run them.
_NBA_COMMANDS = {
    "fetch-schedule": "fetch_schedule_cmd",
    "fetch": "fetch",
    "build-features": "build_features_cmd",
    "fetch-injuries": "fetch_injuries",
    "export-game-cards": "export_game_cards_cmd",
    "predict-date": "predict_date_cmd",
}

#: The stats.nba.com schedule source inserted before fetch_schedule_2025_26 (an EDIT below).
_NBA_SCHEDULE_HELPER = '''def _current_nba_season(today=None) -> str:
    """EDIT: the season in play on `today` ('2026-27' from July 2026), the one the schedule should carry."""
    import datetime as _dt

    d = today or _dt.date.today()
    start = d.year if d.month >= 7 else d.year - 1
    return f"{start}-{str(start + 1)[-2:]}"


_STATS_SCHEDULE_CACHE: dict[str, dict[str, Any]] = {}


def _stats_schedule_payload(season: str | None = None) -> dict[str, Any]:
    """EDIT: the CDN schedule payload rebuilt from stats.nba.com ScheduleLeagueV2, which carries the same game-level fields.

    cdn.nba.com/static/json/staticData/scheduleLeagueV2*.json answers 403 to this host (fleet and Windows, with or
    without browser headers, measured 2026-10-14), so the vendored command always took the local fallback and rewrote
    the previous season's file. One request per process (cached). Raises when the season has no games yet (e.g. before
    the schedule is published), which leaves the local fallback in charge exactly as before.
    """
    season = season or _current_nba_season()
    if season in _STATS_SCHEDULE_CACHE:
        return _STATS_SCHEDULE_CACHE[season]
    from nba_api.stats.endpoints.scheduleleaguev2 import ScheduleLeagueV2

    frame = ScheduleLeagueV2(league_id="00", season=season, timeout=60).get_data_frames()[0]
    if frame is None or frame.empty:
        raise RuntimeError(f"ScheduleLeagueV2 returned no games for {season}")

    def _v(row, col):
        val = row.get(col)
        if val is None or (isinstance(val, float) and pd.isna(val)) or (isinstance(val, str) and val == ""):
            return None
        return val

    by_date: dict[str, list[dict[str, Any]]] = {}
    for _, row in frame.iterrows():
        national = [{"broadcasterName": _v(row, f"nationalBroadcasters_{i}_broadcasterDisplay")} for i in range(5)
                    if _v(row, f"nationalBroadcasters_{i}_broadcasterDisplay")]
        game = {
            "gameId": _v(row, "gameId"), "gameLabel": _v(row, "gameLabel"), "gameSubtype": _v(row, "gameSubtype"),
            "gameStatus": _v(row, "gameStatus"), "gameStatusText": _v(row, "gameStatusText"),
            "gameDateTimeUTC": _v(row, "gameDateTimeUTC"), "gameDateUTC": _v(row, "gameDateUTC"), "gameTimeUTC": _v(row, "gameTimeUTC"),
            "gameDateTimeEst": _v(row, "gameDateTimeEst"), "gameDateEst": _v(row, "gameDateEst"), "gameTimeEst": _v(row, "gameTimeEst"),
            "homeTeam": {k: _v(row, f"homeTeam_{k}") for k in ("teamId", "teamTricode", "teamCity", "teamName")},
            "awayTeam": {k: _v(row, f"awayTeam_{k}") for k in ("teamId", "teamTricode", "teamCity", "teamName")},
            "arenaName": _v(row, "arenaName"), "arenaCity": _v(row, "arenaCity"), "arenaState": _v(row, "arenaState"),
            "broadcasters": {"national": national},
        }
        by_date.setdefault(str(_v(row, "gameDate") or ""), []).append(game)
    payload = {"leagueSchedule": {"seasonYear": str(frame["seasonYear"].iloc[0] or season),
                                  "gameDates": [{"gameDate": d, "games": g} for d, g in by_date.items()]}}
    _STATS_SCHEDULE_CACHE[season] = payload
    return payload


def fetch_schedule_2025_26() -> pd.DataFrame:
'''

#: Lane source-cli-implied-prob-zero-guard (2026-10-15). Both vendored CLIs carry the same nested converter
#: `predict_date_cmd -> _merge_odds_df -> implied_prob_american`, which priced an American 0 as 100/(0+100) = 1.0 and
#: fed it to `edge_win` (scripts/probability_differential.py, measured 2026-10-15). Hardening, not a live misprice:
#: production runs predict-date with no --merge-odds, the OddsAPI consensus it merges never emits 0, and nothing in
#: Syndicate reads home_implied_prob or edge_win (fleet 2026-10-15: 0 of 166 numeric moneylines were 0 across 26
#: game_odds files). The same guard went upstream; once a re-pulled vendor/ carries it, this anchor matches 0x and the
#: generator stops on it, which is the cue to delete this EDIT.
_IMPLIED_PROB_ZERO_GUARD_EDIT = (
    "cli",
    "VENDORED DEFECT FIXED: _merge_odds_df's implied_prob_american priced an American 0 as 1.0 (100/(0+100)); 0 is not "
    "a price, so it is refused with pd.NA, the converter's existing refusal (it feeds res['home_ml'].apply)",
    "        def implied_prob_american(odds):\n            try:\n                o = float(odds)\n"
    "            except Exception:\n                return pd.NA\n            if pd.isna(o):\n                return pd.NA\n",
    "        def implied_prob_american(odds):\n            try:\n                o = float(odds)\n"
    "            except Exception:\n                return pd.NA\n"
    "            if pd.isna(o) or o == 0:  # EDIT: 0 is not an American price (it priced as 1.0)\n                return pd.NA\n",
)

#: Anchored edits: (module, why, old, new). The ONLY hand-written behaviour in the port.
_NBA_EDITS: list[tuple[str, str, str, str]] = [
    (
        "config",
        "the vendored repo root is vendor/nba_betting_repo (parents[2] of nba_betting/config.py). The port's repo root "
        "is source_cli/repo/: its models/ is a byte-identical copy of the vendored models (MODELS below). Like the "
        "vendored repo on the fleet it has no .env and no data/ (checked 2026-10-12: paths.root/.env and "
        "paths.root/data/raw/injuries.csv, the two other reads of the root, do not exist there either), and the "
        "vendored import-time reconcile_repo_data_to_active() copy is not ported (fleet dry-run: 0 of 178 to copy).",
        "def _repo_root() -> Path:\n    return Path(__file__).resolve().parents[2]\n",
        "def _repo_root() -> Path:\n    return Path(__file__).resolve().parent / \"repo\"  # EDIT: Syndicate-owned repo root (models/)\n",
    ),
    # Lane nba-schedule-current-season (user request 2026-10-14): the vendored fetch-schedule never wrote the season in
    # play. cdn.nba.com answers 403 to this host, so it always took the local fallback, which re-reads
    # schedule_2025_26.csv and writes it back (fleet file: 2024-10-22..2026-04-12, empty statuses) -- no 2026-27 game
    # reached the props refresh, the live tick's gid index or the games-history freshness trigger.
    (
        "schedule",
        "a stats.nba.com ScheduleLeagueV2 source between the (403) CDN and the local fallback, rebuilt into the CDN "
        "payload shape so the vendored parsing loop below runs unchanged",
        "def fetch_schedule_2025_26() -> pd.DataFrame:\n",
        _NBA_SCHEDULE_HELPER,
    ),
    (
        "schedule",
        "the CDN failure path tries stats.nba.com before the local fallback",
        "    try:\n        payload = _request_schedule_payload()\n    except Exception:\n        return _load_local_schedule_fallback()\n",
        "    try:\n        payload = _request_schedule_payload()\n    except Exception:\n"
        "        try:  # EDIT: the CDN answers 403 to this host; stats.nba.com serves the same feed\n"
        "            payload = _stats_schedule_payload()\n"
        "        except Exception:\n"
        "            return _load_local_schedule_fallback()\n",
    ),
    (
        "cli",
        "fetch-schedule also writes schedule_<season>.{json,csv} under the season's own name; schedule_2025_26.* stays "
        "the alias the vendored readers open by that name (the live tick's gid index, the local fallback)",
        "        df.to_csv(csv_path, index=False)\n",
        "        df.to_csv(csv_path, index=False)\n"
        "        # EDIT: the season's own name too (schedule_2026_27.*); schedule_2025_26.* stays the alias read by name\n"
        "        season_token = str(df[\"season_year\"].dropna().iloc[0]).replace(\"-\", \"_\") if \"season_year\" in df.columns and df[\"season_year\"].notna().any() else \"\"\n"
        "        if season_token and season_token != \"2025_26\":\n"
        "            df.to_json(out_dir / f\"schedule_{season_token}.json\", orient=\"records\", date_format=\"iso\")\n"
        "            df.to_csv(out_dir / f\"schedule_{season_token}.csv\", index=False)\n",
    ),
    (
        "cli",
        "VENDORED DEFECT FIXED: _load_schedule_day filtered on date_utc first and shifted that midnight-UTC date to "
        "America/Chicago, so asking for day D returned day D+1's games (fleet A/B 2026-10-14: predict-date 10-20 built an "
        "11-game slate, none of the opener's 3). Masked until now because the schedule held no current-season games. The "
        "WNBA fork of the same function already prefers date_est (the ET game date); the NBA one now does too",
        "        day_col = next((col for col in (\"date_utc\", \"date_est\", \"date\") if col in frame.columns), None)\n"
        "        if not day_col:\n            return pd.DataFrame()\n        day_frame = frame.copy()\n",
        "        day_col = next((col for col in (\"date_est\", \"date_utc\", \"date\") if col in frame.columns), None)  # EDIT: ET game date first (as the WNBA fork)\n"
        "        if not day_col:\n            return pd.DataFrame()\n        day_frame = frame.copy()\n",
    ),
    _IMPLIED_PROB_ZERO_GUARD_EDIT,
]

#: Top-level statements that bind nothing but change behaviour: kept, at their source position in the header.
_NBA_KEEP_STATEMENTS = {
    ("cli", "os.environ.setdefault('ONNXRUNTIME_LOG_SEVERITY_LEVEL', '3')"),
    ("cli", "os.environ.setdefault('ORT_DISABLE_CPUINFO', '1')"),
    ("games_npu", "warnings.filterwarnings('ignore')"),
}

#: The vendored models the port reads through paths.models, copied byte-for-byte.
MODELS_DST = "repo/models"

LEAGUES["nba"] = dict(pkg_name=_NBA_PKG_NAME, commands=_NBA_COMMANDS, edits=_NBA_EDITS, keep=_NBA_KEEP_STATEMENTS,
                      refresh="NBA props refresh")

#: WNBA (lane nba-source-cli-native, user decision 2026-10-13): the commands scripts/refresh_wnba_oddsapi_props.py
#: runs on EVERY refresh (`_ensure_source_game_inputs`, `_ensure_rotation_inputs_for_props_refresh`,
#: `_run_source_predict_date`). Its CPU `daily-update` fallback never fired in the 30 days measured (0 "predict-date
#: failed" lines) and is not ported; the refresh drops that fallback.
LEAGUES["wnba"] = dict(
    pkg_name="wnba_betting",
    commands={
        "fetch-schedule": "fetch_schedule_cmd",
        "fetch": "fetch",
        "build-features": "build_features_cmd",
        "fetch-injuries": "fetch_injuries",
        "write-pregame-expected-minutes": "write_pregame_expected_minutes_cmd",
        "predict-date": "predict_date_cmd",
    },
    edits=[
        (
            "config",
            "the vendored repo root is vendor/wnba_betting_repo (parents[2] of wnba_betting/config.py). The port's repo root "
            "is source_cli/repo/: its models/ is a byte-identical copy of the vendored models. The root's other reads -- .env, "
            "data/raw/injuries.csv and league_status's data/overrides/roster_overrides.csv -- do not exist in the vendored repo "
            "(git or the fleet, checked 2026-10-13), and the import-time reconcile copy is not ported (fleet dry-run: 0 of 288).",
            "def _repo_root() -> Path:\n    return Path(__file__).resolve().parents[2]\n",
            "def _repo_root() -> Path:\n    return Path(__file__).resolve().parent / \"repo\"  # EDIT: Syndicate-owned repo root (models/)\n",
        ),
        _IMPLIED_PROB_ZERO_GUARD_EDIT,  # the WNBA fork carries the same converter, byte for byte
    ],
    keep={  # same three as NBA, same reasons
        ("cli", "os.environ.setdefault('ONNXRUNTIME_LOG_SEVERITY_LEVEL', '3')"),
        ("cli", "os.environ.setdefault('ORT_DISABLE_CPUINFO', '1')"),
        ("games_npu", "warnings.filterwarnings('ignore')"),
    },
    refresh="WNBA props refresh",
)

MODELS_DST = "repo/models"


def configure(code: str) -> None:
    """Install league `code` as the module globals the generator reads."""
    global LEAGUE_CODE, PKG_NAME, PKG, OUT, COMMANDS, EDITS, KEEP_STATEMENTS, MODELS_SRC
    cfg = LEAGUES[code]
    LEAGUE_CODE = code
    PKG_NAME = cfg["pkg_name"]
    PKG = ROOT / "vendor" / f"{code}_betting_repo" / "src" / PKG_NAME
    OUT = ROOT / "syndicate" / "features" / code / "source_cli"
    COMMANDS = cfg["commands"]
    EDITS = cfg["edits"]
    KEEP_STATEMENTS = cfg["keep"]
    MODELS_SRC = ROOT / "vendor" / f"{code}_betting_repo" / "models"


configure("nba")

CLI_FOOTER = '\n\nif __name__ == "__main__":\n    cli()\n'


def _module_path(mod: str) -> Path:
    p = PKG / (mod.replace(".", "/") + ".py")
    return p if p.exists() else PKG / mod.replace(".", "/") / "__init__.py"


def _is_package(mod: str) -> bool:
    return (PKG / mod.replace(".", "/") / "__init__.py").exists()


def _resolve_rel(mod: str, level: int, target: str | None) -> str:
    """Module name (relative to the package root) of `from <.*level><target> import ...` written inside `mod`."""
    parts = mod.split(".")
    base = parts if _is_package(mod) else parts[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join([p for p in base if p] + ([target] if target else []))


def _rel_level_for(mod: str, target_mod: str) -> str:
    """Relative import prefix to reach package-root module `target_mod` from `mod` (mirrored layout)."""
    depth = len(mod.split(".")) - (0 if _is_package(mod) else 1)
    return "." * (depth + 1) + target_mod


def _rewrite_absolute(text: str, mod: str) -> str:
    def sub(m: re.Match) -> str:
        return f"from {_rel_level_for(mod, m.group(1))} import "

    return re.sub(rf"\bfrom {PKG_NAME}\.([\w.]+) import ", sub, text)


def _demands_in(text: str, mod: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            target = _resolve_rel(mod, node.level, node.module)
            for a in node.names:
                sub = (target + "." + a.name) if target else a.name
                if not node.module and (PKG / (sub.replace(".", "/") + ".py")).exists() or _is_package(sub) and not node.module:
                    out.setdefault(sub, set()).add("*")  # `from . import <module>`: the whole module
                elif node.module and (_is_package(target + "." + a.name) or (PKG / ((target + "." + a.name).replace(".", "/") + ".py")).exists()):
                    out.setdefault(target + "." + a.name, set()).add("*")
                else:
                    out.setdefault(target or "__init__", set()).add(a.name)
    return out


def _pure_import(node: ast.stmt) -> bool:
    """A top-level import, or a try whose body is imports only and whose handlers only rebind (the header form)."""
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.Try):
        body_ok = all(isinstance(s, (ast.Import, ast.ImportFrom)) for s in node.body)
        handlers_ok = all(isinstance(s, (ast.Import, ast.ImportFrom, ast.Assign, ast.Pass)) for h in node.handlers for s in h.body)
        return body_ok and handlers_ok and not node.orelse and not node.finalbody
    return False


def _closure(src: Path, roots: list[str], header_names: set[str]):
    """Like port_basketball_live_tick._closure, but a top-level try/if/with that binds a needed name is an ordinary
    body statement (copied in place: it may use definitions above it, e.g. games_npu's onnxruntime import)."""
    import builtins

    raw = src.read_text(encoding="utf-8-sig")
    lines = raw.splitlines()
    tree = ast.parse(raw)
    binders: dict[str, list[ast.stmt]] = {}
    for node in tree.body:
        if _pure_import(node):
            continue
        for name in _tg._bound_names(node) | ({n.id for w in ast.walk(node) for n in [w] if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)} if isinstance(node, (ast.Try, ast.If, ast.With)) else set()):
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
            raise SystemExit(f"[{src.relative_to(PKG)}] unresolved module name {name!r}")
        if isinstance(nodes[-1], (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nodes = [nodes[-1]]
        for node in nodes:
            selected[node.lineno] = node
            own = node.name if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None
            seg = _tg._segment(lines, node)
            stack.extend(_tg._module_refs(seg, own))
            if isinstance(node, (ast.Try, ast.If, ast.With)):  # names an in-place try/if imports are bound by it
                for sub in ast.walk(node):
                    if isinstance(sub, (ast.Import, ast.ImportFrom)):
                        for a in sub.names:
                            seen.add((a.asname or a.name).split(".")[0])
    return lines, selected, used_header, tree


def generate_module(mod: str, roots: set[str]) -> tuple[str, list[str]]:
    src = _module_path(mod)
    raw = src.read_text(encoding="utf-8-sig")
    tree = ast.parse(raw)
    lines = raw.split("\n")
    import_stmts = [n for n in tree.body if _pure_import(n) and not (isinstance(n, ast.ImportFrom) and n.module == "__future__")]
    header_names = set().union(*[_tg._bound_names(n) for n in import_stmts]) if import_stmts else set()
    whole = "*" in roots
    if whole:
        selected = {n.lineno: n for n in tree.body if not _pure_import(n) and not (isinstance(n, ast.Expr) and n is tree.body[0] and isinstance(n.value, ast.Constant))}
        used_header = header_names
    else:
        _lines, selected, used_header, _t = _closure(src, sorted(roots), header_names)
    dropped = []
    for n in tree.body:
        if n.lineno in selected or _pure_import(n):
            continue
        if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign, ast.AnnAssign)):
            continue  # a definition outside the closure: not needed
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant):
            continue  # docstring
        if (mod, ast.unparse(n)) in KEEP_STATEMENTS:
            continue
        dropped.append(f"{mod}:{n.lineno} {ast.unparse(n)[:120]!r}")
    header_parts = []
    keep = [n for n in tree.body if (mod, ast.unparse(n)) in KEEP_STATEMENTS]
    for node in sorted(import_stmts + keep, key=lambda n: n.lineno):
        if node in keep:
            header_parts.append(_tg._segment(lines, node))
            continue
        if isinstance(node, ast.ImportFrom) and node.level >= 1:
            keep = [a for a in node.names if (a.asname or a.name) in used_header]
            if keep:
                header_parts.append(f"from {'.' * node.level}{node.module or ''} import " + ", ".join(
                    a.name + (f" as {a.asname}" if a.asname else "") for a in keep))
            continue
        header_parts.append(_tg._segment(lines, node))
    body = "\n\n\n".join(_tg._segment(lines, selected[k]) for k in sorted(selected))
    text_body = _rewrite_absolute("\n".join(header_parts) + "\n\n\n" + body, mod)
    for emod, why, old, new in EDITS:
        if emod != mod:
            continue
        if text_body.count(old) != 1:
            raise SystemExit(f"[{mod}] EDIT ({why}) matched {text_body.count(old)}x")
        text_body = text_body.replace(old, new)
    sha = hashlib.sha256(src.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:16]  # LF-normalised: a Windows (CRLF) and a Linux checkout must stamp the same hash, or --check fails on one of them
    doc = ('"""GENERATED by scripts/port_basketball_source_cli.py -- do not edit by hand (`--check` fails on a hand edit).\n\n'
           f"Source: {src.relative_to(ROOT).as_posix()} (sha256 {sha}...), {'whole module' if whole else str(len(selected)) + ' top-level statements'},\n"
           "copied verbatim except for the import header and the EDITS listed in the generator.\n"
           '"""\n')
    has_future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body)
    text = doc + ("from __future__ import annotations\n\n" if has_future else "") + text_body + "\n"
    if mod == "cli":
        text += CLI_FOOTER
    return text, dropped


def generate() -> tuple[dict[str, str], list[str]]:
    demands: dict[str, set[str]] = {"cli": set(COMMANDS.values()) | {"cli"}}
    done: dict[str, frozenset] = {}
    outputs: dict[str, str] = {}
    dropped_all: list[str] = []
    while True:
        todo = [m for m in demands if done.get(m) != frozenset(demands[m])]
        if not todo:
            break
        for mod in todo:
            if not _module_path(mod).exists():
                raise SystemExit(f"generated code imports {mod!r}, which is not in {PKG}")
            text, dropped = generate_module(mod, demands[mod])
            outputs[mod] = text
            done[mod] = frozenset(demands[mod])
            dropped_all = [d for d in dropped_all if not d.startswith(mod + ":")] + dropped
            for dmod, names in _demands_in(text, mod).items():
                demands.setdefault(dmod, set()).update(names)
    files: dict[str, str] = {}
    for mod, text in outputs.items():
        _tg._validate(mod, text)
        rel = mod.replace(".", "/") + ("/__init__.py" if _is_package(mod) else ".py")
        files[rel] = text
    # every package directory needs an __init__ (an empty one when the vendored __init__ is not in the closure)
    for rel in list(files):
        parts = rel.split("/")[:-1]
        for i in range(1, len(parts) + 1):
            init = "/".join(parts[:i]) + "/__init__.py"
            files.setdefault(init, '"""GENERATED by scripts/port_basketball_source_cli.py (package marker)."""\n')
    files.setdefault("__init__.py", f'"""Syndicate port of the vendored {PKG_NAME} CLI commands the {LEAGUES[LEAGUE_CODE]["refresh"]} runs.\n\n'
                     'GENERATED by scripts/port_basketball_source_cli.py (lane nba-source-cli-native, 2026-10-12). Run as\n'
                     f'`python -m syndicate.features.{LEAGUE_CODE}.source_cli.cli <command>`.\n"""\n')
    return files, dropped_all


def model_files() -> dict[str, bytes]:
    import subprocess

    tracked = subprocess.run(["git", "ls-files", "--", str(MODELS_SRC.relative_to(ROOT))], capture_output=True, text=True, cwd=ROOT).stdout.split()
    out = {}
    for rel in tracked:
        src = ROOT / rel
        if src.is_file():
            out[MODELS_DST + "/" + src.relative_to(MODELS_SRC).as_posix()] = src.read_bytes()
    if not out:
        raise SystemExit(f"no tracked model files under {MODELS_SRC}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--league", choices=sorted(LEAGUES), default="nba")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()
    configure(args.league)
    files, dropped = generate()
    if args.report:
        for rel, text in sorted(files.items()):
            print(f"{text.count(chr(10)):6d}  {rel}")
        print(f"TOTAL {sum(t.count(chr(10)) for t in files.values())} lines in {len(files)} files")
        print("DROPPED top-level statements (bind nothing):")
        for d in dropped:
            print("  ", d)
        return 0
    models = model_files()
    if args.check:
        bad = [r for r, t in files.items() if not (OUT / r).exists() or (OUT / r).read_bytes().replace(b"\r\n", b"\n") != t.encode("utf-8")]
        bad += [r for r, b in models.items() if not (OUT / r).exists() or (OUT / r).read_bytes() != b]
        extra = sorted(p.relative_to(OUT).as_posix() for p in OUT.rglob("*.py") if p.relative_to(OUT).as_posix() not in files) if OUT.exists() else []
        extra += sorted(p.relative_to(OUT).as_posix() for p in (OUT / MODELS_DST).rglob("*") if p.is_file() and p.relative_to(OUT).as_posix() not in models) if (OUT / MODELS_DST).exists() else []
        print("CHECK OK" if not bad and not extra else f"CHECK FAILED differs={sorted(bad)} unexpected={extra}")
        return 0 if not bad and not extra else 1
    for stale in (OUT.rglob("*.py") if OUT.exists() else []):
        if stale.relative_to(OUT).as_posix() not in files:
            stale.unlink()
    for rel, text in files.items():
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(text.encode("utf-8"))
    for rel, data in models.items():
        dst = OUT / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    print(f"wrote {len(files)} modules + {len(models)} model files to {OUT.relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
