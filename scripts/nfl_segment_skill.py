"""Grade NFL quarter/half game-line probabilities against the market and the box (todo #752).

WHY. `nfl_segment_projections.attach_nfl_segment_projections` prices NFL h1/h2/q1-q4
rows off the sim's own segment histograms (`ace49609b`, 2026-10-08) and stamps
`model_skill: {"state": "unmeasured"}` on every one. Nothing ever measured them, and
an unmeasured note scores `skill_reliability` 1.0, so they rank at full weight. The
lane that asked for this pricing (`nfl-segment-model`) made "a held-out check that
the segment probabilities are calibrated before they rank anything" its verification.
This is that check.

PRE-REGISTERED (lane `nfl-segment-skill`, `.syndicate/lanes.md`, before any data was
graded):
- Population: every NFL game with (a) a pregame quote on a segment market
  (captured_at < commence_time) in `nfl_source/tracking/book_quotes/<date>.jsonl.gz`,
  (b) a regular-season `smartsim2_segment_distributions_<season>_wk<w>.json` block for
  the same matchup, and (c) a final ESPN linescore.
- Market: each book's LAST pregame two-sided pair, de-vigged proportionally; the
  consensus line is the line most books quote (ties -> nearer the median of all
  book lines); the market probability is the mean of the de-vigged books AT that line.
- Model: exactly production's arithmetic -- `ncaaf.segment_projections.probability_above`
  over the sidecar histogram, home/over side, line in the away frame (home covers
  strictly past it), h2h = segment margin > 0. Pushes are dropped from both sides.
- One observation per (game, segment, market). Families: totals, spreads, h2h, each
  pooled over h1/h2/q1-q4. dBrier = Brier(model) - Brier(market), 95% CI by a
  game-clustered bootstrap. Verdict: beats if the CI's upper bound < 0, loses if its
  lower bound > 0, parity otherwise (stated with n as underpowered).

AS-OF. The sidecar for week W is built from plays of weeks < W
(`generate_smartsim2_nfl_projections.team_rating`, `before_week`), so a file
regenerated after kickoff carries no information from that week's games.

    py -3 scripts/nfl_segment_skill.py --sidecars C:\\tmp\\nfl_seg\\sidecars \\
        --quotes C:\\tmp\\nfl_seg\\quotes --linescores C:\\tmp\\nfl_seg\\linescores.json \\
        --out C:\\tmp\\nfl_seg\\result.json
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import random
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

SEGMENTS = ("h1", "h2", "q1", "q2", "q3", "q4")
MARKETS = ("totals", "spreads", "h2h")
HOME_SIDE = {"totals": "over", "spreads": "home", "h2h": "home"}
AWAY_SIDE = {"totals": "under", "spreads": "away", "h2h": "away"}
ESPN_SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={ymd}"


# ---------------------------------------------------------------- prices ----
def american_to_prob(price: Any) -> float | None:
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if p >= 100:
        return 100.0 / (p + 100.0)
    if p <= -100:
        return -p / (-p + 100.0)
    return None


def devig_pair(home_price: Any, away_price: Any) -> float | None:
    """Proportional de-vig of one book's two-sided pair -> P(home/over)."""
    a, b = american_to_prob(home_price), american_to_prob(away_price)
    if a is None or b is None or a + b <= 0:
        return None
    return a / (a + b)


def frame_line(market: str, selection: str, line: Any) -> float | None:
    """The line in the grid's frame: totals as quoted, spreads in the AWAY frame
    (a home +6.5 quote is away -6.5; home covers when margin > -6.5), h2h 0."""
    if market == "h2h":
        return 0.0
    try:
        value = float(line)
    except (TypeError, ValueError):
        return None
    if market == "spreads" and selection == "home":
        return -value
    return value


def iter_quotes(paths: Iterable[str]) -> Iterable[dict[str, Any]]:
    for path in paths:
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as fh:  # type: ignore[operator]
            for raw in fh:
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue


def consensus_markets(quotes: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    """`{(event_id, segment, market): consensus}` from pregame segment quotes.

    Per book, only its LAST pregame snapshot counts, and only a pair quoted on
    both sides at the same framed line in that snapshot."""
    latest: dict[tuple[str, str, str, str], str] = {}
    keep: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    meta: dict[str, dict[str, Any]] = {}
    for q in quotes:
        if str(q.get("kind") or "") == "prop" or q.get("player_name"):
            continue
        seg, market = str(q.get("segment") or ""), str(q.get("market") or "")
        if seg not in SEGMENTS or market not in MARKETS:
            continue
        cap, start = str(q.get("captured_at") or ""), str(q.get("commence_time") or "")
        if not cap or not start or _ts(cap) >= _ts(start):
            continue
        event = str(q.get("event_id") or "")
        key = (event, seg, market, str(q.get("bookmaker") or ""))
        meta.setdefault(event, {"home_team": q.get("home_team"), "away_team": q.get("away_team"),
                                "commence_time": start})
        if key not in latest or cap > latest[key]:
            latest[key] = cap
            keep[key] = [q]
        elif cap == latest[key]:
            keep[key].append(q)
    per_market: dict[tuple[str, str, str], list[tuple[float, float, str]]] = defaultdict(list)
    for (event, seg, market, book), rows in keep.items():
        sides: dict[float, dict[str, Any]] = defaultdict(dict)
        for q in rows:
            sel = str(q.get("selection") or "")
            line = frame_line(market, sel, q.get("line"))
            if line is None or sel not in (HOME_SIDE[market], AWAY_SIDE[market]):
                continue
            sides[line][sel] = q.get("price")
        for line, pair in sides.items():
            p = devig_pair(pair.get(HOME_SIDE[market]), pair.get(AWAY_SIDE[market]))
            if p is not None:
                per_market[(event, seg, market)].append((line, p, book))
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, books in per_market.items():
        counts: dict[float, int] = defaultdict(int)
        for line, _p, _b in books:
            counts[line] += 1
        median = statistics.median(line for line, _p, _b in books)
        top = max(counts.values())
        line = min((ln for ln, n in counts.items() if n == top), key=lambda ln: (abs(ln - median), ln))
        probs = [p for ln, p, _b in books if ln == line]
        out[key] = {**meta[key[0]], "line": line, "market_prob": sum(probs) / len(probs),
                    "books_at_line": len(probs), "books": len(books)}
    return out


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


# --------------------------------------------------------------- outcomes ----
def segment_outcome(market: str, line: float, home: int, away: int) -> int | None:
    """1 home/over wins, 0 it loses, None a push -- the grid's own conventions."""
    value = home + away if market == "totals" else home - away
    if value > line:
        return 1
    if value < line:
        return 0
    return None


def fetch_linescores(dates: Iterable[str], cache: Path) -> dict[str, dict[str, Any]]:
    """`{"<home key>|<away key>|<YYYY-MM-DD kickoff UTC>": {home, away, final}}` from ESPN."""
    from syndicate.features.shared.segment_actuals import linescores_from_competitor
    from syndicate.features.shared.nfl_segment_projections import _team_key

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
            status = ((comp.get("status") or {}).get("type") or {})
            teams = {c.get("homeAway"): c for c in comp.get("competitors") or []}
            if "home" not in teams or "away" not in teams:
                continue
            home_key = _team_key((teams["home"].get("team") or {}).get("displayName"))
            away_key = _team_key((teams["away"].get("team") or {}).get("displayName"))
            start = str(event.get("date") or comp.get("date") or "")[:10]
            games[f"{home_key}|{away_key}|{start}"] = {
                "home": linescores_from_competitor(teams["home"]),
                "away": linescores_from_competitor(teams["away"]),
                "final": bool(status.get("completed")),
                "espn_id": event.get("id"),
            }
        fetched.add(ymd)
        have["dates_fetched"] = sorted(fetched)
        cache.write_text(json.dumps(have, indent=1), encoding="utf-8")
    return games


# ------------------------------------------------------------------ stats ----
def brier(p: float, y: int) -> float:
    return (p - y) ** 2


def clustered_ci(obs: list[dict[str, Any]], value, *, reps: int, seed: int) -> tuple[float, float, float]:
    """(mean, lo, hi) of `value(o)` with a bootstrap that resamples GAMES."""
    by_game: dict[str, list[float]] = defaultdict(list)
    for o in obs:
        by_game[o["game"]].append(value(o))
    games = sorted(by_game)
    if not games:
        return (float("nan"),) * 3  # type: ignore[return-value]
    mean = sum(sum(v) for v in by_game.values()) / sum(len(v) for v in by_game.values())
    rng = random.Random(seed)
    draws = []
    for _ in range(reps):
        total = n = 0.0
        for _g in games:
            vals = by_game[games[rng.randrange(len(games))]]
            total += sum(vals)
            n += len(vals)
        draws.append(total / n)
    draws.sort()
    return mean, draws[int(0.025 * reps)], draws[min(reps - 1, int(0.975 * reps))]


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def logistic_fit(xs: list[list[float]], ys: list[int], iters: int = 50) -> list[float] | None:
    """Plain IRLS logistic regression with an intercept; None if it does not converge."""
    k = len(xs[0]) + 1 if xs else 0
    if not xs or len(xs) <= k:
        return None
    beta = [0.0] * k
    for _ in range(iters):
        grad = [0.0] * k
        hess = [[0.0] * k for _ in range(k)]
        for x, y in zip(xs, ys):
            row = [1.0, *x]
            z = sum(b * v for b, v in zip(beta, row))
            p = 1.0 / (1.0 + math.exp(-max(min(z, 30), -30)))
            w = p * (1 - p)
            for i in range(k):
                grad[i] += (y - p) * row[i]
                for j in range(k):
                    hess[i][j] += w * row[i] * row[j]
        step = _solve(hess, grad)
        if step is None:
            return None
        beta = [b + s for b, s in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-8:
            return beta
    return beta


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] / m[i][i] for i in range(n)]


# ------------------------------------------------------------------- main ----
def build_observations(consensus, blocks, linescores) -> tuple[list[dict[str, Any]], dict[str, int]]:
    from syndicate.features.ncaaf.segment_projections import probability_above, _histogram, _segment_block
    from syndicate.features.shared.nfl_segment_projections import _season_for, _team_key
    from syndicate.features.shared.segment_actuals import segment_score_pair

    refused: dict[str, int] = defaultdict(int)
    obs = []
    for (event, seg, market), c in sorted(consensus.items()):
        home, away = _team_key(c["home_team"]), _team_key(c["away_team"])
        season = _season_for(c["commence_time"])
        block = blocks.get((season, home, away))
        if block is None:
            refused["no_sim_block"] += 1
            continue
        start = _ts(c["commence_time"])
        box = None
        for day in (start, start - timedelta(days=1)):
            box = linescores.get(f"{home}|{away}|{day.strftime('%Y-%m-%d')}")
            if box:
                break
        if not box or not box.get("final"):
            refused["no_final_box"] += 1
            continue
        pair = segment_score_pair("nfl", seg, home_linescores=box["home"], away_linescores=box["away"])
        if pair is None:
            refused["no_segment_score"] += 1
            continue
        y = segment_outcome(market, c["line"], *pair)
        if y is None:
            refused["push"] += 1
            continue
        hist = _histogram(_segment_block(block, seg) or {}, "total_points_dist" if market == "totals" else "margin_dist")
        if hist is None:
            refused["no_histogram"] += 1
            continue
        p_model, _push = probability_above(hist, c["line"])
        if p_model is None:
            refused["model_all_push"] += 1
            continue
        sb = _segment_block(block, seg) or {}
        obs.append({
            "game": event, "segment": seg, "market": market, "line": c["line"], "y": y,
            "p_model": p_model, "p_market": c["market_prob"], "books": c["books_at_line"],
            "sim_week": block.get("game_id", "")[5:7], "home": home, "away": away,
            "commence_time": c["commence_time"], "home_pts": pair[0], "away_pts": pair[1],
            "sim_home_mean": sb.get("home_points_mean"), "sim_away_mean": sb.get("away_points_mean"),
        })
    return obs, dict(refused)


def grade(obs: list[dict[str, Any]], *, reps: int, seed: int) -> dict[str, Any]:
    def summarise(sub: list[dict[str, Any]]) -> dict[str, Any]:
        if not sub:
            return {"n": 0}
        diff = clustered_ci(sub, lambda o: brier(o["p_model"], o["y"]) - brier(o["p_market"], o["y"]), reps=reps, seed=seed)
        bm = sum(brier(o["p_model"], o["y"]) for o in sub) / len(sub)
        bk = sum(brier(o["p_market"], o["y"]) for o in sub) / len(sub)
        verdict = "beats_market" if diff[2] < 0 else ("loses_to_market" if diff[1] > 0 else "parity")
        out = {"n": len(sub), "games": len({o["game"] for o in sub}), "brier_model": round(bm, 5),
               "brier_market": round(bk, 5), "diff": round(diff[0], 5), "ci95": [round(diff[1], 5), round(diff[2], 5)],
               "verdict_class": verdict, "hit_rate": round(sum(o["y"] for o in sub) / len(sub), 4),
               "mean_p_model": round(sum(o["p_model"] for o in sub) / len(sub), 4),
               "mean_p_market": round(sum(o["p_market"] for o in sub) / len(sub), 4),
               "mean_abs_gap": round(sum(abs(o["p_model"] - o["p_market"]) for o in sub) / len(sub), 4)}
        for name, key in (("slope_model", "p_model"), ("slope_market", "p_market")):
            fit = logistic_fit([[_logit(o[key])] for o in sub], [o["y"] for o in sub])
            out[name] = round(fit[1], 3) if fit else None
        both = logistic_fit([[_logit(o["p_market"]), _logit(o["p_model"])] for o in sub], [o["y"] for o in sub])
        out["info_beyond_line"] = {"w_market": round(both[1], 3), "w_model": round(both[2], 3)} if both else None
        return out

    result: dict[str, Any] = {"families": {}, "by_segment": {}}
    for market in MARKETS:
        sub = [o for o in obs if o["market"] == market]
        result["families"][market] = summarise(sub)
        for seg in SEGMENTS:
            result["by_segment"][f"{market}/{seg}"] = summarise([o for o in sub if o["segment"] == seg])
    result["pooled_all"] = summarise(obs)
    return result


def engine_read(blocks: Mapping[Any, Mapping[str, Any]], linescores: Mapping[str, Any], *, reps: int, seed: int) -> dict[str, Any]:
    """Every sidecar game with a final box: per-segment sim mean vs actual, and PIT of totals."""
    from syndicate.features.ncaaf.segment_projections import _histogram, _segment_block
    from syndicate.features.shared.segment_actuals import segment_score_pair

    boxes_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for key, box in linescores.items():
        home, away, day = key.split("|")
        if box.get("final"):
            boxes_by_pair[(home, away)].append({**box, "day": day})
    rows = []
    for (season, home, away), block in blocks.items():
        if season != 2026 or not boxes_by_pair.get((home, away)):
            continue
        box = boxes_by_pair[(home, away)][0]
        for seg in ("full", *SEGMENTS):
            sb = _segment_block(block, seg)
            if not sb:
                continue
            if seg == "full":
                pair = (sum(v or 0 for v in box["home"]), sum(v or 0 for v in box["away"]))
            else:
                pair = segment_score_pair("nfl", seg, home_linescores=box["home"], away_linescores=box["away"])
            if pair is None:
                continue
            hist = _histogram(sb, "total_points_dist") or {}
            total = sum(hist.values()) or 1
            actual = pair[0] + pair[1]
            below = sum(n for v, n in hist.items() if float(v) < actual) / total
            at = sum(n for v, n in hist.items() if float(v) == actual) / total
            rows.append({"game": block.get("game_id"), "segment": seg,
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
            "pit_deciles": [sum(1 for p in pits if lo / 10 <= p < (lo + 1) / 10 or (lo == 9 and p == 1.0)) for lo in range(10)],
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sidecars", required=True)
    ap.add_argument("--quotes", required=True)
    ap.add_argument("--linescores", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=752)
    args = ap.parse_args(argv)

    from syndicate.features.shared.nfl_segment_projections import load_nfl_segment_blocks

    blocks = load_nfl_segment_blocks([Path(args.sidecars)])
    consensus = consensus_markets(iter_quotes(sorted(glob.glob(str(Path(args.quotes) / "*.jsonl*")))))
    starts = {_ts(c["commence_time"]) for c in consensus.values()}
    dates = {d.strftime("%Y-%m-%d") for s in starts for d in (s, s - timedelta(days=1))}
    # The engine read covers every sidecar week (from week 4), not only the quoted ones.
    weeks_start = min(starts) - timedelta(days=30) if starts else datetime.now(timezone.utc)
    day = weeks_start
    while day <= datetime.now(timezone.utc):
        dates.add(day.strftime("%Y-%m-%d"))
        day += timedelta(days=1)
    linescores = fetch_linescores(dates, Path(args.linescores))

    obs, refused = build_observations(consensus, blocks, linescores)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "population": {"segment_markets_quoted": len(consensus), "observations": len(obs),
                       "games": len({o["game"] for o in obs}), "refused": refused,
                       "sim_blocks": len(blocks), "first_kickoff": min((o["commence_time"] for o in obs), default=None),
                       "last_kickoff": max((o["commence_time"] for o in obs), default=None)},
        "grade": grade(obs, reps=args.reps, seed=args.seed),
        "engine": engine_read(blocks, linescores, reps=args.reps, seed=args.seed),
    }
    Path(args.out).write_text(json.dumps(result, indent=1), encoding="utf-8")
    Path(args.out).with_suffix(".obs.json").write_text(json.dumps(obs), encoding="utf-8")
    print(json.dumps({"population": result["population"], "families": result["grade"]["families"]}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
