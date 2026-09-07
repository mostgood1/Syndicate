#!/usr/bin/env python3
"""WHERE does the sim beat the market? Per sport, per market, per subset.

`[2026-09-07, user: "we are globally making a call on something that should
enhance SOME games to be bet on ... winners, spreads, game totals, intervals, all
player props. They all must have somewhere that our sim gives us an edge IF TUNED
CORRECTLY"]`

--------------------------------------------------------------------------
WHY A SLATE AVERAGE CANNOT ANSWER THIS
--------------------------------------------------------------------------
Nobody bets the slate. A model can lose to the market on pooled Brier and still
be worth having, if its errors concentrate in games it has no read on while the
subset where it disagrees hardest with the market is where it is right. That is
the whole mechanism of selective +EV: not beating the market everywhere, but
finding a subset where you do.

So this buckets by **|model - market|**, which is the axis a bettor actually
selects on. Beating the market on games you would never bet is worth nothing;
losing to it there costs nothing.

--------------------------------------------------------------------------
WHAT THIS FIXES IN THE EXISTING SCORER
--------------------------------------------------------------------------
`scripts/score_live_gameline_offline.py` already joins this ledger to outcomes
and computes Brier for model AND market side by side -- the right benchmark. It
then throws away most of what it could answer:

  * `if str(rec.get("market")) != "h2h": continue` -- it scores MONEYLINE ONLY.
    Totals and spreads are written to the ledger every build and filtered out at
    scoring time.
  * It reports POOLED Brier, which is the slate-average defect above.

Both are fixed here. Nothing about the ledger changed; the data was always there.

--------------------------------------------------------------------------
A FIELD-NAMING TRAP, DOCUMENTED BECAUSE IT IS SILENT
--------------------------------------------------------------------------
`live_gameline_ledger.py:229` writes `"model_home_win_prob": lg.get("model_prob")`
for EVERY market. On a totals row that field holds P(over); on a spreads row it
holds P(home covers). **One field, three meanings, named for one of them.** A
reader who trusts the name scores totals as moneylines and gets a plausible
number. Everything below keys off `market` and never off the field name.

--------------------------------------------------------------------------
OUTCOME CONVENTIONS, each stated because getting one backwards is invisible
--------------------------------------------------------------------------
  h2h      home won                       (level games dropped -- not an outcome)
  totals   (home + away) > line
  spreads  (home - away) > line

The spread frame is the AWAY-frame line and is NOT negated for the home side:
`live_gameline_join.price_distribution_market` documents it -- "with `L` the
away-frame line, home covers when `margin > L`" -- and getting it backwards
produced measured home probabilities of 0.67-0.74 on underdogs and 19-28 point
phantom edges on 2026-08-08. The same convention is used here deliberately, so a
scoring bug cannot silently disagree with the pricer.

    python scripts/subset_edge_scan.py --sport mlb --days 6
    python scripts/subset_edge_scan.py --sport mlb,ncaaf --days 3 --json out.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

BASE = os.environ.get("SYNDICATE_BASE_URL") or "https://syndicate-an21.onrender.com"
STATSAPI = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={d}"
ESPN_CFB = ("https://site.api.espn.com/apis/site/v2/sports/football/college-football/"
            "scoreboard?limit=400&dates={d}")

_TOTALS = {"totals", "totals_alt", "alternate_totals"}
_SPREADS = {"spreads", "spreads_alt", "alternate_spreads"}


def _admin_token() -> str | None:
    for candidate in (Path(".env"),
                      Path(__file__).resolve().parent.parent / ".env",
                      Path.home() / "OneDrive" / "Coding" / "Syndicate" / ".env"):
        try:
            if not candidate.exists():
                continue
            for line in candidate.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.strip().startswith("ADMIN_TOKEN"):
                    value = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if value:
                        return value
        except OSError:
            continue
    return os.environ.get("ADMIN_TOKEN")


def ledger_records(sport: str, day: str, token: str | None) -> list[dict[str, Any]]:
    rel = f"{sport}_source/data/live_gameline_ledger/live_gameline_ledger_{day}.jsonl"
    url = BASE + "/api/ops/artifacts/export?" + urllib.parse.urlencode({"path": rel})
    req = urllib.request.Request(url, headers={"X-Admin-Token": token or ""})
    payload = json.load(urllib.request.urlopen(req, timeout=150))
    blob = ""
    for _name, value in (payload.get("artifacts") or {}).items():
        if isinstance(value, str):
            blob = value
            break
    out = []
    for line in blob.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def finals_with_scores(sport: str, day: str) -> dict[str, tuple[int, int]]:
    """`game_pk -> (home_score, away_score)`. SCORES, not just the winner.

    The existing scorer returns a bool, which is why it could never have scored
    totals or spreads even if its market filter were removed.
    """
    out: dict[str, tuple[int, int]] = {}
    try:
        if sport == "mlb":
            doc = json.load(urllib.request.urlopen(STATSAPI.format(d=day), timeout=60))
            for block in doc.get("dates", []):
                for game in block.get("games", []):
                    if (game.get("status") or {}).get("abstractGameState") != "Final":
                        continue
                    teams = game.get("teams") or {}
                    home = (teams.get("home") or {}).get("score")
                    away = (teams.get("away") or {}).get("score")
                    if isinstance(home, int) and isinstance(away, int):
                        out[str(game.get("gamePk"))] = (home, away)
        elif sport == "ncaaf":
            url = ESPN_CFB.format(d=day.replace("-", ""))
            doc = json.load(urllib.request.urlopen(
                urllib.request.Request(url, headers={"User-Agent": "syndicate-ops"}), timeout=60))
            for event in doc.get("events") or []:
                status = ((event.get("status") or {}).get("type") or {})
                if status.get("state") != "post":
                    continue
                comp = (event.get("competitions") or [{}])[0]
                scores: dict[str, int] = {}
                for team in comp.get("competitors") or []:
                    try:
                        scores[str(team.get("homeAway"))] = int(team.get("score"))
                    except (TypeError, ValueError):
                        pass
                if "home" in scores and "away" in scores:
                    out[str(event.get("id"))] = (scores["home"], scores["away"])
    except Exception as exc:  # noqa: BLE001
        print(f"  [finals] {sport} {day}: {type(exc).__name__} -- outcomes unavailable", flush=True)
    return out


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None


def outcome_for(market: str, line: Any, home: int, away: int) -> bool | None:
    """True when the row's POSITIVE side happened. None when unscoreable."""
    key = str(market or "").strip().lower()
    if key in {"h2h", "h2h_3_way"}:
        return None if home == away else home > away      # a level game is not an outcome
    value = _f(line)
    if value is None:
        return None
    if key in _TOTALS:
        total = home + away
        return None if abs(total - value) < 1e-9 else total > value   # push is not an outcome
    if key in _SPREADS:
        margin = home - away
        return None if abs(margin - value) < 1e-9 else margin > value
    return None


def scan(records, finals, *, max_age: float | None) -> dict[str, list[tuple[float, float, bool]]]:
    """market -> [(model_p, market_p, hit)]. Keyed off `market`, never the field name.

    `max_age` IS NOT OPTIONAL IN PRACTICE and omitting it manufactures an edge.
    Measured 2026-09-05 on MLB: quote age p50 281s, p90 518s, and only 653 of
    2,721 rows fresher than 120s. The model reads live state at time T while the
    recorded line is from T-281s on average -- in baseball that can be a whole
    inning. Scoring a score-aware model against a line that has not seen the same
    innings gives the model an information advantage NO REAL BETTOR HAS, and it
    shows up as a spectacular fake edge.

    ABSENT AGE IS EXCLUDED, never admitted: a row with no age cannot be shown to
    be fresh, and unknown must not take the permissive branch.
    """
    by_market: dict[str, list[tuple[float, float, bool]]] = defaultdict(list)
    for rec in records:
        if max_age is not None:
            age = _f(rec.get("quote_age_seconds"))
            if age is None or age > max_age:
                continue
        key = str(rec.get("game_pk") or "").strip()
        if key not in finals:
            continue
        market = str(rec.get("market") or "").strip().lower()
        model = _f(rec.get("model_home_win_prob"))     # see the naming trap above
        book = _f(rec.get("market_fair_prob"))
        if model is None or book is None:
            continue
        home, away = finals[key]
        hit = outcome_for(market, rec.get("line"), home, away)
        if hit is None:
            continue
        by_market[market].append((model, book, hit))
    return by_market


# Below this, the market leg carries no information and NO comparison against it
# is valid. Measured 2026-09-05 on MLB: h2h market probability has sd 0.251,
# spreads 0.132, totals **0.058**.
_MIN_MARKET_SD = 0.10


def report(market: str, rows: list[tuple[float, float, bool]]) -> dict[str, Any]:
    # A DEGENERATE MARKET LEG IS REFUSED, NOT SCORED. This guard exists because
    # the first version of this script reported a spectacular fake edge:
    # spreads top-decile model Brier 0.087 against a market 0.244, model better
    # on 108 of 121.
    #
    # WHY IT WAS FAKE. Spreads and totals are priced about -110/-110, so
    # de-vigging the PRICE returns ~0.50 every time -- the market expresses its
    # view through the LINE, not the price. So the comparison was not
    # model-vs-market at all; it was an informative estimator against a constant
    # 0.5, which ANY informative estimator beats. Selecting the top decile by
    # `|model - market|` then selects on the MODEL'S OWN CONFIDENCE, and Brier
    # rewards confident-and-correct, so the bucket fills with near-decided games.
    # Split by game phase without that selection, the entire effect collapses to
    # spreads -0.02 and totals -0.006.
    #
    # h2h is the only market whose recorded market probability varies (sd 0.251),
    # and it is the one market where the model LOSES -- worse in the top bucket
    # (+0.042 Brier) than overall (+0.008).
    #
    # THE REFUSAL IS CATEGORICAL, NOT EMPIRICAL, and that distinction is the fix.
    # A pure sd threshold at 0.10 caught totals (sd 0.079) and let SPREADS
    # through (sd 0.132) -- yet spreads' apparent edge is the same artifact, and
    # collapses to -0.02 once you split by game phase instead of selecting on
    # `|model - market|`. An empirical cutoff refuses for a symptom; a market
    # whose noise happens to exceed the threshold slips past for no good reason.
    # So line-priced markets are refused BY KIND, with the sd check kept as a
    # second net for anything else that degenerates.
    market_sd = statistics.pstdev([q for _p, q, _h in rows]) if len(rows) > 1 else 0.0
    key = str(market or "").strip().lower()
    if key in _TOTALS or key in _SPREADS or market_sd < _MIN_MARKET_SD:
        print("")
        print(f"  --- {market}  (n={len(rows)}) ---")
        # THE REASON PRINTED MUST BE THE REASON THAT FIRED. Printing the sd
        # clause for a spreads row whose sd is 0.1374 would state something
        # false in the course of refusing something correctly -- and a wrong
        # explanation attached to a right answer is worse than no explanation,
        # because it survives review.
        if key in _TOTALS or key in _SPREADS:
            reason = "line_priced_market"
            print(f"  REFUSED ({reason}): this market prices the LINE, not the")
            print(f"  probability. Both sides sit near -110, so de-vigging the PRICE")
            print(f"  returns ~0.50 whatever the line is -- the market's information is")
            print(f"  in the line and this ledger records the price. Measured sd here:")
            print(f"  {market_sd:.4f}. Any 'edge' against a ~constant leg is an artifact:")
            print(f"  selecting the top decile by |model - market| then selects on the")
            print(f"  MODEL'S OWN confidence, and Brier rewards confident-and-correct.")
            print(f"  Split by game phase instead, the whole effect collapses to ~-0.02.")
        else:
            reason = "market_leg_degenerate"
            print(f"  REFUSED ({reason}): market leg sd {market_sd:.4f} < {_MIN_MARKET_SD},")
            print(f"  so it carries no information and no comparison against it is valid.")
        return {"market": market, "n": len(rows), "refused": reason,
                "market_sd": round(market_sd, 6)}
    rows = sorted(rows, key=lambda r: -abs(r[0] - r[1]))
    out = {"market": market, "n": len(rows), "buckets": []}
    print(f"\n  --- {market}  (n={len(rows)}) ---")
    print(f"  {'bucket':>9} {'n':>5} {'model':>8} {'market':>8} {'model-mkt':>10} {'model better':>13}")
    for label, frac in (("top 10%", 0.10), ("top 25%", 0.25), ("top 50%", 0.50), ("ALL", 1.0)):
        sub = rows[: max(1, int(len(rows) * frac))]
        if not sub:
            continue
        m = statistics.fmean((p - (1.0 if h else 0.0)) ** 2 for p, _q, h in sub)
        k = statistics.fmean((q - (1.0 if h else 0.0)) ** 2 for _p, q, h in sub)
        wins = sum(1 for p, q, h in sub
                   if (p - (1.0 if h else 0.0)) ** 2 < (q - (1.0 if h else 0.0)) ** 2)
        flag = "  <-- EDGE" if m < k else ""
        print(f"  {label:>9} {len(sub):>5} {m:>8.5f} {k:>8.5f} {m - k:>+10.5f} "
              f"{wins:>8}/{len(sub)}{flag}")
        out["buckets"].append({"bucket": label, "n": len(sub), "model_brier": round(m, 6),
                               "market_brier": round(k, 6), "diff": round(m - k, 6),
                               "model_better": wins})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sport", default="mlb", help="mlb | ncaaf | comma-separated")
    ap.add_argument("--days", type=int, default=4, help="how many days back, ending yesterday")
    ap.add_argument("--max-quote-age", type=float, default=120.0,
                    help="seconds; rows with a staler or absent quote are DROPPED. "
                         "The default is not conservatism -- without it a live "
                         "score-aware model is scored against a line that has not "
                         "seen the same innings, which fabricates an edge. Pass 0 "
                         "to disable and expect the result to be wrong.")
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    token = _admin_token()
    print("SUBSET EDGE SCAN -- where does the sim beat the market?")
    print(f"  source: {BASE}  (PRODUCTION)\n")

    results: dict[str, Any] = {}
    read_any = False
    for sport in [s.strip() for s in args.sport.split(",") if s.strip()]:
        pooled: dict[str, list[tuple[float, float, bool]]] = defaultdict(list)
        for back in range(1, args.days + 1):
            day = (date.today() - timedelta(days=back)).isoformat()
            try:
                records = ledger_records(sport, day, token)
            except Exception as exc:  # noqa: BLE001
                print(f"  [ledger] {sport} {day}: {type(exc).__name__}")
                continue
            if not records:
                continue
            read_any = True
            finals = finals_with_scores(sport, day)
            if not finals:
                continue
            max_age = args.max_quote_age or None
            for market, rows in scan(records, finals, max_age=max_age).items():
                pooled[market].extend(rows)
            print(f"  {sport} {day}: {len(records)} ledger rows, {len(finals)} finals")
        if pooled:
            print(f"\n=== {sport.upper()} ===")
            results[sport] = [report(m, r) for m, r in sorted(pooled.items())]

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2), encoding="utf-8")

    # READING NOTHING IS NOT A RESULT. Same rule as `sim_output_checklist`.
    if not read_any:
        print("\nFAIL -- NO LEDGER ROWS READ. Not 'no edge'; check ADMIN_TOKEN and the dates.")
        return 2
    if not results:
        print("\nNO SCOREABLE ROWS -- ledger read, but nothing joined to a final.")
        return 2
    print("\n  A market whose TOP bucket beats the market is a bettable subset even if")
    print("  ALL does not. A market that loses in the top bucket too has no subset to")
    print("  sell, and the pooled number was not hiding one.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
