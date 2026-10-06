"""Measure batted-ball baserunning rates from StatsAPI play-by-play (lane mlb-combined-calibration).

The sim's non-hit in-play resolver (simulate.py `_resolve_in_play_out_with_runners`) has
rates that are MEASURED here, never fitted:

  r2  P(runner on 2B ends on 3B or scores | GIDP, 0 outs before)      bip_dp_r2_to_3b_rate
  r3  P(runner on 3B scores               | GIDP, 0 outs before)      bip_dp_r3_scores_rate
  fc  P(force out / FC out | ground ball, runner on 1B, 0-1 outs,
        not a GIDP)                                                    bip_fc_rate
  sf  P(sac fly | fly+pop (or line) out-or-error, runner on 3B,
        0-1 outs)                                                      bip_sf_rate_flypop / _line
  roe P(batter reaches on error | field_out or field_error), per
        trajectory: ground / line / fly+pop (bunts excluded)          bip_roe_rate_ground / _line / _air

THE BASE STATE BEFORE A PLAY comes from the previous play's `matchup.postOn*` within the
same half-inning. A play's `runners` list holds only runners who MOVED: a runner who held
on 3rd during a popup is absent from it, so selecting plays by `runners` keeps only the
plays where he moved and biases every advancement rate up (the first version of this
script did exactly that: sac flies 110/116 with 2 popups in 316 games). A runner who is
on base before the play and absent from `runners` held his base.
Stolen bases during the at-bat are not replayed (the previous play's post-state is used).

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
BASES = (("postOnFirst", "1B"), ("postOnSecond", "2B"), ("postOnThird", "3B"))


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


def plays_with_state(data: dict):
    """Yield (pre_bases {base: runner_id}, outs_before, play) for every play."""
    prev = None
    for play in ((data.get("liveData") or {}).get("plays") or {}).get("allPlays") or []:
        a = play.get("about") or {}
        half = (a.get("inning"), a.get("halfInning"))
        if prev is not None and prev[0] == half:
            pre, outs_before = prev[1], prev[2]
        else:
            pre, outs_before = {}, 0
        yield pre, outs_before, play
        m = play.get("matchup") or {}
        post = {base: (m.get(k) or {}).get("id") for k, base in BASES if (m.get(k) or {}).get("id")}
        prev = (half, post, int((play.get("count") or {}).get("outs") or 0))


def final_base(play: dict, runner_id: int, start: str) -> str:
    """Where a runner on `start` ended the play: his last movement, else he held."""
    end = start
    for r in play.get("runners") or []:
        if ((r.get("details") or {}).get("runner") or {}).get("id") != runner_id:
            continue
        mv = r.get("movement") or {}
        end = "out" if mv.get("isOut") else (mv.get("end") or end)
    return end


def trajectory(play: dict):
    hit = [e.get("hitData") for e in play.get("playEvents") or [] if e.get("hitData")]
    return hit[-1].get("trajectory") if hit else None


_FC_YES = ("force_out", "fielders_choice_out")
_FC_NO = ("field_out", "field_error", "fielders_choice")
_SF_YES = ("sac_fly", "sac_fly_double_play")
_SF_ALL = _SF_YES + ("field_out", "double_play", "field_error")


def collect(data: dict, acc: dict) -> None:
    for pre, outs_before, play in plays_with_state(data):
        ev = (play.get("result") or {}).get("eventType")
        traj = trajectory(play)
        if ev == "grounded_into_double_play":
            acc["gidp_all"] += 1
            if outs_before == 0:
                acc["gidp_zero_out"] += 1
                if pre.get("2B"):
                    acc["r2"].append(final_base(play, pre["2B"], "2B") in ("3B", "score"))
                if pre.get("3B"):
                    acc["r3"].append(final_base(play, pre["3B"], "3B") == "score")
        if pre.get("1B") and outs_before <= 1 and traj == "ground_ball" and ev in _FC_YES + _FC_NO + ("grounded_into_double_play",):
            acc["grounders"].append(ev)
        if pre.get("3B") and outs_before <= 1 and traj in ("fly_ball", "popup", "line_drive") and ev in _SF_ALL:
            acc["airballs"].append((traj, ev))
        if ev in ("field_out", "field_error") and traj in ("ground_ball", "line_drive", "fly_ball", "popup"):
            acc["roe"].append((traj, ev == "field_error"))


def wilson(k: int, n: int) -> list[float]:
    if n == 0:
        return [float("nan"), float("nan")]
    z, p = 1.96, k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [c - h, c + h]


def share(k: int, n: int) -> dict:
    return {"k": k, "n": n, "rate": k / n if n else None, "ci95": wilson(k, n)}


def summarise(acc: dict) -> dict:
    g = acc["grounders"]
    k = sum(1 for e in g if e in _FC_YES)
    n = sum(1 for e in g if e in _FC_YES + _FC_NO)
    gd = sum(1 for e in g if e == "grounded_into_double_play")
    air = acc["airballs"]

    def sf(trajs):
        return share(sum(1 for t, e in air if t in trajs and e in _SF_YES), sum(1 for t, _ in air if t in trajs))

    return {"gidp_all_outs": acc["gidp_all"], "gidp_zero_out": acc["gidp_zero_out"],
            "r2": share(sum(acc["r2"]), len(acc["r2"])), "r3": share(sum(acc["r3"]), len(acc["r3"])),
            "fc": share(k, n), "dp_conversion_info_only": share(gd, gd + n),
            "fc_counts": {e: g.count(e) for e in sorted(set(g))},
            "sf_flypop": sf(("fly_ball", "popup")), "sf_line": sf(("line_drive",)),
            "sf_info": {"fly_ball": sf(("fly_ball",)), "popup": sf(("popup",))},
            **{f"roe_{name}": share(sum(1 for t, e in acc["roe"] if t in trajs and e), sum(1 for t, _ in acc["roe"] if t in trajs))
               for name, trajs in (("ground", ("ground_ball",)), ("line", ("line_drive",)), ("air", ("fly_ball", "popup")))}}


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
    acc = {"gidp_all": 0, "gidp_zero_out": 0, "r2": [], "r3": [], "grounders": [], "airballs": [], "roe": []}
    games = failed = 0
    for d in sorted(set(args.dates)):
        for pk in game_pks(data_dir, d):
            try:
                data = feed(pk, cache)
            except Exception:
                failed += 1
                continue
            games += 1
            collect(data, acc)
    rep = {"dates": sorted(set(args.dates)), "games": games, "feeds_failed": failed, **summarise(acc)}
    Path(args.out).write_text(json.dumps(rep, indent=1), encoding="utf-8")
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
