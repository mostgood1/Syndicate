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

WHAT THE TRIGGER READS, AND WHY IT CHANGED (2026-08-16). The trigger comes from
the SERVED payload -- the same surface the verdict judges. It used to come from
`/api/board/layer2-shortlist`, which gated whether the confirming read ran at
all, and that was wrong in a way that mattered: the shortlist is a filtered
view. It drops `stale_kickoff_seconds` (7200 -- any game started more than two
hours ago) and `max_quote_age_seconds`, which is precisely the in-play late-game
population every trigger this instrument has caught came from. Measured at
03:14:08Z on 2026-08-16, same instant: shortlist 0 rows, served payload 18
priced rows, 8345 opportunities considered and all 8345 filtered out. A gate
reading 0 against a judged surface of 18 reports `no_trigger` while it is simply
blind. The shortlist is still recorded as context and can no longer suppress a
check.

COST. One unauthenticated GET (shortlist context) plus one POST to
`/api/intelligence/query` per check -- the POST now runs every time rather than
only on a trigger, which is the price of not being blind. The board rebuilds on
roughly a 25-minute cycle, so the 600s default already oversamples it; a quiet
slate re-reads the same artifact and cannot produce new information.

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


def _served_rows(payload: Any) -> list[dict[str, Any]]:
    """Every `fair_probability` in the served payload, with identity and its price.

    `fair_price` is populated ONLY when it is CO-LOCATED on the same node as the
    probability, and is `None` otherwise. That distinction carries a verdict:
    a probability with no price is the post-fix shape (the fixed code omits the
    column rather than faking one), so it must be visible, not silently dropped.

    Identity is inherited downward; the NUMBERS never are. Inheriting a
    probability the way identity is inherited would happily pair it with an
    unrelated nested price and invent a misprice.

    Returns OCCURRENCES, not rows. The served payload echoes the same logical row
    into several sections, so one mispriced market can appear a dozen times.
    `_dedupe` collapses them; both counts are reported, because they answer
    different questions and only one of them is a count of broken markets.
    """
    rows: list[dict[str, Any]] = []
    # A `quote` node is read from its PARENT (where the co-located price lives)
    # and then walked into again by the recursion. Without this, every quoted row
    # emits twice -- once priced at the parent, once unpriced at the quote node --
    # and each correctly-priced row grows a phantom unpriced twin. Invisible
    # while only pairs were emitted; a double-count the moment they are not.
    consumed: set[int] = set()

    def walk(node: Any, identity: dict[str, Any]) -> None:
        if isinstance(node, dict):
            # Identity is inherited downward: `fair_price` often sits on a nested
            # node that carries no sport/market of its own.
            here = dict(identity)
            for field in ("sport", "market", "side"):
                if isinstance(node.get(field), str):
                    here[field] = node[field]
            game = node.get("game")
            if isinstance(game, dict) and isinstance(game.get("matchup"), str):
                here["matchup"] = game["matchup"]

            price = node.get("fair_price")
            quote = node.get("quote") if isinstance(node.get("quote"), dict) else {}
            probability = node.get("fair_probability")
            if probability is None and "fair_probability" in quote:
                probability = quote.get("fair_probability")
                consumed.add(id(quote))
            if isinstance(probability, (int, float)) and not isinstance(probability, bool) \
                    and id(node) not in consumed:
                priced = isinstance(price, (int, float)) and not isinstance(price, bool)
                rows.append({**here,
                             "fair_probability": float(probability),
                             "fair_price": float(price) if priced else None})
            for value in node.values():
                walk(value, here)
        elif isinstance(node, list):
            for item in node:
                walk(item, identity)

    walk(payload, {})
    return rows


def _joined_pairs(payload: Any) -> list[dict[str, Any]]:
    """The subset of `_served_rows` that actually carries a price.

    Joined on the row rather than compared as two populations -- the whole
    finding rests on knowing WHICH probability produced WHICH price.
    """
    return [row for row in _served_rows(payload) if row["fair_price"] is not None]


def _row_key(entry: dict[str, Any]) -> tuple:
    """Identity of a logical market row.

    Includes the identity fields so two genuinely different markets that happen
    to share a price are NOT collapsed into one -- the failure mode that would
    turn an under-count into a claim of correctness.
    """
    return (
        round(entry["fair_probability"], 9),
        entry["fair_price"],
        entry.get("sport"),
        entry.get("market"),
        entry.get("side"),
        entry.get("matchup"),
    )


def _dedupe(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse repeated occurrences of one row, keeping the repeat count."""
    seen: dict[tuple, dict[str, Any]] = {}
    for entry in entries:
        key = _row_key(entry)
        if key in seen:
            seen[key]["occurrences"] += 1
        else:
            seen[key] = {**entry, "occurrences": 1}
    return list(seen.values())


def correct_price(probability: float) -> float:
    """The unclamped fair price. Same form as `opportunity_signals.american_price`."""
    if probability >= 0.5:
        return -100.0 * probability / (1.0 - probability)
    return 100.0 * (1.0 - probability) / probability


def classify(out_of_clamp: list[dict[str, Any]], pairs: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide what production is doing, from published content alone.

    `pairs` are OCCURRENCES; the evidence array is DEDUPED to logical rows, so a
    reader cannot mistake one repeated market for a dozen broken ones.
    """
    at_clamp = _dedupe([e for e in pairs
                        if abs(e["fair_price"]) == CLAMP_PRICE
                        and (e["fair_probability"] < CLAMP_LOW or e["fair_probability"] > CLAMP_HIGH)])
    beyond = _dedupe([e for e in pairs if abs(e["fair_price"]) > CLAMP_PRICE])

    def _identity(entry: dict[str, Any]) -> dict[str, Any]:
        return {k: entry[k] for k in ("sport", "market", "side", "matchup") if entry.get(k)}

    if at_clamp:
        verdict = "PRE_FIX_MISPRICE"
        detail = [{
            **_identity(e),
            "fair_probability": round(e["fair_probability"], 6),
            "published_fair_price": e["fair_price"],
            "correct_fair_price": round(correct_price(e["fair_probability"])),
            "error_points": round(abs(correct_price(e["fair_probability"]) - e["fair_price"])),
            "occurrences_in_payload": e["occurrences"],
        } for e in at_clamp]
    elif beyond:
        verdict = "POST_FIX_OK"
        detail = [{
            **_identity(e),
            "fair_probability": round(e["fair_probability"], 6),
            "published_fair_price": e["fair_price"],
            "occurrences_in_payload": e["occurrences"],
        } for e in beyond]
    else:
        # The probability exists but no price was published for it. The fixed
        # code omits the column rather than faking one, so this is the expected
        # post-fix shape when the probability sits outside (0, 1) handling.
        verdict = "POST_FIX_OK_COLUMN_ABSENT"
        detail = []

    return {
        "verdict": verdict,
        "out_of_clamp_rows": out_of_clamp,
        # DEDUPED to logical rows. `occurrences_in_payload` on each entry is how
        # many times the served payload echoed it.
        "evidence": detail,
        "evidence_rows": len(detail),
        "pairs_joined_occurrences": len(pairs),
        "pairs_joined_rows": len(_dedupe(pairs)),
        "mispriced_rows": len(at_clamp),
    }


def check_once() -> dict[str, Any]:
    """Read the surface that actually publishes prices, and judge THAT.

    WHY THIS IS NOT GATED ON THE SHORTLIST ANY MORE. It used to be: the cheap
    shortlist GET decided whether the expensive read ran at all. That made the
    instrument blind in exactly the window it exists to watch. The shortlist is
    a heavily FILTERED view -- it drops `stale_kickoff_seconds` (7200: any game
    started more than two hours ago) and `max_quote_age_seconds` -- and the
    triggers this instrument has actually caught came from IN-PLAY markets late
    in games, which is precisely the population those filters remove.

    Measured 2026-08-16T03:14:08Z, same instant: the shortlist offered 0 rows
    while the served payload published 18 priced rows. A gate reading 0 against
    a judged surface of 18 reports `no_trigger` while it simply cannot see. It
    is the shape `learnings.md` warns about -- a healthy reading is evidence
    only once you know what makes it read unhealthy.

    So the trigger is now derived from the served payload itself: the same
    population the verdict is about. The shortlist is still read, but ONLY as
    recorded context, and it can no longer suppress a check.
    """
    record: dict[str, Any] = {"checked_at": _now()}

    # Context, not a gate. A failure here must not stop the real read, so the
    # divergence stays visible without ever being load-bearing.
    try:
        shortlist = _get(SHORTLIST_PATH)
        shortlist_rows = _fair_probabilities(shortlist)
        record["shortlist_rows"] = len(shortlist_rows)
        record["shortlist_out_of_clamp_count"] = sum(
            1 for r in shortlist_rows
            if r["fair_probability"] < CLAMP_LOW or r["fair_probability"] > CLAMP_HIGH)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        record["shortlist_rows"] = None
        record["shortlist_error"] = f"{type(exc).__name__}: {exc}"

    try:
        served = _post(QUERY_PATH, {"question": "show me the board"})
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
        # A failed read is not a result. Say so rather than reporting a verdict.
        record.update({"status": "unreachable",
                       "verdict": "TRIGGER_UNCONFIRMED",
                       "error": f"served read failed: {type(exc).__name__}: {exc}"})
        return record

    rows = _served_rows(served)
    out_of_clamp = _dedupe([r for r in rows
                            if r["fair_probability"] < CLAMP_LOW
                            or r["fair_probability"] > CLAMP_HIGH])
    probabilities = [r["fair_probability"] for r in rows]
    record.update({
        "status": "ok",
        "served_probability_occurrences": len(rows),
        "served_probability_rows": len(_dedupe(rows)),
        "min_fair_probability": round(min(probabilities), 6) if probabilities else None,
        "max_fair_probability": round(max(probabilities), 6) if probabilities else None,
        "out_of_clamp_count": len(out_of_clamp),
    })

    if not out_of_clamp:
        # Stated, not implied: this run proves nothing about the fix.
        record["verdict"] = "no_trigger"
        record["note"] = ("no out-of-clamp probability published on this slate; "
                          "NOT evidence of correctness")
        return record

    record["triggered"] = True
    prices: list[float] = []
    _walk_fair_prices(served, prices)
    # OCCURRENCE counts -- the payload echoes one row into several sections, so
    # these are NOT counts of broken markets. The `_rows` figures in classify()
    # are. Named explicitly because the old `served_at_clamp_price` read like a
    # row count and was quoted as one.
    record["served_fair_price_occurrences"] = len(prices)
    record["served_at_clamp_price_occurrences"] = sum(1 for v in prices if abs(v) == CLAMP_PRICE)
    record["served_beyond_clamp_price_occurrences"] = sum(1 for v in prices if abs(v) > CLAMP_PRICE)
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
    # Both populations are printed because their divergence is the defect this
    # instrument was rebuilt around. `served` is what the verdict is about;
    # `shortlist` is context and never gates anything.
    head = (f"[{record['checked_at']}] served_rows={record.get('served_probability_rows')} "
            f"(shortlist={record.get('shortlist_rows')}) "
            f"p=[{record.get('min_fair_probability')}, {record.get('max_fair_probability')}] "
            f"out_of_clamp={record.get('out_of_clamp_count')}")
    verdict = record.get("verdict", "?")
    if verdict == "no_trigger":
        return head + "  -> no_trigger (proves nothing)"
    line = head + f"  -> {verdict}"
    rows = record.get("evidence_rows")
    if rows is not None:
        line += (f" ({rows} distinct row(s); "
                 f"{record.get('served_at_clamp_price_occurrences', 0)} clamp-priced "
                 f"occurrences of {record.get('served_fair_price_occurrences', 0)})")
    for item in record.get("evidence") or []:
        who = " ".join(str(item[k]) for k in ("sport", "market", "side", "matchup") if item.get(k))
        line += (f"\n      {who}  p={item['fair_probability']} published={item['published_fair_price']}"
                 + (f" correct={item['correct_fair_price']} off_by={item['error_points']}"
                    if "correct_fair_price" in item else "")
                 + f"  (x{item.get('occurrences_in_payload', 1)} in payload)")
    return line


def _self_test() -> int:
    """Exercise the classifier on synthetic payloads.

    Production cannot be made to produce a triggering slate on demand, so the
    branch that matters most is the one that would otherwise never run before it
    is needed -- and an untested classifier is worth nothing at the moment it
    finally fires.
    """
    def pair(p: float, v: float, **identity: Any) -> dict[str, Any]:
        return {"fair_probability": p, "fair_price": v, **identity}

    checks: list[tuple[str, str, dict[str, Any]]] = []

    pre = classify([{"fair_probability": 0.992056}], [pair(0.992056, -4900.0), pair(0.4, 150.0)])
    checks.append(("out-of-clamp priced AT the clamp", "PRE_FIX_MISPRICE", pre))

    post = classify([{"fair_probability": 0.992056}], [pair(0.992056, -12488.0), pair(0.4, 150.0)])
    checks.append(("out-of-clamp priced BEYOND the clamp", "POST_FIX_OK", post))

    absent = classify([{"fair_probability": 0.992056}], [pair(0.4, 150.0)])
    checks.append(("out-of-clamp with no price published", "POST_FIX_OK_COLUMN_ABSENT", absent))

    # p=0.98 is ON the edge, and `american_price(0.98)` is legitimately -4900.
    # Fixed code produces this, so it must NOT read as a misprice.
    edge = classify([], [pair(0.98, -4900.0)])
    checks.append(("p exactly AT the edge is legitimately -4900", "POST_FIX_OK_COLUMN_ABSENT", edge))

    failures = 0

    # --- dedupe, the bug this section exists to prevent recurring ---------
    # One row echoed 14 times through the payload must read as ONE broken market.
    echoed = classify(
        [{"fair_probability": 0.007934}],
        [pair(0.007934, 4900.0, sport="nfl", market="h2h_3_way", side="away", matchup="JAX @ NO")] * 14
        + [pair(0.4, 150.0, sport="mlb", market="totals", side="over", matchup="A @ B")],
    )
    ok = echoed["evidence_rows"] == 1 and echoed["mispriced_rows"] == 1 \
        and echoed["evidence"][0]["occurrences_in_payload"] == 14 \
        and echoed["pairs_joined_occurrences"] == 15 and echoed["pairs_joined_rows"] == 2
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] one row echoed 14x reads as 1 row, 14 occurrences: "
          f"rows={echoed['evidence_rows']} mispriced={echoed['mispriced_rows']} "
          f"occ={echoed['evidence'][0]['occurrences_in_payload'] if echoed['evidence'] else None} "
          f"joined={echoed['pairs_joined_occurrences']}/{echoed['pairs_joined_rows']}")

    # The opposite error, and the dangerous one: two DIFFERENT markets that
    # happen to share a price must NOT collapse into one, or a real misprice
    # disappears into a dedupe and the instrument under-reports.
    distinct = classify(
        [{"fair_probability": 0.007934}],
        [pair(0.007934, 4900.0, sport="nfl", market="h2h_3_way", side="away", matchup="JAX @ NO"),
         pair(0.007934, 4900.0, sport="nfl", market="h2h_3_way", side="away", matchup="KC @ DEN")],
    )
    ok = distinct["mispriced_rows"] == 2
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] two different games at the same price stay 2 rows: "
          f"{distinct['mispriced_rows']}")

    # A pair requires the price and the probability to be CO-LOCATED on one
    # node (`fair_price` beside `fair_probability`, or beside `quote`). That is
    # deliberate and conservative: inheriting a probability downward the way
    # identity is inherited would happily pair it with an unrelated nested
    # price and invent a misprice. Identity is safe to inherit; the numbers are
    # not.
    real_shape = _joined_pairs({"structured_response": {"top_opportunities": [
        {"sport": "nfl", "market": "h2h_3_way", "side": "away",
         "game": {"matchup": "JAX @ NO"},
         "quote": {"fair_probability": 0.007934},
         "fair_price": 4900.0}]}})
    ok = (len(real_shape) == 1 and real_shape[0].get("sport") == "nfl"
          and real_shape[0].get("matchup") == "JAX @ NO"
          and real_shape[0]["fair_price"] == 4900.0)
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] identity is captured on a real-shaped row: "
          f"{ {k: v for k, v in (real_shape[0] if real_shape else {}).items() if k != 'fair_probability'} }")

    # The conservative half, asserted so nobody 'fixes' it into inheriting:
    # price and probability on SEPARATE sibling nodes must yield NO pair.
    split = _joined_pairs({"row": {"quote": {"fair_probability": 0.007934},
                                   "card": {"fair_price": 4900.0}}})
    ok = len(split) == 0
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] a split price/probability yields NO invented pair: "
          f"{len(split)} pair(s)")

    # --- the trigger population, which is what changed on 2026-08-16 ---------
    # An UNPRICED out-of-clamp probability must still reach the trigger. It is
    # the post-fix shape (the fixed code omits the column rather than faking a
    # price), so dropping it would make POST_FIX_OK_COLUMN_ABSENT unreachable
    # and the instrument would go blind to the fix working.
    unpriced = _served_rows({"structured_response": {"top_opportunities": [
        {"sport": "nfl", "market": "h2h_3_way", "side": "away",
         "game": {"matchup": "JAX @ NO"},
         "quote": {"fair_probability": 0.007934}}]}})
    ok = (len(unpriced) == 1 and unpriced[0]["fair_price"] is None
          and unpriced[0]["fair_probability"] < CLAMP_LOW
          and unpriced[0].get("matchup") == "JAX @ NO")
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] an UNPRICED out-of-clamp probability still triggers: "
          f"rows={len(unpriced)} price={unpriced[0]['fair_price'] if unpriced else '?'}")

    # And the trigger must not fire on a slate confined to the band, or every
    # quiet night becomes a spurious verdict.
    inside = _served_rows({"rows": [{"quote": {"fair_probability": 0.4}, "fair_price": 150.0},
                                    {"quote": {"fair_probability": 0.63}, "fair_price": -170.0}]})
    triggered = [r for r in inside
                 if r["fair_probability"] < CLAMP_LOW or r["fair_probability"] > CLAMP_HIGH]
    ok = len(inside) == 2 and not triggered
    failures += 0 if ok else 1
    print(f"  [{'PASS' if ok else 'FAIL'}] a slate inside the band does NOT trigger: "
          f"rows={len(inside)} triggering={len(triggered)}")

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
    parser.add_argument("--self-test", action="store_true", help="exercise the classifier and exit")
    args = parser.parse_args(argv)

    if args.self_test:
        return _self_test()

    checks = 0
    while True:
        record = check_once()
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
