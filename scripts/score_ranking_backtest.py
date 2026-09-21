"""Does the Layer 2 `score` rank winners?  Grade the priced population ROW BY ROW, keep the score.

Lane `layer2-score-outcome-calibration`, user request 2026-09-21: "assess the layer 2 board
scoring model ... ensure the top ranked opps are performing at a high hit rate".

WHY THIS EXISTS BESIDE `bucket_search.py`. The scorecard grades the recorder
(`opportunity_population_ledger`) into per-GAME accumulators keyed by bucket, and its graded
rows drop the fields the RANKING is made of -- `sc`, `ev`, `vp`, `bq`, `ba`, `fm`, `ln`. So
"does a higher score win more" cannot be read off it. This grades the same records with the
same code (`bucket_search.grade_population`, the MLB prop grader, the production extra
settlers) one record at a time, so every graded row keeps its record beside its outcome.

Nothing here re-derives a result: `grade_population` decides win / loss / push and why a row
is ungradable, exactly as the nightly cron does. Read-only against production (web's disk via
`/api/ops/artifacts/stream`, the public scoreboard).

    py -3 scripts/score_ranking_backtest.py pull --start 2026-09-14 --end 2026-09-20 --out C:/tmp/l2score/graded.jsonl
    py -3 scripts/score_ranking_backtest.py analyze --graded C:/tmp/l2score/graded.jsonl
"""

from __future__ import annotations

import argparse
import collections
import functools
import importlib.util
import json
import math
import random
import sys
import tempfile
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import measured_bucket_skill as mbs  # noqa: E402
from syndicate.features.shared import model_scorecard as msc  # noqa: E402
from syndicate.features.shared.opportunity_population_ledger import parse_population_key  # noqa: E402

EXCHANGE_BOOKS = frozenset({"prophetx", "novig", "kalshi", "polymarket", "sporttrade", "betfair_ex_uk", "matchbook"})
SEED = 20260921


def _load_publisher() -> Any:
    source = REPO_ROOT / "scripts" / "publish_model_scorecard.py"
    spec = importlib.util.spec_from_file_location("publish_model_scorecard", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _days(start: str, end: str) -> list[str]:
    first, last = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def market_family(market: str, is_prop: bool) -> str:
    """game_main / game_alt / prop / other -- the unit the ranking question is asked in."""
    market = str(market or "").lower()
    if is_prop:
        return "prop"
    if market.endswith("_alt") or market.startswith("alternate_"):
        return "game_alt"
    if market in ("h2h", "h2h_3_way", "spreads", "totals"):
        return "game_main"
    return "game_other"


def earliest_per_phase(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """`grade_population`'s own selection rule: the earliest sighting per (sport, key, phase)."""
    chosen: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for record in records:
        key = (str(record.get("sport") or "").strip().lower(), str(record.get("k") or ""),
               mbs._phase(record.get("gs"), sighted_at=record.get("t"), commence_time=record.get("ct")))
        if not key[1]:
            continue
        held = chosen.get(key)
        if held is None or str(record.get("t") or "") < str(held.get("t") or ""):
            chosen[key] = record
    return list(chosen.values())


def graded_row(record: Mapping[str, Any], graded: Mapping[str, Any]) -> dict[str, Any]:
    identity = parse_population_key(str(record.get("k") or "")) or {}
    is_prop = bool(identity.get("player_name"))
    view = mbs.view_from_record(record)
    return {
        "date": graded.get("date"),
        "sport": graded.get("sport"),
        "game": graded.get("game"),
        "market": identity.get("market"),
        "family": market_family(identity.get("market"), is_prop),
        "segment": view.get("segment"),
        "phase": view.get("phase"),
        "side": identity.get("side"),
        "line": identity.get("line"),
        "player": identity.get("player_name") or None,
        "t": record.get("t"),
        "y": graded.get("y"),
        "pnl": graded.get("pnl"),
        "px": _num(record.get("px")),
        "fp": _num(record.get("fp")),
        "fm": record.get("fm"),
        "bq": _num(record.get("bq")),
        "ba": _num(record.get("ba")),
        "ev": _num(record.get("ev")),
        "me": _num(record.get("me")),
        "eb": record.get("eb"),
        "sc": _num(record.get("sc")),
        "vp": _num(record.get("vp")),
        "sr": _num(record.get("sr")),
        "ss": record.get("ss"),
        "vc": record.get("vc"),
        "ln": record.get("ln"),
        "gs": record.get("gs"),
        "la": record.get("la"),
        # Openings-only extras (`pull-openings`): the recorder stores no bookmaker.
        "bk": record.get("bk"),
        "bp": record.get("bp"),
        "qsa": _num(record.get("qsa")),
        "fab": record.get("fab"),
        "src": record.get("src") or "recorder",
    }


def grade_rows(
    records: Sequence[Mapping[str, Any]],
    *,
    grade: Callable[..., tuple[list[dict[str, Any]], dict[str, int]]],
    chips_for: Callable[[str], Sequence[Mapping[str, Any]] | None],
    central_date: Callable[[Any], str | None],
    today: str,
) -> tuple[list[dict[str, Any]], collections.Counter]:
    """Grade each earliest-per-phase record ALONE, so the graded row can carry its record.

    Team names are lent across sightings of one event first, as `grade_population` does
    within a batch -- a lone record cannot borrow them from a sibling otherwise.
    """
    named: dict[tuple[str, str], tuple[str, str]] = {}
    for record in records:
        identity = parse_population_key(str(record.get("k") or ""))
        if identity and record.get("ht") and record.get("at"):
            named.setdefault((str(record.get("sport") or "").lower(), identity["event_id"]),
                             (record["ht"], record["at"]))
    out: list[dict[str, Any]] = []
    reasons: collections.Counter = collections.Counter()
    chips_cache: dict[str, Sequence[Mapping[str, Any]] | None] = {}
    for record in earliest_per_phase(records):
        kickoff = central_date(record.get("ct"))
        if kickoff is None:
            reasons["no_kickoff"] += 1
            continue
        if kickoff >= today:
            reasons["not_yet"] += 1
            continue
        if kickoff not in chips_cache:
            try:
                chips_cache[kickoff] = list(chips_for(kickoff) or [])
            except Exception as exc:  # a scoreboard we could not read is not an empty one
                print(f"CHIPS_UNAVAILABLE {kickoff} {type(exc).__name__}: {exc}", flush=True)
                chips_cache[kickoff] = None
        if chips_cache[kickoff] is None:
            reasons["chips_unavailable"] += 1
            continue
        graded, ungraded = grade([record], {kickoff: chips_cache[kickoff]}, named, today=today)
        if not graded:
            for reason, n in ungraded.items():
                reasons[reason] += n
            continue
        reasons["graded"] += 1
        out.append(graded_row(record, graded[0]))
    return out, reasons


def _cached_text(reader: Any, cache: Path, relative: str, subdir: str) -> str | None:
    local = cache / subdir / Path(relative).name
    if local.exists():
        return local.read_text(encoding="utf-8")
    text = reader.text(relative)
    if text is None:
        return None
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(text, encoding="utf-8")
    return text


def opening_to_record(bs: Any, opening: Mapping[str, Any]) -> dict[str, Any] | None:
    """A PUBLISHED opening as a population record, through the recorder's own builders
    (`bucket_search.records_from_openings`), plus the fields only the openings ledger has."""
    built = bs.records_from_openings([opening])
    if not built:
        return None
    record = dict(built[0])
    record.update({
        "bk": opening.get("bookmaker"),
        "bp": opening.get("book_prices"),
        "qsa": opening.get("quote_seen_age_seconds"),
        "fab": opening.get("fair_anchor_book"),
        "src": "openings",
    })
    return record


def stable_chip_index(original: Callable[[Sequence[Mapping[str, Any]]], Any]) -> Callable[..., Any]:
    """`index_chips`, memoised on the chip OBJECTS rather than the list that carries them.

    NOT id(chips): `grade_population` passes `list(chips)`, a fresh temporary per call, so an
    id() key both grew without bound (8.9 GB, measured 2026-09-21) and -- once a temporary was
    freed and its id reused -- could hand back ANOTHER DAY's scoreboard, which in a playoff
    series is the same two teams with a different final. The chip dicts themselves are kept
    alive for the whole run by the per-day cache, so their ids are stable.
    """
    cache: dict[tuple[int, int, int], Any] = {}

    def cached(chips: Sequence[Mapping[str, Any]]) -> Any:
        if not chips:
            return original(chips)
        key = (len(chips), id(chips[0]), id(chips[-1]))
        if key not in cache:
            cache[key] = original(chips)
        return cache[key]

    cached.cache = cache  # type: ignore[attr-defined]
    return cached


def cmd_pull(args: argparse.Namespace) -> int:
    pub = _load_publisher()
    bs = msc.load_bucket_search()
    token = pub.admin_token()
    if not token:
        print("REFUSING: no ADMIN_TOKEN", flush=True)
        return 2
    reader = pub.WebReader(pub.base_url(), token)
    cache = Path(args.cache or tempfile.mkdtemp(prefix="score_backtest_"))
    cache.mkdir(parents=True, exist_ok=True)
    sports = [s.strip() for s in args.sports.split(",") if s.strip()]
    records: list[dict[str, Any]] = []
    for day in _days(args.start, args.end):
        if args.source == "openings":
            relative = bs.OPENINGS_PATH_TEMPLATE.format(date=day)
            text = _cached_text(reader, cache, relative, "openings")
            got = [r for r in (opening_to_record(bs, o) for o in bs.parse_openings_text(text or "")) if r]
            got = [r for r in got if str(r.get("sport") or "").lower() in sports]
            records.extend(got)
            print(f"OPENINGS {relative} records={len(got)}", flush=True)
            continue
        for sport in sports:
            for part in range(bs.MAX_PARTS):
                relative = f"reports/intelligence/{bs.POPULATION_SUBDIR}/{day}__{sport}__part{part:03d}.jsonl"
                text = _cached_text(reader, cache, relative, "parts")
                if text is None:
                    break
                got = bs.parse_records_text(text)
                records.extend(got)
                print(f"PART {relative} records={len(got)}", flush=True)
    print(f"RECORDS {len(records)} from {args.start}..{args.end} sports={sports} source={args.source}", flush=True)

    from syndicate.features.mlb.prop_outcomes import MlbPropGrader
    from syndicate.features.shared.population_outcomes import build_extra_settler

    mlb = MlbPropGrader(cache_dir=cache / "statsapi")
    settler = build_extra_settler(cache_dir=cache / "settlers", fetch_export=reader.text)

    bs.SCORECARD.index_chips = stable_chip_index(bs.SCORECARD.index_chips)

    def chips_for(day: str) -> list[Any]:
        local = cache / "chips" / f"{day}.json"
        if local.exists():
            return json.loads(local.read_text(encoding="utf-8"))
        chips = pub.fetch_chips_with_retry(bs, day)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(json.dumps(chips), encoding="utf-8")
        return chips

    chip_lists: dict[str, list[Any]] = {}

    def chips_for_stable(day: str) -> list[Any]:
        # One list object per day, so the id()-keyed index cache hits across records.
        if day not in chip_lists:
            chip_lists[day] = chips_for(day)
        return chip_lists[day]

    def grade(recs, chips_by_date, named, *, today):
        return bs.grade_population(recs, chips_by_date, named, today=today, prop_settler=mlb.settle,
                                   score_source=mlb.final_score, extra_settler=settler)

    today = args.today or msc.central_today(datetime.now(timezone.utc), bs.SCORECARD.central_date)
    rows, reasons = grade_rows(records, grade=grade, chips_for=chips_for_stable,
                               central_date=bs.SCORECARD.central_date, today=today)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"GRADED {len(rows)} -> {out}", flush=True)
    print(f"REASONS {json.dumps(dict(reasons.most_common()), sort_keys=False)}", flush=True)
    print(f"SETTLERS {json.dumps(settler.report(), default=str)[:2000]}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    pull = sub.add_parser("pull")
    pull.add_argument("--start", required=True)
    pull.add_argument("--end", required=True)
    pull.add_argument("--sports", default="mlb,nfl,ncaaf,soccer,wnba,nhl")
    pull.add_argument("--out", required=True)
    pull.add_argument("--cache", default=None)
    pull.add_argument("--today", default=None)
    pull.add_argument("--source", choices=("recorder", "openings"), default="recorder")
    args = parser.parse_args(argv)
    if args.cmd == "pull":
        return cmd_pull(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
