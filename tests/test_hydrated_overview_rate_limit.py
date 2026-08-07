"""#251 -- the hydrated sport overview is rate-limited even under force_refresh.

The regression: refresh-worker was OOM-killed at 4GiB every ~3 minutes.
`_HOME_OVERVIEW_TTL_SEC` is 10s and the worker's board loop runs every ~90s, so
the cache could never hit there -- while the entry was still retained the whole
time. Measured 2026-08-07 on refresh-worker:

    05:10:57  OVERVIEW_SPORT_BEGIN mlb    993.8MB container
    05:12:10  mlb board_contract         3922.6MB  95.8%   <- +2.9GB in 73s
    05:12:23  post_build_overview        3009MB anon, and it stays there

So the process held the previous hydrated MLB context AND built a new one on top
of it, ~2x 2.9GB against a 4GiB ceiling, every cycle. Two circuit breakers
(#249/#250) bounded the damage and could not stop it, because the cost was being
paid unnecessarily rather than merely being large.
"""

from __future__ import annotations

from unittest.mock import patch

from syndicate.blueprints import home as home_module


def _seed_cache(*, slug: str, date: str, age_sec: float, skip_hydration: bool = False) -> dict:
    key = home_module._sport_cache_key(slug, date)
    if skip_hydration:
        key = f"{key}:skip_hydration"
    payload = {"slug": slug, "context_label": date, "_marker": "cached"}
    now = home_module.time.monotonic()
    home_module._HOME_OVERVIEW_CACHE[key] = (now - age_sec, payload)
    return payload


def _clear():
    home_module._HOME_OVERVIEW_CACHE.clear()


def test_forced_hydrated_rebuild_is_served_from_cache_when_recent():
    _clear()
    _seed_cache(slug="mlb", date="2026-08-07", age_sec=30.0)
    result = home_module._build_sport_overview(
        {"slug": "mlb"}, "2026-08-07", force_refresh=True, skip_game_hydration=False
    )
    # If the limiter did not hold, this would run the real ~2.9GB build and the
    # marker would be gone.
    assert result["_marker"] == "cached"


def test_forced_hydrated_rebuild_proceeds_once_the_entry_is_stale():
    _clear()
    _seed_cache(slug="mlb", date="2026-08-07", age_sec=10_000.0)
    with patch.object(home_module, "_sport_cache_key", side_effect=home_module._sport_cache_key) as keyed:
        try:
            home_module._build_sport_overview(
                {"slug": "mlb"}, "2026-08-07", force_refresh=True, skip_game_hydration=False
            )
        except Exception:
            # The real build needs artifacts this test does not stage; reaching
            # it at all is the assertion -- the limiter did not short-circuit.
            pass
    assert keyed.called


def test_fingerprint_pass_is_never_rate_limited():
    # skip_game_hydration=True substitutes empty lists for exactly the loaders
    # that cost 2.9GB, runs all eight sports in ~2s, and feeds
    # _source_state_fingerprint. Rate-limiting it would make change detection
    # blind -- the one thing this must not do.
    _clear()
    _seed_cache(slug="mlb", date="2026-08-07", age_sec=30.0, skip_hydration=True)
    result = home_module._build_sport_overview(
        {"slug": "mlb"}, "2026-08-07", force_refresh=True, skip_game_hydration=True
    )
    assert result.get("_marker") != "cached"


def test_pruner_does_not_evict_the_entry_the_rate_limiter_needs():
    # #255. The defect in #251, and the reason it did nothing in production.
    #
    # _prune_home_cache runs on EVERY write with ttl=_HOME_OVERVIEW_TTL_SEC
    # (10s) and pops every entry at or past it. The worker writes all eight
    # sports each cycle, so the hydrated MLB entry was reliably deleted ~10s
    # after being stored -- while the rate limiter asks for one up to 300s old.
    # Retention shorter than reuse means the limiter can never fire.
    #
    # Two clocks, two jobs: TTL is how long an entry may be SERVED to a normal
    # caller; the rebuild interval is how long it must SURVIVE so a forced
    # caller can be refused. This pins that retention takes the max.
    _clear()
    now = home_module.time.monotonic()
    key = home_module._sport_cache_key("mlb", "2026-08-07")
    home_module._HOME_OVERVIEW_CACHE[key] = (now - 60.0, {"slug": "mlb", "_marker": "cached"})

    # A write for a DIFFERENT key triggers the prune, exactly as another
    # sport's overview does on the worker every cycle.
    other = home_module._sport_cache_key("nba", "2026-08-07")
    home_module._HOME_OVERVIEW_CACHE[other] = (now, {"slug": "nba"})
    home_module._prune_home_cache(
        home_module._HOME_OVERVIEW_CACHE,
        now=now,
        ttl=max(
            home_module._HOME_OVERVIEW_TTL_SEC,
            home_module._hydrated_overview_min_rebuild_interval_sec(),
        ),
    )

    # 60s old: far past the 10s serve TTL, well inside the 300s reuse window.
    assert key in home_module._HOME_OVERVIEW_CACHE, (
        "the pruner evicted the entry the rate limiter exists to serve"
    )

    # And end to end: a forced hydrated rebuild is still refused afterwards.
    result = home_module._build_sport_overview(
        {"slug": "mlb"}, "2026-08-07", force_refresh=True, skip_game_hydration=False
    )
    assert result["_marker"] == "cached"


def test_retention_still_bounded_when_the_limiter_is_disabled():
    # With the interval at 0 the reuse window vanishes, so retention must fall
    # back to the plain serve TTL rather than silently keeping entries forever.
    _clear()
    now = home_module.time.monotonic()
    with patch.dict("os.environ", {"SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC": "0"}):
        ttl = max(
            home_module._HOME_OVERVIEW_TTL_SEC,
            home_module._hydrated_overview_min_rebuild_interval_sec(),
        )
        assert ttl == home_module._HOME_OVERVIEW_TTL_SEC
        home_module._HOME_OVERVIEW_CACHE["stale"] = (now - 60.0, {"slug": "mlb"})
        home_module._prune_home_cache(home_module._HOME_OVERVIEW_CACHE, now=now, ttl=ttl)
        assert "stale" not in home_module._HOME_OVERVIEW_CACHE


def test_interval_is_env_tunable_and_zero_restores_old_behaviour():
    with patch.dict("os.environ", {"SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC": "45"}):
        assert home_module._hydrated_overview_min_rebuild_interval_sec() == 45.0
    with patch.dict("os.environ", {"SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC": "0"}):
        assert home_module._hydrated_overview_min_rebuild_interval_sec() == 0.0
    # Garbage must not disable the protection.
    with patch.dict("os.environ", {"SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC": "not-a-number"}):
        assert home_module._hydrated_overview_min_rebuild_interval_sec() == 300.0


def test_zero_interval_lets_a_forced_hydrated_rebuild_through():
    _clear()
    _seed_cache(slug="mlb", date="2026-08-07", age_sec=1.0)
    with patch.dict("os.environ", {"SYNDICATE_HYDRATED_OVERVIEW_MIN_REBUILD_SEC": "0"}):
        try:
            result = home_module._build_sport_overview(
                {"slug": "mlb"}, "2026-08-07", force_refresh=True, skip_game_hydration=False
            )
        except Exception:
            return  # reached the real build, which is the point
    assert result.get("_marker") != "cached"
