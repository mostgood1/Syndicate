"""Four arms, 13 dates, 177 games: does the unit fix close the gap to independence?

Same instrument as the one-date run, at ~30x the clusters. Outcomes come from
`daily_top_props` (graded in-file), joints from the backfill.

FOUR ARMS ON IDENTICAL MARGINALS -- only the dependence term varies:
    independence    p_A * p_B
    heuristic       the flag-sum path
    measured RAW    the joint's Spearman coefficient, as originally shipped
    measured CONV   the same coefficient through `threshold_correlation`

THE POPULATION IS SELECTED. `daily_top_props` is chosen BY MODEL EDGE, so this
answers "does the fix help on the props we would actually bet", not "does it
help on all pairs". That is the more decision-relevant question and a DIFFERENT
one from the neutral `props_actuals` test -- reported separately, never pooled.

Bootstrap resamples GAMES. Pairs inside a game are not independent.
"""
from __future__ import annotations

import json
import os
import math
import pathlib
import random
import subprocess
import sys
import unicodedata
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
WT = REPO
for p in (str(WT),):
    if p not in sys.path:
        sys.path.insert(0, p)

from syndicate.features.correlation_engine import compute_correlation  # noqa: E402
from syndicate.features.intelligence_parlay_runtime import (  # noqa: E402
    _correlation_adjusted_probability,
)
from syndicate.features.mlb.threshold_correlation import threshold_correlation  # noqa: E402

BACK = pathlib.Path(os.environ.get("SYNDICATE_JOINT_BACKFILL")
                    or (REPO / "reports" / "joint_backfill"))
#: `stat` on a top_props row is ALREADY the joint's label segment.
JOINT_MARKETS = {"hits", "home_runs", "total_bases", "rbi"}
EPS = 1e-6


def norm(v) -> str:
    s = unicodedata.normalize("NFKD", str(v or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.lower().replace(".", " ").replace("-", " ").split())


def walk(node, out):
    if isinstance(node, dict):
        if node.get("actual") is not None and node.get("line") is not None:
            out.append(node)
            return
        for v in node.values():
            walk(v, out)
    elif isinstance(node, list):
        for v in node:
            walk(v, out)


def p_over(dist, line):
    if not isinstance(dist, dict) or not dist:
        return None
    tot = ov = 0.0
    for k, v in dist.items():
        try:
            key, cnt = float(k), float(v)
        except (TypeError, ValueError):
            continue
        tot += cnt
        if key > line:
            ov += cnt
    return (ov / tot) if tot > 0 else None


def tri(i, k):
    if i < k:
        i, k = k, i
    return i * (i - 1) // 2 + k


def ll(p, y):
    p = min(max(p, 1e-9), 1 - 1e-9)
    return -(math.log(p) if y else math.log(1 - p))


def main() -> int:
    files = subprocess.run(["git", "ls-files", "data/*top_props*"],
                           cwd=REPO, capture_output=True, text=True).stdout.split()
    graded = defaultdict(dict)      # date -> norm(player) -> market -> (actual, line)
    for f in files:
        p = REPO / f
        d = p.stem.replace("daily_top_props_", "").replace("_", "-")
        if len(d) != 10 or not (BACK / d).is_dir():
            continue
        try:
            acc = []
            walk(json.loads(p.read_text(encoding="utf-8")), acc)
        except Exception:
            continue
        for r in acc:
            mk = str(r.get("stat") or "").strip()
            if mk not in JOINT_MARKETS:
                continue
            # PITCHER rows share the stat vocabulary but are not batter
            # dimensions in the joint. Excluding them by `group` rather than by
            # hoping the label lookup misses.
            if str(r.get("group") or "").strip().lower() not in ("hitter", "batter"):
                continue
            who = norm(r.get("playerName"))
            try:
                pk = int(r.get("gamePk"))
                key = (pk, who)
                graded[d][key] = graded[d].get(key) or {}
                graded[d][key][mk] = (float(r["actual"]), float(r["line"]))
            except (TypeError, ValueError, KeyError):
                continue
    print("dates with graded rows: %d" % len(graded))

    per_game, skipped = [], defaultdict(int)
    for date in sorted(graded):
        for jf in sorted((BACK / date).glob("joint_*.json")):
            doc = json.loads(jf.read_text(encoding="utf-8"))
            # joint_0_STL_at_CHC_pk824659_g1 -> 824659
            game_pk = None
            for tok in jf.stem.split("_"):
                if tok.startswith("pk") and tok[2:].isdigit():
                    game_pk = int(tok[2:])
                    break
            if game_pk is None:
                skipped["no_game_pk"] += 1
                continue
            j = doc.get("joint") or {}
            labels, lower = j.get("labels") or [], j.get("corr_lower") or []
            if not labels or not lower:
                skipped["no_joint"] += 1
                continue
            UND, scale = j.get("undefined", -32768), float(j.get("scale") or 1000.0)
            pos = {l: i for i, l in enumerate(labels)}
            legs = []
            for pid, prof in (doc.get("hitter_props") or {}).items():
                if not prof.get("is_lineup_batter"):
                    skipped["not_lineup"] += 1
                    continue
                if float(prof.get("pa_mean") or 0.0) < 1.0:
                    skipped["thin_pa"] += 1
                    continue
                got = graded[date].get((game_pk, norm(prof.get("name"))))
                if not got:
                    skipped["no_graded_row"] += 1
                    continue
                for mk, (actual, line) in got.items():
                    lab = f"batter|{pid}|{mk}"
                    if lab not in pos:
                        skipped["no_label"] += 1
                        continue
                    p = p_over(prof.get(f"{mk}_dist"), line)
                    if p is None or p <= EPS or p >= 1 - EPS:
                        skipped["degenerate_marginal"] += 1
                        continue
                    legs.append({"pid": pid, "name": prof.get("name"), "market": mk,
                                 "label": lab, "p": p, "won": 1 if actual > line else 0,
                                 "team": prof.get("team")})
            pairs = []
            for a in range(len(legs)):
                for b in range(a + 1, len(legs)):
                    la, lb = legs[a], legs[b]
                    raw = lower[tri(pos[la["label"]], pos[lb["label"]])]
                    if raw == UND:
                        skipped["undefined_corr"] += 1
                        continue
                    measured = raw / scale
                    ca = {"sport": "mlb", "sport_slug": "mlb", "game_key": jf.stem,
                          "event_id": jf.stem, "team": la["team"], "team_key": la["team"],
                          "subject": la["name"], "player_name": la["name"],
                          "market": la["market"], "market_key": la["market"],
                          "selection": "over", "side": "over"}
                    cb = dict(ca, team=lb["team"], team_key=lb["team"], subject=lb["name"],
                              player_name=lb["name"], market=lb["market"], market_key=lb["market"])
                    heur = float(compute_correlation(ca, cb).get("correlation_score") or 0.0)
                    probs = [la["p"], lb["p"]]
                    pairs.append({
                        "y": 1 if (la["won"] and lb["won"]) else 0,
                        "indep": _correlation_adjusted_probability(probs, 0.0),
                        "heur": _correlation_adjusted_probability(probs, heur),
                        "raw": _correlation_adjusted_probability(probs, measured),
                        "conv": _correlation_adjusted_probability(
                            probs, threshold_correlation(measured, la["p"], lb["p"])),
                        "same_player": la["pid"] == lb["pid"],
                        "measured": measured, "heuristic": heur,
                    })
            if pairs:
                per_game.append((f"{date}/{jf.stem}", pairs))

    n = sum(len(p) for _, p in per_game)
    print("games: %d   pairs: %d" % (len(per_game), n))
    print("skipped:", dict(skipped))
    if not n:
        return 3

    def table(sub, label):
        m = sum(len(p) for _, p in sub)
        if not m:
            return
        print("\n%s -- n=%d over %d games" % (label, m, len(sub)))
        print("  %-16s %10s %10s" % ("arm", "log-loss", "brier"))
        for arm, nm in (("indep", "independence"), ("heur", "heuristic"),
                        ("raw", "measured RAW"), ("conv", "measured CONV")):
            a = sum(ll(x[arm], x["y"]) for _, p in sub for x in p) / m
            b = sum((x[arm] - x["y"]) ** 2 for _, p in sub for x in p) / m
            print("  %-16s %10.5f %10.5f" % (nm, a, b))
        rng = random.Random(99)
        for base in ("heur", "indep", "raw"):
            d = []
            for _ in range(2000):
                pick = [sub[rng.randrange(len(sub))] for _ in sub]
                k = sum(len(p) for _, p in pick)
                if not k:
                    continue
                c = sum(ll(x["conv"], x["y"]) for _, p in pick for x in p) / k
                o = sum(ll(x[base], x["y"]) for _, p in pick for x in p) / k
                d.append(c - o)
            d.sort()
            if d:
                print("  CONV vs %-9s %+0.5f  95%% CI [%+0.5f, %+0.5f]" % (
                    base, sum(d) / len(d), d[int(.025 * len(d))], d[int(.975 * len(d))]))

    table(per_game, "ALL PAIRS")
    for lbl, keep in (("SAME-PLAYER", True), ("CROSS-PLAYER", False)):
        sub = [(g, [x for x in pp if x["same_player"] is keep]) for g, pp in per_game]
        table([(g, pp) for g, pp in sub if pp], lbl)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
