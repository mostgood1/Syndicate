"""As-of MLB lineup projection from StatsAPI history (lane mlb-statsapi-asof-rebuild, option B).

Production mostly simmed on Rotowire "default vs RHP / vs LHP" projected lineups (175 of 208
June sides). Historical Rotowire projections are not recoverable, so for dates whose stored
inputs are gone this reproduces the same idea from data that existed before the game:

  for team T on date D facing a starter of hand h, take T's last N regular-season games
  (officialDate < D) whose opposing PROBABLE starter threw with hand h (fewer than MIN_SAME
  such games -> T's last N games of either hand). The projection is the 9 players with the
  most starts there who are on T's active roster on D; ties go to the most recent start,
  and the order is the players' mean batting slot.

Everything it reads predates D: the schedule's starting lineups of EARLIER games, probable
starters' throwing hands, and the active roster as of D (published before the game).

  python scripts/mlb_asof_lineup_projection.py --probe --data-root <fleet mlb data> \\
      --dates 2026-06-15 ... --cache ~/mlb_statsapi_asof_cache
prints how B compares with production's stored projections and with the actual lineups.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

API = "https://statsapi.mlb.com/api/v1"
N_GAMES = 15
MIN_SAME = 5


class Http:
    """GET JSON with a permanent on-disk cache keyed by URL (the inputs are historical)."""

    def __init__(self, cache: Path):
        self.cache = Path(os.path.expanduser(str(cache)))
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> dict:
        key = self.cache / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")
        if key.exists():
            blob = json.loads(key.read_text(encoding="utf-8"))
            if blob.get("url") == url:
                return blob["data"]
        for attempt in range(4):
            try:
                with urllib.request.urlopen(url, timeout=60) as r:
                    data = json.loads(r.read().decode("utf-8"))
                break
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 * (attempt + 1))
        key.write_text(json.dumps({"url": url, "data": data}), encoding="utf-8")
        return data


def season_games(http: Http, start: str, end: str) -> list[dict]:
    """Every regular-season game in [start, end] with lineups, probables and teams."""
    out = []
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    while d0 <= d1:
        chunk_end = min(d1, d0 + dt.timedelta(days=13))
        url = (f"{API}/schedule?sportId=1&gameType=R&startDate={d0}&endDate={chunk_end}"
               "&hydrate=lineups,probablePitcher,team")
        for day in http.get(url).get("dates") or []:
            for g in day.get("games") or []:
                lu = g.get("lineups") or {}
                row = {"game_pk": int(g["gamePk"]), "date": str(g.get("officialDate") or day.get("date")),
                       "game_number": int(g.get("gameNumber") or 1),
                       "status": str((g.get("status") or {}).get("detailedState") or "")}
                for side in ("away", "home"):
                    t = (g.get("teams") or {}).get(side) or {}
                    team = t.get("team") or {}
                    row[f"{side}_team_id"] = int(team.get("id") or 0)
                    row[f"{side}_name"] = str(team.get("name") or "")
                    row[f"{side}_abbr"] = str(team.get("abbreviation") or "")
                    row[f"{side}_probable"] = int((t.get("probablePitcher") or {}).get("id") or 0)
                    row[f"{side}_lineup"] = [int(p["id"]) for p in (lu.get(f"{side}Players") or []) if p.get("id")]
                out.append(row)
        d0 = chunk_end + dt.timedelta(days=1)
    return out


def pitch_hands(http: Http, ids) -> dict[int, str]:
    ids = sorted({int(i) for i in ids if i})
    hands = {}
    for k in range(0, len(ids), 150):
        part = ",".join(str(i) for i in ids[k:k + 150])
        data = http.get(f"{API}/people?personIds={part}&fields=people,id,pitchHand,code")
        for p in data.get("people") or []:
            hands[int(p["id"])] = str((p.get("pitchHand") or {}).get("code") or "R")
    return hands


def active_roster(http: Http, team_id: int, date: str) -> set[int]:
    data = http.get(f"{API}/teams/{int(team_id)}/roster?rosterType=active&date={date}")
    return {int((r.get("person") or {}).get("id") or 0) for r in data.get("roster") or []} - {0}


def team_history(games: list[dict], hands: dict[int, str]) -> dict[int, list[dict]]:
    """team_id -> its games with a starting lineup, oldest first: date, lineup, opposing hand."""
    hist = defaultdict(list)
    for g in sorted(games, key=lambda r: (r["date"], r["game_number"])):
        for side, opp in (("away", "home"), ("home", "away")):
            lineup = g[f"{side}_lineup"]
            if len(lineup) < 9:
                continue
            hist[g[f"{side}_team_id"]].append({"date": g["date"], "lineup": lineup[:9],
                                               "opp_hand": hands.get(g[f"{opp}_probable"])})
    return hist


def project(history: list[dict], date: str, opp_hand: str | None, roster: set[int] | None = None,
            n: int = N_GAMES, min_same: int = MIN_SAME) -> list[int]:
    """The projected batting order for a team on `date`, from games strictly before it."""
    prior = [h for h in history if h["date"] < date]
    same = [h for h in prior if opp_hand and h["opp_hand"] == opp_hand]
    window = (same if len(same) >= min_same else prior)[-n:]

    def tally(games):
        starts, last_seen, slots = defaultdict(int), {}, defaultdict(list)
        for i, h in enumerate(games):
            for slot, pid in enumerate(h["lineup"]):
                if roster is not None and pid not in roster:
                    continue
                starts[pid] += 1
                last_seen[pid] = i
                slots[pid].append(slot)
        return starts, last_seen, slots

    starts, last_seen, slots = tally(window)
    chosen = sorted(starts, key=lambda p: (-starts[p], -last_seen[p]))[:9]
    if len(chosen) < 9:
        # An unavailable regular can leave the same-hand window short: fill from the team's
        # recent games of either hand before the builder backfills in arbitrary roster order.
        s2, l2, sl2 = tally(prior[-n:])
        for p in sorted(s2, key=lambda p: (-s2[p], -l2[p])):
            if len(chosen) == 9:
                break
            if p not in chosen:
                chosen.append(p)
                slots[p] = slots.get(p) or sl2[p]
                starts[p] = starts.get(p, 0)
    return sorted(chosen, key=lambda p: (sum(slots[p]) / len(slots[p]), -starts[p]))


def _probe(args) -> int:
    http = Http(args.cache)
    games = season_games(http, f"{args.season}-03-01", max(args.dates))
    hands = pitch_hands(http, [g[f"{s}_probable"] for g in games for s in ("away", "home")])
    hist = team_history(games, hands)
    stored_root = Path(os.path.expanduser(args.data_root)) / "daily" / "snapshots"
    n = 0
    ov_stored = ov_actual = ov_stored_vs_actual = 0.0
    for d in sorted(set(args.dates)):
        lp = stored_root / d / "lineups.json"
        stored = {int(g["game_pk"]): g for g in (json.loads(lp.read_text()).get("games") or [])} if lp.exists() else {}
        for g in (g for g in games if g["date"] == d):
            s = stored.get(g["game_pk"])
            for side, opp in (("away", "home"), ("home", "away")):
                actual = g[f"{side}_lineup"][:9]
                sp = [int(x) for x in ((s or {}).get(f"{side}_projected_ids") or [])][:9]
                if len(actual) < 9 or len(sp) < 9:
                    continue
                proj = project(hist[g[f"{side}_team_id"]], d, hands.get(g[f"{opp}_probable"]),
                               active_roster(http, g[f"{side}_team_id"], d))
                n += 1
                ov_stored += len(set(proj) & set(sp)) / 9
                ov_actual += len(set(proj) & set(actual)) / 9
                ov_stored_vs_actual += len(set(sp) & set(actual)) / 9
    print(json.dumps({"sides": n, "B_vs_production_projection": round(ov_stored / max(1, n), 3),
                      "B_vs_actual": round(ov_actual / max(1, n), 3),
                      "production_projection_vs_actual": round(ov_stored_vs_actual / max(1, n), 3)}))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--data-root", default="")
    ap.add_argument("--dates", nargs="+", default=[])
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--cache", default="~/mlb_statsapi_asof_cache")
    args = ap.parse_args(argv)
    return _probe(args) if args.probe else 0


if __name__ == "__main__":
    raise SystemExit(main())
