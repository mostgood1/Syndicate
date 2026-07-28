from __future__ import annotations

import logging
import os

from flask import has_request_context


logger = logging.getLogger(__name__)


class ComputeInRequestPathError(RuntimeError):
    """Raised when heavy intelligence compute is about to run inside a live
    web request on a hosted (Render) deployment. See
    refuse_if_compute_in_request_path.
    """


def warn_if_compute_in_request_path(operation: str) -> None:
    if not has_request_context():
        return
    logger.warning("WARNING: compute in request path", extra={"operation": str(operation or "").strip() or "unknown"})


def _is_render_hosted() -> bool:
    raw_value = str(os.environ.get("RENDER") or os.environ.get("SYNDICATE_REQUIRE_HOSTED_STORAGE") or "").strip().lower()
    return raw_value in {"1", "true", "yes", "on"}


def refuse_if_compute_in_request_path(operation: str) -> None:
    """Hard-enforce this repo's load-bearing rule: the web service does no
    heavy computation, intelligence compute belongs on refresh-worker only,
    web just reads what has already been computed there.

    #56/#98/#109. Two separate incidents this session were both the same
    root cause wearing different clothes: #98's OOM (the ops.py candidate-
    trace debug endpoint calling _build_candidate_pool directly on the 2GB
    web container under load) and #109's memory spike (the query API's
    force_refresh cache-miss fallback calling _compute_response directly).
    Both were fixed individually after the fact. Rather than relying on
    every future caller remembering not to reintroduce this, this is now a
    structural gate at the actual compute entry points
    (IntelligenceStateService._compute_response/_build_candidate_pool) --
    including the admin-gated debug endpoint, which is not exempted; #98's
    incident is exactly why not.

    refresh-worker is a plain script with no Flask app, so
    has_request_context() is always False there -- this can only ever fire
    for a real HTTP request being served by a web dyno, regardless of which
    Render service happens to be running the code. Local dev (not
    render-hosted) keeps the previous warn-only behavior so a developer
    running the app directly, with no separate worker process, is
    unaffected.
    """
    if not has_request_context():
        return
    if not _is_render_hosted():
        warn_if_compute_in_request_path(operation)
        return
    logger.error("REFUSED: compute in request path on hosted web", extra={"operation": str(operation or "").strip() or "unknown"})
    raise ComputeInRequestPathError(
        f"Refusing to run {operation!r} inside a web request on a hosted deployment -- "
        "intelligence compute belongs on refresh-worker only; web reads precomputed state."
    )
