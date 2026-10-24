"""Live + paper cell scorecard for Kalshi / Polymarket -- where real edge is, and where it is not.

Lane `live-cell-scorecard` (2026-10-24). Findings: `.syndicate/findings_2026-10-24_live_cell_scorecard.md`.
Read-only. Two steps:

    # 1. FLEET (inside WSL, fleet venv, refresh-worker state env, nice 19) -- writes only --out
    python scripts/live_cell_scorecard.py dump --out /mnt/c/tmp/lcs/ledger.json

    # nightly (the `live-cell-scorecard` job in scripts/local_production.py; fleet env, renices itself to 19)
    python scripts/live_cell_scorecard.py nightly   # -> $SYNDICATE_REPORTS_ROOT/intelligence/live_cell_scorecard/<date>.{json,md}

    # 2. anywhere
    py -3 scripts/live_cell_scorecard.py report --ledger C:/tmp/lcs/ledger.json [--since 2026-10-20] \
        [--until ...] [--out-json PATH] [--out-md PATH] [--min-n 5] [--reps 2000]

`dump` asserts the keyvalue read of the live ledger document returned ok=True before it trusts a count:
`read_json_file` turns a failed read into an EMPTY document (#658), and a system `python3` with no
`redis` module produced exactly that on 2026-10-22 (findings_2026-10-22_sim_stake_earned_profile.md s0).

CELL = book x venue x sport x family x price bucket x phase.

- book: `live` (venue kalshi / polymarket, real money), `paper` (paper:kalshi / paper:polymarket, the
  alongside-live book), `ladder` (paper:<venue>:ladder, the below-floor EV bands).
- family: h2h / spread / total / prop / parlay / other. From `market` (+ `player_name`) when the row has it;
  the 552 `venue_rebuild` rows (08-06..09-28) have no market, so it is parsed from the Kalshi series ticker
  or the Polymarket slug prefix (aec/atc h2h, asc spread, tsc total, astatc prop).
- price bucket: the CONTRACT price of the side bought, 0..1. Live rows record `fill_price` as a contract
  price (rebuilds: `venue_avg_price`); paper rows record American odds and are converted with
  `paper_settlement.profit_per_dollar` -- the repo's unit rule (`[ledger-price-units]`).
- phase: live rows by the path that placed them -- `in_game` when the row has no `ev_pct` and is not a
  rebuild (the in-game entry path stamps no ev; first one 2026-10-23T23:38Z); paper rows `in_game` when
  submitted at/after `commence_time`; else `pregame`.

Metrics per cell: n bets, games, staked, pnl (`pnl_dollars`, which is net of fees on every book),
dollar ROI = pnl/staked, flat ROI = mean(pnl/stake), win rate, mean price, same-book CLV (`closing_mark.
clv_pct` where `close_book_scope == same_book`) with its n, and a GAME-CLUSTERED bootstrap 90% CI on both
ROIs (games resampled with replacement; seeded, so reruns reproduce). Game = `event_id`, else the game
token of the ticker / slug, so every leg on one game moves together.

Paper rows are deduplicated per (venue, position_key) keeping the first submit, as the paper studies do; a
live row is a real fill and is never deduplicated.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

LIVE_VENUES = ("kalshi", "polymarket")
PAPER_VENUES = ("paper:kalshi", "paper:polymarket")
LADDER_VENUES = ("paper:kalshi:ladder", "paper:polymarket:ladder")
BUCKETS = ((0.0, 0.40, "<40c"), (0.40, 0.55, "40-55c"), (0.55, 0.75, "55-75c"), (0.75, 1.01, "75c+"))
SETTLED = ("won", "lost", "push")

# The cell classifiers live in the gate, so the gate and the report that justifies it can never disagree.
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from syndicate.features.shared.live_cell_gate import (  # noqa: E402
    family_of, game_of, parse_ts as _ts, phase_of, sport_of,
)


def contract_price(price: Any) -> float | None:
    """0..1 price of the side bought, from a contract price or American odds."""
    try:
        p = float(price)
    except (TypeError, ValueError):
        return None
    if 0.0 < p < 1.0:
        return p
    try:
        from syndicate.features.shared.paper_settlement import profit_per_dollar
        profit = profit_per_dollar(p)
    except ImportError:
        profit = (p / 100.0) if p >= 100 else (100.0 / -p) if p <= -100 else None
    if not profit or profit <= 0:
        return None
    return 1.0 / (1.0 + profit)


def bucket(p: float | None) -> str:
    if p is None:
        return "?"
    for lo, hi, name in BUCKETS:
        if lo <= p < hi:
            return name
    return "?"


def book_of(venue: str) -> str | None:
    if venue in LIVE_VENUES:
        return "live"
    if venue in PAPER_VENUES:
        return "paper"
    if venue in LADDER_VENUES:
        return "ladder"
    return None


def rows_from(orders: Iterable[Mapping[str, Any]], since: str | None = None, until: str | None = None) -> tuple[list[dict], dict]:
    """Settled, filled, staked rows, one dict each, plus a drop census."""
    drops: dict[str, int] = defaultdict(int)
    seen: set = set()
    out: list[dict] = []
    ordered = sorted(orders, key=lambda o: str(o.get("submitted_at") or ""))
    for r in ordered:
        venue = str(r.get("venue"))
        book = book_of(venue)
        if book is None:
            continue
        if r.get("status") != "filled":
            drops[f"{book}:not_filled"] += 1
            continue
        if r.get("outcome") not in SETTLED:
            drops[f"{book}:unsettled"] += 1
            continue
        sub = str(r.get("submitted_at") or "")
        if (since and sub < since) or (until and sub >= until):
            continue
        stake = float(r.get("fill_stake_dollars") or 0.0)
        if stake <= 0 or r.get("pnl_dollars") is None:
            drops[f"{book}:no_stake_or_pnl"] += 1
            continue
        if book != "live":
            key = (venue, r.get("position_key") or r.get("opening_key") or r.get("idempotency_key"))
            if key in seen:
                drops[f"{book}:duplicate_position"] += 1
                continue
            seen.add(key)
        price = contract_price(r.get("fill_price") if r.get("fill_price") not in (None, 0) else r.get("venue_avg_price"))
        mark = r.get("closing_mark") if isinstance(r.get("closing_mark"), Mapping) else {}
        clv = mark.get("clv_pct") if mark.get("close_book_scope") == "same_book" else None
        out.append({
            "book": book,
            "venue": venue.split(":")[1] if ":" in venue else venue,
            "sport": sport_of(r),
            "family": family_of(r),
            "bucket": bucket(price),
            "phase": phase_of(r),
            "game": game_of(r),
            "date": str(r.get("selected_date") or sub[:10]),
            "submitted_at": sub,
            "price": price,
            "stake": stake,
            "pnl": float(r["pnl_dollars"]),
            "outcome": r["outcome"],
            "clv": float(clv) if isinstance(clv, (int, float)) else None,
            "exited": bool(r.get("exit_applied")),
        })
    return out, dict(drops)


def _roi(rows: list[dict]) -> tuple[float, float]:
    staked = sum(r["stake"] for r in rows)
    dollar = sum(r["pnl"] for r in rows) / staked if staked else float("nan")
    flat = sum(r["pnl"] / r["stake"] for r in rows) / len(rows) if rows else float("nan")
    return dollar, flat


def clustered_ci(rows: list[dict], reps: int = 2000, seed: int = 20261024, level: float = 0.90) -> dict:
    """Game-clustered bootstrap percentile CI on dollar and flat ROI."""
    by_game: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_game[r["game"]].append(r)
    games = list(by_game.values())
    if len(games) < 2:
        return {"dollar": (None, None), "flat": (None, None)}
    rng = random.Random(seed)
    dollar, flat = [], []
    for _ in range(reps):
        stake = pnl = unit = 0.0
        n = 0
        for _g in range(len(games)):
            for r in games[rng.randrange(len(games))]:
                stake += r["stake"]
                pnl += r["pnl"]
                unit += r["pnl"] / r["stake"]
                n += 1
        dollar.append(pnl / stake if stake else 0.0)
        flat.append(unit / n if n else 0.0)
    lo_i, hi_i = int(reps * (1 - level) / 2), int(reps * (1 + level) / 2) - 1
    dollar.sort()
    flat.sort()
    return {"dollar": (dollar[lo_i], dollar[hi_i]), "flat": (flat[lo_i], flat[hi_i])}


def summarise(rows: list[dict], reps: int) -> dict:
    dollar, flat = _roi(rows)
    ci = clustered_ci(rows, reps=reps)
    clvs = [r["clv"] for r in rows if r["clv"] is not None]
    decided = [r for r in rows if r["outcome"] != "push"]
    return {
        "n": len(rows),
        "games": len({r["game"] for r in rows}),
        "staked": round(sum(r["stake"] for r in rows), 2),
        "pnl": round(sum(r["pnl"] for r in rows), 2),
        "roi_dollar": round(100 * dollar, 2),
        "roi_flat": round(100 * flat, 2),
        "ci90_dollar": [None if v is None else round(100 * v, 1) for v in ci["dollar"]],
        "ci90_flat": [None if v is None else round(100 * v, 1) for v in ci["flat"]],
        "win_rate": round(sum(r["outcome"] == "won" for r in decided) / len(decided), 3) if decided else None,
        "mean_price": round(sum(r["price"] for r in rows if r["price"] is not None) / max(1, sum(r["price"] is not None for r in rows)), 3),
        "clv_same_book_mean": round(sum(clvs) / len(clvs), 2) if clvs else None,
        "clv_n": len(clvs),
        "dates": [min(r["date"] for r in rows), max(r["date"] for r in rows)] if rows else None,
    }


MIN_GAMES = 10   # below this a game-clustered CI is a handful of draws, not an interval


def verdict(s: Mapping[str, Any], min_n: int) -> str:
    """EDGE / LOSES only when the flat-ROI CI90 excludes 0 on >= min_n bets and >= MIN_GAMES games.

    Not a gate by itself: ~100 cells are scored, so ~5 will clear a one-sided 5% bar by chance. A cell
    earns money only on a FORWARD record (the gate policy in the findings), never on this table alone.
    """
    lo, hi = s["ci90_flat"]
    if s["n"] < min_n or s["games"] < MIN_GAMES or lo is None:
        return "thin"
    if lo > 0:
        return "EDGE"
    if hi < 0:
        return "LOSES"
    return "unproven"


def group(rows: list[dict], keys: tuple[str, ...], reps: int, min_n: int) -> list[dict]:
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        cells[tuple(r[k] for k in keys)].append(r)
    out = []
    for key, rs in cells.items():
        s = summarise(rs, reps)
        s.update(dict(zip(keys, key)))
        s["verdict"] = verdict(s, min_n)
        out.append(s)
    out.sort(key=lambda s: (-s["staked"]))
    return out


def coverage(rows: list[dict]) -> dict:
    out = {}
    for book_venue in sorted({(r["book"], r["venue"]) for r in rows}):
        rs = [r for r in rows if (r["book"], r["venue"]) == book_venue]
        dates = sorted({r["date"] for r in rs})
        out[":".join(book_venue)] = {"settled": len(rs), "dates": len(dates), "first": dates[0], "last": dates[-1],
                                     "in_game": sum(r["phase"] == "in_game" for r in rs)}
    return out


def build_report(orders: list[Mapping[str, Any]], since: str | None, until: str | None, reps: int, min_n: int) -> dict:
    rows, drops = rows_from(orders, since, until)
    cell_keys = ("book", "venue", "sport", "family", "bucket", "phase")
    return {
        "window": {"since": since, "until": until},
        "orders_read": len(orders),
        "newest_submitted_at": max((str(o.get("submitted_at") or "") for o in orders), default=None),
        "coverage": coverage(rows),
        "drops": drops,
        "headline": group(rows, ("book", "venue", "phase"), reps, min_n),
        "by_bucket": group(rows, ("book", "venue", "bucket"), reps, min_n),
        "by_family": group(rows, ("book", "venue", "sport", "family"), reps, min_n),
        "cells": group(rows, cell_keys, reps, min_n),
        "weekly": weekly(rows),
    }


def weekly(rows: list[dict]) -> list[dict]:
    """P&L per ISO week (Mon-Sun, by submit date) x book x venue x phase -- the weekly report's table."""
    cells: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        d = _ts(r["submitted_at"]) or _ts(r["date"] + "T00:00:00+00:00")
        year, week, _ = d.isocalendar()
        cells[(f"{year}-W{week:02d}", r["book"], r["venue"], r["phase"])].append(r)
    out = []
    for (wk, book, venue, phase), rs in sorted(cells.items()):
        staked = sum(r["stake"] for r in rs)
        pnl = sum(r["pnl"] for r in rs)
        out.append({"week": wk, "book": book, "venue": venue, "phase": phase, "n": len(rs),
                    "staked": round(staked, 2), "pnl": round(pnl, 2), "roi_dollar": round(100 * pnl / staked, 1) if staked else None})
    return out


def _fmt_ci(ci: list) -> str:
    return "n/a" if ci[0] is None else f"[{ci[0]:+.0f}, {ci[1]:+.0f}]"


def markdown(report: Mapping[str, Any], min_n: int) -> str:
    lines = [f"# Cell scorecard -- window {report['window']}",
             f"orders read {report['orders_read']}, newest submit {report['newest_submitted_at']}", "", "## Coverage", "",
             "| book:venue | settled | dates | first | last | in-game |", "|---|---|---|---|---|---|"]
    for k, c in report["coverage"].items():
        lines.append(f"| {k} | {c['settled']} | {c['dates']} | {c['first']} | {c['last']} | {c['in_game']} |")
    lines += ["", f"drops: {report['drops']}", ""]
    cols = "| n | games | staked | pnl | ROI $ | ROI flat | CI90 flat | win | px | CLV sb (n) | verdict |"
    for title, section, keys in (("Headline", "headline", ("book", "venue", "phase")),
                                 ("By price bucket", "by_bucket", ("book", "venue", "bucket")),
                                 ("By sport x family", "by_family", ("book", "venue", "sport", "family")),
                                 (f"Cells (n >= {min_n})", "cells", ("book", "venue", "sport", "family", "bucket", "phase"))):
        lines += [f"## {title}", "", "| " + " | ".join(keys) + " " + cols,
                  "|" + "---|" * (len(keys) + 11)]
        for s in report[section]:
            if section == "cells" and s["n"] < min_n:
                continue
            clv = "" if s["clv_same_book_mean"] is None else f"{s['clv_same_book_mean']:+.2f} ({s['clv_n']})"
            lines.append("| " + " | ".join(str(s[k]) for k in keys) +
                         f" | {s['n']} | {s['games']} | {s['staked']:.2f} | {s['pnl']:+.2f} | {s['roi_dollar']:+.1f}% |"
                         f" {s['roi_flat']:+.1f}% | {_fmt_ci(s['ci90_flat'])} | {s['win_rate']} | {s['mean_price']} | {clv} | {s['verdict']} |")
        lines.append("")
    lines += ["## Weekly P&L (ISO week of submit)", "", "| week | book | venue | phase | n | staked | pnl | ROI $ |",
              "|---|---|---|---|---|---|---|---|"]
    for w in report["weekly"]:
        lines.append(f"| {w['week']} | {w['book']} | {w['venue']} | {w['phase']} | {w['n']} | {w['staked']:.2f} |"
                     f" {w['pnl']:+.2f} | {w['roi_dollar']}% |")
    return "\n".join(lines)


def fleet_orders() -> list | None:
    """`full_history_orders()`, or None when the live document did not read (#658)."""
    from syndicate.features.shared import execution_ledger
    from syndicate.features.shared.refresh_state_store import read_json_file_result

    ok = read_json_file_result(execution_ledger._ledger_path())[1]
    print(f"live_document_read_ok={ok}", flush=True)
    if ok is not True:
        print("REFUSED: the live ledger document did not read; a count now would be the archive alone (#658)", flush=True)
        return None
    return execution_ledger.full_history_orders()


def cmd_dump(args) -> int:
    orders = fleet_orders()
    if orders is None:
        return 2
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(orders, default=str), encoding="utf-8")
    print(f"rows {len(orders)} newest {max(str(o.get('submitted_at') or '') for o in orders)} -> {args.out}")
    return 0


# NIGHTLY: the `live-cell-scorecard` SCHEDULED_JOBS entry (scripts/local_production.py). Read-only on the
# ledger; writes only <reports root>/intelligence/live_cell_scorecard/. The windows are fixed so nights compare.
NIGHTLY_SUBDIR = Path("intelligence") / "live_cell_scorecard"
NIGHTLY_WINDOWS = (("all", None), ("since_2026-10-20", "2026-10-20"), ("last_7d", 7))
FLAG_SECTIONS = ("headline", "by_family", "cells")


def flags_of(reports: Mapping[str, Mapping[str, Any]]) -> list[dict]:
    """Every scored group whose CI90 excludes 0 (verdict EDGE or LOSES), per window -- the user's revisit list."""
    out = []
    for window, report in reports.items():
        for section in FLAG_SECTIONS:
            for s in report.get(section) or ():
                if s.get("verdict") in ("EDGE", "LOSES"):
                    key = "|".join(str(s[k]) for k in ("book", "venue", "sport", "family", "bucket", "phase") if k in s)
                    out.append({"window": window, "section": section, "key": key, "verdict": s["verdict"],
                                "n": s["n"], "games": s["games"], "roi_flat": s["roi_flat"], "ci90_flat": s["ci90_flat"]})
    return out


def flag_changes(today: list[dict], previous: list[dict] | None) -> dict[str, list[dict]]:
    """Flags that appeared or cleared since the previous night (None = no previous night: all are new)."""
    ident = lambda f: (f["window"], f["section"], f["key"], f["verdict"])
    before = {ident(f) for f in previous or ()}
    now = {ident(f) for f in today}
    return {"new": [f for f in today if ident(f) not in before],
            "cleared": [f for f in previous or () if ident(f) not in now]}


def run_nightly(orders: list[Mapping[str, Any]], out_dir: Path, now: datetime, reps: int = 2000, min_n: int = 5) -> dict:
    from datetime import timedelta

    out_dir.mkdir(parents=True, exist_ok=True)
    reports = {}
    for name, since in NIGHTLY_WINDOWS:
        if isinstance(since, int):
            since = (now - timedelta(days=since)).strftime("%Y-%m-%dT%H:%M:%S")
        reports[name] = build_report(orders, since, None, reps, min_n)
    flags = flags_of(reports)
    previous = None
    earlier = sorted(p for p in out_dir.glob("20*.json") if p.stem < now.date().isoformat())
    if earlier:
        try:
            previous = json.loads(earlier[-1].read_text(encoding="utf-8")).get("flags")
        except (ValueError, OSError):
            previous = None
    summary = {"generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "flags": flags,
               "flag_changes": flag_changes(flags, previous), "previous_file": earlier[-1].name if earlier else None,
               "windows": reports}
    stem = now.date().isoformat()
    (out_dir / f"{stem}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    md = [f"# Live cell scorecard {stem}", "", "## Flags (CI90 excludes 0)", ""]
    md += [f"- {'NEW ' if f in summary['flag_changes']['new'] else ''}{f['verdict']} {f['window']} {f['key']}: "
           f"{f['roi_flat']:+.1f}% {f['ci90_flat']} n {f['n']} games {f['games']}" for f in flags] or ["- none"]
    md += [f"- CLEARED {f['verdict']} {f['window']} {f['key']}" for f in summary["flag_changes"]["cleared"]]
    for name, report in reports.items():
        md += ["", f"# window {name}", markdown(report, min_n)]
    (out_dir / f"{stem}.md").write_text("\n".join(md), encoding="utf-8")
    return summary


def cmd_nightly(args) -> int:
    import os

    try:
        os.nice(19)   # research job: the fleet shares the host with the live workers
    except (AttributeError, OSError):
        pass
    orders = fleet_orders()
    if orders is None:
        return 2
    root = Path(args.reports_root or os.environ.get("SYNDICATE_REPORTS_ROOT") or "reports")
    now = datetime.now(timezone.utc)
    summary = run_nightly(orders, root / NIGHTLY_SUBDIR, now, reps=args.reps)
    changes = summary["flag_changes"]
    print(f"LIVE_CELL_SCORECARD date={now.date().isoformat()} orders={len(orders)} flags={len(summary['flags'])} "
          f"new={len(changes['new'])} cleared={len(changes['cleared'])} out={root / NIGHTLY_SUBDIR}", flush=True)
    for f in changes["new"]:
        print(f"  NEW_FLAG {f['verdict']} {f['window']} {f['key']} roi_flat={f['roi_flat']} ci90={f['ci90_flat']} n={f['n']}", flush=True)
    return 0


def cmd_report(args) -> int:
    raw = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    orders = raw.get("orders", []) if isinstance(raw, Mapping) else raw
    report = build_report(orders, args.since, args.until, args.reps, args.min_n)
    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, indent=1), encoding="utf-8")
    md = markdown(report, args.min_n)
    if args.out_md:
        Path(args.out_md).write_text(md, encoding="utf-8")
    else:
        sys.stdout.write(md + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dump")
    d.add_argument("--out", required=True)
    rp = sub.add_parser("report")
    rp.add_argument("--ledger", required=True)
    rp.add_argument("--since", default=None, help="submitted_at >= this ISO prefix")
    rp.add_argument("--until", default=None, help="submitted_at < this ISO prefix")
    rp.add_argument("--reps", type=int, default=2000)
    rp.add_argument("--min-n", type=int, default=5)
    rp.add_argument("--out-json", default=None)
    rp.add_argument("--out-md", default=None)
    nt = sub.add_parser("nightly", help="fleet: dump + all windows + flags -> <reports root>/intelligence/live_cell_scorecard/")
    nt.add_argument("--reports-root", default=None, help="default: $SYNDICATE_REPORTS_ROOT")
    nt.add_argument("--reps", type=int, default=2000)
    args = parser.parse_args(argv)
    return {"dump": cmd_dump, "report": cmd_report, "nightly": cmd_nightly}[args.cmd](args)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
