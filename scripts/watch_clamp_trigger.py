#!/usr/bin/env python3
"""Watch production for a slate that can prove -- or disprove -- the fair-price clamp fix.

WHY THIS EXISTS. `/preflight` on the clamp fix (`7bb74c95`) returned FAIL, and
not because the change was unsafe: it could not be MEASURED. The defect only
becomes observable when the board carries a `fair_probability` outside
[0.02, 0.98], because that is the only input the old
`max(0.02, min(0.98, p))` clamp changed. Two such rows existed on 2026-08-15
(mlb totals, p=0.992056 and 0.007944, published at -4900/+4900 against a correct
-/+12488) and were gone within hours. The slate at preflight time ran
min 0.05846 / max 0.63833 -- nowhere near an edge.

So the trigger is real but transient, and waiting for it by hand does not work.

WHAT MAKES THIS A MEASUREMENT AND NOT AN ALARM. It does not merely say "the
condition occurred". When the condition occurs it takes the confirming read and
classifies production itself:

    PRE_FIX_MISPRICE  an out-of-clamp probability IS published at exactly
                      +/-4900  -> the bug is live, and this record is the
                      evidence the deploy is judged against
    POST_FIX_OK       an out-of-clamp probability prices BEYOND +/-4900, or the
                      column is absent -> the fix is working in production
    no_trigger        no out-of-clamp probability on this slate; nothing is
                      provable either way right now

That third state is the point. A run that reports `no_trigger` is explicitly NOT
evidence of correctness -- it is the instrument saying it cannot see. Recording
that distinction is what stops a healthy-looking reading from being banked as a
pass (`learnings.md`: a healthy reading is evidence only once you know what makes
it read unhealthy).

The verdict is derived from PUBLISHED CONTENT, not from a deployed SHA, so it
needs no API key and cannot be fooled by a deploy that did not carry the fix.

COST. The cheap probe is one unauthenticated GET of the shortlist artifact. The
expensive confirming POST to `/api/intelligence/query` runs ONLY on a trigger,
so a quiet slate costs one small request per interval. The board rebuilds on
roughly a 25-minute cycle, so the 600s default already oversamples it.

Usage:
    python scripts/watch_clamp_trigger.py --once          # single check
    python scripts/watch_clamp_trigger.py                 # poll until triggered
    python scripts/watch_clamp_trigger.py --interval 900 --max-checks 40
    python scripts/watch_clamp_trigger.py --self-test     # exercise the classifier

Exit codes:
    0   ran, no trigger (nothing provable)
    10  TRIGGERED -- read the evidence file; a verdict is available
    1   could not reach production
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

BASE_URL = "https://syndicate-an21.onrender.com"
SHORTLIST_PATH = "/api/board/layer2-shortlist"
QUERY_PATH = "/api/intelligence/query"

# The old clamp. A probability strictly inside this band was never altered by it,
# which is exactly why a slate confined to the band proves nothing.
CLAMP_LOW = 0.02
CLAMP_HIGH = 0.98
# What the clamp emitted at its edges. `american_price(0.98)` is also -4900, so a
# value AT the edge is not by itself proof -- the probability must be OUTSIDE.
CLAMP_PRICE = 4900.0

OUT_DIR = REPO_ROOT / "reports" / "clamp_watch"
LOG_PATH = OUT_DIR / "observations.jsonl"

EXIT_NO_TRIGGER = 0
EXIT_TRIGGERED = 10
EXIT_UNREACHABLE = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(path: str, timeout: int = 120) -> Any:
    with urllib.request.urlopen(BASE_URL + path, timeout=timeout) as response:
        return json.loads(response.read())


def _post(path: str, payload: dict[str, Any], timeout: int = 240) -> Any:
    request = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _fair_probabilities(shortlist: Any) -> list[dict[str, Any]]:
    """Every row's no-vig probability, with enough identity to find it again."""
    out = []
    for row in (shortlist or {}).get("rows") or []:
        quote = row.get("quote") if isinstance(row.get("quote"), dict) else {}
        probability = quote.get("fair_probability")
        if isinstance(probability, (int, float)) and not isinstance(probability, bool):
            out.append({
                "fair_probability": float(probability),
                "sport": row.get("sport"),
                "market": row.get("market"),
                "side": row.get("side"),
                "game": row.get("game"),
            })
    return out


def _walk_fair_prices(node: Any, found: list[float]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "fair_price" and isinstance(value, (int, float)) and not isinstance(value, bool):
                found.append(float(value))
            _walk_fair_prices(value, found)
    elif isinstance(node, list):
        for item in node:
            _walk_fair_prices(item, found)


def _joined_pairs(payload: Any) -> list[tuple[float, float]]:
    """(fair_probability, fair_price) pairs from the served payload.

    Joined on the row rather than compared as two populations -- the whole
    finding rests on knowing WHICH probability produced WHICH price.
    """
    pairs: list[tuple[float, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            price = node.get("fair_price")
            quote = node.get("quote") if isinstance(node.get("quote"), dict) else {}
            probability = node.get("fair_probability")
            if probability is None:
                probability = quote.get("fair_probability")
            if isinstance(price, (int, float)) and isinstance(probability, (int, float)):
                pairs.append((float(probability), float(price)))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return pairs


def correct_price(probability: float) -> float:
    """The unclamped fair price. Same form as `opportunity_signals.american_price`."""
    if probability >= 0.5:
        return -100.0 * probability / (1.0 - probability)
    return 100.0 * (1.0 - probability) / probability


def classify(out_of_clamp: list[dict[str, Any]], pairs: list[tuple[float, float]]) -> dict[str, Any]:
    """Decide what production is doing, from published content alone."""
    at_clamp = [(p, v) for p, v in pairs if abs(v) == CLAMP_PRICE and (p < CLAMP_LOW or p > CLAMP_HIGH)]
    beyond = [(p, v) for p, v in pairs if abs(v) > CLAMP_PRICE]

    if at_clamp:
        verdict = "PRE_FIX_MISPRICE"
        detail = [{
            "fair_probability": round(p, 6),
            "published_fair_price": v,
            "correct_fair_price": round(correct_price(p)),
            "error_points": round(abs(correct_price(p) - v)),
        } for p, v in at_clamp]
    elif beyond:
        verdict = "POST_FIX_OK"
        detail = [{"fair_probability": round(p, 6), "published_fair_price": v} for p, v in beyond]
    else:
        # The probability exists but no price was published for it. The fixed
        # code omits the column rather than faking one, so this is the expected
        # post-fix shape when the probability sits outside (0, 1) handling.
        verdict = "POST_FIX_OK_COLUMN_ABSENT"
        detail = []

    return {
        "verdict": verdict,
        "out_of_clamp_rows": out_of_clamp,
        "evidence": detail,
        "pairs_joined": len(pairs),
    }


def check_once(*, confirm: bool = True) -> dict[str, Any]:
    """One cheap probe; the expensive read only if it can prove something."""
    record: dict[str, Any] = {"checked_at": _now()}
    try:
        shortlist = _get(SHORTLIST_PATH)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        record.update({"status": "unreachable", "error": f"{type(exc).__name__}: {exc}"})
        return record

    rows = _fair_probabilities(shortlist)
    out_of_clamp = [r for r in rows
                    if r["fair_probability"] < CLAMP_LOW or r["fair_probability"] > CLAMP_HIGH]
    probabilities = [r["fair_probability"] for r in rows]
    record.update({
        "status": "ok",
        "shortlist_rows": len(rows),
        "min_fair_probability": round(min(probabilities), 6) if probabilities else None,
        "max_fair_probability": round(max(probabilities), 6) if probabilities else None,
        "out_of_clamp_count": len(out_of_clamp),
    })

    if not out_of_clamp:
        # Stated, not implied: this run proves nothing about the fix.
        record["verdict"] = "no_trigger"
        record["note"] = "no out-of-clamp probability on this slate; NOT evidence of correctness"
        return record

    record["triggered"] = True
    if not confirm:
        record["verdict"] = "TRIGGER_UNCONFIRMED"
        record["note"] = "trigger seen; confirming read skipped (--no-confirm)"
        return record

    try:
        served = _post(QUERY_PATH, {"question": "show me the board"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        # A failed read is not a result. Say so rather than reporting a verdict.
        record["verdict"] = "TRIGGER_UNCONFIRMED"
        record["error"] = f"confirming read failed: {type(exc).__name__}: {exc}"
        return record

    prices: list[float] = []
    _walk_fair_prices(served, prices)
    record["served_fair_price_count"] = len(prices)
    record["served_at_clamp_price"] = sum(1 for v in prices if abs(v) == CLAMP_PRICE)
    record["served_beyond_clamp_price"] = sum(1 for v in prices if abs(v) > CLAMP_PRICE)
    record.update(classify(out_of_clamp, _joined_pairs(served)))
    return record


def _write(record: dict[str, Any]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    if record.get("triggered"):
        stamp = record["checked_at"].replace(":", "").replace("-", "")
        (OUT_DIR / f"trigger_{stamp}.json").write_text(
            json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")


def _summarize(record: dict[str, Any]) -> str:
    if record.get("status") == "unreachable":
        return f"[{record['checked_at']}] UNREACHABLE -- {record.get('error')}"
    head = (f"[{record['checked_at']}] rows={record.get('shortlist_rows')} "
            f"p=[{record.get('min_fair_probability')}, {record.get('max_fair_probability')}] "
            f"out_of_clamp={record.get('out_of_clamp_count')}")
    verdict = record.get("verdict", "?")
    if verdict == "no_trigger":
        return head + "  -> no_trigger (proves nothing)"
    line = head + f"  -> {verdict}"
    for item in record.get("evidence") or []:
        line += (f"\n      p={item['fair_probability']} published={item['published_fair_price']}"
                 + (f" correct={item['correct_fair_price']} off_by={item['error_points']}"
                    if "correct_fair_price" in item else ""))
    return line


def _self_test() -> int:
    """Exercise the classifier on synthetic payloads.

    Production cannot be made to produce a triggering slate on demand, so the
    branch that matters most is the one that would otherwise never run before it
    is needed -- and an untested classifier is worth nothing at the moment it
    finally fires.
    """
    checks: list[tuple[str, str, dict[str, Any]]] = []

    pre = classify([{"fair_probability": 0.992056}], [(0.992056, -4900.0), (0.4, 150.0)])
    checks.append(("out-of-clamp priced AT the clamp", "PRE_FIX_MISPRICE", pre))

    post = classify([{"fair_probability": 0.992056}], [(0.992056, -12488.0), (0.4, 150.0)])
    checks.append(("out-of-clamp priced BEYOND the clamp", "POST_FIX_OK", post))

    absent = classify([{"fair_probability": 0.992056}], [(0.4, 150.0)])
    checks.append(("out-of-clamp with no price published", "POST_FIX_OK_COLUMN_ABSENT", absent))

    # p=0.98 is ON the edge, and `american_price(0.98)` is legitimately -4900.
    # Fixed code produces this, so it must NOT read as a misprice.
    edge = classify([], [(0.98, -4900.0)])
    checks.append(("p exactly AT the edge is legitimately -4900", "POST_FIX_OK_COLUMN_ABSENT", edge))

    failures = 0
    for name, expected, got in checks:
        ok = got["verdict"] == expected
        failures += 0 if ok else 1
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {got['verdict']}"
              + ("" if ok else f" (expected {expected})"))

    arithmetic = round(correct_price(0.992056))
    ok = arithmetic == -12488
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] correct_price(0.992056) = {arithmetic} (expected -12488)")

    print("self-test:", "all passed" if not failures else f"{failures} FAILED")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--once", action="store_true", help="single check, then exit")
    parser.add_argument("--interval", type=int, default=600,
                        help="seconds between checks (default 600; the board rebuilds ~every 25 min)")
    parser.add_argument("--max-checks", type=int, default=0, help="stop after N checks (0 = unlimited)")
    parser.add_argument("--no-confirm", action="store_true",
                        help="skip the expensive confirming read on a trigger")
    parser.add_argument("--self-test", action="store_true", help="exercise the classifier and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    checks = 0
    while True:
        record = check_once(confirm=not args.no_confirm)
        _write(record)
        print(_summarize(record), flush=True)
        checks += 1

        if record.get("triggered"):
            print(f"\nTRIGGERED. Evidence written to {LOG_PATH.parent}", flush=True)
            print("Next: this is the measurement the clamp deploy is judged against.", flush=True)
            print("A PRE_FIX_MISPRICE verdict means the bug is live and the deploy "
                  "now has a discriminating before/after.", flush=True)
            return EXIT_TRIGGERED

        if args.once or (args.max_checks and checks >= args.max_checks):
            return EXIT_UNREACHABLE if record.get("status") == "unreachable" else EXIT_NO_TRIGGER

        time.sleep(max(60, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
