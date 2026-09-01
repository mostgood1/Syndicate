"""Score the retained live game-line ledger against AUTHORITATIVE finals.

WHY THIS EXISTS ALONGSIDE THE WORKER-SIDE SCORER. `live_gameline_score` runs
inside the board build and can only use outcomes the BOARD holds. That index is
lossy in a way its own counters cannot show:

  * MLB's `game_chip_scoreboard` nulls the score on a level "FINAL", because a
    0-0 MLB final is a schedule placeholder. That is CORRECT, and it leaves the
    scorer holding a final it cannot score. Measured 2026-08-29: a grid with 15
    games, 12 of them `final`, and exactly ONE carrying numeric scores.
  * Measured 2026-09-01 across 08-20..08-31: the board's index yielded **143
    games**; MLB StatsAPI yields **157** over the same dates.

So the worker scorer under-counts, and the shortfall is not random -- it lands
on whichever games the upstream nulling touched. This scores the SAME ledger
against StatsAPI, which is the sport's own record.

IT DOES NOT REIMPLEMENT THE ARITHMETIC. `score_ledger_records` is imported and
used verbatim. Two scorers that agree by coincidence rather than by construction
is a drift this repo has already paid for once -- `_SCOREABLE_MARKETS` was
hand-copied and was wrong on first write. The ONLY thing that differs here is
where the outcomes come from.

THE INDEPENDENT UNIT IS GAMES, NOT RECORDS. The ledger holds many snapshots of
each game, so an n of 6,183 is 157 games seen repeatedly. Every pooled figure
here is printed with its game count, and `--bootstrap` resamples GAMES.

DEFAULTS TO THE FRESH CUT. `--max-quote-age 120` is on by default because the
same ledger supports opposite conclusions depending on which prices are
admitted: pooled over every quote age the model reads as parity (-0.00202); on
quotes that were actually alive it LOSES (+0.01096). Passing `-1` reports every
row, including prices nobody could have taken.

`--calibrate` runs the leave-one-date-out harness that any proposed model or
calibration change must pass before promotion. It exists because a 2-parameter
recalibration (home lift + shrink) looked compelling in-sample -- mean model
prob 0.5178 against an actual home win rate of 0.5412 -- and was WORSE out of
sample (0.18388 against 0.18145 raw). In-sample calibration evidence is not
evidence.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date as _date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

DEFAULT_BASE = "https://syndicate-an21.onrender.com"
STATSAPI = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"


def _admin_token() -> str:
    tok = os.environ.get("ADMIN_TOKEN", "").strip()
    if tok:
        return tok
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"')
    return ""


def fetch_ledger(base: str, sport: str, day: str, timeout: int = 300) -> list[dict]:
    """The retained ledger for one date, via the artifact export.

    The ledger IS in `HOT_ARTIFACT_PATTERNS` and IS a real disk write (not a
    keyvalue write), so the export reaches it. An empty `artifacts` map means
    the file does not exist for that date, which is normal outside the retention
    window and is NOT an error.
    """
    pattern = (f"{sport}_source/data/live_gameline_ledger/"
               f"live_gameline_ledger_{day}.jsonl")
    url = f"{base.rstrip('/')}/api/ops/artifacts/export?pattern={urllib.parse.quote(pattern)}"
    req = urllib.request.Request(url)
    tok = _admin_token()
    if tok:
        req.add_header("Authorization", f"Bearer {tok}")
    with urllib.request.urlopen(req, timeout=timeout) as fh:
        doc = json.loads(fh.read().decode("utf-8"))
    body = next(iter((doc.get("artifacts") or {}).values()), "")
    out: list[dict] = []
    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def fetch_finals(day: str, timeout: int = 60) -> dict[str, bool]:
    """`game_pk` -> did the home side win, from MLB StatsAPI.

    Only games whose abstract state is `Final` AND that carry both numeric
    scores are returned. Baseball cannot end level, so a level "final" is
    dropped here for the same reason `build_finals_index` drops it: it is a
    corrupt row, not an outcome.
    """
    with urllib.request.urlopen(STATSAPI.format(d=day), timeout=timeout) as fh:
        doc = json.loads(fh.read().decode("utf-8"))
    out: dict[str, bool] = {}
    for block in doc.get("dates", []):
        for game in block.get("games", []):
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            home = (teams.get("home") or {}).get("score")
            away = (teams.get("away") or {}).get("score")
            if not isinstance(home, int) or not isinstance(away, int) or home == away:
                continue
            out[str(game.get("gamePk"))] = home > away
    return out


def _pairs(records, finals, *, max_age):
    """(model, market, won, game_pk, date) for scoreable, fresh-enough h2h rows."""
    from syndicate.features.shared.live_gameline_score import _finite_prob, _quote_age

    rows = []
    for rec in records:
        if str(rec.get("market") or "").strip().lower() != "h2h":
            continue
        key = str(rec.get("game_pk") or "").strip()
        if key not in finals:
            continue
        model = _finite_prob(rec.get("model_home_win_prob"))
        market = _finite_prob(rec.get("market_fair_prob"))
        if model is None or market is None:
            continue
        if max_age is not None:
            age = _quote_age(rec.get("quote_age_seconds"))
            # ABSENT AGE IS EXCLUDED, never admitted. Unknown must not take the
            # permissive branch -- a row with no age cannot be shown to be fresh.
            if age is None or age > max_age:
                continue
        rows.append((model, market, bool(finals[key]), key, str(rec.get("date") or "")))
    return rows


def _brier(rows, idx):
    return sum((r[idx] - (1.0 if r[2] else 0.0)) ** 2 for r in rows) / len(rows)


def _lg(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sig(z):
    return 1.0 / (1.0 + math.exp(-z))


def _fit(rows, *, iters=400, lr=0.5):
    """logit(p') = a + b*logit(p_model), gradient descent on log loss."""
    a, b = 0.0, 1.0
    for _ in range(iters):
        ga = gb = 0.0
        for model, _market, won, _game, _day in rows:
            z = _lg(model)
            err = _sig(a + b * z) - (1.0 if won else 0.0)
            ga += err
            gb += err * z
        n = len(rows)
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sport", default="mlb")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--days", type=int, default=14,
                    help="Look-back window ending yesterday.")
    ap.add_argument("--start", default="", metavar="YYYY-MM-DD")
    ap.add_argument("--end", default="", metavar="YYYY-MM-DD")
    ap.add_argument("--max-quote-age", type=float, default=120.0,
                    help="Seconds. The FRESH cut -- the only population a model "
                         "claim may be made on. -1 disables it.")
    ap.add_argument("--bootstrap", type=int, default=2000,
                    help="Resamples over GAMES for the CI. 0 to skip.")
    ap.add_argument("--calibrate", action="store_true",
                    help="Leave-one-date-out check of a 2-param recalibration.")
    ap.add_argument("--json-out", default="")
    args = ap.parse_args()

    if args.start and args.end:
        first, last = _date.fromisoformat(args.start), _date.fromisoformat(args.end)
    else:
        last = _date.today() - timedelta(days=1)
        first = last - timedelta(days=max(0, args.days - 1))
    days = [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]
    max_age = None if args.max_quote_age < 0 else args.max_quote_age

    from syndicate.features.shared.live_gameline_score import score_ledger_records

    per_date: dict[str, dict] = {}
    all_rows: list[tuple] = []
    print(f"sport={args.sport} dates={days[0]}..{days[-1]} "
          f"max_quote_age={'off' if max_age is None else f'{max_age:.0f}s'}")
    print()
    print(f"{'date':<12}{'recs':>8}{'games':>7}{'n':>7}{'model':>10}{'market':>10}{'diff':>10}")
    print("-" * 64)
    for day in days:
        try:
            records = fetch_ledger(args.base_url, args.sport, day)
        except Exception as exc:  # noqa: BLE001 -- reported, never silent
            print(f"{day:<12}  FETCH FAILED: {type(exc).__name__}: {exc}")
            continue
        if not records:
            print(f"{day:<12}{0:>8}   -- no retained ledger for this date")
            continue
        finals = fetch_finals(day)
        rows = _pairs(records, finals, max_age=max_age)
        # The shared scorer's full block, so this script and the worker agree by
        # construction on every population they both report.
        per_date[day] = {"records": len(records), "finals": len(finals),
                         "block": score_ledger_records(records, finals)}
        if not rows:
            print(f"{day:<12}{len(records):>8}{len(finals):>7}{0:>7}"
                  f"   -- no scoreable rows at this freshness")
            continue
        all_rows.extend(rows)
        model_b, market_b = _brier(rows, 0), _brier(rows, 1)
        print(f"{day:<12}{len(records):>8}{len({r[3] for r in rows}):>7}{len(rows):>7}"
              f"{model_b:>10.5f}{market_b:>10.5f}{model_b - market_b:>+10.5f}")

    if not all_rows:
        print("\nNO SCOREABLE ROWS IN WINDOW -- nothing to conclude.")
        return 6

    games = {r[3] for r in all_rows}
    model_b, market_b = _brier(all_rows, 0), _brier(all_rows, 1)
    print("-" * 64)
    print(f"{'POOLED':<12}{'':>8}{len(games):>7}{len(all_rows):>7}"
          f"{model_b:>10.5f}{market_b:>10.5f}{model_b - market_b:>+10.5f}")
    print()
    print(f"independent unit: {len(games)} games -- the {len(all_rows)} rows are "
          f"repeated snapshots of them")
    print("NEGATIVE diff = the model beat the market.")

    result = {"dates": days, "games": len(games), "rows": len(all_rows),
              "model_brier": round(model_b, 5), "market_brier": round(market_b, 5),
              "model_minus_market_brier": round(model_b - market_b, 5),
              "max_quote_age_seconds": max_age, "per_date": per_date}

    if args.bootstrap > 0:
        by_game = defaultdict(list)
        for row in all_rows:
            by_game[row[3]].append(row)
        keys = list(by_game)
        rng = random.Random(20260901)
        diffs = []
        for _ in range(args.bootstrap):
            flat = [r for _ in keys for r in by_game[rng.choice(keys)]]
            diffs.append(_brier(flat, 0) - _brier(flat, 1))
        diffs.sort()
        low, high = diffs[int(len(diffs) * 0.025)], diffs[int(len(diffs) * 0.975)]
        worse = 100.0 * sum(1 for d in diffs if d > 0) / len(diffs)
        print(f"\nbootstrap over {len(keys)} games ({args.bootstrap} resamples): "
              f"95% CI [{low:+.5f}, {high:+.5f}], model worse in {worse:.1f}% of resamples")
        result.update(ci_low=round(low, 5), ci_high=round(high, 5), pct_worse=round(worse, 1))

    if args.calibrate:
        print("\nLEAVE-ONE-DATE-OUT RECALIBRATION   logit(p') = a + b*logit(p_model)")
        print("A fix is real only if `recal` beats `raw` HERE. In-sample does not count.")
        print(f"\n{'held-out':<12}{'n':>7}{'raw':>10}{'recal':>10}{'market':>10}")
        print("-" * 49)
        by_day = defaultdict(list)
        for row in all_rows:
            by_day[row[4]].append(row)
        tot_raw = tot_cal = tot_mkt = 0.0
        n_tot = 0
        for day in sorted(by_day):
            test = by_day[day]
            train = [r for other, rs in by_day.items() if other != day for r in rs]
            if len(test) < 20 or not train:
                continue
            a, b = _fit(train)
            raw = _brier(test, 0)
            cal = sum((_sig(a + b * _lg(r[0])) - (1.0 if r[2] else 0.0)) ** 2
                      for r in test) / len(test)
            mkt = _brier(test, 1)
            print(f"{day:<12}{len(test):>7}{raw:>10.5f}{cal:>10.5f}{mkt:>10.5f}")
            tot_raw += raw * len(test)
            tot_cal += cal * len(test)
            tot_mkt += mkt * len(test)
            n_tot += len(test)
        if n_tot:
            print("-" * 49)
            print(f"{'POOLED':<12}{n_tot:>7}{tot_raw / n_tot:>10.5f}"
                  f"{tot_cal / n_tot:>10.5f}{tot_mkt / n_tot:>10.5f}")
            delta = (tot_cal - tot_raw) / n_tot
            print(f"\nrecal vs raw: {delta:+.5f}  -> "
                  f"{'HELPS' if delta < 0 else 'DOES NOT HELP -- do not ship it'}")
            result["loo"] = {"raw": round(tot_raw / n_tot, 5),
                             "recal": round(tot_cal / n_tot, 5),
                             "market": round(tot_mkt / n_tot, 5), "n": n_tot}

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
