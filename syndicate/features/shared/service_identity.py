"""Which service is this, is it the hosted production fleet, which commit is it running --
read from NEUTRAL `SYNDICATE_*` markers first and the Render-era `RENDER*` names second.

WHY `[2026-11-17, lane render-config-retirement, todo #766 reopened; user: "we should not
depend on render at all", then "Steps 1+2, load later"]`. Production left Render on
2026-09-30, but about 30 code sites still decided how they behave from env vars NAMED for
Render: `RENDER=true` ("hosted"), `RENDER_SERVICE_NAME` / `_ID` / `_INSTANCE_ID` ("which
service am I"), `RENDER_GIT_COMMIT`, `RENDER_EXTERNAL_URL`, `RENDER_GIT_BRANCH`. The fleet
(`scripts/local_production.py`) fakes them on purpose, because without them web starts its
own board builder, the request-path guard switches off, and the two workers count each
other's jobs.

THE CONTRACT, which is what makes this safe to load on a live-money fleet:
- every reader asks `service_marker("SYNDICATE_X")` where it used to ask
  `os.environ.get("RENDER_X")`, and keeps its OWN predicate on the answer (truthy set,
  `.strip()`, `or` chains) exactly as it was;
- `service_marker` returns the neutral key's value when the key is PRESENT (even empty, so
  the neutral name is authoritative whenever it is set at all), else the Render-era key's
  value, else None;
- the launcher sets each neutral key to EXACTLY the value of the Render key it mirrors, in
  exactly the cases it sets that key (`local_production.derive_role_env`).
So with both set, with only the Render names set (a role started before the launcher set
the neutral ones), or with neither (a laptop, CI), every reader returns what it returned
before. `tests/test_service_marker_readers.py` checks each reader under neutral-only,
legacy-only and neither (off != on), and fails if a non-test file reads a Render marker
any other way.

Step 3 -- the launcher no longer setting the `RENDER*` names, and these fallbacks deleted
-- is a separate decision (a drained full `down`/`up`), not made here.

Names a child process must not inherit (CI steps, replay harnesses) are in
`ALL_MARKER_NAMES`: scrub both spellings, or a scrubbed `RENDER` is undone by an inherited
`SYNDICATE_HOSTED`.
"""

from __future__ import annotations

import os
from typing import Mapping

# neutral name -> the Render-era name it replaces. The launcher sets the left side to the
# right side's value; readers ask for the left side.
NEUTRAL_TO_RENDER: dict[str, str] = {
    "SYNDICATE_HOSTED": "RENDER",
    "SYNDICATE_SERVICE_NAME": "RENDER_SERVICE_NAME",
    "SYNDICATE_SERVICE_ID": "RENDER_SERVICE_ID",
    "SYNDICATE_INSTANCE_ID": "RENDER_INSTANCE_ID",
    "SYNDICATE_GIT_COMMIT": "RENDER_GIT_COMMIT",
    "SYNDICATE_EXTERNAL_URL": "RENDER_EXTERNAL_URL",
    # Never set by the fleet (Render injected it); kept so a reader has one way to ask.
    "SYNDICATE_GIT_BRANCH": "RENDER_GIT_BRANCH",
}

# Render injected these too; nothing in this repo sets them now. Listed only so scrubbers
# can keep removing them from child environments.
RENDER_ONLY_INJECTED: tuple[str, ...] = (
    "RENDER_SERVICE_TYPE",
    "RENDER_EXTERNAL_HOSTNAME",
    "RENDER_GIT_REPO_SLUG",
    "RENDER_DISCOVERY_SERVICE",
)

ALL_MARKER_NAMES: tuple[str, ...] = (
    tuple(NEUTRAL_TO_RENDER) + tuple(NEUTRAL_TO_RENDER.values()) + RENDER_ONLY_INJECTED
)


def _check(name: str) -> str:
    if name not in NEUTRAL_TO_RENDER:
        raise KeyError(f"{name!r} is not a service marker; expected one of {sorted(NEUTRAL_TO_RENDER)}")
    return NEUTRAL_TO_RENDER[name]


def service_marker(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """The neutral marker's value if it is present, else its Render-era name's, else None.

    `env` defaults to `os.environ`; pass a mapping to read another process's environ.
    """
    legacy = _check(name)
    source = os.environ if env is None else env
    if name in source:
        return source[name]
    return source.get(legacy)


def service_marker_key(name: str, env: Mapping[str, str] | None = None) -> str | None:
    """WHICH key `service_marker(name)` read: the neutral name, the Render-era name, or None.
    For log lines that report what armed a guard."""
    legacy = _check(name)
    source = os.environ if env is None else env
    if name in source:
        return name
    if legacy in source:
        return legacy
    return None


def environ_markers(blob: bytes) -> dict[str, str]:
    """The marker keys (both spellings) from a `/proc/<pid>/environ` blob. Nothing else is
    decoded: another process's environ holds venue keys."""
    wanted = set(ALL_MARKER_NAMES)
    out: dict[str, str] = {}
    for item in blob.split(b"\x00"):
        key, sep, value = item.partition(b"=")
        if not sep:
            continue
        name = key.decode("utf-8", "replace")
        if name in wanted:
            out[name] = value.decode("utf-8", "replace")
    return out


def marker_env(neutral_values: Mapping[str, str]) -> dict[str, str]:
    """Both spellings for each neutral marker given: what a launcher sets so that readers
    on either side of the rename see the same value."""
    out: dict[str, str] = {}
    for name, value in neutral_values.items():
        out[name] = value
        out[_check(name)] = value
    return out


def scrub(env: dict[str, str]) -> dict[str, str]:
    """Remove every marker, both spellings, from `env` in place (and return it)."""
    for name in ALL_MARKER_NAMES:
        env.pop(name, None)
    return env
