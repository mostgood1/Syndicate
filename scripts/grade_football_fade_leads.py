"""Grade F9 / F10a / F10b -- the football FADE leads -- forward on 2026, exactly as pre-registered.

Lane `signal-engine-football`, lane block "FOOTBALL v2 PRE-REGISTERED" (`817efce7`, 2026-10-14 00:14Z). The v1 test
found the market OVER-reacting to two kinds of news; these bet the UNDER against that reaction:

  F9   nfl.fade_vacated_targets   UNDER receptions / receiving yards when `nfl.vacated_targets` fires
  F10a nfl.fade_carry_spike       UNDER rushing attempts / rushing yards when `nfl.carry_share_up` fires
  F10b ncaaf.fade_carry_spike     UNDER rushing yards when `ncaaf.carry_share_up` fires

GAMES     kickoff after REGISTERED_AT; NFL 2026 REG weeks 6-18, NCAAF 2026 weeks 8-16.
PRICES    the fleet quote logs `<sport>_source/tracking/book_quotes/2026_wk<W>.jsonl` (append-on-change). Per book, the
          last observation at or before kickoff - 10 min: the points present at the book's latest capture, an unchanged
          side carried forward (the H7 grader's change-log rule). Kickoff = the event's EARLIEST commence_time. Books =
          the H7 US-sportsbook list, for the fair AND the price. Main line = most two-sided books (tie -> median Shin
          p_over nearest 0.5); fair = median per-book Shin.
FEATURES  the v1 builders run in memory on 2026 data with weeks < W (NFL OUT = nflverse `injuries_2026.csv`).
OUTCOMES  NFL: production's per-play extractors on `pbp_2026.csv`, no qualifying play -> void. NCAAF: the CFBD box row,
          none -> void. Pushes void.
PRIMARY   residual of the UNDER vs the median Shin fair, game-clustered bootstrap B 2000 seed 20261014, one-sided
          p = (#boot <= 0 + 1) / (B + 1). SECONDARY: flat ROI at the best US price.
BAR       Holm over {F9, F10a, F10b} at family-wise one-sided alpha 0.025, read ONCE when NFL week 18 and NCAAF week 16
          are graded. Any earlier read is INTERIM: numbers, no verdict.

    SYNDICATE_DATA_ROOT=~/syndicate-prod/data python3 scripts/grade_football_fade_leads.py --out fades.json
    # format check on weeks outside the registered window (NOT the test):
    ... --nfl-weeks 2-5 --ncaaf-weeks 2-6 --ignore-registration-time --out dry.json
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from grade_h7_nba_unders import US_BOOKS, holm, roi  # noqa: E402
from signal_lift_football import _read_jsonl, decimal, nfl_outcomes  # noqa: E402
from syndicate.features.shared.matchup_signals import norm_player, residual_stats  # noqa: E402
from syndicate.features.shared.matchup_signals_football import (  # noqa: E402
    FOOTBALL_MARKET_STATS,
    ncaaf_signal_fires,
    nfl_signal_fires,
)
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

# ---- the registration (do not edit after 2026-10-14) ----------------------------------------------------------------
REGISTERED_AT = datetime(2026, 10, 14, 0, 14, tzinfo=timezone.utc)
SEASON = 2026
NFL_WEEKS = (6, 18)
NCAAF_WEEKS = (8, 16)
CLOSE_LEAD = timedelta(minutes=10)
SEED, B = 20261014, 2000
ALPHA = 0.025
HYPOTHESES = {
    "F9": {"sport": "nfl", "signal": "nfl.vacated_targets", "stats": ("receptions", "receiving_yards")},
    "F10a": {"sport": "nfl", "signal": "nfl.carry_share_up", "stats": ("rushing_attempts", "rushing_yards")},
    "F10b": {"sport": "ncaaf", "signal": "ncaaf.carry_share_up", "stats": ("rushing_yards",)},
}
# ----------------------------------------------------------------------------------------------------------------------


def _ts(v: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def close_main_lines(rows: Iterable[Mapping[str, Any]], *, books: frozenset[str] = US_BOOKS,
                     lead: timedelta = CLOSE_LEAD) -> list[dict[str, Any]]:
    """Closing main lines from an append-on-change quote log (see module docstring)."""
    rows = [r for r in rows if str(r.get("kind") or "prop") == "prop"]
    kickoff: dict[str, datetime] = {}
    for r in rows:
        c, e = _ts(r.get("commence_time")), str(r.get("event_id") or "")
        if c is not None and e and (e not in kickoff or c < kickoff[e]):
            kickoff[e] = c
    last: dict[tuple, tuple[datetime, float]] = {}
    book_ts: dict[tuple, datetime] = {}
    meta: dict[str, dict[str, Any]] = {}
    for r in rows:
        stat = FOOTBALL_MARKET_STATS.get(str(r.get("market") or ""))
        side = str(r.get("selection") or "").strip().lower()
        book = str(r.get("bookmaker") or "").lower()
        e, seen = str(r.get("event_id") or ""), _ts(r.get("captured_at") or r.get("snapshot_ts"))
        if stat is None or side not in ("over", "under") or book not in books or e not in kickoff or seen is None:
            continue
        if seen > kickoff[e] - lead:
            continue
        try:
            point, price = float(r.get("line")), float(r.get("price"))
        except (TypeError, ValueError):
            continue
        bk = (e, stat, str(r.get("player_name") or "").strip(), book)
        if bk + (point, side) not in last or seen >= last[bk + (point, side)][0]:
            last[bk + (point, side)] = (seen, price)
        if bk not in book_ts or seen > book_ts[bk]:
            book_ts[bk] = seen
        meta.setdefault(e, {"home_team": r.get("home_team"), "away_team": r.get("away_team"), "kickoff": kickoff[e]})
    current = {k[:5] for k, (ts, _) in last.items() if ts == book_ts[k[:4]]}
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for (e, stat, player, book, point, side), (_, price) in last.items():
        if (e, stat, player, book, point) in current:
            by_point[(e, stat, player, point)][book][side] = price
    candidates: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (e, stat, player, point), bks in by_point.items():
        two = [s for s in bks.values() if "over" in s and "under" in s]
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for s in two) if f]
        if fairs:
            candidates[(e, stat, player)].append({
                "event": e, "stat": stat, "player": player, "point": point, "books": len(fairs),
                "p_over": statistics.median(fairs), "best_under": max((s["under"] for s in two), key=decimal), **meta[e]})
    out = []
    for cands in candidates.values():
        cands.sort(key=lambda c: (-c["books"], abs(c["p_over"] - 0.5)))
        out.append(cands[0])
    return out


def quotes_path(root: Path, sport: str, week: int) -> Path | None:
    """The week's quote log, plain or gzip -- the daily compaction gzips closed shards (retention keeps `book_quotes`
    120 days, past the final read)."""
    base = root / f"{sport}_source" / "tracking" / "book_quotes" / f"{SEASON}_wk{week}.jsonl"
    for path in (base, base.with_name(base.name + ".gz")):
        if path.is_file():
            return path
    return None


def _weeks(spec: str | None, default: tuple[int, int]) -> list[int]:
    if not spec:
        return list(range(default[0], default[1] + 1))
    lo, _, hi = spec.partition("-")
    return list(range(int(lo), int(hi or lo) + 1))


def nfl_records(root: Path, weeks: list[int], ignore_registration: bool, counts: dict[str, int]) -> list[dict[str, Any]]:
    from build_nfl_signals import _read_pbp, build_week, game_counts, load_out
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.shared.team_aliases import canonical_team

    pbp = root / "nfl_source" / "tracking" / "nflverse" / "pbp" / f"pbp_{SEASON}.csv"
    if not pbp.is_file():
        counts["nfl_no_pbp"] += 1
        return []
    players, teams = game_counts(_read_pbp(pbp))
    out = load_out(root / "nfl_source" / "tracking" / "nflverse" / "injuries" / f"injuries_{SEASON}.csv", SEASON)
    outcomes = nfl_outcomes(SEASON)
    graded_weeks = {row["week"] for row in teams.values()}
    records = []
    for week in weeks:
        path = quotes_path(root, "nfl", week)
        if path is None:
            counts["nfl_weeks_without_quotes"] += 1
            continue
        if week not in graded_weeks:
            counts["nfl_weeks_not_in_pbp_yet"] += 1
            continue
        table = {r["player_id"]: r for r in build_week(players, teams, out, week)}
        for line in close_main_lines(_read_jsonl(path)):
            if not ignore_registration and line["kickoff"] <= REGISTERED_AT:
                counts["pre_registration_kickoff"] += 1
                continue
            hyps = [h for h, spec in HYPOTHESES.items() if spec["sport"] == "nfl" and line["stat"] in spec["stats"]]
            if not hyps:
                continue
            gteams = {canonical_team("nfl", str(line.get("away_team") or "")),
                      canonical_team("nfl", str(line.get("home_team") or ""))} - {None}
            pid, _src = ps.resolve_player_id_for_game(SEASON, week, line["player"], gteams, lambda t: canonical_team("nfl", t))
            feats = table.get(pid) if pid else None
            if feats is None:
                counts["nfl_unjoined"] += 1
                continue
            fired = set(nfl_signal_fires(feats))
            for h in hyps:
                if HYPOTHESES[h]["signal"] in fired:
                    records.append(_grade(h, line, outcomes.get((pid, week)), week, counts))
    return [r for r in records if r]


def ncaaf_records(root: Path, weeks: list[int], ignore_registration: bool, counts: dict[str, int]) -> list[dict[str, Any]]:
    from build_ncaaf_signals import build_week, load_box, team_games
    from syndicate.features.shared.team_aliases import canonical_team

    box = load_box(root, {SEASON})
    teams = team_games(box)
    canon = {k: t for t in {r["team"] for r in box} for k in (canonical_team("ncaaf", t),) if k}
    # Pair the two clubs by the box's own game_id: the 2026 snapshot leaves `opponent` empty (measured 2026-10-14).
    game_teams: dict[str, set[str]] = defaultdict(set)
    game_week: dict[str, int] = {}
    for r in box:
        game_teams[r["game_id"]].add(r["team"])
        game_week[r["game_id"]] = r["week"]
    games_by_pair: dict[frozenset, list[tuple[int, str]]] = defaultdict(list)
    for game, members in game_teams.items():
        if len(members) == 2:
            games_by_pair[frozenset(members)].append((game_week[game], game))
    box_rows = {(r["game_id"], r["key"]): r for r in box if not r["is_team_row"]}
    graded_weeks = {r["week"] for r in box}
    records = []
    for week in weeks:
        path = quotes_path(root, "ncaaf", week)
        if path is None:
            counts["ncaaf_weeks_without_quotes"] += 1
            continue
        if week not in graded_weeks:
            counts["ncaaf_weeks_not_in_box_yet"] += 1
            continue
        table = [r for r in build_week(box, teams, SEASON, week) if r.get("kind") == "player"]
        for line in close_main_lines(_read_jsonl(path)):
            if not ignore_registration and line["kickoff"] <= REGISTERED_AT:
                counts["pre_registration_kickoff"] += 1
                continue
            if line["stat"] not in HYPOTHESES["F10b"]["stats"]:
                continue
            gteams = {canon.get(canonical_team("ncaaf", str(line.get(k) or ""))) for k in ("home_team", "away_team")} - {None}
            game = next((g for w, g in sorted(games_by_pair.get(frozenset(gteams), []), key=lambda x: abs(x[0] - week))
                         if len(gteams) == 2), None)
            key = norm_player(line["player"])
            match = [r for r in table if r["player_key"] == key and r["team"] in gteams]
            if game is None or len(match) != 1:
                counts["ncaaf_unjoined"] += 1
                continue
            if "ncaaf.carry_share_up" in ncaaf_signal_fires(match[0]):
                records.append(_grade("F10b", line, box_rows.get((game, key)), week, counts))
    return [r for r in records if r]


def _grade(h: str, line: Mapping[str, Any], res: Mapping[str, Any] | None, week: int,
           counts: dict[str, int]) -> dict[str, Any] | None:
    if not res:
        counts[f"{h}_void_no_outcome"] += 1
        return None
    value = float(res.get(line["stat"]) or 0.0)
    if value == line["point"]:
        counts[f"{h}_void_push"] += 1
        return None
    y = 1.0 if value < line["point"] else 0.0
    return {"h": h, "week": week, "game": line["event"], "stat": line["stat"], "player": line["player"],
            "point": line["point"], "y": y, "p": round(1.0 - line["p_over"], 5), "price": line["best_under"],
            "pnl": (decimal(line["best_under"]) - 1.0) if y else -1.0}


def report(records: list[dict[str, Any]], *, final: bool, counts: Mapping[str, int]) -> dict[str, Any]:
    out: dict[str, Any] = {"final_read": final, "counts": dict(counts), "hypotheses": {}}
    pvals = {}
    for h in HYPOTHESES:
        rows = [r for r in records if r["h"] == h]
        res = residual_stats(rows, B=B, seed=SEED)
        out["hypotheses"][h] = {**HYPOTHESES[h], "residual_under": res, "roi_best_us_price": roi(rows, B=B, seed=SEED),
                                "weeks": sorted({r["week"] for r in rows})}
        pvals[h] = res.get("p_one_sided")
    if final:
        out["holm"] = holm(pvals, alpha=ALPHA)
    for h in HYPOTHESES:
        out["hypotheses"][h]["verdict"] = ("INTERIM (no verdict before the final read)" if not final
                                           else ("SUPPORTED" if out["holm"][h] else "NOT SUPPORTED"))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--nfl-weeks", default=None, help="override, e.g. 2-5 (a format check, NOT the registered test)")
    ap.add_argument("--ncaaf-weeks", default=None)
    ap.add_argument("--ignore-registration-time", action="store_true", help="format check on pre-registration games")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    nfl_w, ncaaf_w = _weeks(args.nfl_weeks, NFL_WEEKS), _weeks(args.ncaaf_weeks, NCAAF_WEEKS)
    registered = not (args.nfl_weeks or args.ncaaf_weeks or args.ignore_registration_time)
    counts: dict[str, int] = defaultdict(int)
    records = nfl_records(root, nfl_w, args.ignore_registration_time, counts) + \
        ncaaf_records(root, ncaaf_w, args.ignore_registration_time, counts)
    graded = {"nfl": {r["week"] for r in records if r["h"] != "F10b"}, "ncaaf": {r["week"] for r in records if r["h"] == "F10b"}}
    final = registered and NFL_WEEKS[1] in graded["nfl"] and NCAAF_WEEKS[1] in graded["ncaaf"] \
        and not counts.get("nfl_weeks_not_in_pbp_yet") and not counts.get("ncaaf_weeks_not_in_box_yet")
    rep = report(records, final=final, counts=counts)
    rep["registered_window"] = registered
    rep["records"] = records
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
    print(f"FADES registered_window={registered} final={final} counts={dict(counts)}", flush=True)
    for h, e in rep["hypotheses"].items():
        s, r = e["residual_under"], e["roi_best_us_price"]
        print(f"  {h:5s} {e['signal']:22s} n={s.get('n')} g={s.get('games')} hit={s.get('hit_rate')} p={s.get('mean_p')} "
              f"resid={s.get('residual')} ci={s.get('ci95')} p1={s.get('p_one_sided')} | ROI={r.get('roi_pct')} "
              f"{r.get('ci95')} | {e['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
