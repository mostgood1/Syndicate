"""Which service is this, is it the hosted production fleet, which commit is it running --
read from the fleet's NEUTRAL `SYNDICATE_*` service markers.

HISTORY `[2026-11-17, lane render-config-retirement, todo #766; user: "we should not depend
on render at all", "go ahead with step 3", "drop the RENDER names too"]`. Production left
Render on 2026-09-30, but about 30 code sites still decided how they behave from env vars
NAMED for Render (`RENDER=true`, `RENDER_SERVICE_NAME`, ...), and the fleet faked them on
purpose. In three steps:
- step 2: every reader asked `service_marker("SYNDICATE_X")`, which preferred the neutral
  name and fell back on the Render one; the launcher set both, to one value.
- step 3a: the launcher set only the neutral names. A drained `up` at `91d865fd5`
  (2026-11-17 21:53Z) loaded it, and every role then carried only the neutral markers: the
  compare showed `RENDER*` removed, `SYNDICATE_*` added with equal values, nothing else.
- step 3b (this file): the Render-name fallback is gone. A `RENDER*` variable now means
  nothing to any reader; `tests/test_service_marker_readers.py` fails if code reads one.

WHAT EACH MARKER GATES, and what its absence does, is in
`.syndicate/findings_2026-11-17_render_config_retirement.md`. Absent is NOT off:
- without `SYNDICATE_HOSTED` / `SYNDICATE_SERVICE_ID`, web starts its own board builder;
- without `SYNDICATE_HOSTED`, the request-path guard goes warn-only;
- without `SYNDICATE_SERVICE_NAME`, the two workers count each other's jobs.

`scripts/local_production.py` sets them for every role (it cannot import this module
without installing `syndicate`'s global urllib opener into the supervisor, so it spells the
same names out, pinned by the test). A child that must not look hosted scrubs
`SERVICE_MARKERS`.
"""

from __future__ import annotations

import os
from typing import Mapping

SERVICE_MARKERS: tuple[str, ...] = (
    "SYNDICATE_HOSTED",
    "SYNDICATE_SERVICE_NAME",
    "SYNDICATE_SERVICE_ID",
    "SYNDICATE_INSTANCE_ID",
    "SYNDICATE_GIT_COMMIT",
    "SYNDICATE_EXTERNAL_URL",
    # Set by nothing on the fleet; kept so a reader has one way to ask.
    "SYNDICATE_GIT_BRANCH",
)

# Scrubbers remove every marker; the names are the same set.
ALL_MARKER_NAMES: tuple[str, ...] = SERVICE_MARKERS


def _check(name: str) -> None:
    if name not in SERVICE_MARKERS:
        raise KeyError(f"{name!r} is not a service marker; expected one of {list(SERVICE_MARKERS)}")


def service_marker(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """The marker's value, or None when absent. `env` defaults to `os.environ`; pass a
    mapping to read another process's environ."""
    _check(name)
    return (os.environ if env is None else env).get(name)


def service_marker_key(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """The key `service_marker(name)` read, or None when absent. For log lines that report
    what armed a guard."""
    _check(name)
    return name if name in (os.environ if env is None else env) else None


def environ_markers(blob: bytes) -> dict[str, str]:
    """The marker keys from a `/proc/<pid>/environ` blob. Nothing else is decoded: another
    process's environ holds venue keys."""
    wanted = set(SERVICE_MARKERS)
    out: dict[str, str] = {}
    for item in blob.split(b"\x00"):
        key, sep, value = item.partition(b"=")
        if not sep:
            continue
        name = key.decode("utf-8", "replace")
        if name in wanted:
            out[name] = value.decode("utf-8", "replace")
    return out


def scrub(env: dict[str, str]) -> dict[str, str]:
    """Remove every service marker from `env` in place (and return it)."""
    for name in SERVICE_MARKERS:
        env.pop(name, None)
    return env
