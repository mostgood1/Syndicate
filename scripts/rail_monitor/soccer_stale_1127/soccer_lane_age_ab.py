"""A/B for lane soccer-live-lane-age-ceiling: with SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE ABSENT, does this checkout
produce byte-identical rows and coverage to the committed (pre-change) versions of the two changed modules?

  py -3 soccer_lane_age_ab.py <repo>            runs both sides in subprocesses and compares
  py -3 soccer_lane_age_ab.py <repo> base|work  one side, JSON to stdout

`base` execs `git show HEAD:<path>` for live_gameline_join.py and soccer_live_gameline_source.py in place of the
working copies (HEAD = the branch's base on main); `work` imports the working copies. Same fixtures, same build times,
the switch absent on both. Fixtures: an aggregate lens and a per-league lens, 3 matches (one with liveRefusal),
h2h home/draw/away + totals over/under + spreads rows, judged at +60 s, +700 s and +6,063 s.
"""
import json
import os
import subprocess
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODS = (("syndicate.features.shared.live_gameline_join", "syndicate/features/shared/live_gameline_join.py"),
        ("syndicate.features.shared.soccer_live_gameline_source", "syndicate/features/shared/soccer_live_gameline_source.py"))
DATE = "2026-11-27"
LENS_AT = datetime(2026, 11, 27, 20, 1, 59, tzinfo=timezone.utc)


def proj(h, d, a, total):
    return {"simulations": 400, "home_win_probability": h, "draw_probability": d, "away_win_probability": a,
            "projected_final_home_goals": total * 0.55, "projected_final_away_goals": total * 0.45,
            "projected_final_total": total, "over_2_5_probability": 0.52, "home_red_card_applied": False,
            "away_red_card_applied": False,
            "scoreline_probabilities": {"0-0": 0.1, "1-0": 0.15, "0-1": 0.1, "1-1": 0.15, "2-0": 0.1, "2-1": 0.15,
                                        "1-2": 0.1, "2-2": 0.1, "3-1": 0.05}}


GAMES = [
    {"event_id": "1", "league": "serie_a", "home_team": "Venezia", "away_team": "Bologna", "score_home": 0,
     "score_away": 0, "status_display_clock": "17'", "projection": proj(0.31, 0.30, 0.39, 2.4)},
    {"event_id": "2", "league": "epl", "home_team": "Nottingham Forest", "away_team": "Chelsea", "score_home": 1,
     "score_away": 1, "status_display_clock": "55'", "projection": proj(0.35, 0.33, 0.32, 3.1)},
    {"event_id": "3", "league": "la_liga", "home_team": "Levante", "away_team": "Racing Santander", "score_home": 0,
     "score_away": 1, "status_display_clock": "70'", "projection": proj(0.2, 0.3, 0.5, 1.8),
     "liveRefusal": {"reason": "key_player_out"}},
]


def rows():
    out = []
    for away, home in (("Bologna", "Venezia"), ("Chelsea", "Nottingham Forest"), ("Real Racing Club de Santander", "Levante")):
        for side in ("home", "draw", "away"):
            out.append({"sport": "soccer", "kind": "game", "market": "h2h", "segment": "full", "home_team": home,
                        "away_team": away, "side": side, "game": {"state": "live"}, "age_seconds": 20.0,
                        "projection": {"market_fair_prob_over": 0.4, "side": "home"}})
        for side in ("over", "under"):
            out.append({"sport": "soccer", "kind": "game", "market": "totals", "segment": "full", "home_team": home,
                        "away_team": away, "side": side, "line": 2.5, "game": {"state": "live"}, "age_seconds": 20.0,
                        "projection": {"market_fair_prob_over": 0.5, "side": "over"}})
        out.append({"sport": "soccer", "kind": "game", "market": "spreads", "segment": "full", "home_team": home,
                    "away_team": away, "side": "home", "line": -0.5, "game": {"state": "live"}, "age_seconds": 20.0,
                    "projection": {"market_fair_prob_over": 0.45, "side": "home"}})
    return out


def side(repo, which):
    os.environ.pop("SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE", None)
    # Control run only: AB_WORK_SWITCH=on|shadow sets the switch on the WORK side, to show the A/B can see a change.
    if which == "work" and os.environ.get("AB_WORK_SWITCH"):
        os.environ["SYNDICATE_LIVE_GAMELINE_SOCCER_LANE_AGE"] = os.environ["AB_WORK_SWITCH"]
    sys.path.insert(0, repo)
    if which == "base":
        import syndicate.features.shared as pkg
        for name, path in MODS:
            src = subprocess.run(["git", "-C", repo, "show", f"HEAD:{path}"], capture_output=True, check=True).stdout
            mod = types.ModuleType(name)
            mod.__file__ = os.path.join(repo, path)
            mod.__package__ = "syndicate.features.shared"
            sys.modules[name] = mod
            setattr(pkg, name.rsplit(".", 1)[1], mod)
            exec(compile(src.decode("utf-8"), mod.__file__, "exec"), mod.__dict__)
    from syndicate.features.shared import refresh_state_store as rss
    from syndicate.features.shared import soccer_live_gameline_source as src_mod
    from syndicate.features.shared.live_gameline_join import attach_live_gamelines
    result = {}
    for store in ("aggregate", "per_league"):
        root = Path(tempfile.mkdtemp(prefix=f"ab_{which}_{store}_"))
        rss.data_root = lambda root=root: root
        if store == "aggregate":
            (root / "live").mkdir(parents=True)
            (root / "live" / "soccer_live_lens.json").write_text(json.dumps(
                {"date": DATE, "generated_at": LENS_AT.isoformat(), "games": GAMES}), encoding="utf-8")
        else:
            for g in GAMES:
                d = root / "soccer_source" / g["league"] / "api" / "live_state"
                d.mkdir(parents=True, exist_ok=True)
                (d / f"live_state_{DATE}.json").write_text(json.dumps(
                    {"league": g["league"], "date": DATE, "generated_at": LENS_AT.isoformat(),
                     "games": {g["event_id"]: g}, "match_box": {}}), encoding="utf-8")
        index = src_mod.soccer_live_gameline_index(DATE, data_root=root)
        result[f"{store}/index"] = {"|".join(k): v for k, v in sorted(index.items())}
        for secs in (60, 700, 6063):
            rs = rows()
            cov = attach_live_gamelines(rs, index, sport="soccer", now=LENS_AT + timedelta(seconds=secs))
            result[f"{store}/{secs}s"] = {"rows": rs, "coverage": cov}
    return result


def main():
    repo = sys.argv[1]
    if len(sys.argv) > 2:
        print(json.dumps(side(repo, sys.argv[2]), sort_keys=True, default=str))
        return
    out = {}
    for which in ("base", "work"):
        p = subprocess.run([sys.executable, os.path.abspath(__file__), repo, which], capture_output=True, text=True,
                           encoding="utf-8")
        if p.returncode != 0:
            print(which, "FAILED", p.stderr[-2000:])
            sys.exit(2)
        out[which] = json.loads(p.stdout)
    b, w = out["base"], out["work"]
    same = 0
    for case in sorted(b):
        eq = json.dumps(b[case], sort_keys=True, default=str) == json.dumps(w.get(case), sort_keys=True, default=str)
        same += eq
        v = (w.get(case) or {})
        cov = v.get("coverage") or {}
        print(f"{case:24s} {'IDENTICAL' if eq else 'DIFFERS'}  priceable {cov.get('rows_live_gameline_priceable')} "
              f"withheld {cov.get('rows_live_gameline_withheld')} lane_age_max_s {cov.get('lane_age_max_s')}")
    print(f"{same} of {len(b)} cases identical; work has {len(w)} cases")
    sys.exit(0 if same == len(b) == len(w) else 1)


if __name__ == "__main__":
    main()
