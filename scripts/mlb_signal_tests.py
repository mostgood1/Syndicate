"""MLB matchup signals v1 on the bought 2026 regular-season closes (lane `signal-engine-mlb`).

The user's example, tested as registered: "if a batter has a historical edge against a pitcher, has better statcast data
against that pitcher's arsenal, and recency of the batter performance show a positive streak this might indicate that
the prop for hitter to get a hit has a higher likelihood." Registered in the lane block before any close met an outcome.

  lines     `<odds-dir>/<game_pk>.json` (`mlb_props_pull.py`): OddsAPI history at first pitch - 10 min, US books,
            batter_hits / batter_total_bases / pitcher_strikeouts. ONE main line per (game, market, player): most two-sided
            books (tie -> Shin p nearest 0.5); fair = median per-book Shin.
  outcome   hits / total bases from the hitting log, strikeouts from the pitching log (`mlb_player_game_log_2026_*.csv`,
            game_type R), joined on (game_pk, player name); no row -> void; push -> void.
  features  ALL AS-OF -- the season is walked day by day and each day's lines are scored before that day's data is added.
    bvp       (PA, hits) for (opposing starter, batter): every pre-2026 date of the legacy daily index plus 2026 Statcast
              plate appearances before the day, counted exactly as `build_mlb_bvp_index.scan_raw_chunk` counts them.
              bvp_edge = bvp hits/PA - the batter's 2026 hits/PA (needs >= 10 BvP PA and >= 50 season PA).
    arsenal   sum over pitch types of the starter's 2026 usage share x the batter's 2026 wOBA on PAs ending on that type
              (shrunk to the batter's overall with k = 25 PA), minus the batter's overall wOBA (>= 300 pitcher pitches,
              >= 50 batter PA).
    recency   hits/PA over the last 7 games - hits/PA over the earlier 2026 games (>= 20 earlier games).
    k_trend   the starter's K/BF over his last 3 starts - over the earlier starts (>= 5 earlier starts).
    opp_k     the opposing lineup's team 2026 SO/PA (>= 500 PA).
  The opposing starter is the box score's starter (a late scratch is known to the close too).
  windows   discover game day < 2026-06-25 <= confirm (the schedule's median regular-season day)

  --mode distributions   feature quantiles over DISCOVER lines; reads no outcome value
  --mode lift            the registered test
"""
from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
for _p in (REPO_ROOT, REPO_ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from nba_unders_test import roi_stats  # noqa: E402
from syndicate.features.shared.matchup_signals import bh_adjust, norm_player, residual_stats  # noqa: E402
from syndicate.features.shared.opportunity_signals import devig  # noqa: E402

SPLIT_DATE = "2026-06-25"
SHRINK_PA = 25.0
MARKET_STAT = {"batter_hits": "h", "batter_total_bases": "tb", "pitcher_strikeouts": "k"}
BATTER_MARKETS = ("batter_hits", "batter_total_bases")
# Registered thresholds (lane block "MLB v1 PRE-REGISTERED"): the DISCOVER p90 / p10 (stack: p75) of each feature over
# its eligible quoted main lines, from `--mode distributions` (features only). 0.0 = not registered -> refuses to lift.
THRESHOLDS: dict[str, float] = {"bvp_edge": 0.0, "arsenal_hi": 0.0, "arsenal_lo": 0.0, "recency": 0.0,
                                "stack_bvp": 0.0, "stack_arsenal": 0.0, "stack_recency": 0.0,
                                "k_trend": 0.0, "opp_k_hi": 0.0, "opp_k_lo": 0.0}
SIGNALS = {  # name -> (side, markets)
    "mlb.bvp_edge": ("over", BATTER_MARKETS), "mlb.arsenal_edge": ("over", BATTER_MARKETS),
    "mlb.arsenal_bad": ("under", BATTER_MARKETS), "mlb.hot_streak": ("over", BATTER_MARKETS),
    "mlb.matchup_stack": ("over", BATTER_MARKETS), "mlb.k_trend_up": ("over", ("pitcher_strikeouts",)),
    "mlb.opp_k_high": ("over", ("pitcher_strikeouts",)), "mlb.opp_k_low": ("under", ("pitcher_strikeouts",)),
}
_HIT = {"single", "double", "triple", "home_run"}


def decimal(price: float) -> float:
    return 1.0 + price / 100.0 if price > 0 else 1.0 + 100.0 / -price


def _f(v: Any) -> float | None:
    try:
        return None if v in (None, "", "NA", "nan") else float(v)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------- lines


def main_lines(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    data = (snapshot.get("snap") or {}).get("data") or {}
    by_point: dict[tuple, dict[str, dict[str, float]]] = defaultdict(lambda: defaultdict(dict))
    for book in data.get("bookmakers") or []:
        for market in book.get("markets") or []:
            if market.get("key") not in MARKET_STAT:
                continue
            for o in market.get("outcomes") or []:
                side = str(o.get("name") or "").strip().lower()
                point, price = _f(o.get("point")), _f(o.get("price"))
                if side in ("over", "under") and o.get("description") and point is not None and price is not None:
                    by_point[(norm_player(o["description"]), market["key"], point)][book.get("key") or ""][side] = price
    cands: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
    for (player, market, point), books in by_point.items():
        two = [s for s in books.values() if "over" in s and "under" in s]
        fairs = [f[0] for f in (devig([s["over"], s["under"]], method="shin") for s in two) if f]
        if fairs:
            unders = [decimal(s["under"]) for s in two]
            overs = [decimal(s["over"]) for s in two]
            cands[(player, market)].append({"player_key": player, "market": market, "point": point, "books": len(fairs),
                                            "p_over": statistics.median(fairs), "under_dec_best": max(unders),
                                            "under_dec_median": statistics.median(unders), "over_dec_best": max(overs)})
    out = []
    for c in cands.values():
        c.sort(key=lambda x: (-x["books"], abs(x["p_over"] - 0.5)))
        out.append(c[0])
    return out


# ----------------------------------------------------------------------------- inputs


def load_logs(hitting: Path, pitching: Path) -> tuple[dict, dict, dict, dict]:
    """(batter rows by (game_pk, key), pitcher rows by (game_pk, key), starters by game_pk -> {team: pid}, all rows)."""
    bat, pit, starters, games = {}, {}, defaultdict(dict), defaultdict(list)
    with hitting.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("game_type") or "").upper() != "R":
                continue
            row = {"game": str(r["game_pk"]), "date": r["date"][:10], "pid": int(r["player_id"]), "team": r["team"],
                   "opp": r["opponent"], "pa": _f(r.get("pa")) or 0.0, "h": _f(r.get("h")) or 0.0,
                   "tb": _f(r.get("tb")) or 0.0, "so": _f(r.get("so")) or 0.0}
            bat[(row["game"], norm_player(r.get("player_name")))] = row
            games["bat"].append(row)
    with pitching.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("game_type") or "").upper() != "R":
                continue
            row = {"game": str(r["game_pk"]), "date": r["date"][:10], "pid": int(r["player_id"]), "team": r["team"],
                   "opp": r["opponent"], "k": _f(r.get("k")) or 0.0, "bf": _f(r.get("batters_faced")) or 0.0,
                   "starter": str(r.get("is_starter")) in ("1", "True", "true")}
            pit[(row["game"], norm_player(r.get("player_name")))] = row
            if row["starter"]:
                starters[row["game"]][row["team"]] = row["pid"]
            games["pit"].append(row)
    return bat, pit, starters, games


def load_statcast(raw_root: Path) -> dict[str, dict[str, list]]:
    """day -> {"pa": [(pitcher, batter, pitch_type, woba, is_hit)], "pitches": [(pitcher, pitch_type)]}. A day counts
    from ONE chunk (overlapping windows), as in `build_mlb_bvp_index.build`."""
    by_day: dict[str, dict[str, list]] = {}
    for chunk in sorted(raw_root.glob("**/statcast_*.csv.gz")):
        local: dict[str, dict[str, list]] = defaultdict(lambda: {"pa": [], "pitches": []})
        with gzip.open(chunk, "rt", encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                day = str(r.get("game_date") or "")[:10]
                if (r.get("game_type") or "R") != "R" or len(day) != 10:
                    continue
                try:
                    pid, bid = int(float(r.get("pitcher") or 0)), int(float(r.get("batter") or 0))
                except ValueError:
                    continue
                pt = (r.get("pitch_type") or "").strip() or "UN"
                local[day]["pitches"].append((pid, pt))
                event = str(r.get("events") or "").strip().lower()
                if event and pid > 0 and bid > 0:
                    local[day]["pa"].append((pid, bid, pt, _f(r.get("woba_value")) or 0.0, event in _HIT))
        for day, v in local.items():
            by_day.setdefault(day, v)
    return by_day


def load_legacy_bvp(legacy_dir: Path, before: str) -> dict[tuple[int, int], list[int]]:
    """(pitcher, batter) -> [PA, hits] summed over every legacy date before `before` (each date counted once)."""
    acc: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    seen: set[str] = set()
    for path in sorted(legacy_dir.glob("*.json")):
        try:
            by_date = json.loads(path.read_text(encoding="utf-8")).get("by_date") or {}
        except Exception:  # noqa: BLE001
            continue
        for day, pitcher_map in by_date.items():
            day = str(day)[:10]
            if day >= before or day in seen or not isinstance(pitcher_map, dict):
                continue
            seen.add(day)
            for pk, batters in pitcher_map.items():
                for bk, c in (batters or {}).items():
                    try:
                        a = acc[(int(pk), int(bk))]
                        a[0] += int(c.get("pa") or 0)
                        a[1] += int(c.get("hits") or 0)
                    except (TypeError, ValueError, AttributeError):
                        continue
    return acc


# ----------------------------------------------------------------------------- the as-of walk


class State:
    """Season-to-date counters, updated AFTER each day's lines are scored."""

    def __init__(self, bvp_base: dict[tuple[int, int], list[int]]):
        self.bvp = defaultdict(lambda: [0, 0], {k: list(v) for k, v in bvp_base.items()})
        self.b_type = defaultdict(lambda: [0, 0.0])        # (batter, pitch type) -> [PA, sum wOBA]
        self.b_all = defaultdict(lambda: [0, 0.0])         # batter -> [PA, sum wOBA]
        self.p_mix = defaultdict(lambda: defaultdict(int))  # pitcher -> pitch type -> pitches
        self.p_total = defaultdict(int)
        self.b_games = defaultdict(list)                   # batter -> [(h, pa)] in date order
        self.p_starts = defaultdict(list)                  # pitcher -> [(k, bf)]
        self.team_k = defaultdict(lambda: [0.0, 0.0])      # team -> [SO, PA]

    def add_day(self, statcast_day: Mapping[str, list] | None, bat_rows: list, pit_rows: list) -> None:
        for pid, pt in (statcast_day or {}).get("pitches", []):
            self.p_mix[pid][pt] += 1
            self.p_total[pid] += 1
        for pid, bid, pt, woba, is_hit in (statcast_day or {}).get("pa", []):
            self.bvp[(pid, bid)][0] += 1
            self.bvp[(pid, bid)][1] += 1 if is_hit else 0
            for key, store in (((bid, pt), self.b_type), (bid, self.b_all)):
                store[key][0] += 1
                store[key][1] += woba
        for r in bat_rows:
            if r["pa"] > 0:
                self.b_games[r["pid"]].append((r["h"], r["pa"]))
            self.team_k[r["team"]][0] += r["so"]
            self.team_k[r["team"]][1] += r["pa"]
        for r in pit_rows:
            if r["starter"] and r["bf"] > 0:
                self.p_starts[r["pid"]].append((r["k"], r["bf"]))

    def batter_features(self, bid: int, pid: int | None) -> dict[str, Any]:
        games = self.b_games.get(bid, [])
        season_pa = sum(pa for _, pa in games)
        hpa = sum(h for h, _ in games) / season_pa if season_pa >= 50 else None
        f: dict[str, Any] = {"season_pa": season_pa, "bvp_pa": None, "bvp_edge": None, "arsenal": None, "recency": None}
        if len(games) >= 27:
            last, early = games[-7:], games[:-7]
            f["recency"] = round(sum(h for h, _ in last) / max(1.0, sum(pa for _, pa in last))
                                 - sum(h for h, _ in early) / max(1.0, sum(pa for _, pa in early)), 4)
        if pid is None:
            return f
        bpa, bh = self.bvp.get((pid, bid), (0, 0))
        f["bvp_pa"] = bpa
        if bpa >= 10 and hpa is not None:
            f["bvp_edge"] = round(bh / bpa - hpa, 4)
        n_all, w_all = self.b_all.get(bid, (0, 0.0))
        if n_all >= 50 and self.p_total.get(pid, 0) >= 300:
            overall = w_all / n_all
            total = self.p_total[pid]
            score = 0.0
            for pt, cnt in self.p_mix[pid].items():
                n, w = self.b_type.get((bid, pt), (0, 0.0))
                score += (cnt / total) * ((w + SHRINK_PA * overall) / (n + SHRINK_PA))
            f["arsenal"] = round(score - overall, 4)
        return f

    def pitcher_features(self, pid: int, opp_team: str) -> dict[str, Any]:
        starts = self.p_starts.get(pid, [])
        f: dict[str, Any] = {"k_trend": None, "opp_k": None}
        if len(starts) >= 8:
            last, early = starts[-3:], starts[:-3]
            f["k_trend"] = round(sum(k for k, _ in last) / max(1.0, sum(b for _, b in last))
                                 - sum(k for k, _ in early) / max(1.0, sum(b for _, b in early)), 4)
        so, pa = self.team_k.get(opp_team, (0.0, 0.0))
        if pa >= 500:
            f["opp_k"] = round(so / pa, 4)
        return f


def collect(odds_dir: Path, hitting: Path, pitching: Path, raw_root: Path, legacy_dir: Path,
            counts: dict[str, int], *, with_outcomes: bool) -> list[dict[str, Any]]:
    bat, pit, starters, games = load_logs(hitting, pitching)
    statcast = load_statcast(raw_root)
    state = State(load_legacy_bvp(legacy_dir, "2026-01-01"))
    snaps_by_day: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(odds_dir.glob("*.json")):
        snap = json.loads(path.read_text(encoding="utf-8"))
        snaps_by_day[str(snap["date"])].append(snap)
    bat_by_day, pit_by_day = defaultdict(list), defaultdict(list)
    for r in games["bat"]:
        bat_by_day[r["date"]].append(r)
    for r in games["pit"]:
        pit_by_day[r["date"]].append(r)
    days = sorted(set(snaps_by_day) | set(statcast) | set(bat_by_day))
    records = []
    for day in days:
        for snap in snaps_by_day.get(day, []):
            game = str(snap["game"])
            for line in main_lines(snap):
                counts["main_lines"] += 1
                if line["market"] == "pitcher_strikeouts":
                    row = pit.get((game, line["player_key"]))
                    feats = state.pitcher_features(row["pid"], row["opp"]) if row else None
                else:
                    row = bat.get((game, line["player_key"]))
                    opp_sp = starters.get(game, {}).get(row["opp"]) if row else None
                    feats = state.batter_features(row["pid"], opp_sp) if row else None
                if row is None:
                    counts["void_no_box_row"] += 1
                    continue
                rec = {**line, "game": game, "day": day, "window": "confirm" if day >= SPLIT_DATE else "discover",
                       "feats": feats}
                if with_outcomes:
                    value = row[MARKET_STAT[line["market"]]]
                    if value == line["point"]:
                        counts["void_push"] += 1
                        continue
                    rec["y_over"] = 1.0 if value > line["point"] else 0.0
                counts["joined"] += 1
                records.append(rec)
        state.add_day(statcast.get(day), bat_by_day.get(day, []), pit_by_day.get(day, []))
    return records


# ----------------------------------------------------------------------------- rules, distributions, lift


def fires(f: Mapping[str, Any], t: Mapping[str, float] = THRESHOLDS) -> list[str]:
    out = []
    def ge(k, th):
        return f.get(k) is not None and t[th] != 0.0 and f[k] >= t[th]
    if ge("bvp_edge", "bvp_edge"):
        out.append("mlb.bvp_edge")
    if ge("arsenal", "arsenal_hi"):
        out.append("mlb.arsenal_edge")
    if f.get("arsenal") is not None and t["arsenal_lo"] != 0.0 and f["arsenal"] <= t["arsenal_lo"]:
        out.append("mlb.arsenal_bad")
    if ge("recency", "recency"):
        out.append("mlb.hot_streak")
    if ge("bvp_edge", "stack_bvp") and ge("arsenal", "stack_arsenal") and ge("recency", "stack_recency"):
        out.append("mlb.matchup_stack")
    if ge("k_trend", "k_trend"):
        out.append("mlb.k_trend_up")
    if ge("opp_k", "opp_k_hi"):
        out.append("mlb.opp_k_high")
    if f.get("opp_k") is not None and t["opp_k_lo"] != 0.0 and f["opp_k"] <= t["opp_k_lo"]:
        out.append("mlb.opp_k_low")
    return out


def eligible(name: str, f: Mapping[str, Any]) -> bool:
    need = {"mlb.bvp_edge": ("bvp_edge",), "mlb.arsenal_edge": ("arsenal",), "mlb.arsenal_bad": ("arsenal",),
            "mlb.hot_streak": ("recency",), "mlb.matchup_stack": ("bvp_edge", "arsenal", "recency"),
            "mlb.k_trend_up": ("k_trend",), "mlb.opp_k_high": ("opp_k",), "mlb.opp_k_low": ("opp_k",)}[name]
    return all(f.get(k) is not None for k in need)


def _q(values: list[float]) -> dict[str, Any]:
    v = sorted(values)
    if not v:
        return {"n": 0}
    pick = lambda q: round(v[min(len(v) - 1, int(q * len(v)))], 4)  # noqa: E731
    return {"n": len(v), "p10": pick(0.10), "p25": pick(0.25), "p50": pick(0.50), "p75": pick(0.75), "p90": pick(0.90)}


def distributions(records: list[dict[str, Any]]) -> dict[str, Any]:
    disc = [r for r in records if r["window"] == "discover"]
    bat = [r["feats"] for r in disc if r["market"] in BATTER_MARKETS]
    pit = [r["feats"] for r in disc if r["market"] == "pitcher_strikeouts"]
    return {"bvp_edge": _q([f["bvp_edge"] for f in bat if f.get("bvp_edge") is not None]),
            "arsenal": _q([f["arsenal"] for f in bat if f.get("arsenal") is not None]),
            "recency": _q([f["recency"] for f in bat if f.get("recency") is not None]),
            "k_trend": _q([f["k_trend"] for f in pit if f.get("k_trend") is not None]),
            "opp_k": _q([f["opp_k"] for f in pit if f.get("opp_k") is not None]),
            "lines": {"batter": len(bat), "pitcher": len(pit)}}


def lift(records: list[dict[str, Any]]) -> dict[str, Any]:
    fired, base = defaultdict(list), defaultdict(list)
    unders = defaultdict(list)
    for r in records:
        u = {"y": 1.0 - r["y_over"], "p": 1.0 - r["p_over"], "game": r["game"], "under_dec_best": r["under_dec_best"],
             "under_dec_median": r["under_dec_median"]}
        unders[(r["market"], r["window"])].append(u)
        fs = set(fires(r["feats"]))
        for name, (side, markets) in SIGNALS.items():
            if r["market"] not in markets or not eligible(name, r["feats"]):
                continue
            rec = {"y": r["y_over"] if side == "over" else 1.0 - r["y_over"],
                   "p": r["p_over"] if side == "over" else 1.0 - r["p_over"], "game": r["game"],
                   "under_dec_best": r["over_dec_best"] if side == "over" else r["under_dec_best"],
                   "under_dec_median": r["over_dec_best"] if side == "over" else r["under_dec_median"]}
            (fired if name in fs else base)[(name, r["window"])].append(rec)
    report: dict[str, Any] = {"signals": {}, "unders": {}}
    confirm_p = {}
    for name, (side, markets) in SIGNALS.items():
        e: dict[str, Any] = {"side": side, "markets": markets}
        for w in ("discover", "confirm"):
            f, b = residual_stats(fired[(name, w)], B=2000), residual_stats(base[(name, w)], B=300)
            e[w] = {"fired": f, "baseline": b,
                    "hit_lift_vs_baseline": None if not f.get("n") or not b.get("n") else round(f["hit_rate"] - b["hit_rate"], 4),
                    "roi_best_price_on_side": roi_stats(fired[(name, w)], "under_dec_best", B=600) if fired[(name, w)] else {}}
        d, c = e["discover"]["fired"], e["confirm"]["fired"]
        confirm_p[name] = c.get("p_one_sided")
        e["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["signals"][name] = e
    for name, keep in bh_adjust(confirm_p, q=0.10).items():
        report["signals"][name]["bh_q10_confirm"] = keep
    for market in MARKET_STAT:
        e = {}
        for w in ("discover", "confirm"):
            rs = unders[(market, w)]
            e[w] = {"residual": residual_stats(rs, B=2000), "roi_best_price": roi_stats(rs, "under_dec_best", B=600) if rs else {},
                    "roi_median_price": roi_stats(rs, "under_dec_median", B=600) if rs else {}}
        d, c = e["discover"]["residual"], e["confirm"]["residual"]
        e["verdict"] = "SUPPORTED" if c.get("ci95") and c["ci95"][0] > 0 and (d.get("residual") or 0) > 0 else "NOT SUPPORTED"
        report["unders"][market] = e
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--mode", choices=("distributions", "lift"), required=True)
    ap.add_argument("--odds-dir", required=True)
    ap.add_argument("--data-root", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    base = Path(args.data_root).expanduser() / "mlb_source" / "source_artifacts" / "data"
    if args.mode == "lift" and any(v == 0.0 for v in THRESHOLDS.values()):
        print("REFUSING: thresholds are not registered yet", flush=True)
        return 3
    counts: dict[str, int] = defaultdict(int)
    records = collect(Path(args.odds_dir), base / "derived" / "mlb_player_game_log_2026_hitting.csv",
                      base / "derived" / "mlb_player_game_log_2026_pitching.csv", base / "statcast" / "raw_pitches",
                      base / "cache" / "statcast" / "bvp" / "statcast_bvp_file_daily", counts,
                      with_outcomes=args.mode == "lift")
    report: dict[str, Any] = {"counts": dict(counts), "split_date": SPLIT_DATE,
                              "joined_by_window": {w: sum(1 for r in records if r["window"] == w) for w in ("discover", "confirm")},
                              "games_by_window": {w: len({r["game"] for r in records if r["window"] == w}) for w in ("discover", "confirm")}}
    if args.mode == "distributions":
        report["distributions_discover"] = distributions(records)
    else:
        report.update(lift(records))
        report["thresholds"] = dict(THRESHOLDS)
    Path(args.out).write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("counts", "joined_by_window", "games_by_window")}), flush=True)
    if args.mode == "distributions":
        for k, v in report["distributions_discover"].items():
            print(f"  {k}: {v}", flush=True)
        return 0
    for name, e in report["signals"].items():
        for w in ("discover", "confirm"):
            f, b = e[w]["fired"], e[w]["baseline"]
            print(f"  {name:20s} {w:8s} fired n={f.get('n')} g={f.get('games')} hit={f.get('hit_rate')} p={f.get('mean_p')} "
                  f"resid={f.get('residual')} ci={f.get('ci95')} | base n={b.get('n')} resid={b.get('residual')} "
                  f"| lift={e[w]['hit_lift_vs_baseline']} ROI={e[w]['roi_best_price_on_side'].get('roi_pct')}", flush=True)
        print(f"  {name:20s} VERDICT {e['verdict']}  BH={e['bh_q10_confirm']}", flush=True)
    for market, e in report["unders"].items():
        for w in ("discover", "confirm"):
            s, rb = e[w]["residual"], e[w]["roi_best_price"]
            print(f"  unders {market:20s} {w:8s} n={s.get('n')} g={s.get('games')} resid={s.get('residual')} ci={s.get('ci95')} "
                  f"ROI best={rb.get('roi_pct')} median={e[w]['roi_median_price'].get('roi_pct')}", flush=True)
        print(f"  unders {market:20s} VERDICT {e['verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
