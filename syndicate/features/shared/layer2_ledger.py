"""Layer 2 board picks into the evaluation ledger -- the board grades itself.

WHY (lane `intelligence-evidence-coverage`, user 2026-10-07: "we shouldnt have
seperate lists being generated"). The board users see and execution trades is
the Layer 2 shortlist, but the evaluation ledger -- accuracy, calibration, CLV,
ROI -- only ever recorded the LEGACY intelligence pool
(`maybe_record_board_state_to_evaluation_ledger` reads the per-date state's
`ranked_all`, which holds no Layer 2 card). So every accuracy number described
a list nobody bets.

Three things a Layer 2 card needs before settlement can grade it, measured by
reading `evaluation_settlement` / `settlement_identity` on 2026-10-07:

1. **MLB id space.** A card's `game_pk` is the OddsAPI event hash; MLB graded
   rows carry the StatsAPI gamePk, and `find_graded_row` returns `game_absent`
   with no club fallback when both sides carry ids and none overlap. The
   StatsAPI pk is stamped here through `bet_status_mlb`'s own schedule index
   (the same recovery the order grader uses).
2. **Date.** Records are graded against the recording call's `selected_date`;
   the shortlist spans a window. Only cards whose game falls on that US Eastern
   date are recorded.
3. **Volume.** The ledger id hashes the whole payload, so a card re-recorded on
   every build mints a record per price tick -- in the function whose chunk
   stream OOM'd the worker before. Each `pick_id` is recorded ONCE per date, at
   its first sighting (the same rule as the CLV opening ledger), tracked in a
   tiny per-date sidecar.

DEFAULT OFF (`SYNDICATE_LEDGER_RECORD_LAYER2`): this adds a writer to a shared
ledger; it is switched on deliberately and measured against the legacy records
over a window before the legacy recording is retired.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

_PICK_ID_FIELDS = ("sport", "event_id", "kind", "market", "segment", "side", "line", "player_name")


def _norm(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).strip().lower()


def pick_id(card: Mapping[str, Any]) -> str:
    """The bet's identity, independent of book, price and time.

    Two books quoting the same side at the same line are the same pick; a
    different line is a different bet. Stable across builds, so the ledger and
    the board can be joined on it.
    """
    sport = card.get("sport") or card.get("sport_slug")
    parts = [_norm(sport)] + [_norm(card.get(field)) for field in _PICK_ID_FIELDS[1:]]
    if not parts[2]:
        parts[2] = _norm(card.get("candidate_type"))
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"l2_{digest}"


def recording_enabled() -> bool:
    return str(os.environ.get("SYNDICATE_LEDGER_RECORD_LAYER2") or "").strip().lower() in {"1", "true", "yes", "on"}


def eastern_game_date(card: Mapping[str, Any]) -> str | None:
    from syndicate.features.shared.prop_evidence.common import eastern_date

    stamp = str(card.get("commence_time") or "").strip()
    return eastern_date(stamp) if stamp else None


# The compact record: what settlement reads (sport, ids, market, segment, side,
# team/fixture, player, line, odds, model probability) plus provenance. Volatile
# board fields (score, movement, quote, detail) are left out so the ledger id is
# a function of the PICK and its opening price.
_RECORD_FIELDS = (
    "sport",
    "sport_slug",
    "event_id",
    "kind",
    "market",
    "market_key",
    "segment",
    "side",
    "selection",
    "display_name",
    "team",
    "home_team",
    "away_team",
    "matchup",
    "player_name",
    "player_id",
    "line",
    "odds",
    "commence_time",
    "model_probability",
    "ev_pct",
    "ev_vs_fair_pct",
    "board_lane",
)


def ledger_record(card: Mapping[str, Any], *, mlb_index: Mapping | None = None) -> dict[str, Any]:
    record = {field: card.get(field) for field in _RECORD_FIELDS if card.get(field) is not None}
    record["pick_id"] = card.get("pick_id") or pick_id(card)
    record["source"] = "layer2_shortlist"
    record["candidate_type"] = card.get("kind") or card.get("candidate_type")
    record["name"] = card.get("selection") or card.get("display_name")
    if card.get("model_probability") is not None:
        record["implied_probability"] = card.get("model_probability")
    sport = str(card.get("sport") or card.get("sport_slug") or "").strip().lower()
    if sport == "mlb" and mlb_index is not None:
        from syndicate.features.shared.bet_status_mlb import _resolve_game_pk

        game_pk, _reason = _resolve_game_pk(card, mlb_index)
        if game_pk is not None:
            record["game_pk"] = game_pk
            record["oddsapi_event_id"] = card.get("event_id")
            record.pop("event_id", None)
    return record


def _sidecar_path(reports_root: Path, selected_date: str) -> Path:
    return Path(reports_root) / "intelligence" / "layer2_ledger_picks" / f"{selected_date}.json"


def _read_seen(path: Path) -> set[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(item) for item in (payload.get("pick_ids") or [])} if isinstance(payload, dict) else set()


def first_sightings(
    cards: Iterable[Mapping[str, Any]], selected_date: str, *, reports_root: Path, mlb_index: Mapping | None = None
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Compact records for the cards on `selected_date` not yet recorded that date.

    Returns (records, counts). Does NOT write the sidecar: `mark_recorded`
    does, only after the ledger write succeeded.
    """
    seen = _read_seen(_sidecar_path(reports_root, selected_date))
    counts = {"cards": 0, "other_date": 0, "already": 0, "new": 0, "mlb_pk_stamped": 0, "mlb_pk_missing": 0}
    records: list[dict[str, Any]] = []
    batch: set[str] = set()
    for card in cards:
        if not isinstance(card, Mapping):
            continue
        counts["cards"] += 1
        if eastern_game_date(card) != selected_date:
            counts["other_date"] += 1
            continue
        pid = card.get("pick_id") or pick_id(card)
        if pid in seen or pid in batch:
            counts["already"] += 1
            continue
        record = ledger_record(card, mlb_index=mlb_index)
        if str(record.get("sport") or "").lower() == "mlb":
            counts["mlb_pk_stamped" if "game_pk" in record else "mlb_pk_missing"] += 1
        batch.add(pid)
        records.append(record)
    counts["new"] = len(records)
    return records, counts


def mark_recorded(records: Iterable[Mapping[str, Any]], selected_date: str, *, reports_root: Path) -> None:
    path = _sidecar_path(reports_root, selected_date)
    seen = _read_seen(path)
    seen |= {str(r.get("pick_id")) for r in records if r.get("pick_id")}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"date": selected_date, "pick_ids": sorted(seen)}), encoding="utf-8")
    os.replace(tmp, path)
