#!/usr/bin/env python3
"""Re-score a past date's live-gameline ledger with the CURRENT scorer.

WHY THIS EXISTS. `history.jsonl` stores the board's RETAINED summary for a
date, and a re-capture of a past date re-serves that summary verbatim rather
than recomputing it. So a cut the scorer gained LATER can never appear for an
earlier date, no matter how many times the date is re-captured -- and because
`pool_live_gameline_trend.best_per_date` skips a date whose cut has no brier,
the date does not shrink the pool, it drops out of it silently.

Measured 2026-09-24: 2026-08-30 and 2026-08-31 were the only two dates whose
summaries were computed inside the ~47h window between `75cf9aec`
(2026-08-30 11:59 CDT, added `scored_markets`/`records_by_market`) and
`4d20ea00` (2026-09-01 11:07 CDT, added `fresh_quotes_only`). Their 09-23
re-capture carries `scored_markets` yet `fresh_quote_seconds: None`, which
`live_gameline_score.py` sets UNCONDITIONALLY to a constant -- proof the
scoring function never ran and a stored object was served. The per-record
ledgers, however, carry `quote_age_seconds` on 100% of records (5,904/5,904
and 8,161/8,161); `live_gameline_ledger.py` has stamped it since `7e1d0cac`
(2026-08-15). The data was never missing. Only the summary was too old.

WHAT MAKES A RE-SCORE TRUSTWORTHY, AND WHY THIS REFUSES WITHOUT IT. A
reconstruction is NOT automatically the same measurement as the board's. The
2026-09-08 precedent (`findings_2026-09-08_live_gameline_0904_per_game.md`)
rebuilt 09-04 from the same ledger and got +0.06352 against the board's
+0.07827, because its finals index resolved 15 games where the board had 13.
Direction matched; the number did not.

So this script does not ask to be believed. `--expect-*` names the retained
`all_records` briers and n, and an appended row is REFUSED unless the re-score
reproduces them EXACTLY. That is a strong check: it pins two briers to 5dp and
two row counts simultaneously, on a population the current scorer rebuilt from
raw records. When it passes, the `fresh_quotes_only` block this adds is the
same measurement as the `all_records`/`priceable_only` already in history, not
a lookalike computed on a different set of games.

THE BOARD'S POPULATION IS THE TARGET, NOT THE FULLEST ONE. A late game that
finished after the board's last build of its date is final on StatsAPI today
and was not final for the board then. `--exclude-game-pk` reproduces the
board's set. Measured for 08-31: a leave-one-out search over all 12 StatsAPI
finals found exactly ONE that reproduces the retained figures -- 824314
(BAL @ COL, first pitch 00:1xZ). Scoring the fuller 12-game set instead is
defensible data but it is NOT what every neighbouring date in the series is,
so pooling it would compare populations across dates.

Usage:
    python scripts/rescore_live_gameline_date.py --date 2026-08-30 \
        --expect-model 0.15138 --expect-market 0.18455 --expect-n 618/526

    ... --exclude-game-pk 824314 --append

Exit codes:
    0 ok
    2 ledger fetch/read failed
    3 no expectation given (refuses to append blind)
    4 verification FAILED -- the re-score is not the board's measurement
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from syndicate.features.shared.live_gameline_score import (  # noqa: E402
    finals_from_scores,
    score_ledger_records,
)

HISTORY = REPO / "reports" / "live_gameline_accuracy" / "history.jsonl"
LEDGER_PATH = "mlb_source/data/live_gameline_ledger/live_gameline_ledger_{date}.jsonl"
DEFAULT_BASE = "https://syndicate-an21.onrender.com"
STATSAPI = "https://statsapi.mlb.com/api/v1/schedule?sportId=1&date={date}"


def _admin_token() -> str | None:
    token = os.environ.get("ADMIN_TOKEN")
    if token:
        return token.strip()
    env = REPO / ".env"
    if not env.exists():
        return None
    for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.strip().startswith("ADMIN_TOKEN"):
            _, _, value = line.partition("=")
            return value.strip().strip('"').strip("'")
    return None


def _fetch_ledger(date: str, base: str, dest: Path) -> bytes:
    token = _admin_token()
    if not token:
        raise RuntimeError("no ADMIN_TOKEN in env or .env")
    url = f"{base}/api/ops/artifacts/stream?path=" + LEDGER_PATH.format(date=date)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        raw = resp.read()
    dest.write_bytes(raw)
    return raw


def _final_scores(date: str) -> dict[str, tuple[float, float]]:
    """`game_pk` -> `(away, home)` for games FINAL on StatsAPI.

    Scores here are ints; the LEDGER's own `home_score`/`away_score` are
    strings (`'4'`), which is why the finals index is built from StatsAPI and
    not from the records -- and why an `isinstance(x, int)` split over the
    ledger silently returns n=0. Noted in the 09-08 findings; kept here so the
    next reader does not rediscover it.
    """
    with urllib.request.urlopen(STATSAPI.format(date=date), timeout=60) as resp:
        sched = json.load(resp)
    scores: dict[str, tuple[float, float]] = {}
    for day in sched.get("dates", []):
        for game in day.get("games", []):
            if (game.get("status") or {}).get("abstractGameState") != "Final":
                continue
            teams = game.get("teams") or {}
            away = (teams.get("away") or {}).get("score")
            home = (teams.get("home") or {}).get("score")
            if away is None or home is None:
                continue
            scores[str(game["gamePk"])] = (float(away), float(home))
    return scores


def _scorer_provenance() -> dict[str, str | None]:
    """The exact scorer that produced these numbers, so the row is re-derivable."""
    rel = "syndicate/features/shared/live_gameline_score.py"
    try:
        sha = subprocess.run(
            ["git", "log", "-1", "--format=%H", "--", rel],
            cwd=REPO, capture_output=True, text=True, timeout=30,
        ).stdout.strip() or None
    except Exception:
        sha = None
    digest = hashlib.sha256((REPO / rel).read_bytes()).hexdigest()[:16]
    return {"scorer_file": rel, "scorer_commit": sha, "scorer_sha256_16": digest}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", required=True, help="slate date, zero-padded YYYY-MM-DD")
    ap.add_argument("--sport", default="mlb", help="only mlb is wired (StatsAPI finals)")
    ap.add_argument("--ledger", help="local ledger .jsonl; fetched from production if absent")
    ap.add_argument("--base-url", default=DEFAULT_BASE)
    ap.add_argument("--exclude-game-pk", action="append", default=[],
                    help="game_pk the board did NOT have a final for; repeatable")
    ap.add_argument("--expect-model", type=float, help="retained all_records model brier")
    ap.add_argument("--expect-market", type=float, help="retained all_records market brier")
    ap.add_argument("--expect-n", help="retained all_records n, as MODEL/MARKET")
    ap.add_argument("--append", action="store_true", help="append the verified row to history.jsonl")
    ap.add_argument("--json-out", help="also write the full score object here")
    args = ap.parse_args(argv)

    date = args.date
    scratch = Path(os.environ.get("TEMP", ".")) / "live_gameline_rescore"
    scratch.mkdir(parents=True, exist_ok=True)

    # --- records -------------------------------------------------------
    path = Path(args.ledger) if args.ledger else scratch / f"ledger_{date}.jsonl"
    try:
        if args.ledger or path.exists():
            raw = path.read_bytes()
        else:
            raw = _fetch_ledger(date, args.base_url, path)
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED to obtain ledger for {date}: {exc}", file=sys.stderr)
        return 2
    records = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not records:
        print(f"ledger for {date} is EMPTY ({len(raw)} bytes)", file=sys.stderr)
        return 2

    # --- finals, restricted to the board's population ------------------
    scores = _final_scores(date)
    excluded = [str(g) for g in args.exclude_game_pk]
    kept = {k: v for k, v in scores.items() if k not in excluded}
    missing = [g for g in excluded if g not in scores]

    score = score_ledger_records(records, finals_from_scores(kept), final_scores=kept)

    print(f"=== {date} re-scored by the CURRENT scorer ===")
    print(f"  ledger bytes={len(raw)} records={len(records)} statsapi_finals={len(scores)}"
          f" excluded={excluded or 'none'} scored_games={score['games_with_outcome']}")
    if missing:
        print(f"  WARNING: --exclude-game-pk {missing} not among StatsAPI finals (no effect)")
    for name in ("all_records", "priceable_only", "fresh_quotes_only"):
        block = score.get(name) or {}
        model, market = block.get("model") or {}, block.get("market") or {}
        paired = block.get("model_paired") or {}
        if model.get("brier") is None:
            print(f"  {name:18s} NO DATA")
            continue
        diff = (round(paired["brier"] - market["brier"], 5)
                if paired.get("brier") is not None and market.get("brier") is not None else None)
        print(f"  {name:18s} model={model['brier']} paired={paired.get('brier')}"
              f" market={market.get('brier')} n={model['n']}/{market.get('n')} paired_diff={diff}")
    print(f"  quote_age_absent={score.get('quote_age_absent')}"
          f" fresh_quote_seconds={score.get('fresh_quote_seconds')}")

    # --- verification gate ---------------------------------------------
    if args.expect_model is None or args.expect_market is None or not args.expect_n:
        print("\nNO EXPECTATION: pass --expect-model/--expect-market/--expect-n (the retained\n"
              "all_records figures) so the re-score can be proved to be the board's own\n"
              "measurement. Refusing to append a row nothing checked.", file=sys.stderr)
        return 3

    want_model_n, _, want_market_n = args.expect_n.partition("/")
    got = score["all_records"]
    checks = {
        "model_brier": (got["model"]["brier"], args.expect_model),
        "market_brier": (got["market"]["brier"], args.expect_market),
        "model_n": (got["model"]["n"], int(want_model_n)),
        "market_n": (got["market"]["n"], int(want_market_n)),
    }
    failed = {k: v for k, v in checks.items()
              if (abs(v[0] - v[1]) > 1e-5 if isinstance(v[1], float) else v[0] != v[1])}
    print("\n  VERIFICATION against the retained summary (all_records):")
    for key, (got_v, want_v) in checks.items():
        print(f"    {key:13s} got={got_v} retained={want_v} {'OK' if key not in failed else 'MISMATCH'}")
    if failed:
        print(f"\nVERIFICATION FAILED on {sorted(failed)} -- this re-score is NOT the board's\n"
              "measurement, so its fresh_quotes_only is not poolable with the rest of the\n"
              "series. Find the finals the board actually had (a leave-one-out search over\n"
              "StatsAPI finals identifies a late game the board never saw) before appending.",
              file=sys.stderr)
        return 4
    print("    => EXACT: the current scorer reproduces the retained measurement.")

    # --- the row --------------------------------------------------------
    row = {
        "sport": args.sport,
        "date": date,
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "games_with_outcome": score["games_with_outcome"],
        "records_considered": score.get("records_considered"),
        "scored_markets": score.get("scored_markets"),
        "records_by_market": score.get("records_by_market"),
        "all_records": score.get("all_records"),
        "last_per_game": score.get("last_per_game"),
        "priceable_only": score.get("priceable_only"),
        "fresh_quotes_only": score.get("fresh_quotes_only"),
        "fresh_quote_seconds": score.get("fresh_quote_seconds"),
        "by_quote_age": score.get("by_quote_age"),
        "quote_age_absent": score.get("quote_age_absent"),
        "unscored": score.get("unscored"),
        # --- PROVENANCE. THIS ROW IS NOT A BOARD CAPTURE. ---------------
        # `backfill` already means "re-captured a past date FROM THE BOARD".
        # This row never touched the board's scorer output, so it needs its
        # own word: a reader (or a future pooling rule) must be able to tell
        # a reconstruction from an observation without inferring it from a
        # timestamp. `rescored_from_ledger` is that word, and the verified
        # block below is what earns it.
        "backfill": True,
        "rescored_from_ledger": True,
        "rescore": {
            "reason": "retained summary predates fresh_quotes_only (4d20ea00, 2026-09-01)",
            "ledger_path": LEDGER_PATH.format(date=date),
            "ledger_bytes": len(raw),
            "ledger_sha256_16": hashlib.sha256(raw).hexdigest()[:16],
            "finals_source": "statsapi.mlb.com/api/v1/schedule",
            "statsapi_finals": len(scores),
            "excluded_game_pks": excluded,
            "verified_against_retained": {k: {"got": v[0], "retained": v[1]}
                                          for k, v in checks.items()},
            **_scorer_provenance(),
        },
    }

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(score, indent=2), encoding="utf-8")

    if not args.append:
        print("\n  (--append not given; nothing written)")
        return 0

    # history.jsonl is SHARED and append-only -- other sessions and the
    # snapshot cron write it too. Open in append mode and never rewrite it.
    before = sum(1 for _ in HISTORY.open(encoding="utf-8")) if HISTORY.exists() else 0
    with HISTORY.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")
    after = sum(1 for _ in HISTORY.open(encoding="utf-8"))
    print(f"\n  appended -> {HISTORY}  ({before} -> {after} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
