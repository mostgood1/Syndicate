"""Grade NCAAF quarter/half game-line probabilities against the market and the box (todo #804).

WHY. `ncaaf.segment_projections.segment_projection` stamps every NCAAF h1/h2/q1-q4 view
with the FULL-GAME module's loss (`{"state": "measured_loss", ...}`) and no
`established_loss_rel`. `projection_skill.normalize_existing_note` serves that as
`status: measured`, and `measured_market_skill.skill_reliability` returns 1.0 for a
note with no `established_loss_rel`. Measured on the served board 2026-11-14 22:48Z:
1,617 NCAAF segment rows ranked at 1.0, while the same model's full-game rows sat at
0.814 (spreads, h2h) and 0.514 (totals). The module's docstring says the loss "acts
through ranking"; it did not, and no segment-level measurement exists. This is it.

PRE-REGISTERED (lane `ncaaf-segment-skill`, `.syndicate/lanes.md`, pushed before any
outcome was read). The method is `scripts/nfl_segment_skill.py`'s (todo #752), whose
de-vig, consensus, framing and statistics this file imports unchanged. What differs is
the NCAAF bridge and the as-of rule:

- BRIDGE = production's own (`segment_projections.attach_ncaaf_segment_projections`):
  `oddsapi_lines.resolve_team` -> `game_projections._norm` -> the pair in a 2026
  `smartsim2_projections_<s>_wk<w>.csv` -> its ESPN `game_id` -> that week's
  `smartsim2_segment_distributions` block. A pair in several weeks takes the week whose
  ESPN event is dated within one day of the kickoff.
- AS-OF = the sidecar's own `generated_at` must be STRICTLY BEFORE the game's
  `commence_time`. The files are rewritten through the week (each week's last write
  lands on its Saturday) and SP+ refreshes in season, so a file written after kickoff
  is neither what the board served nor clean of the game it prices.
- BOX = ESPN's college-football scoreboard, indexed by event id (the artifact key).
- Bootstrap seed 804.

    py -3 scripts/ncaaf_segment_skill.py --sidecars C:\\tmp\\ncaaf_seg\\sidecars \\
        --quotes C:\\tmp\\ncaaf_seg\\quotes --linescores C:\\tmp\\ncaaf_seg\\linescores.json \\
        --out C:\\tmp\\ncaaf_seg\\result.json [--count-only]
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import re
import statistics
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts.nfl_segment_skill import (  # noqa: E402 -- the #752 method, unchanged
    SEGMENTS,
    _ts,
    clustered_ci,
    consensus_markets,
    grade,
    iter_quotes,
    segment_outcome,
)

ESPN_SCOREBOARD = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
    "?dates={ymd}&groups=80&limit=400"
)
_CSV_RE = re.compile(r"smartsim2_projections_(\d{4})_wk(\d+)\.csv$")
_SIDECAR_RE = re.compile(r"smartsim2_segment_distributions_(\d{4})_wk(\d+)\.json$")


# ----------------------------------------------------------------- inputs ----
def load_weeks(sidecar_dir: Path) -> dict[tuple[int, int], dict[str, Any]]:
    """`{(season, week): {"pairs": {(home, away): game_id}, "blocks": {...}, "generated_at": str}}`.

    The pair keys are `_norm` of the CSV's own names -- the map production builds in
    `load_ncaaf_segment_inputs`. A week without a sidecar is kept with no blocks so
    the refusal is counted rather than invisible."""
    from syndicate.features.ncaaf.game_projections import _norm

    weeks: dict[tuple[int, int], dict[str, Any]] = {}
    for path_text in sorted(glob.glob(str(sidecar_dir / "smartsim2_projections_*_wk*.csv"))):
        match = _CSV_RE.search(path_text)
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        pairs: dict[tuple[str, str], str] = {}
        with open(path_text, "r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                home, away = str(row.get("home_team") or "").strip(), str(row.get("away_team") or "").strip()
                game_id = str(row.get("game_id") or "").strip()
                if home and away and game_id:
                    pairs[(_norm(home), _norm(away))] = game_id
        weeks[key] = {"pairs": pairs, "blocks": {}, "generated_at": None}
    for path_text in sorted(glob.glob(str(sidecar_dir / "smartsim2_segment_distributions_*_wk*.json"))):
        match = _SIDECAR_RE.search(path_text)
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        payload = json.loads(Path(path_text).read_text(encoding="utf-8"))
        slot = weeks.setdefault(key, {"pairs": {}, "blocks": {}, "generated_at": None})
        slot["blocks"] = {str(g): b for g, b in (payload.get("games") or {}).items()}
        slot["generated_at"] = payload.get("generated_at")
    return weeks


def fetch_linescores(dates: Iterable[str], cache: Path) -> dict[str, dict[str, Any]]:
    """`{espn_event_id: {date, home_name, away_name, home, away, final}}` from ESPN."""
    from syndicate.features.shared.segment_actuals import linescores_from_competitor

    have: dict[str, Any] = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}
    games = have.setdefault("games", {})
    fetched = set(have.setdefault("dates_fetched", []))
    for ymd in sorted(set(dates)):
        if ymd in fetched:
            continue
        req = urllib.request.Request(ESPN_SCOREBOARD.format(ymd=ymd.replace("-", "")),
                                     headers={"User-Agent": "segment-grade/1.0"})
        payload = json.load(urllib.request.urlopen(req, timeout=60))
        for event in payload.get("events") or []:
            comp = (event.get("competitions") or [{}])[0]
            status = (comp.get("status") or {}).get("type") or {}
            teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            if "home" not in teams or "away" not in teams:
                continue
            games[str(event.get("id"))] = {
                "date": str(event.get("date") or comp.get("date") or ""),
                "home_name": (teams["home"].get("team") or {}).get("displayName"),
                "away_name": (teams["away"].get("team") or {}).get("displayName"),
                "home": linescores_from_competitor(teams["home"]),
                "away": linescores_from_competitor(teams["away"]),
                "final": bool(status.get("completed")),
            }
        fetched.add(ymd)
        have["dates_fetched"] = sorted(fetched)
        cache.write_text(json.dumps(have, indent=1), encoding="utf-8")
    return games


# ------------------------------------------------------------------ bridge ----
def bridge(c: Mapping[str, Any], weeks: Mapping[tuple[int, int], Mapping[str, Any]],
           boxes: Mapping[str, Mapping[str, Any]]) -> tuple[str | None, dict[str, Any]]:
    """`(refusal, found)` for one quoted market. `found` has week, game_id, block, box."""
    from syndicate.features.ncaaf.game_projections import _norm
    from syndicate.features.ncaaf.oddsapi_lines import resolve_team

    pair = (_norm(resolve_team(c.get("home_team"))), _norm(resolve_team(c.get("away_team"))))
    if not pair[0] or not pair[1]:
        return "team_unresolved", {}
    start = _ts(str(c["commence_time"]))
    candidates = [(wk, slot["pairs"][pair]) for wk, slot in sorted(weeks.items()) if pair in slot["pairs"]]
    if not candidates:
        return "no_projection_pair", {}
    dated = []
    for wk, game_id in candidates:
        box = boxes.get(str(game_id))
        if box and box.get("date") and abs((_ts(box["date"]) - start).total_seconds()) <= 86400:
            dated.append((wk, game_id, box))
    if not dated:
        return "no_espn_event_near_kickoff", {}
    if len(dated) > 1:
        return "ambiguous_week", {}
    wk, game_id, box = dated[0]
    slot = weeks[wk]
    block = slot["blocks"].get(str(game_id))
    if not isinstance(block, Mapping):
        return "no_sim_block", {}
    gen = slot.get("generated_at")
    if not gen or _ts(str(gen)) >= start:
        return "sidecar_written_after_kickoff", {}
    if not box.get("final"):
        return "no_final_box", {}
    return None, {"week": wk, "game_id": str(game_id), "block": block, "box": box, "generated_at": gen}


def build_observations(consensus, weeks, boxes, *, count_only: bool = False):
    from syndicate.features.ncaaf.segment_projections import _histogram, _segment_block, probability_above
    from syndicate.features.shared.segment_actuals import segment_score_pair

    refused: dict[str, int] = defaultdict(int)
    eligible: set[tuple[str, str, str]] = set()
    obs = []
    for (event, seg, market), c in sorted(consensus.items()):
        why, found = bridge(c, weeks, boxes)
        if why:
            refused[why] += 1
            continue
        block = found["block"]
        sb = _segment_block(block, seg) or {}
        hist = _histogram(sb, "total_points_dist" if market == "totals" else "margin_dist")
        if hist is None:
            refused["no_histogram"] += 1
            continue
        p_model, _push = probability_above(hist, c["line"])
        if p_model is None:
            refused["model_all_push"] += 1
            continue
        eligible.add((event, seg, market))
        if count_only:
            continue  # NO OUTCOME IS READ before the registration is on main.
        box = found["box"]
        pair = segment_score_pair("ncaaf", seg, home_linescores=box["home"], away_linescores=box["away"])
        if pair is None:
            refused["no_segment_score"] += 1
            continue
        y = segment_outcome(market, c["line"], *pair)
        if y is None:
            refused["push"] += 1
            continue
        obs.append({
            "game": event, "espn_id": found["game_id"], "segment": seg, "market": market,
            "line": c["line"], "y": y, "p_model": p_model, "p_market": c["market_prob"],
            "books": c["books_at_line"], "sim_week": found["week"][1], "home": c["home_team"],
            "away": c["away_team"], "commence_time": c["commence_time"],
            "sidecar_generated_at": found["generated_at"], "home_pts": pair[0], "away_pts": pair[1],
        })
    return obs, dict(refused), eligible


def engine_read(weeks, boxes, *, reps: int, seed: int) -> dict[str, Any]:
    """Every 2026 sidecar game with a final box and a write before kickoff: per-segment
    sim mean vs actual, PIT of totals, quarter shares. Descriptive only."""
    from syndicate.features.ncaaf.segment_projections import _histogram, _segment_block
    from syndicate.features.shared.segment_actuals import segment_score_pair

    rows = []
    for (season, _wk), slot in sorted(weeks.items()):
        gen = slot.get("generated_at")
        if season != 2026 or not gen:
            continue
        for game_id, block in slot["blocks"].items():
            box = boxes.get(str(game_id))
            if not box or not box.get("final") or not box.get("date") or _ts(box["date"]) <= _ts(str(gen)):
                continue
            for seg in ("full", *SEGMENTS):
                sb = _segment_block(block, seg)
                if not sb:
                    continue
                if seg == "full":
                    pair = (sum(v or 0 for v in box["home"]), sum(v or 0 for v in box["away"]))
                else:
                    pair = segment_score_pair("ncaaf", seg, home_linescores=box["home"], away_linescores=box["away"])
                if pair is None:
                    continue
                hist = _histogram(sb, "total_points_dist") or {}
                total = sum(hist.values()) or 1
                actual = pair[0] + pair[1]
                below = sum(n for v, n in hist.items() if float(v) < actual) / total
                at = sum(n for v, n in hist.items() if float(v) == actual) / total
                rows.append({"game": str(game_id), "segment": seg,
                             "sim_total": float(sb["home_points_mean"]) + float(sb["away_points_mean"]),
                             "sim_margin": float(sb["home_points_mean"]) - float(sb["away_points_mean"]),
                             "actual_total": actual, "actual_margin": pair[0] - pair[1],
                             "pit_mid": below + at / 2.0})
    out: dict[str, Any] = {"games": len({r["game"] for r in rows})}
    for seg in ("full", *SEGMENTS):
        sub = [r for r in rows if r["segment"] == seg]
        if not sub:
            continue
        bias = clustered_ci(sub, lambda r: r["sim_total"] - r["actual_total"], reps=reps, seed=seed)
        mbias = clustered_ci(sub, lambda r: r["sim_margin"] - r["actual_margin"], reps=reps, seed=seed)
        pits = sorted(r["pit_mid"] for r in sub)
        out[seg] = {
            "n": len(sub),
            "sim_total_mean": round(sum(r["sim_total"] for r in sub) / len(sub), 2),
            "actual_total_mean": round(sum(r["actual_total"] for r in sub) / len(sub), 2),
            "total_bias": [round(x, 2) for x in bias],
            "margin_bias": [round(x, 2) for x in mbias],
            "actual_total_sd": round(statistics.pstdev(r["actual_total"] for r in sub), 2),
            "pit_outer_20pct": round(sum(1 for p in pits if p < 0.1 or p > 0.9) / len(pits), 3),
        }
    full = out.get("full", {}).get("actual_total_mean")
    sim_full = out.get("full", {}).get("sim_total_mean")
    if full and sim_full:
        out["quarter_share"] = {
            q: {"sim": round(out[q]["sim_total_mean"] / sim_full, 3), "actual": round(out[q]["actual_total_mean"] / full, 3)}
            for q in ("q1", "q2", "q3", "q4") if q in out
        }
    return out


def established_loss_rel(family: Mapping[str, Any]) -> float:
    """The registered rule: max(0, CI lower) / Brier(market), 0.0 when not established."""
    try:
        lo = float(family["ci95"][0])
        market = float(family["brier_market"])
    except (KeyError, TypeError, ValueError, IndexError):
        return 0.0
    if not lo > 0 or not market > 0:
        return 0.0
    return round(lo / market, 5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sidecars", required=True)
    ap.add_argument("--quotes", required=True)
    ap.add_argument("--linescores", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=804)
    ap.add_argument("--count-only", action="store_true",
                    help="population counts only; no outcome is read or graded")
    args = ap.parse_args(argv)

    weeks = load_weeks(Path(args.sidecars))
    consensus = consensus_markets(iter_quotes(sorted(glob.glob(str(Path(args.quotes) / "*.jsonl*")))))
    starts = {_ts(str(c["commence_time"])) for c in consensus.values()}
    dates = {d.strftime("%Y-%m-%d") for s in starts for d in (s, s - timedelta(days=1))}
    boxes = fetch_linescores(dates, Path(args.linescores))

    obs, refused, eligible = build_observations(consensus, weeks, boxes, count_only=args.count_only)
    population = {
        "segment_markets_quoted": len(consensus),
        "games_quoted": len({k[0] for k in consensus}),
        "refused": refused,
        "eligible_markets": len(eligible),
        "eligible_games": len({k[0] for k in eligible}),
        "weeks": {f"{s}_wk{w}": {"pairs": len(v["pairs"]), "blocks": len(v["blocks"]),
                                 "generated_at": v["generated_at"]} for (s, w), v in sorted(weeks.items())},
    }
    if args.count_only:
        by_family: dict[str, set[str]] = defaultdict(set)
        markets_by_family: dict[str, int] = defaultdict(int)
        for (event, _seg, market) in eligible:
            by_family[market].add(event)
            markets_by_family[market] += 1
        population["eligible_games_by_family"] = {m: len(v) for m, v in sorted(by_family.items())}
        population["eligible_markets_by_family"] = dict(sorted(markets_by_family.items()))
        print(json.dumps({"count_only": True, "population": population}, indent=1))
        return 0
    population.update({"observations": len(obs), "games": len({o["game"] for o in obs}),
                       "first_kickoff": min((o["commence_time"] for o in obs), default=None),
                       "last_kickoff": max((o["commence_time"] for o in obs), default=None)})
    graded = grade(obs, reps=args.reps, seed=args.seed)
    for family in graded["families"].values():
        if family.get("n"):
            family["established_loss_rel"] = established_loss_rel(family)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "population": population,
        "grade": graded,
        "engine": engine_read(weeks, boxes, reps=args.reps, seed=args.seed),
    }
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    Path(args.out).with_suffix(".obs.json").write_text(json.dumps(obs), encoding="utf-8")
    print(json.dumps({"population": population, "families": graded["families"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
