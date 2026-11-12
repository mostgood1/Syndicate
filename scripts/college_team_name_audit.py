"""Which college team names in the odds feed do not resolve to a school -- the check that keeps the Games rail matched.

Lane `college-odds-feed-team-names`, 2026-11-12. User: "still have college teams not matching" -- CSU Bakersfield's two
games (men's @ Western Illinois, women's @ Washington) drew chip-less "N opportunities" cards on the Games rail, because
the odds feed spells the school "CSU Bakersfield Roadrunners" and ESPN's registry "Cal State Bakersfield". The same
symptom was reported and fixed by hand on 11-03 and 11-07, and the 11-03 deploy entry already named the cure: read this
audit before a big slate, not after a user spots the card. This is that audit, committed.

WHAT IT READS (read-only), under SYNDICATE_DATA_ROOT:
  - every quote shard, `<league>_source/tracking/book_quotes/<date>.jsonl[.gz]`: each event's `away_team` / `home_team`;
  - ESPN's scoreboards, `<league>_source/data/scoreboard/scoreboard_<date>.json`, for EVIDENCE only.

WHAT IT REPORTS: every name `team_aliases.chip_join_key(league, name)` cannot resolve, with its event count and dates.
When the event's OTHER team resolves, the ESPN game that day (+-1 day) whose same-side opponent resolves to that school
names the unresolved team's ESPN spelling: that is the evidence an alias needs (an alias with no evidence is a guess).

Exit 0 when every name resolves, 1 when any does not, 2 when no quote shard was readable (unknown is not clean).

    python scripts/college_team_name_audit.py                      # both leagues, every shard on disk
    python scripts/college_team_name_audit.py --league wncaab --since 2026-11-10 --json
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LEAGUES = ("ncaab", "wncaab")


def _shard_date(name: str) -> str | None:
    stem = name[:-len(".jsonl.gz")] if name.endswith(".jsonl.gz") else name[:-len(".jsonl")] if name.endswith(".jsonl") else None
    if not stem or stem.startswith("."):
        return None
    try:
        return dt.date.fromisoformat(stem).isoformat()
    except ValueError:
        return None


def odds_events(root: Path, league: str, since: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """One record per distinct (event_id, away, home) in the league's quote shards, and how many shards were read."""
    folder = root / f"{league}_source" / "tracking" / "book_quotes"
    out: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    shards = 0
    if not folder.is_dir():
        return out, 0
    for path in sorted(folder.iterdir()):
        day = _shard_date(path.name)
        if not day or (since and day < since):
            continue
        opener = gzip.open if path.name.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
                shards += 1
                for line in handle:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(row, dict) or str(row.get("kind") or "game") != "game":
                        continue
                    key = (row.get("event_id"), row.get("away_team"), row.get("home_team"))
                    if key in seen or not (row.get("away_team") and row.get("home_team")):
                        continue
                    seen.add(key)
                    out.append({"date": str(row.get("date") or day), "event_id": row.get("event_id"),
                                "away": str(row["away_team"]), "home": str(row["home_team"])})
        except OSError:
            continue
    return out, shards


def espn_games(root: Path, league: str) -> dict[str, list[dict[str, str]]]:
    folder = root / f"{league}_source" / "data" / "scoreboard"
    by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    if not folder.is_dir():
        return by_date
    for path in sorted(folder.glob("scoreboard_*.json")):
        day = path.stem[len("scoreboard_"):]
        try:
            board = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for game in (board.get("games") if isinstance(board, dict) else board) or []:
            if not isinstance(game, dict):
                continue
            home, away = game.get("home") or {}, game.get("away") or {}
            if home.get("name") and away.get("name"):
                by_date[day].append({"home": str(home["name"]), "away": str(away["name"])})
    return by_date


def audit(root: Path, leagues: Iterable[str] = LEAGUES, since: str | None = None, resolve=None) -> dict[str, Any]:
    if resolve is None:
        from syndicate.features.shared.team_aliases import chip_join_key as resolve
    report: dict[str, Any] = {"data_root": str(root), "since": since, "leagues": {}}
    for league in leagues:
        events, shards = odds_events(root, league, since)
        games = espn_games(root, league)
        unresolved: dict[str, dict[str, Any]] = {}
        bad_events = 0
        for event in events:
            keys = {side: resolve(league, event[side]) for side in ("away", "home")}
            if all(keys.values()):
                continue
            bad_events += 1
            for side, other in (("away", "home"), ("home", "away")):
                if keys[side]:
                    continue
                entry = unresolved.setdefault(event[side], {"events": 0, "dates": set(), "espn_spelling": Counter()})
                entry["events"] += 1
                entry["dates"].add(event["date"])
                if not keys[other]:
                    continue
                day = dt.date.fromisoformat(event["date"])
                for near in (day, day - dt.timedelta(days=1), day + dt.timedelta(days=1)):
                    for game in games.get(near.isoformat(), []):
                        if resolve(league, game[other]) == keys[other]:
                            entry["espn_spelling"][game[side]] += 1
        report["leagues"][league] = {
            "shards_read": shards,
            "events": len(events),
            "events_with_an_unresolved_team": bad_events,
            "unresolved": {
                name: {"events": v["events"], "dates": sorted(v["dates"]), "espn_spelling": dict(v["espn_spelling"].most_common())}
                for name, v in sorted(unresolved.items(), key=lambda kv: (-kv[1]["events"], kv[0]))
            },
        }
    return report


def exit_code(report: dict[str, Any]) -> int:
    leagues = report.get("leagues") or {}
    if not leagues or all(not v.get("shards_read") for v in leagues.values()):
        return 2
    return 1 if any(v.get("unresolved") for v in leagues.values()) else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT", ""))
    ap.add_argument("--league", choices=LEAGUES, action="append", help="default: both")
    ap.add_argument("--since", help="first shard date to read, YYYY-MM-DD (default: every shard on disk)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if not args.data_root:
        print("set SYNDICATE_DATA_ROOT or pass --data-root", file=sys.stderr)
        return 2
    report = audit(Path(args.data_root), args.league or LEAGUES, args.since)
    code = exit_code(report)
    if args.json:
        print(json.dumps(report, indent=1, ensure_ascii=False))
        return code
    for league, v in report["leagues"].items():
        print(f"{league}: {v['events_with_an_unresolved_team']} of {v['events']} odds events have an unresolved team "
              f"({v['shards_read']} shards)")
        for name, u in v["unresolved"].items():
            print(f"  {name!r}: {u['events']} event(s) {u['dates'][0]}..{u['dates'][-1]}; ESPN spelling {u['espn_spelling'] or 'unknown'}")
    print({0: "CLEAN", 1: "UNRESOLVED NAMES", 2: "NO SHARDS READ"}[code])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
