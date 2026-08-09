"""End-to-end diagnostic for the odds/betting pipeline. Reads PRODUCTION.

    py -3 scripts\\diagnose_betting_pipeline.py
    py -3 scripts\\diagnose_betting_pipeline.py --date 2026-08-09 --json
    py -3 scripts\\diagnose_betting_pipeline.py --sport mlb

It walks the pipeline in order and names THE FIRST STAGE THAT IS ZERO:

    odds acquisition -> odds artifacts -> Layer 1 (book grid / market board)
      -> Layer 2-A (candidates) -> Layer 2-B/C (arb, low hold)
      -> board publication -> what the site actually serves

That ordering is the tool's reason to exist. Every stage downstream of a
zero also reads as broken, so a report that lists eight failures teaches
nothing; one that says "the earliest zero is odds artifacts" is the answer.

THREE DISTINCTIONS IT REFUSES TO BLUR, each of which cost a real evening:

  ZERO vs UNMEASURED  -- a 502 from a restarting web service is not "no
                         candidates". Unmeasured stages print `??`, never `0`.
  COUNT vs RATE       -- every cadence carries its window and sample count.
                         One occurrence is not a cadence.
  CONFIGURED vs REAL  -- an interval env var is what was asked for; the gap
                         between log lines is what happens. They differ by
                         15x on the intelligence loop today.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))

from scripts._pipeline_diag import (  # noqa: E402
    SERVICES,
    SPORTS,
    Probe,
    Stage,
    banner,
    cadence,
    fetch_logs,
    first_broken,
    log_window,
    matches,
    oom_events,
    render_owner_id,
    service_commits,
    utcnow,
    web_json,
)


def stage_services() -> tuple[Stage, dict[str, str]]:
    """Read every service's live commit and recent kills FIRST.

    Not politeness: a stale service answers confidently and wrongly, and
    an OOM-cycling one answers 502. Both change how you read the numbers
    below, so they must be known before the numbers are taken.
    """
    stage = Stage(name="0. services (read before any number)")
    commits = service_commits()
    distinct = {commit for commit in commits.values() if commit and not commit.startswith("?")}
    stage.count = 1
    stage.notes.append("live commits: " + ", ".join(f"{name}={sha}" for name, sha in commits.items()))
    if len(distinct) > 1:
        stage.notes.append(
            "!! SERVICES ARE ON DIFFERENT COMMITS -- a question touching two of them "
            "can get two answers, both authoritative-looking"
        )
    kills = [(when, kind) for when, kind in oom_events(SERVICES["web"], limit=20) if "OOM" in kind or "unhealthy" in kind]
    if kills:
        stage.notes.append(f"!! web: {len(kills)} OOM/unhealthy events in the last 20 (most recent {kills[0][0]})")
        for when, kind in kills[:4]:
            stage.notes.append(f"   {when}  {kind}")
        stage.notes.append("   a 502 below is web being dead, NOT the stage being empty")
    return stage, commits


def stage_odds_acquisition(logs: list[dict]) -> Stage:
    """Are we buying odds, how fast, and what is it costing."""
    stage = Stage(name="1. odds acquisition (OddsAPI)")
    payload, status, error = web_json("/api/ops/oddsapi/quota", admin=True)
    if not isinstance(payload, dict):
        stage.unknown = True
        stage.probes.append(Probe("oddsapi/quota", False, error or "unreadable", status=status))
    else:
        quota = payload.get("quota") if isinstance(payload.get("quota"), dict) else payload
        baseline = quota.get("baseline") if isinstance(quota.get("baseline"), dict) else {}
        used = baseline.get("used")
        remaining = baseline.get("remaining")
        observed = baseline.get("observedAt")
        stage.count = 1
        stage.notes.append(f"credits used={used} remaining={remaining} (observedAt {observed})")
        stage.notes.append(
            "!! `remaining` is the PROVIDER's number and it implies a ~15M cap. The real "
            "contractual ceiling is 5M -- do not plan against this field."
        )
        if isinstance(used, int):
            stage.notes.append(f"against the real 5M cap: {used / 5_000_000:.1%} consumed")
        by_hour = quota.get("by_hour_utc") if isinstance(quota.get("by_hour_utc"), dict) else {}
        if by_hour:
            credits = {hour: (row or {}).get("credits", 0) for hour, row in by_hour.items()}
            top = sorted(credits.items(), key=lambda kv: kv[1], reverse=True)[:3]
            stage.notes.append(
                "costliest hours (UTC): " + ", ".join(f"{hour}h={value:,}" for hour, value in top)
            )
            stage.notes.append(
                "compare an hour against ITS OWN historical norm, never against the daily mean -- "
                "a window mean of 3.4x and a same-hours reading of 0.29x are both true (#303)"
            )

    fetches = matches(logs, r"PUBLISH_OK.*oddsapi_(game_lines|hitter_props|pitcher_props)")
    rate, note = cadence(fetches)
    stage.cadence_note = f"odds artifact publishes: {note}"
    if rate is None and stage.count:
        stage.notes.append("(too few publishes in the log window to infer a fetch cadence)")
    return stage


def stage_odds_artifacts(date: str, *, include_export: bool = False) -> Stage:
    """Do today's odds files exist, and is the slate INTACT?

    The subtle failure is not absence, it is EROSION: the live file is
    rewritten each refresh with only events still in progress, so a slate
    silently collapses through the day. `#265`'s pregame freeze holds the
    full slate; the gap between them is the real health signal.
    """
    stage = Stage(name="2. odds artifacts on disk")
    if not include_export:
        stage.unknown = True
        stage.notes.append(
            "SKIPPED -- /api/ops/artifacts/export is not safe to poll. Pass --with-export to run it."
        )
        stage.notes.append(
            "Why: `ops.py` globs HOT_ARTIFACT_PATTERNS across the whole artifact tree BEFORE "
            "filtering to the requested pattern, so the cost is in the walk, not the response size."
        )
        stage.notes.append(
            "Measured 2026-08-09: web OOM gaps were 16-28 min, then three of my own diagnostic "
            "runs at ~21:46/~21:49/~21:52 were each followed by an OOM within ~60s (21:46:59, "
            "21:49:50, 21:52:09). n=3 on an already-cycling service, so CONTRIBUTING is likely "
            "and PROVEN is not claimed -- but a diagnostic must not be a load source."
        )
        return stage
    slug = date.replace("-", "_")
    base = f"mlb_source/data/daily/snapshots/{date}"

    live, status, error = web_json(
        f"/api/ops/artifacts/export?pattern={base}/oddsapi_game_lines_{slug}.json", admin=True, timeout=90
    )
    frozen, _, _ = web_json(
        f"/api/ops/artifacts/export?pattern={base}/oddsapi_game_lines_{slug}_pregame.json", admin=True, timeout=90
    )

    def games_in(blob) -> int | None:
        if not isinstance(blob, dict):
            return None
        for value in (blob.get("artifacts") or {}).values():
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except Exception:
                    return None
            if isinstance(value, dict):
                return len(value.get("games") or [])
        return None

    live_games = games_in(live)
    frozen_games = games_in(frozen)

    if live_games is None and frozen_games is None:
        stage.unknown = True
        stage.probes.append(Probe("game lines export", False, error or "unreadable", status=status))
        return stage

    stage.count = max(live_games or 0, frozen_games or 0)
    stage.denominator = frozen_games if frozen_games else None
    stage.notes.append(f"live file: {live_games} games   pregame freeze (#265): {frozen_games} games")
    if live_games is not None and frozen_games and live_games < frozen_games:
        stage.notes.append(
            f"!! the live file has ERODED by {frozen_games - live_games} games. "
            "Readers that do not consult the freeze will show blank rows for exactly those."
        )
    if not frozen_games:
        stage.notes.append("!! no pregame freeze for this date -- nothing can restore an eroded slate")
    return stage


def stage_layer1(sports: tuple[str, ...]) -> Stage:
    """The book grid: games carrying priced market rows, per sport."""
    stage = Stage(name="3. Layer 1 - market board / book grid")
    total_rows = 0
    total_games = 0
    covered = 0
    unreadable: list[str] = []
    for sport in sports:
        payload, status, error = web_json(f"/{sport}/api/market-board", timeout=60)
        if not isinstance(payload, dict):
            unreadable.append(f"{sport}({status or error})")
            continue
        games = payload.get("games") or []
        with_rows = [game for game in games if isinstance(game, dict) and game.get("rows")]
        rows = sum(len(game.get("rows") or []) for game in games if isinstance(game, dict))
        total_rows += rows
        total_games += len(games)
        covered += len(with_rows)
        if games:
            flag = "  <-- games with no rows" if len(with_rows) < len(games) else ""
            stage.notes.append(f"{sport:8} {len(with_rows):>3}/{len(games):<3} games priced, {rows:>4} rows{flag}")
    if unreadable and total_games == 0:
        stage.unknown = True
        stage.notes.append("unreadable: " + ", ".join(unreadable))
        return stage
    if unreadable:
        stage.notes.append("unreadable (NOT counted as zero): " + ", ".join(unreadable))
    stage.count = total_rows
    stage.denominator = None
    stage.notes.insert(0, f"{covered} of {total_games} games across all sports carry any market rows")
    return stage


def stage_layer2a(logs: list[dict]) -> Stage:
    """Candidate generation, and the free in-situ control beside it.

    LAYER2_SHORTLIST and CANDIDATE_POOL_READY read the SAME population by
    two different paths in the same process on the same cycle. When they
    disagree, the disagreement localises the fault -- it is not "which is
    right". A healthy shortlist beside a zero pool excludes missing
    artifacts, a stale mirror, a broken join, absent odds, manifest gaps
    and a date mismatch, all at once and for free.
    """
    stage = Stage(name="4. Layer 2-A - candidate generation")

    shortlists = matches(logs, r"LAYER2_SHORTLIST")
    pools = matches(logs, r"CANDIDATE_POOL_READY")
    guards = matches(logs, r"OVERVIEW_STOPPED_FOR_MEMORY|MEMORY_GUARD_ABORT")

    def last_int(entries: list[dict], field: str) -> int | None:
        import re as _re

        for entry in reversed(entries):
            found = _re.search(rf"{field}=(\d+)", str(entry.get("message") or ""))
            if found:
                return int(found.group(1))
        return None

    rows = last_int(shortlists, "rows")
    considered = last_int(shortlists, "considered")
    pool = last_int(pools, "count")

    if not shortlists and not pools:
        stage.unknown = True
        stage.notes.append("no shortlist or pool lines in the log window - the loop may not be running")
        return stage

    stage.count = pool
    stage.denominator = considered
    _, note = cadence(pools)
    stage.cadence_note = f"pool builds: {note}"
    stage.notes.append(f"shortlist (control path): rows={rows} considered={considered}")
    stage.notes.append(f"pool (overview path):     count={pool}")

    zero_pools = [entry for entry in pools if "count=0" in str(entry.get("message") or "")]
    if pools:
        stage.notes.append(f"pool builds returning zero: {len(zero_pools)} of {len(pools)} in window")
    if rows and not pool:
        stage.notes.append(
            "!! SHORTLIST HEALTHY, POOL EMPTY -- one population, two paths, only the "
            "overview-dependent one starved. This excludes missing artifacts / stale mirror / "
            "broken join / absent odds / manifest gaps as causes."
        )
        if guards:
            stage.notes.append(
                f"!! {len(guards)} memory-guard events in the same window "
                f"(most recent {str(guards[-1].get('timestamp'))[:19]}) -- see #285/#290. "
                "Do NOT lower the floor; the fix is to need less."
            )
    return stage


def stage_layer2bc() -> Stage:
    """Arb and low-hold: the other two Layer 2 boards."""
    stage = Stage(name="5. Layer 2-B/C - arb and low hold")
    found = 0
    for label, path in (("book-grid", "/api/board/book-grid?sport=mlb"), ("cross-book", "/api/board/cross-book?sport=mlb")):
        payload, status, error = web_json(path, timeout=60)
        if isinstance(payload, dict):
            rows = payload.get("rows") or payload.get("opportunities") or payload.get("games") or []
            count = len(rows) if isinstance(rows, list) else 0
            found += count
            stage.notes.append(f"{label:12} {count} rows")
        else:
            stage.probes.append(Probe(label, False, error or "unreadable", status=status))
    if not stage.notes:
        stage.unknown = True
        return stage
    stage.count = found
    return stage


def stage_board(date: str, logs: list[dict]) -> Stage:
    """What the site actually serves, plus whether the write can even land."""
    stage = Stage(name="6. board publication - what the site serves")

    served, status, error = web_json("/api/intelligence/status", timeout=60)
    snapshot, _, _ = web_json(f"/api/ops/board-snapshot/inspect?date={date}", admin=True, timeout=60)

    if not isinstance(served, dict):
        stage.unknown = True
        stage.probes.append(Probe("/api/intelligence/status", False, error or "unreadable", status=status))
    else:
        block = served.get("status") or {}
        top = block.get("top_opportunities") or []
        stage.count = len(top)
        stage.notes.append(f"served top_opportunities={len(top)} candidate_count={served.get('candidate_count')}")

    if isinstance(snapshot, dict):
        generated = snapshot.get("snapshot_generated_at")
        stage.notes.append(
            f"snapshot written {generated}, holding "
            f"{snapshot.get('top_opportunities_count')} opportunities / "
            f"{snapshot.get('recommendation_count')} recommendations"
        )
        age = _age_minutes(generated)
        if age is not None:
            stage.notes.append(f"snapshot age {age:.0f} min")
            if age > 30:
                stage.notes.append("!! stale -- a board older than the loop interval means writes are not landing")

    rejects = matches(logs, r"KEYVALUE_WRITE_REJECTED")
    refused = matches(logs, r"STATE_ARTIFACT_FALLBACK_REFUSED|PUBLISH_FAILED")
    if rejects or refused:
        first, last, minutes = log_window(logs)
        stage.notes.append(
            f"!! TRANSPORT: {len(rejects)} keyvalue rejections and {len(refused)} publish/fallback "
            f"refusals in {minutes:.0f} min ({first} -> {last}). The board can be built and still not cross."
        )
    return stage


def _age_minutes(stamp: object) -> float | None:
    if not stamp:
        return None
    text = str(stamp)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (utcnow() - parsed).total_seconds() / 60.0
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", default=None, help="slate date (default: today, US Central)")
    parser.add_argument("--sport", default=None, help="restrict Layer 1 to one sport")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--with-export",
        action="store_true",
        help="run the artifact-export probe. OFF by default: the endpoint globs the whole "
        "artifact tree and is a plausible contributor to web OOMs. Use it deliberately, once.",
    )
    parser.add_argument(
        "--log-limit",
        type=int,
        default=1000,
        help="log lines per service (max 1000 -- the API 400s above that). The worker "
        "is chatty: 400 lines bought only ~3 minutes, too short to contain one "
        "15-minute board cycle.",
    )
    args = parser.parse_args()

    date = args.date or utcnow().strftime("%Y-%m-%d")
    sports = (args.sport,) if args.sport else SPORTS

    owner = render_owner_id()
    worker_logs, log_error = fetch_logs(SERVICES["refresh-worker"], limit=args.log_limit, owner_id=owner)
    first, last, minutes = log_window(worker_logs)

    services_stage, _ = stage_services()
    stages = [
        services_stage,
        stage_odds_acquisition(worker_logs),
        stage_odds_artifacts(date, include_export=args.with_export),
        stage_layer1(sports),
        stage_layer2a(worker_logs),
        stage_layer2bc(),
        stage_board(date, worker_logs),
    ]

    if args.json:
        print(
            json.dumps(
                {
                    "date": date,
                    "log_window": {"first": first, "last": last, "minutes": round(minutes, 1)},
                    "stages": [
                        {
                            "name": stage.name,
                            "count": stage.count,
                            "denominator": stage.denominator,
                            "healthy": stage.healthy,
                            "unmeasured": stage.unknown,
                            "cadence": stage.cadence_note,
                            "notes": stage.notes,
                        }
                        for stage in stages
                    ],
                    "first_broken": (first_broken(stages).name if first_broken(stages) else None),
                },
                indent=2,
            )
        )
        return 0

    print(banner(f"BETTING PIPELINE - {date}   (worker log window {first} -> {last}, {minutes:.0f} min)"))
    if log_error:
        print(f"  !! LOG FETCH FAILED: {log_error}")
        print("     Every log-derived stage below is UNMEASURED, not zero. Fix this first.")
    if minutes and minutes < 16:
        print(
            f"  !! WINDOW IS {minutes:.0f} MIN. The board cycle is ~15 min, so this window may\n"
            "     contain zero or one complete cycle. Any cadence below is under-sampled --\n"
            "     raise --log-limit before treating a rate here as real."
        )
    for stage in stages:
        print(stage.render())

    broken = first_broken(stages)
    print(banner("VERDICT"))
    if broken is None:
        print("  Every stage is non-zero. The pipeline is producing end to end.")
    elif broken.unknown:
        print(f"  EARLIEST UNMEASURED STAGE: {broken.name}")
        print("  This is NOT a zero. Fix the read before concluding anything about it,")
        print("  and treat every stage after it as unknown rather than broken.")
    else:
        print(f"  EARLIEST ZERO: {broken.name}")
        print("  Work here. Every stage downstream of a zero also reads as broken and none")
        print("  of them are the cause -- do not touch readers, endpoints or the UI first.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
