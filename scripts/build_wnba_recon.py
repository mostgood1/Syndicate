"""Build WNBA post-game reconciliation artifacts, Syndicate-owned, from ESPN.

WHY THIS EXISTS. `_load_recon_indexes` in
`syndicate/features/shared/live_lens_local.py` settles every graded WNBA row --
game totals, ATS, quarter/half totals and player props -- by joining against
three CSVs:

    recon_games_<date>.csv      home_pts / visitor_pts / total_actual
    recon_quarters_<date>.csv   actual_q1..q4_total, actual_h1/h2_total
    recon_props_<date>.csv      per player: pts reb ast threes stl blk tov pra

MEASURED 2026-08-31 against production (lane `wnba-accuracy-assessment`), via
`/api/ops/artifacts/export?names_only=1`:

    recon_games_*.csv     4 files IN ALL OF PRODUCTION   (05-27, 05-28, 06-21, 06-23)
    recon_quarters_*.csv  0 files
    recon_props_*.csv    33 files, ALL 2026-05-20..06-26

and -- the part that matters more than the count -- **in every one of the four
`recon_games` files that do exist, the outcome columns are EMPTY STRINGS**:

    date,home_team,visitor_team,home_tri,away_tri,home_pts,visitor_pts,pred_margin,actual_margin,total_actual,margin_error,total_error
    2026-05-27,Chicago Sky,Toronto Tempo,CHICAGO SKY,TORONTO TEMPO,,,0.1932,,,,

The file is written PREGAME, carrying `pred_margin`, and nothing ever comes back
to fill in what happened. So the prediction is recorded and the outcome never is,
which is why `n_settled` is 0 on every WNBA accuracy surface even on dates where
the recon file exists.

**This producer is the missing half: it runs AFTER the games and writes only
what actually happened.** It is deliberately outcome-only -- it does not write
`pred_margin` and does not merge with a pregame file, because a producer that
does both is how the pregame version came to overwrite the outcome one.

Native ESPN, not the vendor CLI, for the reasons stated at length in
`scripts/build_wnba_boxscores.py` -- whose fetchers, host choice and
completed-only rule this reuses rather than re-deriving.

Only games ESPN reports as COMPLETED are written. A slate still in progress
writes nothing rather than a row of zeros, because a zero here is
indistinguishable from a real result downstream.

Exit codes:  0 wrote  1 nothing final on the slate (not a failure)  2 fetched but empty
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import date as _date
from datetime import timedelta as _timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.build_wnba_boxscores import _get  # noqa: E402
from scripts.build_wnba_boxscores import _SUMMARY  # noqa: E402
from scripts.build_wnba_boxscores import _split_pair  # noqa: E402
from scripts.build_wnba_boxscores import completed_event_ids  # noqa: E402

# Column contracts taken from what the READER asks for
# (`live_lens_local._load_recon_indexes` / `_actual_total` /
# `_actual_ats_margin_home` / `_actual_prop`), not from the malformed pregame
# files -- those name `actual_margin` and never fill it.
GAME_COLUMNS: tuple[str, ...] = (
    "date", "game_id", "gameId", "home_tri", "away_tri",
    "home_pts", "visitor_pts", "actual_margin", "total_actual", "source",
)
QUARTER_COLUMNS: tuple[str, ...] = (
    "date", "game_id", "gameId",
    "actual_q1_total", "actual_q2_total", "actual_q3_total", "actual_q4_total",
    "actual_h1_total", "actual_h2_total", "source",
)
PROP_COLUMNS: tuple[str, ...] = (
    "date", "game_id", "gameId", "player_id", "player_name", "team_abbr",
    "pts", "reb", "ast", "threes", "stl", "blk", "tov", "pra", "pr", "pa", "ra",
    "min", "source",
)

# ESPN box-score keys, same names `build_wnba_boxscores` reads.
_SCALARS = {
    "pts": "points", "reb": "rebounds", "ast": "assists",
    "stl": "steals", "blk": "blocks", "tov": "turnovers", "min": "minutes",
}
_THREES = "threePointFieldGoalsMade-threePointFieldGoalsAttempted"


# League parameter (lane nba-season-phase, 2026-10-06): NBA had NO recon producer after 2026-06-13, so the NBA props
# bias calibration had no outcomes to learn from. The same outcome-only rows, from NBA's ESPN endpoints, written under
# nba_source/ with NBA team codes. "wnba" is the default and behaves exactly as before.
_LEAGUES: dict[str, dict[str, Any]] = {
    "wnba": {"scoreboard": None, "summary": _SUMMARY, "base": "wnba_source/data/processed", "tag": "wnba_recon"},
    "nba": {
        "scoreboard": str(__import__("os").environ.get("SYNDICATE_NBA_SCOREBOARD_URL")
                          or "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard").strip(),
        "summary": "https://site.web.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
        "base": "nba_source/data/processed",
        "tag": "nba_recon",
    },
}


def _league(league: str) -> dict[str, Any]:
    key = str(league or "wnba").strip().lower()
    if key not in _LEAGUES:
        raise ValueError(f"unknown league {league!r}")
    return _LEAGUES[key]


def _tri(abbr: str, league: str) -> str:
    """ESPN team abbreviation -> the code the league's other artifacts use (NBA: GS -> GSW, NY -> NYK, ...)."""
    value = str(abbr or "").upper()
    if str(league or "wnba").strip().lower() != "nba":
        return value
    from syndicate.features.shared.basketball_props_smart_sim import _espn_to_tri_local

    return _espn_to_tri_local(value, league_code="nba")


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except Exception:
        return None


def _summary(event_id: str, league: str = "wnba") -> dict[str, Any]:
    return _get(f"{_league(league)['summary']}?event={event_id}")


def _linescore_totals(competitors: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-period COMBINED totals. Absent periods yield None, never 0.

    A WNBA game is four 10-minute quarters; overtime periods appear as extra
    linescore entries and are deliberately NOT folded into Q4 -- `actual_q4_total`
    means the fourth quarter, and a reader comparing it to a Q4 line would be
    wrong by the whole of OT.
    """
    per_period: dict[int, int] = {}
    counts: dict[int, int] = {}
    for competitor in competitors:
        for index, entry in enumerate(competitor.get("linescores") or [], start=1):
            value = entry.get("displayValue", entry.get("value"))
            points = _int(value)
            if points is None:
                continue
            per_period[index] = per_period.get(index, 0) + points
            counts[index] = counts.get(index, 0) + 1

    def period(index: int) -> int | None:
        # Both teams must have reported the period, or the "total" is one team's.
        return per_period.get(index) if counts.get(index) == 2 else None

    quarters = {index: period(index) for index in (1, 2, 3, 4)}
    h1 = None
    if quarters[1] is not None and quarters[2] is not None:
        h1 = quarters[1] + quarters[2]
    h2 = None
    if quarters[3] is not None and quarters[4] is not None:
        h2 = quarters[3] + quarters[4]
    return {"quarters": quarters, "h1": h1, "h2": h2}


def rows_for_event(event_id: str, date_str: str, league: str = "wnba") -> dict[str, list[dict[str, Any]]]:
    """One completed game -> its game, quarter and player rows."""
    payload = _summary(event_id, league)
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    if not competitions:
        return {"games": [], "quarters": [], "props": []}
    competitors = (competitions[0].get("competitors") or [])

    home = away = None
    for competitor in competitors:
        record = {
            "tri": _tri((competitor.get("team") or {}).get("abbreviation") or "", league),
            "score": _int(competitor.get("score")),
        }
        if str(competitor.get("homeAway") or "").lower() == "home":
            home = record
        else:
            away = record
    if not home or not away or home["score"] is None or away["score"] is None:
        return {"games": [], "quarters": [], "props": []}

    game_row = {
        "date": date_str,
        "game_id": event_id,
        "gameId": event_id,
        "home_tri": home["tri"],
        "away_tri": away["tri"],
        "home_pts": home["score"],
        "visitor_pts": away["score"],
        "actual_margin": home["score"] - away["score"],
        "total_actual": home["score"] + away["score"],
        "source": "espn",
    }

    periods = _linescore_totals(competitors)
    quarter_row = {
        "date": date_str,
        "game_id": event_id,
        "gameId": event_id,
        "actual_q1_total": periods["quarters"][1],
        "actual_q2_total": periods["quarters"][2],
        "actual_q3_total": periods["quarters"][3],
        "actual_q4_total": periods["quarters"][4],
        "actual_h1_total": periods["h1"],
        "actual_h2_total": periods["h2"],
        "source": "espn",
    }

    prop_rows: list[dict[str, Any]] = []
    for team in (payload.get("boxscore") or {}).get("players") or []:
        team_tri = _tri((team.get("team") or {}).get("abbreviation") or "", league)
        stats_block = (team.get("statistics") or [{}])[0]
        index = {name: position for position, name in enumerate(stats_block.get("keys") or stats_block.get("names") or [])}
        for athlete in stats_block.get("athletes") or []:
            person = athlete.get("athlete") or {}
            name = str(person.get("displayName") or "").strip()
            if not name:
                continue
            if athlete.get("didNotPlay"):
                # A DNP is not a zero. Omitting the row makes the prop
                # ungradeable, which is correct; writing 0 would settle every
                # UNDER on a player who never took the floor.
                continue
            values = athlete.get("stats") or []
            if not values:
                continue

            def stat(key: str) -> int | None:
                position = index.get(_SCALARS[key])
                if position is None or position >= len(values):
                    return None
                return _int(values[position])

            threes = None
            position = index.get(_THREES)
            if position is not None and position < len(values):
                made, _ = _split_pair(values[position])
                threes = _int(made)

            pts, reb, ast = stat("pts"), stat("reb"), stat("ast")

            def combo(*parts: int | None) -> int | None:
                return None if any(part is None for part in parts) else sum(parts)  # type: ignore[arg-type]

            prop_rows.append({
                "date": date_str,
                "game_id": event_id,
                "gameId": event_id,
                "player_id": person.get("id"),
                "player_name": name,
                "team_abbr": team_tri,
                "pts": pts, "reb": reb, "ast": ast, "threes": threes,
                "stl": stat("stl"), "blk": stat("blk"), "tov": stat("tov"),
                "pra": combo(pts, reb, ast),
                "pr": combo(pts, reb),
                "pa": combo(pts, ast),
                "ra": combo(reb, ast),
                "min": stat("min"),
                "source": "espn",
            })

    return {"games": [game_row], "quarters": [quarter_row], "props": prop_rows}


def artifact_relative_paths(date_str: str, league: str = "wnba") -> dict[str, str]:
    base = _league(league)["base"]
    return {
        "games": f"{base}/recon_games_{date_str}.csv",
        "quarters": f"{base}/recon_quarters_{date_str}.csv",
        "props": f"{base}/recon_props_{date_str}.csv",
    }


def to_csv(rows: list[dict[str, Any]], columns: tuple[str, ...]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore",
                            lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({key: ("" if row.get(key) is None else row.get(key)) for key in columns})
    return buffer.getvalue()


def build_date(date_str: str, *, dry_run: bool = False, data_root: Path | None = None,
               league: str = "wnba") -> dict[str, Any]:
    cfg = _league(league)
    tag = cfg["tag"]
    event_ids = completed_event_ids(date_str, scoreboard_url=cfg["scoreboard"])
    if not event_ids:
        print(f"[{tag}] {date_str} no completed games", flush=True)
        return {"status": "no_final", "date": date_str, "games": 0}

    games: list[dict[str, Any]] = []
    quarters: list[dict[str, Any]] = []
    props: list[dict[str, Any]] = []
    for event_id in event_ids:
        try:
            built = rows_for_event(event_id, date_str, league)
        except Exception as exc:  # a single bad event must not lose the slate
            print(f"[{tag}] {date_str} event {event_id} FAILED: {type(exc).__name__}: {exc}", flush=True)
            continue
        games.extend(built["games"])
        quarters.extend(built["quarters"])
        props.extend(built["props"])

    if not games:
        print(f"[{tag}] {date_str} fetched {len(event_ids)} events, produced NO rows", flush=True)
        return {"status": "empty", "date": date_str, "games": 0}

    if data_root:
        root = Path(data_root)
    else:
        # The SAME resolver `build_wnba_boxscores` uses, deliberately, rather
        # than a second local default. On Render this is the MOUNTED DISK; a
        # `REPO_ROOT / "data"` fallback would write into the ephemeral checkout
        # and the artifact would vanish on the next deploy.
        from syndicate.features.shared.refresh_state_store import data_root as _resolved_data_root

        root = Path(_resolved_data_root())
    paths = artifact_relative_paths(date_str, league)
    payloads = {
        "games": (paths["games"], to_csv(games, GAME_COLUMNS)),
        "quarters": (paths["quarters"], to_csv(quarters, QUARTER_COLUMNS)),
        "props": (paths["props"], to_csv(props, PROP_COLUMNS)),
    }
    written: dict[str, str] = {}
    for kind, (relative, text) in payloads.items():
        target = root / relative
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        written[kind] = str(target)

    print(
        f"[{tag}] {date_str} {'DRY ' if dry_run else ''}wrote"
        f" games={len(games)} quarters={len(quarters)} props={len(props)}"
        f" -> {root / paths['games']}",
        flush=True,
    )
    return {
        "status": "dry_run" if dry_run else "ok",
        "date": date_str,
        "games": len(games),
        "quarters": len(quarters),
        "props": len(props),
        "paths": written,
    }


def _dates(start: str, end: str) -> list[str]:
    first = _date.fromisoformat(start)
    last = _date.fromisoformat(end)
    if last < first:
        first, last = last, first
    out: list[str] = []
    while first <= last:
        out.append(first.isoformat())
        first = first + _timedelta(days=1)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--date", help="single slate, YYYY-MM-DD")
    parser.add_argument("--start", help="backfill start, YYYY-MM-DD")
    parser.add_argument("--end", help="backfill end, YYYY-MM-DD")
    parser.add_argument("--data-root", help="artifact root (defaults to SYNDICATE_DATA_ROOT, else ./data)")
    parser.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    parser.add_argument("--league", default="wnba", choices=sorted(_LEAGUES), help="wnba (default) or nba")
    args = parser.parse_args(argv)

    if args.start and args.end:
        targets = _dates(args.start, args.end)
    elif args.date:
        targets = [args.date]
    else:
        targets = [(_date.today() - _timedelta(days=1)).isoformat()]

    import os

    root = args.data_root or os.environ.get("SYNDICATE_DATA_ROOT") or None

    wrote = empty = 0
    for date_str in targets:
        result = build_date(date_str, dry_run=bool(args.dry_run),
                            data_root=Path(root) if root else None, league=args.league)
        if result.get("status") in {"ok", "dry_run"}:
            wrote += 1
        elif result.get("status") == "empty":
            empty += 1

    print(f"[{_league(args.league)['tag']}] SUMMARY dates={len(targets)} wrote={wrote} empty={empty}", flush=True)
    if wrote:
        return 0
    return 2 if empty else 1


if __name__ == "__main__":
    raise SystemExit(main())
