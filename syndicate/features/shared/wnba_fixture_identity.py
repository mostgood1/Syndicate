"""The stable WNBA fixture identity, and the canonical fixture set per date.

WHY THIS EXISTS. `game_cards_<date>.csv` has carried THREE mutually
incompatible `game_id` schemes, measured across 62 local files:

    seq_index      1395 rows   "1", "2", ... and "100".."264"
    hex_hash         39 rows   "0f160b99581637ed10718a0bf90a33d38"
    long_numeric     16 rows

Two CONSECUTIVE dates in production disagreed: `game_cards_2026-08-16.csv`
carried `game_id=1` and `game_cards_2026-08-17.csv` carried
`0f160b99581637ed10718a0bf90a33d38`. An id that changes shape between branches
is not an identity -- nothing can join on it, and the 2026-08-17 spec's own gate
said to stop and establish one before building a coverage fix on top.

**THE IDENTITY ALREADY EXISTED; NOBODY WAS USING IT.**
`schedule_2026.csv` is keyed by the ESPN event id, and that is the SAME
namespace the live feed uses. Measured 2026-08-17, both sources, same instant:

    schedule_2026.csv            ESPN scoreboard?dates=20260816
    401857148 CHI @ SEA    ==    401857148 CHI @ SEA
    401857150 IND @ ATL    ==    401857150 IND @ ATL
    401857149 POR @ PHX    ==    401857149 POR @ PHX

So pregame artifacts and the live lens can join on one key for free. The
schedule covers 351 fixtures over 121 dates, 2026-04-25 to 2026-09-24.

WHAT THIS MODULE REFUSES TO DO, and why each refusal is load-bearing:

1. **It never invents an id.** An unresolvable fixture returns `None`. The
   sequential-index scheme above is exactly what inventing looks like, and it
   is what made the artifact unjoinable in the first place.

2. **It never reports game STATE.** `schedule_2026.csv` carries
   `game_status_text`, and it is STALE: measured 2026-08-17, it read
   "In Progress" for CHI@SEA and IND@ATL and "Scheduled" for POR@PHX while
   ESPN had all three at Final. `Fixture` therefore has no status field at
   all -- the one way to guarantee nobody joins a board to a dead status is
   not to hand it to them. State comes from the live lens, always.

3. **Orientation is part of the identity.** `(home, away)` is not
   `(away, home)`. A swapped pair does NOT resolve, because silently matching
   it would flip the sign of every spread and margin on the row -- a real
   number against the wrong side, which is worse than a blank.

4. **Ambiguity refuses rather than picks.** If a date somehow carries the same
   matchup twice, `resolve_fixture_id` returns `None`. Same rule
   `wnba_game_projections.lookup` already uses.

5. **A missing or unreadable schedule yields an EMPTY fixture set, never an
   exception.** This is imported by an artifact build path; a diagnostic or a
   lookup must never be able to take down the build it serves.

DATE KEY. `date_est` is the slate key. Measured over all 351 fixtures: zero
fixtures where the Eastern and Central calendar dates differ, and zero rows
where the `date_est` column disagrees with the Eastern date computed from
`datetime_utc`. So callers on the refresh script's Central convention and
callers on Eastern agree for this season -- stated as a measurement, not an
assumption, because it is a property of the 2026 schedule and not a guarantee.
"""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

# Candidate locations, most authoritative first. The vendored repo holds the
# git-tracked master; the mirror under data/wnba_source is refreshed copy.
_SCHEDULE_RELATIVE_PATHS: tuple[str, ...] = (
    "vendor/wnba_betting_repo/data/processed/schedule_2026.csv",
    "data/wnba_source/source_artifacts/data/processed/schedule_2026.csv",
    "data/wnba_source/data/processed/schedule_2026.csv",
)

# Keyed on (path, mtime, size) rather than a bare lru_cache so a refreshed
# schedule is picked up without a process restart, and so tests are not fighting
# a wall-clock TTL. `conftest` clears time-keyed caches for exactly that reason.
_CACHE: dict[tuple[str, int, int], tuple["Fixture", ...]] = {}


@dataclass(frozen=True)
class Fixture:
    """One scheduled fixture. `fixture_id` is the ESPN event id.

    Deliberately carries NO status field -- see refusal 2 in the module
    docstring. The schedule's status column is stale and must not be reachable
    from here.
    """

    fixture_id: str
    date_est: str
    home_tricode: str
    away_tricode: str
    home_team: str
    away_team: str
    datetime_utc: str
    season_type: str

    @property
    def is_regular_season(self) -> bool:
        return self.season_type == "regular-season"


def _repo_root() -> Path:
    # syndicate/features/shared/<this file> -> repo root is three parents up.
    return Path(__file__).resolve().parents[3]


def schedule_path() -> Path | None:
    """First schedule file that exists, or None. An override wins outright."""
    override = os.environ.get("SYNDICATE_WNBA_SCHEDULE_PATH", "").strip()
    if override:
        candidate = Path(override)
        return candidate if candidate.is_file() else None
    root = _repo_root()
    for rel in _SCHEDULE_RELATIVE_PATHS:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def load_schedule() -> tuple[Fixture, ...]:
    """Every fixture in the schedule, or an empty tuple. Never raises."""
    path = schedule_path()
    if path is None:
        return ()
    try:
        stat = path.stat()
        key = (str(path), int(stat.st_mtime), int(stat.st_size))
    except OSError:
        return ()
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    fixtures: list[Fixture] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if not isinstance(row, dict):
                    continue
                fixture_id = str(row.get("game_id") or "").strip()
                date_est = str(row.get("date_est") or "").strip()
                home_tri = str(row.get("home_tricode") or "").strip().upper()
                away_tri = str(row.get("away_tricode") or "").strip().upper()
                # A row missing any part of its identity is dropped rather than
                # patched. A fixture with no id is precisely the thing this
                # module exists to stop propagating.
                if not (fixture_id and date_est and home_tri and away_tri):
                    continue
                fixtures.append(
                    Fixture(
                        fixture_id=fixture_id,
                        date_est=date_est,
                        home_tricode=home_tri,
                        away_tricode=away_tri,
                        home_team=" ".join(
                            part
                            for part in (
                                str(row.get("home_city") or "").strip(),
                                str(row.get("home_name") or "").strip(),
                            )
                            if part
                        ),
                        away_team=" ".join(
                            part
                            for part in (
                                str(row.get("away_city") or "").strip(),
                                str(row.get("away_name") or "").strip(),
                            )
                            if part
                        ),
                        datetime_utc=str(row.get("datetime_utc") or "").strip(),
                        season_type=str(row.get("season_type_slug") or "").strip(),
                    )
                )
    except (OSError, csv.Error, UnicodeDecodeError):
        return ()

    result = tuple(fixtures)
    _CACHE[key] = result
    return result


def fixtures_for_date(date_str: Any, *, regular_season_only: bool = False) -> tuple[Fixture, ...]:
    """THE CANONICAL DENOMINATOR for a slate.

    This is the number every per-date WNBA artifact should be measured against.
    Measured 2026-08-16: this returns 3 while `game_cards_2026-08-16.csv` held
    1 row -- which is the coverage defect, stated as a ratio rather than as an
    absolute count that means nothing on its own.
    """
    date_key = str(date_str or "").strip()
    if not date_key:
        return ()
    out = [f for f in load_schedule() if f.date_est == date_key]
    if regular_season_only:
        out = [f for f in out if f.is_regular_season]
    return tuple(out)


def team_lookup() -> dict[str, str]:
    """Every accepted spelling -> tricode.

    Built from the schedule itself rather than from a hand-written table, so it
    cannot drift from the fixture set it is used to join against. Measured
    against 62 artifact files: all 15 real WNBA team strings in
    `game_cards`/`predictions` match `"{city} {name}"` exactly, so this is a
    lookup and not a fuzzy match.
    """
    table: dict[str, str] = {}
    for fixture in load_schedule():
        for tri, full in (
            (fixture.home_tricode, fixture.home_team),
            (fixture.away_tricode, fixture.away_team),
        ):
            if not tri:
                continue
            table[_norm(tri)] = tri
            if full:
                table[_norm(full)] = tri
    return table


def normalize_team(value: Any) -> str | None:
    """A team spelling -> its tricode, or None.

    None is a real answer, not a failure to try. Measured in the artifacts:
    `'Oklahoma City Thunder'` and `'San Antonio Spurs'` both appear in WNBA
    game_cards -- NBA teams, one row each. They resolve to None here, and a
    caller that reports them is surfacing genuine upstream contamination that
    a permissive matcher would have silently absorbed.
    """
    key = _norm(value)
    if not key:
        return None
    table = team_lookup()
    hit = table.get(key)
    if hit:
        return hit
    # Alias fallback, UNAMBIGUOUS ONLY -- the same rule
    # `wnba_game_projections.lookup` uses. Two candidates means the join cannot
    # know which, and a wrong fixture is worse than an unresolved one.
    try:
        from syndicate.features.shared.team_aliases import teams_match
    except Exception:
        return None
    candidates = {tri for spelling, tri in table.items() if teams_match("wnba", key, spelling)}
    return next(iter(candidates)) if len(candidates) == 1 else None


def resolve_fixture_id(date_str: Any, home: Any, away: Any) -> str | None:
    """(date, home, away) -> ESPN fixture id, or None.

    ORIENTATION IS PART OF THE IDENTITY. Passing the teams the wrong way round
    returns None rather than the fixture, because a swapped match would flip
    every spread and margin sign on the joined row.
    """
    home_tri, away_tri = normalize_team(home), normalize_team(away)
    if not (home_tri and away_tri) or home_tri == away_tri:
        return None
    hits = [
        f
        for f in fixtures_for_date(date_str)
        if f.home_tricode == home_tri and f.away_tricode == away_tri
    ]
    return hits[0].fixture_id if len(hits) == 1 else None


def coverage_against_schedule(
    date_str: Any,
    rows: Iterable[Any],
    *,
    home_key: str = "home_team",
    away_key: str = "visitor_team",
) -> dict[str, Any]:
    """What a per-date artifact covers, as a RATIO against the schedule.

    Exists so a coverage defect is reportable as "1 of 3" rather than as a bare
    row count, which is the form that let `game_cards` sit short for weeks. The
    unresolved list is returned rather than counted, because "the artifact is
    missing a fixture" and "the artifact names a team we cannot resolve" are
    two different bugs and must not look alike.
    """
    scheduled = fixtures_for_date(date_str)
    expected = {f.fixture_id for f in scheduled}
    covered: set[str] = set()
    unresolved: list[dict[str, str]] = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        home, away = row.get(home_key), row.get(away_key)
        fixture_id = resolve_fixture_id(date_str, home, away)
        if fixture_id is None:
            unresolved.append({"home": str(home or ""), "away": str(away or "")})
            continue
        covered.add(fixture_id)
    missing = sorted(expected - covered)
    by_id = {f.fixture_id: f for f in scheduled}
    return {
        "date": str(date_str or ""),
        "scheduled": len(expected),
        "covered": len(covered),
        "missing_fixture_ids": missing,
        "missing_matchups": [
            f"{by_id[i].away_tricode}@{by_id[i].home_tricode}" for i in missing if i in by_id
        ],
        "unresolved_rows": unresolved,
    }


GAME_CARDS_BACKFILL_ENV = "WNBA_GAME_CARDS_SCHEDULE_BACKFILL"


def backfill_enabled() -> bool:
    """Kill switch for the coverage backfill. ABSENT MEANS ENABLED.

    Deliberately the opposite default from
    `_evaluation_settlement_auto_refresh_enabled` (absent -> False), and the
    difference is not an inconsistency: that flag guards a ~1.4GB job where
    running unintentionally is the expensive mistake, whereas the defect here is
    a MISSING row, so the expensive mistake is NOT covering. Set to
    `0`/`false`/`no`/`off` to restore the pre-2026-08-17 behaviour exactly.

    Note for anyone editing `render.yaml`: adding this key at all is a no-op
    unless the value is falsey, because absent and "1" mean the same thing here.
    """
    raw = os.environ.get(GAME_CARDS_BACKFILL_ENV, "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _iso_utc(datetime_utc: str) -> str:
    """Schedule `2026-08-16 23:00:00+00:00` -> artifact `2026-08-16T23:00:00Z`.

    The two formats differ, and a backfilled row carrying the schedule's spelling
    would be the only row in the file with a different one -- which is the kind
    of quiet inconsistency that makes a downstream parser fail on exactly the
    rows this fix added. Unparseable input returns "" rather than a guess.
    """
    text = str(datetime_utc or "").strip()
    if not text:
        return ""
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return ""


def stamp_and_backfill_game_cards_rows(
    date_str: Any,
    rows: Any,
    *,
    home_key: str = "home_team",
    away_key: str = "visitor_team",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Stamp `fixture_id` on every row, then add any scheduled fixture missing.

    THE COVERAGE FIX, kept here rather than in the builder so the builder's edit
    is three lines and so this is testable without running an artifact build.

    Returns `(rows, report)`. The report is what the `#375` census should print:
    a RATIO, because "1 row" was the form that let this sit short for weeks.

    Rules, each one load-bearing:

    * **A row that cannot be resolved keeps a BLANK `fixture_id` and is
      counted, never dropped.** Two real rows in the artifacts name NBA teams;
      losing them would hide upstream contamination.
    * **Backfilled rows carry identity and commence time ONLY.** Every market
      and projection column is left absent, which the board already renders as
      absent. Inventing a price would be far worse than a missing game.
    * **An empty schedule backfills NOTHING.** Out of season, or a date with no
      slate, must not have one invented -- the same refusal the WNBA
      scoreboard carry-forward makes for a 200-with-no-events.
    * **Never raises.** This is called from a build path.
    """
    out_rows: list[dict[str, Any]] = [dict(r) for r in (rows or ()) if isinstance(r, dict)]
    report: dict[str, Any] = {
        "scheduled": 0,
        "covered": 0,
        "backfilled": 0,
        "unresolved": 0,
        "backfill_enabled": backfill_enabled(),
    }
    try:
        scheduled = fixtures_for_date(date_str)
    except Exception:
        return out_rows, report
    report["scheduled"] = len(scheduled)

    covered: set[str] = set()
    for row in out_rows:
        try:
            fixture_id = resolve_fixture_id(date_str, row.get(home_key), row.get(away_key))
            if fixture_id is None:
                fixture_id = resolve_fixture_id(date_str, row.get("home_tri"), row.get("away_tri"))
        except Exception:
            fixture_id = None
        if fixture_id:
            row["fixture_id"] = fixture_id
            covered.add(fixture_id)
        else:
            row.setdefault("fixture_id", "")
            report["unresolved"] += 1
    report["covered"] = len(covered)

    if not scheduled or not report["backfill_enabled"]:
        return out_rows, report

    for fixture in scheduled:
        if fixture.fixture_id in covered:
            continue
        out_rows.append(
            {
                "date": str(date_str or ""),
                # `game_id` gets the STABLE id too, so newly written rows stop
                # extending the sequential-index scheme. Existing rows keep
                # whatever they had -- `fixture_id` is the authoritative column
                # and the one consumers should migrate to.
                "game_id": fixture.fixture_id,
                "fixture_id": fixture.fixture_id,
                "home_team": fixture.home_team,
                "visitor_team": fixture.away_team,
                "home_tri": fixture.home_tricode,
                "away_tri": fixture.away_tricode,
                "commence_time": _iso_utc(fixture.datetime_utc),
            }
        )
        report["backfilled"] += 1
    return out_rows, report


def _clear_cache() -> None:
    """Test hook. The cache is content-keyed, so this is only needed when a
    test rewrites a schedule file within the same mtime granularity."""
    _CACHE.clear()
