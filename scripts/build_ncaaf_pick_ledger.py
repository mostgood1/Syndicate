"""Stage 0 writer: build/refresh the NCAAF pick ledger from CFBD.

Populates the four quantities `pick_gate`'s exit criterion needs -- model
margin, OPENING line, CLOSING line, realised result -- one row per
(game x provider).

    py -3 scripts/build_ncaaf_pick_ledger.py --season 2025            # backfill
    py -3 scripts/build_ncaaf_pick_ledger.py --season 2026 --week 1   # in-season
    py -3 scripts/build_ncaaf_pick_ledger.py --season 2025 --evaluate-only

IDEMPOTENT. Re-running merges rather than appends, and an opening line already
on file is never rewritten -- see `pick_ledger._merge`. So this is safe to put
on a weekly autorun and safe to re-run by hand after a failure.

RUNS ON THE WORKER, NOT WEB. It fetches from an external API and writes an
artifact; the web service reads precomputed artifacts and does no heavy work.

THE MODEL JOIN IS OPTIONAL, AND DELIBERATELY SO. Market and result rows are
recorded whether or not a projection exists for that game. A ledger that
refused rows without a model would silently under-report exactly the games the
model failed to produce -- which is the population most worth seeing.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from syndicate.features.football.pick_ledger import (  # noqa: E402
    PickLedgerRow,
    coverage,
    evaluate,
    is_leaked_rating_source,
    ledger_path,
    load_ledger,
    upsert,
)

CFBD = "https://api.collegefootballdata.com"


def _token() -> str:
    tok = os.environ.get("CFBD_API_KEY", "").strip()
    if tok:
        return tok
    env = REPO / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.strip().startswith("CFBD_API_KEY"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise RuntimeError(
        "CFBD_API_KEY absent. Set it in the environment or .env -- this script "
        "cannot fabricate market data and must fail loudly rather than write an "
        "empty ledger that looks like 'no games'."
    )


def _get(url: str, token: str):
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + token, "User-Agent": "syndicate/1.0"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read().decode())


def _norm(name: str | None) -> str:
    t = (name or "").strip().lower().replace("state", "st").replace("&", "and")
    t = re.sub(r"[^a-z0-9 ]", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _load_model_projections(season: int) -> dict[tuple[str, str], dict]:
    """Model rows keyed by (home, away), from whatever projection CSVs exist.

    Reads the same artifacts the board serves. Missing files are not an error:
    §the model join is optional by design.
    """
    out: dict[tuple[str, str], dict] = {}
    roots = [
        REPO / "data" / "ncaaf_source" / "data",
        Path(os.environ.get("SYNDICATE_DATA_ROOT", "data")) / "ncaaf_source" / "data",
    ]
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.glob(f"smartsim2_projections_{season}_wk*.csv")):
            if path in seen:
                continue
            seen.add(path)
            try:
                with path.open("r", encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        key = (_norm(row.get("home_team")), _norm(row.get("away_team")))
                        out[key] = row
            except OSError:
                continue
    return out


def _f(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_rows(season: int, week: int | None, token: str) -> list[PickLedgerRow]:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    model = _load_model_projections(season)

    wk = f"&week={week}" if week else ""
    games = _get(f"{CFBD}/games?year={season}&seasonType=regular&classification=fbs{wk}", token)
    lines = _get(f"{CFBD}/lines?year={season}&seasonType=regular{wk}", token)

    by_id: dict[str, dict] = {}
    for g in games:
        gid = str(g.get("id") or "")
        if gid:
            by_id[gid] = g

    rows: list[PickLedgerRow] = []
    for entry in lines:
        gid = str(entry.get("id") or "")
        game = by_id.get(gid)
        if game is None:
            # A line for a game outside the FBS filter. Skip rather than invent
            # a game record for it.
            continue
        home, away = game.get("homeTeam"), game.get("awayTeam")
        hs, as_ = _f(game.get("homePoints")), _f(game.get("awayPoints"))
        if hs is None:
            hs = _f(game.get("homeScore"))
        if as_ is None:
            as_ = _f(game.get("awayScore"))
        realised_margin = (hs - as_) if (hs is not None and as_ is not None) else None
        realised_total = (hs + as_) if (hs is not None and as_ is not None) else None
        m = model.get((_norm(home), _norm(away))) or {}

        for ln in (entry.get("lines") or []):
            rows.append(
                PickLedgerRow(
                    sport="ncaaf",
                    season=int(game.get("season") or season),
                    week=int(game.get("week") or (week or 0)),
                    game_id=gid,
                    home_team=str(home or ""),
                    away_team=str(away or ""),
                    start_date=str(game.get("startDate") or ""),
                    provider=str(ln.get("provider") or ""),
                    spread_open=_f(ln.get("spreadOpen")),
                    spread_close=_f(ln.get("spread")),
                    total_open=_f(ln.get("overUnderOpen")),
                    total_close=_f(ln.get("overUnder")),
                    home_moneyline=_f(ln.get("homeMoneyline")),
                    away_moneyline=_f(ln.get("awayMoneyline")),
                    model_margin=_f(m.get("margin_mean")),
                    model_total=_f(m.get("total_mean")),
                    model_home_win_prob=_f(m.get("home_win_rate")),
                    model_margin_stdev=_f(m.get("margin_stdev")),
                    rating_source=str(m.get("rating_source") or ""),
                    model_generated_at=str(m.get("generated_at") or ""),
                    home_score=hs,
                    away_score=as_,
                    realised_margin=realised_margin,
                    realised_total=realised_total,
                    captured_at=now,
                )
            )
    return rows


def _report(rows) -> None:
    cov = coverage(rows)
    print("\n--- COVERAGE (denominators, not just counts) ---")
    for k in ("rows", "games", "with_model", "with_spread_close", "with_spread_open",
              "open_missing", "with_result", "gradable_vs_close", "gradable_vs_open"):
        print(f"  {k:22s} {cov.get(k)}")
    print(f"  providers              {', '.join(cov.get('providers') or []) or '-'}")

    ev = evaluate(rows)

    warn = ev.get("leak_warning")
    if warn:
        print("\n" + "!" * 70)
        print("LEAKED RATING SOURCE IN GRADED ROWS")
        print(warn["message"])
        print("!" * 70)

    for label in ("vs_close", "vs_open"):
        r = ev[label]
        print(f"\n--- MODEL {label.replace('_', ' ').upper()} ---")
        if r.get("verdict") == "INSUFFICIENT":
            print(f"  n={r['n']} -- INSUFFICIENT to judge")
            continue
        print(f"  n={r['n']}  model MAE {r['model_mae']:.3f}  market MAE {r['market_mae']:.3f}")
        print(f"  paired dMAE {r['delta_mae']:+.3f}  SE {r['se']:.3f}  t {r['t']:+.2f}  -> {r['verdict']}")
        for prov, pr in (r.get("by_provider") or {}).items():
            if pr.get("verdict") == "INSUFFICIENT":
                continue
            print(f"     {prov:14s} n={pr['n']:4d}  dMAE {pr['delta_mae']:+.3f}  t {pr['t']:+.2f}  {pr['verdict']}")
        by_src = r.get("by_rating_source") or {}
        if by_src:
            print("   by rating source (NEVER pool leaked with clean):")
            for src, sr in by_src.items():
                if sr.get("verdict") == "INSUFFICIENT":
                    continue
                tag = " [LEAKED]" if is_leaked_rating_source(src) else ""
                print(f"     {src:24s} n={sr['n']:4d}  dMAE {sr['delta_mae']:+.3f}  "
                      f"t {sr['t']:+.2f}  {sr['verdict']}{tag}")
    print(
        "\nA market may reopen in pick_gate._SERVING_REGISTRY only on "
        "MODEL_BETTER vs_close, out-of-sample.\nTIED is not enough: tied on "
        "average, minus the vig, still loses."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, required=True)
    ap.add_argument("--week", type=int, default=None, help="Omit to do the whole season.")
    ap.add_argument("--root", type=str, default=None, help="Ledger root (defaults to SYNDICATE_DATA_ROOT or data/).")
    ap.add_argument("--evaluate-only", action="store_true", help="Read the ledger and grade it; fetch nothing.")
    ap.add_argument("--dry-run", action="store_true", help="Fetch and report; do not write.")
    args = ap.parse_args()

    path = ledger_path("ncaaf", args.season, root=args.root)

    if args.evaluate_only:
        rows = load_ledger("ncaaf", args.season, root=args.root)
        print(f"ledger: {path}  ({len(rows)} rows)")
        if not rows:
            print("EMPTY -- run without --evaluate-only first.")
            return 1
        _report(rows)
        return 0

    rows = build_rows(args.season, args.week, _token())
    print(f"built {len(rows)} (game x provider) rows for {args.season}"
          + (f" week {args.week}" if args.week else " (full season)"))
    if args.dry_run:
        print("DRY RUN -- not written")
        _report(rows)
        return 0

    counts = upsert("ncaaf", args.season, rows, root=args.root)
    print(f"ledger: {path}")
    print(f"  added {counts['added']}  updated {counts['updated']}  "
          f"unchanged {counts['unchanged']}  total {counts['total']}")
    _report(load_ledger("ncaaf", args.season, root=args.root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
