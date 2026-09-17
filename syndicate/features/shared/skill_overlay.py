"""The auto-updated bucket-skill overlay the Layer 2 scorer reads.

Lane `model-scorecard-cron`. USER DECISION `[2026-09-17, in chat]`: "Auto-update measured
skill" -- the daily scorecard's VALIDATED buckets move Layer 2 scores without a code
review, replacing the hand-run `bucket_search.py --write-table`. Built with guardrails,
because scoring decides what `portfolio_commit` stakes, including live exchange orders:

- VALIDATED ONLY, UNDER THE UNCHANGED BAR. The cron writes only buckets that pass
  `bucket_search`'s own MIN_GAMES / MIN_DATES / FDR / leave-one-date-out rules, and this
  reader re-checks the floors, the verdicts and the loss scale before trusting a file.
- BOUNDED BY THE TABLE'S EXISTING MATH. `measured_bucket_skill.bucket_factor` is unchanged:
  a pocket can only CANCEL a category demotion (never raise past 1.0) and a loss is floored
  at `SKILL_FLOOR`. At most `MAX_BUCKETS` entries are accepted.
- EXPIRES. A payload past `expires_at` (72 h, 3x the daily cron -- never equal to the
  producer's interval, the 2026-09-08 FORBIDDEN rule) is ignored and the shipped static
  table stands, so a dead cron degrades to the old behaviour instead of freezing scores.
- KILL SWITCH. `SYNDICATE_SKILL_OVERLAY=off` returns the static table immediately.
- NEVER RAISES, NEVER BLOCKS. A bad file is logged and ignored; a missing file on a worker
  is fetched from web on a background thread, and the build that noticed uses what it has.

Where the file comes from: the cron publishes `OVERLAY_PATH` to WEB's disk. Web reads it
there. Workers (refresh-worker builds Layer 2 and scores the orders) cannot share web's
disk, so they pull it through `/api/ops/artifacts/export` when their copy is missing or
expired. The name carries no date on purpose: the workers' date-scoped
`pull_hot_artifacts(*<date>*)` must not drag it along on every cycle.
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OVERLAY_PATH = "reports/model_scorecard/measured_bucket_skill_overlay.json"
ENV_SWITCH = "SYNDICATE_SKILL_OVERLAY"
MAX_BUCKETS = 100
MIN_GAMES_FLOOR = 60
MIN_DATES_FLOOR = 5
CHECK_INTERVAL_SECONDS = 600.0
PULL_INTERVAL_SECONDS = 1800.0
SOURCE_PREFIX = "model_scorecard/"

_OFF_VALUES = frozenset({"off", "0", "false", "no"})
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "checked_at": 0.0,
    "mtime": None,
    "table": None,
    "meta": {"source": "static", "reason": "not_checked"},
    "last_pull_at": 0.0,
    "pull_running": False,
    "logged": None,
}


def overlay_enabled() -> bool:
    return str(os.environ.get(ENV_SWITCH) or "").strip().lower() not in _OFF_VALUES


def _overlay_file() -> Path | None:
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        return Path(data_root()) / OVERLAY_PATH
    except Exception:
        return None


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate(payload: Any, *, now: datetime | None = None) -> tuple[dict[str, dict[str, Any]] | None, str]:
    """(table, "ok") or (None, reason). The same verdict filter as `load_table`, plus the guardrails."""
    from syndicate.features.shared.measured_bucket_skill import VERDICT_SKILL_LOSS, VERDICT_SKILL_POCKET

    now = now or datetime.now(timezone.utc)
    if not isinstance(payload, Mapping):
        return None, "not_an_object"
    if not str(payload.get("source") or "").startswith(SOURCE_PREFIX):
        return None, "unknown_source"
    expires = _parse_time(payload.get("expires_at"))
    if expires is None:
        return None, "no_expiry"
    if expires <= now:
        return None, "expired"
    buckets = payload.get("buckets")
    if not isinstance(buckets, Mapping):
        return None, "no_buckets"
    if len(buckets) > MAX_BUCKETS:
        return None, "too_many_buckets"
    table: dict[str, dict[str, Any]] = {}
    for bucket_id, entry in buckets.items():
        if not isinstance(entry, Mapping) or str(bucket_id).count("|") != 4:
            return None, "malformed_bucket"
        verdict = entry.get("verdict")
        if verdict not in (VERDICT_SKILL_POCKET, VERDICT_SKILL_LOSS):
            return None, "unvalidated_verdict"
        try:
            games, dates = int(entry.get("games")), int(entry.get("dates"))
        except (TypeError, ValueError):
            return None, "malformed_sample"
        if games < MIN_GAMES_FLOOR or dates < MIN_DATES_FLOOR:
            return None, "below_sample_floor"
        if verdict == VERDICT_SKILL_LOSS:
            loss = entry.get("established_loss_rel")
            if isinstance(loss, bool) or not isinstance(loss, (int, float)) or loss < 0:
                return None, "malformed_loss_scale"
        table[str(bucket_id)] = dict(entry)
    return table, "ok"


def _log(meta: Mapping[str, Any]) -> None:
    signature = (meta.get("source"), meta.get("reason"), meta.get("buckets"), meta.get("generated_at"))
    if _STATE["logged"] == signature:
        return
    _STATE["logged"] = signature
    print("[skill_overlay] SOURCE=%s reason=%s buckets=%s generated_at=%s expires_at=%s"
          % (meta.get("source"), meta.get("reason"), meta.get("buckets"), meta.get("generated_at"),
             meta.get("expires_at")), flush=True)


def _pull_in_background() -> None:
    """Fetch web's copy onto this disk. Never blocks the caller; at most once per PULL_INTERVAL."""
    now = time.monotonic()
    if _STATE["pull_running"] or now - float(_STATE["last_pull_at"] or 0.0) < PULL_INTERVAL_SECONDS:
        return
    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if not token:
        return
    try:
        from syndicate.features.shared import artifact_publisher as ap

        url = ap._export_url(exact_path=OVERLAY_PATH)  # noqa: SLF001
    except Exception:
        return
    if not url:
        return
    _STATE["pull_running"] = True
    _STATE["last_pull_at"] = now

    def _run() -> None:
        try:
            ok, written = ap._pull_hot_artifacts_request(url, token, timeout_seconds=120)  # noqa: SLF001
            print(f"[skill_overlay] PULL ok={ok} files={written}", flush=True)
        except Exception as exc:
            print(f"[skill_overlay] PULL_FAILED {type(exc).__name__}: {exc}", flush=True)
        finally:
            _STATE["pull_running"] = False
            _STATE["checked_at"] = 0.0

    threading.Thread(target=_run, name="skill-overlay-pull", daemon=True).start()


def active_table(static: Mapping[str, Mapping[str, Any]], *, now: datetime | None = None,
                 path: Path | None = None, pull: bool = True) -> Mapping[str, Mapping[str, Any]]:
    """The overlay's validated buckets when enabled, present and unexpired; else `static`."""
    try:
        if not overlay_enabled():
            meta = {"source": "static", "reason": "switch_off", "buckets": len(static)}
            _STATE["meta"] = meta
            _log(meta)
            return static
        clock = time.monotonic()
        with _LOCK:
            fresh = clock - float(_STATE["checked_at"] or 0.0) < CHECK_INTERVAL_SECONDS
            if fresh and path is None and now is None:
                table = _STATE["table"]
                return table if table is not None else static
            _STATE["checked_at"] = clock
            target = path or _overlay_file()
            if target is None or not target.is_file():
                _STATE["table"], _STATE["mtime"] = None, None
                meta = {"source": "static", "reason": "overlay_absent", "buckets": len(static)}
                if pull:
                    _pull_in_background()
            else:
                mtime = target.stat().st_mtime
                payload = json.loads(target.read_text(encoding="utf-8"))
                table, reason = validate(payload, now=now)
                _STATE["mtime"] = mtime
                _STATE["table"] = table
                meta = {"source": "overlay" if table is not None else "static", "reason": reason,
                        "buckets": len(table) if table is not None else len(static),
                        "generated_at": payload.get("generated_at") if isinstance(payload, Mapping) else None,
                        "expires_at": payload.get("expires_at") if isinstance(payload, Mapping) else None}
                if table is None and reason == "expired" and pull:
                    _pull_in_background()
            _STATE["meta"] = meta
            _log(meta)
            return _STATE["table"] if _STATE["table"] is not None else static
    except Exception as exc:
        meta = {"source": "static", "reason": f"error:{type(exc).__name__}", "buckets": len(static)}
        _STATE["meta"] = meta
        _STATE["table"] = None
        _log(meta)
        return static


def status() -> dict[str, Any]:
    return dict(_STATE["meta"])


def reset_cache() -> None:
    """Tests only."""
    _STATE.update({"checked_at": 0.0, "mtime": None, "table": None, "last_pull_at": 0.0,
                   "pull_running": False, "logged": None, "meta": {"source": "static", "reason": "not_checked"}})
