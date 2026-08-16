"""Persist live game-line edges at the moment they are computed.

Lane `live-game-line-projection`, built for `clv-without-settlement`.

WHY THIS EXISTS. `live_gamelines` is recomputed from scratch on every board
build, for whatever games are live at that instant. Measured 2026-08-16 on ONE
slate: `rows_live_gameline_edged` read **25 -> 4 -> 1** across three consecutive
builds. CLV needs `(edge at time T)` paired with `(price at settlement)`, and
the first half was never written down — by the time a game settles, the row that
carried its edge has been overwritten many times over. **Nothing here computes
CLV; it makes CLV computable later.**

Mirrors the precedent this repo already set for recommendations
(`2b14fbeb`, the opening-price recorder, 584 bytes/record) rather than inventing
a second shape.

THREE DESIGN CONSTRAINTS, each from a measured cost in this repo.

1. **Disk, not keyvalue.** `reports/**` is keyvalue-backed with an 8 MB payload
   ceiling on a 256 MB shared store; an append-only ledger there would blow it.
   This writes JSONL under `data/<sport>_source/`, which is disk-backed.
2. **Deduplicated against the LAST record for the same market**, not written
   once per build. The board rebuilds every few minutes and most rows do not
   move between builds; recording unconditionally would multiply the file by the
   build rate for no information. A record is written only when the model or
   market number actually changes — so the file is a movement history, which is
   what CLV wants, at a fraction of the size.
3. **Bounded per build and per file**, and it says so in its own counters when
   it truncates. A silent cap reads as "that is all that happened", which is the
   failure mode `book_grid_artifact` already documents at length.

WHAT IS DELIBERATELY NOT HERE. No close, no settlement, no CLV arithmetic, no
opinion about which side is right. `closing_price` is owned by
`closing-stamp-is-detection-time` and currently records the HOME price on every
row (18/18), so pairing here would inherit a known defect. This records the
OPEN half and stops.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# v1 recorded PRICEABLE rows only. v2 records every PROJECTED row and carries
# `priceable` / `withheld_reason` per record. **The version is load-bearing for
# any reader**: a rate computed across both populations is a rate over two
# different denominators. Filter on `v` before aggregating, never on date.
LEDGER_VERSION = 2

# A live slate tops out around 15 games x a handful of priceable markets. 500
# is far above that and still bounds a pathological build.
_MAX_RECORDS_PER_BUILD = 500
# ~600 bytes/record x 20k = ~12 MB/day worst case, on a disk with 50 GB.
_MAX_RECORDS_PER_FILE = 20_000


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ledger_path(sport: str, date_str: str) -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    slug = str(sport or "").strip().lower()
    return (
        data_root()
        / f"{slug}_source"
        / "data"
        / "live_gameline_ledger"
        / f"live_gameline_ledger_{str(date_str).strip()}.jsonl"
    )


def _enabled() -> bool:
    """Default ON with an env kill switch.

    `learnings.md`: worker periodic work is never free (`#241` caused a
    production restart loop). This is an append of a few hundred bytes per
    changed market per build, not a computation — but it still gets a switch
    that needs no deploy to throw.
    """
    raw = str(os.environ.get("MLB_LIVE_GAMELINE_LEDGER_ENABLED") or "").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def record_key(row: Mapping[str, Any]) -> tuple:
    """Identity of a market across builds: game, segment, market, book set.

    The book set is part of the key because the same market appears once per
    book-consensus row and their prices genuinely differ; collapsing them would
    silently keep whichever was written last.
    """
    return (
        row.get("game_pk"),
        str(row.get("segment") or ""),
        str(row.get("market") or ""),
        str(row.get("books_key") or ""),
    )


def _moved(previous: Mapping[str, Any] | None, current: Mapping[str, Any]) -> bool:
    """Has anything CLV would care about changed since the last record?

    Compares the two numbers that define the observation. Timestamps and row
    ordering are excluded on purpose — including them would make every build
    look like movement and defeat the deduplication entirely.
    """
    if previous is None:
        return True
    # `priceable` is compared even though it is derived: it depends on `sims_run`
    # through the standard error, and `sims_run` is NOT one of the compared
    # numbers. A row can therefore cross the noise bar with identical model and
    # market probabilities, and that crossing is exactly the event this file
    # exists to timestamp.
    for field in ("model_home_win_prob", "market_fair_prob", "edge_pp", "priceable"):
        if previous.get(field) != current.get(field):
            return True
    return False


def build_records(
    grid: Any,
    *,
    sport: str,
    date_str: str,
    generated_at: str | None = None,
) -> list[dict[str, Any]]:
    """One record per PROJECTED live game-line row on this grid.

    **CHANGED IN v2, ON A MEASUREMENT THAT REFUTED v1's PREMISE.** v1 recorded
    priceable rows only, justified by "recording thousands of refusals per build
    would bury the handful of rows CLV can actually score." Measured 2026-08-16
    03:00Z on a live slate: the ENTIRE live game-line population is **8 rows per
    build, 2 of them projected, 0 priceable** — so `candidates` was 0 and the
    ledger was never asked to write anything. There are no thousands. The
    projected population costs ~2 records per build against a 20,000-record cap.

    **Why this is not a widening for its own sake.** Priceable is a decision
    about the ESTIMATOR'S noise at 120 sims, not about the model. Recording only
    the rows that clear it means the file can only ever answer "did the tail that
    cleared a 2σ bar beat the close" — a self-selected sample, with an n small
    enough that the answer is unfalsifiable. Recording every projected row keeps
    `priceable` as a FIELD, so that question is still askable, and adds the
    denominator that makes it a rate.

    The gate is presence of the join's own `live_gameline` block, which
    `attach_live_gamelines` attaches on exactly the `projected=True` path — rows
    refused earlier (wrong segment, no live projection) never get one, so they
    stay out without a second rule here deciding it.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(grid, (list, tuple)):
        return out
    stamp = str(generated_at or _now_iso())
    for row in grid:
        if not isinstance(row, Mapping):
            continue
        lg = row.get("live_gameline")
        if not isinstance(lg, Mapping):
            continue
        books = sorted({str(b).strip().lower() for b in (row.get("books") or []) if str(b).strip()})
        game = row.get("game") if isinstance(row.get("game"), Mapping) else {}
        out.append(
            {
                "v": LEDGER_VERSION,
                "recorded_at": stamp,
                "sport": str(sport or "").strip().lower(),
                "date": str(date_str or "").strip(),
                # --- identity, so a close can be joined to this later ---
                "game_pk": lg.get("game_pk"),
                "event_id": row.get("event_id"),
                "home_team": row.get("home_team"),
                "away_team": row.get("away_team"),
                "segment": row.get("segment"),
                "market": row.get("market"),
                "books_key": ",".join(books),
                # --- the OPEN half of CLV ---
                "model_home_win_prob": lg.get("model_prob"),
                "market_fair_prob": lg.get("market_prob"),
                "edge_pp": lg.get("edge_pp"),
                # WHETHER THE BOARD WOULD HAVE SHOWN THIS EDGE, kept as a field
                # rather than as a filter. A CLV pass restricted to
                # `priceable: true` reproduces v1's population exactly; one that
                # ignores it measures the model instead of the publish gate.
                # Absent must never read as false, so both are written always.
                "priceable": bool(lg.get("priceable")),
                "withheld_reason": lg.get("withheld_reason"),
                "sigma": lg.get("sigma"),
                # --- what makes the number interpretable later ---
                "prob_std_err": lg.get("prob_std_err"),
                "sims_run": lg.get("sims_run"),
                "live_state_as_of": lg.get("as_of"),
                "carried_forward": bool(lg.get("carried_forward")),
                "game_state": game.get("state"),
                "home_score": game.get("home_score"),
                "away_score": game.get("away_score"),
                # Quote age at record time. `state.md` (program Tier 1) requires
                # cadence/quote age on every CLV record: an "opening" price can
                # be up to two hours off the real open in the pregame regime.
                "quote_age_seconds": row.get("age_seconds"),
                "quote_updated_at": row.get("updated_at"),
                # Which sharp books were quoting THIS market at THIS moment.
                # `state.md`'s "100% sharp coverage" is the sharp SET; Pinnacle
                # specifically was 15/30 in production, so a Pinnacle-referenced
                # close covers about half the population and the join must know.
                "sharp_books": [b for b in books if b in _SHARP_BOOKS],
                "has_pinnacle": "pinnacle" in books,
            }
        )
    return out


_SHARP_BOOKS = frozenset({"pinnacle", "betfair_ex_eu", "matchbook", "novig", "prophetx"})


def read_last_by_key(path: Path) -> dict[tuple, dict[str, Any]]:
    """Last record per market key, for deduplication. Missing file -> empty."""
    out: dict[tuple, dict[str, Any]] = {}
    try:
        if not path.is_file():
            return out
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    # A truncated final line is expected after a SIGKILL mid-append
                    # and must not discard the whole history.
                    continue
                if isinstance(rec, dict):
                    out[record_key(rec)] = rec
    except Exception:
        return out
    return out


def append_records(path: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    """Append the records that MOVED. Returns counters, never raises."""
    coverage: dict[str, Any] = {
        "candidates": len(records),
        "written": 0,
        "skipped_unchanged": 0,
        "truncated_build_cap": 0,
        "truncated_file_cap": 0,
        "enabled": True,
    }
    if not _enabled():
        coverage["enabled"] = False
        return coverage
    if not records:
        return coverage

    if len(records) > _MAX_RECORDS_PER_BUILD:
        coverage["truncated_build_cap"] = len(records) - _MAX_RECORDS_PER_BUILD
        records = records[:_MAX_RECORDS_PER_BUILD]

    try:
        previous = read_last_by_key(path)
        existing_lines = len(previous)
        to_write = []
        for rec in records:
            if _moved(previous.get(record_key(rec)), rec):
                to_write.append(rec)
            else:
                coverage["skipped_unchanged"] += 1
        if existing_lines >= _MAX_RECORDS_PER_FILE:
            coverage["truncated_file_cap"] = len(to_write)
            return coverage
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for rec in to_write:
                handle.write(json.dumps(rec, separators=(",", ":"), default=str) + "\n")
        coverage["written"] = len(to_write)
    except Exception as exc:
        # A ledger failure must never take down the board build. The board is
        # the product; this is instrumentation for a measurement that does not
        # exist yet.
        coverage["error"] = f"{type(exc).__name__}: {exc}"
    return coverage


def record_live_gamelines(grid: Any, *, sport: str, date_str: str,
                          generated_at: str | None = None) -> dict[str, Any]:
    """Entry point for the artifact builder. Never raises."""
    try:
        records = build_records(grid, sport=sport, date_str=date_str, generated_at=generated_at)
        return append_records(ledger_path(sport, date_str), records)
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "written": 0}
