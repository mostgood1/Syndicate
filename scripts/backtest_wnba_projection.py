"""Backtest: does the WNBA game model predict anything? (`#428`, first of six)

`#425` gap 1 made every projection declare whether its model has ever been
evaluated. Six producers answer `unmeasured`. This measures the first one.

WHAT IT MEASURES. `game_cards_<date>.csv` carries `pred_margin` and
`pred_total` per game. Both are compared against the real final score, and both
are reported **against a constant baseline** -- the sample's own mean margin and
mean total. The baseline is not decoration: NFL's totals model sits at r=0.269
and beats the historical mean by only 0.22 MAE, so a bare correlation would have
read as skill. A model that cannot beat "always predict the average" has no
value however well it correlates. The market line is reported alongside where
present, as the standard everyone is actually betting against.

WHERE THE DATA COMES FROM, and why two sources.
  * PROJECTIONS -- production, via `/api/ops/artifacts/stream?path=`. NOT the
    local checkout: the local `game_cards_*.csv` are 7-column stubs with no
    projection columns at all, while production's carry 19 including the two
    measured here. `#428` was filed "blocked on data" off that local read and
    was wrong by roughly 20x.
  * OUTCOMES -- ESPN's public WNBA scoreboard. The projection artifact does not
    carry finals, so the outcome has to come from somewhere else, and ESPN is
    the same independent feed the NFL work already relies on.

DO NOT ADD A BROWSER USER-AGENT to the ESPN call. It returns HTTP 403 to
browser-spoof UAs from Render's outbound IP (confirmed 2026-08-05, and again
from a dev machine 2026-08-13 where PowerShell's default UA got 403 on a URL
urllib fetched fine). `urllib.request.Request(url)` with no headers is
load-bearing, not an oversight.

HONESTY RULES BUILT IN, because this file exists to produce a number someone
will later trust:
  * the INTERSECTION is reported, never the union -- dates with a projection but
    no final (or vice versa) are excluded AND counted, per CLAUDE.md's standing
    join trap;
  * `n` travels with every statistic, and the script REFUSES to emit a
    MEASURED_SKILL block below --min-games;
  * the margin sign convention is checked against real finals before any
    correlation is trusted, because an inverted sign turns skill into
    anti-skill and reads plausibly either way;
  * "no skill" is a RESULT and is printed as such. `#367` concluded exactly that
    for NFL (corr -0.047) and it is why that projection is suppressed today.

Usage:
  py -3 scripts/backtest_wnba_projection.py --limit 20      # quick pass
  py -3 scripts/backtest_wnba_projection.py                 # every stored date
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE = "https://syndicate-an21.onrender.com"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard"


def _admin_token() -> str:
    for line in (REPO_ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("ADMIN_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("ADMIN_TOKEN not found in .env")


def _get(url: str, headers: dict | None = None, timeout: int = 90) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


# --------------------------------------------------------------------------
# projections (production)
# --------------------------------------------------------------------------


def available_dates() -> list[str]:
    payload = json.loads(_get(f"{BASE}/wnba/api/archive").decode("utf-8"))
    dates = payload.get("available_dates")
    return [str(d) for d in dates] if isinstance(dates, list) else []


def projections_for(date: str, token: str, cache: Path) -> list[dict]:
    """One date's `pred_margin`/`pred_total` per game, from PRODUCTION."""
    cached = cache / f"game_cards_{date}.csv"
    if cached.is_file():
        text = cached.read_text(encoding="utf-8", errors="replace")
    else:
        path = f"wnba_source/data/processed/game_cards_{date}.csv"
        url = f"{BASE}/api/ops/artifacts/stream?path={urllib.parse.quote(path)}"
        try:
            text = _get(url, headers={"X-Admin-Token": token}).decode("utf-8", errors="replace")
        except Exception:
            return []
        cache.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")

    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        home = str(row.get("home_tri") or "").strip().upper()
        away = str(row.get("away_tri") or "").strip().upper()
        if not (home and away):
            continue

        def num(key):
            value = str(row.get(key) or "").strip()
            try:
                return float(value) if value else None
            except ValueError:
                return None

        rows.append({
            "date": date, "home": home, "away": away,
            "pred_margin": num("pred_margin"), "pred_total": num("pred_total"),
            "market_spread": num("home_spread"), "market_total": num("total"),
        })
    return rows


# --------------------------------------------------------------------------
# outcomes (ESPN)
# --------------------------------------------------------------------------


def finals_for(date: str, cache: Path) -> dict[tuple[str, str], tuple[int, int]]:
    cached = cache / f"espn_{date}.json"
    if cached.is_file():
        payload = json.loads(cached.read_text(encoding="utf-8"))
    else:
        compact = date.replace("-", "")
        try:
            payload = json.loads(_get(f"{ESPN}?dates={compact}", timeout=20).decode("utf-8"))
        except Exception:
            return {}
        cache.mkdir(parents=True, exist_ok=True)
        cached.write_text(json.dumps(payload), encoding="utf-8")

    out: dict[tuple[str, str], tuple[int, int]] = {}
    for event in payload.get("events") or []:
        competitions = event.get("competitions") or []
        if not competitions:
            continue
        status_type = ((event.get("status") or {}).get("type") or {})
        if not status_type.get("completed"):
            continue          # only a FINAL counts as an outcome
        home = away = None
        for competitor in competitions[0].get("competitors") or []:
            tri = ((competitor.get("team") or {}).get("abbreviation") or "").strip().upper()
            try:
                score = int(competitor.get("score"))
            except (TypeError, ValueError):
                continue
            if competitor.get("homeAway") == "home":
                home = (tri, score)
            elif competitor.get("homeAway") == "away":
                away = (tri, score)
        if home and away:
            out[(home[0], away[0])] = (home[1], away[1])
    return out


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def corr(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = fmean(xs), fmean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(num / (dx * dy), 4) if dx and dy else None


def mae(pred: list[float], actual: list[float]) -> float:
    return round(fmean(abs(p - a) for p, a in zip(pred, actual)), 3)


def report(label: str, pred: list[float], actual: list[float],
           market: list[float | None], *, market_is_negated: bool = False) -> dict:
    baseline = fmean(actual)
    out = {
        "n": len(pred),
        "correlation": corr(pred, actual),
        "mae_model": mae(pred, actual),
        "mae_constant_baseline": mae([baseline] * len(actual), actual),
        "baseline_value": round(baseline, 3),
    }
    # The market's home spread is quoted as the favourite's handicap, i.e. the
    # NEGATIVE of the margin it implies. Negate before comparing, or the market
    # looks catastrophically wrong and the model looks good by contrast.
    paired = [((-m if market_is_negated else m), a)
              for m, a in zip(market, actual) if m is not None]
    if len(paired) >= 3:
        out["mae_market_line"] = mae([m for m, _ in paired], [a for _, a in paired])
        out["n_with_market"] = len(paired)
        out["beats_market"] = out["mae_model"] < out["mae_market_line"]
    beats = out["mae_model"] < out["mae_constant_baseline"]
    out["beats_constant_baseline"] = beats
    out["verdict"] = (
        f"beats the constant baseline by "
        f"{round(out['mae_constant_baseline'] - out['mae_model'], 3)} MAE"
        if beats else
        "NO measured skill -- does not beat predicting the historical mean"
    )
    print(f"\n--- {label} ---")
    for key, value in out.items():
        print(f"    {key:26s} {value}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0, help="only the N most recent dates")
    parser.add_argument("--min-games", type=int, default=30,
                        help="refuse to emit a MEASURED_SKILL block below this")
    args = parser.parse_args()

    token = _admin_token()
    cache = Path(os.environ.get("TEMP", "/tmp")) / "wnba_backtest_cache"

    dates = available_dates()
    if args.limit:
        dates = dates[-args.limit:]
    print(f"stored WNBA dates in production: {len(dates)}"
          f"{f' (limited to {args.limit})' if args.limit else ''}")

    rows, no_proj, no_final = [], [], []
    for i, date in enumerate(dates, 1):
        projections = projections_for(date, token, cache)
        if not projections:
            no_proj.append(date)
            continue
        finals = finals_for(date, cache)
        if not finals:
            no_final.append(date)
            continue
        for p in projections:
            score = finals.get((p["home"], p["away"]))
            if score is None:
                continue
            home_score, away_score = score
            rows.append({**p,
                         "actual_margin": home_score - away_score,
                         "actual_total": home_score + away_score})
        if i % 10 == 0:
            print(f"  ...{i}/{len(dates)} dates, {len(rows)} joined games")
        time.sleep(0.15)

    # THE DENOMINATOR THAT MATTERS IS PER-METRIC, NOT THE JOIN.
    #
    # v1 of this script gated on len(rows) -- games joined to a final -- and
    # then reported statistics over whichever of those rows happened to carry a
    # projection. On the first full run that was **361 joined and n=9
    # measured**, and the guard passed on 361 while every number rested on 9.
    # That is the ledger's "a pooled denominator can make a measurement
    # unreadable", reproduced by the script written to avoid it.
    #
    # A row with a final but a NULL pred_margin is not a data point about the
    # model. It is a row the model never scored, and counting it inflates
    # confidence in exactly the direction that produces an authoritative-
    # looking wrong answer.
    n_margin = sum(1 for r in rows if r["pred_margin"] is not None)
    n_total = sum(1 for r in rows if r["pred_total"] is not None)

    print("\nCOVERAGE (the intersection is what every number below rests on)")
    print(f"  dates considered                  : {len(dates)}")
    print(f"  dates with no projection artifact : {len(no_proj)}")
    print(f"  dates with no ESPN final          : {len(no_final)}")
    print(f"  games joined to a final           : {len(rows)}")
    print(f"  ...of those, WITH pred_margin     : {n_margin}"
          f"   ({(100.0 * n_margin / len(rows)) if rows else 0:.1f}%)")
    print(f"  ...of those, WITH pred_total      : {n_total}"
          f"   ({(100.0 * n_total / len(rows)) if rows else 0:.1f}%)")

    measurable = max(n_margin, n_total)
    if measurable < args.min_games:
        print(f"\nREFUSING TO EMIT A SKILL CONSTANT: only {measurable} games carry a "
              f"projection (< --min-games {args.min_games}).")
        print(f"{len(rows)} games joined to a final, but a joined game the model never")
        print("scored says nothing about the model. Gating on the join instead of on")
        print("the projection is how a 9-game sample gets reported as 361.")
        print("\nTHE FINDING IS THE COVERAGE, NOT THE SKILL: production game_cards carry")
        print(f"a projection on {measurable} of {len(rows)} completed games. Fix that")
        print("before measuring skill -- a correlation here would be #377 again.")
        return 1

    margin_rows = [r for r in rows if r["pred_margin"] is not None]
    margin_pred = [r["pred_margin"] for r in margin_rows]
    margin_act = [float(r["actual_margin"]) for r in margin_rows]
    sign_corr = corr(margin_pred, margin_act)
    print(f"\nSIGN CHECK: corr(pred_margin, actual_margin) = {sign_corr}")
    if sign_corr is not None and sign_corr < 0:
        print("  NEGATIVE -- either the model is anti-predictive or the home/away sign")
        print("  convention is inverted. Resolve BEFORE trusting anything below.")

    results = {
        "sport": "wnba",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": len(rows),
        "dates": f"{dates[0]}..{dates[-1]}" if dates else "",
    }
    results["margins"] = report(
        "MARGIN (pred_margin vs actual)", margin_pred, margin_act,
        [r["market_spread"] for r in margin_rows], market_is_negated=True)

    total_rows = [r for r in rows if r["pred_total"] is not None]
    results["totals"] = report(
        "TOTAL (pred_total vs actual)",
        [r["pred_total"] for r in total_rows],
        [float(r["actual_total"]) for r in total_rows],
        [r["market_total"] for r in total_rows])

    print("\n" + "=" * 72)
    print("MEASURED_SKILL block (paste into a constant the producer attaches):")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
