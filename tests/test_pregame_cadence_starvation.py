"""A launch that produces NO run must not cost a sport its whole interval.

THE PRODUCTION FAILURE, measured 2026-09-25 on live-odds-worker.

NHL's pregame cadence is 7200s. At 19:24:30Z the loop printed
`ODDS_SWEEP_LAUNCHED sports=mlb,nhl count=2` and NO run containing nhl was
created -- every second from 19:24:15 to 19:24:44 was probed and the only runs
were `wnba/pregame` and `ncaaf/live`. The marker advanced anyway, so nhl waited
another two hours. Because mlb and ncaaf hold a refresh in flight almost
continuously during a live slate, nhl's rare slot collides nearly every time:
its collector had produced nothing since 15:44:17Z and its board carried ZERO
rows on a four-game night.

`_record_pregame_sport_sweep_epochs` is called BEFORE the launch on purpose --
"a launch that dies costs one skipped interval instead of a duplicate sweep. A
missed refresh is self-correcting on the next tick." That trade is CORRECT for
mlb, which relaunches every ~90s. It is not a skipped tick for a 2-hour sport;
it is a two-hour outage that repeats.

The rewind restores the prior epochs once the launch is KNOWN to have produced
nothing, so the sport is due again on the next tick. It cannot reintroduce `#20`
(two concurrent OddsAPI sweeps): that protection is `_record_odds_refresh_launch`,
a single GLOBAL marker written before any of this and read independently.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import syndicate.features.shared.live_refresh_loop as loop  # noqa: E402


@pytest.fixture
def marker_store(monkeypatch):
    """An in-memory stand-in for the on-disk epochs file."""
    store: dict[str, float] = {}

    monkeypatch.setattr(loop, "_read_pregame_sport_sweep_epochs", lambda: dict(store))

    def _write(path, payload):
        store.clear()
        store.update(payload)

    monkeypatch.setattr(loop, "write_json_file", _write)
    return store


def test_a_launch_that_produced_nothing_restores_the_prior_epoch(marker_store, capsys):
    """nhl's 2-hour marker must not advance on a launch that created no run."""
    marker_store.update({"mlb": 1000.0, "nhl": 1000.0})
    prior = dict(marker_store)

    # record-first: the loop stamps before it knows the outcome
    loop._record_pregame_sport_sweep_epochs(9000.0, ["mlb", "nhl"])
    assert marker_store["nhl"] == 9000.0, "precondition: the stamp lands first"

    loop._rewind_pregame_sport_sweep_epochs(prior, ["mlb", "nhl"])
    assert marker_store["nhl"] == 1000.0
    assert marker_store["mlb"] == 1000.0
    assert "PREGAME_CADENCE_MARKER_REWOUND" in capsys.readouterr().out


def test_a_sport_that_had_NEVER_swept_goes_back_to_never(marker_store):
    """Restoring an invented epoch would be worse than the bug.

    A sport with no marker reads as `no_marker` and the cadence filter fails
    OPEN for it. Writing some epoch on rewind would silently close that door.
    """
    marker_store.update({"mlb": 1000.0})
    prior = dict(marker_store)

    loop._record_pregame_sport_sweep_epochs(9000.0, ["mlb", "nhl"])
    assert marker_store["nhl"] == 9000.0

    loop._rewind_pregame_sport_sweep_epochs(prior, ["mlb", "nhl"])
    assert "nhl" not in marker_store
    assert marker_store["mlb"] == 1000.0


def test_rewind_touches_only_the_sports_in_that_launch(marker_store):
    marker_store.update({"mlb": 1000.0, "nhl": 1000.0, "wnba": 5555.0})
    prior = dict(marker_store)

    loop._record_pregame_sport_sweep_epochs(9000.0, ["nhl"])
    loop._rewind_pregame_sport_sweep_epochs(prior, ["nhl"])

    assert marker_store["nhl"] == 1000.0
    assert marker_store["wnba"] == 5555.0, "a sport not in the launch is untouched"


def test_rewind_is_silent_and_harmless_when_nothing_changed(marker_store, capsys):
    """A successful launch never calls this, but it must be safe if it does."""
    marker_store.update({"nhl": 1000.0})
    loop._rewind_pregame_sport_sweep_epochs({"nhl": 1000.0}, ["nhl"])
    assert marker_store["nhl"] == 1000.0
    assert "PREGAME_CADENCE_MARKER_REWOUND" not in capsys.readouterr().out


def test_the_duplicate_guard_is_a_DIFFERENT_marker(monkeypatch):
    """The rewind cannot reintroduce `#20`, and this pins why.

    `_record_odds_refresh_launch` writes ONE global file; the per-sport epochs
    are a separate file. If these ever became the same path, restoring a
    per-sport epoch would start rolling back the concurrency guard too.
    """
    assert loop._last_odds_refresh_launch_path() != loop._pregame_sport_sweep_epochs_path()
