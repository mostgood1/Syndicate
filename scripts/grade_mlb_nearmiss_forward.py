"""Grade M1 / M2 -- the two MLB v1 near misses -- forward on the 2027 regular season, exactly as pre-registered.

Lane `mlb-nearmiss-forward` (user 2026-10-14: "register the two MLB near-miss forward tests"). Two SEPARATE hypotheses,
each read once after the 2027 regular season at one-sided p <= 0.0125 (alpha split up front, family-wise 0.025 -- not a
Holm pairing: learnings 2026-10-14, "register a lead alone unless the family is the claim"):

  M1  mlb.arsenal_bad  UNDER batter_hits / batter_total_bases when the batter's arsenal edge vs the box-score starter
      <= -0.017 (v1: discover +0.1%, confirm +2.0% [-0.1, +4.2] on 3,760 lines)
  M2  mlb.opp_k_low    UNDER pitcher strikeouts when the opposing lineup's season SO/PA <= 0.199 (v1: +1.9%, +4.9%
      [-1.3, +11.6] on 217 lines)

FEATURES  `mlb_signal_tests.State` -- the v1 as-of walk, on 2027 data: Statcast `raw_pitches/2027/`, game logs
          `mlb_player_game_log_2027_{hitting,pitching}.csv` (game_type R); each day's lines scored before it is added.
PRICES    the fleet quote logs `mlb_source/tracking/book_quotes/<date>.jsonl[.gz]` (files game day -1..+1), markets
          batter_hits / batter_total_bases / strikeouts; per book the last observation at or before first pitch - 10 min
          (`close_main_lines`, change-log rule, earliest commence = first pitch); fair = median per-book Shin over the US
          books; price = best US under (both as in the v1 evidence -- no Pinnacle).
GAMES     2027 regular season, first pitch after REGISTERED_AT, game day <= FINAL_READ; DOUBLEHEADERS EXCLUDED (a team pair
          plus a date is not a game). Outcome: the box row (hits / TB / K); none -> void; push void.
PRIMARY   each: residual of the UNDER vs the Shin fair, game-clustered bootstrap B 2000 seed 20261014, one-sided p =
          (#boot <= 0 + 1) / (B + 1); SUPPORTED iff p <= 0.0125 at the final read. SECONDARY: flat ROI at the best US under.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from grade_football_fade_leads import close_main_lines  # noqa: E402
from grade_h7_nba_unders import US_BOOKS, roi  # noqa: E402
from mlb_signal_tests import State, load_logs, load_statcast  # noqa: E402
from signal_lift_football import _read_jsonl, decimal  # noqa: E402
from syndicate.features.shared.matchup_signals import norm_player, residual_stats  # noqa: E402

# ---- the registration -------------------------------------------------------------------------------------------------
REGISTERED_AT = datetime(2026, 10, 14, 14, 39, tzinfo=timezone.utc)  # the lane-block registration
SEASON = "2027"
FINAL_READ = "2027-10-03"
CLOSE_LEAD = timedelta(minutes=10)
MARKETS = {"batter_hits": "h", "batter_total_bases": "tb", "strikeouts": "k"}
ARSENAL_BAD = -0.017
OPP_K_LOW = 0.199
ALPHA_EACH = 0.0125
SEED, B = 20261014, 2000
HYPOTHESES = {"M1": "mlb.arsenal_bad", "M2": "mlb.opp_k_low"}
# ----------------------------------------------------------------------------------------------------------------------


def _quotes_for(root: Path, day: str) -> Path | None:
    base = root / "mlb_source" / "tracking" / "book_quotes" / f"{day}.jsonl"
    for path in (base, base.with_name(base.name + ".gz")):
        if path.is_file():
            return path
    return None


def collect(root: Path, through: str, ignore_registration: bool, counts: dict[str, int]) -> list[dict[str, Any]]:
    from syndicate.features.shared.team_aliases import canonical_team

    base = root / "mlb_source" / "source_artifacts" / "data"
    bat, pit, starters, games = load_logs(base / "derived" / f"mlb_player_game_log_{SEASON}_hitting.csv",
                                          base / "derived" / f"mlb_player_game_log_{SEASON}_pitching.csv")
    statcast = load_statcast(base / "statcast" / "raw_pitches" / SEASON)
    state = State({})
    game_of: dict[tuple[str, frozenset], list[str]] = defaultdict(list)
    for r in games["bat"]:
        key = (r["date"], frozenset({canonical_team("mlb", r["team"]), canonical_team("mlb", r["opp"])}))
        if r["game"] not in game_of[key]:
            game_of[key].append(r["game"])
    bat_by_day, pit_by_day = defaultdict(list), defaultdict(list)
    for r in games["bat"]:
        bat_by_day[r["date"]].append(r)
    for r in games["pit"]:
        pit_by_day[r["date"]].append(r)
    records, seen = [], set()
    days = sorted(set(bat_by_day) | set(statcast))
    for d in days:
        if d <= through:
            rows = []
            for k in (-1, 0, 1):
                path = _quotes_for(root, (date.fromisoformat(d) + timedelta(days=k)).isoformat())
                if path is not None:
                    rows += _read_jsonl(path)
            for line in close_main_lines(rows, books=US_BOOKS, lead=CLOSE_LEAD, market_stats=MARKETS):
                ident = (line["event"], line["stat"], line["player"])
                if ident in seen:
                    continue
                if not ignore_registration and line["kickoff"] <= REGISTERED_AT:
                    seen.add(ident)
                    counts["pre_registration"] += 1
                    continue
                # A line belongs to the game on ITS OWN first-pitch date (US Central), never to the day being walked:
                # files d-1..d+1 are read, and a series puts the same two clubs on consecutive days.
                if (line["kickoff"] - timedelta(hours=5)).date().isoformat() != d:
                    continue  # graded on its own day
                teams = frozenset({canonical_team("mlb", line.get("home_team")), canonical_team("mlb", line.get("away_team"))})
                gids = game_of.get((d, teams), [])
                if not gids:
                    counts["no_box_game_for_line"] += 1
                    continue
                seen.add(ident)
                if len(gids) > 1:
                    counts["void_doubleheader"] += 1
                    continue
                game, key = gids[0], norm_player(line["player"])
                if line["stat"] == "k":
                    row = pit.get((game, key))
                    feats = state.pitcher_features(row["pid"], row["opp"]) if row else None
                    hyp = "M2" if feats and feats.get("opp_k") is not None and feats["opp_k"] <= OPP_K_LOW else None
                else:
                    row = bat.get((game, key))
                    opp_sp = starters.get(game, {}).get(row["opp"]) if row else None
                    feats = state.batter_features(row["pid"], opp_sp) if row else None
                    hyp = "M1" if feats and feats.get("arsenal") is not None and feats["arsenal"] <= ARSENAL_BAD else None
                if row is None or line["best_under"] is None:
                    counts["void_no_box_row_or_price"] += 1
                    continue
                value = row[line["stat"]]
                if value == line["point"]:
                    counts["void_push"] += 1
                    continue
                y = 1.0 if value < line["point"] else 0.0
                counts["graded"] += 1
                if hyp:
                    records.append({"h": hyp, "day": d, "game": game, "player": line["player"], "stat": line["stat"],
                                    "point": line["point"], "y": y, "p": round(1.0 - line["p_over"], 5),
                                    "price": line["best_under"], "pnl": (decimal(line["best_under"]) - 1.0) if y else -1.0})
        state.add_day(statcast.get(d), bat_by_day.get(d, []), pit_by_day.get(d, []))
    return records


def report(records: list[dict[str, Any]], through: str, counts: dict[str, int]) -> dict[str, Any]:
    final = through >= FINAL_READ and any(r["day"] >= "2027-09-15" for r in records)
    out: dict[str, Any] = {"through": through, "final_read": final, "counts": dict(counts), "hypotheses": {}}
    for h, name in HYPOTHESES.items():
        rs = [r for r in records if r["h"] == h]
        res = residual_stats(rs, B=B, seed=SEED)
        verdict = ("INTERIM (no verdict before the final read)" if not final
                   else ("SUPPORTED" if res.get("p_one_sided") is not None and res["p_one_sided"] <= ALPHA_EACH
                         else "NOT SUPPORTED"))
        out["hypotheses"][h] = {"signal": name, "residual_under": res,
                                "roi_best_us_under": roi(rs, B=B, seed=SEED) if rs else {"n": 0},
                                "markets": dict(Counter(r["stat"] for r in rs)), "alpha": ALPHA_EACH, "verdict": verdict}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--through", default=None, help="last game day (default: FINAL_READ)")
    ap.add_argument("--season", default=None, help="format check only: grade another season's files (NOT the test)")
    ap.add_argument("--ignore-registration-time", action="store_true", help="format check on pre-registration games")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    global SEASON
    if args.season:
        SEASON = args.season
    through = min(args.through or FINAL_READ, FINAL_READ)
    counts: dict[str, int] = defaultdict(int)
    records = collect(Path(os.path.expanduser(args.data_root)), through, args.ignore_registration_time, counts)
    rep = report(records, through, counts)
    rep["season"], rep["records"] = SEASON, records
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(f"MLB_NEARMISS season={SEASON} through={through} final={rep['final_read']} counts={rep['counts']}", flush=True)
    for h, e in rep["hypotheses"].items():
        s, r = e["residual_under"], e["roi_best_us_under"]
        print(f"  {h} {e['signal']:16s} n={s.get('n')} g={s.get('games')} resid={s.get('residual')} ci={s.get('ci95')} "
              f"p1={s.get('p_one_sided')} | ROI={r.get('roi_pct')} | markets={e['markets']} | {e['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
