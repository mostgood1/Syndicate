"""`#359` -- a fresh artifact must survive a restart, not be stranded by one.

The live-lens publish sweep held its watermark in a local variable initialised to
`time.time()`, so every restart reset the floor to boot time and anything written
before it could never satisfy `mtime >= floor` again. Measured in production
2026-08-11, same league and same code path twenty minutes apart:

    la_liga 2026-08-16  written 21:43:56Z  published 21:44:16Z   web FRESH
    la_liga 2026-08-15  written 21:54:14Z  never published       web STALE
                                                                 (still serving 2026-07-20)

`live_refresh_loop._hot_artifact_publish_since_epoch` had already fixed exactly
this on the other publish path, for this same artifact family. This loop was
written afterwards and reintroduced it.
"""

from __future__ import annotations

import time
from unittest import mock

from syndicate.features.shared import live_lens_loop as loop

STORE = "syndicate.features.shared.refresh_state_store.read_json_file"
TWO_HOURS = 2 * 3600


def test_restart_resumes_from_the_stored_watermark():
    """THE FIX. Before this, a restart returned `loop_started_epoch` and every
    artifact written in the minutes beforehand was permanently unpublishable."""
    now = time.time()
    with mock.patch(STORE, return_value={"epoch": now - 300}):
        resumed = loop._live_lens_publish_since_epoch(loop_started_epoch=now)
    assert now - resumed == mock.ANY
    assert round(now - resumed) == 300, "a restart must reach back to the last successful sweep"


def test_cold_start_does_not_sweep_the_whole_artifact_history():
    """No watermark means nothing was ever published from here. Sweeping all
    history on a first tick is how the 2026-07-25 OOM began, so absent must mean
    'start tracking from now'."""
    now = time.time()
    with mock.patch(STORE, return_value=None):
        assert loop._live_lens_publish_since_epoch(loop_started_epoch=now) == now


def test_an_ancient_watermark_is_clamped():
    """A worker down overnight must not wake up and try to publish everything
    touched since -- the unbounded window is the failure mode the pull side's
    ceiling exists to prevent."""
    now = time.time()
    with mock.patch(STORE, return_value={"epoch": now - 86400}):
        resumed = loop._live_lens_publish_since_epoch(loop_started_epoch=now)
    assert round(now - resumed) == TWO_HOURS


def test_unreadable_is_not_treated_as_absent():
    """The two must not share a branch. Absent means 'nothing was ever
    published, start from now'; unreadable means 'something probably was and we
    cannot see how far'. Collapsing the second onto the first silently strands
    whatever the last run had not pushed -- which is the defect this whole
    function exists to fix, reintroduced through the error path.

    Caught by this test during development: the first implementation set
    `stored = None` in the `except` and fell into the absent branch, so an
    unreadable watermark resumed from *now* while the comment above it claimed
    the opposite.
    """
    now = time.time()
    with mock.patch(STORE, side_effect=OSError("keyvalue unreachable")):
        resumed = loop._live_lens_publish_since_epoch(loop_started_epoch=now)
    assert resumed != now, "an unreadable watermark was treated as 'nothing to resume'"
    assert round(now - resumed) == TWO_HOURS


def test_a_malformed_stamp_is_also_not_absent():
    now = time.time()
    for payload in ({"epoch": "not-a-number"}, {"epoch": object()}):
        with mock.patch(STORE, return_value=payload):
            resumed = loop._live_lens_publish_since_epoch(loop_started_epoch=now)
        assert round(now - resumed) == TWO_HOURS


def test_recording_the_watermark_never_raises():
    """Module-wide constraint: this runs on the loop thread. A failed write must
    cost one idempotent re-publish, never the loop."""
    with mock.patch(
        "syndicate.features.shared.refresh_state_store.write_json_file",
        side_effect=OSError("disk full"),
    ):
        loop._record_live_lens_publish_watermark(time.time())


def test_the_watermark_is_not_shared_with_the_other_publish_loop():
    """Both loops run on refresh-worker and sweep the same allowlist. A shared
    floor would let whichever swept first advance past files the other had not
    published yet -- the same permanent skip, through a side door."""
    from syndicate.features.shared import live_refresh_loop

    assert (
        loop._live_lens_publish_watermark_path().name
        != live_refresh_loop._hot_artifact_publish_watermark_path().name
    )
