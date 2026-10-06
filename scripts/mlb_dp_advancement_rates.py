"""Measure how runners move on a real ground-into-double-play (lane mlb-combined-calibration).

The sim's DP branch (simulate.py `_resolve_in_play_out_with_runners`) used to hold every
other runner in place. Its two advancement rates are MEASURED here from StatsAPI
play-by-play, never fitted:
  r2 = P(runner who started on 2B ends on 3B or scores | GIDP, 0 outs before, runner on 2B)
  r3 = P(runner who started on 3B scores               | GIDP, 0 outs before, runner on 3B)
With 1 out before, a DP ends the inning and nothing advances, so only 0-out plays count.

  python scripts/mlb_dp_advancement_rates.py --data-root <fleet mlb data> --dates 2026-06-15 ... \\
      --cache ~/mlb_pbp_cache --out rates.json
Game pks come from the stored sims for each date (daily/sims, daily/sims_pregame).
"""
from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path

FEED = "https://statsapi.mlb.com/api/v1.1/game/{pk}/feed/live"


def game_pks(data_dir: Path, date: str) -> list[int]:
    pks = set()
    for sub in ("sims", "sims_pregame"):
        for f in glob.glob(str(data_dir / "daily" / sub / date / "sim_*.json")):
            m = re.search(r"pk(\d+)", Path(f).name)
            if m:
                pks.add(int(m.group(1)))
    return sorted(pks)


def feed(pk: int, cache: Path) -> dict:
    p = cache / f"feed_{pk}.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    with urllib.request.urlopen(FEED.format(pk=pk), timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    if ((data.get("gameData") or {}).get("status") or {}).get("abstractGameState") == "Final":
        p.write_text(json.dumps(data), encoding="utf-8")
    time.sleep(0.2)
    return data


def gidp_events(data: dict) -> list[dict]:
    """One record per 0-out GIDP: where the runners who started on 2B / 3B ended."""
    out = []
    for play in ((data.get("liveData") or {}).get("plays") or {}).get("allPlays") or []:
        res = play.get("result") or {}
        if res.get("eventType") != "grounded_into_double_play":
            continue
        outs_after = int((play.get("count") or {}).get("outs") or 0)
        runners = play.get("runners") or []
        outs_on_play = sum(1 for r in runners if (r.get("movement") or {}).get("isOut"))
        if outs_after - outs_on_play != 0:
            continue
        final = {}
        for r in runners:
            mv = r.get("movement") or {}
            rid = ((r.get("details") or {}).get("runner") or {}).get("id")
            start = mv.get("originBase") or mv.get("start")
            if start not in ("2B", "3B") or rid is None:
                continue
            # A runner can appear in several movement segments; keep the last one.
            end = "out" if mv.get("isOut") else (mv.get("end") or start)
            final.setdefault(rid, {"start": start})["end"] = end
        out.append({"game_pk": (data.get("gamePk")), "runners": list(final.values())})
    return out


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def rates(events: list[dict]) -> dict:
    n2 = k2 = n3 = k3 = 0
    for e in events:
        for r in e["runners"]:
            if r["start"] == "2B":
                n2 += 1
                k2 += r["end"] in ("3B", "score")
            elif r["start"] == "3B":
                n3 += 1
                k3 += r["end"] == "score"
    return {"r2": {"k": k2, "n": n2, "rate": k2 / n2 if n2 else None, "ci95": wilson(k2, n2)},
            "r3": {"k": k3, "n": n3, "rate": k3 / n3 if n3 else None, "ci95": wilson(k3, n3)}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--dates", nargs="+", required=True)
    ap.add_argument("--cache", default="~/mlb_pbp_cache")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    data_dir = Path(os.path.expanduser(args.data_root))
    cache = Path(os.path.expanduser(args.cache))
    cache.mkdir(parents=True, exist_ok=True)
    events, games, failed, gidp_all = [], 0, 0, 0
    for d in sorted(set(args.dates)):
        for pk in game_pks(data_dir, d):
            try:
                data = feed(pk, cache)
            except Exception:
                failed += 1
                continue
            games += 1
            gidp_all += sum(1 for p in ((data.get("liveData") or {}).get("plays") or {}).get("allPlays") or []
                            if (p.get("result") or {}).get("eventType") == "grounded_into_double_play")
            events += gidp_events(data)
    rep = {"dates": sorted(set(args.dates)), "games": games, "feeds_failed": failed,
           "gidp_all_outs": gidp_all, "gidp_zero_out": len(events), **rates(events)}
    Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
