"""The daily model scorecard: model vs market vs outcome over the Layer 2 PRICED population.

Lane `model-scorecard-cron` `[2026-09-17]`. The user asked whether anything backtests the
models on the active sports daily/weekly, for game lines and props, pregame and live. The
measured answer was no: the 2026-09-14 assessment table was a one-off made by hand, and
`scripts/bucket_search.py` only ran when someone ran it. This module is the scheduled form.

WHAT IS MEASURED. Every side the board PRICED (`opportunity_population_ledger`), never the
published subset -- the 2026-09-12 FORBIDDEN rule, because a publication filter freezes a
metric instead of shrinking it. Graded by `bucket_search.grade_population` (its own rules,
imported) plus the per-sport settlers in `population_outcomes`. For each cell
sport x market x segment x phase, and for each pre-registered bucket inside it:

    brier_diff = Brier(model) - Brier(market) on the side's probability, per GAME
    (positive = the model is worse), with a seeded 95% bootstrap CI over games,
    leave-one-date-out stability and Benjamini-Hochberg across the family.

THE VERDICT LOGIC IS `bucket_search.evaluate_buckets`'s, reproduced over per-game SUMS so
a month of history fits in a small state file. `tests/test_model_scorecard.py` holds the
two to identical output on the same graded rows; a second copy that drifts is the defect
this repo keeps paying for, so that parity test is the contract.

INCREMENTAL, BECAUSE A CRON HAS NO DISK AND WEB'S EXPORTS ARE SLOW. A game is graded ONCE,
when it is final, and only its per-bucket sums are kept; the raw records of games not yet
final ride along in the state between runs. So a daily run fetches only the board dates
that can still change instead of re-reading a month of recorder parts (15-38 s per export
on web, which has OOM'd on export bursts).

NO POOLING ACROSS GRADER VERSIONS (2026-09-01 FORBIDDEN rule). The state carries the grader
signature; when it changes, history is RESET and rebuilt from the recorder, and the
scorecard says so. Every payload names the versions that produced it.

TWO THRESHOLDS, ON PURPOSE.
- The REPORT (category cells) uses `REPORT_MIN_GAMES` / `REPORT_MIN_DATES`: NFL plays 16
  games a week and a scorecard that says "insufficient" for a season is useless to read.
- The OVERLAY, which moves Layer 2 scores, uses `bucket_search`'s own MIN_GAMES / MIN_DATES
  / FDR_Q unchanged. A looser bar never reaches scoring.
"""

from __future__ import annotations

import collections
import gzip
import importlib.util
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date as date_cls, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from syndicate.features.shared import measured_bucket_skill as mbs
from syndicate.features.shared import skill_overlay
from syndicate.features.shared.opportunity_population_ledger import parse_population_key

SCORECARD_VERSION = "model_scorecard/1"
REPORT_DIR = "reports/model_scorecard"
# GZIPPED. Measured 2026-09-17: the plain state was 33.9 MB, and web (which sits at 1.6-1.9 GB of its
# 2 GiB limit) was OOM-killed at 16:36:52Z seconds into a cron run that streamed it back. gzip took the
# same state to ~2.5 MB on the wire; this keeps it that size on web's disk and in every read.
STATE_PATH = f"{REPORT_DIR}/state/scorecard_state.json.gz"
LATEST_PATH = f"{REPORT_DIR}/model_scorecard_latest.json"
OVERLAY_PATH = skill_overlay.OVERLAY_PATH
RECORDER_START = "2026-09-14"
WINDOWS = (7, 28)
RETAIN_DAYS = 35
FORCE_COMMIT_AFTER_DAYS = 3
BOARD_DATE_COMPLETE_AFTER_DAYS = 2
REPORT_MIN_GAMES = 15
REPORT_MIN_DATES = 3
MAX_OVERLAY_BUCKETS = 100
OVERLAY_TTL_HOURS = 72
KEEP_FIELDS = ("k", "t", "sport", "ct", "ht", "at", "px", "fp", "fm", "bq", "ba", "me", "gs")
NOT_FINAL_MARKERS = ("not_final", "not_started", "not_complete", "no_chips_for_kickoff_date", "in_progress",
                     "unavailable", "not_in_live_state")

VERDICT_NAMES = {
    mbs.VERDICT_SKILL_POCKET: "beats_market",
    mbs.VERDICT_SKILL_LOSS: "loses_to_market",
    mbs.VERDICT_PARITY: "parity",
    mbs.VERDICT_INSUFFICIENT: "insufficient",
}


def scorecard_path(day: str) -> str:
    # No ISO date in the NAME: the workers' `pull_hot_artifacts(*<date>*)` would otherwise copy
    # every day's scorecard onto both worker disks on every cycle.
    return f"{REPORT_DIR}/model_scorecard_{day.replace('-', '')}.json"


def markdown_path(day: str) -> str:
    return f"{REPORT_DIR}/model_scorecard_{day.replace('-', '')}.md"


def load_bucket_search() -> Any:
    """`scripts/bucket_search.py` as a module -- the grader and the statistics, imported."""
    source = Path(__file__).resolve().parents[3] / "scripts" / "bucket_search.py"
    spec = importlib.util.spec_from_file_location("bucket_search", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# records
# ---------------------------------------------------------------------------


def strip_record(record: Mapping[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in KEEP_FIELDS if record.get(field) is not None}


def game_key(record: Mapping[str, Any]) -> str | None:
    identity = parse_population_key(str(record.get("k") or ""))
    sport = str(record.get("sport") or "").strip().lower()
    if not identity or not sport or not identity.get("event_id"):
        return None
    return f"{sport}|{identity['event_id']}"


def record_identity(record: Mapping[str, Any]) -> tuple[str, str, str]:
    phase = mbs._phase(record.get("gs"), sighted_at=record.get("t"), commence_time=record.get("ct"))
    return str(record.get("k") or ""), phase, str(record.get("t") or "")


def central_today(now: datetime, central_date: Callable[[Any], str | None]) -> str:
    today = central_date(now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return today or now.date().isoformat()


def _shift(day: str, days: int) -> str:
    return (date_cls.fromisoformat(day) + timedelta(days=days)).isoformat()


def _is_not_final(reason: str) -> bool:
    return any(marker in reason for marker in NOT_FINAL_MARKERS)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------


def empty_state(grader_signature: str, sport_versions: Mapping[str, str] | None = None) -> dict[str, Any]:
    return {
        "version": SCORECARD_VERSION,
        "grader_signature": grader_signature,
        "sport_versions": dict(sport_versions or {}),
        "board_dates": {},
        "pending": {},
        "games": {},
        "ungraded": {},
        "late_records": 0,
        "resets": [],
    }


def load_state(payload: Any, grader_signature: str, *, now: datetime,
               sport_versions: Mapping[str, str] | None = None) -> tuple[dict[str, Any], str | None]:
    """The saved state, or a fresh one. Returns (state, reset_reason or None).

    TWO LEVELS OF RESET, so a new settler does not erase every sport's history.
    - `grader_signature` is the code EVERY sport grades through (`grade_population` and the
      rules it imports). When it changes, all history resets.
    - `sport_versions` maps each sport to the settler that owns it. When only those change, the
      games and ungraded counts of the CHANGED sports are dropped and every retained board date
      is marked incomplete, so the next runs refetch the recorder and regrade exactly those
      sports; games of the other sports are kept (their re-fetched records count as `late`).
    """
    sport_versions = dict(sport_versions or {})
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if not isinstance(payload, Mapping) or payload.get("version") != SCORECARD_VERSION:
        reason = None if payload is None else "state_version_changed"
        return empty_state(grader_signature, sport_versions), reason
    if payload.get("grader_signature") != grader_signature:
        state = empty_state(grader_signature, sport_versions)
        state["resets"] = list(payload.get("resets") or [])[-9:] + [{
            "at": stamp,
            "from": payload.get("grader_signature"),
            "to": grader_signature,
        }]
        return state, "grader_signature_changed"
    state = empty_state(grader_signature, sport_versions)
    for field in ("board_dates", "pending", "games", "ungraded"):
        if isinstance(payload.get(field), Mapping):
            state[field] = {key: value for key, value in payload[field].items()}
    state["late_records"] = int(payload.get("late_records") or 0)
    state["resets"] = list(payload.get("resets") or [])
    saved_versions = dict(payload.get("sport_versions") or {})
    changed = sorted(sport for sport in set(saved_versions) | set(sport_versions)
                     if saved_versions.get(sport) != sport_versions.get(sport))
    if not changed:
        return state, None
    dropped = [key for key, game in state["games"].items() if str(game.get("sport")) in changed]
    for key in dropped:
        del state["games"][key]
    for day, sports in list(state["ungraded"].items()):
        state["ungraded"][day] = {sport: reasons for sport, reasons in sports.items() if sport not in changed}
    for entry in state["board_dates"].values():
        entry["complete"] = False
    state["resets"] = state["resets"][-9:] + [{
        "at": stamp,
        "sports": changed,
        "from": {sport: saved_versions.get(sport) for sport in changed},
        "to": {sport: sport_versions.get(sport) for sport in changed},
        "games_dropped": len(dropped),
    }]
    return state, "sport_versions_changed:" + ",".join(changed)


def board_dates_to_fetch(state: Mapping[str, Any], today: str, *, limit: int) -> list[str]:
    """Today and yesterday always; then any board date in the retain window not yet complete, oldest first."""
    first = max(RECORDER_START, _shift(today, -RETAIN_DAYS))
    wanted: list[str] = []
    for day in (today, _shift(today, -1)):
        if day >= first and day not in wanted:
            wanted.append(day)
    day = first
    while day < _shift(today, -1):
        entry = state["board_dates"].get(day)
        if not entry or not entry.get("complete"):
            wanted.append(day)
        day = _shift(day, 1)
    return wanted[:max(2, limit)]


def merge_board_date(state: dict[str, Any], day: str, records: Iterable[Mapping[str, Any]], *,
                     today: str, central_date: Callable[[Any], str | None], fetched_at: str) -> dict[str, int]:
    """Fold one board date's records into `pending`. Records of already-graded games are counted late."""
    counts = collections.Counter()
    seen: dict[str, set[tuple[str, str, str]]] = {}
    for record in records:
        key = game_key(record)
        if key is None:
            counts["unkeyable"] += 1
            continue
        if key in state["games"]:
            counts["late"] += 1
            continue
        bucket = state["pending"].setdefault(key, [])
        if key not in seen:
            seen[key] = {record_identity(held) for held in bucket}
        identity = record_identity(record)
        if identity in seen[key]:
            counts["duplicate"] += 1
            continue
        seen[key].add(identity)
        bucket.append(strip_record(record))
        counts["added"] += 1
    state["late_records"] = int(state.get("late_records") or 0) + counts["late"]
    state["board_dates"][day] = {
        "fetched_at": fetched_at,
        "records": sum(counts.values()),
        "complete": day <= _shift(today, -BOARD_DATE_COMPLETE_AFTER_DAYS),
    }
    return dict(counts)


# ---------------------------------------------------------------------------
# grading
# ---------------------------------------------------------------------------


def _accumulate(ids: dict[str, list[float]], row: Mapping[str, Any]) -> None:
    buckets = list(row.get("buckets") or [])
    if not buckets:
        return
    prefix = "|".join(buckets[0].split("|")[:4])
    p_model, p_market, y = row.get("p_model"), row.get("p_market"), row.get("y")
    for bucket_id in [prefix, *buckets]:
        acc = ids.setdefault(bucket_id, [0.0, 0, 0.0, 0.0, 0.0, 0])
        if p_model is not None and p_market is not None and y is not None:
            acc[0] += (p_model - y) ** 2 - (p_market - y) ** 2
            acc[1] += 1
            acc[2] += (p_market - y) ** 2
            acc[3] += (p_model - y) ** 2
        if row.get("pnl") is not None and (row.get("model_edge_pct") or 0) > 0:
            acc[4] += row["pnl"]
            acc[5] += 1


def grade_pending(
    state: dict[str, Any],
    *,
    today: str,
    grade: Callable[..., tuple[list[dict[str, Any]], dict[str, int]]],
    chips_for: Callable[[str], Sequence[Mapping[str, Any]]],
    central_date: Callable[[Any], str | None],
) -> dict[str, int]:
    """Grade every pending game whose kickoff date has passed; commit it once nothing is still not final.

    `grade(records, chips_by_date, today=..., ungraded_by_sport=...)` is `grade_population` with
    its settlers bound. A game with any not-final reason stays pending until
    `FORCE_COMMIT_AFTER_DAYS` after kickoff, then commits what did grade.
    """
    counts = collections.Counter()
    chips_cache: dict[str, Sequence[Mapping[str, Any]]] = {}
    for key in sorted(state["pending"]):
        records = state["pending"][key]
        kickoff = next((d for d in (central_date(r.get("ct")) for r in records) if d), None)
        if kickoff is None:
            if all(str(r.get("t") or "")[:10] < _shift(today, -RETAIN_DAYS) for r in records):
                del state["pending"][key]
                counts["dropped_no_kickoff"] += 1
            continue
        if kickoff >= today:
            counts["not_yet"] += 1
            continue
        if kickoff not in chips_cache:
            try:
                chips_cache[kickoff] = list(chips_for(kickoff) or [])
            except Exception as exc:
                # A scoreboard we could not READ is not a scoreboard with no games: grading now would
                # count every game line `no_chip_match` and commit the game with those rows lost.
                print(f"[model_scorecard] CHIPS_UNAVAILABLE {kickoff} {type(exc).__name__}: {exc}", flush=True)
                chips_cache[kickoff] = None
        if chips_cache[kickoff] is None:
            counts["chips_unavailable"] += 1
            continue
        by_sport: dict[str, dict[str, int]] = {}
        graded, ungraded = grade(records, {kickoff: chips_cache[kickoff]}, today=today, ungraded_by_sport=by_sport)
        still_open = any(_is_not_final(reason) for reason in ungraded)
        if still_open and kickoff > _shift(today, -FORCE_COMMIT_AFTER_DAYS):
            counts["waiting_for_final"] += 1
            continue
        ids: dict[str, list[float]] = {}
        for row in graded:
            _accumulate(ids, row)
        sport = key.split("|", 1)[0]
        state["games"][key] = {"date": kickoff, "sport": sport, "rows": len(graded), "ids": ids}
        day_counts = state["ungraded"].setdefault(kickoff, {})
        for sport_name, reasons in by_sport.items():
            target = day_counts.setdefault(sport_name, {})
            for reason, n in reasons.items():
                target[reason] = int(target.get(reason, 0)) + int(n)
        del state["pending"][key]
        counts["committed"] += 1
        counts["committed_forced" if still_open else "committed_final"] += 1
    return dict(counts)


def prune(state: dict[str, Any], today: str) -> None:
    floor = _shift(today, -RETAIN_DAYS)
    state["games"] = {key: game for key, game in state["games"].items() if str(game.get("date") or "") >= floor}
    state["ungraded"] = {day: value for day, value in state["ungraded"].items() if day >= floor}
    state["board_dates"] = {day: value for day, value in state["board_dates"].items() if day >= floor}


# ---------------------------------------------------------------------------
# evaluation -- bucket_search.evaluate_buckets over per-game sums
# ---------------------------------------------------------------------------


def evaluate_ids(
    games: Iterable[Mapping[str, Any]],
    *,
    bs: Any,
    select: Callable[[str], bool],
    min_games: int,
    min_dates: int,
    resamples: int,
    seed: int,
    q: float,
) -> list[dict[str, Any]]:
    per_id: dict[str, list[tuple[str, list[float]]]] = collections.defaultdict(list)
    for game in games:
        for bucket_id, acc in (game.get("ids") or {}).items():
            if select(bucket_id):
                per_id[bucket_id].append((str(game.get("date")), acc))

    results: list[dict[str, Any]] = []
    for bucket_id, entries in sorted(per_id.items()):
        skill_pairs = [(day, acc[0] / acc[1]) for day, acc in entries if acc[1]]
        market_means = [acc[2] / acc[1] for _day, acc in entries if acc[1]]
        model_means = [acc[3] / acc[1] for _day, acc in entries if acc[1]]
        roi_pairs = [(day, acc[4] / acc[5]) for day, acc in entries if acc[5]]
        result: dict[str, Any] = {
            "bucket_id": bucket_id,
            "games": len(skill_pairs),
            "dates": len({day for day, _ in skill_pairs}),
            "market_brier": (sum(market_means) / len(market_means)) if market_means else None,
            "model_brier": (sum(model_means) / len(model_means)) if model_means else None,
            "roi_games": len(roi_pairs),
            "roi_dates": len({day for day, _ in roi_pairs}),
        }
        skill = bs.bootstrap_mean([v for _, v in skill_pairs], resamples=resamples,
                                  seed=bs._bucket_seed(seed, bucket_id, "skill")) if skill_pairs else None
        result["brier_diff"] = skill["mean"] if skill else None
        result["ci95"] = [skill["ci_lower"], skill["ci_upper"]] if skill else None
        result["p"] = skill["p"] if skill else None
        result["lodo_stable"] = bs.leave_one_date_out_stable(skill_pairs) if skill_pairs else False
        roi = bs.bootstrap_mean([v for _, v in roi_pairs], resamples=resamples,
                                seed=bs._bucket_seed(seed, bucket_id, "roi")) if roi_pairs else None
        result["roi_model_side"] = roi["mean"] if roi else None
        result["roi_ci95"] = [roi["ci_lower"], roi["ci_upper"]] if roi else None
        result["roi_p"] = roi["p"] if roi else None
        result["roi_lodo_stable"] = bs.leave_one_date_out_stable(roi_pairs) if roi_pairs else False
        results.append(result)

    skill_eligible = [r for r in results if r["games"] >= min_games and r["dates"] >= min_dates and r["p"] is not None]
    skill_pass = bs.benjamini_hochberg([r["p"] for r in skill_eligible], q)
    for index, result in enumerate(skill_eligible):
        result["fdr_pass"] = index in skill_pass
    roi_eligible = [r for r in results
                    if r["roi_games"] >= min_games and r["roi_dates"] >= min_dates and r["roi_p"] is not None]
    roi_pass = bs.benjamini_hochberg([r["roi_p"] for r in roi_eligible], q)
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


def is_cell(bucket_id: str) -> bool:
    return bucket_id.count("|") == 3


def is_bucket(bucket_id: str) -> bool:
    return bucket_id.count("|") == 4


def _round(value: Any, digits: int = 6) -> Any:
    return round(value, digits) if isinstance(value, float) else value


def cell_row(result: Mapping[str, Any]) -> dict[str, Any]:
    sport, market, segment, phase = result["bucket_id"].split("|")
    return {
        "sport": sport, "market": market, "segment": segment, "phase": phase,
        "games": result["games"], "dates": result["dates"],
        "model_brier": _round(result["model_brier"]), "market_brier": _round(result["market_brier"]),
        "brier_diff": _round(result["brier_diff"]),
        "ci95": [_round(v) for v in result["ci95"]] if result["ci95"] else None,
        "p": _round(result["p"], 5),
        "lodo_stable": result["lodo_stable"],
        "verdict": VERDICT_NAMES[result["verdict"]],
        "roi_model_side": _round(result["roi_model_side"], 5),
        "roi_ci95": [_round(v, 5) for v in result["roi_ci95"]] if result["roi_ci95"] else None,
        "roi_games": result["roi_games"],
    }


def window_games(state: Mapping[str, Any], today: str, days: int) -> list[Mapping[str, Any]]:
    first = _shift(today, -days)
    return [game for game in state["games"].values() if first <= str(game.get("date") or "") < today]


def window_span(today: str, days: int) -> dict[str, Any]:
    """Whether a window's LABEL is backed by the history it claims.

    A `28d` heading over 6 days of population is a claim the data does not support, and
    until 2026-09-20 nothing said so: `7d` and `28d` were serving byte-identical cells
    (263 each) because the recorder started 2026-09-14, and both were presented as if
    they were two different measurements.

    `effective_days` is what the recorder can actually back. `degraded` is a fact about
    COVERAGE, not an error -- an under-backed window is still the best available reading,
    it just must not be quoted as a 28-day result.
    """
    first = _shift(today, -days)
    backed_from = max(first, RECORDER_START)
    effective = max(0, (date_cls.fromisoformat(today) - date_cls.fromisoformat(backed_from)).days)
    degraded = effective < days
    return {
        "nominal_days": days,
        "effective_days": effective,
        "backed_from": backed_from,
        "degraded": degraded,
        "degraded_reason": (
            f"the recorder started {RECORDER_START}, so this window is backed by "
            f"{effective}d of population, not {days}d"
        ) if degraded else None,
    }


def coverage(state: Mapping[str, Any], games: Sequence[Mapping[str, Any]], today: str, days: int) -> dict[str, Any]:
    first = _shift(today, -days)
    by_sport: dict[str, dict[str, Any]] = {}
    for game in games:
        entry = by_sport.setdefault(str(game.get("sport")), {"games": 0, "rows": 0, "dates": set()})
        entry["games"] += 1
        entry["rows"] += int(game.get("rows") or 0)
        entry["dates"].add(str(game.get("date")))
    ungraded: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for day, sports in state["ungraded"].items():
        if first <= day < today:
            for sport, reasons in sports.items():
                ungraded[sport].update({reason: int(n) for reason, n in reasons.items()})
    # A RATE, not a count. `2,887 player_not_in_box` is unreadable until you know it sits
    # against 14,319 graded rows (11.5%) -- and the worst COUNT is routinely not the worst
    # RATE: on 2026-09-20 mlb's 2,866 was 4.6% while wnba's 596 was 5.4%. The denominator is
    # every row the grader CONSIDERED for that sport, so a sport's reasons sum to its
    # `ungraded_rate` and the number is comparable ACROSS sports of very different sizes.
    rates: dict[str, dict[str, Any]] = {}
    for sport, counter in sorted(ungraded.items()):
        graded_rows = int((by_sport.get(sport) or {}).get("rows") or 0)
        total_ungraded = int(sum(counter.values()))
        considered = graded_rows + total_ungraded
        if not considered:
            continue
        rates[sport] = {
            "considered_rows": considered,
            "graded_rows": graded_rows,
            "ungraded_rows": total_ungraded,
            "ungraded_rate": _round(total_ungraded / considered, 5),
            "by_reason": {reason: _round(count / considered, 5) for reason, count in counter.most_common()},
        }

    return {
        "kickoff_dates": [first, _shift(today, -1)],
        "recorder_start": RECORDER_START,
        "dates_with_graded_games": len({str(g.get("date")) for g in games}),
        "window_span": window_span(today, days),
        "by_sport": {sport: {"games": v["games"], "graded_rows": v["rows"], "dates": len(v["dates"])}
                     for sport, v in sorted(by_sport.items())},
        "ungraded_by_sport": {sport: dict(counter.most_common()) for sport, counter in sorted(ungraded.items())},
        "ungraded_rate_by_sport": rates,
    }


def overlay_payload(bucket_results: Sequence[Mapping[str, Any]], *, now: datetime, window: str,
                    method: Mapping[str, Any], grader: Mapping[str, Any]) -> dict[str, Any]:
    """VALIDATED buckets only, in `measured_bucket_skill.load_table`'s shape, capped and dated."""
    validated = [r for r in bucket_results if r["verdict"] in (mbs.VERDICT_SKILL_POCKET, mbs.VERDICT_SKILL_LOSS)]
    validated.sort(key=lambda r: (r["p"] if r["p"] is not None else 2.0, r["bucket_id"]))
    kept = validated[:MAX_OVERLAY_BUCKETS]
    buckets = {
        r["bucket_id"]: {
            "verdict": r["verdict"],
            "games": r["games"],
            "dates": r["dates"],
            "brier_diff": round(r["brier_diff"], 6),
            "ci95": [round(r["ci95"][0], 6), round(r["ci95"][1], 6)],
            "market_brier": round(r["market_brier"], 6) if r["market_brier"] else None,
            "established_loss_rel": r["established_loss_rel"],
        }
        for r in kept
    }
    return {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (now + timedelta(hours=OVERLAY_TTL_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": SCORECARD_VERSION,
        "window": window,
        "method": dict(method),
        "grader": dict(grader),
        "buckets_tested": len(bucket_results),
        "buckets_validated": len(validated),
        "buckets_capped": max(0, len(validated) - len(kept)),
        "buckets": buckets,
    }


def overlay_diff(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> dict[str, Any]:
    before = dict((previous or {}).get("buckets") or {})
    after = dict(current.get("buckets") or {})
    changed = sorted(k for k in set(before) & set(after) if before[k].get("verdict") != after[k].get("verdict"))
    return {
        "added": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "verdict_changed": changed,
    }


def verdict_changes(previous: Mapping[str, Any] | None, cells: Sequence[Mapping[str, Any]], window: str) -> list[dict[str, Any]]:
    """Cells whose verdict differs from the previous scorecard's same window."""
    old = {}
    for cell in ((previous or {}).get("windows") or {}).get(window, {}).get("cells") or []:
        old["|".join((cell["sport"], cell["market"], cell["segment"], cell["phase"]))] = cell.get("verdict")
    out = []
    for cell in cells:
        key = "|".join((cell["sport"], cell["market"], cell["segment"], cell["phase"]))
        if key in old and old[key] != cell["verdict"]:
            out.append({"cell": key, "from": old[key], "to": cell["verdict"]})
    return out


def build_scorecard(
    state: Mapping[str, Any],
    *,
    bs: Any,
    today: str,
    now: datetime,
    grader: Mapping[str, Any],
    run: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    resamples: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(scorecard, overlay). Pure: everything it reads is in `state`."""
    resamples = int(resamples or bs.RESAMPLES)
    windows: dict[str, Any] = {}
    bucket_results: list[dict[str, Any]] = []
    for days in WINDOWS:
        games = window_games(state, today, days)
        cells = evaluate_ids(games, bs=bs, select=is_cell, min_games=REPORT_MIN_GAMES, min_dates=REPORT_MIN_DATES,
                             resamples=resamples, seed=bs.SEED, q=bs.FDR_Q)
        rows = [cell_row(r) for r in cells]
        label = f"{days}d"
        windows[label] = {
            "coverage": coverage(state, games, today, days),
            "cells": rows,
            "verdict_changes": verdict_changes(previous, rows, label),
        }
        if days == max(WINDOWS):
            bucket_results = evaluate_ids(games, bs=bs, select=is_bucket, min_games=bs.MIN_GAMES,
                                          min_dates=bs.MIN_DATES, resamples=resamples, seed=bs.SEED, q=bs.FDR_Q)
    longest = f"{max(WINDOWS)}d"
    method = {"unit": "game", "skill_metric": "brier(model)-brier(market) on the side, per game",
              "report_min_games": REPORT_MIN_GAMES, "report_min_dates": REPORT_MIN_DATES,
              "overlay_min_games": bs.MIN_GAMES, "overlay_min_dates": bs.MIN_DATES, "fdr_q": bs.FDR_Q,
              "resamples": resamples, "seed": bs.SEED, "population": "opportunity_population_ledger (priced, not published)"}
    overlay = overlay_payload(bucket_results, now=now, window=f"{longest} to {today}", method=method, grader=grader)
    counts = collections.Counter(r["verdict"] for r in bucket_results)
    scorecard = {
        "version": SCORECARD_VERSION,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "today_central": today,
        "grader": dict(grader),
        "method": method,
        "run": dict(run),
        "windows": windows,
        "buckets": {"tested": len(bucket_results),
                    "verdicts": {VERDICT_NAMES[k]: v for k, v in counts.items()},
                    "profit_pockets_reported_not_scored": sum(1 for r in bucket_results if r["profit_verdict"])},
        "overlay": {"buckets": len(overlay["buckets"]), "validated": overlay["buckets_validated"],
                    "capped": overlay["buckets_capped"], "expires_at": overlay["expires_at"]},
        "state": {"pending_games": len(state["pending"]), "graded_games": len(state["games"]),
                  "late_records": state.get("late_records", 0), "resets": list(state.get("resets") or [])[-3:]},
    }
    return scorecard, overlay


def markdown(scorecard: Mapping[str, Any]) -> str:
    lines = [f"# Model scorecard {scorecard['today_central']}", "",
             f"Generated {scorecard['generated_at']} by {scorecard['version']}. Population: the Layer 2 PRICED "
             "population (recorder), graded per game. brier_diff > 0 means the model is WORSE than the market.", ""]
    for label, window in scorecard["windows"].items():
        cov = window["coverage"]
        lines.append(f"## {label}: kickoff {cov['kickoff_dates'][0]}..{cov['kickoff_dates'][1]} "
                     f"({cov['dates_with_graded_games']} dates with graded games)")
        lines.append("")
        span = cov.get("window_span") or {}
        if span.get("degraded"):
            lines.append(f"> **DEGRADED WINDOW** -- {span.get('degraded_reason')}. Do not quote this as a "
                         f"{span.get('nominal_days')}-day result.")
            lines.append("")
        for sport, entry in cov["by_sport"].items():
            rate = (cov.get("ungraded_rate_by_sport") or {}).get(sport) or {}
            suffix = (f", {rate['ungraded_rate']:.1%} ungraded ({rate['ungraded_rows']} of "
                      f"{rate['considered_rows']} considered)") if rate else ""
            lines.append(f"- {sport}: {entry['games']} games, {entry['graded_rows']} graded rows, "
                         f"{entry['dates']} dates{suffix}")
        lines.append("")
        lines.append("| sport | market | segment | phase | games | dates | model Brier | market Brier | diff [95% CI] | verdict |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for cell in sorted(window["cells"], key=lambda c: (c["sport"], c["phase"], c["segment"], c["market"])):
            ci = cell["ci95"]
            diff = "" if cell["brier_diff"] is None else f"{cell['brier_diff']:+.4f} [{ci[0]:+.4f}, {ci[1]:+.4f}]"
            model = "" if cell["model_brier"] is None else f"{cell['model_brier']:.4f}"
            market = "" if cell["market_brier"] is None else f"{cell['market_brier']:.4f}"
            lines.append(f"| {cell['sport']} | {cell['market']} | {cell['segment']} | {cell['phase']} | {cell['games']} | "
                         f"{cell['dates']} | {model} | {market} | {diff} | {cell['verdict']} |")
        if window["verdict_changes"]:
            lines += ["", "Verdict changes since the previous scorecard:"]
            lines += [f"- {c['cell']}: {c['from']} -> {c['to']}" for c in window["verdict_changes"]]
        lines.append("")
    overlay = scorecard["overlay"]
    lines.append(f"Scoring overlay: {overlay['buckets']} validated buckets (of {scorecard['buckets']['tested']} tested; "
                 f"{overlay['capped']} capped), expires {overlay['expires_at']}.")
    return "\n".join(lines) + "\n"


def dumps(payload: Any) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, default=str)


def encode_state(state: Mapping[str, Any]) -> bytes:
    return gzip.compress(dumps(state).encode("utf-8"), compresslevel=6, mtime=0)


def decode_state(blob: bytes | None) -> Any:
    """The saved state from web, whether the transport already un-gzipped it or not. None when absent."""
    if blob is None:
        return None
    if blob[:2] == b"\x1f\x8b":
        blob = gzip.decompress(blob)
    return json.loads(blob.decode("utf-8"))
