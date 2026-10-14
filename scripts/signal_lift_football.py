"""Lift test for the football matchup signals (lane `signal-engine-football`).

Lines: the backfilled closing prop quotes (NFL: kickoff - 10 min, 2023-25; NCAAF: kickoff - 10 min, 2024-25). One MAIN
line per (event, market, player): the point quoted two-sided by the most books (tie -> median Shin p_over nearest 0.5);
fair = median per-book Shin de-vig (production `opportunity_signals.devig`). Signals: the as-of week tables
(`build_nfl_signals.py`, `build_ncaaf_signals.py`) with the registered thresholds (`matchup_signals_football`).

TWO MODES, so thresholds are set without reading an outcome:
  --mode distributions   joins lines to features and prints coverage + feature quantiles on the quoted population.
                         Loads NO outcome (no box value, no pbp stat for the graded week).
  --mode lift            the test: residual = y - p_shin on lines where a signal fires (its markets, its side), vs the
                         eligible-but-not-fired baseline, per window, game-clustered CIs, BH q = 0.10 on CONFIRM.

Outcomes: NFL -- production's own per-play stat extractors (`nfl.player_stats`, official attempts), one pass per season;
a player with no qualifying play in the game is VOID (no snap data to tell a DNP from a zero). NCAAF -- the CFBD box row
for (game, player); none -> void. Pushes void.

    SYNDICATE_DATA_ROOT=~/syndicate-prod/data python3 scripts/signal_lift_football.py --sport nfl --mode distributions \\
        --quotes-dir ~/syndicate-prod/data/backfill/nfl_prop_closes_2023_25 --out nfl_dist.json
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from syndicate.features.shared.matchup_signals import bh_adjust, norm_player, read_signal_table, residual_stats  # noqa: E402
from syndicate.features.shared.matchup_signals_football import (  # noqa: E402
    FOOTBALL_MARKET_STATS,
    FOOTBALL_REGISTRY,
    THRESHOLDS,
    V1_SIGNALS,
    ncaaf_eligible,
    ncaaf_signal_fires,
    nfl_eligible,
    nfl_signal_fires,
    week_key,
)
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

# Pre-registered windows (lane block `signal-engine-football`): (season, first week, last week).
# NCAAF is 2025 only: the 2024 box history is partial (median 14.5 team plays per game in the as-of tables vs 65 in
# 2025), so every 2024 share and pace would rest on a wrong denominator.
WINDOWS = {
    "nfl": {"discover": ((2023, 1, 18), (2024, 1, 18)), "confirm": ((2025, 1, 18),)},
    "ncaaf": {"discover": ((2025, 1, 8),), "confirm": ((2025, 9, 16),)},
}


def window_of(sport: str, season: int, week: int) -> str | None:
    return next((w for w, spans in WINDOWS[sport].items() if any(s == season and lo <= week <= hi for s, lo, hi in spans)),
                None)
_FILE_RE = re.compile(r"(?:quotes_)?(\d{4})_wk(\d+)\.jsonl$")


def quote_files(directory: Path) -> list[tuple[int, int, Path]]:
    out = []
    for path in directory.glob("*.jsonl"):
        m = _FILE_RE.search(path.name)
        if m:
            out.append((int(m.group(1)), int(m.group(2)), path))
    return sorted(out)


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def main_lines(quotes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One record per (event, market, player): the most two-sided-quoted point, median Shin p_over."""
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    meta: dict[str, dict[str, Any]] = {}
    for q in quotes:
        stat = FOOTBALL_MARKET_STATS.get(str(q.get("market") or ""))
        side = str(q.get("selection") or "").strip().lower()
        if stat is None or side not in ("over", "under") or str(q.get("kind") or "prop") != "prop":
            continue
        try:
            point, price = float(q.get("line")), float(q.get("price"))
        except (TypeError, ValueError):
            continue
        event = str(q.get("event_id") or "")
        by_point[(event, stat, str(q.get("player_name") or "").strip(), point)][str(q.get("bookmaker") or "")][side] = price
        meta.setdefault(event, {"home_team": q.get("home_team"), "away_team": q.get("away_team"),
                                "cfbd_game_id": q.get("cfbd_game_id"), "commence_time": q.get("commence_time")})
    candidates: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (event, stat, player, point), books in by_point.items():
        two = [s for s in books.values() if "over" in s and "under" in s]
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for s in two) if f]
        if fairs:
            unders = [decimal(s["under"]) for s in two]
            candidates[(event, stat, player)].append({"event": event, "stat": stat, "player": player, "point": point,
                                                      "books": len(fairs), "p_over": statistics.median(fairs),
                                                      "under_dec_best": max(unders),
                                                      "under_dec_median": statistics.median(unders), **meta[event]})
    out = []
    for cands in candidates.values():
        cands.sort(key=lambda c: (-c["books"], abs(c["p_over"] - 0.5)))
        out.append(cands[0])
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Plain or gzip (the daily compaction gzips closed `book_quotes` shards)."""
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


# ----------------------------------------------------------------------------- NFL joins


def nfl_outcomes(season: int) -> dict[tuple[str, int], dict[str, float]]:
    """(player_id, week) -> stat totals, via production's per-play extractors in ONE pass over the season."""
    from syndicate.features.nfl import player_stats as ps

    out: dict[tuple[str, int], dict[str, float]] = {}
    for play in ps.load_player_plays(season):
        for pid in {play.get("passer_player_id"), play.get("rusher_player_id"), play.get("receiver_player_id")} - {"", None}:
            row = out.setdefault((pid, play["week"]), {s: 0.0 for s in ps.STAT_KEYS})
            for stat, extract in ps._STAT_EXTRACTORS.items():  # the grading extractors themselves, not a copy
                row[stat] += extract(play, pid)
    return out


def nfl_join(season: int, week: int, line: Mapping[str, Any], tables: Mapping[str, Mapping[str, Any]],
             counts: dict[str, int]) -> tuple[str | None, Mapping[str, Any] | None]:
    from syndicate.features.nfl import player_stats as ps
    from syndicate.features.shared.team_aliases import canonical_team

    teams = {canonical_team("nfl", str(line.get("away_team") or "")), canonical_team("nfl", str(line.get("home_team") or ""))}
    teams.discard(None)
    pid, _src = ps.resolve_player_id_for_game(season, week, line["player"], teams, lambda t: canonical_team("nfl", t))
    if pid is None:
        counts["unresolved_player"] += 1
        return None, None
    feats = tables.get(pid)
    if feats is None:
        counts["no_signal_row"] += 1
        return pid, None
    return pid, feats


# ----------------------------------------------------------------------------- NCAAF joins


def ncaaf_box_index(root: Path, seasons: set[int]) -> tuple[dict[str, set[str]], dict[tuple[str, str], dict[str, Any]]]:
    """(game_id -> teams, (game_id, player_key) -> box row). Used for team identity AND, in lift mode, outcomes."""
    from build_ncaaf_signals import load_box

    game_teams: dict[str, set[str]] = defaultdict(set)
    rows: dict[tuple[str, str], dict[str, Any]] = {}
    for r in load_box(root, seasons):
        game_teams[r["game_id"]].add(r["team"])
        if not r["is_team_row"]:
            key = (r["game_id"], r["key"])
            rows[key] = None if key in rows else r  # a name twice in one game is ambiguous -> None
    return game_teams, rows


def ncaaf_join(line: Mapping[str, Any], week_rows: list[Mapping[str, Any]], game_teams: Mapping[str, set[str]],
               counts: dict[str, int]) -> Mapping[str, Any] | None:
    game = str(line.get("cfbd_game_id") or "")
    teams = game_teams.get(game)
    if not teams:
        counts["game_not_in_box"] += 1
        return None
    key = norm_player(line["player"])
    matches = [r for r in week_rows if r.get("kind") == "player" and r.get("player_key") == key and r.get("team") in teams]
    if len(matches) != 1:
        counts["no_signal_row" if not matches else "ambiguous_player"] += 1
        return None
    feats = dict(matches[0])
    pace = {r["team"]: r.get("plays_pg") for r in week_rows if r.get("kind") == "team" and r.get("team") in teams}
    feats["game_pace"] = round(sum(pace.values()), 2) if len(pace) == 2 and None not in pace.values() else None
    return feats


# ----------------------------------------------------------------------------- run


def collect(sport: str, root: Path, quotes_dir: Path, *, with_outcomes: bool) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Joined line records {window, season, week, game, stat, point, p_over, feats, [y_over]}."""
    seasons = {s for spans in WINDOWS[sport].values() for s, _, _ in spans}
    counts: dict[str, int] = defaultdict(int)
    records: list[dict[str, Any]] = []
    outcomes_cache: dict[int, Any] = {}
    game_teams, box_rows = ({}, {}) if sport != "ncaaf" else ncaaf_box_index(root, seasons)
    for season, week, path in quote_files(quotes_dir):
        window = window_of(sport, season, week)
        if window is None:
            continue
        lines = main_lines(_read_jsonl(path))
        counts["main_lines"] += len(lines)
        table = read_signal_table(root, sport, str(season), week_key(week))
        if not table:
            counts["weeks_without_table"] += 1
        if sport == "nfl":
            by_pid = {r["player_id"]: r for r in table}
        for line in lines:
            if sport == "nfl":
                pid, feats = nfl_join(season, week, line, by_pid, counts)
            else:
                pid, feats = None, ncaaf_join(line, table, game_teams, counts)
            if feats is None:
                continue
            rec = {"window": window, "season": season, "week": week, "game": line["event"], "stat": line["stat"],
                   "point": line["point"], "p_over": line["p_over"], "feats": feats}
            if with_outcomes:
                if sport == "nfl":
                    if season not in outcomes_cache:
                        outcomes_cache[season] = nfl_outcomes(season)
                    res = outcomes_cache[season].get((pid, week))
                else:
                    res = box_rows.get((str(line.get("cfbd_game_id") or ""), norm_player(line["player"])))
                if not res:
                    counts["void_no_outcome"] += 1
                    continue
                value = float(res.get(line["stat"]) or 0.0)
                if value == line["point"]:
                    counts["void_push"] += 1
                    continue
                rec["y_over"] = 1.0 if value > line["point"] else 0.0
            counts["joined"] += 1
            records.append(rec)
    return records, dict(counts)


def _q(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = sorted(values)
    pick = lambda q: round(v[min(len(v) - 1, int(q * len(v)))], 4)  # noqa: E731
    return {"n": len(v), "p05": pick(0.05), "p10": pick(0.10), "p15": pick(0.15), "p50": pick(0.50),
            "p85": pick(0.85), "p90": pick(0.90), "p95": pick(0.95), "nonzero": sum(1 for x in v if x)}


def distributions(sport: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Feature quantiles over DISCOVER-window main lines, per the markets each feature's signals use. No outcome."""
    disc = [r for r in records if r["window"] == "discover"]
    def vals(feature: str, stats: tuple[str, ...], extra=lambda f: True) -> list[float]:
        return [r["feats"][feature] for r in disc if r["stat"] in stats and r["feats"].get(feature) is not None
                and extra(r["feats"])]
    if sport == "nfl":
        min_share, min_pass = THRESHOLDS["nfl_min_share"], THRESHOLDS["nfl_min_pass_share"]
        return {
            "tgt_trend (rec lines)": _q(vals("tgt_trend", ("receptions", "receiving_yards"))),
            "carry_trend (rush lines)": _q(vals("carry_trend", ("rushing_attempts", "rushing_yards"))),
            "vac_tgt_fresh (rec lines, own tgt share >= min)": _q(vals(
                "vac_tgt_fresh", ("receptions", "receiving_yards"), lambda f: (f.get("tgt_share_season") or 0) >= min_share)),
            "vac_carry_fresh (rush lines, own carry share >= min)": _q(vals(
                "vac_carry_fresh", ("rushing_attempts", "rushing_yards"), lambda f: (f.get("carry_share_season") or 0) >= min_share)),
            "team_proe (pass lines, starting passer)": _q(vals(
                "team_proe", ("passing_attempts", "passing_yards"), lambda f: (f.get("pass_share_season") or 0) >= min_pass)),
        }
    return {
        "carry_trend (rush lines)": _q(vals("carry_trend", ("rushing_yards",))),
        "rec_trend (rec lines)": _q(vals("rec_trend", ("receptions", "receiving_yards"))),
        "game_pace (yardage lines)": _q(vals("game_pace", ("passing_yards", "rushing_yards", "receiving_yards"))),
    }


def lift(sport: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    fires_fn, eligible_fn = (nfl_signal_fires, nfl_eligible) if sport == "nfl" else (ncaaf_signal_fires, ncaaf_eligible)
    specs = {n: s for n, s in FOOTBALL_REGISTRY.items() if s.sport == sport and n in V1_SIGNALS}
    fired_rows: dict[tuple[str, str], list] = defaultdict(list)
    base_rows: dict[tuple[str, str], list] = defaultdict(list)
    for r in records:
        fires = set(fires_fn(r["feats"]))
        for name, spec in specs.items():
            if r["stat"] not in spec.markets or not eligible_fn(name, r["feats"]):
                continue
            y = r["y_over"] if spec.side == "over" else 1.0 - r["y_over"]
            p = r["p_over"] if spec.side == "over" else 1.0 - r["p_over"]
            (fired_rows if name in fires else base_rows)[(name, r["window"])].append({"y": y, "p": p, "game": r["game"]})
    report: dict[str, Any] = {"signals": {}}
    confirm_p = {}
    for name, spec in specs.items():
        entry: dict[str, Any] = {"side": spec.side, "markets": spec.markets, "rule": spec.rule}
        for window in WINDOWS[sport]:
            fired = residual_stats(fired_rows[(name, window)])
            base = residual_stats(base_rows[(name, window)], B=300)
            entry[window] = {"fired": fired, "baseline": base,
                             "hit_lift_vs_baseline": None if not fired.get("n") or not base.get("n")
                             else round(fired["hit_rate"] - base["hit_rate"], 4)}
        d, c = entry["discover"]["fired"], entry["confirm"]["fired"]
        confirm_p[name] = c.get("p_one_sided")
        entry["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["signals"][name] = entry
    for name, keep in bh_adjust(confirm_p, q=0.10).items():
        report["signals"][name]["bh_q10_confirm"] = keep
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sport", choices=("nfl", "ncaaf"), required=True)
    ap.add_argument("--mode", choices=("distributions", "lift"), required=True)
    ap.add_argument("--data-root", default=os.environ.get("SYNDICATE_DATA_ROOT") or "")
    ap.add_argument("--quotes-dir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if not args.data_root:
        print("REFUSING: no --data-root", flush=True)
        return 2
    root = Path(os.path.expanduser(args.data_root))
    if args.mode == "lift" and any(v == 0.0 for k, v in THRESHOLDS.items() if k.startswith(args.sport)):
        print("REFUSING: thresholds are not registered yet (a 0.0 threshold remains)", flush=True)
        return 3
    records, counts = collect(args.sport, root, Path(os.path.expanduser(args.quotes_dir)), with_outcomes=args.mode == "lift")
    per_window = defaultdict(int)
    for r in records:
        per_window[r["window"]] += 1
    report: dict[str, Any] = {"sport": args.sport, "mode": args.mode, "counts": counts, "joined_by_window": dict(per_window),
                              "games_by_window": {w: len({r["game"] for r in records if r["window"] == w}) for w in per_window}}
    if args.mode == "distributions":
        report["distributions_discover"] = distributions(args.sport, records)
    else:
        report.update(lift(args.sport, records))
        report["thresholds"] = dict(THRESHOLDS)
    Path(args.out).write_text(json.dumps(report, indent=1, default=list), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("counts", "joined_by_window", "games_by_window")}), flush=True)
    if args.mode == "distributions":
        for k, v in report["distributions_discover"].items():
            print(f"  {k}: {v}", flush=True)
    else:
        for name, e in report["signals"].items():
            for w in WINDOWS[args.sport]:
                f, b = e[w]["fired"], e[w]["baseline"]
                print(f"  {name:28s} {w:8s} fired n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} "
                      f"p={f.get('mean_p')} resid={f.get('residual')} ci={f.get('ci95')} | base n={b.get('n')} "
                      f"resid={b.get('residual')} | hit_lift={e[w]['hit_lift_vs_baseline']}", flush=True)
            print(f"  {name:28s} VERDICT {e['verdict']}  BH(q=.10, confirm)={e['bh_q10_confirm']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
