"""Which NCAAF weeks have been played -- as an artifact this platform OWNS.

WHY THIS EXISTS RATHER THAN A SECOND CACHE. `ncaaf_target_week` needs one fact:
the lowest week still holding an unplayed game. Until now it got that by
reading `historical_truth/games_<season>.json.gz` -- a CACHE OF A VENDOR PAYLOAD
-- directly, on the request path.

That file is doing two different jobs and only one of them is a cache:

  * for a COMPLETED season (2023-2025) it is immutable vendor data, and
    `ensure_games_cached`'s write-once rule is exactly right;
  * for the LIVE season it is operational state that changes every Saturday,
    and write-once froze it. Measured 2026-09-01: written 2026-07-21, 888 games,
    `completed: False` on 888 of 888, so `min(week with an unplayed game)`
    returned 1 -- and `_week_is_within_pregame_window` trimmed the board to
    `week <= 1` while projection artifacts existed for weeks 1-13 and 15.

Refreshing the cache fixes the worker's copy and NOT the web service's: the two
do not share a disk, and the cache cannot cross. `publish_hot_artifact` reads
files under 4 MB as UTF-8 text (`_PUBLISH_STREAM_MIN_BYTES`), so a 39 KB gzip
fails with `SKIP_READ_FAILED` -- measured, not assumed. The transfer mechanism
this repo already has cannot carry that file at all.

So the live half becomes what everything else on the board already is: a small,
owned, published artifact. Web reads it and never calls CFBD, which is
CLAUDE.md's worker/web split rather than an exception to it.

FACTS, NOT THE DECISION. This stores per-week played/unplayed COUNTS, not a
`target_week` field. `ncaaf_target_week`'s rule ("lowest week with an unplayed
game") stays in code where it can be read and changed; an artifact that baked
the answer in would silently outlive any change to the rule, and every consumer
would inherit whichever policy was live when the file was written.

The same holds for the one clock-dependent fact it also carries: each week's
LATEST UNPLAYED KICKOFF (`unplayed_kickoffs`). The artifact is rebuilt once a
day, so "is this week over?" cannot be answered at BUILD time -- measured
2026-09-08, the build ran 137.8 minutes into week 1's last game and the board
then served a finished week for a day. The kickoff is the producer's fact;
comparing it with the clock happens at READ time, in `target_week_from_state`.

WRITE PATH -> READ PATH, checked rather than assumed, because an artifact that
lands where nothing reads is inert and looks identical to the bug it was meant
to fix (see `artifact_publisher`'s own note on the season-projection CSVs,
published as no-ops for 13 days):

    worker writes   week_state_path(season)  == data_path("week_state", ...)
    web reads       week_state_path(season)  == data_path("week_state", ...)

They are the same function. That is the point -- the sibling defect happened
because two different expressions were believed to name one location.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from typing import Iterable
from typing import Mapping

from syndicate.features.ncaaf.sources import data_path

SOURCE = "ncaaf_games_cache"

# Matches `ncaaf_historical_loader._GAME_COMPLETION_GRACE_SECONDS`. A game is
# over well inside this window; anything still `completed: False` past it is
# counted as unplayed but FLAGGED, so a reader can tell "not played yet" from
# "played and the upstream flag never arrived".
#
# `target_week_from_state` reads the SAME number, deliberately: a game this far
# past kickoff is a stale flag, and a stale flag must not hold the board on a
# finished week. One grace, not two that can drift apart.
_COMPLETION_GRACE_SECONDS = 12 * 3600


def _now() -> float:
    """The reader's clock -- a function so a test can pin it."""
    return time.time()


def week_state_path(season: int) -> Path:
    return data_path("week_state", f"ncaaf_week_state_{season}.json")


def _parse_epoch(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.timestamp()


def _kickoff_epoch(game: Any) -> float | None:
    if not isinstance(game, Mapping):
        return None
    return _parse_epoch(game.get("startDate"))


def build_week_state(season: int, *, games: Iterable[Any], now: float) -> dict[str, Any]:
    """Per-week counts derived from a CFBD `/games` payload.

    `stale_flags` is the diagnostic that would have made the original defect
    visible in one read: games whose kickoff is well past and which the payload
    still calls unplayed. On a healthy snapshot it is 0. On the 2026-07-21 file
    it was 8 -- the same 8 the cards board was independently showing as `Final`.

    `unplayed_kickoffs` carries, for every week still holding an unplayed game,
    the LATEST kickoff among those games (`last`, ISO UTC) and how many of them
    have no parseable kickoff at all (`undated`). It is what lets the reader
    tell "this week's last game has not been played yet" from "this week's last
    game kicked off many hours ago and the flag has not arrived".
    """
    weeks: dict[str, dict[str, int]] = {}
    latest_unplayed: dict[str, float] = {}
    undated_unplayed: dict[str, int] = {}
    total = 0
    stale_flags = 0
    cutoff = now - _COMPLETION_GRACE_SECONDS

    for game in games or ():
        if not isinstance(game, Mapping):
            continue
        if str(game.get("seasonType") or "regular").strip().lower() != "regular":
            continue
        try:
            week = int(game.get("week"))
        except (TypeError, ValueError):
            continue
        total += 1
        key = str(week)
        bucket = weeks.setdefault(key, {"games": 0, "completed": 0, "unplayed": 0})
        bucket["games"] += 1
        if game.get("completed"):
            bucket["completed"] += 1
            continue
        bucket["unplayed"] += 1
        kickoff = _kickoff_epoch(game)
        if kickoff is None:
            undated_unplayed[key] = undated_unplayed.get(key, 0) + 1
            continue
        if kickoff > latest_unplayed.get(key, float("-inf")):
            latest_unplayed[key] = kickoff
        if kickoff < cutoff:
            stale_flags += 1

    unplayed_kickoffs: dict[str, dict[str, Any]] = {}
    for key, bucket in weeks.items():
        if bucket["unplayed"] <= 0:
            continue
        entry: dict[str, Any] = {"undated": undated_unplayed.get(key, 0)}
        if key in latest_unplayed:
            entry["last"] = datetime.fromtimestamp(latest_unplayed[key], timezone.utc).isoformat()
        unplayed_kickoffs[key] = entry

    return {
        "season": int(season),
        "source": SOURCE,
        "generated_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "games": total,
        "stale_completion_flags": stale_flags,
        "weeks": weeks,
        "unplayed_kickoffs": unplayed_kickoffs,
    }


def write_week_state(state: Mapping[str, Any]) -> Path:
    path = week_state_path(int(state["season"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.part")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
    return path


def read_week_state(season: int) -> dict[str, Any] | None:
    """The published artifact, or None when absent/unusable.

    Never raises. A missing or malformed artifact must degrade to the caller's
    existing behaviour, not take the board down -- this replaces a read that
    always worked, so any failure here has to be at least as survivable.
    """
    try:
        payload = json.loads(week_state_path(season).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - absent, unreadable, or not JSON
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("weeks"), dict):
        return None
    if int(payload.get("season") or 0) != int(season):
        # A season mismatch means we resolved to the wrong file. Refusing is the
        # only safe answer: a week number carries no season, so a cross-season
        # hit would be silently plausible.
        return None
    return payload


def _week_can_still_be_played(entry: Any, now: float) -> bool:
    """Can any of this week's unplayed games still be upcoming or in progress?

    YES whenever it cannot tell -- no entry, an undated game, an unparseable
    kickoff. Advancing the board is the permissive branch here, so an unknown
    keeps the week exactly as the rule held it before this field existed.
    """
    if not isinstance(entry, Mapping):
        return True  # no facts for this week: hold it, as before the field existed
    try:
        if int(entry.get("undated") or 0) > 0:
            return True
    except (TypeError, ValueError):
        return True
    last = _parse_epoch(entry.get("last"))
    if last is None:
        return True
    return last >= now - _COMPLETION_GRACE_SECONDS


def target_week_from_state(state: Mapping[str, Any] | None, *, now: float | None = None) -> int | None:
    """Lowest week with an unplayed game that can still be played, or None if
    the state cannot answer.

    None is the same "cannot determine" the schedule path returns, and callers
    already fail OPEN on it (`_week_is_within_pregame_window` returns True), so
    an unusable artifact widens the board rather than blanking it.

    THE GRACE, AND WHY IT IS APPLIED HERE RATHER THAN AT BUILD TIME. The
    artifact is rebuilt once a day inside the projection run, and that run
    drifts ~19 min/day around the clock. When it lands mid-slate it counts the
    evening's games as unplayed, and the plain rule then held the board on a
    FINISHED week until the next day's build: measured 2026-09-08 (the build
    caught SMU @ Florida State 137.8 min after kickoff; `deploys.md`), and
    predicted for every Saturday whose build lands before the last final. A
    week whose every unplayed game kicked off more than
    `_COMPLETION_GRACE_SECONDS` ago -- the stale-flag threshold -- no longer
    holds the board. Only the clock is read here; the kickoffs are the
    producer's facts.

    Two guards keep the grace from becoming a new failure:
      * an artifact without `unplayed_kickoffs` (written before the field
        existed) answers exactly as it did before;
      * the HIGHEST week still holding an unplayed game is never skipped, so the
        grace can never turn an answer into None -- which `ncaaf_target_week`
        would read as "no artifact" and answer from the STALE games cache.
    """
    if not isinstance(state, Mapping):
        return None
    weeks = state.get("weeks")
    if not isinstance(weeks, Mapping):
        return None
    candidates: list[tuple[int, str]] = []
    for key, bucket in weeks.items():
        if not isinstance(bucket, Mapping):
            continue
        try:
            if int(bucket.get("unplayed") or 0) > 0:
                candidates.append((int(key), str(key)))
        except (TypeError, ValueError):
            continue
    if not candidates:
        return None
    kickoffs = state.get("unplayed_kickoffs")
    if not isinstance(kickoffs, Mapping):
        kickoffs = {}
    clock = _now() if now is None else float(now)
    highest = max(week for week, _ in candidates)
    playable = [
        week
        for week, key in candidates
        if week == highest or _week_can_still_be_played(kickoffs.get(key), clock)
    ]
    return min(playable)


__all__ = [
    "SOURCE",
    "build_week_state",
    "read_week_state",
    "target_week_from_state",
    "week_state_path",
    "write_week_state",
]
