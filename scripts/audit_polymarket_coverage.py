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
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
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
    selected_date: str = "",
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
        _has_segment,
        _line_from_modifiers,
        parse_slug,
    )
    from syndicate.features.shared.team_aliases import teams_match as alias_match

    # The board's own signed HOME spread per fixture.
    #
    # COUNTED, because the first production run returned a zero this dict could
    # not explain. "the board has no spread rows", "they carry no date" and
    # "the venue lists no spreads" are three different facts that all render as
    # `fixtures=0`, and a line that cannot tell them apart sends the reader to
    # the wrong one -- which is the whole subject of the audit this serves.
    home_line: dict[tuple[str, str, str, str], float] = {}
    board_spread_rows = 0
    skipped_board_rows = 0
    for row in board:
        if str(row.get("market") or "").strip().lower() not in {"spreads", "spread"}:
            continue
        board_spread_rows += 1
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
        # THE CALLER'S DATE IS THE FALLBACK, AND IN PRACTICE IT DOES THE WORK.
        #
        # MEASURED IN PRODUCTION 2026-08-25T21:47:20Z, the first run of this
        # test: `fixtures=0 no_board_fixture=1167`. Every one of 1,167 spread
        # slugs failed to pair, because this dict came out EMPTY -- shortlist
        # rows carry neither `selected_date` nor `date` (`_board_rows_for_join`
        # returns them verbatim from `read_layer2_shortlist` and nothing stamps
        # one on), so `all(key)` was False for every row.
        #
        # `join_polymarket_to_board` already documents this exact trap and
        # already solves it the same way. Row first, so a board that DOES carry
        # its own date still wins and a multi-date board is not collapsed onto
        # one caller's date.
        date = str(
            row.get("selected_date") or row.get("date") or selected_date or ""
        ).strip()
        key = (sport, date, str(row.get("home_team") or ""), str(row.get("away_team") or ""))
        if not all(key):
            skipped_board_rows += 1
            continue
        home_line.setdefault(key, line)

    agree = disagree = 0
    unmatched_fixtures = 0
    segment_slugs = 0
    seen_fixture: set[tuple] = set()
    disagreements: list[dict[str, Any]] = []

    for row in slate:
        if str(row.get("sportsMarketTypeV2") or "").upper() != "SPORTS_MARKET_TYPE_SPREAD":
            continue
        parsed = parse_slug(row.get("slug"))
        if parsed is None:
            continue
        # A FIRST-FIVE-INNINGS SPREAD IS NOT A GAME SPREAD.
        #
        # MEASURED IN PRODUCTION 2026-08-25T22:01:52Z, the first run that
        # produced any votes at all: `fixtures=7 agree_home=2 disagree=5
        # rate=0.2857` -- and **all five disagreements carried `-f5-`**:
        #
        #   asc-mlb-cle-laa-2026-08-25-f5-neg-1pt5   board_home_line=+1.5
        #   asc-mlb-chc-az-2026-08-25-f5-neg-1pt5    board_home_line=+1.5
        #   asc-mlb-min-ath-2026-08-25-f5-neg-1pt5   board_home_line=+1.0
        #   asc-mlb-phi-sea-2026-08-25-f5-neg-1pt5   board_home_line=+1.5
        #   asc-mlb-cin-sf-2026-08-25-f5-neg-1pt5    board_home_line=+1.0
        #
        # The board's spread is the FULL GAME; `f5` is the first five innings.
        # Their signs need not agree and comparing them measures nothing. Both
        # `join_polymarket_to_board` and `venue_quote_adapters._polymarket_sides`
        # already refuse segment rows for exactly this reason; this test did
        # not, so a rate of 0.2857 looked like evidence against the
        # symmetric-ladder finding when it was an artefact of the instrument.
        #
        # IT COMPOUNDED with the one-vote rule below: `seen_fixture` is set on
        # the FIRST match, so an `f5` slug appearing earlier in the slate stole
        # the fixture's only vote from the full-game slug behind it.
        if _has_segment(parsed["modifiers"]):
            segment_slugs += 1
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
        # The three numbers that tell a real zero from a broken one.
        "board_spread_rows": board_spread_rows,
        "board_fixtures_keyed": len(home_line),
        "board_rows_unkeyable": skipped_board_rows,
        "fixtures_compared": n,
        "agree_with_home_sign": agree,
        "disagree": disagree,
        "agreement_rate": rate,
        "spread_slugs_with_no_board_fixture": unmatched_fixtures,
        # Counted rather than silently dropped: a segment ladder is real
        # coverage we refuse elsewhere, and its size is worth seeing.
        "segment_slugs_skipped": segment_slugs,
        "sample_disagreements": disagreements,
        "verdict": verdict,
    }


# --------------------------------------------------------------------------
# THE BOOT HOOK -- opt-in, off unless explicitly switched on
# --------------------------------------------------------------------------


def _env_bool(name: str, *, default: bool = False) -> bool:
    """ABSENT MEANS OFF, and that is stated rather than implied.

    `CLAUDE.md`: "Absent != off. Check the code's default for any key you add."
    This one defaults FALSE, so the hook is inert on every boot until someone
    sets the flag, and unsetting it restores the inert state exactly.
    """
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def run_spread_audit_if_enabled() -> dict[str, Any] | None:
    """Run the spread sign test once at boot, if the flag is set. Never raises.

    WHY A BOOT HOOK AND NOT A CRON OR AN ENDPOINT. The two inputs live in the
    shared keyvalue store and nothing outside Render's private network can
    reach it (`ipAllowList: []`, and `SYNDICATE_REFRESH_STATE_URL` is supplied
    by `fromService`, a blueprint-only mechanism). So the test has to run from
    inside a service that already holds the connection. This is the same
    pattern `SYNDICATE_EXCHANGE_MARKETS_PROBE_ON_BOOT` and
    `SYNDICATE_KALSHI_POLYMARKET_ARB_PROBE_ON_BOOT` already use on the sibling
    worker, deliberately, so there is one shape for "diagnostic that runs once
    on request" rather than two.

    IT READS. It does not fetch from the venue, write a file, place an order,
    or touch pricing -- see this module's header. The worst case for a boot
    with the flag set is one extra artifact read and one printed line.

    RETURNS the report (or None when the flag is off) so a test can assert BOTH
    directions. A hook that has never been shown to do anything when switched
    on is indistinguishable from one that is wired up wrong, which is the
    failure `learnings.md` records as "a guard that has never once PASSED is
    not a guard".
    """
    if not _env_bool("SYNDICATE_POLYMARKET_SPREAD_AUDIT_ON_BOOT"):
        return None

    try:
        # THE GAME DATE, in UTC and explicitly. Three timezone-ambiguous
        # `date.today()` sites were fixed in this repo on 2026-08-25; this is
        # not going to be the fourth.
        selected_date = str(
            os.environ.get("SYNDICATE_POLYMARKET_SPREAD_AUDIT_DATE") or ""
        ).strip() or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            min_sample = int(os.environ.get("SYNDICATE_POLYMARKET_SPREAD_AUDIT_MIN_SAMPLE") or 30)
        except (TypeError, ValueError):
            min_sample = 30

        slate, fetched_at, reason = _load_slate()
        if reason:
            # A NAMED REFUSAL, never a zero. "no slate on disk" and "the venue
            # lists no spreads" are opposite facts and must not share a line.
            print(
                f"[audit_polymarket_coverage] SPREAD_SIGN_AUDIT status=refused reason={reason}"
                f" date={selected_date}",
                flush=True,
            )
            return {"status": "refused", "reason": reason}

        board, board_reason = _load_board(selected_date)
        if board_reason:
            print(
                f"[audit_polymarket_coverage] SPREAD_SIGN_AUDIT status=refused"
                f" reason={board_reason} date={selected_date}"
                f" slate_markets={len(slate)}",
                flush=True,
            )
            return {"status": "refused", "reason": board_reason}

        result = spread_sign_test(
            slate, board, min_sample=min_sample, selected_date=selected_date
        )
        print(
            f"[audit_polymarket_coverage] SPREAD_SIGN_AUDIT status=ok date={selected_date}"
            f" slate_markets={len(slate)} board_rows={len(board)}"
            f" slate_fetched_at={fetched_at}"
            f" board_spread_rows={result['board_spread_rows']}"
            f" board_fixtures_keyed={result['board_fixtures_keyed']}"
            f" board_rows_unkeyable={result['board_rows_unkeyable']}"
            f" fixtures={result['fixtures_compared']}"
            f" agree_home={result['agree_with_home_sign']}"
            f" disagree={result['disagree']}"
            f" rate={result['agreement_rate']}"
            f" no_board_fixture={result['spread_slugs_with_no_board_fixture']}"
            f" segment_skipped={result['segment_slugs_skipped']}"
            f" verdict={result['verdict']!r}"
            f" disagreements={result['sample_disagreements']}",
            flush=True,
        )
        return {"status": "ok", **result}
    except Exception as exc:  # noqa: BLE001
        # A DIAGNOSTIC MUST NOT BE ABLE TO KILL THE WORKER IT RUNS IN.
        print(
            f"[audit_polymarket_coverage] SPREAD_SIGN_AUDIT_FAILED"
            f" {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


def run_offset_probe_if_enabled() -> dict[str, Any] | None:
    """Is `find_first_game_offset`'s boundary landing ABOVE part of the game block?

    THE QUESTION, and why logs cannot answer it. Measured 2026-08-25:

        19:28Z  start_offset=12142  games=13255  futures=1613  truncated=True
        22:11Z  start_offset=20987  games=7936   futures=47    truncated=False

    A scan that now claims completeness returns 5,319 FEWER game markets than
    the truncated one did, after its start offset jumped +8,845. Over the same
    window MLB full-game spreads went from present in the join's index
    (`offered: ['chc-az@-2.5','-1.5','+1.5','+2.5']`, 20:16Z -- and that index
    REFUSES segments, so those were full-game) to absent entirely
    (`no_candidates|mlb|spreads: 51`, `offered: []`, 22:01Z).

    The budget trim is EXONERATED as the cause: `dropped_for_size=0
    dropped_by_date={}` on every cycle, with 5.99MB of headroom. So the loss is
    upstream of it, and there are exactly two candidates with opposite fixes:
    the venue stopped listing those markets, or **the boundary search stopped
    seeing them**. `find_first_game_offset`'s own docstring names the second --
    "past the first games (silently missing part of the slate)".

    `monotonic` is supposed to catch that and reads True. It is weaker than it
    looks: it only checks offsets the binary search HAPPENED to probe, so a
    boundary sitting inside the block can still report True.

    THE TEST. Probe a ladder BELOW the live boundary. **If any offset below it
    returns game rows, the boundary is too high and part of the slate is
    invisible to us.** If every one returns futures or empty, the boundary is
    right and the missing markets are the venue's, not ours.

    Derived from the CURRENT boundary, never hardcoded -- the value under test
    moves every day, which is the whole reason that function exists.

    COST: ~10 signed GETs of 5 rows. This DOES call the venue, deliberately --
    no artifact can answer "what lives at offset 18000", which is the one
    question here. It is opt-in, one-shot at boot, reads only, and places
    nothing. Unset the flag once the answer is in.
    """
    if not _env_bool("SYNDICATE_POLYMARKET_OFFSET_PROBE_ON_BOOT"):
        return None

    try:
        from syndicate.features.shared.polymarket_us_markets import (
            find_first_game_offset,
            probe_offset_landscape,
        )

        located = find_first_game_offset()
        boundary = located.get("first_game_offset")
        if not isinstance(boundary, int) or boundary <= 0:
            print(
                "[audit_polymarket_coverage] OFFSET_BOUNDARY_PROBE status=refused"
                f" reason=no_boundary located={located}",
                flush=True,
            )
            return {"status": "refused", "reason": "no_boundary", "located": located}

        # A ladder BELOW the boundary, plus the boundary and one page above it
        # as controls: the boundary itself must show games, and a rung below it
        # must not.
        rungs = sorted({
            max(0, int(boundary * f)) for f in (0.2, 0.4, 0.6, 0.8, 0.9, 0.95, 0.99)
        } | {boundary, boundary + 2000})
        result = probe_offset_landscape(offsets=tuple(rungs), limit=5)
        samples = result.get("samples") or {}

        below = {
            off: s for off, s in samples.items()
            if int(off) < boundary and isinstance(s, Mapping) and int(s.get("games") or 0) > 0
        }
        at_boundary_games = int(
            (samples.get(str(boundary)) or {}).get("games") or 0
        )
        if below:
            verdict = (
                f"BOUNDARY TOO HIGH -- {len(below)} offset(s) below {boundary} carry game"
                " rows, so part of the slate is invisible to us. NOT a venue absence."
            )
        elif at_boundary_games == 0:
            verdict = (
                f"INCONCLUSIVE -- the boundary {boundary} itself returned no game rows,"
                " so the control failed and nothing here can be trusted."
            )
        else:
            verdict = (
                f"BOUNDARY SOUND -- every rung below {boundary} is futures or empty and"
                " the boundary itself carries games. Missing markets are the VENUE's,"
                " not our scan's."
            )
        print(
            "[audit_polymarket_coverage] OFFSET_BOUNDARY_PROBE status=ok"
            f" boundary={boundary} probes={located.get('probes')}"
            f" monotonic={located.get('monotonic')}"
            f" rungs={rungs}"
            f" games_below_boundary={ {k: v.get('games') for k, v in below.items()} }"
            f" at_boundary_games={at_boundary_games}"
            f" verdict={verdict!r}"
            f" samples={samples}",
            flush=True,
        )
        return {"status": "ok", "boundary": boundary, "verdict": verdict, "samples": samples}
    except Exception as exc:  # noqa: BLE001
        print(
            f"[audit_polymarket_coverage] OFFSET_BOUNDARY_PROBE_FAILED"
            f" {type(exc).__name__}: {exc}",
            flush=True,
        )
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


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
                slate, board, min_sample=args.min_sample, selected_date=args.date
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
