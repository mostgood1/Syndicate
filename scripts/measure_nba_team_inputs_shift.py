"""`#473` A/B: the same NBA games, same seed, NBA team inputs OFF vs ON (lane `nba-sim-team-adj-473`).

    # one arm (wraps scripts/record_basketball_engine_corpus.py; SCRATCH data root per arm, never production)
    nice -n 19 python scripts/measure_nba_team_inputs_shift.py run --arm on -- --league nba --dates 2026-10-05 \\
        --source-root ~/nba473/on/nba_source --out-dir ~/nba473/corpus_on --seed 7 --n-sims 500 \\
        --env-from-pid <refresh-worker pid> --scratch-data-root ~/nba473/on
    # compare the two arms' sim outputs (`<out-prefix>_<date>_<HOME>_<AWAY>.json`)
    python scripts/measure_nba_team_inputs_shift.py compare --off ~/nba473/off/nba_source --on ~/nba473/on/nba_source

WHY A WRAPPER. The recorder replaces the whole environment with the fleet role's (`--env-from-pid`), so a shell
variable cannot reach the sim; this sets `SYNDICATE_NBA_TEAM_INPUTS` inside that loaded environment.

WHAT IS REPORTED, per game and pooled: the RAW model margin/total (`market_anchor.model_*_raw`, what the engine
produced before the production market anchor) and the PUBLISHED ones (`score.*_mean`, after the anchor), the margin
and total SDs from the published quantiles, the team-adjustment diag, and how well each arm's raw margin tracks the
market spread (a team-quality input should move it toward the market; the anchor hides that in the published number).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _run(arm: str, rest: list[str]) -> int:
    from scripts import record_basketball_engine_corpus as rec

    value = "0" if arm == "off" else "1"
    if arm == "on_nostack":
        # DIAGNOSTIC ARM, scratch only: NBA stops multiplying the team prior onto the market-anchored points target,
        # as WNBA has since 2026-10-01. Separates what the input does from the double count it switches on.
        # Pair it with `nba_sim_total_inputs.json` {"skip_def_subtraction": true} in the arm's scratch processed root.
        from dataclasses import replace

        from syndicate.features.basketball_engine import league

        league._BY_CODE["nba"] = replace(league.NBA, team_prior_stacks_on_target=False)
    os.environ["SYNDICATE_NBA_TEAM_INPUTS"] = value
    original = rec.load_role_env

    def with_arm(*a, **k):
        env = original(*a, **k)
        env["SYNDICATE_NBA_TEAM_INPUTS"] = value
        return env

    rec.load_role_env = with_arm
    return rec.main(rest)


def _game(path: Path) -> dict:
    d = json.loads(path.read_text(encoding="utf-8"))
    score, anchor = d.get("score") or {}, d.get("market_anchor") or {}
    ctx = d.get("context") or {}
    tap = ctx.get("team_advanced_priors") or {}
    pem = ctx.get("pregame_expected_minutes") or {}
    mq, tq = score.get("margin_q") or {}, score.get("total_q") or {}
    return {
        "raw_margin": anchor.get("model_margin_raw"), "raw_total": anchor.get("model_total_raw"),
        "pub_margin": score.get("margin_mean"), "pub_total": score.get("total_mean"),
        # p10..p90 spread / 2.563 = SD under normality
        "margin_sd": ((mq.get("p90") - mq.get("p10")) / 2.563) if mq else None,
        "total_sd": ((tq.get("p90") - tq.get("p10")) / 2.563) if tq else None,
        "market_spread": (d.get("market") or {}).get("market_home_spread"),
        "team_adj_applied": bool(tap.get("applied")), "team_adj_reason": tap.get("reason"),
        "home_eff": ((tap.get("home_adj") or {}).get("eff_mult")), "away_eff": ((tap.get("away_adj") or {}).get("eff_mult")),
        "pem_applied": [bool((pem.get(s) or {}).get("applied")) for s in ("home", "away")],
    }


def _corr(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 3:
        return None
    mx = sum(p[0] for p in pairs) / len(pairs)
    my = sum(p[1] for p in pairs) / len(pairs)
    sxy = sum((x - mx) * (y - my) for x, y in pairs)
    sx = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
    sy = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
    return round(sxy / (sx * sy), 3) if sx and sy else None


def _compare(off_root: Path, on_root: Path, prefix: str) -> int:
    off_dir, on_dir = off_root / "data" / "processed", on_root / "data" / "processed"
    names = sorted(p.name for p in on_dir.glob(f"{prefix}_*.json") if (off_dir / p.name).is_file())
    rows = []
    for name in names:
        off, on = _game(off_dir / name), _game(on_dir / name)
        rows.append({"game": name[len(prefix) + 1:-5], "off": off, "on": on})
    out = {"games": len(rows), "per_game": rows}
    if rows:
        def mean(key, arm):
            vals = [r[arm][key] for r in rows if r[arm][key] is not None]
            return round(sum(vals) / len(vals), 3) if vals else None

        def mean_abs_delta(key):
            vals = [abs(r["on"][key] - r["off"][key]) for r in rows if r["on"][key] is not None and r["off"][key] is not None]
            return round(sum(vals) / len(vals), 3) if vals else None

        out["pooled"] = {
            arm: {k: mean(k, arm) for k in ("raw_margin", "raw_total", "pub_margin", "pub_total", "margin_sd", "total_sd")}
            for arm in ("off", "on")
        }
        out["mean_abs_delta"] = {k: mean_abs_delta(k) for k in ("raw_margin", "raw_total", "pub_margin", "pub_total", "margin_sd", "total_sd")}
        # market_home_spread is the home line (negative = home favoured), so -spread is the market's expected margin
        out["corr_raw_margin_vs_market"] = {
            arm: _corr([r[arm]["raw_margin"] for r in rows], [(-r[arm]["market_spread"]) if r[arm]["market_spread"] is not None else None for r in rows])
            for arm in ("off", "on")
        }
        out["team_adj_applied"] = {arm: sum(r[arm]["team_adj_applied"] for r in rows) for arm in ("off", "on")}
        out["starter_feed_applied_sides"] = {arm: sum(sum(r[arm]["pem_applied"]) for r in rows) for arm in ("off", "on")}
        out["off_equals_on_games"] = sum(1 for r in rows if r["off"]["raw_margin"] == r["on"]["raw_margin"] and r["off"]["raw_total"] == r["on"]["raw_total"])
    print(json.dumps(out, indent=2, default=str))
    return 0 if rows else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["run"]:
        ap = argparse.ArgumentParser()
        ap.add_argument("--arm", required=True, choices=("on", "off", "on_nostack"))
        rest = argv[argv.index("--") + 1:] if "--" in argv else []
        args = ap.parse_args(argv[1:argv.index("--")] if "--" in argv else argv[1:])
        return _run(args.arm, rest)
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("compare",))
    ap.add_argument("--off", required=True, type=Path)
    ap.add_argument("--on", required=True, type=Path)
    ap.add_argument("--out-prefix", default="engine_corpus")
    args = ap.parse_args(argv)
    return _compare(args.off.expanduser(), args.on.expanduser(), args.out_prefix)


if __name__ == "__main__":
    sys.exit(main())
