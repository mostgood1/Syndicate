"""Search the Layer 2 priced population for buckets where a model succeeds -- or fails.

Lane `accuracy-assessment-0914`, user request 2026-09-14: "then build the bucket search on
the recorder data". The category table says whether a model beats the market ON AVERAGE;
this finds pockets INSIDE a category, on the whole population the board priced
(`opportunity_population_ledger`), never on the published subset.

WHAT IS GRADED. Full-game h2h, spreads and totals, from final scores, through
`layer2_live_scorecard`'s own `grade` / `match_chip` (imported, not re-derived). Props and
segment rows are counted UNGRADED by reason. Pushes are dropped.

THE PRE-REGISTERED METHOD (lane block, written before any data was searched):
- Buckets come from `measured_bucket_skill.bucket_ids` -- the SAME function the scorer
  uses. Sport x market x segment x phase x ONE band of ONE dimension.
- The unit is the GAME: rows are averaged within a game first. Row-level inference was
  measured to inflate significance ~7x in this repo (+21 sigma by row, +2.9 by game).
- Skill metric: Brier(model) - Brier(market) on the side's probability, with
  p_model = fair_probability + model_edge_pct/100 (clamped) and p_market = fair_probability.
- Profit metric: flat 1u ROI at the recorded price on rows where the model favours the side.
- VALIDATED requires ALL of: >= MIN_GAMES games and >= MIN_DATES dates; a 95% bootstrap CI
  over games that excludes 0 (seeded); the sign kept with each date left out; and
  Benjamini-Hochberg at FDR_Q across every bucket eligible in the run.
- Verdicts: `skill_pocket` / `skill_loss` / `parity` / `insufficient`; and separately
  `profit_pocket` (reported, NOT used by scoring).

OUTPUT. A JSON report and a markdown table. `--write-table` writes the VALIDATED skill
buckets into `syndicate/features/shared/measured_bucket_skill.json`, which the scorer
reads; that file changes behaviour, so it ships through review and a deploy like code.

    py -3 scripts/bucket_search.py --start 2026-09-15 --end 2026-09-24 --out-dir C:/tmp/bucket_search
    py -3 scripts/bucket_search.py --records-dir DIR --chips-dir DIR --out-dir DIR     (offline)
    ... --write-table        (writes the validated buckets for the scorer)

Coverage is printed before any result, per the repo rule: record dates, chip dates, the
intersection, and how many dates and games the result rests on.
"""

from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import os
import random
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import measured_bucket_skill as mbs  # noqa: E402
from syndicate.features.shared.opportunity_population_ledger import (  # noqa: E402
    POPULATION_SUBDIR,
    parse_population_key,
    population_key,
    population_record,
)

PROP_GRADED_SPORTS = frozenset({"mlb"})
OPENINGS_PATH_TEMPLATE = "reports/intelligence/clv_openings/{date}.jsonl"
POPULATIONS = ("recorder", "published")


def _load_scorecard() -> Any:
    source = REPO_ROOT / "scripts" / "layer2_live_scorecard.py"
    spec = importlib.util.spec_from_file_location("layer2_live_scorecard", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


SCORECARD = _load_scorecard()

MIN_GAMES = 60
MIN_DATES = 5
RESAMPLES = 2000
SEED = 20260914
FDR_Q = 0.10
P_FLOOR, P_CEIL = 0.001, 0.999
BASE_URL = "https://syndicate-an21.onrender.com"
SPORTS = ("mlb", "nfl", "ncaaf", "soccer", "wnba", "nba", "nhl", "ncaab")
MAX_PARTS = 64


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------


def parse_records_text(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("k"):
            records.append(parsed)
    return records


def load_records_dir(path: Path | str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for file in sorted(Path(path).glob("*__*__part*.jsonl")):
        records.extend(parse_records_text(file.read_text(encoding="utf-8")))
    return records


def load_chips_dir(path: Path | str) -> dict[str, list[dict[str, Any]]]:
    """`<YYYY-MM-DD>.json` holding the game-chips payload (`{"chips": [...]}`) or a bare list."""
    out: dict[str, list[dict[str, Any]]] = {}
    for file in sorted(Path(path).glob("????-??-??.json")):
        payload = json.loads(file.read_text(encoding="utf-8"))
        chips = payload.get("chips") if isinstance(payload, Mapping) else payload
        out[file.stem] = [chip for chip in (chips or []) if isinstance(chip, Mapping)]
    return out


def parse_openings_text(text: str) -> list[dict[str, Any]]:
    openings: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("key"):
            openings.append(parsed)
    return openings


def load_openings_dir(path: Path | str) -> list[dict[str, Any]]:
    """Offline: `<YYYY-MM-DD>.jsonl` published-opening ledgers."""
    openings: list[dict[str, Any]] = []
    for file in sorted(Path(path).glob("????-??-??.jsonl")):
        openings.extend(parse_openings_text(file.read_text(encoding="utf-8")))
    return openings


def records_from_openings(openings: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """PUBLISHED openings -> population records, through the recorder's own key and record builders.

    The openings ledger holds only what the shortlist PUBLISHED (one row per side per book), so
    anything measured on these records is conditioned on admission: a preview, never a scoring input.
    """
    records: list[dict[str, Any]] = []
    for opening in openings:
        row = {
            "sport": opening.get("sport"),
            "event_id": opening.get("event_id"),
            "kind": opening.get("kind"),
            "market": opening.get("market"),
            "segment": opening.get("segment"),
            "side": opening.get("side"),
            "line": opening.get("line"),
            "player_name": opening.get("player_name"),
            "home_team": opening.get("home_team"),
            "away_team": opening.get("away_team"),
            "commence_time": opening.get("commence_time"),
            "game_state": opening.get("game_state"),
            "model_edge_pct": opening.get("model_edge_pct"),
            "ev_pct": opening.get("ev_pct"),
            "quote": {
                "price": opening.get("price"),
                "fair_probability": opening.get("fair_probability"),
                "fair_method": opening.get("fair_method"),
                "books_quoting": opening.get("books_quoting"),
                "book_age_seconds": opening.get("book_age_seconds"),
            },
        }
        key = population_key(row)
        if key:
            records.append(population_record(row, key, str(opening.get("captured_at") or ""), sport=opening.get("sport")))
    return records


def fetch_openings(base_url: str, token: str, day: str, *, cache_dir: Path | None = None,
                   complete: bool = False) -> list[dict[str, Any]]:
    """One date's published-opening ledger from web's copy; [] when web has none.

    With `cache_dir`, a file for a date that is over (`complete`) is kept, so a rerun does not
    pull it again: a Saturday file measured 17.5 MB.
    """
    cached = cache_dir / f"{day}.jsonl" if cache_dir else None
    if cached is not None and cached.is_file():
        return parse_openings_text(cached.read_text(encoding="utf-8"))
    relative = OPENINGS_PATH_TEMPLATE.format(date=day)
    url = f"{base_url.rstrip('/')}/api/ops/artifacts/export?path={urllib.parse.quote(relative, safe='')}"
    try:
        payload = _get_json(url, token)
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 404):
            return []
        raise
    artifacts = payload.get("artifacts") if isinstance(payload, Mapping) else None
    if not isinstance(artifacts, Mapping) or not artifacts:
        return []
    text = str(next(iter(artifacts.values())))
    if cached is not None and complete:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_text(text, encoding="utf-8")
    return parse_openings_text(text)


def _main_worktree() -> Path | None:
    """The repository's MAIN worktree — `git worktree list` names it first.

    `REPO_ROOT` is only the checkout this copy of the script lives in; from a session
    worktree that is not where the gitignored `.env` is (learnings 2026-09-10).
    """
    import subprocess

    try:
        listed = subprocess.run(["git", "-C", str(REPO_ROOT), "worktree", "list", "--porcelain"],
                                capture_output=True, text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in listed.splitlines():
        if line.startswith("worktree "):
            return Path(line[len("worktree "):].strip())
    return None


def env_file_candidates(env_file: Path | str | None = None) -> list[Path]:
    """Where ADMIN_TOKEN is looked for, in order: `--env-file`, this checkout, the main worktree."""
    candidates = [Path(env_file)] if env_file else []
    candidates.append(REPO_ROOT / ".env")
    main_tree = _main_worktree()
    if main_tree is not None:
        candidates.append(main_tree / ".env")
    unique: list[Path] = []
    for path in candidates:
        if path not in unique:
            unique.append(path)
    return unique


def _admin_token(env_file: Path | str | None = None) -> str:
    """ADMIN_TOKEN from the environment, else the first candidate `.env` that holds one. Never printed."""
    from_env = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if from_env:
        return from_env
    for path in env_file_candidates(env_file):
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            key, sep, value = line.strip().partition("=")
            if sep and key.strip() == "ADMIN_TOKEN":
                token = value.strip().strip('"').strip("'")
                if token:
                    return token
    return ""


def _get_json(url: str, token: str | None = None, timeout: float = 180.0) -> Any:
    headers = {"User-Agent": "syndicate-bucket-search"}
    if token:
        headers["X-Admin-Token"] = token
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout) as response:
        return json.loads(response.read())


def fetch_records(base_url: str, token: str, day: str, sports: Sequence[str] = SPORTS) -> list[dict[str, Any]]:
    """Every part of every sport for one board date, from web's copy. Sequential, bounded."""
    records: list[dict[str, Any]] = []
    for sport in sports:
        for part in range(MAX_PARTS):
            relative = f"reports/intelligence/{POPULATION_SUBDIR}/{day}__{sport}__part{part:03d}.jsonl"
            url = f"{base_url.rstrip('/')}/api/ops/artifacts/export?path={urllib.parse.quote(relative, safe='')}"
            try:
                payload = _get_json(url, token)
            except urllib.error.HTTPError as exc:
                if exc.code in (403, 404):
                    break
                raise
            artifacts = payload.get("artifacts") if isinstance(payload, Mapping) else None
            if not isinstance(artifacts, Mapping) or not artifacts:
                break
            records.extend(parse_records_text(next(iter(artifacts.values()))))
    return records


TEAM_LOOKUP_MARKETS = ("h2h", "totals", "spreads")


def fetch_event_teams(base_url: str, token: str, day: str, sport: str,
                      market: str | None = None) -> dict[tuple[str, str], tuple[str, str]]:
    """(sport, event_id) -> (home, away) from that date's served book grid.

    Only for records written before the recorder carried team names. The grid serves at most
    2,000 rows — soccer 2026-09-14 returned 2,000 of 3,082, covering 9 events — so ask for
    one market at a time.
    """
    params: dict[str, Any] = {"sport": sport, "date": day, "limit": 2000}
    if market:
        params["market"] = market
    payload = _get_json(f"{base_url.rstrip('/')}/api/board/book-grid?{urllib.parse.urlencode(params)}", token)
    out: dict[tuple[str, str], tuple[str, str]] = {}
    for row in (payload.get("rows") or []) if isinstance(payload, Mapping) else []:
        event_id = str(row.get("event_id") or "").strip()
        if event_id and row.get("home_team") and row.get("away_team"):
            out.setdefault((sport, event_id), (row["home_team"], row["away_team"]))
    return out


def resolve_event_teams(
    records: Iterable[Mapping[str, Any]],
    fetch: Any,
    *,
    today: str | None = None,
) -> tuple[dict[tuple[str, str], tuple[str, str]], int]:
    """Team names for unnamed score-gradeable records, from the served book grids.

    `fetch(day, sport, market)` returns a (sport, event_id) -> (home, away) map. Grids are tried
    on each record's KICKOFF date, then on the dates it was SIGHTED: a board date carries games
    for days ahead, and a late kickoff can sit only on the next date's grid (soccer's one 09-13
    final was on the 09-14 grid and not on 09-13's). Games that have not kicked off by `today`
    are not looked up, nor are events a sibling record already names. Returns (map, grids fetched).
    """
    named: set[tuple[str, str]] = set()
    missing: dict[str, set[str]] = collections.defaultdict(set)
    kickoff_days: dict[str, set[str]] = collections.defaultdict(set)
    sighted_days: dict[str, set[str]] = collections.defaultdict(set)
    for record in records:
        identity = parse_population_key(str(record.get("k") or ""))
        if not identity:
            continue
        sport = str(record.get("sport") or "").strip().lower()
        if record.get("ht") and record.get("at"):
            named.add((sport, identity["event_id"]))
            continue
        if identity["player_name"] or identity["market"] not in mbs.GRADABLE_MARKETS:
            continue
        if (identity["segment"] or "full") not in ("full", "full_game"):
            continue
        kickoff = SCORECARD.central_date(record.get("ct"))
        if not kickoff or (today is not None and kickoff > today):
            continue
        missing[sport].add(identity["event_id"])
        kickoff_days[sport].add(kickoff)
        sighted = SCORECARD.central_date(record.get("t"))
        if sighted and (today is None or sighted <= today):
            sighted_days[sport].add(sighted)

    out: dict[tuple[str, str], tuple[str, str]] = {}
    lookups = 0
    for sport in sorted(missing):
        still = {event for event in missing[sport] if (sport, event) not in named}
        grid_days = sorted(kickoff_days[sport]) + sorted(sighted_days[sport] - kickoff_days[sport])
        for day in grid_days:
            for market in TEAM_LOOKUP_MARKETS:
                if not still:
                    break
                found = fetch(day, sport, market) or {}
                lookups += 1
                for (found_sport, event), teams in found.items():
                    if found_sport == sport and event in still:
                        out[(sport, event)] = teams
                still -= {event for (named_sport, event) in out if named_sport == sport}
            if not still:
                break
    return out, lookups


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------


def scorecard_record(
    record: Mapping[str, Any],
    event_teams: Mapping[tuple[str, str], tuple[str, str]] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """The recorder record in the shape `layer2_live_scorecard.grade` / `match_chip` read."""
    identity = parse_population_key(str(record.get("k") or ""))
    if not identity:
        return None, "unparseable_key"
    sport = str(record.get("sport") or "").strip().lower()
    home, away = record.get("ht"), record.get("at")
    if not (home and away) and event_teams:
        teams = event_teams.get((sport, identity["event_id"]))
        if teams:
            home, away = teams
    return {
        "sport": sport,
        "event_id": identity["event_id"],
        "market": identity["market"],
        "segment": identity["segment"] or "full",
        "side": identity["side"],
        "line": identity["line"],
        "player_name": identity["player_name"],
        "home_team": home,
        "away_team": away,
        "commence_time": record.get("ct"),
        "price": record.get("px"),
    }, None


THREE_WAY_H2H_SPORTS = frozenset({"soccer"})


def settle_from_score(record: Mapping[str, Any], away_score: int, home_score: int) -> str | None:
    """'win' | 'loss' | 'push', or None: the scorecard's rules, plus what they get wrong or skip.

    - A 3-way moneyline (soccer `h2h` quotes home / draw / away): a draw is a RESULT, so home
      and away lose and the draw side wins. `layer2_live_scorecard.grade` calls it a push and
      cannot settle the draw side, which drops every drawn game from the measurement.
    - Both teams to score (`btts` yes / no), which a final score settles.
    """
    sport = str(record.get("sport") or "").strip().lower()
    market = str(record.get("market") or "").strip().lower()
    side = str(record.get("side") or "").strip().lower()
    if market == "h2h" and sport in THREE_WAY_H2H_SPORTS:
        if side == "draw":
            return "win" if away_score == home_score else "loss"
        if side in {"home", "away"} and away_score == home_score:
            return "loss"
    if market == "btts":
        if side not in {"yes", "no"}:
            return None
        return "win" if (away_score > 0 and home_score > 0) == (side == "yes") else "loss"
    return SCORECARD.grade(record, away_score, home_score)


def grade_population(
    records: Iterable[Mapping[str, Any]],
    chips_by_date: Mapping[str, Sequence[Mapping[str, Any]]],
    event_teams: Mapping[tuple[str, str], tuple[str, str]] | None = None,
    *,
    today: str | None = None,
    prop_settler: Any = None,
    ungraded_by_sport: dict[str, dict[str, int]] | None = None,
    score_source: Any = None,
    extra_settler: Any = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """One graded row per priced side, plus the count of what could not be graded and why.

    With `today` (a Central date), a kickoff after it is counted `not_started` before anything
    that needs a join, so an unplayed game does not read as a join failure.

    With `prop_settler(shaped) -> (result, reason)`, player props in `PROP_GRADED_SPORTS` are
    settled by it (MLB: `prop_outcomes.MlbPropGrader.settle`, from box scores) and graded like
    game lines, with their reasons prefixed `prop_`. Without it, and for every other sport, a
    prop is counted `player_prop`.

    With `extra_settler(shaped, view) -> None | (result, reason)` [lane `model-scorecard-cron`,
    2026-09-17], every record the settler HANDLES is settled by it before any of the skips
    below (props of other sports, segments, alternate / 3-way markets): `None` means "not
    mine" and the record takes the existing path unchanged, so passing no settler grades
    exactly what this function graded before. Its reasons are prefixed `extra_`.

    ONE SIGHTING PER PHASE. The earliest sighting is kept per (sport, key, phase), not per
    (sport, key): the recorder writes a side once pregame AND once live, and keeping only
    the earliest would silently drop every live row whose line never moved.
    """
    chosen: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    # The EARLIEST sighting is the one graded, and it can predate the recorder carrying team
    # names while a later sighting of the same event carries them: lend them across.
    named: dict[tuple[str, str], tuple[str, str]] = {}
    for record in records:
        key = (str(record.get("sport") or "").strip().lower(), str(record.get("k") or ""),
               mbs._phase(record.get("gs"), sighted_at=record.get("t"), commence_time=record.get("ct")))
        if not key[1]:
            continue
        if record.get("ht") and record.get("at"):
            identity = parse_population_key(key[1])
            if identity:
                named.setdefault((key[0], identity["event_id"]), (record["ht"], record["at"]))
        held = chosen.get(key)
        if held is None or str(record.get("t") or "") < str(held.get("t") or ""):
            chosen[key] = record
    event_teams = {**(event_teams or {}), **named}

    indexed = {day: SCORECARD.index_chips(list(chips)) for day, chips in chips_by_date.items()}
    graded: list[dict[str, Any]] = []
    ungraded: collections.Counter[str] = collections.Counter()
    by_sport: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    def skip(sport_name: str, reason: str) -> None:
        ungraded[reason] += 1
        by_sport[sport_name][reason] += 1

    for (sport, _key, _phase), record in chosen.items():
        view = mbs.view_from_record(record)
        shaped, reason = scorecard_record(record, event_teams)
        if shaped is None:
            skip(sport, reason or "unparseable_key")
            continue
        is_prop = bool(shaped["player_name"])
        handled = extra_settler(shaped, view) if extra_settler is not None else None
        if handled is not None:
            day = SCORECARD.central_date(shaped["commence_time"])
            if day and today is not None and day > today:
                skip(sport, "not_started")
                continue
            result, why = handled
            if result is None:
                skip(sport, f"extra_{why}" if why else "extra_unsettled")
                continue
        else:
            if is_prop and (prop_settler is None or sport not in PROP_GRADED_SPORTS):
                skip(sport, "player_prop")
                continue
            if not is_prop and view["market"] not in mbs.GRADABLE_MARKETS:
                skip(sport, "market_not_gradeable_from_score")
                continue
            if view["segment"] not in ("full", "full_game"):
                skip(sport, "segment_not_full_game")
                continue
            day = SCORECARD.central_date(shaped["commence_time"])
            if day and today is not None and day > today:
                skip(sport, "not_started")
                continue
            if is_prop:
                if not day:
                    skip(sport, "prop_no_commence_time")
                    continue
                result, why = prop_settler(shaped)
                if result is None:
                    skip(sport, f"prop_{why}" if why else "prop_unsettled")
                    continue
            else:
                if not (shaped["home_team"] and shaped["away_team"]):
                    skip(sport, "no_team_names")
                    continue
                if day and day in indexed:
                    chip, why = SCORECARD.match_chip(shaped, indexed[day].get(sport, []))
                else:
                    chip, why = None, "no_chips_for_kickoff_date"
                if chip is not None and chip["state"] != "final":
                    skip(sport, "game_not_final")
                    continue
                scores = chip["scores"] if chip is not None else None
                if scores is None and score_source is not None and sport in PROP_GRADED_SPORTS:
                    # The scoreboard served past MLB finals with null scores (2026-09-02: 15 of 15);
                    # the schedule's official final settles them, matched the way the prop grader matches.
                    scores, source_why = score_source(shaped)
                    if scores is None:
                        skip(sport, f"final_{source_why}" if source_why else "final_unavailable")
                        continue
                elif chip is None:
                    skip(sport, why or "no_chip_match")
                    continue
                elif scores is None:
                    skip(sport, "final_score_unparseable")
                    continue
                result = settle_from_score(shaped, *scores)
                if result is None:
                    skip(sport, "unsettleable_side_or_line")
                    continue
        if result == "push":
            skip(sport, "push")
            continue
        outcome = 1.0 if result == "win" else 0.0
        fair = view["fair_probability"]
        edge = view["model_edge_pct"]
        p_model = None
        if fair is not None and edge is not None:
            p_model = min(P_CEIL, max(P_FLOOR, fair + edge / 100.0))
        price = SCORECARD._as_float(shaped["price"])
        pnl = None
        if price is not None and price != 0:
            pnl = (SCORECARD.decimal_odds(price) - 1.0) if outcome else -1.0
        graded.append({
            "date": day,
            "sport": sport,
            "game": f"{sport}|{shaped['event_id']}",
            "buckets": mbs.bucket_ids(view),
            "y": outcome,
            "p_market": fair,
            "p_model": p_model,
            "model_edge_pct": edge,
            "pnl": pnl,
            # The price the side was offered at. `pnl` alone cannot say whether a row was +EV
            # against its fair (a loss is -1 at any price), so without this the price-shopping
            # edge -- the one that sizes live money -- cannot be graded at all.
            "price": price,
        })
    if ungraded_by_sport is not None:
        ungraded_by_sport.update({name: dict(counts) for name, counts in sorted(by_sport.items())})
    return graded, dict(ungraded)


# ---------------------------------------------------------------------------
# statistics
# ---------------------------------------------------------------------------


def bootstrap_mean(values: Sequence[float], *, resamples: int, seed: int) -> dict[str, float] | None:
    """Mean, 95% percentile CI and a two-sided bootstrap p over the given per-game values."""
    n = len(values)
    if n == 0:
        return None
    mean = sum(values) / n
    try:
        import numpy as np

        rng = np.random.default_rng(seed)
        arr = np.asarray(values, dtype=float)
        means = arr[rng.integers(0, n, size=(resamples, n))].mean(axis=1)
        means.sort()
        lower = float(means[int(0.025 * resamples)])
        upper = float(means[min(resamples - 1, int(0.975 * resamples))])
        at_or_below = float((means <= 0).mean())
        at_or_above = float((means >= 0).mean())
    except ImportError:
        rng = random.Random(seed)
        sampled = []
        for _ in range(resamples):
            sampled.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
        sampled.sort()
        lower = sampled[int(0.025 * resamples)]
        upper = sampled[min(resamples - 1, int(0.975 * resamples))]
        at_or_below = sum(1 for m in sampled if m <= 0) / resamples
        at_or_above = sum(1 for m in sampled if m >= 0) / resamples
    p_value = max(1.0 / resamples, min(1.0, 2.0 * min(at_or_below, at_or_above)))
    return {"mean": mean, "ci_lower": lower, "ci_upper": upper, "p": p_value}


def leave_one_date_out_stable(pairs: Sequence[tuple[str, float]]) -> bool:
    """True when the mean keeps its (non-zero) sign with EACH date removed in turn."""
    dates = sorted({day for day, _ in pairs})
    if len(dates) < 2:
        return False
    full = sum(value for _, value in pairs) / len(pairs)
    if full == 0:
        return False
    positive = full > 0
    for day in dates:
        rest = [value for other, value in pairs if other != day]
        if not rest:
            return False
        mean = sum(rest) / len(rest)
        if mean == 0 or (mean > 0) != positive:
            return False
    return True


def benjamini_hochberg(p_values: Sequence[float], q: float) -> set[int]:
    """Indices of the p-values that pass Benjamini-Hochberg at false discovery rate `q`."""
    m = len(p_values)
    if m == 0:
        return set()
    order = sorted(range(m), key=lambda i: p_values[i])
    passing = 0
    for rank, index in enumerate(order, start=1):
        if p_values[index] <= q * rank / m:
            passing = rank
    return {order[r] for r in range(passing)}


def _bucket_seed(seed: int, bucket_id: str, metric: str) -> int:
    return (seed + zlib.crc32(f"{bucket_id}|{metric}".encode("utf-8"))) % (2**32)


def evaluate_buckets(
    graded: Sequence[Mapping[str, Any]],
    *,
    min_games: int = MIN_GAMES,
    min_dates: int = MIN_DATES,
    resamples: int = RESAMPLES,
    seed: int = SEED,
    q: float = FDR_Q,
) -> list[dict[str, Any]]:
    per_bucket: dict[str, dict[str, dict[str, Any]]] = collections.defaultdict(dict)
    for row in graded:
        for bucket_id in row["buckets"]:
            game = per_bucket[bucket_id].setdefault(row["game"], {"date": row["date"], "diff": [], "market": [], "pnl": []})
            if row["p_model"] is not None and row["p_market"] is not None:
                game["diff"].append((row["p_model"] - row["y"]) ** 2 - (row["p_market"] - row["y"]) ** 2)
                game["market"].append((row["p_market"] - row["y"]) ** 2)
            if row["pnl"] is not None and (row["model_edge_pct"] or 0) > 0:
                game["pnl"].append(row["pnl"])

    results: list[dict[str, Any]] = []
    for bucket_id, games in sorted(per_bucket.items()):
        # SORTED, so a verdict is a function of the data and not of the order rows arrived in.
        # `bootstrap_mean` resamples by INDEX from a fixed seed, so the same values in another
        # order give another CI. Measured 2026-09-21 on production's scorecard state: 4 of 12
        # shuffles of the same games changed the validated set. `model_scorecard.evaluate_ids`
        # sorts the same way, which keeps the two evaluators in parity.
        skill_pairs = sorted((g["date"], sum(g["diff"]) / len(g["diff"])) for g in games.values() if g["diff"])
        market_means = [sum(g["market"]) / len(g["market"]) for g in games.values() if g["market"]]
        roi_pairs = sorted((g["date"], sum(g["pnl"]) / len(g["pnl"])) for g in games.values() if g["pnl"])
        result: dict[str, Any] = {
            "bucket_id": bucket_id,
            "games": len(skill_pairs),
            "dates": len({day for day, _ in skill_pairs}),
            "market_brier": (sum(market_means) / len(market_means)) if market_means else None,
            "roi_games": len(roi_pairs),
            "roi_dates": len({day for day, _ in roi_pairs}),
        }
        skill = bootstrap_mean([v for _, v in skill_pairs], resamples=resamples,
                               seed=_bucket_seed(seed, bucket_id, "skill")) if skill_pairs else None
        result["brier_diff"] = skill["mean"] if skill else None
        result["ci95"] = [skill["ci_lower"], skill["ci_upper"]] if skill else None
        result["p"] = skill["p"] if skill else None
        result["lodo_stable"] = leave_one_date_out_stable(skill_pairs) if skill_pairs else False
        roi = bootstrap_mean([v for _, v in roi_pairs], resamples=resamples,
                             seed=_bucket_seed(seed, bucket_id, "roi")) if roi_pairs else None
        result["roi_model_side"] = roi["mean"] if roi else None
        result["roi_ci95"] = [roi["ci_lower"], roi["ci_upper"]] if roi else None
        result["roi_p"] = roi["p"] if roi else None
        result["roi_lodo_stable"] = leave_one_date_out_stable(roi_pairs) if roi_pairs else False
        results.append(result)

    skill_eligible = [r for r in results if r["games"] >= min_games and r["dates"] >= min_dates and r["p"] is not None]
    skill_pass = benjamini_hochberg([r["p"] for r in skill_eligible], q)
    for index, result in enumerate(skill_eligible):
        result["fdr_pass"] = index in skill_pass
    roi_eligible = [r for r in results if r["roi_games"] >= min_games and r["roi_dates"] >= min_dates and r["roi_p"] is not None]
    roi_pass = benjamini_hochberg([r["roi_p"] for r in roi_eligible], q)
    for index, result in enumerate(roi_eligible):
        result["roi_fdr_pass"] = index in roi_pass

    for result in results:
        eligible = result["games"] >= min_games and result["dates"] >= min_dates and result["p"] is not None
        verdict = mbs.VERDICT_INSUFFICIENT
        if eligible:
            verdict = mbs.VERDICT_PARITY
            lower, upper = result["ci95"]
            if result.get("fdr_pass") and result["lodo_stable"] and (upper < 0 or lower > 0):
                verdict = mbs.VERDICT_SKILL_POCKET if upper < 0 else mbs.VERDICT_SKILL_LOSS
        result["verdict"] = verdict
        result["established_loss_rel"] = None
        if verdict == mbs.VERDICT_SKILL_LOSS and result["market_brier"]:
            result["established_loss_rel"] = round(max(0.0, result["ci95"][0]) / result["market_brier"], 5)
        result["profit_verdict"] = None
        if (result.get("roi_fdr_pass") and result["roi_lodo_stable"] and result["roi_ci95"]
                and result["roi_ci95"][0] > 0):
            result["profit_verdict"] = mbs.VERDICT_PROFIT_POCKET

    rank = {mbs.VERDICT_SKILL_POCKET: 0, mbs.VERDICT_SKILL_LOSS: 1, mbs.VERDICT_PARITY: 2, mbs.VERDICT_INSUFFICIENT: 3}
    results.sort(key=lambda r: (rank[r["verdict"]], r["p"] if r["p"] is not None else 2.0, r["bucket_id"]))
    return results


# ---------------------------------------------------------------------------
# output
# ---------------------------------------------------------------------------


def coverage(records: Sequence[Mapping[str, Any]], chips_by_date: Mapping[str, Any],
             graded: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    record_dates = sorted({d for d in (SCORECARD.central_date(r.get("ct")) for r in records) if d})
    chip_dates = sorted(chips_by_date)
    graded_dates = sorted({row["date"] for row in graded})
    return {
        "record_kickoff_dates": record_dates,
        "chip_dates": chip_dates,
        "intersection": sorted(set(record_dates) & set(chip_dates)),
        "graded_dates": graded_dates,
        "graded_rows": len(graded),
        "graded_games": len({row["game"] for row in graded}),
    }


def table_payload(results: Sequence[Mapping[str, Any]], *, window: str, method: Mapping[str, Any]) -> dict[str, Any]:
    buckets = {}
    for result in results:
        if result["verdict"] not in (mbs.VERDICT_SKILL_POCKET, mbs.VERDICT_SKILL_LOSS):
            continue
        buckets[result["bucket_id"]] = {
            "verdict": result["verdict"],
            "games": result["games"],
            "dates": result["dates"],
            "brier_diff": round(result["brier_diff"], 6),
            "ci95": [round(result["ci95"][0], 6), round(result["ci95"][1], 6)],
            "market_brier": round(result["market_brier"], 6) if result["market_brier"] else None,
            "established_loss_rel": result["established_loss_rel"],
        }
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": window,
        "method": dict(method),
        "buckets_tested": len(results),
        "buckets": buckets,
    }


def markdown_report(results: Sequence[Mapping[str, Any]], cov: Mapping[str, Any], ungraded: Mapping[str, int],
                    population: str = "recorder") -> str:
    lines = ["# Bucket search", ""]
    if population == "published":
        lines += [
            "> **PUBLISHED POPULATION: A PREVIEW, NOT SCORING-ELIGIBLE.** These are rows the shortlist ADMITTED, "
            "so every bucket is conditioned on publication. No verdict here reaches `measured_bucket_skill.json`.",
            "",
        ]
    lines += [
        f"Graded rows {cov['graded_rows']}, games {cov['graded_games']}, dates {len(cov['graded_dates'])} "
        f"({', '.join(cov['graded_dates'][:3])}{' ...' if len(cov['graded_dates']) > 3 else ''}).",
        f"Record kickoff dates {len(cov['record_kickoff_dates'])}, chip dates {len(cov['chip_dates'])}, "
        f"intersection {len(cov['intersection'])}.",
        f"Ungraded: {json.dumps(dict(sorted(ungraded.items())))}",
        "",
        "| bucket | verdict | games | dates | brier diff | 95% CI | p | LODO | FDR | ROI model side | ROI CI | profit |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        ci = r["ci95"]
        roi_ci = r["roi_ci95"]
        brier = "" if r["brier_diff"] is None else f"{r['brier_diff']:+.4f}"
        ci_text = "" if not ci else f"[{ci[0]:+.4f}, {ci[1]:+.4f}]"
        p_text = "" if r["p"] is None else f"{r['p']:.4f}"
        roi = "" if r["roi_model_side"] is None else f"{100 * r['roi_model_side']:+.1f}%"
        roi_ci_text = "" if not roi_ci else f"[{100 * roi_ci[0]:+.1f}%, {100 * roi_ci[1]:+.1f}%]"
        lines.append(
            f"| {r['bucket_id']} | {r['verdict']} | {r['games']} | {r['dates']} | {brier} | {ci_text} | "
            f"{p_text} | {r['lodo_stable']} | {r.get('fdr_pass', '')} | {roi} | {roi_ci_text} | "
            f"{r['profit_verdict'] or ''} |"
        )
    return "\n".join(lines) + "\n"


def _date_range(start: str, end: str) -> list[str]:
    first, last = date_cls.fromisoformat(start), date_cls.fromisoformat(end)
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--start", help="first board date (YYYY-MM-DD), production mode")
    parser.add_argument("--end", help="last board date (YYYY-MM-DD), production mode")
    parser.add_argument("--sports", default=",".join(SPORTS))
    parser.add_argument("--records-dir", help="offline: directory of recorder part files")
    parser.add_argument("--chips-dir", help="offline: directory of <date>.json game-chips payloads")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--env-file", help="a .env holding ADMIN_TOKEN (default: this checkout, then the main worktree)")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--min-games", type=int, default=MIN_GAMES)
    parser.add_argument("--min-dates", type=int, default=MIN_DATES)
    parser.add_argument("--resamples", type=int, default=RESAMPLES)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--fdr-q", type=float, default=FDR_Q)
    parser.add_argument("--population", choices=POPULATIONS, default="recorder",
                        help="recorder: the pre-publication population (scoring-eligible); "
                             "published: the clv_openings ledger (a PREVIEW, never written to the table)")
    parser.add_argument("--openings-dir", help="offline: directory of <date>.jsonl published-opening ledgers")
    parser.add_argument("--no-props", action="store_true",
                        help="do not read statsapi.mlb.com: no MLB prop grading from box scores, and no "
                             "schedule final score for an MLB game line whose scoreboard chip has none")
    parser.add_argument("--write-table", action="store_true",
                        help="write validated skill buckets to measured_bucket_skill.json (a behaviour change)")
    args = parser.parse_args(argv)
    if args.write_table and args.population != "recorder":
        parser.error("--write-table needs --population recorder: the published population is conditioned on "
                     "publication and can never set a scoring factor")
    if args.openings_dir and args.population != "published":
        parser.error("--openings-dir holds published openings; pass --population published")

    sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    event_teams: dict[tuple[str, str], tuple[str, str]] = {}
    prop_settler = score_source = None
    if not args.no_props:
        from syndicate.features.mlb.prop_outcomes import MlbPropGrader

        mlb_grader = MlbPropGrader(cache_dir=out_dir / "statsapi_cache")
        prop_settler, score_source = mlb_grader.settle, mlb_grader.final_score

    if args.records_dir or args.openings_dir:
        if args.openings_dir:
            records = records_from_openings(load_openings_dir(args.openings_dir))
        else:
            records = load_records_dir(args.records_dir)
        chips_by_date = load_chips_dir(args.chips_dir) if args.chips_dir else {}
        window = f"offline:{args.openings_dir or args.records_dir}"
    else:
        if not (args.start and args.end):
            parser.error("--start and --end are required unless --records-dir is given")
        token = _admin_token(args.env_file)
        if not token:
            searched = ", ".join(str(p) for p in env_file_candidates(args.env_file))
            parser.error(f"no ADMIN_TOKEN in the environment or in: {searched}")
        records = []
        days = _date_range(args.start, args.end)
        today = SCORECARD.central_date(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
        for day in days:
            if args.population == "published":
                openings = fetch_openings(args.base_url, token, day, cache_dir=out_dir / "openings_cache",
                                          complete=bool(today and day < today))
                day_records = [r for r in records_from_openings(openings) if r.get("sport") in sports]
                print(f"[bucket_search] OPENINGS day={day} openings={len(openings)} records={len(day_records)}",
                      flush=True)
            else:
                day_records = fetch_records(args.base_url, token, day, sports)
                print(f"[bucket_search] RECORDS day={day} records={len(day_records)}", flush=True)
            records.extend(day_records)
        event_teams, lookups = resolve_event_teams(
            records,
            lambda day, sport, market: fetch_event_teams(args.base_url, token, day, sport, market),
            today=today,
        )
        print(f"[bucket_search] TEAM_LOOKUPS grids={lookups} events_named={len(event_teams)}", flush=True)
        kickoff_days = sorted({d for d in (SCORECARD.central_date(r.get("ct")) for r in records)
                               if d and (today is None or d <= today)})
        chips_by_date = {day: SCORECARD.fetch_chips(args.base_url, day, None) for day in kickoff_days}
        window = f"{args.population}:{args.start}..{args.end}"

    now_central = SCORECARD.central_date(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    ungraded_by_sport: dict[str, dict[str, int]] = {}
    graded, ungraded = grade_population(records, chips_by_date, event_teams, today=now_central,
                                        prop_settler=prop_settler, ungraded_by_sport=ungraded_by_sport,
                                        score_source=score_source)
    cov = coverage(records, chips_by_date, graded)
    graded_by_sport = {
        sport_name: {"rows": sum(1 for row in graded if row["sport"] == sport_name),
                     "games": len({row["game"] for row in graded if row["sport"] == sport_name}),
                     "dates": len({row["date"] for row in graded if row["sport"] == sport_name})}
        for sport_name in sorted({row["sport"] for row in graded})
    }
    print("[bucket_search] COVERAGE " + json.dumps(cov, default=str), flush=True)
    print("[bucket_search] GRADED_BY_SPORT " + json.dumps(graded_by_sport), flush=True)
    print("[bucket_search] UNGRADED " + json.dumps(ungraded), flush=True)
    print("[bucket_search] UNGRADED_BY_SPORT " + json.dumps(ungraded_by_sport), flush=True)
    results = evaluate_buckets(graded, min_games=args.min_games, min_dates=args.min_dates,
                               resamples=args.resamples, seed=args.seed, q=args.fdr_q)
    method = {"min_games": args.min_games, "min_dates": args.min_dates, "resamples": args.resamples,
              "seed": args.seed, "fdr_q": args.fdr_q, "unit": "game",
              "skill_metric": "brier(model)-brier(market) on the side", "profit_metric": "flat 1u ROI, model side",
              "props": "none" if prop_settler is None else "mlb via statsapi box scores",
              "phase": "game_state when present, else sighted before/after commence"}
    report = {"population": args.population, "scoring_eligible": args.population == "recorder",
              "window": window, "method": method, "coverage": cov, "graded_by_sport": graded_by_sport,
              "ungraded": ungraded, "ungraded_by_sport": ungraded_by_sport, "buckets": results}
    (out_dir / "bucket_search_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out_dir / "bucket_search_report.md").write_text(markdown_report(results, cov, ungraded, args.population),
                                                     encoding="utf-8")
    counts = collections.Counter(r["verdict"] for r in results)
    profit = sum(1 for r in results if r["profit_verdict"])
    print(f"[bucket_search] VERDICTS {dict(counts)} profit_pockets={profit} report={out_dir}", flush=True)
    if args.write_table:
        mbs.TABLE_PATH.write_text(json.dumps(table_payload(results, window=window, method=method), indent=2) + "\n",
                                  encoding="utf-8")
        print(f"[bucket_search] TABLE_WRITTEN {mbs.TABLE_PATH}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
