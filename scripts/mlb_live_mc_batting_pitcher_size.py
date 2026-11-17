"""Size the MLB live-MC batting-side pitcher defect on recorded statsapi feeds.

Lane `mlb-live-mc-batting-pitcher` (side finding of todo #814). READ-ONLY: it
reads final `feed_live` feeds and the day's roster snapshots, and writes JSON to
--out. It changes nothing on the fleet.

THE DEFECT. `_live_mc_projection` (live_lens_port/app_slice.py) passes
`estimate_live` only the FIELDING team's current pitcher, so `_build_initial_state`
(sim_engine/live_mc.py) seeds the BATTING team with its starter. When that
starter has already been pulled, the sims put him back on the mound for his
team's next fielding half.

WHAT IT MEASURES.
  1. FREQUENCY, all feeds: the share of plate-appearance starts (a proxy for
     live ticks, which fire on a timer through the whole game) at which the
     batting team's last-used pitcher is not its starter. Broken out by inning.
  2. EFFECT, a sample of those ticks on games with a roster snapshot: the same
     LiveSituation run three ways, `--sims` each, through the app's own
     `_roster_from_snapshot_side` + `estimate_live` + `_forward_live_cfg_kwargs`:
       off   = batting side's id unset (what production does), seed s
       on    = batting side's id = its last-used pitcher,     seed s
       null  = off again with seed s+1 (the noise floor of |off - on|)
     It also reads, from the `off` arm, how many outs the PULLED starter records
     in the sims (it should be 0).

Not reproduced (identical in every arm, so they cannot make the arms differ):
the current count and per-inning pitch counts (each tick is a PA start).

Run on the fleet host at Idle priority, e.g. from WSL:
    PYTHONPATH=<checkout> nice -n 19 ~/.venvs/syndicate/bin/python \
        scripts/mlb_live_mc_batting_pitcher_size.py --out /mnt/c/tmp/mlbbp/size.json
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

DEFAULT_MLB = os.path.expanduser("~/syndicate-prod/data/mlb_source/source_artifacts/data")


def _load_feed(path: str) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def _slot(box_side: dict, pid: int):
    row = (box_side.get("players") or {}).get(f"ID{pid}") or {}
    raw = str(row.get("battingOrder") or "")
    if raw.isdigit():
        return int(raw) // 100 - 1
    return None


def replay_ticks(feed: dict):
    """One tick per plate-appearance start, with the state BEFORE that PA."""
    plays = (((feed.get("liveData") or {}).get("plays") or {}).get("allPlays")) or []
    box = ((feed.get("liveData") or {}).get("boxscore") or {}).get("teams") or {}
    starters = {}
    for side in ("away", "home"):
        pl = (box.get(side) or {}).get("pitchers") or []
        starters[side] = int(pl[0]) if pl else None
    pitches = defaultdict(int)
    bf = defaultdict(int)
    last_pitcher = {"away": None, "home": None}  # team's most recent pitcher on the mound
    last_slot = {"away": None, "home": None}
    away_score = home_score = 0
    outs = 0
    bases = {}  # base -> runner id
    prev_half = None
    for play in plays:
        about = play.get("about") or {}
        inning = int(about.get("inning") or 0)
        top = bool(about.get("isTopInning"))
        half_key = (inning, top)
        if half_key != prev_half:
            outs, bases, prev_half = 0, {}, half_key
        batting = "away" if top else "home"
        fielding = "home" if top else "away"
        mu = play.get("matchup") or {}
        batter = int((mu.get("batter") or {}).get("id") or 0)
        pitcher = int((mu.get("pitcher") or {}).get("id") or 0)
        if pitcher:
            last_pitcher[fielding] = pitcher
        slot = _slot(box.get(batting) or {}, batter)
        if slot is not None:
            last_slot_batting = slot
        else:
            last_slot_batting = ((last_slot[batting] + 1) % 9) if last_slot[batting] is not None else 0
        other_next = ((last_slot[fielding] + 1) % 9) if last_slot[fielding] is not None else 0
        if play.get("result", {}).get("type") == "atBat" and outs < 3 and inning >= 1:
            yield {
                "inning": inning, "top": top, "outs": outs,
                "bases": dict(bases),
                "away_score": away_score, "home_score": home_score,
                "batting": batting, "fielding": fielding,
                "fielding_pitcher": pitcher,
                "batting_last_pitcher": last_pitcher[batting],
                "starters": dict(starters),
                "batting_slot": last_slot_batting, "fielding_next_slot": other_next,
                "pitches": dict(pitches), "bf": dict(bf),
            }
        # advance the state past this play
        for ev in play.get("playEvents") or []:
            if ev.get("isPitch"):
                pid = int(((ev.get("details") or {}).get("pitcherId")) or 0) or pitcher
                pitches[pid] += 1
        if pitcher:
            bf[pitcher] += 1
        if slot is not None:
            last_slot[batting] = slot
        last_end = {}
        for r in play.get("runners") or []:
            rid = int(((r.get("details") or {}).get("runner") or {}).get("id") or 0)
            mv = r.get("movement") or {}
            last_end[rid] = None if mv.get("isOut") else mv.get("end")
        for b in list(bases):
            if bases[b] in last_end:
                del bases[b]
        for rid, end in last_end.items():
            if end in ("1B", "2B", "3B"):
                bases[end] = rid
        res = play.get("result") or {}
        away_score = int(res.get("awayScore") or away_score)
        home_score = int(res.get("homeScore") or home_score)
        outs = int((play.get("count") or {}).get("outs") or outs)


def _base_state(bases: dict):
    """The app's own reader, fed the same `offense` shape the live snapshot carries."""
    from syndicate.features.mlb.live_lens_port.app_slice import _live_base_state
    offense = {k: {"id": bases.get(b)} for k, b in (("first", "1B"), ("second", "2B"), ("third", "3B")) if bases.get(b)}
    return _live_base_state({"offense": offense})


def _roster_doc(snap_dir: str, game_pk: int, away: str, home: str):
    cands = glob.glob(os.path.join(snap_dir, f"roster_*_pk{game_pk}_*.json")) + glob.glob(
        os.path.join(snap_dir, f"roster_*_pk{game_pk}.json"))
    if not cands:
        cands = glob.glob(os.path.join(snap_dir, f"roster_*_{away}_at_{home}*.json"))
        if len(cands) != 1:
            return None
    with open(sorted(cands)[0], encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mlb-data", default=DEFAULT_MLB)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sims", type=int, default=300)
    ap.add_argument("--ticks-per-game", type=int, default=2)
    ap.add_argument("--max-games", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20261116)
    args = ap.parse_args()

    feeds = sorted(glob.glob(os.path.join(args.mlb_data, "raw/statsapi/feed_live/2026/*/*.json.gz")))
    rng = random.Random(args.seed)
    freq = {"games": 0, "ticks": 0, "affected": 0, "by_inning": defaultdict(lambda: [0, 0]),
            "games_with_affected": 0, "dates": set()}
    samples = []  # (date, gamePk, tick, away_abbr, home_abbr)
    for path in feeds:
        date = Path(path).parent.name
        game_pk = int(Path(path).name.split(".")[0])
        try:
            feed = _load_feed(path)
        except Exception as exc:
            print(f"skip {path}: {exc}", flush=True)
            continue
        state = ((feed.get("gameData") or {}).get("status") or {}).get("abstractGameState")
        if state != "Final":
            continue
        freq["games"] += 1
        freq["dates"].add(date)
        teams = (feed.get("gameData") or {}).get("teams") or {}
        abbr = {s: str((teams.get(s) or {}).get("abbreviation") or "") for s in ("away", "home")}
        affected_ticks = []
        for t in replay_ticks(feed):
            inn = min(t["inning"], 10)
            freq["ticks"] += 1
            freq["by_inning"][inn][0] += 1
            bat = t["batting"]
            hit = bool(t["batting_last_pitcher"]) and t["batting_last_pitcher"] != t["starters"][bat]
            if hit:
                freq["affected"] += 1
                freq["by_inning"][inn][1] += 1
                affected_ticks.append(t)
        if affected_ticks:
            freq["games_with_affected"] += 1
            for t in rng.sample(affected_ticks, min(args.ticks_per_game, len(affected_ticks))):
                samples.append((date, game_pk, t, abbr["away"], abbr["home"]))

    summary = {
        "feeds": len(feeds), "final_games": freq["games"], "dates": len(freq["dates"]),
        "pa_ticks": freq["ticks"], "affected_ticks": freq["affected"],
        "affected_share": round(freq["affected"] / max(1, freq["ticks"]), 4),
        "games_with_affected": freq["games_with_affected"],
        "by_inning": {str(k): {"ticks": v[0], "affected": v[1], "share": round(v[1] / max(1, v[0]), 4)}
                      for k, v in sorted(freq["by_inning"].items())},
    }
    print(json.dumps(summary, indent=1), flush=True)

    from syndicate.features.mlb.live_lens_port.app_slice import _roster_from_snapshot_side
    from syndicate.features.mlb.sim_engine.live_mc import LiveSituation, estimate_live, _forward_live_cfg_kwargs

    rows = []
    no_roster = 0
    t0 = time.time()
    for i, (date, game_pk, t, away_abbr, home_abbr) in enumerate(samples):
        if args.max_games and len(rows) >= args.max_games * args.ticks_per_game:
            break
        doc = _roster_doc(os.path.join(args.mlb_data, "daily/snapshots", date), game_pk, away_abbr, home_abbr)
        if not isinstance(doc, dict):
            no_roster += 1
            continue
        try:
            away_r = _roster_from_snapshot_side(doc.get("away"))
            home_r = _roster_from_snapshot_side(doc.get("home"))
        except Exception as exc:
            no_roster += 1
            print(f"roster_build_failed {game_pk}: {exc}", flush=True)
            continue
        bat, fld = t["batting"], t["fielding"]
        rosters = {"away": away_r, "home": home_r}
        roster_sp = {s: int(rosters[s].lineup.pitcher.player.mlbam_id) for s in ("away", "home")}
        bullpen_ids = {int(p.player.mlbam_id) for p in (rosters[bat].lineup.bullpen or [])}

        def _idx(side, slot):
            return int(slot or 0)

        bs, r1, r2, r3 = _base_state(t["bases"])

        def situation(batting_pid):
            ids = {fld: t["fielding_pitcher"], bat: batting_pid}
            return LiveSituation(
                inning=t["inning"], top=t["top"], outs=t["outs"], bases=bs,
                runner_on_1b=r1, runner_on_2b=r2, runner_on_3b=r3,
                away_score=t["away_score"], home_score=t["home_score"],
                away_next_batter_index=_idx("away", t["batting_slot"] if bat == "away" else t["fielding_next_slot"]),
                home_next_batter_index=_idx("home", t["batting_slot"] if bat == "home" else t["fielding_next_slot"]),
                away_pitcher_id=ids["away"], home_pitcher_id=ids["home"],
                pitcher_pitch_count=t["pitches"], pitcher_batters_faced=t["bf"],
            )

        cfg = _forward_live_cfg_kwargs(date)
        seed = game_pk * 31 + t["inning"] * 2 + int(t["top"])
        off = estimate_live(away_r, home_r, situation(None), sims=args.sims, seed=seed, cfg_kwargs=cfg)
        on = estimate_live(away_r, home_r, situation(t["batting_last_pitcher"]), sims=args.sims, seed=seed, cfg_kwargs=cfg)
        null = estimate_live(away_r, home_r, situation(None), sims=args.sims, seed=seed + 1, cfg_kwargs=cfg)
        sp = t["starters"][bat]
        rsp = roster_sp[bat]
        rsp_outs = (off.pitcher_stat_dist or {}).get(rsp, {}).get("OUTS", {})
        rsp_share = sum(v for k, v in rsp_outs.items() if int(k) > 0) / max(1, args.sims)
        sp_outs = (off.pitcher_stat_dist or {}).get(sp, {}).get("OUTS", {})
        sp_mean_outs = sum(int(k) * v for k, v in sp_outs.items()) / max(1, args.sims)
        sp_share = sum(v for k, v in sp_outs.items() if int(k) > 0) / max(1, args.sims)
        rows.append({
            "date": date, "gamePk": game_pk, "inning": t["inning"], "top": t["top"], "outs": t["outs"],
            "score": [t["away_score"], t["home_score"]], "batting": bat,
            "starter": sp, "starter_pitches": t["pitches"].get(sp, 0),
            "starter_matches_roster": sp == roster_sp[bat],
            "batting_pitcher": t["batting_last_pitcher"],
            "batting_pitcher_in_bullpen": t["batting_last_pitcher"] in bullpen_ids,
            "off_home_wp": off.home_win_prob, "on_home_wp": on.home_win_prob, "null_home_wp": null.home_win_prob,
            "off_total": off.avg_total_runs, "on_total": on.avg_total_runs, "null_total": null.avg_total_runs,
            "off_starter_mean_outs": round(sp_mean_outs, 3), "off_starter_share_pitching": round(sp_share, 3),
            "roster_starter": rsp, "off_roster_starter_share_pitching": round(rsp_share, 3),
            "d_batting_wp_on_minus_off": (on.home_win_prob - off.home_win_prob) * (1 if bat == "home" else -1),
        })
        if (i + 1) % 10 == 0:
            print(f"{i + 1}/{len(samples)} ticks, {time.time() - t0:.0f}s", flush=True)

    def _stats(vals):
        vals = [abs(v) for v in vals]
        if not vals:
            return None
        return {"n": len(vals), "median": round(statistics.median(vals), 4),
                "mean": round(statistics.fmean(vals), 4),
                "p90": round(sorted(vals)[int(0.9 * (len(vals) - 1))], 4), "max": round(max(vals), 4)}

    def _rms_true(on_off, null_off):
        # E[(on-off)^2] - E[(null-off)^2]: the effect's RMS net of sim noise. Conservative:
        # on/off share a seed (common random numbers) so their noise is <= null's.
        if not on_off:
            return None
        a = statistics.fmean([v * v for v in on_off]); b = statistics.fmean([v * v for v in null_off])
        return {"rms_on_off": round(a ** 0.5, 4), "rms_null": round(b ** 0.5, 4), "rms_effect_net": round(max(0.0, a - b) ** 0.5, 4)}

    def _strata(pred):
        sub = [r for r in rows if pred(r)]
        return {
            "n": len(sub),
            "wp": _rms_true([r["on_home_wp"] - r["off_home_wp"] for r in sub], [r["null_home_wp"] - r["off_home_wp"] for r in sub]),
            "total": _rms_true([r["on_total"] - r["off_total"] for r in sub], [r["null_total"] - r["off_total"] for r in sub]),
            "signed_mean_d_batting_wp": round(statistics.fmean([r["d_batting_wp_on_minus_off"] for r in sub]), 4) if sub else None,
            "signed_mean_d_total": round(statistics.fmean([r["on_total"] - r["off_total"] for r in sub]), 4) if sub else None,
            "roster_starter_share_pitching_off": round(statistics.fmean([r["off_roster_starter_share_pitching"] for r in sub]), 4) if sub else None,
        }

    effect = {
        "strata": {
            "all": _strata(lambda r: True),
            "starter_matches_roster_lt75": _strata(lambda r: r["starter_matches_roster"] and r["starter_pitches"] < 75),
            "starter_matches_roster_ge75": _strata(lambda r: r["starter_matches_roster"] and r["starter_pitches"] >= 75),
            "starter_not_roster_starter": _strata(lambda r: not r["starter_matches_roster"]),
            "inning_le5": _strata(lambda r: r["inning"] <= 5),
            "inning_6_7": _strata(lambda r: 6 <= r["inning"] <= 7),
            "inning_ge8": _strata(lambda r: r["inning"] >= 8),
        },
        "sampled_ticks": len(samples), "simulated_ticks": len(rows), "no_roster": no_roster, "sims_per_arm": args.sims,
        "abs_d_home_wp_on_vs_off": _stats([r["on_home_wp"] - r["off_home_wp"] for r in rows]),
        "abs_d_home_wp_null": _stats([r["null_home_wp"] - r["off_home_wp"] for r in rows]),
        "abs_d_total_on_vs_off": _stats([r["on_total"] - r["off_total"] for r in rows]),
        "abs_d_total_null": _stats([r["null_total"] - r["off_total"] for r in rows]),
        "signed_mean_d_total_on_minus_off": round(statistics.fmean([r["on_total"] - r["off_total"] for r in rows]), 4) if rows else None,
        "off_starter_share_pitching_mean": round(statistics.fmean([r["off_starter_share_pitching"] for r in rows]), 4) if rows else None,
        "off_starter_mean_outs": round(statistics.fmean([r["off_starter_mean_outs"] for r in rows]), 3) if rows else None,
        "starter_matches_roster": sum(1 for r in rows if r["starter_matches_roster"]),
        "batting_pitcher_in_bullpen": sum(1 for r in rows if r["batting_pitcher_in_bullpen"]),
    }
    print(json.dumps(effect, indent=1), flush=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"frequency": summary, "effect": effect, "rows": rows}, fh, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
