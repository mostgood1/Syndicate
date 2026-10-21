"""Per-team diff of the NBA SmartSim's player pool against each team's CURRENT roster (lane ``nba-current-rosters``).

For every ``smart_sim_<date>_<HOME>_<AWAY>.json`` under the NBA processed dir, and each side of it:

  * STALE    -- simulated for the team, but not on the team's current roster (``now_on`` says where ESPN has him:
                another team, or ``none``);
  * MISSING  -- on the team's current roster, not simulated;
  * MISSING_PRICED -- MISSING and a player prop is posted for him in this game's OddsAPI snapshot
                (``oddsapi_player_props_<date>.csv``): the book expects him to play.

Truth is ESPN's current team roster, fetched live (``--roster-csv`` reads a saved one instead). The sim file's own
``context.excluded_players`` stamp is reported next to MISSING so an injury exclusion is visible as one.
For each STALE player it also prints the team the 2025-26 inputs give him (``rosters_2025-26.csv`` and the last
``player_logs.csv`` row), which is what the lane's hypothesis predicts the sim used.

Exit 1 when any side has a STALE or MISSING_PRICED player (a gate), 0 when every side is clean, 2 on no sims.

    python scripts/nba_sim_roster_audit.py --date 2026-10-20 --date 2026-10-21
    python scripts/nba_sim_roster_audit.py --date 2026-10-21 --data-root ~/syndicate-prod/data --json out.json

Read-only: it writes nothing under the data root.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared import nba_current_rosters as ncr  # noqa: E402


def processed_dir(data_root: Path) -> Path:
    return Path(data_root) / "nba_source" / "data" / "processed"


def sim_files(processed: Path, date_str: str) -> List[Path]:
    return sorted(p for p in processed.glob(f"smart_sim_{date_str}_*.json") if p.stem.count("_") == 4)


def sim_sides(path: Path) -> Dict[str, Any]:
    """{'home': tri, 'away': tri, 'players': {tri: [names]}, 'excluded': {tri: set(keys)}}."""
    payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    home = str(payload.get("home") or path.stem.split("_")[3]).strip().upper()
    away = str(payload.get("away") or path.stem.split("_")[4]).strip().upper()
    players = payload.get("players") if isinstance(payload.get("players"), dict) else {}
    excluded = ((payload.get("context") or {}).get("excluded_players") or {}) if isinstance(payload.get("context"), dict) else {}
    out = {"home": home, "away": away, "players": {}, "excluded": {}}
    for side, tri in (("home", home), ("away", away)):
        out["players"][tri] = [str(p.get("player_name") or "").strip() for p in (players.get(side) or []) if str(p.get("player_name") or "").strip()]
        out["excluded"][tri] = {ncr.name_key(k) for k in (excluded.get(tri) or [])}
    return out


def roster_from_csv(path: Path) -> Dict[str, List[str]]:
    teams: Dict[str, List[str]] = defaultdict(list)
    with Path(path).open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            tri = str(r.get("TEAM_ABBREVIATION") or "").strip().upper()
            name = str(r.get("PLAYER") or r.get("PLAYER_NAME") or "").strip()
            if tri and name:
                teams[tri].append(name)
    return dict(teams)


def roster_from_espn(http_get=None) -> Dict[str, List[str]]:
    get = http_get or ncr._http_get_json
    teams: Dict[str, List[str]] = {}
    for espn_id, tri in ncr.espn_teams(get):
        payload = get(f"{ncr.ESPN_BASE}/teams/{espn_id}/roster")
        rows = ncr._athlete_rows(payload, tri, season_label="", fetched_at="", stats_ids={})
        teams[tri] = [r["PLAYER"] for r in rows]
    return teams


def priced_by_event(processed: Path, date_str: str, to_tri) -> Dict[frozenset, Set[str]]:
    """{frozenset({home_tri, away_tri}): {name_key of every player with a posted player_* line}}."""
    out: Dict[frozenset, Set[str]] = defaultdict(set)
    path = processed / f"oddsapi_player_props_{date_str}.csv"
    if not path.is_file():
        return out
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        for r in csv.DictReader(fh):
            if not str(r.get("market") or "").startswith("player_"):
                continue
            k = ncr.name_key(r.get("player_name"))
            h, a = to_tri(r.get("home_team")), to_tri(r.get("away_team"))
            if k and h and a:
                out[frozenset((h, a))].add(k)
    return out


def old_team_maps(processed: Path) -> Tuple[Dict[str, str], Dict[str, str]]:
    """({key: team in rosters_2025-26.csv}, {key: team of the newest player_logs row})."""
    roster: Dict[str, str] = {}
    old = processed / "rosters_2025-26.csv"
    if old.is_file():
        for tri, names in roster_from_csv(old).items():
            for n in names:
                roster[ncr.name_key(n)] = tri
    logs: Dict[str, Tuple[str, str]] = {}
    pl = processed / "player_logs.csv"
    if pl.is_file():
        with pl.open(encoding="utf-8", errors="replace", newline="") as fh:
            for r in csv.DictReader(fh):
                k = ncr.name_key(r.get("PLAYER_NAME"))
                d = str(r.get("GAME_DATE") or "")[:10]
                if k and d >= logs.get(k, ("", ""))[0]:
                    logs[k] = (d, str(r.get("TEAM_ABBREVIATION") or "").strip().upper())
    return roster, {k: v[1] for k, v in logs.items()}


def audit(processed: Path, dates: Iterable[str], current: Mapping[str, List[str]], to_tri) -> Dict[str, Any]:
    team_of: Dict[str, str] = {}
    for tri, names in current.items():
        for n in names:
            team_of.setdefault(ncr.name_key(n), tri)
    old_roster, old_logs = old_team_maps(processed)
    sides: List[Dict[str, Any]] = []
    for d in dates:
        priced = priced_by_event(processed, d, to_tri)
        for path in sim_files(processed, d):
            s = sim_sides(path)
            event_priced = priced.get(frozenset((s["home"], s["away"])), set())
            for tri in (s["home"], s["away"]):
                sim_names = s["players"][tri]
                sim_keys = {ncr.name_key(n): n for n in sim_names}
                cur = {ncr.name_key(n): n for n in current.get(tri, [])}
                stale = [{"player": sim_keys[k], "now_on": team_of.get(k, "none"),
                          "rosters_2025_26": old_roster.get(k, ""), "last_log_team": old_logs.get(k, "")}
                         for k in sorted(set(sim_keys) - set(cur))]
                missing_keys = sorted(set(cur) - set(sim_keys))
                missing = [{"player": cur[k], "priced": k in event_priced, "excluded_in_sim": k in s["excluded"][tri],
                            "has_history": k in old_logs} for k in missing_keys]
                sides.append({
                    "date": d, "file": path.name, "team": tri, "n_sim": len(sim_names), "n_roster": len(cur),
                    "stale": stale, "missing": missing,
                    "n_stale": len(stale), "n_missing": len(missing),
                    "n_missing_priced": sum(1 for m in missing if m["priced"]),
                    "n_overlap": len(set(sim_keys) & set(cur)),
                })
    totals = {
        "sides": len(sides),
        "sides_with_stale": sum(1 for s in sides if s["n_stale"]),
        "sides_with_missing_priced": sum(1 for s in sides if s["n_missing_priced"]),
        "stale_players": sum(s["n_stale"] for s in sides),
        "missing_players": sum(s["n_missing"] for s in sides),
        "missing_priced_players": sum(s["n_missing_priced"] for s in sides),
        "sim_players": sum(s["n_sim"] for s in sides),
        "stale_matching_2025_26_team": sum(1 for s in sides for x in s["stale"]
                                           if s["team"] in {x["rosters_2025_26"], x["last_log_team"]}),
    }
    return {"totals": totals, "sides": sides}


def _default_to_tri():
    from syndicate.features.shared.basketball_props_smart_sim import _to_tricode_local

    return lambda value: str(_to_tricode_local(value) or "").strip().upper()


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--date", action="append", required=True)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--roster-csv", default="", help="read current rosters from this CSV instead of ESPN")
    ap.add_argument("--json", default="", help="write the full report here")
    ap.add_argument("--quiet", action="store_true", help="totals and per-side counts only")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("--data-root or SYNDICATE_DATA_ROOT is required", file=sys.stderr)
        return 2
    processed = processed_dir(Path(args.data_root).expanduser())
    current = roster_from_csv(Path(args.roster_csv)) if args.roster_csv else roster_from_espn()
    print(f"current rosters: {len(current)} teams, {sum(len(v) for v in current.values())} players "
          f"({'csv ' + args.roster_csv if args.roster_csv else 'ESPN live'})")
    report = audit(processed, args.date, current, _default_to_tri())
    if not report["sides"]:
        print("no smart_sim files for " + ", ".join(args.date))
        return 2
    for s in report["sides"]:
        print(f"{s['date']} {s['file'][len('smart_sim_') + 11:-5]:<8} {s['team']}: sim {s['n_sim']:>2} roster {s['n_roster']:>2} "
              f"overlap {s['n_overlap']:>2} STALE {s['n_stale']:>2} MISSING {s['n_missing']:>2} (priced {s['n_missing_priced']})")
        if args.quiet:
            continue
        for x in s["stale"]:
            print(f"      stale   {x['player']:<28} now_on={x['now_on']:<4} rosters_2025-26={x['rosters_2025_26'] or '-':<4} last_log={x['last_log_team'] or '-'}")
        for m in s["missing"]:
            tags = [t for t, on in (("PRICED", m["priced"]), ("excluded", m["excluded_in_sim"]), ("no-history", not m["has_history"])) if on]
            print(f"      missing {m['player']:<28} {' '.join(tags)}")
    print("TOTALS " + json.dumps(report["totals"]))
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    t = report["totals"]
    return 1 if (t["stale_players"] or t["missing_priced_players"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
