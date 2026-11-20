"""How often a neutral-site college basketball game's board rows were the REVERSE of its live re-sim lane, and dark.

Lane college-neutral-site-live-join (2026-11-19). READ-ONLY. Run on the fleet, at nice 19, with the fleet's code:

    cd ~/Syndicate && PYTHONPATH=$HOME/Syndicate SYNDICATE_DATA_ROOT=$HOME/syndicate-prod/data \\
        nice -n 19 ~/.venvs/syndicate/bin/python <this file> --league ncaab --start 2026-11-02 --end 2026-11-19

Per Central date, three sources, each named in the output:
- ESPN's own orientation: the public scoreboard (`ncaab/slate.SCOREBOARD_URL`, the GET the slate makes every minute),
  parsed by `slate.parse_scoreboard` BEFORE `orient_neutral_site_games`. That is the orientation the live re-sim
  publishes (`ncaab/live_resim._espn_names` reads the same ESPN event's `homeAway`). `--evidence` cross-checks it
  against the lanes the re-sim actually wrote (`live_evidence/<league>/<date>.jsonl`, from 11-09).
- The slate artifact (`scoreboard_<date>.json`): its last write's games and `reoriented_neutral_site`.
- The live gameline ledger (`live_gameline_ledger_<date>.jsonl`, plus the next date's for a game past midnight): the
  board rows' OWN orientation, and whether a full-game row ever carried the model. A full-game row the join missed is
  never written there, but the game's segment rows are (refused `segment_pricing_disabled`), so a dark game still
  shows up -- with no full-game model row.

A game is REVERSED when its ledger rows read (ESPN home @ ESPN away); DARK-WHILE-REVERSED when no full-game row in that
orientation carried a model. A game can carry both orientations (WVU / Florida 11-19 flipped mid-game).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from collections import defaultdict
from pathlib import Path


def _key(league: str, name: str) -> str:
    from syndicate.features.shared.team_aliases import chip_join_key

    text = str(name or "").strip()
    return chip_join_key(league, text) or text.lower()


def _espn_games(league: str, date: str) -> list[dict]:
    from syndicate.features.ncaab import slate

    url = (slate.SCOREBOARD_URL if league == "ncaab" else slate._league(league).scoreboard_url)
    payload = slate._fetch_json(url.format(compact=date.replace("-", "")))
    games, _dropped = slate.parse_scoreboard(payload, d1_ids=slate._d1_ids(league))
    return games


def _ledger_rows(root: Path, league: str, date: str):
    day = dt.date.fromisoformat(date)
    for d in (day, day + dt.timedelta(days=1)):
        path = root / f"{league}_source/data/live_gameline_ledger/live_gameline_ledger_{d.isoformat()}.jsonl"
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    yield d.isoformat(), json.loads(line)
                except ValueError:
                    continue


def _evidence_orientation(root: Path, league: str, date: str) -> dict[str, tuple[str, str]]:
    path = root / f"live_evidence/{league}/{date}.jsonl"
    out: dict[str, tuple[str, str]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("home") and row.get("away"):
                out.setdefault(str(row.get("event_id")), (_key(league, row["away"]), _key(league, row["home"])))
    return out


def run(league: str, start: str, end: str, root: Path) -> dict:
    day, last = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    totals = defaultdict(int)
    per_date = []
    games_out = []
    while day <= last:
        date = day.isoformat()
        day += dt.timedelta(days=1)
        slate_path = root / f"{league}_source/data/scoreboard/scoreboard_{date}.json"
        if not slate_path.exists():
            per_date.append({"date": date, "slate": "absent"})
            continue
        slate_payload = json.loads(slate_path.read_text(encoding="utf-8"))
        slate_games = {str(g.get("event_id")): g for g in slate_payload.get("games") or []}
        try:
            espn = {str(g.get("event_id")): g for g in _espn_games(league, date)}
        except Exception as exc:  # noqa: BLE001
            per_date.append({"date": date, "espn": f"fetch failed: {type(exc).__name__}"})
            continue
        evidence = _evidence_orientation(root, league, date)

        # Ledger rows by unordered canonical pair -> orientation -> (rows, full-game rows with a model).
        ledger: dict[frozenset, dict[tuple[str, str], list[int]]] = defaultdict(lambda: defaultdict(lambda: [0, 0, 0]))
        for _d, row in _ledger_rows(root, league, date):
            a, h = _key(league, row.get("away_team")), _key(league, row.get("home_team"))
            if not a or not h or a == h:
                continue
            cell = ledger[frozenset((a, h))][(a, h)]
            cell[0] += 1
            if str(row.get("segment") or "") in ("full", "full_game", "game"):
                cell[1] += 1
                if row.get("model_home_win_prob") is not None:
                    cell[2] += 1

        stats = defaultdict(int)
        stats["slate_games"] = len(slate_games)
        stats["slate_reoriented_field"] = int(slate_payload.get("reoriented_neutral_site") or 0)
        for eid, game in espn.items():
            ea, eh = _key(league, game["away"]["name"]), _key(league, game["home"]["name"])
            neutral = bool(game.get("neutral_site"))
            s = slate_games.get(eid)
            slate_reoriented = bool(s) and (_key(league, s["away"]["name"]), _key(league, s["home"]["name"])) == (eh, ea)
            if eid in evidence:
                stats["evidence_games"] += 1
                stats["evidence_agrees_espn"] += 1 if evidence[eid] == (ea, eh) else 0
            orient = ledger.get(frozenset((ea, eh)))
            live = bool(orient)
            direct, rev = (orient or {}).get((ea, eh)), (orient or {}).get((eh, ea))
            stats["espn_games"] += 1
            stats["neutral"] += neutral
            stats["slate_reoriented"] += slate_reoriented
            stats["live_with_rows"] += live
            if neutral:
                stats["neutral_live"] += live
            if rev:
                stats["reversed_live"] += 1
                stats["reversed_live_neutral"] += neutral
                dark = rev[2] == 0
                stats["dark_while_reversed"] += dark
                games_out.append({"date": date, "event_id": eid, "espn": f"{game['away']['name']} @ {game['home']['name']}",
                                  "neutral": neutral, "slate_reoriented": slate_reoriented,
                                  "reversed_rows": rev[0], "reversed_full_rows": rev[1], "reversed_full_with_model": rev[2],
                                  "direct_rows": (direct or [0])[0], "direct_full_with_model": (direct or [0, 0, 0])[2],
                                  "dark_while_reversed": dark})
            if direct and not rev:
                stats["direct_live"] += 1
                stats["direct_live_dark"] += direct[2] == 0
                if neutral:
                    stats["direct_live_neutral"] += 1
        for k, v in stats.items():
            totals[k] += v
        per_date.append({"date": date, **stats})
    return {"league": league, "start": start, "end": end, "totals": dict(totals), "per_date": per_date,
            "reversed_games": games_out}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--league", default="ncaab", choices=("ncaab", "wncaab"))
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--root", default=os.environ.get("SYNDICATE_DATA_ROOT") or str(Path.home() / "syndicate-prod" / "data"))
    ap.add_argument("--json", help="write the full result here")
    args = ap.parse_args()
    out = run(args.league, args.start, args.end, Path(args.root))
    if args.json:
        Path(args.json).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"league={out['league']} {out['start']}..{out['end']} totals={json.dumps(out['totals'], sort_keys=True)}")
    for d in out["per_date"]:
        print(json.dumps(d, sort_keys=True))
    for g in out["reversed_games"]:
        print("REVERSED", json.dumps(g, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
