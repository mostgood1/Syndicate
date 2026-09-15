"""Which buckets actually MAKE MONEY. Realised outcomes, not paper edge.

WHY THIS EXISTS. `bucket_live_edges.py` reports how loudly the model disagrees
with the market, per bucket. That is not profit. Its headline row --
`spreads q4_late`, n=2471, 20.49pp at edge/se 6.35 -- says the model disagrees
with the book late and confidently. It does not say the model is RIGHT, and
nothing in this repo has ever checked.

WHAT THIS MEASURES INSTEAD. For every ledger row whose game has a final:

    the model prefers a side (whichever way it differs from the market)
    -> did that side WIN?
    -> at what rate, against the rate a NULL says that side would win anyway?

The difference is the edge in probability points, which is the thing that turns
into money. Positive means the model's disagreement was right.

**`market_fair_prob` IS NOT A VALID BASELINE FOR TOTALS OR SPREADS, AND USING IT
WAS THIS SCRIPT'S BIGGEST ERROR.** Books price those markets about -110/-110, so
the de-vigged price is ~0.50 WHATEVER the line is -- measured market-leg sd:
h2h 0.251, spreads 0.132, totals 0.058. Confirmed here independently: the
within-game slope of P(over) against the line is **-0.005 per run** where a real
total needs about -0.12, and P(over) moves only 0.512 -> 0.453 across TEN runs
of line.

The market does not express its view as a probability. **It expresses it as the
LINE.** Comparing an informative model probability to a ~0.50 constant
manufactures edge out of nothing -- `live_gameline_ledger` already records that
this produced a fake ~90% ATS result in `subset_edge_scan` before that scan
learned to refuse these markets, and it is what produced +14pp of "realised
edge" here before this correction.

SO EACH MARKET IS SCORED THE WAY ITS PRICE IS ACTUALLY SET:

  h2h              the de-vig IS the market's view -> compare probabilities.
                   Gated on the market calibrating against the outcome, because
                   a flipped convention would otherwise read as a fake edge.

  totals, spreads  the LINE is the market's view -> compare POINT FORECASTS.
                   `model_total_mean` / `model_margin_mean` against the line,
                   scored on the actual total / margin via `point_forecast_side`.
                   Gated on the LINE tracking the actual outcome (game-level
                   correlation), the analogue of h2h's calibration gate.

**AND A CONSTANT 0.50 IS NOT A VALID NULL FOR THE POINT-FORECAST READ EITHER.**
Until 2026-09-15 `point_forecast_side` existed here but `main()` never called it,
and the scratch replay that finally did (74 games) showed why 0.50 alone is not
enough:

  * totals "+12.16pp" was the model backing the OVER in 69 of 73 games in a
    sample where overs landed 61.6% -- always-over won exactly as often.
  * spreads q4_late "+18.5pp" was the model siding with whichever team the
    CURRENT SCORE already covered (50/54) -- that rule alone won 72.2%, and the
    late run line is priced away from 0.50 (the backed side's de-vig ~0.67).

So every point-forecast bucket is scored against ALL of these nulls, and the
headline is the edge against the HARDEST one (`binding_null`):

  coin_flip       0.50. Shown for continuity with the old read; binding only if
                  every other null is weaker.
  side_base_rate  the bucket's own rate for the side the model backed (over-rate
                  if it backed over, under-rate if under). A model whose side
                  choice carries no information beyond "overs landed" scores 0.
  scoreboard      the win rate of the rule "back the side the CURRENT score
                  already sits on" (current total / margin vs the line), on the
                  same games. No lean (score exactly on the line) counts 0.5.
  market_price    the de-vigged price of the backed side, where the price is
                  oriented correctly. Refused per market, loudly, if the price
                  does not point the same way as the outcome.

A bet missing any null input (no score, no price) is SKIPPED by name rather than
scored against a weaker subset of nulls -- an unknown must never default to the
permissive branch.

A row without the mean field is UNMEASURED, never folded in with a probability
comparison as a substitute. Only `segment == full` point-forecast rows are
scored: a first-5 line cannot be resolved from the final score.

    h2h      outcome: the home team won
    totals   outcome: away + home > line          (equal = push, dropped)
    spreads  outcome: home margin > line          (canonical frame, `#262`)

THE DENOMINATOR IS GAMES, NOT ROWS, AND THE FIRST VERSION OF THIS SCRIPT GOT
THAT WRONG. The ledger writes a row per build per market per line per book set,
so 42,692 MLB rows over ten days resolve to **122 distinct games** -- a median of
334 rows per game, max 817. Treating those as independent produced +14.63pp of
"realised edge" at **+21 sigma**, a result that is impossible on its face: real
betting edges are 1-3pp. The binomial standard error was understated by roughly
sqrt(334) ~ 18x, and a handful of lucky games can carry hundreds of winning rows.

So every row is collapsed to ONE observation per (game, market, segment, band)
-- which is also the unit a bettor acts on: you back a game once, not 334 times.
`n_games` is printed beside every rate and the standard error is computed on it.

A bucket under `--min-n` prints UNMEASURED and no number. The top buckets are
re-checked on a chronological out-of-sample split, because picking the best of
many buckets in-sample finds noise every time.

Run:
    python scripts/bucket_realised_performance.py --sport mlb --days 14
    python scripts/bucket_realised_performance.py --rows-jsonl pulled.jsonl   # replay a pull
"""

from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict

REPO = pathlib.Path(__file__).resolve().parents[1]
BASE = "https://syndicate-an21.onrender.com"

PROGRESS_BANDS = [
    (0.00, 0.25, "q1_early"),
    (0.25, 0.50, "q2_midearly"),
    (0.50, 0.75, "q3_midlate"),
    (0.75, 1.01, "q4_late"),
]

# The line must track the actual outcome at least this well, per game, before a
# point-forecast market is scored. Measured 2026-09-15: totals 0.518, spreads
# 0.517 on 74 games. A frame flip reads NEGATIVE, so this is a direction check
# with some margin, not a quality bar.
_LINE_TRACKS_OUTCOME_MIN_CORR = 0.2


def secret(name: str) -> str:
    # The environment first: a session worktree has no `.env`, and copying one in
    # would put the secret inside a checkout.
    env = os.environ.get(name)
    if env:
        return env.strip().strip('"').strip("'")
    path = REPO / ".env"
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith(name):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def band_for(progress) -> str:
    try:
        p = float(progress)
    except (TypeError, ValueError):
        return "unknown_progress"
    for lo, hi, name in PROGRESS_BANDS:
        if lo <= p < hi:
            return name
    return "unknown_progress"


def ledger_rows(sport: str, days: int, token: str) -> list[dict]:
    import datetime as dt

    rows = []
    today = dt.datetime.now(dt.timezone.utc).date()
    for i in range(days):
        day = (today - dt.timedelta(days=i)).strftime("%Y-%m-%d")
        pat = (f"{sport}_source/data/live_gameline_ledger/"
               f"live_gameline_ledger_{day}.jsonl")
        u = f"{BASE}/api/ops/artifacts/export?" + urllib.parse.urlencode(
            {"pattern": pat, "limit": "1"})
        try:
            rq = urllib.request.Request(u, headers={"X-Admin-Token": token,
                                                    "Accept": "application/json"})
            with urllib.request.urlopen(rq, timeout=240) as r:
                arts = json.load(r).get("artifacts") or {}
        except Exception as exc:
            print(f"  {day}: {type(exc).__name__}", flush=True)
            continue
        n0 = len(rows)
        for _name, raw in arts.items():
            body = raw if isinstance(raw, str) else json.dumps(raw)
            for line in body.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
        print(f"  {day}: {len(rows) - n0} rows", flush=True)
    return rows


def finals_for(dates: set[str]) -> dict[str, tuple[int, int]]:
    """game_pk -> (away_runs, home_runs) for FINAL games."""
    out: dict[str, tuple[int, int]] = {}
    for date in sorted(dates):
        url = (f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"
               f"&hydrate=linescore")
        try:
            with urllib.request.urlopen(url, timeout=60) as resp:
                doc = json.load(resp)
        except Exception:
            continue
        for day in doc.get("dates") or []:
            for g in day.get("games") or []:
                if str(((g.get("status") or {}).get("abstractGameState") or "")).lower() != "final":
                    continue
                ls = g.get("linescore") or {}
                teams = ls.get("teams") or {}
                a = (teams.get("away") or {}).get("runs")
                h = (teams.get("home") or {}).get("runs")
                if a is None or h is None:
                    continue
                out[str(g.get("gamePk"))] = (int(a), int(h))
    return out


# Point-forecast markets: the LINE is the market view, and the model's own mean
# is what competes with it. Keyed by the ledger column that carries that mean --
# note the column is `model_total_mean`, NOT `total_mean`; reading the latter
# returns None on every row and looks exactly like an unfed field.
_POINT_FORECAST = {
    "totals": ("model_total_mean", lambda a, h: a + h),
    "totals_alt": ("model_total_mean", lambda a, h: a + h),
    "spreads": ("model_margin_mean", lambda a, h: h - a),
    "spreads_alt": ("model_margin_mean", lambda a, h: h - a),
}


def point_forecast_side(rec: dict, final: tuple[int, int]):
    """(model_side_won, ok) for a market whose view is the LINE.

    The model backs the over/home when its own mean sits above the line. The
    outcome is the actual total/margin against that same line, so nothing here
    touches `market_fair_prob` -- which is ~0.50 by construction and carries no
    information about where the line is.
    """
    market = str(rec.get("market") or "").strip().lower()
    spec = _POINT_FORECAST.get(market)
    if spec is None:
        return None, False
    col, actual_fn = spec
    mean = rec.get(col)
    line = rec.get("line")
    if mean is None or line is None:
        return None, False
    try:
        mean, line = float(mean), float(line)
    except (TypeError, ValueError):
        return None, False
    away, home = final
    actual = actual_fn(away, home)
    if actual == line or abs(mean - line) < 1e-9:
        return None, False        # push, or the model has no lean
    return (mean > line) == (actual > line), True


def _score_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def point_forecast_entry(rec: dict, final: tuple[int, int]):
    """(entry, skip_reason) for one point-forecast row. Exactly one is None.

    `won` comes from `point_forecast_side` and nowhere else, so this path and the
    production scorer (`live_gameline_score`, which mirrors that function) cannot
    disagree about what a hit is. Everything else here is the NULLS' inputs.
    """
    market = str(rec.get("market") or "").strip().lower()
    spec = _POINT_FORECAST.get(market)
    if spec is None:
        return None, "not_a_point_forecast_market"
    if str(rec.get("segment") or "") != "full":
        return None, "segment_not_full_game"
    won, ok = point_forecast_side(rec, final)
    if not ok:
        return None, "no_mean_or_push_or_no_lean"
    col, actual_fn = spec
    mean, line = float(rec[col]), float(rec["line"])
    away, home = final
    backs_first = mean > line
    first_won = actual_fn(away, home) > line

    # SCOREBOARD: the side the current score already sits on. Missing scores are
    # a skip, not a 0.5 -- a 0.5 would quietly weaken the hardest null.
    cur_away, cur_home = _score_int(rec.get("away_score")), _score_int(rec.get("home_score"))
    if cur_away is None or cur_home is None:
        return None, "no_current_score"
    current = actual_fn(cur_away, cur_home)
    if current == line:
        scoreboard = 0.5
    else:
        scoreboard = 1.0 if (current > line) == first_won else 0.0

    mp = rec.get("market_fair_prob")
    try:
        mp = float(mp)
    except (TypeError, ValueError):
        return None, "no_market_price"
    return {
        "kind": "point",
        "won": won,
        "backs_first": backs_first,
        "first_won": first_won,
        "scoreboard": scoreboard,
        "first_price": mp,
        "implied": mp if backs_first else 1.0 - mp,
        "edge": abs(mean - line),
    }, None


def line_convention_gate(rows: list[dict], finals: dict, market: str, min_n: int):
    """Game-level corr(line, actual) on the earliest scoreable row per game.

    Returns (corr, n_games). A flipped frame reads negative; a join that paired
    lines with the wrong game reads ~0.
    """
    spec = _POINT_FORECAST[market]
    _col, actual_fn = spec
    first: dict[str, dict] = {}
    for r in rows:
        if str(r.get("market") or "").strip().lower() != market:
            continue
        if str(r.get("segment") or "") != "full" or r.get("line") is None:
            continue
        pk = str(r.get("game_pk") or "")
        if pk not in finals:
            continue
        stamp = str(r.get("recorded_at") or "")
        if pk not in first or stamp < str(first[pk].get("recorded_at") or ""):
            first[pk] = r
    lines, actuals = [], []
    for pk, r in first.items():
        try:
            lines.append(float(r["line"]))
        except (TypeError, ValueError):
            continue
        actuals.append(float(actual_fn(*finals[pk])))
    if len(lines) < min_n:
        return None, len(lines)
    try:
        return statistics.correlation(lines, actuals), len(lines)
    except statistics.StatisticsError:
        return None, len(lines)


def price_points_the_right_way(entries: list[dict]) -> bool:
    """Is `market_fair_prob` P(first side)? Mean price must be higher on the games
    where the first side won. A reversed orientation would turn `market_price`
    into a null the model beats for free."""
    won = [e["first_price"] for e in entries if e["first_won"]]
    lost = [e["first_price"] for e in entries if not e["first_won"]]
    if not won or not lost:
        return False
    return statistics.mean(won) >= statistics.mean(lost)


def score_bucket(vals: list[dict], price_ok: bool = True) -> dict:
    """Edge against every null, and the headline against the HARDEST.

    Point-forecast se is the larger of the binomial se on the win rate and the
    paired se of (won - null): a per-bet null may never shrink the bar below what
    the win rate alone would carry. Probability buckets keep the binomial se they
    have always had, so h2h numbers stay comparable with the 09-08 and 09-15 runs.
    """
    n = len(vals)
    won = [1.0 if v["won"] else 0.0 for v in vals]
    rate = statistics.mean(won)
    binom_se = math.sqrt(max(rate * (1 - rate), 1e-9) / n)
    if vals[0]["kind"] == "probability":
        nulls = {"market_price": [v["implied"] for v in vals]}
    else:
        p_first = statistics.mean(1.0 if v["first_won"] else 0.0 for v in vals)
        nulls = {
            "coin_flip": [0.5] * n,
            "side_base_rate": [p_first if v["backs_first"] else 1.0 - p_first for v in vals],
            "scoreboard": [v["scoreboard"] for v in vals],
        }
        if price_ok:
            nulls["market_price"] = [v["implied"] for v in vals]
    per = {}
    for name, xs in nulls.items():
        d = [w - x for w, x in zip(won, xs)]
        if vals[0]["kind"] == "probability":
            se = binom_se * 100
        else:
            paired_se = statistics.stdev(d) / math.sqrt(n) if n > 1 else float("inf")
            se = max(binom_se, paired_se) * 100
        edge = statistics.mean(d) * 100
        per[name] = {"null_pct": statistics.mean(xs) * 100, "edge_pp": edge,
                     "se": se, "sigma": edge / se if se else None}
    binding = min(per, key=lambda k: per[k]["edge_pp"])
    return {"n": n, "won_pct": rate * 100, "nulls": per, "binding_null": binding,
            **{k: per[binding][k] for k in ("null_pct", "edge_pp", "se", "sigma")}}


def resolve(rec: dict, final: tuple[int, int], spread_sign: float):
    """(first_side_won, ok). `first_side` is home for h2h/spreads, over for totals."""
    away, home = final
    market = str(rec.get("market") or "").strip().lower()
    if market == "h2h":
        if home == away:
            return None, False
        return home > away, True
    line = rec.get("line")
    try:
        line = float(line)
    except (TypeError, ValueError):
        return None, False
    if market in {"totals", "totals_alt"}:
        total = away + home
        if total == line:
            return None, False            # push
        return total > line, True
    if market in {"spreads", "spreads_alt"}:
        margin = home - away
        adj = margin + spread_sign * line
        if abs(adj) < 1e-9:
            return None, False            # push
        return adj > 0, True
    return None, False


def brier(pairs):
    return sum((p - (1.0 if w else 0.0)) ** 2 for p, w in pairs) / len(pairs)


def _read_jsonl(path: pathlib.Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sport", default="mlb")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--json", type=pathlib.Path)
    ap.add_argument("--rows-jsonl", type=pathlib.Path,
                    help="replay ledger rows from a local JSONL (a saved production "
                         "pull) instead of fetching; say which you used")
    args = ap.parse_args(argv)

    if args.rows_jsonl:
        rows = _read_jsonl(args.rows_jsonl)
        print(f"REPLAY of {args.rows_jsonl}: {len(rows)} ledger rows (not a fresh pull)")
    else:
        token = secret("ADMIN_TOKEN")
        print(f"pulling {args.sport} ledger, {args.days} days")
        rows = ledger_rows(args.sport, args.days, token)
        print(f"TOTAL ledger rows: {len(rows)}")
    if not rows:
        print("UNMEASURED: no ledger rows.")
        return 1

    dates = {str(r.get("date") or "")[:10] for r in rows if r.get("date")}
    finals = finals_for({d for d in dates if d})
    print(f"finals fetched for {len(finals)} games across {len(dates)} dates\n")

    # ---- GATES, per market. Probability markets must calibrate; point-forecast
    # markets must have a LINE that tracks the outcome. They are never gated on
    # `market_fair_prob`, which is ~0.50 there by construction.
    usable_markets = {}
    point_markets = set()
    for market in sorted({str(r.get("market") or "").strip().lower() for r in rows}):
        if not market:
            continue
        if market in _POINT_FORECAST:
            corr, n_games = line_convention_gate(rows, finals, market, args.min_n)
            if corr is None:
                print(f"  {market:12s} UNMEASURED (fewer than {args.min_n} games with a "
                      f"full-game line, n={n_games})")
                continue
            ok = corr >= _LINE_TRACKS_OUTCOME_MIN_CORR
            print(f"  {market:12s} games={n_games:4d} corr(line, actual)={corr:+.3f}   "
                  f"-> {'USABLE (point forecast)' if ok else 'REFUSED'}")
            if ok:
                point_markets.add(market)
            else:
                print(f"       ** the LINE does not track the outcome under the home-margin "
                      f"/ over frame. That points at the frame or the join, not the book. **")
            continue
        cands = [+1.0]
        best = None
        for sign in cands:
            pairs = []
            for r in rows:
                if str(r.get("market") or "").strip().lower() != market:
                    continue
                mp = r.get("market_fair_prob")
                pk = str(r.get("game_pk") or "")
                if mp is None or pk not in finals:
                    continue
                won, ok = resolve(r, finals[pk], sign)
                if not ok:
                    continue
                pairs.append((float(mp), won))
            if len(pairs) < args.min_n:
                continue
            b = brier(pairs)
            rate = sum(1 for _p, w in pairs if w) / len(pairs)
            base = sum((rate - (1.0 if w else 0.0)) ** 2 for _p, w in pairs) / len(pairs)
            if best is None or b < best["brier"]:
                best = {"sign": sign, "brier": b, "baseline": base,
                        "n": len(pairs),
                        "mean_pred": statistics.mean(p for p, _w in pairs),
                        "rate": rate}
        if best is None:
            print(f"  {market:12s} UNMEASURED (fewer than {args.min_n} scoreable rows)")
            continue
        skill = 1.0 - best["brier"] / best["baseline"] if best["baseline"] else float("nan")
        # 3pp, not 10pp. The first cut used 0.10 and passed TOTALS at a
        # miscalibration of 0.099 -- the market predicting 49.0% while 58.9%
        # of overs actually landed. A book does not miss by ten points; that
        # gap is MY outcome resolution being wrong, and the loose gate let it
        # through into a headline edge.
        ok = skill > 0 and abs(best["mean_pred"] - best["rate"]) < 0.03
        print(f"  {market:12s} n={best['n']:5d} sign={best['sign']:+.0f}  "
              f"market Brier {best['brier']:.4f} vs base {best['baseline']:.4f} "
              f"(skill {skill:+.3f})  mean_pred {best['mean_pred']:.3f} vs "
              f"actual {best['rate']:.3f}   -> {'USABLE' if ok else 'REFUSED'}")
        if ok:
            usable_markets[market] = best["sign"]
        else:
            print(f"       ** the MARKET does not calibrate against this outcome "
                  f"resolution. That points at MY join, not the book. Refusing "
                  f"this market rather than reporting a fake edge. **")
    if not usable_markets and not point_markets:
        print("\nUNMEASURED: no market passed its gate.")
        return 1

    # ---- bucket the model's realised edge
    buckets = defaultdict(list)
    seen: dict = {}
    skipped = defaultdict(int)
    for r in rows:
        market = str(r.get("market") or "").strip().lower()
        pk = str(r.get("game_pk") or "")
        if market in point_markets:
            if pk not in finals:
                skipped["no_final"] += 1
                continue
            entry, reason = point_forecast_entry(r, finals[pk])
            if entry is None:
                skipped[f"point:{reason}"] += 1
                continue
        elif market in usable_markets:
            mp = r.get("market_fair_prob")
            model = r.get("model_home_win_prob")
            if mp is None or model is None:
                skipped["no_probability"] += 1
                continue
            if pk not in finals:
                skipped["no_final"] += 1
                continue
            won, ok = resolve(r, finals[pk], usable_markets[market])
            if not ok:
                skipped["push_or_unresolved"] += 1
                continue
            model, mp = float(model), float(mp)
            backs_first = model > mp
            entry = {"kind": "probability", "won": won if backs_first else (not won),
                     "implied": mp if backs_first else (1.0 - mp),
                     "edge": abs(model - mp)}
        else:
            skipped["market_not_usable"] += 1
            continue
        key = (str(r.get("game_state") or "?"), market,
               str(r.get("segment") or "?"), band_for(r.get("progress_fraction")))
        # ONE OBSERVATION PER GAME PER BUCKET PER LINE. See the module docstring:
        # the ledger writes hundreds of rows per game and treating them as
        # independent inflated sigma ~18x. The earliest row is kept because it is
        # the first moment the signal was actionable.
        # LINE IS **NOT** IN THIS KEY, and that is the whole correction.
        # Keeping it left 542 "bets" across 94 games -- 5.8 lines per game, all
        # resolving off the SAME final score, so a game the model called right
        # contributed ~6 wins and the standard error was still ~2.4x too small.
        # h2h, which has one line per game, collapsed to 94/94 and showed no
        # edge; spreads kept showing +14pp. That asymmetry was the tell.
        # One bet per game per bucket, comparable across markets.
        dedup_key = (key, pk)
        stamp = str(r.get("recorded_at") or "")
        prior = seen.get(dedup_key)
        if prior is not None and prior[0] <= stamp:
            skipped["duplicate_row_same_game"] += 1
            continue
        if prior is not None:
            buckets[key].remove(prior[1])
            skipped["duplicate_row_same_game"] += 1
        entry["date"] = str(r.get("date") or "")
        entry["game"] = pk
        seen[dedup_key] = (stamp, entry)
        buckets[key].append(entry)

    # Price orientation, per point market, over every bet that market kept.
    price_ok = {}
    for market in sorted(point_markets):
        ents = [e for k, vals in buckets.items() if k[1] == market for e in vals]
        price_ok[market] = price_points_the_right_way(ents)
        if ents and not price_ok[market]:
            print(f"  {market:12s} market_price null REFUSED: the de-vig does not point "
                  f"the same way as the outcome, so it is not P(over/home covers)")

    print(f"\nskipped: {dict(skipped)}")
    print(f"\n{'state':7s} {'market':9s} {'seg':7s} {'band':13s} {'bets':>5s} "
          f"{'games':>6s} {'won%':>7s} {'null%':>7s} {'EDGE pp':>8s} {'se':>6s} "
          f"{'sigma':>6s}  binding null")
    out_rows = []
    for key in sorted(buckets, key=lambda k: (k[1], -len(buckets[k]))):
        vals = buckets[key]
        n = len(vals)
        if n < args.min_n:
            print(f"{key[0]:7s} {key[1]:9s} {key[2]:7s} {key[3]:13s} {n:5d}   "
                  f"UNMEASURED (n<{args.min_n})")
            continue
        s = score_bucket(vals, price_ok.get(key[1], True))
        ngames = len({v["game"] for v in vals})
        print(f"{key[0]:7s} {key[1]:9s} {key[2]:7s} {key[3]:13s} {n:5d} "
              f"{ngames:6d} {s['won_pct']:7.2f} {s['null_pct']:7.2f} {s['edge_pp']:+8.2f} "
              f"{s['se']:6.2f} {s['sigma']:+6.2f}  {s['binding_null']}")
        if key[1] in point_markets:
            print("        " + "  ".join(
                f"{name} {v['null_pct']:.1f}: {v['edge_pp']:+.1f}"
                for name, v in s["nulls"].items()))
        out_rows.append({"state": key[0], "market": key[1], "segment": key[2],
                         "band": key[3], "n": n, "won_pct": s["won_pct"],
                         "null_pct": s["null_pct"], "edge_pp": s["edge_pp"],
                         "se": s["se"], "sigma": s["sigma"],
                         "binding_null": s["binding_null"], "nulls": s["nulls"],
                         "scoring": "point_forecast" if key[1] in point_markets else "probability",
                         "n_games": ngames,
                         "dates": sorted({v["date"] for v in vals})})

    print("\n  EDGE pp = how often the model's side WON minus how often the HARDEST null "
          "said it would.\n  Positive = the model's disagreement was right. This is "
          "a NO-VIG figure: real\n  prices are worse, so a bucket needs to clear the "
          "spread before it is money.")

    # ---- out-of-sample check on the leaders
    leaders = sorted([r for r in out_rows if r["n"] >= args.min_n],
                     key=lambda r: -(r["sigma"] or 0))[:5]
    if leaders:
        print(f"\nOUT-OF-SAMPLE CHECK on the top buckets (chronological split):")
        for lead in leaders:
            key = (lead["state"], lead["market"], lead["segment"], lead["band"])
            vals = buckets[key]
            ds = sorted({v["date"] for v in vals})
            if len(ds) < 4:
                print(f"  {key}  only {len(ds)} dates -- cannot split")
                continue
            cut = ds[len(ds) // 2]
            late = [v for v in vals if v["date"] >= cut]
            if len(late) < args.min_n:
                print(f"  {key}  holdout n={len(late)} < {args.min_n} -- UNMEASURED")
                continue
            s = score_bucket(late, price_ok.get(key[1], True))
            print(f"  {key}\n      in-sample {lead['edge_pp']:+.2f}pp vs {lead['binding_null']}  ->  "
                  f"holdout (from {cut}) n={len(late)} {s['edge_pp']:+.2f}pp "
                  f"+/-{s['se']:.2f} ({s['sigma']:+.2f} sigma) vs {s['binding_null']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out_rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
