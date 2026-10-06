"""Refuse basketball prop lines for players the injury feed lists OUT -- per line, on its own fact.

WHY THIS EXISTS (lane wnba-props-out-player-leak, 2026-10-06). The baseline props path never read the
injury feed. ``basketball_props_predictions`` projects the whole roster, ``export_props_edges_local`` prices
every quoted line against that projection, and ``export_props_recommendations_local`` turns every +EV edge
row into a play. SmartSim's exclusion (``basketball_props_smart_sim._smart_sim_injuries_excluded_map_for_date_local``)
only shapes the sim ladders. Measured on the fleet 2026-10-06 for the 2026-10-07 WNBA slate: 64 edge lines
for OUT players, and 3 OUT players carrying a top play (Allisha Gray threes OVER 1.5 +118, EV 31.7%; Jewell
Loyd; Stephanie Talbot) while SmartSim had dropped them.

The refusal is applied in ``export_props_edges_local`` because everything downstream reads that file:
props_recommendations, recommendations_slate, props_recommendations_top_by_game, cards_props_snapshot, and the
board's recommendation-engine prop rows. NBA and WNBA both call it.

RULES
- Each line is its own decision (user prime directive): a line is refused only because ITS player's latest
  feed status is OUT. Nothing here gates a market, a game or a slate.
- OUT means confirmed not playing: OUT, SUSPENDED, INACTIVE, or season-ending/indefinite. DAY-TO-DAY,
  QUESTIONABLE, PROBABLE and DOUBTFUL stay priced.
- The feed (``data/raw/injuries.csv``) is a stack of DAILY SNAPSHOTS of the current injury report, and a
  player who returns simply drops off the next one (measured 2026-10-06: Jewell Loyd and Stephanie Talbot are
  on the 10-05 snapshot and absent from 10-06). So the status comes from the LATEST SNAPSHOT dated on or
  before the game date, never from the player's latest row -- that rule would keep refusing a returned player
  for as long as her old row stayed in the window. A snapshot older than ``_STALE_SNAPSHOT_DAYS`` counts only
  for season-ending designations.
- A missing or unreadable feed refuses nothing, and says so (``feed_status``). Refusing every line because
  the feed is absent would be a slate-wide gate.
- Names are compared with ONE normalizer applied to both sides (punctuation, accents and suffixes folded).
  Lesson of 2026-10-05: two normalizers silently disagreed on apostrophes.
- The feed's team can be stale (traded players, measured 2026-10-03). A name match on a different team is
  refused only when the slate puts that name on exactly one team, so a healthy namesake is never refused.

Kill switch: ``SYNDICATE_PROPS_OUT_PLAYER_REFUSAL=0``. Absent means ON.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any

REFUSAL_REASON = "player OUT on the injury feed"
_SWITCH_ENV = "SYNDICATE_PROPS_OUT_PLAYER_REFUSAL"
_STALE_SNAPSHOT_DAYS = 7
_OUT_STATUSES = frozenset({"OUT", "SUSPENDED", "INACTIVE"})


def refusal_enabled() -> bool:
    raw = str(os.environ.get(_SWITCH_ENV, "") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def player_key(value: object) -> str:
    text = str(value or "").strip()
    if "(" in text:
        text = text.split("(", 1)[0]
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = text.replace("-", " ").replace(",", " ")
    text = re.sub(r"[.'`]", "", text)
    text = re.sub(r"\s+", " ", text).strip().upper()
    for suffix in (" JR", " SR", " II", " III", " IV"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    return text


def _is_out_status(status: object, injury: object = "") -> bool:
    text = str(status or "").strip().upper()
    if text in _OUT_STATUSES:
        return True
    detail = f"{text} {str(injury or '').strip().upper()}"
    return _is_season_out(detail)


def _is_season_out(text: str) -> bool:
    return ("SEASON" in text and "OUT" in text) or "INDEFINITE" in text or "SEASON-ENDING" in text


def injury_feed_path(source_root: Path) -> Path:
    return Path(source_root) / "data" / "raw" / "injuries.csv"


def out_players_for_date(*, source_root: Path, date_str: str) -> dict[str, Any]:
    """Latest feed status per player as of ``date_str``; returns the OUT players keyed by ``player_key``."""
    feed_path = injury_feed_path(source_root)
    result: dict[str, Any] = {"feed_path": str(feed_path), "feed_status": "absent", "feed_rows": 0, "out": {}}
    if not feed_path.exists():
        return result
    try:
        game_date = dt.date.fromisoformat(str(date_str).strip()[:10])
        with feed_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    except Exception as exc:  # unreadable feed: refuse nothing, say why
        result["feed_status"] = f"unreadable: {type(exc).__name__}"
        return result
    result["feed_rows"] = len(rows)
    dated: list[tuple[dt.date, dict[str, str]]] = []
    for row in rows:
        try:
            row_date = dt.date.fromisoformat(str(row.get("date") or "").strip()[:10])
        except ValueError:
            continue
        if row_date <= game_date:
            dated.append((row_date, row))
    if not dated:
        result["feed_status"] = "no snapshot on or before the game date"
        return result
    snapshot_date = max(row_date for row_date, _ in dated)
    result["snapshot_date"] = snapshot_date.isoformat()
    stale = (game_date - snapshot_date).days > _STALE_SNAPSHOT_DAYS
    out: dict[str, dict[str, str]] = {}
    for row_date, row in dated:
        if row_date != snapshot_date:
            continue
        status = row.get("status") or row.get("injury_status")
        injury = row.get("injury") or ""
        if not _is_out_status(status, injury):
            continue
        if stale and not _is_season_out(f"{str(status or '').upper()} {str(injury).upper()}"):
            continue
        key = player_key(row.get("player") or row.get("player_name"))
        if not key:
            continue
        out[key] = {
            "player": str(row.get("player") or row.get("player_name") or ""),
            "team": str(row.get("team") or row.get("team_tri") or "").strip().upper(),
            "status": str(status or "").strip().upper(),
            "feed_date": row_date.isoformat(),
        }
    result["feed_status"] = "read (snapshot stale: season-ending only)" if stale else "read"
    result["out"] = out
    return result


def refuse_out_player_lines(edges, *, source_root: Path, date_str: str, league: str | None, out_dir: Path | None):
    """Drop the edge rows whose player is OUT on the feed. Never raises: a failure here must not take down the
    edges stage for the whole slate, so it keeps every line and prints PROPS_OUT_PLAYER_REFUSAL_FAILED."""
    try:
        return _refuse_out_player_lines(edges, source_root=source_root, date_str=date_str, league=league, out_dir=out_dir)
    except Exception as exc:
        print(
            "[basketball_props_availability] PROPS_OUT_PLAYER_REFUSAL_FAILED "
            f"league={league} date={date_str} error={type(exc).__name__}: {exc}",
            flush=True,
        )
        return edges


def _refuse_out_player_lines(edges, *, source_root: Path, date_str: str, league: str | None, out_dir: Path | None):
    """Drop the edge rows whose player is OUT on the feed; print the count and write a sidecar.

    ``edges`` is the priced-lines DataFrame from ``_compute_props_edges_file_only_local``. Returns the kept rows.
    """
    league_code = str(league or Path(source_root).name.replace("_source", "") or "").strip().lower()
    summary: dict[str, Any] = {
        "date": str(date_str),
        "league": league_code,
        "reason": REFUSAL_REASON,
        "enabled": refusal_enabled(),
        "lines_considered": 0,
        "lines_refused": 0,
        "players_refused": [],
    }
    if not summary["enabled"]:
        summary["feed_status"] = "not read (switch off)"
        _emit(summary, out_dir)
        return edges

    feed = out_players_for_date(source_root=source_root, date_str=date_str)
    summary.update({key: feed[key] for key in ("feed_path", "feed_status", "feed_rows", "snapshot_date") if key in feed})
    out = feed["out"]
    summary["out_players_on_feed"] = len(out)
    columns_attr = getattr(edges, "columns", None)
    columns = list(columns_attr) if columns_attr is not None else []
    if not out or getattr(edges, "empty", True) or "player_name" not in columns:
        if out and not getattr(edges, "empty", True) and "player_name" not in columns:
            summary["feed_status"] = f"{summary['feed_status']}; edges carry no player_name column"
        index = getattr(edges, "index", None)
        summary["lines_considered"] = int(len(index)) if index is not None else 0
        _emit(summary, out_dir)
        return edges

    keys = edges["player_name"].map(player_key)
    teams = edges["team"].astype(str).str.strip().str.upper() if "team" in columns else None
    teams_by_key: dict[str, set[str]] = {}
    if teams is not None:
        for key, team in zip(keys.tolist(), teams.tolist()):
            if key and team and team not in {"NAN", "NONE"}:
                teams_by_key.setdefault(key, set()).add(team)

    refuse = []
    per_player: dict[tuple[str, str], dict[str, Any]] = {}
    for position, key in enumerate(keys.tolist()):
        entry = out.get(key)
        line_team = teams.iloc[position] if teams is not None else ""
        hit = False
        if entry is not None:
            if not entry["team"] or entry["team"] == line_team or len(teams_by_key.get(key, set())) <= 1:
                hit = True
        refuse.append(hit)
        if hit:
            slot = per_player.setdefault(
                (key, line_team),
                {
                    "player": str(edges["player_name"].iloc[position]),
                    "team": line_team,
                    "feed_team": entry["team"],
                    "status": entry["status"],
                    "feed_date": entry["feed_date"],
                    "lines": 0,
                },
            )
            slot["lines"] += 1

    import pandas as pd

    mask = pd.Series(refuse, index=edges.index)
    summary["lines_considered"] = int(len(edges.index))
    summary["lines_refused"] = int(mask.sum())
    summary["players_refused"] = sorted(per_player.values(), key=lambda item: (-item["lines"], item["player"]))
    _emit(summary, out_dir)
    return edges.loc[~mask].copy()


def _emit(summary: dict[str, Any], out_dir: Path | None) -> None:
    # `print`, not logger: the logger never reaches the log collector. Emitted at zero too, so a reading
    # can tell "ran, nothing to refuse" from "never ran".
    names = ",".join(f"{item['player']}({item['team']}):{item['lines']}" for item in summary.get("players_refused", []))
    print(
        "[basketball_props_availability] PROPS_OUT_PLAYER_REFUSED "
        f"league={summary.get('league')} date={summary.get('date')} enabled={summary.get('enabled')} "
        f"feed_status={summary.get('feed_status')} snapshot={summary.get('snapshot_date', '-')} out_on_feed={summary.get('out_players_on_feed', 0)} "
        f"lines_considered={summary.get('lines_considered')} lines_refused={summary.get('lines_refused')} "
        f"players={names or '-'}",
        flush=True,
    )
    if out_dir is None:
        return
    try:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = dict(summary)
        payload["written_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (out_dir / f"props_out_player_refusals_{summary.get('date')}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
    except Exception as exc:
        print(f"[basketball_props_availability] PROPS_OUT_PLAYER_REFUSAL_SIDECAR_FAILED {type(exc).__name__}: {exc}", flush=True)
