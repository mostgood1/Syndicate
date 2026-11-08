"""Does the engine's BLOWOUT rule take second-half points away on an NCAAB resume? (lane ncaab-live-totals-bias, 2026-11-08)

READ-ONLY probe of the CODE (a local run is evidence about the code, never the deployment). For a sample of real
2026-27 men's games it builds production's engine inputs (`ncaab/live_resim.build_engine_inputs`, the dated ratings,
player priors and prior calibration on the fleet disk), resumes each game at HALFTIME with the first half scored at
its prior share (total x H1_SHARE) and the home side leading by 0 / 8 / 16 / 24, and reports the simulated
second-half points (overtime included) under three engine configs:

  prod        production's config (live-odds-worker's college switches, copied from its environ, never printed)
  no_scales   prod with garbage_time_pace_scale = garbage_time_eff_scale = 1.0 (bench minutes + the x1.08 possession
              duration of `_contextual_duration_scale` still apply)
  no_blowout  prod with blowout_margin = blowout_q4_margin = 999: the blowout flag never fires

WHY: `engine.simulate_pbp_game_boxscore` sets `blowout` for a period when `q >= N_PERIODS and |margin| >= 15` (or
`q >= second_half_first_period and |margin| >= 18`). That is NBA's fourth-quarter rule; NCAAB has N_PERIODS = 2, so it
covers the WHOLE second half, decided by the margin at the half (or at the resume point inside it).

Usage (WSL, nice 19, fleet venv, from the repo root):
  nice -n 19 ~/.venvs/syndicate/bin/python scripts/ncaab_blowout_resume_probe.py --env-from-pid <live-odds-worker pid> \
      --pregame-dir <data>/ncaab_source/data/pregame_sim --dates 2026-11-05,2026-11-06,2026-11-07 --games 24 --sims 100
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import statistics
import sys
import time
import zlib
from pathlib import Path

ENV_PREFIXES = ("SYNDICATE_NCAAB_", "SYNDICATE_COLLEGE_", "SYNDICATE_DATA_ROOT", "SYNDICATE_WNCAAB_SOURCE_ROOT")
MARGINS = (0, 8, 16, 24)


def env_from_pid(pid: int) -> list[str]:
    """Copy the allowlisted keys from a process environ into this one. Returns the KEY NAMES only."""
    raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    copied = []
    for item in raw:
        if b"=" not in item:
            continue
        k, v = item.split(b"=", 1)
        key = k.decode("utf-8", "replace")
        if key.startswith(ENV_PREFIXES):
            os.environ[key] = v.decode("utf-8", "replace")
            copied.append(key)
    return sorted(copied)


def sample_games(pregame_dir: Path, dates: list[str], n: int) -> list[dict]:
    rows = []
    for d in dates:
        f = pregame_dir / f"pregame_sim_{d}.json"
        if not f.exists():
            continue
        games = (json.loads(f.read_text(encoding="utf-8")).get("games") or {})
        for eid, g in sorted(games.items()):
            h, a = g.get("home") or {}, g.get("away") or {}
            if h.get("espn_id") and a.get("espn_id"):
                rows.append({"date": d, "event_id": str(eid), "home_id": str(h["espn_id"]), "away_id": str(a["espn_id"]),
                             "home_code": h.get("abbr") or "", "away_code": a.get("abbr") or "",
                             "neutral": bool(g.get("neutral_site")), "pregame_margin": g.get("home_margin_mean")})
    if len(rows) <= n:
        return rows
    step = len(rows) / float(n)
    return [rows[int(i * step)] for i in range(n)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-from-pid", type=int, required=True)
    ap.add_argument("--pregame-dir", required=True)
    ap.add_argument("--dates", required=True)
    ap.add_argument("--games", type=int, default=24)
    ap.add_argument("--sims", type=int, default=100)
    ap.add_argument("--out", default="")
    ap.add_argument("--checkpoint", default="half", choices=("half", "tip", "h1mid", "h2mid"),
                    help="half: start of h2 (default); tip: the opening tip (the pregame sim); h1mid / h2mid: 10:00 left "
                         "in that half, first half scored pro rata at its prior share")
    ap.add_argument("--margins", default=",".join(str(m) for m in MARGINS))
    args = ap.parse_args()
    keys = env_from_pid(args.env_from_pid)
    print(f"env keys copied from pid {args.env_from_pid}: {keys}", flush=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from syndicate.features.basketball_engine.resume import GameState
    from syndicate.features.ncaab import live_resim as lr

    games = sample_games(Path(args.pregame_dir), args.dates.split(","), args.games)
    print(f"games sampled: {len(games)}  half_split={lr.half_split_enabled()} exact_target={lr.exact_target_enabled()} "
          f"mechanisms={sorted(lr.live_mechanisms_from_env())}", flush=True)
    out_rows = []
    t0 = time.time()
    for gi, g in enumerate(games):
        inputs = lr.build_engine_inputs(g["date"], g["home_id"], g["away_id"], neutral=g["neutral"],
                                        home_code=g["home_code"], away_code=g["away_code"])
        if isinstance(inputs, lr.NcaabResimRefusal):
            print(f"  [{gi}] {g['event_id']} refused {inputs.reason} {inputs.detail}", flush=True)
            continue
        prov = inputs["_provenance"]
        total = float(prov["pregameTotal"])
        cfg = inputs["cfg"]
        variants = {
            "prod": cfg,
            "no_scales": dataclasses.replace(cfg, garbage_time_pace_scale=1.0, garbage_time_eff_scale=1.0),
            "no_blowout": dataclasses.replace(cfg, blowout_margin=999, blowout_q4_margin=999),
        }
        h1_full = total * lr.H1_SHARE
        h2_full = total * (1.0 - lr.H1_SHARE)
        sign = 1 if gi % 2 == 0 else -1  # alternate which side leads
        margins = [int(x) for x in args.margins.split(",")] if args.checkpoint != "tip" else [0]
        for m in margins:
            lead = sign * m
            if args.checkpoint == "tip":
                scored, prior_rem = 0, total
                gs = GameState()
            elif args.checkpoint == "half":
                scored, prior_rem = int(round(h1_full)), h2_full
            elif args.checkpoint == "h1mid":
                scored, prior_rem = int(round(h1_full * 0.5)), h1_full * 0.5 + h2_full
            else:  # h2mid
                scored, prior_rem = int(round(h1_full + h2_full * 0.5)), h2_full * 0.5
            if args.checkpoint != "tip":
                hp_total = (scored + lead) // 2
                ap_total = scored - hp_total
                if args.checkpoint == "half":
                    gs = GameState(period=2, seconds_remaining=None, home_period_pts=(hp_total,), away_period_pts=(ap_total,))
                elif args.checkpoint == "h1mid":
                    gs = GameState(period=1, seconds_remaining=600, home_period_pts=(hp_total,), away_period_pts=(ap_total,))
                else:
                    h1h = int(round(hp_total * h1_full / scored)) if scored else 0
                    h1a = int(round(ap_total * h1_full / scored)) if scored else 0
                    gs = GameState(period=2, seconds_remaining=600, home_period_pts=(h1h, hp_total - h1h),
                                   away_period_pts=(h1a, ap_total - h1a))
            seed = zlib.crc32(f"probe|{args.checkpoint}|{g['event_id']}|{m}".encode()) & 0x7FFFFFFF
            h1 = scored
            row = {"event_id": g["event_id"], "date": g["date"], "pregame_total": total, "h1": scored, "margin": m,
                   "prior_h2": prior_rem, "pregame_margin": g["pregame_margin"], "checkpoint": args.checkpoint}
            for name, c in variants.items():
                inp = dict(inputs)
                inp["cfg"] = c
                res = lr.resim_live_game(inp, gs, sims=args.sims, base_seed=seed)
                if isinstance(res, lr.NcaabResimRefusal):
                    row[name] = None
                    continue
                row[name] = float(res["total_mean"]) - h1
            out_rows.append(row)
        print(f"  [{gi}] {g['event_id']} total={total:.1f} done ({time.time() - t0:.0f}s)", flush=True)
    if args.out:
        Path(args.out).write_text("\n".join(json.dumps(r) for r in out_rows) + "\n", encoding="utf-8")
    # summary: mean h2 points by margin and variant, and paired differences vs the prior h2 target
    for m in sorted({r["margin"] for r in out_rows}):
        rs = [r for r in out_rows if r["margin"] == m and all(r.get(v) is not None for v in ("prod", "no_scales", "no_blowout"))]
        if not rs:
            continue
        def mean_sd(vals):
            return statistics.mean(vals), (statistics.stdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else float("nan"))
        p_minus_prior = mean_sd([r["prod"] - r["prior_h2"] for r in rs])
        nb_minus_prior = mean_sd([r["no_blowout"] - r["prior_h2"] for r in rs])
        p_minus_nb = mean_sd([r["prod"] - r["no_blowout"] for r in rs])
        p_minus_ns = mean_sd([r["prod"] - r["no_scales"] for r in rs])
        print(f"[{args.checkpoint}] margin {m:2d}, {len(rs)} games: remaining prod-prior {p_minus_prior[0]:+.2f}+-{p_minus_prior[1]:.2f}  "
              f"no_blowout-prior {nb_minus_prior[0]:+.2f}+-{nb_minus_prior[1]:.2f}  prod-no_blowout {p_minus_nb[0]:+.2f}+-{p_minus_nb[1]:.2f}  "
              f"prod-no_scales {p_minus_ns[0]:+.2f}+-{p_minus_ns[1]:.2f}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
