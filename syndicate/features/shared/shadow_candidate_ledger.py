"""Shadow-recording for candidates `filter_candidates` rejects.

Context: Syndicate learning-loop plan, Stage 2's deliberately-deferred
other half (docs/reports/syndicate_learning_loop_plan_2026_08_03.md).
CLV-first policy promotion only ever sees PUBLISHED candidates -- the
filter's own precision (how good were the candidates it turned away?)
has never been measurable, because rejected candidates were computed,
logged as a summary reason, and discarded (recommendation_engine.py's
`filter_candidates` builds a real `rejected` list every call and never
returns or persists it).

Deliberately NOT built on evaluation_evaluation.py's ledger machinery.
That ledger has a real, documented OOM/4.9GB-chunk incident history from
unbounded per-cycle growth (each record embedding a full manifest blob);
reusing it for a stream that is, by construction, larger than the
published-candidate stream would repeat exactly that failure. This
module is intentionally much smaller in scope:
  - a SEPARATE root (shadow_candidate_ledger/, never evaluation_ledger*)
    so a bug or unexpected growth here can never corrupt or bloat the
    real evaluation ledger the settlement/reliability pipeline reads.
  - LEAN records only (the handful of fields needed to identify and
    later grade a candidate), never the candidate's full payload.
  - a hard per-cycle cap AND deterministic sampling, both enforced here
    rather than trusted to a caller, so a config mistake fails toward
    "records too little" rather than "records everything".
  - off by default (SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED), same
    dark-launch discipline as every autorun added this session.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.source_roots import repo_root_from

DEFAULT_SHADOW_LEDGER_ROOT = repo_root_from(__file__) / "reports" / "intelligence" / "shadow_candidate_ledger"

# The exact fields needed to identify a candidate and later grade it the
# same way evaluation_settlement.py grades a real recommendation --
# nothing else. No market_context, no simulation payload, no manifest
# metadata: those are precisely the fields that made the real ledger's
# records large enough to matter.
_LEAN_FIELDS = (
    "candidate_id",
    "sport_slug",
    "sport",
    "candidate_type",
    "market",
    "market_key",
    "selection",
    "pick",
    "name",
    "player_name",
    "team",
    "home_team",
    "away_team",
    "event_id",
    "game_id",
    "matchup",
    "line",
    "odds",
    "model_probability",
    "implied_probability",
    "edge",
    "confidence",
    "selected_date",
)


def _shadow_ledger_enabled() -> bool:
    raw = str(os.environ.get("SYNDICATE_SHADOW_CANDIDATE_LEDGER_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _sample_rate() -> float:
    raw = str(os.environ.get("SYNDICATE_SHADOW_CANDIDATE_LEDGER_SAMPLE_RATE") or "").strip()
    try:
        value = float(raw) if raw else 0.10
    except ValueError:
        value = 0.10
    return max(0.0, min(1.0, value))


def _max_records_per_cycle() -> int:
    raw = str(os.environ.get("SYNDICATE_SHADOW_CANDIDATE_LEDGER_MAX_PER_CYCLE") or "").strip()
    try:
        value = int(raw) if raw else 50
    except ValueError:
        value = 50
    return max(0, value)


def _retention_days() -> int:
    raw = str(os.environ.get("SYNDICATE_SHADOW_CANDIDATE_LEDGER_RETENTION_DAYS") or "").strip()
    try:
        value = int(raw) if raw else 21
    except ValueError:
        value = 21
    return max(1, value)


def shadow_ledger_path(date_str: str, *, root: Path | None = None) -> Path:
    base = root if root is not None else DEFAULT_SHADOW_LEDGER_ROOT
    token = str(date_str or "unknown").strip()[:10] or "unknown"
    return base / f"{token}.jsonl"


def _candidate_sample_key(candidate: Mapping[str, Any]) -> str:
    candidate_id = str(candidate.get("candidate_id") or "").strip()
    if candidate_id:
        return candidate_id
    # Fall back to a stable composite when candidate_id is missing so
    # sampling is still deterministic (same candidate, same cycle,
    # same in/out decision) rather than silently always-in via a
    # constant-string collision.
    parts = (
        str(candidate.get("sport_slug") or candidate.get("sport") or ""),
        str(candidate.get("market") or candidate.get("market_key") or ""),
        str(candidate.get("selection") or candidate.get("pick") or candidate.get("name") or ""),
        str(candidate.get("event_id") or candidate.get("game_id") or candidate.get("matchup") or ""),
    )
    return "|".join(parts)


def _is_sampled_in(candidate: Mapping[str, Any], *, rate: float) -> bool:
    if rate >= 1.0:
        return True
    if rate <= 0.0:
        return False
    key = _candidate_sample_key(candidate)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    # First 8 hex chars as a uniform-ish [0, 1) draw -- deterministic per
    # candidate identity, not per process/run, so the same rejected
    # candidate reappearing across consecutive cycles doesn't flip in and
    # out of the sample on every tick.
    bucket = int(digest[:8], 16) / 0xFFFFFFFF
    return bucket < rate


def _lean_record(candidate: Mapping[str, Any], *, reason: str, selected_date: str) -> dict[str, Any]:
    record: dict[str, Any] = {"shadow": True, "rejection_reason": reason, "selected_date": selected_date}
    for field_name in _LEAN_FIELDS:
        value = candidate.get(field_name)
        if value not in (None, ""):
            record[field_name] = value
    return record


def record_shadow_candidates(
    rejected_candidates: list[Mapping[str, Any]],
    *,
    selected_date: str,
    root: Path | None = None,
) -> dict[str, Any]:
    """Sample and persist a bounded slice of this cycle's rejected
    candidates. Best-effort by design (same as every other ledger writer
    in this codebase) -- a failure here must never break the board build
    that called it.
    """
    if not _shadow_ledger_enabled():
        return {"ok": True, "skipped": True, "reason": "disabled"}
    if not rejected_candidates:
        return {"ok": True, "skipped": True, "reason": "no_rejected_candidates"}

    rate = _sample_rate()
    cap = _max_records_per_cycle()
    if cap <= 0:
        return {"ok": True, "skipped": True, "reason": "cap_is_zero"}

    try:
        sampled: list[dict[str, Any]] = []
        for candidate in rejected_candidates:
            if not isinstance(candidate, Mapping):
                continue
            if not _is_sampled_in(candidate, rate=rate):
                continue
            reason = str(candidate.get("_shadow_rejection_reason") or "unknown")
            sampled.append(_lean_record(candidate, reason=reason, selected_date=selected_date))
            if len(sampled) >= cap:
                break
        if not sampled:
            return {"ok": True, "skipped": True, "reason": "sample_empty", "considered": len(rejected_candidates)}

        path = shadow_ledger_path(selected_date, root=root)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for record in sampled:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))
                handle.write("\n")

        return {
            "ok": True,
            "skipped": False,
            "considered": len(rejected_candidates),
            "sampled": len(sampled),
            "sample_rate": rate,
            "cap": cap,
            "path": str(path),
        }
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def prune_old_shadow_ledger_files(*, root: Path | None = None, today: date | None = None) -> dict[str, Any]:
    """Deletes shadow-ledger day-files older than the retention window.

    A hard per-cycle cap bounds any single day's growth, but nothing else
    here bounds how many DAYS accumulate -- this is the other half of
    that bound. Best-effort: a failure to prune must never be the reason
    a board-build cycle fails.
    """
    base = root if root is not None else DEFAULT_SHADOW_LEDGER_ROOT
    if not base.exists():
        return {"ok": True, "removed": 0}
    cutoff = (today or date.today()) - timedelta(days=_retention_days())
    removed: list[str] = []
    errors: list[str] = []
    for candidate_path in base.glob("*.jsonl"):
        token = candidate_path.stem
        try:
            file_date = date.fromisoformat(token)
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                candidate_path.unlink()
                removed.append(str(candidate_path))
            except Exception as exc:
                errors.append(f"{candidate_path}: {type(exc).__name__}: {exc}")
    return {"ok": not errors, "removed": len(removed), "removed_paths": removed, "errors": errors}
