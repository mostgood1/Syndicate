"""The `track_record` layer: how THIS market has graded for THIS sport.

READS, NEVER GRADES. Settlement belongs to lane `model-scorecard-cron`, which
publishes `reports/model_scorecard/model_scorecard_latest.json` to web (the file
`GET /api/model-scorecard` serves). Its schema, as that lane stated it
2026-09-17:

    windows["7d" | "28d"].cells[] -- one per sport x market x segment x phase:
        sport, market, segment, phase, games, dates,
        model_brier, market_brier, brier_diff (model minus market; > 0 = WORSE),
        ci95, p, lodo_stable,
        verdict  in {beats_market, loses_to_market, parity, insufficient},
        roi_model_side, roi_ci95, roi_games
    windows[w].coverage.by_sport / ungraded_by_sport
    grader.sport_versions, state.resets  -- history is not comparable across a reset

Props are `segment == "full"` cells keyed by the LOWERCASED board market
(`batter_hits`, `receiving yards`, `player_shots_on_target`). Units are per game.
There is no hit-rate field, and this reader does not invent one.

A cell with `verdict == "insufficient"` is reported AS insufficient -- with its
game count -- never as a record. The bar is the scorecard's own (15 games /
3 dates), not one chosen here.

The row's own `projection.model_skill` note is shown beside it, because that is
the producer's statement about whether the model was ever backtested, and it is
the only skill statement most non-MLB rows carry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from syndicate.features.shared.prop_evidence.common import data_root, fmt_num, load_json, mtime_iso, to_float
from syndicate.features.shared.prop_evidence.contract import (
    ABSENT_NO_ARTIFACT,
    ABSENT_NO_SAMPLE,
    Layer,
    LayerEvidence,
    PropSubject,
    absent,
    table,
)

SCORECARD_RELATIVE = Path("reports") / "model_scorecard" / "model_scorecard_latest.json"
WINDOWS = ("7d", "28d")

_VERDICT_TEXT = {
    "beats_market": "beats the market",
    "loses_to_market": "loses to the market",
    "parity": "no measurable difference from the market",
    "insufficient": "not enough graded games yet",
}


def scorecard_path() -> Path:
    return data_root() / SCORECARD_RELATIVE


def _cells_for(scorecard: dict[str, Any], subject: PropSubject) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    windows = scorecard.get("windows") if isinstance(scorecard, dict) else None
    if not isinstance(windows, dict):
        return out
    for window in WINDOWS:
        block = windows.get(window)
        cells = block.get("cells") if isinstance(block, dict) else None
        for cell in cells or []:
            if not isinstance(cell, dict):
                continue
            if str(cell.get("sport") or "").strip().lower() != subject.sport:
                continue
            if str(cell.get("segment") or "").strip().lower() != (subject.segment or "full"):
                continue
            if str(cell.get("market") or "").strip().lower() != subject.market_key:
                continue
            if str(cell.get("phase") or "pregame").strip().lower() != "pregame":
                continue
            out[window] = cell
    return out


def _roi_text(cell: dict[str, Any]) -> str:
    roi = to_float(cell.get("roi_model_side"))
    if roi is None:
        return "—"
    ci = cell.get("roi_ci95") or []
    lo, hi = (to_float(ci[0]), to_float(ci[1])) if isinstance(ci, list) and len(ci) == 2 else (None, None)
    band = f" [{100 * lo:+.0f}%, {100 * hi:+.0f}%]" if lo is not None and hi is not None else ""
    return f"{100 * roi:+.1f}%{band}"


def _skill_rows(subject: PropSubject) -> list[list[Any]]:
    skill = subject.projection.get("model_skill") if isinstance(subject.projection, dict) else None
    if not isinstance(skill, dict) or not skill:
        return []
    status = str(skill.get("status") or "").strip() or "—"
    verdict = str(skill.get("verdict") or "").strip() or "—"
    sample = skill.get("sample_games")
    return [["Model skill note (this row)", status, verdict if not sample else f"{verdict} (n={sample})"]]


def build_track_record(subject: PropSubject) -> LayerEvidence:
    path = scorecard_path()
    skill_rows = _skill_rows(subject)
    if not path.is_file():
        if skill_rows:
            return LayerEvidence(
                layer=Layer.TRACK_RECORD,
                tables=[table(f"Track record — {subject.market}", ["Window", "Verdict", "Detail"], skill_rows, Layer.TRACK_RECORD)],
                source="projection.model_skill",
                facts={"scorecard": None, "model_skill": subject.projection.get("model_skill")},
            )
        return absent(Layer.TRACK_RECORD, f"{ABSENT_NO_ARTIFACT}:model_scorecard_latest.json", source="model_scorecard")

    try:
        scorecard = load_json(path)
    except Exception:
        return absent(Layer.TRACK_RECORD, f"{ABSENT_NO_ARTIFACT}:model_scorecard_latest.json unreadable", source="model_scorecard")

    cells = _cells_for(scorecard, subject)
    rows: list[list[Any]] = []
    facts: dict[str, Any] = {"generated_at": scorecard.get("generated_at"), "cells": {}}
    for window in WINDOWS:
        cell = cells.get(window)
        if not cell:
            continue
        verdict = str(cell.get("verdict") or "insufficient")
        games = cell.get("games")
        dates = cell.get("dates")
        detail = f"{games} games / {dates} dates"
        if verdict != "insufficient":
            diff = to_float(cell.get("brier_diff"))
            detail += f"; Brier model {fmt_num(cell.get('model_brier'), 3)} vs market {fmt_num(cell.get('market_brier'), 3)}"
            if diff is not None:
                detail += f" ({'worse' if diff > 0 else 'better'} by {abs(diff):.3f})"
            detail += f"; ROI on model side {_roi_text(cell)}"
        rows.append([f"Last {window} (graded)", _VERDICT_TEXT.get(verdict, verdict), detail])
        facts["cells"][window] = {k: cell.get(k) for k in (
            "verdict", "games", "dates", "model_brier", "market_brier", "brier_diff", "roi_model_side", "roi_ci95")}

    rows.extend(skill_rows)
    if not rows:
        versions = (scorecard.get("grader") or {}).get("sport_versions") or {}
        reason = "no_graded_cell_for_market" if subject.sport in versions else "sport_not_graded"
        return absent(Layer.TRACK_RECORD, f"{ABSENT_NO_SAMPLE}:{reason}", source="model_scorecard")

    generated = str(scorecard.get("generated_at") or "")
    return LayerEvidence(
        layer=Layer.TRACK_RECORD,
        tables=[table(
            f"Track record — {subject.sport.upper()} {subject.market} (model scorecard{', ' + generated[:10] if generated else ''})",
            ["Window", "Verdict", "Detail"],
            rows,
            Layer.TRACK_RECORD,
        )],
        facts={**facts, "model_skill": subject.projection.get("model_skill")},
        source="model_scorecard",
        as_of=generated or mtime_iso(path),
    )
