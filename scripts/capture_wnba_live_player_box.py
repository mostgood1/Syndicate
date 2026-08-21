"""Persist WNBA live per-player stat lines as an artifact a worker can read.

WHY THIS EXISTS. Live WNBA props were reported impossible three times on
2026-08-20 for want of live player state. The state was never missing:
`/wnba/api/live_player_boxscore` serves minutes, points, rebounds, assists and
threes per player for every live game, and
`cards.py::_public_live_player_boxscore_payload` has been fetching ESPN's
summary endpoint all along. Read from production 2026-08-21 02:40Z: 17 and 18
players across two live games.

WHAT WAS ACTUALLY MISSING IS PERSISTENCE. That fetch runs in the REQUEST PATH on
web (its own function carries `warn_if_compute_in_request_path`), while the prop
join runs inside the board build on a WORKER. So the data existed, was served,
and was unreachable by the only consumer that needed it -- exactly the
producer/consumer split `#350` records for MLB's live props ("the board read one
artifact and the sim wrote another").

WHY IT CALLS WEB RATHER THAN ESPN. Same shape as `capture_wnba_pbp.py`, and for
the same reason: fetching ESPN here would put third-party IO on a worker tick,
which is the inversion CLAUDE.md's worker rule names and which cost this project
a 1,062MB allocation and an OOM-killed container the last time a tick rebuilt
something it should have consumed. Web already does this fetch as part of
serving a page; this script reads that result and writes it down.

IT REFUSES TO STORE AN EMPTY CAPTURE, and that refusal is the design, not a
nicety. `capture_wnba_pbp.py`'s docstring records the failure mode it is
guarding against: a payload with `ok: True` and a complete structure carrying no
data reads as an answer to every consumer, and a persisted empty is served in
preference to real data afterwards. A slate with no live game must leave NO
artifact rather than an artifact saying nobody played.

Exit codes:  0 wrote  1 nothing live (not a failure)  2 fetched but empty
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_BASE = "https://syndicate-an21.onrender.com"

# The stat keys a WNBA prop is actually priced on. Declared rather than
# inferred: a consumer that guesses at the shape will silently price whatever
# key it finds, and an absent key must be distinguishable from a zero.
PLAYER_STAT_KEYS: tuple[str, ...] = ("pts", "reb", "ast", "threes_made", "mp")


def artifact_relative_path(date_str: str) -> str:
    """Where the capture lands, relative to the data root.

    Under `wnba_source/data/live/` rather than the top-level `live/` tree: the
    latter is the three undated live-lens snapshots, which are fetched
    unconditionally every publish cycle precisely because they carry no date.
    This one IS dated, so it belongs with the dated per-sport artifacts and is
    swept normally.
    """
    return f"wnba_source/data/live/live_player_box_{date_str}.json"


def fetch(base_url: str, date_str: str, *, timeout: int = 60) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/wnba/api/live_player_boxscore?" + urllib.parse.urlencode({"date": date_str})
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def summarize(payload: Any) -> dict[str, Any]:
    """Count what actually arrived, per game, before anything is written.

    Returns counts rather than a boolean so the caller can report WHICH half is
    empty -- games with no players at all is a different fault from a payload
    with no games, and they have different fixes.
    """
    games = payload.get("games") if isinstance(payload, dict) else None
    games = games if isinstance(games, list) else []
    per_game: list[dict[str, Any]] = []
    players_total = 0
    for game in games:
        if not isinstance(game, dict):
            continue
        players = game.get("players") if isinstance(game.get("players"), list) else []
        # A row is only counted when it carries at least one PRICEABLE stat.
        # A name with every stat null is the same shape of empty the pbp
        # skeleton had, and it must not inflate the count that decides whether
        # this capture is worth storing.
        priced = [
            p for p in players
            if isinstance(p, dict) and any(p.get(k) is not None for k in PLAYER_STAT_KEYS)
        ]
        players_total += len(priced)
        per_game.append({
            "event_id": game.get("event_id"),
            "players": len(players),
            "players_with_stats": len(priced),
        })
    return {"games": len(per_game), "players_with_stats": players_total, "per_game": per_game}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--date", required=True, help="YYYY-MM-DD (the board's ET business date)")
    parser.add_argument("--base-url", default=_DEFAULT_BASE)
    parser.add_argument("--dry-run", action="store_true", help="fetch and report; write nothing")
    args = parser.parse_args(argv)

    try:
        payload = fetch(args.base_url, args.date)
    except Exception as exc:  # noqa: BLE001
        print(f"[wnba_live_player_box] FETCH_FAILED date={args.date} "
              f"error={type(exc).__name__}: {exc}", flush=True)
        return 2

    counts = summarize(payload)
    print(f"[wnba_live_player_box] FETCHED date={args.date} "
          f"games={counts['games']} players_with_stats={counts['players_with_stats']} "
          f"per_game={json.dumps(counts['per_game'])}", flush=True)

    if counts["games"] == 0:
        # Not a failure: no live WNBA game is the normal state most of the day.
        print("[wnba_live_player_box] NOTHING_LIVE -- no artifact written", flush=True)
        return 1
    if counts["players_with_stats"] == 0:
        # Fetched something shaped like an answer that contains none. Storing it
        # would make every downstream consumer read "nobody has scored" as fact.
        print("[wnba_live_player_box] EMPTY_CAPTURE -- games present but no player "
              "carried a priceable stat; REFUSING to write", flush=True)
        return 2

    if args.dry_run:
        print("[wnba_live_player_box] DRY_RUN -- not written", flush=True)
        return 0

    from syndicate.features.shared.refresh_state_store import data_root, write_json_file

    relative = artifact_relative_path(args.date)
    path = data_root() / relative
    record = {
        "date": args.date,
        "source": "wnba/api/live_player_boxscore",
        "counts": {k: counts[k] for k in ("games", "players_with_stats")},
        "per_game": counts["per_game"],
        "payload": payload,
    }
    write_json_file(path, record)
    print(f"[wnba_live_player_box] WROTE path={relative} "
          f"games={counts['games']} players={counts['players_with_stats']}", flush=True)

    try:
        from syndicate.features.shared.artifact_publisher import publish_hot_artifact

        published = publish_hot_artifact(path)
        print(f"[wnba_live_player_box] PUBLISH ok={published} path={relative}", flush=True)
    except Exception as exc:  # noqa: BLE001
        # Never fatal: the artifact is written either way, and a publish failure
        # is a cross-service reachability problem rather than a capture one.
        print(f"[wnba_live_player_box] PUBLISH_FAILED {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
