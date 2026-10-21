"""How stale is the NBA SmartSim's market anchor, and would the near-close line have scored better? Read-only.

Lane nba-sim-anchor-staleness (2026-10-21). The sim blends its team means toward the market BEFORE sampling
(`_apply_market_anchor_local`: total 0.7, margin 0.95). The line it blends toward is the job's
`predictions_<D>.csv` row, falling back to `game_odds_<D>.csv`. Both are written once, by the first props refresh
that sees the date (about a day before tip), and never rewritten:
- `_seed_game_odds_from_props_snapshot` returns as soon as `game_odds_<D>.csv` has prices, and
  `_merge_new_snapshot_matchups_into_game_odds` only APPENDS games it lacks;
- `_ensure_game_predictions_for_props_refresh` reuses `predictions_<D>.csv` once it has rows.

For every surviving `smart_sim_<D>_<H>_<A>.json` this prints:
- the anchor the sim recorded (`market_anchor.market_total` / `market_spread`) and when `game_odds_<D>.csv` was
  written (the anchor's capture time), against the tip;
- the consensus at a lead before tip, from `tracking/book_quotes/<D>.jsonl[.gz]`;
- the final, from `linescores_<D>.json` (period sums, OT included), else `recon_games_<D>.csv`.

Consensus is the anchor writer's method. `game_odds_<D>.csv` is written by `predict-date`
(`source_cli/cli.py`, OddsAPI current odds -> `consensus_lines_at_close`), which takes the MODAL point across books
(home spread rows; Over rows), the smaller value on a tie. The props-snapshot seeder's mean is printed beside it.
book_quotes is written ON CHANGE, so a book's standing line at time T is its last row with `captured_at <= T`. Rows
after tip are in-play and are never used.

The counterfactual anchor re-runs `_apply_market_anchor_local` (imported, not copied) on the recorded raw model
means (`model_total_raw`, `model_margin_raw`) with the consensus line instead. The script first checks that the
recorded line reproduces the recorded `anchored_total` / `anchored_margin`, and says how many did not.
The served sim mean (`score.total_mean` / `margin_mean`) comes out of the possession engine, not the anchor
arithmetic. Its counterfactual is `served + (anchored_cf - anchored_recorded)`, i.e. pass-through 1. That is an
ASSUMPTION; the anchored targets are scored on their own beside it.

    python scripts/nba_anchor_staleness.py --data-root /home/amyn/syndicate-prod/data --since 2026-10-03 \
        [--until 2026-10-23] [--lead-minutes 0,30] [--stale-from sim|game_odds] [--json out.json]

After #721 the sim records the REFRESHED line, so the regular-season reading takes the stale arm from
`game_odds_<D>.csv` (`--stale-from game_odds`). Each served counterfactual is the served mean moved by its arm's
anchored delta from the line the sim recorded, so the arithmetic holds whichever line that was.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from syndicate.features.shared.basketball_props_smart_sim import (  # noqa: E402
    _NBA_LEAGUE_LOCAL,
    _apply_market_anchor_local,
    _to_tricode_local,
)

CT = timezone(timedelta(hours=-5))  # US Central, daylight time (in force through 2026-11-01)
MAIN_MARKETS = ("spreads", "totals")


def _utc(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        out = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return out if out.tzinfo else out.replace(tzinfo=timezone.utc)


def _ct(ts: datetime | None) -> str:
    return ts.astimezone(CT).strftime("%m-%d %I:%M %p CT") if ts else "-"


def _num(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _dates(since: str, until: str) -> list[str]:
    d0, d1 = date.fromisoformat(since), date.fromisoformat(until)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


class Quotes:
    """Main-line game quotes (full game, spreads/totals) per (home_tri, away_tri), sorted by captured_at."""

    def __init__(self, quotes_dir: Path):
        self.dir = quotes_dir
        self.loaded: set[str] = set()
        self.by_game: dict[tuple[str, str], list[dict]] = defaultdict(list)
        self.files_read: list[str] = []

    def load(self, day: str) -> None:
        if day in self.loaded:
            return
        self.loaded.add(day)
        for path in (self.dir / f"{day}.jsonl", self.dir / f"{day}.jsonl.gz"):
            if not path.is_file():
                continue
            opener = gzip.open if path.suffix == ".gz" else open
            with opener(path, "rt", encoding="utf-8") as handle:
                for line in handle:
                    if '"kind":"game"' not in line or '"segment":"full"' not in line:
                        continue
                    if '"market":"spreads"' not in line and '"market":"totals"' not in line:
                        continue
                    row = json.loads(line)
                    if row.get("market") not in MAIN_MARKETS or _num(row.get("line")) is None:
                        continue
                    key = (_to_tricode_local(row.get("home_team")), _to_tricode_local(row.get("away_team")))
                    row["_cap"] = _utc(row.get("captured_at"))
                    row["_tip"] = _utc(row.get("commence_time"))
                    if row["_cap"] is None:
                        continue
                    self.by_game[key].append(row)
            self.files_read.append(path.name)
        for rows in self.by_game.values():
            rows.sort(key=lambda r: r["_cap"])

    def consensus(self, home: str, away: str, tip: datetime | None, at: datetime) -> dict:
        """Every book's standing main line at `at` (never after tip), reduced the way the anchor's writer reduces it.

        `total` / `spread` are the MODAL point, ties to the smaller value: `consensus_lines_at_close`
        (`source_cli/odds_api.py`), which `predict-date` uses to write `game_odds_<D>.csv` (pandas
        `Series.mode().iloc[0]` over the home spread rows and over the Over rows). `total_mean` / `spread_mean`
        are the props-snapshot seeder's mean (`_aggregate_game_odds_from_market_rows`), kept for comparison.
        """
        standing: dict[tuple[str, str, str], dict] = {}
        for row in self.by_game.get((home, away), []):
            if row["_cap"] > at:
                break
            if tip is not None and row["_tip"] is not None and abs((row["_tip"] - tip).total_seconds()) > 6 * 3600:
                continue  # a different meeting of the same two teams
            standing[(row["bookmaker"], row["market"], row["selection"])] = row
        overs = [float(r["line"]) for (b, m, s), r in standing.items() if m == "totals" and s == "over"]
        totals = [float(r["line"]) for (b, m, s), r in standing.items() if m == "totals"]
        home_sp = [float(r["line"]) for (b, m, s), r in standing.items() if m == "spreads" and s == "home"]
        away_sp = [float(r["line"]) for (b, m, s), r in standing.items() if m == "spreads" and s == "away"]
        spread_mean = statistics.fmean(home_sp) if home_sp else (-statistics.fmean(away_sp) if away_sp else None)
        caps = [r["_cap"] for r in standing.values()]
        return {
            "total": _mode_low(overs),
            "spread": _mode_low(home_sp),
            "total_mean": statistics.fmean(totals) if totals else None,
            "spread_mean": spread_mean,
            "books": len({b for (b, m, s) in standing}),
            "newest_quote": max(caps) if caps else None,
        }


def _mode_low(values: list[float]) -> float | None:
    """pandas `Series.mode().iloc[0]`: the most frequent value, the smallest one on a tie."""
    if not values:
        return None
    counts = Counter(values)
    top = max(counts.values())
    return min(v for v, c in counts.items() if c == top)


_ESPN_TRI = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}


def _espn_tri(value) -> str:
    text = str(value or "").strip().upper()
    return _ESPN_TRI.get(text, text)


def _finals(processed: Path, day: str) -> dict[tuple[str, str], tuple[int, int, str]]:
    out: dict[tuple[str, str], tuple[int, int, str]] = {}
    recon = processed / f"recon_games_{day}.csv"
    if recon.is_file():
        import csv

        with recon.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                h, a = _num(row.get("home_pts")), _num(row.get("visitor_pts"))
                if h is not None and a is not None:
                    out[(str(row["home_tri"]).upper(), str(row["away_tri"]).upper())] = (int(h), int(a), "recon_games")
    lines = processed / f"linescores_{day}.json"
    if lines.is_file():
        for game in (json.loads(lines.read_text(encoding="utf-8")).get("games") or {}).values():
            hp, ap = game.get("home_periods") or [], game.get("away_periods") or []
            if len(hp) >= 4 and len(ap) >= 4:
                key = (_espn_tri(game.get("home")), _espn_tri(game.get("away")))
                h, a = int(sum(hp)), int(sum(ap))
                prior = out.get(key)
                out[key] = (h, a, "linescores" if prior is None else ("both" if prior[:2] == (h, a) else "MISMATCH"))
    return out


def _game_odds_rows(processed: Path, day: str) -> tuple[dict[tuple[str, str], dict], datetime | None]:
    import csv

    path = processed / f"game_odds_{day}.csv"
    if not path.is_file():
        return {}, None
    rows = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            key = (_to_tricode_local(row.get("home_team")), _to_tricode_local(row.get("visitor_team") or row.get("away_team")))
            rows[key] = row
    return rows, datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _anchor(raw_total: float, raw_margin: float, total: float | None, spread: float | None, w_total: float, w_margin: float) -> tuple[float, float]:
    home_mu, away_mu = _apply_market_anchor_local(
        home_mu=0.5 * (raw_total + raw_margin),
        away_mu=0.5 * (raw_total - raw_margin),
        market_total=total,
        market_home_spread=spread,
        w_total=w_total,
        w_margin=w_margin,
        min_team_pts=float(_NBA_LEAGUE_LOCAL.min_team_points),
    )
    return home_mu + away_mu, home_mu - away_mu


def collect(data_root: Path, since: str, until: str, leads: list[int], regular_from: str, now: datetime,
            stale_from: str = "sim") -> list[dict]:
    processed = data_root / "nba_source" / "data" / "processed"
    quotes = Quotes(data_root / "nba_source" / "tracking" / "book_quotes")
    out: list[dict] = []
    for day in _dates(since, until):
        sims = sorted(glob.glob(str(processed / f"smart_sim_{day}_*_*.json")))
        if not sims:
            continue
        for qday in (day, (date.fromisoformat(day) + timedelta(days=1)).isoformat()):
            quotes.load(qday)
        odds_rows, odds_mtime = _game_odds_rows(processed, day)
        finals = _finals(processed, day)
        for sim_path in sims:
            sim = json.loads(Path(sim_path).read_text(encoding="utf-8"))
            home, away = str(sim.get("home") or "").upper(), str(sim.get("away") or "").upper()
            anchor = sim.get("market_anchor") or {}
            score = sim.get("score") or {}
            odds_row = odds_rows.get((home, away)) or {}
            tip = _utc(odds_row.get("commence_time"))
            if tip is None:
                tips = [r["_tip"] for r in quotes.by_game.get((home, away), []) if r["_tip"] is not None]
                tip = min(tips) if tips else None
            rec = {
                "date": day,
                "phase": "regular" if day >= regular_from else "preseason",
                "game": f"{home}_{away}",
                "tip": tip,
                "anchor_written": odds_mtime,
                "anchor_total": _num(anchor.get("market_total")),
                "anchor_spread": _num(anchor.get("market_spread")),
                "anchor_line_source": anchor.get("market_line_source"),
                "anchor_line_as_of": anchor.get("market_line_as_of"),
                "game_odds_total": _num(odds_row.get("total")),
                "game_odds_spread": _num(odds_row.get("home_spread")),
                "w_total": _num(anchor.get("total_w")),
                "w_margin": _num(anchor.get("margin_w")),
                "anchor_state": anchor.get("state"),
                "raw_total": _num(anchor.get("model_total_raw")),
                "raw_margin": _num(anchor.get("model_margin_raw")),
                "anchored_total": _num(anchor.get("anchored_total")),
                "anchored_margin": _num(anchor.get("anchored_margin")),
                "served_total": _num(score.get("total_mean")),
                "served_margin": _num(score.get("margin_mean")),
                "sim_written": datetime.fromtimestamp(os.path.getmtime(sim_path), tz=timezone.utc),
                "final": finals.get((home, away)),
                "pending": tip is None or tip > now,
            }
            # The stale arm: the line the sim recorded, or (once sims carry the refreshed line, #721) the line
            # predict-date stored in game_odds_<D>.csv.
            if stale_from == "game_odds":
                rec["stale_total"], rec["stale_spread"] = rec["game_odds_total"], rec["game_odds_spread"]
            else:
                rec["stale_total"], rec["stale_spread"] = rec["anchor_total"], rec["anchor_spread"]
            # The consensus at the anchor's own write time: the method check (it should reproduce the anchor).
            if odds_mtime is not None:
                rec["consensus_at_anchor_write"] = quotes.consensus(home, away, tip, odds_mtime)
            for lead in leads:
                at = (min(tip, now) if tip is not None else now) - timedelta(minutes=lead if tip is not None and tip <= now else 0)
                rec[f"close_{lead}"] = quotes.consensus(home, away, tip, at)
            out.append(rec)
    return out


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    vals = sorted(values)
    p90 = vals[min(len(vals) - 1, int(math.ceil(0.9 * len(vals))) - 1)]
    return {
        "n": len(vals),
        "median": statistics.median(vals),
        "mean": statistics.fmean(vals),
        "p90": p90,
        "max": vals[-1],
        "ge1": sum(v >= 1.0 for v in vals),
        "ge2": sum(v >= 2.0 for v in vals),
    }


def _paired(errors_a: list[float], errors_b: list[float]) -> dict:
    """b - a on absolute errors: negative = b is closer to the final."""
    diffs = [b - a for a, b in zip(errors_a, errors_b)]
    n = len(diffs)
    if n == 0:
        return {"n": 0}
    mean = statistics.fmean(diffs)
    se = statistics.stdev(diffs) / math.sqrt(n) if n > 1 else float("nan")
    return {
        "n": n,
        "mae_a": statistics.fmean(errors_a),
        "mae_b": statistics.fmean(errors_b),
        "diff": mean,
        "se": se,
        "b_better": sum(d < 0 for d in diffs),
        "b_worse": sum(d > 0 for d in diffs),
        "tied": sum(d == 0 for d in diffs),
    }


def analyse(records: list[dict], lead: int) -> dict:
    key = f"close_{lead}"
    report: dict = {"lead_minutes": lead}
    method_ok = method_n = method_tot = method_sp = recon_ok = recon_n = 0
    misses: list[str] = []
    for rec in records:
        at_write = rec.get("consensus_at_anchor_write") or {}
        if None not in (rec["anchor_total"], rec["anchor_spread"], at_write.get("total"), at_write.get("spread")):
            method_n += 1
            tot_ok = abs(at_write["total"] - rec["anchor_total"]) < 0.01
            sp_ok = abs(at_write["spread"] - rec["anchor_spread"]) < 0.01
            method_tot += int(tot_ok)
            method_sp += int(sp_ok)
            method_ok += int(tot_ok and sp_ok)
            if not (tot_ok and sp_ok):
                misses.append(f"{rec['date']} {rec['game']} anchor {rec['anchor_total']}/{rec['anchor_spread']} "
                              f"quotes {at_write['total']}/{at_write['spread']} ({at_write.get('books')} books)")
        if None not in (rec["raw_total"], rec["raw_margin"], rec["anchored_total"], rec["w_total"], rec["w_margin"]):
            recon_n += 1
            t, m = _anchor(rec["raw_total"], rec["raw_margin"], rec["anchor_total"], rec["anchor_spread"], rec["w_total"], rec["w_margin"])
            recon_ok += int(abs(t - rec["anchored_total"]) < 1e-6 and abs(m - rec["anchored_margin"]) < 1e-6)
    report["method_check"] = {"both_equal": method_ok, "total_equal": method_tot, "spread_equal": method_sp,
                              "of": method_n, "misses": misses}
    report["anchor_reconstruction"] = {"exact": recon_ok, "of": recon_n}

    for phase in ("preseason", "regular", "all"):
        rows = [r for r in records if phase == "all" or r["phase"] == phase]
        stale_t, stale_s, ages, dt_signed, ds_signed = [], [], [], [], []
        for r in rows:
            close = r.get(key) or {}
            if r["stale_total"] is not None and close.get("total") is not None:
                stale_t.append(abs(close["total"] - r["stale_total"]))
                dt_signed.append(close["total"] - r["stale_total"])
            if r["stale_spread"] is not None and close.get("spread") is not None:
                stale_s.append(abs(close["spread"] - r["stale_spread"]))
                ds_signed.append(close["spread"] - r["stale_spread"])
            if r["tip"] is not None and r["anchor_written"] is not None:
                ages.append((r["tip"] - r["anchor_written"]).total_seconds() / 3600.0)
        acc: dict = {}
        graded = [r for r in rows if r["final"] and not r["pending"] and (r.get(key) or {}).get("total") is not None
                  and r["stale_total"] is not None and r["stale_spread"] is not None and (r.get(key) or {}).get("spread") is not None]
        if graded:
            lt_o, lt_c, ls_o, ls_c, at_o, at_c, am_o, am_c, st_o, st_c, sm_o, sm_c = ([] for _ in range(12))
            for r in graded:
                h, a, _src = r["final"]
                tot, mar = h + a, h - a
                close = r[key]
                lt_o.append(abs(r["stale_total"] - tot))
                lt_c.append(abs(close["total"] - tot))
                ls_o.append(abs(-r["stale_spread"] - mar))
                ls_c.append(abs(-close["spread"] - mar))
                if None in (r["raw_total"], r["raw_margin"], r["w_total"], r["w_margin"]):
                    continue
                t_o, m_o = _anchor(r["raw_total"], r["raw_margin"], r["stale_total"], r["stale_spread"], r["w_total"], r["w_margin"])
                t_c, m_c = _anchor(r["raw_total"], r["raw_margin"], close["total"], close["spread"], r["w_total"], r["w_margin"])
                at_o.append(abs(t_o - tot)); at_c.append(abs(t_c - tot))
                am_o.append(abs(m_o - mar)); am_c.append(abs(m_c - mar))
                if r["served_total"] is not None and r["served_margin"] is not None:
                    # the served mean belongs to the line the sim RECORDED; each arm moves it by its anchored delta
                    t_r, m_r = _anchor(r["raw_total"], r["raw_margin"], r["anchor_total"], r["anchor_spread"], r["w_total"], r["w_margin"])
                    st_o.append(abs(r["served_total"] + (t_o - t_r) - tot)); st_c.append(abs(r["served_total"] + (t_c - t_r) - tot))
                    sm_o.append(abs(r["served_margin"] + (m_o - m_r) - mar)); sm_c.append(abs(r["served_margin"] + (m_c - m_r) - mar))
            acc = {
                "line_total": _paired(lt_o, lt_c),
                "line_margin": _paired(ls_o, ls_c),
                "anchored_total": _paired(at_o, at_c),
                "anchored_margin": _paired(am_o, am_c),
                "served_total": _paired(st_o, st_c),
                "served_margin": _paired(sm_o, sm_c),
            }
        report[phase] = {
            "games": len(rows),
            "pending": sum(r["pending"] for r in rows),
            "dates": sorted({r["date"] for r in rows}),
            "staleness_total_abs": _stats(stale_t),
            "staleness_spread_abs": _stats(stale_s),
            "move_total_signed_mean": statistics.fmean(dt_signed) if dt_signed else None,
            "move_spread_signed_mean": statistics.fmean(ds_signed) if ds_signed else None,
            "anchor_age_at_tip_hours": _stats(ages),
            "accuracy_open_vs_close": acc,
        }
    return report


def _fmt(v, nd=1):
    return "-" if v is None else (f"{v:+.{nd}f}" if isinstance(v, float) else str(v))


def print_table(records: list[dict], leads: list[int]) -> None:
    lead = leads[0]
    key = f"close_{lead}"
    print(f"{'date':10} {'game':8} {'tip':18} {'age_h':>5} | {'anc_tot':>7} {'cls_tot':>7} {'dTot':>5} | "
          f"{'anc_sp':>6} {'cls_sp':>6} {'dSp':>5} | {'bk':>2} {'quote_as_of':18} | {'final':>9} {'srv_tot':>7} {'srv_mar':>7}")
    for r in records:
        close = r.get(key) or {}
        age = (r["tip"] - r["anchor_written"]).total_seconds() / 3600 if r["tip"] and r["anchor_written"] else None
        fin = f"{r['final'][0]}-{r['final'][1]}" if r["final"] else ("pending" if r["pending"] else "-")
        d_t = close["total"] - r["stale_total"] if close.get("total") is not None and r["stale_total"] is not None else None
        d_s = close["spread"] - r["stale_spread"] if close.get("spread") is not None and r["stale_spread"] is not None else None
        print(f"{r['date']:10} {r['game']:8} {_ct(r['tip']):18} {(f'{age:5.1f}' if age is not None else '    -')} | "
              f"{_fmt(r['stale_total']):>7} {_fmt(close.get('total')):>7} {_fmt(d_t):>5} | "
              f"{_fmt(r['stale_spread']):>6} {_fmt(close.get('spread')):>6} {_fmt(d_s):>5} | "
              f"{close.get('books', 0):>2} {_ct(close.get('newest_quote')):18} | {fin:>9} "
              f"{_fmt(r['served_total']):>7} {_fmt(r['served_margin']):>7}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-root", required=True, type=Path)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until", default=None)
    ap.add_argument("--lead-minutes", default="0,30", help="consensus taken this long before tip; first one is tabled")
    ap.add_argument("--regular-from", default="2026-10-20", help="first regular-season date")
    ap.add_argument("--stale-from", choices=("sim", "game_odds"), default="sim",
                    help="the stale arm: the sim's recorded line (default), or game_odds_<D>.csv once sims carry the "
                         "refreshed line (#721)")
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    now = datetime.now(timezone.utc)
    until = args.until or now.astimezone(CT).date().isoformat()
    leads = [int(x) for x in str(args.lead_minutes).split(",") if str(x).strip()]
    records = collect(args.data_root, args.since, until, leads, args.regular_from, now, args.stale_from)
    print(f"read at {_ct(now)}; {len(records)} surviving sims {args.since}..{until}")
    print_table(records, leads)
    reports = [analyse(records, lead) for lead in leads]
    print(json.dumps(reports, indent=1, default=str))
    if args.json:
        args.json.write_text(json.dumps({"records": records, "reports": reports}, indent=1, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
