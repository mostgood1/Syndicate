"""Redirects for artifacts a ROUTE publishes as a side effect.

**Why this is a module and not just a conftest fixture.** Same reason
`tests/_cache_isolation.py` is one: **CI does not run pytest.**
`.github/workflows/ci.yml` runs `python -m unittest tests.test_archives`, and
`unittest` never imports `conftest.py`. A redirect that lives only in a fixture
is absent from the one runner that gates merges, so the isolation has to be
importable by both and is defined here exactly once.

**What the problem is.** Several tests assert on a page or an API payload and
reach a builder that PUBLISHES as its last act. `build_cards_page_context`
(WNBA) ends in `publish_cards_page_context`, which resolves its path from
`data_root()` and writes `data/live/wnba_cards_context[_live]_<date>.json`. On
Render that family lives in the keyvalue store; in a checkout it falls through
to the filesystem, so a test run creates `data/live/` in the git-tracked mirror
and leaves published board context sitting in it.

Nothing under `data/live/` is tracked, and that makes it worse rather than
better: untracked and NOT ignored is precisely the state a `git add` sweep
collects, and a later local run reads the file back as if the mirror had
produced it -- the confusion `CLAUDE.md` documents at length. Two separate test
files reached this seam (`test_archives.py` via its routes,
`test_intelligence.py` via `build_intelligence_overview` ->
`_wnba_has_live_games`), which is what makes a shared redirect the right shape:
the next caller inherits it instead of rediscovering it.

The PATH is patched rather than `SYNDICATE_DATA_ROOT` set, because those test
files READ the mirror in hundreds of tests and redirecting the root takes the
data out from under all of them.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterator
from unittest.mock import patch


def _scratch_wnba_cards_context_path(scratch: Path):
    """Same shape as the real path builder, including its two-key rule.

    Both keys are preserved -- `_live` for a context built with tonight's scores
    merged and the plain one for a context built without -- because a redirect
    that collapsed them would make the live-lens variant and the board variant
    overwrite each other, which is a behaviour change dressed as isolation.
    """

    def _path(selected_date: Any, *, live_status_merged: bool = False) -> Path:
        suffix = "_live" if live_status_merged else ""
        return scratch / "live" / f"wnba_cards_context{suffix}_{str(selected_date).strip()}.json"

    return _path


@contextlib.contextmanager
def isolated_wnba_cards_context(scratch: Path | None = None) -> Iterator[Path]:
    """Point `publish_cards_page_context` at scratch space for the duration.

    `scratch` is supplied by the pytest fixture (which already has a per-test
    tmp dir); the unittest entrypoints pass nothing and get a
    `TemporaryDirectory` that is cleaned up on exit.
    """
    from syndicate.features.wnba import cards

    with contextlib.ExitStack() as stack:
        if scratch is None:
            scratch = Path(stack.enter_context(TemporaryDirectory(prefix="wnba_cards_context_")))
        stack.enter_context(
            patch.object(cards, "wnba_cards_context_artifact_path", _scratch_wnba_cards_context_path(scratch))
        )
        yield scratch


@contextlib.contextmanager
def no_vendored_basketball_schedule_fetch() -> Iterator[None]:
    """Stop a test from SUBPROCESSING out to the vendored `fetch-schedule` CLI.

    THE WRITE THE IN-PROCESS GUARD CANNOT SEE, and the reason it is worth naming
    rather than only fixing. `schedule_adapter._fetch_basketball_schedule` reads
    the season schedule for a date and, finding no row for it, calls
    `_fetch_basketball_schedule_via_cli`, which runs
    `python -m wnba_betting.cli fetch-schedule` as a CHILD PROCESS. That child
    fetches the live NBA/WNBA schedule over the network and writes
    `vendor/<repo>/data/processed/schedule_<season>.{json,csv}` -- the file
    `wnba_fixture_identity` calls the git-tracked MASTER. Measured 2026-09-09:
    all 114 rows of `schedule_2026.csv` plus its `.json` rewritten by a test
    run, under both runners.

    `conftest.py`'s write guard wraps `open`/`Path.open`/mkdir in THIS process,
    so a child process is invisible to it by construction. That is the guard's
    one structural blind spot, and this is the block that covers it -- at the
    seam, not by forbidding `subprocess` outright, so the adapter's own
    read/cache logic still runs under test and only the fetch is removed.

    Note this is a NETWORK call in a unit test as well as a tracked-file write:
    it fires whenever the requested date has no row in the season file, which in
    the off-season is every date. Returning False is the adapter's real
    "vendor CLI unavailable" path, which leaves the caller with the rows it
    already read -- exactly the behaviour on a machine with no vendor tree.
    """
    from syndicate.features.shared import schedule_adapter

    with patch.object(schedule_adapter, "_fetch_basketball_schedule_via_cli", return_value=False):
        yield
