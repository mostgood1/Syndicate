"""Measure, READ-ONLY: did our NHL lineups dress players the news collector already held OUT, and did they play?

Lane `nhl-lineup-status` (user 2026-10-16: NHL lineup building must read player status -- REMOVAL ONLY, MEASURED
FIRST). Falsification test: if OUT/IR-at-build players who were dressed mostly PLAYED, the collector's OUT is wrong
more often than right and removal is withheld.

For every date with a lineups file, a scoreboard, and collector history:

  A  DRESSED-BUT-OUT  rows of `lineups_<date>.csv` that are dressed (a line_slot, or the starting goalie) whose player
                      the collector held Out / IR / Suspended (or a posted scratch) AT OR BEFORE the build. BUILD TIME =
                      min(file mtime, the team's scheduled puck drop): the fleet rewrites today's file every cycle
                      until ~23:40 CT, so for a finished date the mtime is POST-GAME and only the puck drop is a
                      pre-game moment. Same matching code production uses (`syndicate.features.nhl.lineup_availability`).
  A' DAY-TO-DAY       the same rows held Day-To-Day (expected to play: DTD must not remove).
  C  REVERSE RISK     every player the collector held Out / IR / Suspended at puck drop whose team played that date:
                      how many PLAYED (TOI > 0 in the boxscore). This is the collector's own error rate, lineup or not.

PLAYED = in the game's api-web boxscore with TOI > 0, read from the fleet's ingestion cache
(`<nhl root>/data/ingestion_cache/boxscore_<id>.json`). `--fetch` reads a missing boxscore from api-web (free) into a
SEPARATE cache dir, never the fleet's. Prop lines = rows of `props/player_props_lines/date=<date>/oddsapi.csv`
(book x market x line) first seen before puck drop, matched by normalized name + game.

Games are split by phase from the game id (01 preseason, 02 regular, 03 playoffs) and never pooled.

    nice -n 19 python scripts/measure_nhl_lineup_status.py --data-root /home/amyn/syndicate-prod/data \\
        --start 2026-10-07 --end 2026-10-16 --json out.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date as _date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nhl import lineup_availability as la  # noqa: E402
from syndicate.features.nhl.sim_engine.hockeysim.features.props_lines import (  # noqa: E402
    initial_surname_key, normalize_name,
)

PHASES = {"01": "preseason", "02": "regular", "03": "playoffs"}
DTD = "DAY-TO-DAY"


def _read_csv(path: Path) -> List[Dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return list(csv.DictReader(fh))
    except OSError:
        return []


def _toi(value: Any) -> float:
    text = str(value or "")
    if ":" not in text:
        return 0.0
    mm, ss = text.split(":", 1)
    try:
        return int(mm) + int(ss) / 60.0
    except ValueError:
        return 0.0


def _status_class(status_text: Any) -> str:
    removal = la.removal_status(status_text)
    if removal in la.REMOVE_STATUSES:
        return removal
    text = str(status_text or "").strip().upper()
    return DTD if text == DTD else (text or "UNKNOWN")


class Boxscores:
    def __init__(self, cache_dir: Path, fetch_dir: Optional[Path]) -> None:
        self.cache_dir, self.fetch_dir = cache_dir, fetch_dir
        self.fetched = 0

    def get(self, game_id: str) -> Optional[Dict[str, Any]]:
        for folder in (self.cache_dir, self.fetch_dir):
            if folder is None:
                continue
            path = folder / f"boxscore_{game_id}.json"
            if path.is_file() and path.stat().st_size > 0:
                try:
                    return json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    pass
        if self.fetch_dir is None:
            return None
        from syndicate.features.nhl.sim_engine.hockeysim.ingestion.nhl_web import NhlWebIngestClient

        self.fetched += 1
        return NhlWebIngestClient(cache_dir=self.fetch_dir).boxscore(game_id)


def _side_players(box: Dict[str, Any], team: str) -> Optional[List[Dict[str, Any]]]:
    pbg = box.get("playerByGameStats") or {}
    for side in ("homeTeam", "awayTeam"):
        abbrev = (box.get(side) or {}).get("abbrev")
        abbrev = abbrev.get("default") if isinstance(abbrev, dict) else abbrev
        if la.team_code(abbrev) == team or str(abbrev or "").upper() == team:
            stats = pbg.get(side) or {}
            return [p for g in ("forwards", "defense", "goalies") for p in stats.get(g) or []]
    return None


def _name_of(p: Dict[str, Any]) -> str:
    name = p.get("name")
    return str(name.get("default") if isinstance(name, dict) else name or "")


def _prop_rows(props: List[Dict[str, str]], name: str, team_name: str, before: Optional[datetime]) -> Dict[str, int]:
    key, team = normalize_name(name), normalize_name(team_name)
    cutoff = la._iso(before) or "9999"
    hits = [r for r in props if normalize_name(r.get("player_name")) == key
            and team in (normalize_name(r.get("home_team")), normalize_name(r.get("away_team")))
            and str(r.get("first_seen_at") or "") <= cutoff]
    return {"rows": len({(r.get("market"), r.get("line"), r.get("book")) for r in hits}),
            "markets": len({r.get("market") for r in hits})}


def measure_date(day: str, *, nhl_root: Path, collector: la.CollectorState, boxes: Boxscores,
                 lead_minutes: int) -> Dict[str, Any]:
    processed = nhl_root / "data" / "processed"
    lineup_path = processed / f"lineups_{day}.csv"
    out: Dict[str, Any] = {"date": day, "lead_minutes": lead_minutes, "games": 0, "team_games": 0, "final_team_games": 0,
                           "phases": {}, "dressed_out": [], "dressed_dtd": [], "reverse": [], "scratch_reverse": [],
                           "feeds": Counter(), "notes": []}
    rows = _read_csv(lineup_path)
    if not rows:
        out["notes"].append("no lineups file")
        return out
    mtime = datetime.fromtimestamp(lineup_path.stat().st_mtime, timezone.utc)
    out["lineups_mtime"] = la._iso(mtime)
    goalies = {la.team_code(r.get("team")): normalize_name(r.get("goalie")) for r in _read_csv(processed / f"starting_goalies_{day}.csv")}
    props = _read_csv(nhl_root / "data" / "props" / "player_props_lines" / f"date={day}" / "oddsapi.csv")
    games = la.slate_games(day, nhl_root)
    by_team: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in rows:
        by_team[la.team_code(r.get("team"))].append(r)
    out["games"] = len({g.game_id for g in games.values()})
    for team, game in sorted(games.items()):
        team_rows = by_team.get(team) or []
        if not team_rows:
            out["notes"].append(f"{team}: on the scoreboard, no lineup rows")
            continue
        phase = PHASES.get(game.game_id[4:6], "other")
        out["phases"][phase] = out["phases"].get(phase, 0) + 1
        out["team_games"] += 1
        start = game.start_utc
        as_of = min(mtime, start) if start else mtime
        if lead_minutes:
            as_of = min(as_of, (start or mtime) - timedelta(minutes=lead_minutes))
        records, meta = collector.injuries_at(as_of)
        out["feeds"][f"{meta.get('source')}:{meta.get('feed_status')}"] += 1
        box = boxes.get(game.game_id)
        final = bool(box) and str(box.get("gameState")) in ("OFF", "FINAL")
        side = _side_players(box, team) if final else None
        played = {int(p["playerId"]): _toi(p.get("toi")) for p in side or [] if p.get("playerId") is not None}
        if final and side is not None:
            out["final_team_games"] += 1
        team_name = team_rows[0].get("team") or team

        def _dressed(r: Dict[str, str]) -> bool:
            if r.get("line_slot"):
                return True
            return r.get("position") == "G" and normalize_name(r.get("full_name")) == goalies.get(team)

        matched = la.match_records(team_rows, team, records)
        scratched = la.match_scratches(team_rows, team, collector.scratches_at(game.game_id, as_of))
        for r in team_rows:
            pid = int(r["player_id"])
            if not _dressed(r):
                continue
            hit = matched.get(pid)
            cls = _status_class(hit[0].get("status")) if hit else None
            if pid in scratched and cls not in la.REMOVE_STATUSES:
                cls, hit = "SCRATCH", ({"status": "scratched", "source_updated_at": scratched[pid].get("captured_at")}, "nhl_id")
            if cls is None:
                continue
            rec = hit[0]
            item = {"date": day, "phase": phase, "team": team, "game_id": game.game_id, "player_id": pid,
                    "player": r.get("full_name"), "slot": r.get("line_slot") or "G", "proj_toi": r.get("proj_toi"),
                    "status": rec.get("status"), "class": cls, "match": hit[1],
                    "source_updated_at": rec.get("source_updated_at"), "as_of": la._iso(as_of),
                    "comment": str(rec.get("comment") or "")[:140],
                    "played": (played.get(pid, 0.0) > 0) if final and side is not None else None,
                    "toi": round(played.get(pid, 0.0), 1) if final and side is not None else None,
                    "props": _prop_rows(props, str(r.get("full_name") or ""), team_name, start)}
            if cls == DTD:
                out["dressed_dtd"].append(item)
            elif cls in la.REMOVE_STATUSES or cls == "SCRATCH":
                out["dressed_out"].append(item)
            else:
                out["notes"].append(f"{r.get('full_name')}: dressed, status {rec.get('status')!r} (neither removed nor DTD)")
        # C: every OUT-held player on this team at this moment, lineup or not -> did he play?
        if final and side is not None:
            by_abbr: Dict[str, List[int]] = defaultdict(list)
            by_full = {normalize_name(r.get("full_name")): int(r["player_id"]) for r in team_rows}
            for p in side:
                by_abbr[initial_surname_key(_name_of(p))].append(int(p["playerId"]))

            def _played_by_name(full_name: Any) -> Optional[int]:
                pid = by_full.get(normalize_name(full_name))
                if pid is None or pid not in played:
                    cands = by_abbr.get(initial_surname_key(full_name), [])
                    pid = cands[0] if len(cands) == 1 else pid
                return pid

            # POSITIVE CONTROL for the C matcher: every lineup-file player who PLAYED must be found by the same
            # name path, or a "0 of N held-OUT played" could be the matcher's blindness, not the collector's accuracy.
            for r in team_rows:
                if played.get(int(r["player_id"]), 0.0) > 0:
                    out["control_total"] = out.get("control_total", 0) + 1
                    pid = _played_by_name(r.get("full_name"))
                    out["control_found"] = out.get("control_found", 0) + int(pid is not None and played.get(pid, 0.0) > 0)
            for (rteam, name), rec in records.items():
                if rteam != team:
                    continue
                cls = _status_class(rec.get("status"))
                if cls not in la.REMOVE_STATUSES and cls != DTD:
                    continue
                pid = _played_by_name(rec.get("athlete"))
                out["reverse"].append({"date": day, "phase": phase, "team": team, "player": rec.get("athlete"),
                                       "status": rec.get("status"), "class": cls, "as_of": la._iso(as_of),
                                       "in_lineup_file": name in by_full,
                                       "played": bool(pid is not None and played.get(pid, 0.0) > 0),
                                       "toi": round(played.get(pid, 0.0), 1) if pid is not None else 0.0,
                                       "comment": str(rec.get("comment") or "")[:140]})
            # Every POSTED scratch for this side (gameinfo latest at as_of), lineup or not -> did he play anyway?
            info = collector.scratches_at(game.game_id, as_of)
            side_key = next((s for s in ("home", "away") if info and la.team_code(info.get(s)) == team), None)
            for item in (info or {}).get(f"{side_key}_scratches") or [] if side_key else []:
                try:
                    spid = int(item.get("id"))
                except (TypeError, ValueError):
                    spid = None
                out["scratch_reverse"].append({"date": day, "team": team, "player": item.get("name"), "as_of": la._iso(as_of),
                                               "captured_at": info.get("captured_at"),
                                               "played": bool(spid is not None and played.get(spid, 0.0) > 0)})
    out["feeds"] = dict(out["feeds"])
    return out


def replay_consistency(collector: la.CollectorState) -> Dict[str, Any]:
    """Does replaying the change log to the state file's own mtime reproduce the state file?"""
    path = collector.state_path
    if path is None or not path.is_file():
        return {"checked": False, "reason": "no state file"}
    mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    state = la.dedupe_state(json.loads(path.read_text(encoding="utf-8")))
    replay = la.dedupe_state(la.replay_injury_events(collector.events(), mtime + timedelta(seconds=1)))
    a = {(k, v.get("status")) for k, v in state.items()}
    b = {(k, v.get("status")) for k, v in replay.items()}
    return {"checked": True, "state_file_at": la._iso(mtime), "state_players": len(a), "replay_players": len(b),
            "only_in_state": sorted(map(str, a - b))[:10], "only_in_replay": sorted(map(str, b - a))[:10],
            "identical": a == b}


def _dates(args: argparse.Namespace) -> List[str]:
    if args.dates:
        return [d.strip() for d in args.dates.split(",") if d.strip()]
    start, end = _date.fromisoformat(args.start), _date.fromisoformat(args.end)
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _summarise(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    table = []
    for res in results:
        out_items = [x for x in res["dressed_out"] if x["class"] != "SCRATCH"]
        scr_items = [x for x in res["dressed_out"] if x["class"] == "SCRATCH"]
        dtd_items = res["dressed_dtd"]
        rev_out = [x for x in res["reverse"] if x["class"] in la.REMOVE_STATUSES]
        rev_dtd = [x for x in res["reverse"] if x["class"] == DTD]
        table.append({
            "date": res["date"], "lead_min": res["lead_minutes"], "phases": res["phases"], "games": res["games"],
            "team_games": res["team_games"], "final_team_games": res["final_team_games"], "feeds": res["feeds"],
            "matcher_control": f"{res.get('control_found', 0)}/{res.get('control_total', 0)}",
            "dressed_out": len(out_items),
            "dressed_out_played": sum(1 for x in out_items if x["played"] is True),
            "dressed_out_not_played": sum(1 for x in out_items if x["played"] is False),
            "dressed_out_unknown": sum(1 for x in out_items if x["played"] is None),
            "dressed_out_prop_rows": sum(x["props"]["rows"] for x in out_items),
            "dressed_scratch": len(scr_items),
            "dressed_scratch_played": sum(1 for x in scr_items if x["played"] is True),
            "dressed_scratch_prop_rows": sum(x["props"]["rows"] for x in scr_items),
            "posted_scratches": len(res["scratch_reverse"]),
            "posted_scratches_played": sum(1 for x in res["scratch_reverse"] if x["played"]),
            "dressed_dtd": len(dtd_items),
            "dressed_dtd_played": sum(1 for x in dtd_items if x["played"] is True),
            "dressed_dtd_not_played": sum(1 for x in dtd_items if x["played"] is False),
            "dressed_dtd_prop_rows": sum(x["props"]["rows"] for x in dtd_items),
            "held_out_team_played": len(rev_out), "held_out_played": sum(1 for x in rev_out if x["played"]),
            "held_dtd_team_played": len(rev_dtd), "held_dtd_played": sum(1 for x in rev_dtd if x["played"]),
        })
    return table


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--nhl-root", default="", help="default <data-root>/nhl_source")
    ap.add_argument("--dates", default="")
    ap.add_argument("--start", default="2026-10-07")
    ap.add_argument("--end", default=datetime.now(timezone.utc).date().isoformat())
    ap.add_argument("--lead-minutes", default="0,180", help="as-of leads before puck drop, comma list")
    ap.add_argument("--fetch-dir", default="", help="fetch missing boxscores from api-web into THIS dir (never the fleet cache)")
    ap.add_argument("--json", default="")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 if any dressed row is held Out/IR/Suspended/scratched at build time (lead 0), "
                         "or if no date had an ok collector state -- the post-deploy verification")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root and no SYNDICATE_DATA_ROOT", flush=True)
        return 2
    data_root = Path(os.path.expanduser(args.data_root))
    nhl_root = Path(args.nhl_root) if args.nhl_root else data_root / "nhl_source"
    collector = la.CollectorState(data_root / "news")
    boxes = Boxscores(nhl_root / "data" / "ingestion_cache", Path(args.fetch_dir) if args.fetch_dir else None)
    consistency = replay_consistency(collector)
    print("REPLAY_CONSISTENCY " + json.dumps(consistency, sort_keys=True), flush=True)
    results = []
    for lead in [int(x) for x in args.lead_minutes.split(",") if x.strip()]:
        for day in _dates(args):
            results.append(measure_date(day, nhl_root=nhl_root, collector=collector, boxes=boxes, lead_minutes=lead))
    table = _summarise(results)
    for row in table:
        print("ROW " + json.dumps(row, sort_keys=True), flush=True)
    for lead in sorted({row["lead_min"] for row in table}):
        rows = [r for r in table if r["lead_min"] == lead and any(k.endswith(":ok") for k in r["feeds"])]
        total = {k: sum(r[k] for r in rows) for k in rows[0] if isinstance(rows[0][k], int) and k != "lead_min"} if rows else {}
        print(f"TOTAL lead_min={lead} dates_with_collector_state={[r['date'] for r in rows]} " + json.dumps(total, sort_keys=True), flush=True)
    for res in results:
        for item in res["dressed_out"] + res["dressed_dtd"]:
            print("PLAYER " + json.dumps(item, sort_keys=True), flush=True)
        for item in res["reverse"]:
            if item["played"] and item["class"] in la.REMOVE_STATUSES:
                print("REVERSE_PLAYED " + json.dumps(item, sort_keys=True), flush=True)
    print(f"boxscores fetched={boxes.fetched}", flush=True)
    if args.json:
        Path(args.json).write_text(json.dumps({"consistency": consistency, "table": table, "results": results,
                                               "measured_at": la._iso(datetime.now(timezone.utc))},
                                              indent=1, sort_keys=True, default=str), encoding="utf-8")
    if args.gate:
        gated = [r for r in table if r["lead_min"] == 0 and any(k.endswith(":ok") for k in r["feeds"])]
        bad = sum(r["dressed_out"] + r["dressed_scratch"] for r in gated)
        if not gated:
            print("GATE UNMEASURED: no date had an ok collector state -- not a pass", flush=True)
            return 1
        print(f"GATE {'FAIL' if bad else 'PASS'}: {bad} dressed row(s) held out at build time over "
              f"{[r['date'] for r in gated]}", flush=True)
        return 1 if bad else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
