"""The coverage/readiness report as a PUBLISHED ARTIFACT, not a request-path build.

WHY THIS EXISTS, and it is a specific measured constraint rather than a
preference.

`/intelligence/status` used to render `intelligence_status.html` directly from
`build_intelligence_status()`. On 2026-06-10 (`5aeb8075`) that render was
replaced by a 302 to the JSON board-state API, which serves a DIFFERENT payload
-- so the board's "Data coverage" link has been dropping people into an
unrendered JSON blob that does not answer the question the link asks, and the
template has been an orphan with no caller at all.

The obvious fix -- revert the redirect -- is unsafe. `build_intelligence_status()`
is recorded at `pipeline/intelligence_state.py` as "confirmed live to
single-handedly exceed the refresh-worker's 2GB memory limit" (2026-07-24), and
that was WITH `skip_game_hydration=True`. Web is also 2GB and its two gunicorn
workers already sit around 500MB each. Calling it in a request handler is
exactly what the worker-split rule in CLAUDE.md forbids, with a measured OOM
behind it.

So this module is the seam the rule asks for: the WORKER publishes, the WEB
reads.

  * `project_coverage_report()` trims the full status blob to precisely the
    fields `intelligence_status.html` renders -- enumerated from the template,
    not guessed. Everything else (`refresh_status`, `daily_update`, the
    simulation contract, per-sport overview internals) is dropped, which is
    both the size control and the reason a keyvalue write is safe here: the
    store rejects at 8MB and closes the connection near 9MB.
  * `publish_coverage_report()` is called from the intelligence-state loop at
    the point it ALREADY has a status in hand, so it adds no computation --
    only a projection and a write.
  * `read_coverage_report()` is what the request handler calls. It never
    builds anything. A missing, stale or wrong-date artifact returns None and
    the page renders a degraded state, which is what CLAUDE.md prescribes:
    "If data is missing at request time, the correct behavior is a
    degraded/empty UI state, not an on-request backfill."

NOT to be confused with `STATUS_CACHE_PATH`
(`reports/intelligence/status_response_cache.json`), which is a different,
FULL-status cache that has zero writers repo-wide and is therefore always a
miss. That one is a separate dead stub; see `.syndicate/leads.md`.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from syndicate.features.shared.refresh_state_store import KeyValuePayloadTooLarge
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root
from syndicate.features.shared.refresh_state_store import write_json_file

COVERAGE_ARTIFACT_NAME = "coverage_report.json"

# The template renders at most 6 of each missing-input list, so publishing more
# is bytes nobody reads. Capped HERE rather than only in the template so the
# artifact's size is bounded by the contract, not by the consumer's politeness.
_MISSING_INPUT_LIMIT = 6

# How old a published report may be before the page treats it as absent.
# Deliberately generous: the intelligence-state loop's own cadence is the real
# producer clock, and a page that blanks itself between ticks is worse than one
# showing a report from earlier in the day WITH its age on screen.
DEFAULT_MAX_AGE_SECONDS = 6 * 60 * 60


def coverage_artifact_path() -> Path:
    """Resolved at call time, not import time.

    `reports_root()` reads `SYNDICATE_REPORTS_ROOT`, which the test suite's
    autouse fixture redirects per test. A module-level constant would bind the
    real reports root at import and write there from every test that touches
    this -- the exact shape of the `data/` mirror writes another lane spent a
    sweep closing.
    """
    return reports_root() / "intelligence" / COVERAGE_ARTIFACT_NAME


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else "").strip()
    return text or default


def _labels(rows: Any, limit: int) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            label = _text(row.get("label"))
        else:
            label = _text(row)
        if label:
            out.append({"label": label})
        if len(out) >= limit:
            break
    return out


def _artifact_rows(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        out.append(
            {
                "label": _text(row.get("label")),
                "path": _text(row.get("path")),
                "exists": bool(row.get("exists")),
                "tracked": bool(row.get("tracked")),
            }
        )
    return out


def _advanced_rows(rows: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        metrics = [
            _text(metric)
            for metric in (row.get("metrics") if isinstance(row.get("metrics"), list) else [])
            if _text(metric)
        ]
        out.append(
            {
                "label": _text(row.get("label")),
                "path": _text(row.get("path")),
                "metrics": metrics,
                "exists": bool(row.get("exists")),
                "tracked": bool(row.get("tracked")),
            }
        )
    return out


def project_coverage_report(status: dict[str, Any] | None, selected_date: str) -> dict[str, Any]:
    """The published shape: exactly what `intelligence_status.html` reads.

    Field-for-field from the template, so a field added to the page without
    being added here renders empty rather than raising -- and a field dropped
    from the page keeps being published until someone removes it here. That
    asymmetry is deliberate: a blank chip is a much cheaper failure than a
    500 on the page people open when they suspect something is broken.
    """
    status = status if isinstance(status, dict) else {}
    gate = status.get("readiness_gate") if isinstance(status.get("readiness_gate"), dict) else {}
    tracked_summary = status.get("tracked_summary") if isinstance(status.get("tracked_summary"), dict) else {}
    advanced_summary = status.get("advanced_summary") if isinstance(status.get("advanced_summary"), dict) else {}

    sports: list[dict[str, Any]] = []
    for sport in status.get("sports") if isinstance(status.get("sports"), list) else []:
        if not isinstance(sport, dict):
            continue
        sport_gate = sport.get("advanced_gate") if isinstance(sport.get("advanced_gate"), dict) else {}
        sports.append(
            {
                "context_label": _text(sport.get("context_label")),
                "name": _text(sport.get("name"), _text(sport.get("slug")).upper()),
                "data_health": _text(sport.get("data_health"), "unknown"),
                "data_warnings": [
                    _text(warning)
                    for warning in (sport.get("data_warnings") if isinstance(sport.get("data_warnings"), list) else [])
                    if _text(warning)
                ],
                "tracked_ready": bool(sport.get("tracked_ready")),
                "advanced_ready": bool(sport.get("advanced_ready")),
                "active_today": bool(sport.get("active_today")),
                "advanced_gate": {
                    "ready": bool(sport_gate.get("ready")),
                    "missing_inputs": _labels(sport_gate.get("missing_inputs"), _MISSING_INPUT_LIMIT),
                    "publish_missing_inputs": _labels(
                        sport_gate.get("publish_missing_inputs"), _MISSING_INPUT_LIMIT
                    ),
                },
                "advanced_inputs": _advanced_rows(sport.get("advanced_inputs")),
                "artifacts": _artifact_rows(sport.get("artifacts")),
            }
        )

    def _count(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    return {
        "selected_date": _text(selected_date) or _text(status.get("selected_date")),
        "generated_at": time.time(),
        "tracked_summary": {
            "tracked_ok": _count(tracked_summary.get("tracked_ok")),
            "tracked_total": _count(tracked_summary.get("tracked_total")),
        },
        "advanced_summary": {
            "tracked_ok": _count(advanced_summary.get("tracked_ok")),
            "tracked_total": _count(advanced_summary.get("tracked_total")),
        },
        "readiness_gate": {
            "ready": bool(gate.get("ready")),
            # Only lengths are rendered, but slugs cost almost nothing and make
            # the artifact answerable by hand when someone asks "which sports".
            "ready_sports": [_text(row.get("slug") if isinstance(row, dict) else row) for row in
                             (gate.get("ready_sports") if isinstance(gate.get("ready_sports"), list) else [])],
            "blocked_sports": [_text(row.get("slug") if isinstance(row, dict) else row) for row in
                               (gate.get("blocked_sports") if isinstance(gate.get("blocked_sports"), list) else [])],
        },
        "sports": sports,
    }


def empty_coverage_report(selected_date: str) -> dict[str, Any]:
    """The degraded shape. Same keys, all zero -- so the page renders its own
    chrome and says nothing has been published yet, instead of 500ing or, worse,
    showing zeros that look like a measured result."""
    return {
        "selected_date": _text(selected_date),
        "generated_at": None,
        "tracked_summary": {"tracked_ok": 0, "tracked_total": 0},
        "advanced_summary": {"tracked_ok": 0, "tracked_total": 0},
        "readiness_gate": {"ready": False, "ready_sports": [], "blocked_sports": []},
        "sports": [],
    }


def publish_coverage_report(status: dict[str, Any] | None, selected_date: str) -> bool:
    """Worker side. Never raises into the caller's loop.

    A coverage page is a convenience; the intelligence-state loop it hangs off
    is not. An oversized payload or a keyvalue hiccup must not take down the
    thing that produces the boards.
    """
    report = project_coverage_report(status, selected_date)
    try:
        write_json_file(coverage_artifact_path(), report)
    except KeyValuePayloadTooLarge as exc:
        print(f"[coverage_report] PUBLISH_REJECTED_TOO_LARGE date={selected_date} {exc}", flush=True)
        return False
    except Exception as exc:
        print(
            f"[coverage_report] PUBLISH_FAILED date={selected_date} "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return False
    print(
        f"[coverage_report] PUBLISHED date={selected_date} sports={len(report['sports'])} "
        f"tracked={report['tracked_summary']['tracked_ok']}/{report['tracked_summary']['tracked_total']}",
        flush=True,
    )
    return True


def read_coverage_report(
    selected_date: str, *, max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
) -> dict[str, Any] | None:
    """Web side. Reads only -- it must never build.

    Returns None for absent, unreadable, wrong-date or stale. The caller
    renders `empty_coverage_report()` in that case rather than computing a
    fresh one, which is the whole point of the split.
    """
    try:
        payload = read_json_file(coverage_artifact_path())
    except Exception as exc:
        print(f"[coverage_report] READ_FAILED {type(exc).__name__}: {exc}", flush=True)
        return None
    if not isinstance(payload, dict):
        return None
    if _text(payload.get("selected_date")) != _text(selected_date):
        return None
    try:
        generated_at = float(payload.get("generated_at") or 0.0)
    except (TypeError, ValueError):
        return None
    if generated_at <= 0.0:
        return None
    if max_age_seconds > 0 and (time.time() - generated_at) > float(max_age_seconds):
        return None
    return payload
