"""`#632`: the fast-refresh clock is PER DATE, and sharing it made the path inert.

MEASURED ON refresh-worker 2026-09-08. In 2h26m of logs, `LAYER2_FAST_REFRESH`
appears **ZERO** times while `GAME_CHIPS_PUBLISHED` appears **18** times. The
chips web serves are written once per `build_layer2_shortlist`, so their cadence
IS the shortlist's cadence -- and for the single date web actually reads
(`central_today_iso()`), consecutive publishes were **12 to 32 minutes** apart
against the endpoint's 120 s freshness threshold.

THE CAUSE. `_layer2_fast_refresh_at` was ONE float on the instance, and the
background loop drains one payload -- one DATE -- per iteration. The heavy build
stamps that clock on success, deliberately ("a full build that just wrote a GOOD
shortlist IS a refresh"), which is right WITHIN a date and wrong ACROSS dates: a
heavy build for 2026-09-07 silenced the fast path for 2026-09-08 and vice versa.
With heavy builds alternating every 10-20 min, the shared clock was never stale
enough and the fast path fired for NEITHER date.

These tests pin the per-date behaviour directly on the two helpers, so they do
not depend on the loop, the memory guards, or a live artifact tree.
"""

from __future__ import annotations

import time

import pytest

from pipeline.intelligence_state import IntelligenceStateService


@pytest.fixture
def store():
    s = object.__new__(IntelligenceStateService)
    s._layer2_fast_refresh_at = {}
    return s


def test_a_refresh_for_one_date_does_not_stamp_another(store):
    """THE BUG, stated directly. This is what made the fast path inert."""
    now = time.time()
    store._mark_layer2_fast_refresh("2026-09-07", now)
    assert store._layer2_fast_refresh_seen("2026-09-07") == pytest.approx(now)
    assert store._layer2_fast_refresh_seen("2026-09-08") == 0.0, (
        "a heavy build for one date must not silence the fast path for another"
    )


def test_an_unseen_date_reads_as_NEVER_refreshed(store):
    # 0.0 is the permissive direction on purpose: it allows a refresh, it can
    # never skip one. An unreadable stamp must not look like a recent refresh.
    assert store._layer2_fast_refresh_seen("2026-01-01") == 0.0
    assert store._layer2_fast_refresh_seen("") == 0.0
    assert store._layer2_fast_refresh_seen(None) == 0.0


def test_a_legacy_float_stamp_does_not_raise_and_reads_as_never(store):
    # A hot reload can leave the pre-`#632` float in place. Raising here would
    # take out the board build; reading it as "never" costs one extra refresh.
    store._layer2_fast_refresh_at = 12345.0
    assert store._layer2_fast_refresh_seen("2026-09-07") == 0.0
    store._mark_layer2_fast_refresh("2026-09-07", 999.0)
    assert isinstance(store._layer2_fast_refresh_at, dict)
    assert store._layer2_fast_refresh_seen("2026-09-07") == 999.0


def test_an_empty_date_is_not_recorded(store):
    store._mark_layer2_fast_refresh("", time.time())
    store._mark_layer2_fast_refresh(None, time.time())
    assert store._layer2_fast_refresh_at == {}


def test_the_map_is_bounded_and_drops_the_OLDEST(store):
    for i in range(40):
        store._mark_layer2_fast_refresh("2026-01-%02d" % (i + 1), float(i))
    assert len(store._layer2_fast_refresh_at) <= 16
    # The most recent dates survive; the oldest are the ones dropped.
    assert store._layer2_fast_refresh_seen("2026-01-40") == 39.0
    assert store._layer2_fast_refresh_seen("2026-01-01") == 0.0


def test_the_rate_limit_still_binds_WITHIN_a_date(store):
    """The sharing was wrong across dates; the limit itself is not. Without
    this, the fix would trade an inert fast path for an unbounded one."""
    now = time.time()
    store._mark_layer2_fast_refresh("2026-09-07", now)
    seen = store._layer2_fast_refresh_seen("2026-09-07")
    assert seen and (now - seen) < 300, "a just-stamped date must still be rate-limited"
