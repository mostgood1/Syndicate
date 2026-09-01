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
#
# v3 (2026-08-30) carries `line`, and `record_key` keys on it. This IS a
# population change, not just a new field: three totals lines on one game used
# to collapse to ONE key and deduplicate against each other, so v2 holds roughly
# one totals record per game per book-set where v3 holds one per LINE. Counting
# records across the boundary counts two different things. v2 records cannot be
# repaired -- the line is not recoverable from the stored probability -- so a
# reader that needs `line` (scoring totals/spreads against their own outcomes)
# must filter to `v >= 3` and will find no history before this date.
#
# v4 (2026-09-01) carries the GAME CLOCK (`inning`, `half`, `outs`,
# `outs_recorded`, `progress_fraction`) and `pregame_home_win_prob`. This is
# ADDITIVE and NOT a population change -- `record_key` is untouched, so v3 and
# v4 records count the same things and may be pooled for any question that does
# not read the new fields. A reader that needs them must filter to `v >= 4`;
# earlier records cannot be repaired, because neither the clock nor the pregame
# baseline is recoverable from what was stored.
LEDGER_VERSION = 4

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
    """Identity of a market across builds: game, segment, market, LINE, book set.

    The book set is part of the key because the same market appears once per
    book-consensus row and their prices genuinely differ; collapsing them would
    silently keep whichever was written last.

    **`line` JOINED THE KEY 2026-08-30. IT IS A LATENT HAZARD CLOSED, NOT AN
    OBSERVED COLLISION — the first draft of this comment claimed the collision as
    measured fact and that was WRONG.** A totals market is not one market, it is
    one per line, and the lines carry genuinely different probabilities (the
    served MLB board that day quoted one game at 9.5 / 9.0 / 8.5 with model probs
    0.3167 / 0.3167 / 0.45). But the old four-part key did NOT collide them in
    practice, and the reason is worth keeping: `books_key` is built from the books
    quoting THAT LINE, so it varies with the line and was acting as an accidental
    proxy for it. Checked against production the same day — 6 live records, every
    line on a distinct book set, **0 groups holding more than one line.**

    So this closes a real gap rather than a bleeding wound: nothing guarantees two
    lines cannot draw the same book set, and when they do the old key would have
    had `_moved` compare a 9.5 row against an 8.5 row and dedupe on the answer,
    silently keeping whichever landed last. `str()` rather than the raw value so
    `9.5` and `"9.5"` cannot split one market into two.
    """
    return (
        row.get("game_pk"),
        str(row.get("segment") or ""),
        str(row.get("market") or ""),
        str(row.get("line") if row.get("line") is not None else ""),
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
                # THE LINE THE PROBABILITY IS ABOUT. Absent until 2026-08-30,
                # and its absence had two costs. (1) It is half of this row's
                # IDENTITY -- see `record_key`, where three totals lines on one
                # game collapsed to a single key and deduplicated against each
                # other. (2) It is the only thing that makes a totals or spreads
                # probability SCOREABLE: `live_gameline_score` can compare a
                # home-win probability to a final, but P(over) means nothing
                # without the number it is over. Historical records cannot be
                # repaired -- the line is not recoverable from the stored
                # probability -- so this is what makes that scoring possible
                # from new records onward, and nothing more.
                "line": row.get("line"),
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
                # --- WHERE IN THE GAME THIS PROBABILITY WAS FORMED (v4) ---
                #
                # The 2026-09-01 skill audit could only split by WALL-CLOCK
                # minutes since a game's first ledger row, because nothing here
                # recorded the game clock. That proxy cannot tell a rain delay
                # from a long inning, and cannot separate "bottom 9, tied, two
                # outs" from "top 5 of a blowout" -- which is precisely the axis
                # the model's skill turned out to vary along.
                #
                # `progress` comes from the lens verbatim; the fields are
                # unpacked here rather than stored whole so a reader does not
                # have to know the producer's camelCase.
                "inning": (lg.get("progress") or {}).get("inning"),
                "half": (lg.get("progress") or {}).get("half"),
                "outs": (lg.get("progress") or {}).get("outs"),
                "outs_recorded": (lg.get("progress") or {}).get("outsRecorded"),
                "progress_fraction": (lg.get("progress") or {}).get("fraction"),
                # THE PREGAME NUMBER THE LIVE ONE REPLACED. Without it, "should
                # the live estimate have stayed closer to its prior" is not a
                # question this file can answer -- and the audit's encompassing
                # regression says that is the question. Present from v4 only.
                "pregame_home_win_prob": lg.get("pregame_home_win_prob"),
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


def read_records(path: Path) -> list[dict[str, Any]]:
    """EVERY record, in file order. Missing file -> empty list.

    Distinct from `read_last_by_key` on purpose. That one collapses to the last
    record per market because it exists to DEDUPLICATE writes. Scoring wants the
    opposite: every forecast the model made, including the superseded ones,
    because calibration over a slate is exactly the question "were the
    intermediate numbers right too".

    Same tolerance for a truncated final line as the dedup reader, and for the
    same reason -- a SIGKILL mid-append is expected on this worker and must not
    discard the day's history.
    """
    out: list[dict[str, Any]] = []
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
                    continue
                if isinstance(rec, dict):
                    out.append(rec)
    except Exception:
        return out
    return out


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
