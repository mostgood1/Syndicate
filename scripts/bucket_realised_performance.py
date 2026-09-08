"""Which buckets actually MAKE MONEY. Realised outcomes, not paper edge.

WHY THIS EXISTS. `bucket_live_edges.py` reports how loudly the model disagrees
with the market, per bucket. That is not profit. Its headline row --
`spreads q4_late`, n=2471, 20.49pp at edge/se 6.35 -- says the model disagrees
with the book late and confidently. It does not say the model is RIGHT, and
nothing in this repo has ever checked.

WHAT THIS MEASURES INSTEAD. For every ledger row whose game has a final:

    the model prefers a side (whichever way it differs from the market)
    -> did that side WIN?
    -> at what rate, against the rate the MARKET implied for the same side?

The difference is the edge in probability points, which is the thing that turns
into money. Positive means the model's disagreement was right.

THE MARKET IS THE CONTROL, AND THIS IS THE LOAD-BEARING PART. A ledger row's
`market_fair_prob` is the book's de-vigged probability for the same side, and a
book is well calibrated by construction -- so if my outcome resolution is wrong
(a flipped line convention on spreads, an over/under mix-up on totals) the
MARKET will look badly calibrated against it. That is a detectable, unambiguous
signal that the join is wrong rather than the model being good. Each market is
gated on it and REFUSED if the market fails, because a convention error would
otherwise show up as a large fake edge in exactly the bucket that matters most.

    h2h      outcome: the home team won
    totals   outcome: away + home > line          (equal = push, dropped)
    spreads  outcome: home margin beats the line  (convention checked, not assumed)

THE DENOMINATOR IS GAMES, NOT ROWS, AND THE FIRST VERSION OF THIS SCRIPT GOT
THAT WRONG. The ledger writes a row per build per market per line per book set,
so 42,692 MLB rows over ten days resolve to **122 distinct games** -- a median of
334 rows per game, max 817. Treating those as independent produced +14.63pp of
"realised edge" at **+21 sigma**, a result that is impossible on its face: real
betting edges are 1-3pp. The binomial standard error was understated by roughly
sqrt(334) ~ 18x, and a handful of lucky games can carry hundreds of winning rows.

So every row is collapsed to ONE observation per
(game, market, segment, band, line) -- which is also the unit a bettor acts on:
you back a game once, not 334 times. `n_games` is printed beside every rate and
the standard error is computed on it.

A bucket under `--min-n` prints UNMEASURED and no number. The top buckets are
re-checked on a chronological out-of-sample split, because picking the best of
many buckets in-sample finds noise every time.

Run:
    python scripts/bucket_realised_performance.py --sport mlb --days 14
"""

from __future__ import annotations

import argparse
import json
import math
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


def secret(name: str) -> str:
    for line in (REPO / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sport", default="mlb")
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--min-n", type=int, default=30)
    ap.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()

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

    # ---- MARKET CALIBRATION GATE, per market, and for spreads it also picks
    # the line convention rather than assuming one.
    usable_markets = {}
    for market in sorted({str(r.get("market") or "").strip().lower() for r in rows}):
        if not market:
            continue
        cands = [+1.0] if market != "spreads" else [+1.0, -1.0]
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
    if not usable_markets:
        print("\nUNMEASURED: no market passed the calibration gate.")
        return 1

    # ---- bucket the model's realised edge
    buckets = defaultdict(list)
    seen: dict = {}
    skipped = defaultdict(int)
    for r in rows:
        market = str(r.get("market") or "").strip().lower()
        if market not in usable_markets:
            skipped["market_not_usable"] += 1
            continue
        mp = r.get("market_fair_prob")
        model = r.get("model_home_win_prob")
        pk = str(r.get("game_pk") or "")
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
        side_won = won if backs_first else (not won)
        implied = mp if backs_first else (1.0 - mp)
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
        dedup_key = (key, str(r.get("game_pk") or ""))
        stamp = str(r.get("recorded_at") or "")
        prior = seen.get(dedup_key)
        if prior is not None and prior[0] <= stamp:
            skipped["duplicate_row_same_game"] += 1
            continue
        if prior is not None:
            buckets[key].remove(prior[1])
            skipped["duplicate_row_same_game"] += 1
        entry = {"won": side_won, "implied": implied,
                 "date": str(r.get("date") or ""), "game": str(r.get("game_pk") or ""),
                 "edge": abs(model - mp)}
        seen[dedup_key] = (stamp, entry)
        buckets[key].append(entry)

    print(f"\nskipped: {dict(skipped)}")
    print(f"\n{'state':7s} {'market':9s} {'seg':7s} {'band':13s} {'bets':>5s} "
          f"{'games':>6s} {'won%':>7s} {'mkt%':>7s} {'EDGE pp':>8s} {'se':>6s} "
          f"{'sigma':>6s}")
    out_rows = []
    for key in sorted(buckets, key=lambda k: -len(buckets[k])):
        vals = buckets[key]
        n = len(vals)
        if n < args.min_n:
            print(f"{key[0]:7s} {key[1]:9s} {key[2]:7s} {key[3]:13s} {n:5d}   "
                  f"UNMEASURED (n<{args.min_n})")
            continue
        rate = sum(1 for v in vals if v["won"]) / n
        implied = statistics.mean(v["implied"] for v in vals)
        edge = (rate - implied) * 100
        se = math.sqrt(max(rate * (1 - rate), 1e-9) / n) * 100
        ngames = len({v["game"] for v in vals})
        print(f"{key[0]:7s} {key[1]:9s} {key[2]:7s} {key[3]:13s} {n:5d} "
              f"{ngames:6d} {rate*100:7.2f} {implied*100:7.2f} {edge:+8.2f} "
              f"{se:6.2f} {edge/se:+6.2f}")
        out_rows.append({"state": key[0], "market": key[1], "segment": key[2],
                         "band": key[3], "n": n, "won_pct": rate * 100,
                         "market_pct": implied * 100, "edge_pp": edge,
                         "se": se, "sigma": edge / se if se else None,
                         "n_games": ngames,
                         "dates": sorted({v["date"] for v in vals})})

    print("\n  EDGE pp = how often the model's side WON minus how often the market "
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
            rate = sum(1 for v in late if v["won"]) / len(late)
            implied = statistics.mean(v["implied"] for v in late)
            edge = (rate - implied) * 100
            se = math.sqrt(max(rate * (1 - rate), 1e-9) / len(late)) * 100
            print(f"  {key}\n      in-sample {lead['edge_pp']:+.2f}pp  ->  "
                  f"holdout (from {cut}) n={len(late)} {edge:+.2f}pp "
                  f"+/-{se:.2f} ({edge/se:+.2f} sigma)")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out_rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
