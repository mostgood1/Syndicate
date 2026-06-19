from __future__ import annotations

import logging

from flask import has_request_context


logger = logging.getLogger(__name__)


def warn_if_compute_in_request_path(operation: str) -> None:
    if not has_request_context():
        return
    logger.warning("WARNING: compute in request path", extra={"operation": str(operation or "").strip() or "unknown"})