# -*- coding: utf-8 -*-
"""H-RR grade: does the refreshed ESPN roster (6a97aafc) make soccer props more accurate than July's?

PRE-REGISTERED: `.syndicate/findings_2026-10-08_soccer_roster_refresh_accuracy_prereg.md` (38322728),
written before any population match kicked off. This script implements that design and nothing else.

Arms share the 2026-10-08T16:25:52Z player-file snapshot and each match's stored pre-kickoff team
distribution; only the roster file differs (A = July seed, B = refreshed). Primary: B - A log loss on
appeared outfield players listed in BOTH arms, SOT 0.5 and anytime-if-playing, match bootstrap.

Run on the fleet host (WSL), at the lowest priority:
    SYNDICATE_CHECKOUT=~/Syndicate nice -n 19 ~/.venvs/syndicate/bin/python roster_refresh_grade.py \
        --freeze-root ~/syndicate-prod/data/soccer_source \
        --inputs /mnt/c/tmp/soccer-roster-grade/inputs_2026-10-08 \
        --work /mnt/c/tmp/soccer-roster-grade/work --out /mnt/c/tmp/soccer-roster-grade/grade_<date>.json
"""
import argparse
import collections
import contextlib
import csv
import datetime as dt
import glob
import hashlib
import importlib.util
import io
import json
import math
import os
import random
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

CHECKOUT = Path(os.environ.get("SYNDICATE_CHECKOUT") or Path(__file__).resolve().parents[2]).expanduser()
sys.path.insert(0, str(CHECKOUT))
AUDIT = CHECKOUT / "scripts" / "soccer_season_audit"

LEAGUES = ["bundesliga", "ligue_1", "la_liga", "epl", "serie_a", "championship", "eredivisie",
           "primeira_liga", "belgian_pro_league"]
KICKOFF_FLOOR = dt.datetime(2026, 10, 7, 1, 0, tzinfo=dt.timezone.utc)
#: PLUMBING SMOKE ONLY: grades matches BEFORE the registered window. Never set for the registered grade;
#: the report records it so a smoke result cannot pass for the real one.
_SMOKE_FLOOR = os.environ.get("ROSTER_GRADE_SMOKE_FLOOR")
if _SMOKE_FLOOR:
    KICKOFF_FLOOR = dt.datetime.fromisoformat(_SMOKE_FLOOR).replace(tzinfo=dt.timezone.utc)
MANIFEST_DIGEST = "440d029a419bd3a3"
EPS = 1e-6
MIN_MATCHES = 60


def ts(value):
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def ll(p, y):
    p = min(1 - EPS, max(EPS, float(p)))
    return -(math.log(p) if y else math.log(1 - p))


def appeared(q):
    return bool(q.get("starter") or q.get("subbed_in"))


def boot(units, fn, reps=2000, seed=11):
    rng = random.Random(seed)
    vals = sorted(fn([units[rng.randrange(len(units))] for _ in units]) for _ in range(reps))
    return [vals[int(0.025 * reps)], vals[int(0.975 * reps) - 1]]


def stage_population(freeze_root: Path, recs_dir: Path, now: dt.datetime) -> collections.Counter:
    """One synthetic recommendations file per frozen pre-kickoff match, in the shape common.load_recs reads."""
    shutil.rmtree(recs_dir, ignore_errors=True)
    recs_dir.mkdir(parents=True)
    count = collections.Counter()
    for lg in LEAGUES:
        for f in glob.glob(str(freeze_root / lg / "api" / "recommendations" / "recommendations_prekickoff_*.json")):
            try:
                body = json.load(open(f, encoding="utf-8"))
            except Exception:
                continue
            for mid, entry in (body.get("matches") or {}).items():
                kick = ts(entry.get("kickoff"))
                if kick is None or kick < KICKOFF_FLOOR or kick > now - dt.timedelta(hours=3):
                    continue
                match = dict(entry.get("match") or {})
                payload = {"league": lg, "date": body.get("date"), "generated_at": entry.get("frozen_at"),
                           "matches": [match], "player_props": entry.get("player_props") or []}
                out = recs_dir / f"{lg}_{mid}_recommendations_{body.get('date')}.json"
                out.write_text(json.dumps(payload), encoding="utf-8")
                count[lg] += 1
    return count


def manifest_digest(inputs: Path) -> str:
    return hashlib.sha256((inputs / "MANIFEST.sha256").read_bytes()).hexdigest()[:16]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--freeze-root", required=True, type=Path)
    ap.add_argument("--inputs", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    digest = manifest_digest(args.inputs)
    assert digest == MANIFEST_DIGEST, f"input snapshot changed: {digest} != {MANIFEST_DIGEST}"

    # 1. Population and outcomes (outcomes.py over the staged files, FULL TIME only).
    os.environ["SOCCER_AUDIT_CACHE"] = str(args.work)
    os.environ["SYNDICATE_REPO_ROOT"] = str(CHECKOUT)
    staged = stage_population(args.freeze_root.expanduser(), args.work / "prod" / "recs", now)
    print("staged frozen matches:", dict(staged), flush=True)
    subprocess.run([sys.executable, str(AUDIT / "outcomes.py")], cwd=str(AUDIT), check=True)
    sys.path.append(str(AUDIT))
    from common import load_outcomes, load_recs  # noqa: E402
    from namejoin_diag import strict_match  # noqa: E402

    spec = importlib.util.spec_from_file_location("bsa_rr", CHECKOUT / "scripts" / "build_soccer_artifacts.py")
    bsa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bsa)
    from syndicate.features.soccer.features.loaders import build_soccer_player_features  # noqa: E402
    from syndicate.features.soccer.sim_engine.soccersim import player_props as PP  # noqa: E402

    recs, outc = load_recs(str(args.work / "prod" / "recs"), prekickoff_only=True), load_outcomes()

    # 2. Squads per arm: same player files, roster the only variable.
    root = args.work / "players_root" / "soccer_source"
    shutil.rmtree(root.parent, ignore_errors=True)
    for lg in LEAGUES:
        (root / lg / "players").mkdir(parents=True)
        for f in glob.glob(str(args.inputs / "players" / lg / "players_*.csv")):
            shutil.copyfile(f, root / lg / "players" / os.path.basename(f))  # copyfile: /mnt/c refuses chmod
    rows = {}
    for arm, sub in (("A", "rosters_july"), ("B", "rosters_new")):
        for lg in LEAGUES:
            path = args.inputs / sub / lg / "rosters_2026.csv"
            bsa.roster_rows = lambda league, season, p=path: tuple(csv.DictReader(open(p, encoding="utf-8")))
            with contextlib.redirect_stdout(io.StringIO()):
                rows[(arm, lg)] = bsa._load_player_rows(lg, root)

    # 3. Paired replay.
    units, single = [], collections.Counter()
    cov = collections.Counter()
    for (lg, mid), m in sorted(recs.items()):
        o = outc.get((lg, mid))
        if not o or m["shots_h"] is None:
            cov["no_outcome_or_distribution"] += 1
            continue
        dist = SimpleNamespace(mean_home_goals=m["home_mean"] or 0.0, mean_away_goals=m["away_mean"] or 0.0,
                               mean_home_shots=m["shots_h"], mean_away_shots=m["shots_a"],
                               mean_home_shots_on_target=m["sot_h"] or 0.0, mean_away_shots_on_target=m["sot_a"] or 0.0)
        unit = {"league": lg, "sot": [], "any": []}
        for side, club in (("home", m["home"]), ("away", m["away"])):
            box = [q for q in o["players"] if q["side"] == side]
            proj, bound = {}, {}
            for arm in ("A", "B"):
                with contextlib.redirect_stdout(io.StringIO()):
                    feats = build_soccer_player_features(rows[(arm, lg)], league=lg, date=m["date"], fixture_teams=[m["home"], m["away"]])
                plain = [{"player_id": f.player_id, "player_name": f.player_name, "position": f.position, "team": f.team,
                          **dict(f.usage_metrics or {})} for f in feats if f.team == club]
                if not plain or not (m["shots_h"] if side == "home" else m["shots_a"]):
                    proj[arm] = []
                    bound[arm] = {}
                    continue
                profiles = PP.build_usage_profiles(plain, side=side, team=club)
                proj[arm] = [PP.project_player_props(dist, p).to_dict() for p in profiles]
                mapping = strict_match([{"player_name": p["player_name"], "side": side} for p in proj[arm]], box)
                bound[arm] = {j: proj[arm][i] for i, j in mapping.items()}
            for j, q in enumerate(box):
                if not appeared(q):
                    continue
                a, b = bound["A"].get(j), bound["B"].get(j)
                if a is None or b is None:
                    if a is not None or b is not None:
                        single["only_A" if a is not None else "only_B"] += 1
                    continue
                if a.get("expected_saves") or str(a.get("position") or "").upper() in ("GK", "G", "GOALKEEPER"):
                    continue
                pa, pb = (a.get("shots_on_target_over_probabilities") or {}).get("0.5"), (b.get("shots_on_target_over_probabilities") or {}).get("0.5")
                if pa is not None and pb is not None:
                    unit["sot"].append((pa, pb, int((q.get("sot") or 0) >= 1)))
                xa, xb = a.get("anytime_scorer_probability_if_playing"), b.get("anytime_scorer_probability_if_playing")
                if xa is not None and xb is not None:
                    unit["any"].append((xa, xb, int((q.get("goals") or 0) >= 1)))
        if unit["sot"] or unit["any"]:
            units.append(unit)

    def delta(us, key):
        n = sum(len(u[key]) for u in us)
        return sum(ll(b, y) - ll(a, y) for u in us for a, b, y in u[key]) / max(n, 1)

    report = {"prereg": "findings_2026-10-08_soccer_roster_refresh_accuracy_prereg.md", "graded_at": now.isoformat(),
              "SMOKE_NOT_THE_REGISTERED_GRADE": bool(_SMOKE_FLOOR), "kickoff_floor": KICKOFF_FLOOR.isoformat(),
              "manifest_digest": digest, "staged": dict(staged), "coverage": dict(cov), "matches": len(units),
              "by_league_matches": dict(collections.Counter(u["league"] for u in units)),
              "appeared_in_one_arm_only": dict(single), "markets": {}}
    verdicts = []
    for key, label in (("sot", "SOT 0.5"), ("any", "anytime")):
        us = [u for u in units if u[key]]
        flat = [t for u in us for t in u[key]]
        if not flat:
            report["markets"][label] = {"n_players": 0}
            verdicts.append("INCONCLUSIVE")
            continue
        ci = boot(us, lambda s: delta(s, key))
        report["markets"][label] = {
            "n_players": len(flat), "n_matches": len(us),
            "logloss_A": round(sum(ll(a, y) for a, _, y in flat) / len(flat), 5),
            "logloss_B": round(sum(ll(b, y) for _, b, y in flat) / len(flat), 5),
            "delta_B_minus_A": round(delta(us, key), 5), "ci95": [round(v, 5) for v in ci],
            "realised_over_expected_A": round(sum(y for *_, y in flat) / max(sum(a for a, _, _ in flat), EPS), 4),
            "realised_over_expected_B": round(sum(y for *_, y in flat) / max(sum(b for _, b, _ in flat), EPS), 4),
            "by_league": {lg: {"n": sum(len(u[key]) for u in us if u["league"] == lg),
                               "delta": round(delta([u for u in us if u["league"] == lg], key), 5)}
                          for lg in sorted({u["league"] for u in us})},
        }
        verdicts.append("SUPPORTED" if ci[1] < 0 else "REFUTED" if ci[0] > 0 else "INCONCLUSIVE")
    report["verdict"] = ("REFUTED" if "REFUTED" in verdicts else
                         "SUPPORTED" if all(v == "SUPPORTED" for v in verdicts) else "INCONCLUSIVE")
    report["underpowered"] = len(units) < MIN_MATCHES
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("matches", "by_league_matches", "appeared_in_one_arm_only", "markets", "verdict", "underpowered")}, indent=1))


if __name__ == "__main__":
    main()
