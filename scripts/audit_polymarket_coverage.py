#!/usr/bin/env python3
"""Regenerate the evidence tables in `docs/ai_context/polymarket_oddsapi_coverage_audit.md`.

READ-ONLY. This script opens two artifacts that other jobs already write, counts
what is in them, and prints. It calls no venue, places no order, writes no file,
and is wired into no loop. Run it on a host that can see
`SYNDICATE_DATA_ROOT` (refresh-worker or live-odds-worker); from a sandbox it
will report `no_slate_artifact` and exit 2, which is the honest outcome rather
than a zero that looks like a venue with no markets.

    python scripts/audit_polymarket_coverage.py [--date YYYY-MM-DD] [--json]

WHY IT EXISTS RATHER THAN THE LOG LINES ALONE
--------------------------------------------------------------------------
Three of the audit's numbers are TRUNCATED where production prints them, and a
truncated diagnostic is exactly how a market family stays invisible:

  * `record_venue_book` prints `skipped_by_sport[:20]`. On 2026-08-25 the
    twenty printed summed to 6,507 against `skipped_total=7545`, so **1,038
    markets sat in leagues whose codes were never named** -- among them, most
    likely, four of Syndicate's ten soccer leagues.
  * `out_of_scope_samples` caps at 14 rows and `unmatched_samples` at 10.
  * No counter anywhere reports the slug PREFIX, so a fourth prefix (`atc`,
    observed once) is uncountable.

This prints all of them complete.

THE SPREAD TEST (`--spreads`, the point of the whole exercise)
--------------------------------------------------------------------------
Polymarket spread outcomes are signed numbers -- `["-1.50","+1.50"]` -- and
name no team, so `execute_portfolio` refuses every spread order by name
(`spread_side_needs_verified_team_mapping`) and `venue_quote_adapters` refuses
every spread quote. That cost 1,519 quotes per cycle on 2026-08-25.

Two of the three facts needed to lift that refusal are CONFIRMED (5 rows of 5,
2026-08-25T19:55-20:34Z): the slug's `pos`/`neg` token labels `outcomes[0]`,
and each fixture's ladder is symmetric about zero, so the sign belongs to ONE
reference club per game. The third -- whether that club is the slug's `<home>`
or its `<away>` -- cannot be read from any log line production emits.

This test settles it without touching the venue. For every fixture that appears
in BOTH the Polymarket slate and the board, it compares the sign of the slug's
handicap against the sign of the board's own home spread. The answer is bimodal:

    agreement ~1.0  ->  the reference club is the slug's <home>
    agreement ~0.0  ->  the reference club is the slug's <away>
    anything else   ->  §5.2 IS FALSIFIED: the reference is not fixed per game,
                        and spreads must stay refused.

It prints the rate WITH ITS SAMPLE SIZE and refuses to call it below
`--min-sample` (default 30), because a mapping this expensive to get wrong
should not be decided on a handful of fixtures.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _load_slate() -> tuple[list[Mapping[str, Any]], float | None, str | None]:
    """The persisted slate. Never the venue -- a second live caller per venue is
    a documented incident class in this repo (`#139/#144`, `#148`)."""
    try:
        from syndicate.features.shared.polymarket_board_join import load_polymarket_markets
    except Exception as exc:  # noqa: BLE001
        return [], None, f"import_failed: {type(exc).__name__}: {exc}"
    rows, fetched_at = load_polymarket_markets()
    if not rows:
        return [], None, "no_slate_artifact"
    return rows, fetched_at, None


def _load_board(selected_date: str) -> tuple[list[Mapping[str, Any]], str | None]:
    try:
        from pipeline.intelligence_state import read_layer2_shortlist
    except Exception as exc:  # noqa: BLE001
        return [], f"import_failed: {type(exc).__name__}: {exc}"
    shortlist = read_layer2_shortlist(selected_date)
    rows = (shortlist or {}).get("rows") if isinstance(shortlist, dict) else None
    rows = [r for r in (rows or []) if isinstance(r, Mapping)]
    return rows, None if rows else "no_shortlist_rows"


def _parsed(rows: Iterable[Mapping[str, Any]]):
    """`(row, parsed_slug)` for every row whose slug matches the grammar.

    Rows that do NOT parse are yielded with `None` rather than skipped -- an
    unparseable slug is a market family we cannot yet name, which is the thing
    this script exists to count.
    """
    from syndicate.features.shared.polymarket_board_join import parse_slug

    for row in rows:
        yield row, parse_slug(row.get("slug"))


def census(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Complete counts. No `[:20]`, no sample cap."""
    by_league_type: Counter[str] = Counter()
    by_prefix: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    unparseable: list[str] = []
    # One verbatim slug per (league, type), so a family can be checked against
    # the venue by hand. The slug is READ, never constructed.
    exemplar: dict[str, str] = {}
    ladders: dict[tuple[str, str, str], set[float]] = defaultdict(set)

    from syndicate.features.shared.polymarket_board_join import (
        MARKET_TYPE_TO_BOARD,
        _line_from_modifiers,
    )

    for row, parsed in _parsed(rows):
        venue_type = str(row.get("sportsMarketTypeV2") or "").upper() or "UNKNOWN"
        by_type[venue_type] += 1
        if parsed is None:
            if len(unparseable) < 40:
                unparseable.append(str(row.get("slug") or "")[:80])
            by_league_type[f"{venue_type}|<unparseable>"] += 1
            continue
        by_prefix[parsed["prefix"]] += 1
        key = f"{venue_type}|{parsed['league']}"
        by_league_type[key] += 1
        exemplar.setdefault(key, str(row.get("slug") or ""))
        board_market = MARKET_TYPE_TO_BOARD.get(venue_type)
        if board_market in {"spreads", "totals"}:
            line = _line_from_modifiers(parsed["modifiers"])
            if line is not None:
                ladders[(parsed["league"], f"{parsed['away']}-{parsed['home']}"
                         f"@{parsed['date']}", board_market)].add(float(line))

    rung_counts = Counter(len(v) for v in ladders.values())
    return {
        "markets": len(rows),
        "by_type": dict(by_type.most_common()),
        "by_prefix": dict(by_prefix.most_common()),
        "by_league_type": dict(by_league_type.most_common()),
        "exemplar_slug_by_league_type": exemplar,
        "unparseable_slugs": unparseable,
        "unparseable_count": by_league_type_total(by_league_type, "<unparseable>"),
        "ladders": len(ladders),
        "rungs_per_ladder": dict(sorted(rung_counts.items())),
        # The four leagues §6.1 says are hidden below the print cap show up
        # here or nowhere.
        "leagues": sorted({k.split("|", 1)[1] for k in by_league_type}),
    }


def by_league_type_total(counter: Counter[str], needle: str) -> int:
    return sum(v for k, v in counter.items() if needle in k)


def spread_sign_test(
    slate: list[Mapping[str, Any]],
    board: list[Mapping[str, Any]],
    *,
    min_sample: int = 30,
) -> dict[str, Any]:
    """Does the slug's `pos`/`neg` sign follow the board's HOME spread?

    Pairs on `(sport, date, home, away)` through `team_aliases`, the same
    resolver `polymarket_board_join._teams_match` uses -- so this test and the
    join can never disagree about which fixture a slug names.

    A fixture contributes ONE vote, not one per rung: a ladder has many rungs
    of the same sign convention and counting each would let a single fixture
    with a deep ladder decide the answer.
    """
    from syndicate.features.shared.polymarket_board_join import (
        _effective_league,
        _line_from_modifiers,
        parse_slug,
    )
    from syndicate.features.shared.team_aliases import teams_match as alias_match

    # The board's own signed HOME spread per fixture.
    home_line: dict[tuple[str, str, str, str], float] = {}
    for row in board:
        if str(row.get("market") or "").strip().lower() not in {"spreads", "spread"}:
            continue
        side = str(row.get("side") or "").strip().lower()
        try:
            line = float(row.get("line"))
        except (TypeError, ValueError):
            continue
        if line != line:  # NaN -- a real value on this board, and not a line
            continue
        # An AWAY row states the same fact with the opposite sign. Normalising
        # to home is what makes the two boards comparable at all.
        if side == "away":
            line = -line
        elif side != "home":
            continue
        sport = str(row.get("sport") or "").strip().lower()
        date = str(row.get("selected_date") or row.get("date") or "").strip()
        key = (sport, date, str(row.get("home_team") or ""), str(row.get("away_team") or ""))
        if not all(key):
            continue
        home_line.setdefault(key, line)

    agree = disagree = 0
    unmatched_fixtures = 0
    seen_fixture: set[tuple] = set()
    disagreements: list[dict[str, Any]] = []

    for row in slate:
        if str(row.get("sportsMarketTypeV2") or "").upper() != "SPORTS_MARKET_TYPE_SPREAD":
            continue
        parsed = parse_slug(row.get("slug"))
        if parsed is None:
            continue
        slug_line = _line_from_modifiers(parsed["modifiers"])
        if slug_line is None or slug_line == 0:
            continue
        league = _effective_league(parsed)
        match = None
        for key, board_line in home_line.items():
            sport, date, home, away = key
            if sport != league or date != parsed["date"]:
                continue
            if alias_match(sport, parsed["home"], home) and alias_match(sport, parsed["away"], away):
                match = (key, board_line)
                break
        if match is None:
            unmatched_fixtures += 1
            continue
        key, board_line = match
        if key in seen_fixture:
            continue
        seen_fixture.add(key)
        if board_line == 0:
            continue
        if (slug_line < 0) == (board_line < 0):
            agree += 1
        else:
            disagree += 1
            if len(disagreements) < 10:
                disagreements.append({
                    "slug": str(row.get("slug") or ""),
                    "slug_line": slug_line,
                    "board_home_line": board_line,
                    "fixture": f"{key[3]} @ {key[2]}",
                })

    n = agree + disagree
    rate = None if not n else round(agree / n, 4)
    if n < min_sample:
        verdict = f"UNDECIDED: n={n} < min_sample={min_sample}"
    elif rate is not None and rate >= 0.98:
        verdict = "REFERENCE CLUB IS THE SLUG'S <home>"
    elif rate is not None and rate <= 0.02:
        verdict = "REFERENCE CLUB IS THE SLUG'S <away>"
    else:
        verdict = (
            "FALSIFIED: the sign is not fixed per fixture. Spreads must stay "
            "refused; do not ship a mapping on this."
        )
    return {
        "fixtures_compared": n,
        "agree_with_home_sign": agree,
        "disagree": disagree,
        "agreement_rate": rate,
        "spread_slugs_with_no_board_fixture": unmatched_fixtures,
        "sample_disagreements": disagreements,
        "verdict": verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", default="", help="board date for the spread test (default: skip it)")
    ap.add_argument("--min-sample", type=int, default=30)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    slate, fetched_at, reason = _load_slate()
    if reason:
        print(f"[audit_polymarket_coverage] status=refused reason={reason}", flush=True)
        return 2

    report: dict[str, Any] = {
        "slate_fetched_at": fetched_at,
        "census": census(slate),
    }

    if args.date:
        board, board_reason = _load_board(args.date)
        report["board_rows"] = len(board)
        report["board_reason"] = board_reason
        if board:
            report["spread_sign_test"] = spread_sign_test(
                slate, board, min_sample=args.min_sample
            )

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
        return 0

    c = report["census"]
    print(f"markets={c['markets']} fetched_at={fetched_at}")
    print(f"\ntypes: {c['by_type']}")
    print(f"prefixes: {c['by_prefix']}")
    print(f"\nleagues ({len(c['leagues'])}): {', '.join(c['leagues'])}")
    print("\n(type|league) -> count, exemplar slug   [COMPLETE, no cap]")
    for key, count in c["by_league_type"].items():
        print(f"  {count:>6}  {key:<48} {c['exemplar_slug_by_league_type'].get(key,'')}")
    print(f"\nladders={c['ladders']} rungs_per_ladder={c['rungs_per_ladder']}")
    if c["unparseable_slugs"]:
        print(f"\nunparseable slugs ({c['unparseable_count']} total, first 40):")
        for slug in c["unparseable_slugs"]:
            print(f"  {slug}")
    if "spread_sign_test" in report:
        print("\nSPREAD SIGN TEST")
        for key, value in report["spread_sign_test"].items():
            print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
