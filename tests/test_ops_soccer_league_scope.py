"""`#433` — ops-triggered soccer refreshes must be able to name a league.

`launch_refresh_run` has accepted `soccer_leagues` since `#282` and
`refresh_odds_sources.py` has implemented `--soccer-leagues`, but
`_start_refresh_job` never passed it — so every soccer refresh reachable
through `/api/ops/odds-refresh/run` was all-leagues, all 50 steps.

That gap had teeth on 2026-08-14: three leagues' odds were 3.6 days stale with
kickoffs two hours away, and the only remedy reachable through the API was the
same full ten-league run that had been dying at step 27 and leaving those
leagues dark. Scoping to one league turns a 50-step job into ~6.

The assertion is on the KWARG REACHING `launch_refresh_run`, not on the
resulting command string: the command is built one layer down and already has
its own coverage (`SOCCER_LEAGUE_SCOPE`). What was broken here was purely the
hand-off.
"""

from __future__ import annotations

import pytest

from syndicate.blueprints import ops as ops_module


@pytest.fixture()
def captured_launch(monkeypatch):
    """Capture the kwargs `_start_refresh_job` hands to `launch_refresh_run`."""
    seen: dict[str, object] = {}

    def _fake_launch(**kwargs):
        seen.update(kwargs)
        return {"pid": 4242, "ok": True}

    monkeypatch.setattr(ops_module, "launch_refresh_run", _fake_launch)
    monkeypatch.setattr(ops_module, "_store_ops_job", lambda job_id, job: job)
    return seen


def test_a_named_league_reaches_launch_refresh_run(captured_launch):
    """The fix. Without it this kwarg was absent and every job was all-leagues."""
    ops_module._start_refresh_job(
        {
            "date": "2026-08-14",
            "sports": "soccer",
            "phase": "pregame",
            "soccer_leagues": "primeira_liga",
            "launch_mode": "manifest_only",
        },
        mode="full",
    )

    assert captured_launch.get("soccer_leagues") == "primeira_liga"


def test_several_leagues_pass_through_verbatim(captured_launch):
    """Comma-separated scope is the CLI's own contract; ops must not reshape it."""
    ops_module._start_refresh_job(
        {
            "date": "2026-08-14",
            "sports": "soccer",
            "soccer_leagues": "primeira_liga,championship,belgian_pro_league",
            "launch_mode": "manifest_only",
        },
        mode="full",
    )

    assert captured_launch.get("soccer_leagues") == "primeira_liga,championship,belgian_pro_league"


def test_soccer_date_also_reaches_the_runner(captured_launch):
    """`--soccer-date` pins the league-date unit; same missing hand-off."""
    ops_module._start_refresh_job(
        {
            "date": "2026-08-14",
            "sports": "soccer",
            "soccer_leagues": "championship",
            "soccer_date": "2026-08-14",
            "launch_mode": "manifest_only",
        },
        mode="full",
    )

    assert captured_launch.get("soccer_date") == "2026-08-14"


def test_omitting_the_scope_still_means_every_league(captured_launch):
    """The default MUST NOT change.

    Every existing caller posts no `soccer_leagues`, and `refresh_odds_sources.py`
    treats empty as "every active league". If this started sending "" as a
    meaningful value, or a stray default league, the nightly all-sports refresh
    would silently narrow — a far worse failure than the one being fixed.
    """
    ops_module._start_refresh_job(
        {"date": "2026-08-14", "sports": "soccer", "launch_mode": "manifest_only"},
        mode="full",
    )

    assert not captured_launch.get("soccer_leagues")
