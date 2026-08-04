"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Recursively replaces non-finite floats (NaN/Infinity/-Infinity) with
  None so a response tree is safe to serialize as strict JSON.

Constraints:
- Pure, stateless, no I/O -- safe to call from any response path.
"""

from __future__ import annotations

import math


def json_safe_value(value: object) -> object:
    """Recursively replace NaN/Infinity/-Infinity with None.

    Found live 2026-07-31 (syndicate/blueprints/intelligence.py's board
    response): a pandas-derived line/odds value reached a response as a
    real Python float('nan'). Python's json.dumps happily serializes that
    as the bareword `NaN` -- valid to Python's own lenient json.loads, but
    not valid JSON per spec, so a browser's strict JSON.parse throws a
    SyntaxError on the ENTIRE payload the instant it hits that one token,
    anywhere in the tree, with the fetch itself reporting success (200)
    and no console/network error to point at the real cause.

    Recurred live 2026-08-04 in a second, unrelated response path
    (syndicate/blueprints/ask_the_syndicate.py's /api/syndicate/query --
    the Ask-the-Syndicate board embed) that had never been wired through
    the original fix, which only covered syndicate/blueprints/intelligence.py's
    own response paths. Moved here (out of blueprints/intelligence.py) and
    wired into the Flask app's own JSON provider (syndicate/app.py) so
    every jsonify() call across every current and future blueprint is
    covered automatically -- not a call-site-by-call-site defensive net
    that a new blueprint can silently fall outside of again.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe_value(item) for item in value]
    return value
