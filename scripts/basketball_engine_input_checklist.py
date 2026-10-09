"""GATING input checklist for Syndicate's basketball possession engine (model engine standard §1).

Lane basketball-native-engine (plan P1). Scope: the ENGINE
(``syndicate/features/basketball_engine``), meaning everything one draw of
``simulate_pbp_game_boxscore`` reads. The smart-sim layer that BUILDS those
inputs (priors, team advanced stats, calibrations) has its own checklist,
``scripts/basketball_sim_input_checklist.py``. This file does not repeat it.

For each input it asks the standard's two questions. Neither alone is enough.

  CONSUMED?   Derived from the ENGINE SOURCE by AST, never from a list of names
              I expected:
                * dataclass fields: every ``dataclasses.fields()`` of
                  EventSimConfig, LeagueParams and GameState, then whether the
                  engine reads ``cfg.<f>`` / ``getattr(cfg, "<f>")`` /
                  ``lp.<f>`` / ``state.<f>`` / ``league.<f>``;
                * player-frame columns: every string literal the engine passes
                  as a column to ``_safe_series`` / ``_player_pct`` /
                  ``_player_usage_weights`` / ``_loop_shot_share`` or tests
                  with ``in players.columns``;
                * team-adjustment keys: every literal key passed to
                  ``_adj_value``;
                * quarter-model attributes: every literal ``getattr(qr, ...)``.
  POPULATED?  Measured over a recorded corpus of REAL production engine calls
              (``scripts/record_basketball_engine_corpus.py``). A field at its
              dataclass DEFAULT counts as unfed. A column that is all-zero or
              absent counts as unfed.

CONSUMED + UNPOPULATED is the alarm, and it exits 1. Three explicit lists
(each entry carries its reason) keep the gate honest instead of permissive:
  EXPECTED_CONSTANT  engine constants that production rightly leaves at the
                     default (fallback rates, gameflow knobs). P3 owns any re-fit.
  CARRIED            fields the engine accepts and deliberately does not consume
                     yet (bonus, foul trouble), so nobody mistakes them for live.
  KNOWN_UNFED        consumed and unfed, with a named owner. Reported as UNFED,
                     never as healthy. If one of them becomes populated, the
                     gate FAILS until the entry is removed, so the list cannot
                     rot.

SUBSTRATE. The corpus is a copy of the fleet's production data root, taken at
recording time. The report names the corpus directory and its dates. A corpus
does not answer whether production holds these inputs now. Re-record for that.

    py -3 scripts/basketball_engine_input_checklist.py --corpus <dir> [--json-out report.json]
    py -3 scripts/basketball_engine_input_checklist.py --static     # consumption + wiring only (no corpus): never PASS on population
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import pickle
import sys
from dataclasses import MISSING, fields
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENGINE_SRC = ROOT / "syndicate" / "features" / "basketball_engine" / "engine.py"

EXPECTED_CONSTANT: dict[str, str] = {
    "possessions_jitter": "engine constant (per-quarter pace noise); EXONERATED as a cause of wide margins (learnings 2026-10-07)",
    "possession_alternation": "calibration lever; default = the old hardcoded 0.85; EXONERATED (learnings 2026-10-07)",
    "env_sd_scale": "calibration lever; default = the old hardcoded 0.65; EXONERATED (learnings 2026-10-07)",
    "team_prior_stacks_on_target": "NBA reads it (default True = today); WNBA ignores it (LeagueParams fixes False)",
    "base_tov_per_poss": "fallback only, used when a team carries no turnover priors",
    "base_shooting_foul_per_fga": "fallback only, used when a team carries no FGA priors",
    "base_nonshooting_foul_per_poss": "engine constant; the non-shooting foul term (P3: score-dependent fouling)",
    "base_oreb_rate": "engine constant; scaled per team by team_adj oreb_mult",
    "base_steal_share_of_tov": "engine constant",
    "base_block_rate_on_2pa": "engine constant; the legacy block mode (NBA) only",
    "blowout_margin": "gameflow constant (P3 owns the situation re-fit)",
    "blowout_q4_margin": "gameflow constant (P3 owns the situation re-fit)",
    "garbage_time_pace_scale": "gameflow constant; KNOWN DEFECT scales both teams equally (findings 2026-10-06 :405-445, P3)",
    "garbage_time_eff_scale": "gameflow constant; same known defect (P3)",
    "bench_weight_boost": "engine constant; passed to the sampler, which ignores it except in blowout_boost_bench mode",
    "record_events": "diagnostics switch; off in production by design",
}
# Engine fields that exist on the engine's EventSimConfig but are not consumed by the engine, with why.
EXPECTED_UNCONSUMED_CONFIG: dict[str, str] = {
    "reconcile_points": "vestigial in the vendored engine too: the PBP loop never reconciles (its own comment says so)",
    "reconcile_max_changes_per_quarter": "vestigial, as above",
}
CARRIED: dict[str, str] = {
    "home_team_fouls": "no bonus mechanism in the loop yet: adding one is a P3 mechanism + re-fit",
    "away_team_fouls": "as above",
    "home_in_bonus": "as above",
    "away_in_bonus": "as above",
    "shot_clock_seconds": "NCAAB hook (P4): the loop has no shot-clock mechanism",
    "team_fouls_for_bonus": "hook (P3/P4): no bonus mechanism",
    "regulation_team_minutes": "INERT in the vendored engines too: assigned to total_min, never read (pinned by test)",
}
# GameState fields are consumed but have NO production caller until P3 wires live re-sims; pregame passes the tip.
RESUME_ONLY: set[str] = {"period", "seconds_remaining", "home_period_pts", "away_period_pts", "possession",
                         "home_on_floor", "away_on_floor", "home_player_fouls", "away_player_fouls"}
KNOWN_UNFED: dict[str, str] = {}
COLUMN_FLOOR = 0.5  # share of player rows with a finite, non-zero value
ALT_COLUMNS = ({"starter_prob", "is_starter"},)  # either one feeds the same signal


# ---------------------------------------------------------------------------------------------------------------
# CONSUMED (AST over the engine source)
# ---------------------------------------------------------------------------------------------------------------


def consumed_from_source(src: str) -> dict[str, set[str]]:
    tree = ast.parse(src)
    attrs: dict[str, set[str]] = {"cfg": set(), "lp": set(), "state": set(), "league": set()}
    columns: set[str] = set()
    adj_keys: set[str] = set()
    quarter_attrs: set[str] = set()
    column_fns = {"_safe_series", "_player_pct", "_player_usage_weights", "_usage_w", "_loop_shot_share"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in attrs:
            attrs[node.value.id].add(node.attr)
        if isinstance(node, ast.Call):
            fname = node.func.id if isinstance(node.func, ast.Name) else (node.func.attr if isinstance(node.func, ast.Attribute) else "")
            lits = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if fname == "getattr" and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and isinstance(node.args[1], ast.Constant):
                owner, key = node.args[0].id, node.args[1].value
                if owner in attrs:
                    attrs[owner].add(key)
                elif owner == "qr":
                    quarter_attrs.add(key)
            if fname in column_fns:
                columns.update(lits)
            if fname == "_adj_value" and len(lits) >= 1:
                adj_keys.add(lits[0])
            if fname == "get" and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "players":
                columns.update(lits)
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str):
            if any(isinstance(c, ast.Attribute) and c.attr == "columns" for c in node.comparators):
                columns.add(node.left.value)
    return {"cfg": attrs["cfg"], "lp": attrs["lp"] | attrs["league"], "state": attrs["state"], "columns": columns, "adj_keys": adj_keys, "quarter_attrs": quarter_attrs}


# ---------------------------------------------------------------------------------------------------------------
# POPULATED (over the recorded corpus)
# ---------------------------------------------------------------------------------------------------------------


def _finite_nonzero(v: Any) -> bool:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return bool(v) and str(v).strip().lower() not in ("false", "0", "nan", "none")
    return math.isfinite(f) and f != 0.0


def measure_corpus(corpus: Path, consumed: dict[str, set[str]]) -> dict[str, Any]:
    from syndicate.features.basketball_engine.engine import EventSimConfig

    defaults = {f.name: f.default for f in fields(EventSimConfig) if f.default is not MISSING}
    games = 0
    dates: set[str] = set()
    leagues: dict[str, int] = {}
    col_rows: dict[str, int] = {c: 0 for c in consumed["columns"]}
    col_hits: dict[str, int] = {c: 0 for c in consumed["columns"]}
    total_rows = 0
    cfg_nondefault: dict[str, int] = {k: 0 for k in defaults}
    cfg_seen = 0
    adj: dict[str, int] = {k: 0 for k in consumed["adj_keys"]}
    q_attrs: dict[str, int] = {k: 0 for k in consumed["quarter_attrs"]}
    targets = pools = quarters = 0
    for path in sorted(Path(corpus).glob("*.pkl")):
        with path.open("rb") as fh:
            game = pickle.load(fh)
        kw = game["kwargs"]
        games += 1
        dates.add(f"{game['league']}:{game['date']}")
        leagues[game["league"]] = leagues.get(game["league"], 0) + 1
        for side in ("home_players", "away_players"):
            df = kw.get(side)
            if df is None:
                continue
            total_rows += len(df)
            for c in col_rows:
                if c in df.columns:
                    col_rows[c] += len(df)
                    col_hits[c] += int(sum(_finite_nonzero(v) for v in df[c].tolist()))
        cfg = kw.get("cfg")
        if cfg is not None:
            cfg_seen += 1
            for k, d in defaults.items():
                if hasattr(cfg, k) and getattr(cfg, k) != d:
                    cfg_nondefault[k] += 1
        for side in ("home_team_adj", "away_team_adj"):
            a = kw.get(side) or {}
            for k in adj:
                if k in a and _finite_nonzero(a[k]) and float(a[k]) != 1.0:
                    adj[k] += 1
        qs = kw.get("quarters") or []
        if qs:
            quarters += 1
            for k in q_attrs:
                if all(getattr(q, k, None) is not None for q in qs):
                    q_attrs[k] += 1
        if kw.get("target_home_points") is not None and kw.get("target_away_points") is not None:
            targets += 1
        if kw.get("home_lineups") or kw.get("away_lineups"):
            pools += 1
    return {
        "games": games, "dates": sorted(dates), "leagues": leagues, "player_rows": total_rows,
        "column_share_nonzero": {c: (col_hits[c] / total_rows if total_rows else 0.0) for c in col_rows},
        "column_share_present": {c: (col_rows[c] / total_rows if total_rows else 0.0) for c in col_rows},
        "cfg_games": cfg_seen, "cfg_nondefault_games": cfg_nondefault,
        "team_adj_nonneutral_sides": adj, "team_adj_sides": 2 * games,
        "quarter_attrs_games": q_attrs, "games_with_quarters": quarters,
        "games_with_targets": targets, "games_with_lineup_pools": pools,
    }


# ---------------------------------------------------------------------------------------------------------------
# WIRING (reachability: production's per-draw helper reaches THIS engine)
# ---------------------------------------------------------------------------------------------------------------


def wiring_check() -> list[str]:
    import functools

    from syndicate.features.basketball_engine import engine as native
    from syndicate.features.shared import basketball_props_smart_sim as bps

    problems: list[str] = []
    for gone in ("_import_real_events_module_local", "_call_real_events_entrypoint_local", "_LOCAL_EVENTS_MODULE", "_local_simulate_pbp_game_boxscore"):
        if hasattr(bps, gone):
            problems.append(f"basketball_props_smart_sim still defines {gone} (the vendored route / flat fallback)")
    seen: dict[str, Any] = {}
    original = native.simulate_pbp_game_boxscore

    @functools.wraps(original)
    def spy(*args, **kwargs):
        seen.update(kwargs)
        return "reached"

    native.simulate_pbp_game_boxscore = spy
    try:
        out = bps._simulate_pbp_game_boxscore_local(league_code="wnba", rng=None, home_players=None, away_players=None)
    finally:
        native.simulate_pbp_game_boxscore = original
    if out != "reached":
        problems.append("production's per-draw helper did not reach the native engine")
    elif seen.get("sample_lineup") is not bps._sample_lineup_local or getattr(seen.get("league"), "code", None) != "wnba":
        problems.append("the native engine was reached without the production sampler or with the wrong league")
    return problems


def main(argv: list[str] | None = None) -> int:
    from syndicate.features.basketball_engine.engine import EventSimConfig
    from syndicate.features.basketball_engine.league import LeagueParams
    from syndicate.features.basketball_engine.resume import GameState

    ap = argparse.ArgumentParser(description="Gating input checklist for the basketball possession engine (exit 1 on alarm).")
    ap.add_argument("--corpus", type=Path)
    ap.add_argument("--static", action="store_true")
    ap.add_argument("--json-out", type=Path)
    args = ap.parse_args(argv)
    if not args.corpus and not args.static:
        ap.error("--corpus <dir> or --static")

    consumed = consumed_from_source(ENGINE_SRC.read_text(encoding="utf-8"))
    rows: list[dict[str, Any]] = []
    alarms: list[str] = []

    def row(group: str, name: str, is_consumed: bool, status: str, detail: str = "") -> None:
        rows.append({"group": group, "field": name, "consumed": is_consumed, "status": status, "detail": detail})
        if status.startswith("ALARM"):
            alarms.append(f"{group}.{name}: {status} {detail}".strip())

    m = measure_corpus(args.corpus, consumed) if args.corpus else None
    if m is not None and m["games"] == 0:
        alarms.append(f"corpus {args.corpus} holds no games: population UNMEASURED, not zero")
        m = None

    # EventSimConfig
    for f in fields(EventSimConfig):
        c = f.name in consumed["cfg"]
        if not c:
            row("EventSimConfig", f.name, False, "ok-unconsumed" if f.name in EXPECTED_UNCONSUMED_CONFIG else "ALARM unconsumed-and-unlisted", EXPECTED_UNCONSUMED_CONFIG.get(f.name, ""))
            continue
        if f.name in EXPECTED_CONSTANT:
            row("EventSimConfig", f.name, True, "constant", EXPECTED_CONSTANT[f.name])
            continue
        if m is None:
            row("EventSimConfig", f.name, True, "UNMEASURED", "no corpus")
            continue
        share = m["cfg_nondefault_games"].get(f.name, 0) / max(1, m["cfg_games"])
        row("EventSimConfig", f.name, True, "populated" if share >= COLUMN_FLOOR else "ALARM consumed-but-at-default", f"non-default in {share:.0%} of {m['cfg_games']} games")

    # LeagueParams: populated by construction (a constant per league); the question is consumption.
    lp_consumed = consumed["lp"] | {"half_start_periods", "half_end_periods", "second_half_first_period"}
    for f in fields(LeagueParams):
        c = (f.name in lp_consumed or f.name == "code") and f.name not in CARRIED
        if f.name in ("regulation_periods",) and {"half_start_periods", "half_end_periods"} & consumed["lp"]:
            c = True
        if not c:
            if f.name in CARRIED:
                row("LeagueParams", f.name, False, "carried", CARRIED[f.name])
            elif f.name == "personal_foul_limit":
                row("LeagueParams", f.name, True, "consumed-via-resume", "_fouled_out_names (resume.py)")
            else:
                row("LeagueParams", f.name, False, "ALARM unconsumed-and-unlisted")
        else:
            row("LeagueParams", f.name, True, "constant-per-league")

    # GameState
    for f in fields(GameState):
        c = f.name in consumed["state"] or f.name in ("home_player_fouls", "away_player_fouls")
        if f.name in CARRIED:
            row("GameState", f.name, c, "carried" if not c else "ALARM carried-but-consumed", CARRIED[f.name])
        elif f.name in RESUME_ONLY:
            row("GameState", f.name, c, "resume-only" if c else "ALARM resume-field-not-consumed", "no production caller until P3; pregame passes the opening tip")
        else:
            row("GameState", f.name, c, "ALARM unlisted")

    # Columns / team adjustments / quarter model / targets / lineup pools
    alt_cols = set().union(*ALT_COLUMNS)
    if m is None:
        for c in sorted(consumed["columns"]):
            row("player_frame", c, True, "UNMEASURED", "no corpus")
    else:
        for c in sorted(consumed["columns"]):
            share = m["column_share_nonzero"][c]
            if c in alt_cols:
                group_share = max(m["column_share_present"][x] for g in ALT_COLUMNS if c in g for x in g)
                row("player_frame", c, True, "populated" if group_share >= COLUMN_FLOOR else "ALARM consumed-but-unfed", f"present {m['column_share_present'][c]:.0%}, alternatives present {group_share:.0%}")
            elif c in KNOWN_UNFED:
                row("player_frame", c, True, "UNFED-known" if share < COLUMN_FLOOR else "ALARM known-unfed-now-populated", KNOWN_UNFED[c])
            else:
                row("player_frame", c, True, "populated" if share >= COLUMN_FLOOR else "ALARM consumed-but-unfed", f"non-zero in {share:.0%} of {m['player_rows']} player rows")
        for k in sorted(consumed["adj_keys"]):
            share = m["team_adj_nonneutral_sides"][k] / max(1, m["team_adj_sides"])
            row("team_adj", k, True, "populated" if share >= COLUMN_FLOOR else ("UNFED-known" if k in KNOWN_UNFED else "ALARM consumed-but-unfed"), f"non-neutral on {share:.0%} of {m['team_adj_sides']} team-sides" + (f" -- {KNOWN_UNFED[k]}" if k in KNOWN_UNFED else ""))
        for k in sorted(consumed["quarter_attrs"]):
            share = m["quarter_attrs_games"][k] / max(1, m["games"])
            row("quarters", k, True, "populated" if share >= COLUMN_FLOOR else "ALARM consumed-but-unfed", f"in {share:.0%} of {m['games']} games")
        for name, n in (("targets", m["games_with_targets"]), ("lineup_pools", m["games_with_lineup_pools"])):
            share = n / max(1, m["games"])
            if name in KNOWN_UNFED:
                row("call", name, True, "UNFED-known" if share < COLUMN_FLOOR else "ALARM known-unfed-now-populated", f"in {share:.0%} of {m['games']} games -- {KNOWN_UNFED[name]}")
            else:
                row("call", name, True, "populated" if share >= COLUMN_FLOOR else "ALARM consumed-but-unfed", f"in {share:.0%} of {m['games']} games")

    wiring = wiring_check()
    alarms.extend(f"wiring: {w}" for w in wiring)
    report = {
        "substrate": f"corpus:{args.corpus}" if args.corpus else "static (no corpus): population UNMEASURED",
        "corpus": None if m is None else {k: m[k] for k in ("games", "dates", "leagues", "player_rows")},
        "rows": rows,
        "wiring_problems": wiring,
        "alarms": alarms,
        "verdict": "FAIL" if alarms else ("PASS" if m is not None else "STATIC-ONLY"),
    }
    width = max(len(r["group"]) + len(r["field"]) for r in rows) + 2
    for r in rows:
        print(f"{(r['group'] + '.' + r['field']).ljust(width)} {'C' if r['consumed'] else '-'} {r['status']:<32} {r['detail']}")
    print(json.dumps({k: report[k] for k in ("substrate", "corpus", "wiring_problems", "alarms", "verdict")}, indent=2))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 1 if report["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
