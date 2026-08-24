"""Can the interval projection be joined to a real market line? Coverage FIRST.

**THIS SCRIPT EXISTS BECAUSE OF A DOCUMENTED TRAP IN THIS REPO.** `CLAUDE.md`:
each artifact family syncs on its own schedule, so any analysis that joins across
families silently collapses to the intersection. The worked MLB example found
four families whose windows overlapped on **one usable date** while the analysis
looked like it ran on months of data. A market join reads TWO families that were
built years apart in different systems, so it is exactly the shape that fails
that way.

So this measures the join before anything is modelled, and reports THE NUMBER OF
DATES THE RESULT WOULD ACTUALLY REST ON.

## THE THREE THINGS A MARKET JOIN NEEDS

  1. GAME STATE      `momentum_events_<date>.json` -- play-level rows carrying
                     game-clock seconds. 282 games backfilled.
  2. A LIVE LINE     `book_quotes/<date>.jsonl` -- append-only, one row per
                     (book, segment, market, line) observation, with
                     `captured_at`. Interval segments (q1..q4, h1, h2) arrive
                     through the paid OddsAPI call and have landed here since
                     2026-08-11 (`period_lines.py`).
  3. A CLOCK BRIDGE  and this is the one that is easy to assume. The state rows
                     are in GAME seconds; the quotes are in WALL-CLOCK UTC.
                     Asking "what was the quarter total when 3:00 remained in
                     Q3" needs a mapping between them, and the season backfill
                     does not carry one -- its rows have `clock_seconds` and
                     nothing else. `live_momentum_<date>.jsonl` DOES: each
                     append pairs a `generated_at` wall clock with a per-game
                     `as_of_seconds`. That file only exists for dates the live
                     poller ran.

Miss (3) and the join is not wrong, it is impossible -- and the failure mode is
a script that runs, reports a number, and has silently matched every probe
against one stale pre-game line.

## THE QUESTION UNDER THE QUESTION

Even with all three, a market join is only interesting if the interval quotes
were captured **DURING** the game. A single pre-tip snapshot of a Q4 total is
not a line anyone could have bet into at 3:00 of Q3. So the headline is not
"are there interval rows" but **how many distinct capture instants there are
per event, and over what span** -- reported per date, because one good date and
eleven empty ones average into something that looks fine.

Measures. Does not model, does not join, does not price.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from syndicate.features.shared.basketball_momentum_artifacts import (
    momentum_artifact_path,
    momentum_events_path,
)
from syndicate.features.shared.odds_book_quotes import resolve_book_quotes_path
from syndicate.features.wnba.cards import _canonical_wnba_tri

def _matchup(home: Any, away: Any) -> tuple[str, str] | None:
    """The join key, canonicalised. `None` when either side cannot be mapped.

    **THE TWO FAMILIES DO NOT SHARE AN ID SPACE, AND THE FIRST RUN OF THIS PROBE
    READ THAT AS "NO GAMES IN COMMON".** `book_quotes.event_id` is OddsAPI's
    `event_obj["id"]`; the state artifact is keyed on ESPN's numeric event id.
    Joining them gave `event_overlap=0` on ALL FOURTEEN dates -- a number that
    looks like a finding about the data and is a fact about the key.

    The repo had already settled this. `period_lines_by_matchup`: *"Keyed on the
    team names exactly as the quote rows carry them ... because the quote log is
    the shared record and should not learn one sport's identifier scheme."* So
    the key is the matchup, and `_canonical_wnba_tri` is reused rather than
    respelt -- it already maps tricodes AND full names ("LASVEGASACES" -> "LVA")
    onto one canonical form. That function is where the LA/LAS collision was
    fixed once; a second copy here would be a second place for it to rot.
    """
    h = _canonical_wnba_tri(str(home or "").strip())
    a = _canonical_wnba_tri(str(away or "").strip())
    if not h or not a or h == a:
        return None
    # **AN UNRECOGNISED NAME COMES BACK UNCHANGED, NOT EMPTY.**
    # `_canonical_wnba_tri` passes a value it does not know straight through, so
    # "Toronto Tempo" becomes the key "TORONTO TEMPO" -- non-empty, distinct,
    # and unable to match the state side's "TOR". That is a silent zero one
    # level below the one this function was written to fix. A canonical WNBA
    # tricode is two to four letters and nothing else, so anything wider is a
    # name the map has never seen and must be reported rather than joined on.
    if not (_looks_like_tricode(h) and _looks_like_tricode(a)):
        return None
    return (h, a)


def _looks_like_tricode(value: str) -> bool:
    return 2 <= len(value) <= 4 and value.isalpha()


# The intervals a book actually prices, per `period_lines._PERIODS`.
INTERVAL_SEGMENTS = ("q1", "q2", "q3", "q4", "h1", "h2")
# Markets that carry a LINE worth projecting against. Moneyline has no number.
LINE_MARKETS = ("totals", "spreads", "totals_alt", "spreads_alt")


def _iter_dates(start: str, end: str):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    while a <= b:
        yield a.isoformat()
        a += timedelta(days=1)


def _read_jsonl(path: Path):
    """Rows from a `.jsonl`, tolerating a shard that is being appended to."""
    try:
        opener = path.open
        if path.suffix == ".gz":
            import gzip
            opener = lambda: gzip.open(path, "rt", encoding="utf-8")  # noqa: E731
        with opener() as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError:
        return


def _state_coverage(root: Path, league: str, day: str) -> dict[str, Any]:
    path = momentum_events_path(root, league_code=league, date_str=day)
    if not path.exists():
        return {"games": 0, "events": set()}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"games": 0, "events": set()}
    games = doc.get("games") or {}
    usable = 0
    keys: set[tuple[str, str]] = set()
    unmapped: set[str] = set()
    for value in games.values():
        if not isinstance(value, dict):
            continue
        if not (value.get("pressure") and value.get("narrator")):
            continue
        usable += 1
        key = _matchup(value.get("home_tri"), value.get("away_tri"))
        if key:
            keys.add(key)
        else:
            unmapped.add(f"{value.get('away_tri')}@{value.get('home_tri')}")
    return {"games": usable, "events": keys, "unmapped": unmapped}


def _bridge_coverage(root: Path, league: str, day: str) -> dict[str, Any]:
    """Wall-clock <-> game-clock pairs, from the per-poll capture."""
    path = momentum_artifact_path(root, league_code=league, date_str=day)
    pairs = 0
    events: set[str] = set()
    stamps: set[str] = set()
    for row in _read_jsonl(path):
        payload = row.get("payload") if isinstance(row.get("payload"), dict) else row
        generated = str(payload.get("generated_at") or "").strip()
        blocks = payload.get("games") or {}
        if not isinstance(blocks, dict):
            continue
        for key, block in blocks.items():
            if not isinstance(block, dict):
                continue
            # BOTH halves required. A capture with a wall clock and no
            # `as_of_seconds` bridges nothing.
            if generated and block.get("as_of_seconds") is not None:
                pairs += 1
                events.add(str(key))
                stamps.add(generated)
    return {"pairs": pairs, "events": events, "instants": len(stamps)}


def _quote_coverage(day: str) -> dict[str, Any]:
    path = resolve_book_quotes_path("wnba", day)
    if not path or not Path(path).exists():
        return {"rows": 0, "interval_rows": 0, "events": set(), "unmapped": set(),
                "by_segment": {}, "instants_by_event": {}, "books": set()}
    rows = interval_rows = 0
    events: set[str] = set()
    by_segment: dict[str, int] = defaultdict(int)
    instants_by_event: dict[tuple[str, str], set] = defaultdict(set)
    books: set[str] = set()
    unmapped: set[str] = set()
    for row in _read_jsonl(Path(path)):
        rows += 1
        segment = str(row.get("segment") or "").strip().lower()
        if segment not in INTERVAL_SEGMENTS:
            continue
        market = str(row.get("market") or "").strip().lower()
        if market not in LINE_MARKETS:
            continue
        if row.get("line") is None:
            continue
        interval_rows += 1
        by_segment[segment] += 1
        key = _matchup(row.get("home_team"), row.get("away_team"))
        if key:
            events.add(key)
            # `captured_at` is when OUR loop looked -- the instant a bettor
            # could have acted on. `book_updated_at` is the book's own clock and
            # is not always present.
            stamp = str(row.get("captured_at") or "").strip()
            if stamp:
                instants_by_event[key].add(stamp)
        else:
            # **NAMED, NOT DROPPED.** An unmappable team is how a real overlap
            # becomes a silent zero -- Toronto and Portland are 2026 expansion
            # sides and are absent from the canonical map's full-name entries.
            unmapped.add(f"{row.get('away_team')}@{row.get('home_team')}")
        book = str(row.get("bookmaker") or "").strip()
        if book:
            books.add(book)
    return {"rows": rows, "interval_rows": interval_rows, "events": events,
            "by_segment": dict(by_segment), "instants_by_event": dict(instants_by_event),
            "books": books, "unmapped": unmapped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", default="wnba")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--data-root", default=None)
    args = parser.parse_args(argv)

    # **ONE SPELLING OF THE QUOTE PATH.** `resolve_book_quotes_path` builds its
    # own path from `data_root()` and takes no root argument, so honouring
    # `--data-root` by constructing the path here would put a SECOND spelling of
    # `<sport>_source/tracking/book_quotes/<date>.jsonl` in the tree. Two
    # spellings of one path is how `/sports/sports/` happened -- and that one
    # only cost a season backfill, whereas this one would silently read an empty
    # directory and report NOT_JOINABLE. Set the env instead and let the real
    # function resolve; `data_root()` reads it fresh on every call.
    if args.data_root:
        os.environ["SYNDICATE_DATA_ROOT"] = str(Path(args.data_root).resolve())
    from syndicate.features.shared.refresh_state_store import data_root
    root = data_root()

    state_days: list[str] = []
    bridge_days: list[str] = []
    quote_days: list[str] = []
    joinable: list[str] = []

    for day in _iter_dates(args.start, args.end):
        state = _state_coverage(root, args.league, day)
        bridge = _bridge_coverage(root, args.league, day)
        quotes = _quote_coverage(day)

        if state["games"]:
            state_days.append(day)
        if bridge["pairs"]:
            bridge_days.append(day)
        if quotes["interval_rows"]:
            quote_days.append(day)

        if not (state["games"] or quotes["interval_rows"]):
            continue

        # **INSTANTS PER EVENT IS THE HEADLINE.** One capture is a pre-tip
        # snapshot; a line nobody could have bet into mid-game.
        counts = sorted((len(v) for v in quotes["instants_by_event"].values()), reverse=True)
        overlap = state["events"] & quotes["events"]
        print(f"[join] DATE {day} state_games={state['games']} "
              f"bridge_pairs={bridge['pairs']} "
              f"quote_interval_rows={quotes['interval_rows']} "
              f"quote_events={len(quotes['events'])} "
              f"event_overlap={len(overlap)} "
              f"instants_per_event={counts[:6]} "
              f"segments={dict(sorted(quotes['by_segment'].items()))}", flush=True)
        stray = (state.get("unmapped") or set()) | (quotes.get("unmapped") or set())
        if stray:
            print(f"[join] UNMAPPED {day} {sorted(stray)[:8]} -- these cannot join "
                  f"and are NOT counted as absent games", flush=True)

        # Joinable means ALL THREE, plus at least one event in common, plus a
        # quote stream that actually moves. Anything less is not a live line.
        if (state["games"] and bridge["pairs"] and overlap
                and any(c >= 2 for c in counts)):
            joinable.append(day)

    def _window(days: list[str]) -> str:
        return f"{days[0]}..{days[-1]}" if days else "none"

    print("[join] " + "-" * 60, flush=True)
    print(f"[join] FAMILY state(momentum_events)  dates={len(state_days)} window={_window(state_days)}", flush=True)
    print(f"[join] FAMILY bridge(live_momentum)   dates={len(bridge_days)} window={_window(bridge_days)}", flush=True)
    print(f"[join] FAMILY quotes(book_quotes)     dates={len(quote_days)} window={_window(quote_days)}", flush=True)

    # **THE NUMBER THE WHOLE SCRIPT EXISTS TO PRINT.** Not a total, not an
    # average -- the count of dates a market join would actually rest on.
    print(f"[join] USABLE_DATES n={len(joinable)} window={_window(joinable)} "
          f"dates={joinable}", flush=True)

    if not joinable:
        print("[join] VERDICT NOT_JOINABLE -- see the per-family windows above "
              "for which of the three is missing", flush=True)
        return 4
    print(f"[join] VERDICT JOINABLE on {len(joinable)} date(s) -- any result "
          f"from this join rests on that number and must be reported with it",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
