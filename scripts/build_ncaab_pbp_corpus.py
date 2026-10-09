"""NCAAB play-by-play backtest corpus: one compact record per finished D-I game.

Phase P4 of `docs/ai_context/basketball_live_native_plan.md` (lane
`ncaab-native-live-tier`). The live tier is graded at in-game checkpoints
against the final and the live close; this is the population it is graded on.
It is also the input for measuring NCAAB's scoring SHAPE (second-half
reversion, end-of-game fouling, bench intervals) before any engine mechanism is
chosen -- the engine standard's mechanism-vs-estimator rule.

ONE FETCH PER GAME, three uses. The ESPN summary that carries the pbp also
carries the team box the ratings producer reads, so every record keeps
`box_rows` in `build_ncaab_team_ratings.parse_summary`'s exact shape. A
walk-forward ratings table "as of the day before" can be rebuilt from the
corpus alone, with no second crawl and no leakage.

What a record holds (`"v": 1`):
  * identity: game_id, date (the scoreboard date queried), season, season_type
    (ESPN: 2 regular, 3 postseason), `phase` (regular / conf_tournament /
    ncaa_tournament / other_postseason), the ESPN notes headline, neutral site;
  * home / away: id, name, final score, period line scores;
  * lines: the summary's pickcenter provider, PREGAME open and close for
    spread (home), total and moneyline. Live in-game prices are NOT in ESPN;
    the live close needs a separate (OddsAPI historical) source;
  * players: [team h/a, athlete id, starter, minutes, PF, PTS] from the box;
  * plays: one row per pbp event, columns in `PLAY_COLUMNS` -- including
    substitutions, fouls, timeouts, the wallclock (to join live odds at a
    checkpoint later) and ESPN's home win probability after the play;
  * check: whether the last pbp score equals the official final.

Output: `<ncaab root>/data/pbp_corpus/pbp_corpus_<season>.jsonl.gz`, appended
(gzip members concatenate), plus `pbp_corpus_<season>.dates.json` for the
dates whose every event is final and recorded. `<ncaab root>` is
`SYNDICATE_NCAAB_SOURCE_ROOT` or `SYNDICATE_DATA_ROOT/ncaab_source`, as the
ratings producer resolves it.

Run research jobs at Idle priority -- the fleet shares this machine:
    py -3 scripts/build_ncaab_pbp_corpus.py --season 2026 --rate 3
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import importlib.util
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Mapping

_SCRIPTS = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location("build_ncaab_team_ratings", _SCRIPTS / "build_ncaab_team_ratings.py")
ratings = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ratings)  # type: ignore[union-attr]

RECORD_VERSION = 1
PLAY_COLUMNS = (
    "seq", "period", "clock", "home", "away", "type", "team", "athlete", "value", "scoring", "shooting", "wall", "wp_home", "sub",
)
SUBSTITUTION_TYPE = 584  # "X subbing in/out for <team>"; `sub` is +1 in, -1 out, None for every other play


def corpus_dir() -> Path:
    return ratings.ncaab_root() / "data" / "pbp_corpus"


def corpus_path(season: int) -> Path:
    return corpus_dir() / f"pbp_corpus_{season}.jsonl.gz"


def dates_path(season: int) -> Path:
    return corpus_dir() / f"pbp_corpus_{season}.dates.json"


# --------------------------------------------------------------------- parse

def clock_seconds(display: Any) -> float | None:
    """"12:34" -> 754.0, "45.3" -> 45.3, anything else -> None."""
    text = str(display or "").strip()
    if not text:
        return None
    try:
        if ":" in text:
            minutes, seconds = text.split(":", 1)
            return int(minutes) * 60 + float(seconds)
        return float(text)
    except ValueError:
        return None


def _wall(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return int(dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _sub_direction(play: Mapping[str, Any]) -> int | None:
    if _int((play.get("type") or {}).get("id")) != SUBSTITUTION_TYPE:
        return None
    text = str(play.get("text") or "").lower()
    if "subbing in" in text or "enters the game" in text:
        return 1
    if "subbing out" in text or "goes to the bench" in text:
        return -1
    return 0  # a substitution whose direction the text does not say; counted, never guessed


def classify_phase(season_type: Any, headline: str, day: str) -> str:
    """regular / conf_tournament / ncaa_tournament / other_postseason.

    ESPN marks the NCAA tournament, NIT and the smaller postseason events as
    season type 3 (checked 2026-03-17..04-06). Conference tournaments stay type
    2 with a notes headline ("Big East Tournament - Quarterfinal", "MAC
    Championship - ..."); November/December multi-team events ALSO carry
    headlines, so a type-2 headline counts as a conference tournament only in
    March.
    """
    text = str(headline or "").lower()
    if _int(season_type) == 3:
        if "men's basketball championship" in text:
            return "ncaa_tournament"
        return "other_postseason"
    if text and str(day)[5:7] == "03":
        return "conf_tournament"
    return "regular"


def _line(node: Any, *path: str) -> float | None:
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    text = str(node or "").strip().lstrip("ou").replace("+", "")
    if text.upper() in {"EVEN", "PK"}:
        return 100.0 if path[-1] == "odds" else 0.0
    try:
        return float(text)
    except ValueError:
        return None


def parse_lines(payload: Mapping[str, Any]) -> dict[str, Any]:
    picks = [p for p in payload.get("pickcenter") or [] if isinstance(p, Mapping)]
    if not picks:
        return {}
    pc = picks[0]
    return {
        "provider": str(((pc.get("provider") or {}).get("name")) or ""),
        "spread_home_open": _line(pc, "pointSpread", "home", "open", "line"),
        "spread_home_close": _line(pc, "pointSpread", "home", "close", "line"),
        "total_open": _line(pc, "total", "over", "open", "line"),
        "total_close": _line(pc, "total", "over", "close", "line"),
        "ml_home_open": _line(pc, "moneyline", "home", "open", "odds"),
        "ml_home_close": _line(pc, "moneyline", "home", "close", "odds"),
        "ml_away_open": _line(pc, "moneyline", "away", "open", "odds"),
        "ml_away_close": _line(pc, "moneyline", "away", "close", "odds"),
    }


CORE_ODDS = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/mens-college-basketball/events/{id}/competitions/{id}/odds"
PREGAME_PROVIDER = "58"  # ESPN BET
LIVE_PROVIDER = "59"  # "ESPN Bet - Live Odds": only the LAST in-play quote survives, with no timestamp


def _american(node: Any, *path: str) -> float | None:
    for key in path:
        if not isinstance(node, Mapping):
            return None
        node = node.get(key)
    if isinstance(node, Mapping):
        node = node.get("american") or node.get("alternateDisplayValue")
    return _line({"x": node}, "x")


def parse_core_odds(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Pregame open/close from ESPN's core odds (provider 58), plus provider 59's last live quote.

    The summary's pickcenter is EMPTY for early-season games (measured
    2026-10-09: 0 of 169 on 2025-11-03, 0 of 82 on 11-15), while the core odds
    still hold them. `live_last` is NOT a live close: it carries no timestamp
    and no game clock, so nothing grades against it.
    """
    out: dict[str, Any] = {}
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        provider = str(((item.get("provider") or {}).get("id")) or "")
        home = item.get("homeTeamOdds") or {}
        away = item.get("awayTeamOdds") or {}
        if provider == PREGAME_PROVIDER and not out.get("provider"):
            out.update({
                "provider": "ESPN BET (core odds)",
                "spread_home_open": _american(home, "open", "pointSpread"),
                "spread_home_close": _american(home, "close", "pointSpread"),
                "total_open": _american(item, "open", "total"),
                "total_close": _american(item, "close", "total"),
                "ml_home_open": _american(home, "open", "moneyLine"),
                "ml_home_close": _american(home, "close", "moneyLine"),
                "ml_away_open": _american(away, "open", "moneyLine"),
                "ml_away_close": _american(away, "close", "moneyLine"),
            })
        elif provider == LIVE_PROVIDER:
            out["live_last"] = {
                "spread_home": _american(home, "current", "pointSpread"),
                "total": _american(item, "current", "total"),
                "note": "last in-play quote, untimestamped; not a live close",
            }
    return out


def parse_players(payload: Mapping[str, Any], side_of: Mapping[str, str]) -> list[list[Any]]:
    out: list[list[Any]] = []
    for team in (payload.get("boxscore") or {}).get("players") or []:
        side = side_of.get(str((team.get("team") or {}).get("id") or ""))
        for block in team.get("statistics") or []:
            names = list(block.get("names") or block.get("labels") or [])
            for athlete in block.get("athletes") or []:
                stats = dict(zip(names, athlete.get("stats") or []))
                out.append([
                    side,
                    str((athlete.get("athlete") or {}).get("id") or ""),
                    bool(athlete.get("starter")),
                    _int(stats.get("MIN")),
                    _int(stats.get("PF")),
                    _int(stats.get("PTS")),
                ])
    return out


def parse_record(payload: Mapping[str, Any], *, season: int, day: str) -> dict[str, Any] | None:
    """One corpus record, or None when the game has no usable pbp or final."""
    header = payload.get("header") or {}
    competition = (header.get("competitions") or [{}])[0]
    competitors = [c for c in competition.get("competitors") or [] if isinstance(c, Mapping)]
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    plays_in = [p for p in payload.get("plays") or [] if isinstance(p, Mapping)]
    if home is None or away is None or not plays_in:
        return None
    home_id, away_id = str((home.get("team") or {}).get("id") or ""), str((away.get("team") or {}).get("id") or "")
    home_score, away_score = _int(home.get("score")), _int(away.get("score"))
    if not home_id or not away_id or home_score is None or away_score is None:
        return None
    side_of = {home_id: "h", away_id: "a"}
    wp = {str(w.get("playId")): w.get("homeWinPercentage") for w in payload.get("winprobability") or [] if isinstance(w, Mapping)}
    plays: list[list[Any]] = []
    for p in plays_in:
        participants = p.get("participants") or []
        athlete = str(((participants[0] or {}).get("athlete") or {}).get("id") or "") if participants else ""
        pid = str(p.get("id") or "")
        plays.append([
            _int(p.get("sequenceNumber")),
            _int((p.get("period") or {}).get("number")),
            clock_seconds((p.get("clock") or {}).get("displayValue")),
            _int(p.get("homeScore")),
            _int(p.get("awayScore")),
            _int((p.get("type") or {}).get("id")),
            side_of.get(str((p.get("team") or {}).get("id") or "")),
            athlete or None,
            _int(p.get("scoreValue")),
            bool(p.get("scoringPlay")),
            bool(p.get("shootingPlay")),
            _wall(p.get("wallclock")),
            wp.get(pid),
            _sub_direction(p),
        ])
    last = next((row for row in reversed(plays) if row[3] is not None and row[4] is not None), None)
    pbp_final = [last[3], last[4]] if last else None
    # The SUMMARY carries the headline as header.gameNote; competition.notes is
    # the scoreboard's field and is None here (measured 2026-10-09, an NCAA
    # first-round game). Read both.
    notes = competition.get("notes") or []
    headline = str(header.get("gameNote") or ((notes[0] or {}).get("headline") if notes else "") or "")
    season_type = (header.get("season") or {}).get("type")

    def _side(c: Mapping[str, Any], score: int) -> dict[str, Any]:
        team = c.get("team") or {}
        return {
            "id": str(team.get("id") or ""),
            "name": str(team.get("location") or team.get("displayName") or ""),
            "score": score,
            "linescores": [_int((ls or {}).get("displayValue")) for ls in c.get("linescores") or []],
        }

    return {
        "v": RECORD_VERSION,
        "game_id": str(header.get("id") or ""),
        "date": day,
        "season": season,
        "season_type": _int(season_type),
        "phase": classify_phase(season_type, headline, day),
        "notes": headline,
        "neutral": bool(competition.get("neutralSite")),
        "conference_game": bool(competition.get("conferenceCompetition")),
        "home": _side(home, home_score),
        "away": _side(away, away_score),
        "lines": parse_lines(payload),
        "box_rows": ratings.parse_summary(payload, season=season, day=day),
        "players": parse_players(payload, side_of),
        "plays_cols": list(PLAY_COLUMNS),
        "plays": plays,
        "check": {
            "pbp_final": pbp_final,
            "pbp_final_matches": pbp_final == [home_score, away_score],
            "n_plays": len(plays),
            "n_subs": sum(1 for row in plays if row[5] == SUBSTITUTION_TYPE),
            "n_subs_undirected": sum(1 for row in plays if row[13] == 0),
            "n_wp": sum(1 for row in plays if row[12] is not None),
        },
    }


def _get_core(url: str, *, timeout: float = 30.0) -> Any:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 -- lines are optional; the game is not
        print(f"[ncaab_pbp_corpus] CORE_ODDS_FAILED url={url} {type(exc).__name__}", flush=True)
        return {}


# ---------------------------------------------------------------------- io

def read_records(path: Path) -> Iterable[dict[str, Any]]:
    if not path.is_file():
        return
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def append_record(path: Path, record: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "at", encoding="utf-8") as handle:
        handle.write(json.dumps(record, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------- run

def run(season: int, today: dt.date, *, rate: float, max_new_games: int | None, start: dt.date | None, end: dt.date | None) -> dict[str, Any]:
    path = corpus_path(season)
    done_path = dates_path(season)
    done_dates: set[str] = set()
    if done_path.is_file():
        done_dates = set(json.loads(done_path.read_text(encoding="utf-8")).get("dates") or [])
    have = {r.get("game_id") for r in read_records(path)}
    counts = {"dates_checked": 0, "games_written": 0, "games_unusable": 0, "final_mismatch": 0, "errors": 0}
    budget = max_new_games
    for day in ratings.season_dates(season, today):
        if (start and day < start) or (end and day > end):
            continue
        key = day.isoformat()
        if key in done_dates:
            continue
        counts["dates_checked"] += 1
        try:
            ids, all_final = ratings.final_event_ids(day)
            time.sleep(1.0 / rate)
        except Exception as exc:  # noqa: BLE001
            print(f"[ncaab_pbp_corpus] SCOREBOARD_FAILED date={key} {exc}", flush=True)
            counts["errors"] += 1
            continue
        complete = all_final
        for event_id in ids:
            if event_id in have:
                continue
            if budget is not None and budget <= 0:
                complete = False
                break
            try:
                record = parse_record(ratings._get_json(f"summary?event={event_id}"), season=season, day=key)
                time.sleep(1.0 / rate)
                if record is not None and record["lines"].get("total_close") is None:
                    record["lines"] = {**parse_core_odds(_get_core(CORE_ODDS.format(id=event_id))), **{k: v for k, v in record["lines"].items() if v is not None}}
                    time.sleep(1.0 / rate)
            except Exception as exc:  # noqa: BLE001
                print(f"[ncaab_pbp_corpus] SUMMARY_FAILED event={event_id} {exc}", flush=True)
                counts["errors"] += 1
                complete = False
                continue
            if record is None:
                counts["games_unusable"] += 1
                continue
            if not record["check"]["pbp_final_matches"]:
                counts["final_mismatch"] += 1
            append_record(path, record)
            have.add(event_id)
            counts["games_written"] += 1
            if budget is not None:
                budget -= 1
        if complete:
            done_dates.add(key)
            done_path.parent.mkdir(parents=True, exist_ok=True)
            done_path.write_text(json.dumps({"season": season, "dates": sorted(done_dates)}), encoding="utf-8")
        if budget is not None and budget <= 0:
            break
        if counts["dates_checked"] % 10 == 0:
            print(f"[ncaab_pbp_corpus] PROGRESS date={key} games={len(have)} " + " ".join(f"{k}={v}" for k, v in counts.items()), flush=True)
    summary = {**counts, "season": season, "games_total": len(have), "path": str(path)}
    print("[ncaab_pbp_corpus] RUN " + " ".join(f"{k}={v}" for k, v in summary.items()), flush=True)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--season", type=int, default=None, help="ESPN season year (the year it ends)")
    parser.add_argument("--rate", type=float, default=3.0, help="requests per second (default 3)")
    parser.add_argument("--max-new-games", type=int, default=None)
    parser.add_argument("--start", type=dt.date.fromisoformat, default=None)
    parser.add_argument("--end", type=dt.date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    today = dt.date.today()
    season = args.season or ratings.default_season(today)
    summary = run(season, today, rate=max(args.rate, 0.2), max_new_games=args.max_new_games, start=args.start, end=args.end)
    return 0 if summary["errors"] == 0 or summary["games_written"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
