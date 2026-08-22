"""Capture basketball attack momentum for the games currently in play.

**NOTHING SCHEDULES THIS YET.** It is a working entrypoint that must be invoked
-- by hand, or by the one-line wiring into the live-lens tick that Phase B
deliberately does not make (see `basketball_momentum_artifacts`'s docstring and
`.syndicate/scope_2026-08-22_basketball_live_momentum.md` section 7a). A
producer that exists is not a producer that runs, and this file existing is not
evidence that any momentum has ever been captured.

Shaped as a SCRIPT rather than as code inside `features/nba/` because that is
soccer's shape -- `scripts/poll_soccer_live_state.py` is a script the live-lens
loop imports -- and because `wnba/live_lens.py` and `live_lens_loop.py` are
both claimed by other open lanes.

    python scripts/poll_basketball_momentum.py --league wnba --date 2026-08-22
    python scripts/poll_basketball_momentum.py --league nba --dry-run

NETWORK. ESPN's site API is unauthenticated but soft-blocks datacenter egress
with a bot-shaped User-Agent: the request SUCCEEDS at the transport level and
returns an empty body, which is indistinguishable downstream from "no games
today". `#469` measured that as the difference between a real payload and
weeks of silently frozen data. The browser UA below is not decoration.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.basketball_momentum_artifacts import append_momentum_artifact
from syndicate.features.shared.basketball_momentum_artifacts import build_momentum_payload
from syndicate.features.shared.basketball_momentum_artifacts import momentum_artifact_path

_SPORT_PATH = {
    "nba": "sports/basketball/nba",
    "wnba": "sports/basketball/wnba",
    "ncaab": "sports/basketball/mens-college-basketball",
    "ncaabw": "sports/basketball/womens-college-basketball",
}

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _get_json(url: str, *, timeout: int = 25) -> dict[str, Any]:
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": _BROWSER_UA}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return {}
            payload = json.loads(response.read().decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def live_event_ids(league: str, date_str: str) -> list[str]:
    """Event ids for games IN PROGRESS. Not scheduled, not final.

    A final game has a complete feed and would produce a full-match series that
    reads on a card as though the game were still being played. Soccer's
    `poll_soccer_live_state` keeps the same separation for the same reason.
    """
    ymd = date_str.replace("-", "")
    url = f"https://site.api.espn.com/apis/site/v2/{_SPORT_PATH[league]}/scoreboard?dates={ymd}"
    scoreboard = _get_json(url)
    out: list[str] = []
    for event in scoreboard.get("events") or []:
        if not isinstance(event, dict):
            continue
        status = ((event.get("status") or {}).get("type") or {})
        if str(status.get("state") or "").strip().lower() != "in":
            continue
        event_id = str(event.get("id") or "").strip()
        if event_id:
            out.append(event_id)
    return out


def fetch_summary(league: str, event_id: str) -> dict[str, Any]:
    url = f"https://site.web.api.espn.com/apis/site/v2/{_SPORT_PATH[league]}/summary?event={event_id}"
    return _get_json(url)


def poll(league: str, date_str: str, *, out_root: Path, dry_run: bool = False) -> dict[str, Any]:
    event_ids = live_event_ids(league, date_str)
    print(f"[basketball_momentum] league={league} date={date_str} live_events={len(event_ids)}", flush=True)
    summaries = {event_id: fetch_summary(league, event_id) for event_id in event_ids}
    summaries = {k: v for k, v in summaries.items() if v}

    payload = build_momentum_payload(summaries, league_code=league, date_str=date_str)
    # `with_series` NOT `count`: a slate of games we fetched but could not read
    # and a slate with no games are both "0 charts", and only one of them is a
    # defect. Printing the pair is what makes them distinguishable in a log.
    print(
        f"[basketball_momentum] fetched={len(summaries)} games={payload['count']} "
        f"with_series={payload['with_series']}",
        flush=True,
    )
    # **WHEN GAMES ARE PRESENT AND NONE CARRIED A SERIES, SAY WHY -- PER GAME.**
    #
    # `with_series=0` is ambiguous between "no live games" and "live games we
    # could not parse", and those need completely different responses. Without
    # this the two print the SAME line, which is the failure this repo names
    # repeatedly: a gate that fires silently cannot be told from a builder that
    # never ran.
    #
    # It matters most in exactly the window where it is least recoverable.
    # Every test of this taxonomy so far has run on hand-built fixtures, because
    # ESPN is 403 from a Claude Code sandbox -- so the first real payload is
    # also the first chance for `_team_index` or `_classify` to be wrong about
    # the feed's actual shape, and WNBA is the only basketball league in season.
    #
    # The three things printed are the three that can be wrong: a stated
    # `reason` from the block, whether `plays` arrived at all, and whether the
    # header yielded competitors (no competitors -> no home side -> every event
    # silently unsigned and dropped).
    if summaries and not payload.get("with_series"):
        for event_id, block in (payload.get("games") or {}).items():
            summary = summaries.get(event_id) or {}
            plays = summary.get("plays")
            header = summary.get("header") if isinstance(summary.get("header"), dict) else {}
            competitions = header.get("competitions") if isinstance(header.get("competitions"), list) else []
            first = competitions[0] if competitions and isinstance(competitions[0], dict) else {}
            competitors = first.get("competitors") if isinstance(first.get("competitors"), list) else None
            print(
                f"[basketball_momentum] NO_SERIES event={event_id} "
                f"supported={block.get('supported')} reason={block.get('reason')!r} "
                f"events={block.get('events')} "
                f"plays={len(plays) if isinstance(plays, list) else 'ABSENT'} "
                f"competitors={len(competitors) if competitors is not None else 'ABSENT'}",
                flush=True,
            )

    if dry_run:
        print("[basketball_momentum] DRY RUN -- nothing written", flush=True)
        return payload

    if not payload.get("with_series"):
        # REFUSE TO STORE AN EMPTY CAPTURE. This appends once per live tick, so
        # a quiet slate would otherwise write a row every few minutes all day
        # and the backtest would have to learn to ignore them. The sibling
        # WNBA live-box capture in `live_lens_loop.py` takes the same position
        # for the same reason.
        #
        # `with_series`, not `count`: a slate we fetched but could not read is
        # also nothing worth storing, and it is the case that most needs
        # saying out loud rather than being written as a row of nulls.
        print(
            f"[basketball_momentum] NOTHING TO STORE league={league} date={date_str} "
            f"games={payload['count']} with_series=0 -- not appended",
            flush=True,
        )
        return payload

    path = momentum_artifact_path(out_root, league_code=league, date_str=date_str)
    append_momentum_artifact(payload, path=path)
    print(f"[basketball_momentum] appended {path}", flush=True)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", required=True, choices=sorted(_SPORT_PATH))
    parser.add_argument("--date", default=None, help="ISO date; defaults to today UTC")
    parser.add_argument("--out-root", default=None, help="artifact root; defaults to <repo>/data")
    parser.add_argument("--dry-run", action="store_true", help="fetch and build, write nothing")
    args = parser.parse_args(argv)

    date_str = args.date
    if not date_str:
        from datetime import datetime, timezone

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_root = Path(args.out_root) if args.out_root else (REPO_ROOT / "data")
    payload = poll(args.league, date_str, out_root=out_root, dry_run=bool(args.dry_run))
    # Exit 3, not 0, when nothing carried a series. A zero exit on an empty
    # capture is how an inert feature reads as healthy for weeks -- the same
    # discipline `scripts/verify_wnba_totals_pricing.py` adopted after a
    # pre-tip zero was indistinguishable from a broken one.
    return 0 if payload.get("with_series") else 3


if __name__ == "__main__":
    raise SystemExit(main())
