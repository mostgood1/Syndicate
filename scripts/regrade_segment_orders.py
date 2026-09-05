"""Re-grade settled orders that were graded against the WHOLE-GAME actual.

WHY THIS EXISTS. `segment` reaches the order row (`execution_ledger.py:134/268/1117`)
and no MLB resolver ever read it: `bet_status_mlb.resolve()` takes
`liveData.linescore.teams.<side>.runs` -- a whole-game total -- for every order,
whatever its segment. So a `first5` / `first3` / `first1` bet was graded against
the full nine innings. Measured on production 2026-09-05: 209 segment orders
exist and 173 of them carry an `outcome`.

READ-ONLY. This script computes what those orders SHOULD have graded and what
that does to book-level ROI. **It never writes the ledger.** Mutating settled
history is a separate decision with its own blast radius, and the ledger is
written concurrently by two services -- `execution_ledger._persist` carries a
`last_blind_write` marker precisely because concurrent edits have been lost.

THE ARITHMETIC IS NOT REIMPLEMENTED. The whole point of a re-grade is that it
must be the SAME grader with a DIFFERENT actual; a second implementation of the
same rules would be measuring my reading of `game_line_bet.py` rather than
measuring the defect. So this calls `game_line_view`, `resolve_bet_status` and
`grade_order` directly and substitutes only the two scores.

THE CONTROL IS LOAD-BEARING AND RUNS FIRST. Before any re-grade is believed,
the same code path is run with the FULL-GAME score and must reproduce the
outcome already stored in the ledger. A re-grade that cannot reproduce the
as-settled verdict is measuring my harness, not the defect. Any order whose
control disagrees is reported and EXCLUDED rather than silently re-graded.

SUBSTRATES, NAMED (`model_engine_standard.md` 3b):
  render            -- the order rows, via /api/portfolio/{live,paper}
  upstream:statsapi -- the per-inning actual, via the schedule `hydrate=linescore`
                       endpoint, which is the same origin `build_mlb_actuals.py`
                       and `scripts/regrade_mlb_game_markets.py:99` already fetch.
This is NOT a claim that production could have graded these correctly. It could
not: `feed_live` on production covers 11 dates, 2026-06-14..06-25, and none of
the affected dates. That gap is a separate, reported finding.
"""
from __future__ import annotations

import argparse
import collections
import gzip
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

STATSAPI_SCHEDULE = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}&hydrate=linescore"

# The segment vocabulary the ledger actually uses, mapped to a number of
# COMPLETED innings. `market_segments.py:51` is the authority on the names.
SEGMENT_INNINGS = {"first1": 1, "first3": 3, "first5": 5}

# Markets resolved from the combined scoreboard rather than one side's score.
# Mirrors `bet_status_mlb._GAME_TOTAL_MARKETS`.
GAME_TOTAL_MARKETS = frozenset({"totals", "totals_alt"})


def _fetch(url: str, headers: Mapping[str, str] | None = None) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            # `render-egress-transport` measured every one of this repo's 122
            # urllib call sites pulling UNCOMPRESSED because urllib does not
            # send this by default. ESPN/StatsAPI both serve gzip.
            "Accept-Encoding": "gzip",
            "User-Agent": "syndicate-segment-regrade/1.0",
            **(headers or {}),
        },
    )
    with urllib.request.urlopen(req, timeout=180) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
    return raw


def load_linescores(dates: list[str], cache: Path | None = None) -> dict[str, dict[str, Any]]:
    """gamePk -> {officialDate, home, away, gameDate, innings:[{num,home,away}]}."""
    if cache is not None and cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    games: dict[str, dict[str, Any]] = {}
    for date in dates:
        payload = json.loads(_fetch(STATSAPI_SCHEDULE.format(date=date)))
        for day in payload.get("dates") or []:
            for game in day.get("games") or []:
                linescore = game.get("linescore") or {}
                games[str(game["gamePk"])] = {
                    "gamePk": game["gamePk"],
                    "officialDate": game.get("officialDate"),
                    "gameDate": game.get("gameDate"),
                    "status": (game.get("status") or {}).get("detailedState"),
                    "home": ((game.get("teams") or {}).get("home") or {}).get("team", {}).get("name"),
                    "away": ((game.get("teams") or {}).get("away") or {}).get("team", {}).get("name"),
                    "linescore_teams": linescore.get("teams"),
                    "innings": [
                        {
                            "num": inning.get("num"),
                            "home": (inning.get("home") or {}).get("runs"),
                            "away": (inning.get("away") or {}).get("runs"),
                        }
                        for inning in (linescore.get("innings") or [])
                    ],
                }
    if cache is not None:
        cache.write_text(json.dumps(games, indent=0), encoding="utf-8")
    return games


def segment_score(game: Mapping[str, Any], innings: int | None) -> tuple[float, float] | None:
    """(home, away) runs after `innings` completed innings, or the final score.

    RETURNS None RATHER THAN A PARTIAL SUM when the game did not reach that
    inning or a half-inning is missing. A `first5` bet on a game that ended in
    the 4th has no first-5 actual, and inventing one by summing what exists is
    the same class of error this whole exercise is correcting.
    """
    if innings is None:
        teams = game.get("linescore_teams") or {}
        home = (teams.get("home") or {}).get("runs")
        away = (teams.get("away") or {}).get("runs")
        if home is None or away is None:
            return None
        return float(home), float(away)
    rows = [r for r in (game.get("innings") or []) if isinstance(r.get("num"), int) and r["num"] <= innings]
    if len(rows) < innings:
        return None
    home_total = 0.0
    away_total = 0.0
    for row in rows:
        # A None half-inning is NOT zero. The home half of the 9th is routinely
        # absent when the home side is already ahead -- irrelevant for segments
        # 1/3/5, but a missing half anywhere else means we cannot see the score.
        if row.get("home") is None or row.get("away") is None:
            return None
        home_total += float(row["home"])
        away_total += float(row["away"])
    return home_total, away_total


def status_for(order: Mapping[str, Any], home: float, away: float) -> dict[str, Any]:
    """The status dict `grade_order` consumes, for one order at one score.

    Reproduces `bet_status_mlb.resolve()`'s market dispatch, and nothing else --
    the game is known FINAL by construction here (every affected game is
    `Final` in the schedule payload), so the feed/state machinery that resolver
    carries is not in play.
    """
    from syndicate.features.shared.bet_status import resolve_bet_status
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market

    market = str(order.get("market") or "").strip().lower()
    if market in GAME_TOTAL_MARKETS:
        return resolve_bet_status(
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            current_value=home + away,
            is_final=True,
            started=True,
        )
    if is_game_line_market("mlb", market):
        view = game_line_view(
            sport="mlb",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=order.get("home_team"),
            away_team=order.get("away_team"),
            home_score=home,
            away_score=away,
            expect_home=order.get("home_team"),
            expect_away=order.get("away_team"),
            # Baseball does not draw: a level regulation score is a push on a
            # two-way moneyline. `bet_status_mlb.resolve` passes this the same way.
            draw_possible=False,
        )
        if view.get("unavailable_reason"):
            return {"decided": False, "unavailable_reason": view["unavailable_reason"]}
        return resolve_bet_status(
            market=market,
            side=view["side"],
            line=view["line"],
            current_value=view["current_value"],
            is_final=True,
            started=True,
        )
    return {"decided": False, "unavailable_reason": "unmapped_market"}


def grade_at(order: Mapping[str, Any], home: float, away: float) -> dict[str, Any]:
    from syndicate.features.shared.paper_settlement import grade_order

    return grade_order(order, status_for(order, home, away))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, help="manifest_*.json written by the ledger read")
    parser.add_argument("--linescore-cache", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    orders = manifest["orders"]
    dates = sorted({str(o["selected_date"]) for o in orders})
    games = load_linescores(dates, Path(args.linescore_cache) if args.linescore_cache else None)

    index: dict[tuple[str, str, str], list[dict[str, Any]]] = collections.defaultdict(list)
    for game in games.values():
        index[(str(game["officialDate"]), str(game["home"]), str(game["away"]))].append(game)

    results = []
    for order in orders:
        key = (str(order["selected_date"]), str(order["home_team"]), str(order["away_team"]))
        candidates = index.get(key) or []
        row = {
            "idempotency_key": order["idempotency_key"],
            "selected_date": order["selected_date"],
            "segment": order["segment"],
            "market": order["market"],
            "side": order["side"],
            "line": order["line"],
            "book": order["book"],
            "venue": order["venue"],
            "mode": order["mode"],
            "home_team": order["home_team"],
            "away_team": order["away_team"],
            "stored_outcome": order["outcome"],
            "stored_pnl_dollars": order["pnl_dollars"],
            "stored_settled_value": order["settled_value"],
            "fill_stake_dollars": order["fill_stake_dollars"],
        }
        if not candidates:
            row["verdict"] = "UNGRADABLE"
            row["reason"] = "no_statsapi_game_matched"
            results.append(row)
            continue
        if len(candidates) > 1:
            # Doubleheader. Pick by scheduled start; the order carries the
            # book's own commence_time in UTC.
            want = str(order.get("commence_time") or "")
            candidates = sorted(candidates, key=lambda g: abs_delta(g.get("gameDate"), want))
        game = candidates[0]
        row["gamePk"] = game["gamePk"]

        # THE CONTROL, AND IT RUNS FIRST. Same code path, FULL-game score: it
        # must reproduce what the ledger already stored.
        full = segment_score(game, None)
        if full is None:
            row["verdict"] = "UNGRADABLE"
            row["reason"] = "no_full_game_score"
            results.append(row)
            continue
        control = grade_at(order, full[0], full[1])
        row["control_outcome"] = control.get("outcome")
        row["control_pnl_dollars"] = control.get("pnl_dollars")
        row["control_reproduces_ledger"] = bool(
            control.get("graded") and control.get("outcome") == order["outcome"]
        )
        if not row["control_reproduces_ledger"]:
            row["verdict"] = "EXCLUDED_CONTROL_FAILED"
            row["reason"] = control.get("reason") or "control_outcome_disagrees_with_ledger"
            results.append(row)
            continue

        innings = SEGMENT_INNINGS.get(str(order["segment"]))
        if innings is None:
            row["verdict"] = "UNGRADABLE"
            row["reason"] = f"unknown_segment_{order['segment']}"
            results.append(row)
            continue
        seg = segment_score(game, innings)
        if seg is None:
            row["verdict"] = "UNGRADABLE"
            row["reason"] = f"no_actual_after_{innings}_innings"
            results.append(row)
            continue
        row["segment_home_runs"], row["segment_away_runs"] = seg
        row["full_home_runs"], row["full_away_runs"] = full
        corrected = grade_at(order, seg[0], seg[1])
        if not corrected.get("graded"):
            row["verdict"] = "UNGRADABLE"
            row["reason"] = corrected.get("reason") or "grader_refused_on_segment_actual"
            results.append(row)
            continue
        row["verdict"] = "REGRADED"
        row["corrected_outcome"] = corrected["outcome"]
        row["corrected_pnl_dollars"] = corrected["pnl_dollars"]
        row["corrected_settled_value"] = corrected.get("settled_value")
        row["outcome_changed"] = corrected["outcome"] != order["outcome"]
        row["pnl_delta_dollars"] = round(
            float(corrected["pnl_dollars"]) - float(order["pnl_dollars"] or 0.0), 4
        )
        results.append(row)

    Path(args.out).write_text(json.dumps({"rows": results}, indent=1), encoding="utf-8")
    verdicts = collections.Counter(r["verdict"] for r in results)
    print("verdicts:", dict(verdicts))
    controls = sum(1 for r in results if r.get("control_reproduces_ledger"))
    print(f"control reproduced the ledger outcome on {controls}/{len(results)} orders")
    changed = sum(1 for r in results if r.get("outcome_changed"))
    print(f"outcome CHANGED on {changed} of the {verdicts['REGRADED']} re-graded")
    return 0


def abs_delta(a: Any, b: Any) -> float:
    """Seconds between two ISO stamps, or a large number when unparseable."""
    from datetime import datetime

    def parse(value: Any):
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    left, right = parse(a), parse(b)
    if left is None or right is None:
        return 1e9
    return abs((left - right).total_seconds())


if __name__ == "__main__":
    raise SystemExit(main())
