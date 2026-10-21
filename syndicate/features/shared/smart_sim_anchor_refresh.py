"""The NBA SmartSim's market anchor follows the market up to tip (lane nba-sim-anchor-staleness, todo #721, 2026-10-21).

WHY. The sim blends its team means toward the market before sampling (``_apply_market_anchor_local``: total 0.7,
margin 0.95). The line it blends toward was the job's ``predictions_<D>.csv`` row, falling back to
``game_odds_<D>.csv``. Both are written ONCE, by ``predict-date`` on the first props refresh that sees the date. The
refresh's lookahead makes that D-2: 10-21's line was written 10-19 3:04 AM CT, about 63 h before tip.
- ``_ensure_game_predictions_for_props_refresh`` reuses a predictions file that has rows.
- ``_seed_game_odds_from_props_snapshot`` returns once game_odds has prices.
Nothing rewrote either, and no reuse check compared odds. Every sim of a date, rebuilds included, anchored to that
line.

Measured on the fleet (``scripts/nba_anchor_staleness.py``, ``.syndicate/findings_2026-10-21_nba_anchor_staleness.md``):
- abs(anchor - last pregame consensus):
  - preseason, 56 games: spread median 1.0, mean 2.2, p90 5.0; 25 games moved 2 pts or more;
  - 10-20: DET_BOS -1.5 -> +1.5, SAS_OKC -2.5 -> +1.5.
- The near-close anchor, scored on 59 games (56 preseason + 3 regular):
  - served margin MAE -0.97 ± 0.36;
  - served total MAE -0.39 ± 0.18.
User decision 2026-10-21: refresh, on by default, kill switch.

THE RULE (NBA only):
1. ``fresh_lines`` reads this run's props snapshot (``oddsapi_player_props_<D>.csv``). The props refresh rewrites it
   on every run, before predictions and sims, with h2h/spreads/totals alongside the player markets. It reduces the
   snapshot with ``consensus_lines_at_close``, the same function ``predict-date`` uses, so the line is the same
   statistic: the modal point across books. Rows for an event that had started at ``snapshot_ts`` are dropped
   (in-play). A snapshot no newer than ``predictions_<D>.csv`` is not used: the stored line is at least as fresh.
2. ``anchor_current`` is the reuse check. A pregame sim whose recorded ``market_anchor`` line is ``MIN_PTS`` or more
   off the fresh line, on the total or the spread, is rebuilt. Replayed over every pregame capture 10-03..10-21:
   2.1 extra builds per regular-season game at 1.0 pt, 4.9 per preseason game. ``smart_sim_tip_freeze`` runs before
   the reuse checks, so a tipped game never gets here.
3. ``override`` replaces the job's line with the fresh one. It stamps ``market_line_source`` / ``market_line_as_of``
   into the job, and the worker copies them into the sim's ``market_anchor``. A side the snapshot does not price
   keeps the stored line.

Pipeline trace (``basketball_props_smart_sim.py``):
- snapshot -> ``fresh_lines``, called once per date before ``_smart_sim_run_date_local``'s per-game loop;
- -> ``anchor_current``, the last condition of the reuse branch's and-chain;
- -> ``override``, right after the job's predictions/game_odds line read;
- -> job ``market_total`` / ``home_spread``;
- -> worker -> ``GameInputsLocal`` -> ``_simulate_quarters_local`` -> ``_apply_market_anchor_local``;
- -> ``market_anchor`` in ``smart_sim_<D>_<H>_<A>.json`` and the engine inputs.
The input is disk-backed on the data root, and ``nba_source/data/processed/oddsapi_player_props_*.csv`` is
allowlisted in ``artifact_publisher``.

Switch ``SYNDICATE_NBA_SIM_ANCHOR_REFRESH``:
- absent or ``on``: refresh and rebuild on drift.
- ``shadow``: log the would-be line and the drift; change nothing.
- ``off`` / ``0`` / ``false`` / ``no``: no snapshot read, no line, no check.
``SYNDICATE_NBA_SIM_ANCHOR_REFRESH_MIN_PTS`` sets the drift threshold (default 1.0).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SWITCH_ENV = "SYNDICATE_NBA_SIM_ANCHOR_REFRESH"
MIN_PTS_ENV = "SYNDICATE_NBA_SIM_ANCHOR_REFRESH_MIN_PTS"
DEFAULT_MIN_PTS = 1.0
SOURCE_LABEL = "props_snapshot_consensus"
_MARKETS = ("h2h", "spreads", "totals")


def mode() -> str:
    raw = str(os.environ.get(SWITCH_ENV, "") or "").strip().lower()
    if raw in {"0", "off", "false", "no"}:
        return "off"
    if raw == "shadow":
        return "shadow"
    return "on"


def min_pts() -> float:
    try:
        value = float(os.environ.get(MIN_PTS_ENV, "") or DEFAULT_MIN_PTS)
    except ValueError:
        return DEFAULT_MIN_PTS
    return value if math.isfinite(value) and value > 0 else DEFAULT_MIN_PTS


def _applies(league: str) -> bool:
    return str(league or "").strip().lower() == "nba"


@dataclass(frozen=True)
class FreshLine:
    total: float | None
    spread: float | None  # home spread, negative = home favoured
    as_of: str
    books: int | None = None


def _utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def fresh_lines(processed_root: Path, date_str: str, *, league: str, to_tricode: Callable[[Any], str],
                stored_written: float | None = None) -> dict[tuple[str, str], FreshLine]:
    """(home_tri, away_tri) -> the current pregame consensus line from this run's props snapshot. Never raises.

    ``stored_written`` is the mtime of the file the job's line comes from (``predictions_<D>.csv``). A snapshot that
    is not newer than it is ignored.
    """
    current = mode()
    if current == "off" or not _applies(league):
        return {}
    path = Path(processed_root) / f"oddsapi_player_props_{str(date_str).strip()}.csv"
    out: dict[tuple[str, str], FreshLine] = {}
    reason = "ok"
    snapshot_ts = None
    try:
        import pandas as pd

        if not path.is_file():
            reason = "no_snapshot"
        else:
            frame = pd.read_csv(path)
            if frame is None or frame.empty or "market" not in frame.columns:
                reason = "empty_snapshot"
            else:
                frame = frame[frame["market"].isin(_MARKETS)].copy()
                stamps = [_utc(v) for v in frame.get("snapshot_ts", pd.Series(dtype=object)).dropna().unique()]
                stamps = [s for s in stamps if s is not None]
                snapshot_ts = max(stamps) if stamps else None
                if snapshot_ts is None:
                    reason = "no_snapshot_ts"
                elif stored_written is not None and snapshot_ts.timestamp() <= float(stored_written):
                    reason = "snapshot_not_newer_than_stored_line"
                else:
                    # In-play rows know the score; a started event is never a pregame line.
                    tips = frame["commence_time"].map(_utc)
                    frame = frame[[tip is not None and tip > snapshot_ts for tip in tips]]
                    if frame.empty:
                        reason = "no_pregame_rows"
                    else:
                        from syndicate.features.nba.source_cli.odds_api import consensus_lines_at_close

                        wide = consensus_lines_at_close(frame)
                        for _, row in (wide if wide is not None else pd.DataFrame()).iterrows():
                            key = (str(to_tricode(row.get("home_team")) or "").upper(),
                                   str(to_tricode(row.get("away_team")) or "").upper())
                            total, spread = _num(row.get("total_point")), _num(row.get("spread_point"))
                            if not key[0] or not key[1] or (total is None and spread is None):
                                continue
                            books = _num(row.get("books_count"))
                            out[key] = FreshLine(total=total, spread=spread, as_of=snapshot_ts.isoformat(),
                                                 books=int(books) if books is not None else None)
    except Exception as exc:  # never break the sim run over a fresher line
        reason = f"error:{type(exc).__name__}"
        out = {}
    print(f"SMART_SIM_ANCHOR_REFRESH league={league} date={date_str} mode={current} games={len(out)} "
          f"snapshot_ts={snapshot_ts.isoformat() if snapshot_ts else None} reason={reason}", flush=True)
    return out


def _recorded_anchor(out_path: Path) -> tuple[float | None, float | None] | None:
    try:
        payload = json.loads(Path(out_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    anchor = payload.get("market_anchor") if isinstance(payload, dict) else None
    if not isinstance(anchor, dict):
        return (None, None)
    return _num(anchor.get("market_total")), _num(anchor.get("market_spread"))


def _gap(fresh: float | None, have: float | None) -> float:
    if fresh is None:
        return 0.0  # the snapshot does not price this side; the stored line stays
    if have is None:
        return math.inf  # the sim ran unanchored on this side and a line now exists
    return abs(fresh - have)


def anchor_current(out_path: Path, fresh: FreshLine | None, *, date_str: str, league: str) -> bool:
    """The reuse check: False (rebuild) when the sim's recorded anchor is MIN_PTS or more off the fresh line."""
    current = mode()
    if current == "off" or fresh is None or not _applies(league):
        return True
    recorded = _recorded_anchor(out_path)
    if recorded is None:
        return True  # unreadable: the other reuse checks own that case
    have_total, have_spread = recorded
    threshold = min_pts()
    drift = max(_gap(fresh.total, have_total), _gap(fresh.spread, have_spread))
    if drift < threshold:
        return True
    print(f"[smart_sim_reuse] SMART_SIM_REUSE_ANCHOR_DRIFT league={league} date={date_str} file={Path(out_path).name} "
          f"have={have_total}/{have_spread} want={fresh.total}/{fresh.spread} as_of={fresh.as_of} "
          f"min_pts={threshold} mode={current}" + (" -> re-simulate" if current == "on" else " (shadow: kept)"),
          flush=True)
    return current != "on"


def override(market_total: float | None, home_spread: float | None, fresh: FreshLine | None, *, date_str: str,
             league: str, home: str, away: str) -> tuple[float | None, float | None, dict[str, Any]]:
    """The job's line: the fresh one when the switch is on. Returns (total, spread, job stamp keys)."""
    current = mode()
    if current == "off" or fresh is None or not _applies(league):
        return market_total, home_spread, {}
    new_total = fresh.total if fresh.total is not None else market_total
    new_spread = fresh.spread if fresh.spread is not None else home_spread
    if new_total != market_total or new_spread != home_spread:
        print(f"SMART_SIM_ANCHOR_LINE league={league} date={date_str} game={home}_{away} "
              f"stored={market_total}/{home_spread} fresh={new_total}/{new_spread} as_of={fresh.as_of} mode={current}",
              flush=True)
    if current != "on":
        return market_total, home_spread, {}
    return new_total, new_spread, {"market_line_source": SOURCE_LABEL, "market_line_as_of": fresh.as_of}
