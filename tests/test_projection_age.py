"""`#350` — a projection has an age and the board never showed it.

Measured 2026-08-11: la_liga's `recommendations_2026-08-15.json` carried
`generated_at: 2026-07-20T21:32:50Z` -- a 22-DAY-OLD simulation -- and the board
rendered it identically to a fresh one. Prices already carry `age_seconds`; the
model behind them carried nothing, so "the sim likes this" could mean "as of
three weeks ago" with no way to tell.
"""

from __future__ import annotations

import datetime as dt
import json

from syndicate.features.shared.soccer_projections import (
    SoccerProjectionIndex,
    _age_hours,
    attach_soccer_projections,
    load_soccer_projections,
)


def _write(root, league, date_str, generated_at):
    d = root / league / "api" / "recommendations"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"recommendations_{date_str}.json").write_text(json.dumps({
        "league": league, "date": date_str, "generated_at": generated_at,
        "matches": [{
            "event_id": f"evt-{league}", "league": league, "date": date_str,
            "matchup": {"home_team": "Home FC", "away_team": "Away FC"},
            "win_probability": {"home": 0.55, "away": 0.25},
        }],
    }), encoding="utf-8")


def test_a_stale_sim_is_visible_on_the_row(tmp_path):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=22)).isoformat()
    _write(tmp_path, "la_liga", "2026-08-15", old)
    index = load_soccer_projections([tmp_path], "2026-08-15")
    rows = [{"market": "h2h", "home_team": "Home FC", "away_team": "Away FC", "sides": ["home", "away"]}]
    attach_soccer_projections(rows, index)
    proj = rows[0]["projection"]
    assert proj["generated_at"] == old
    assert proj["age_hours"] > 500          # ~528h for 22 days



def test_a_fresh_sim_reads_fresh(tmp_path):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    _write(tmp_path, "la_liga", "2026-08-15", now)
    index = load_soccer_projections([tmp_path], "2026-08-15")
    rows = [{"market": "h2h", "home_team": "Home FC", "away_team": "Away FC", "sides": ["home", "away"]}]
    attach_soccer_projections(rows, index)
    assert rows[0]["projection"]["age_hours"] < 1


def test_age_is_per_league_not_global(tmp_path):
    # Leagues simulate on their own units, so one stale league must not make the
    # others look stale, or the reverse.
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=20)).isoformat()
    new = dt.datetime.now(dt.timezone.utc).isoformat()
    _write(tmp_path, "la_liga", "2026-08-15", old)
    _write(tmp_path, "mls", "2026-08-15", new)
    index = load_soccer_projections([tmp_path], "2026-08-15")
    assert index.generated_at_by_league["la_liga"] == old
    assert index.generated_at_by_league["mls"] == new


def test_an_unparseable_timestamp_is_unknown_not_fresh(tmp_path):
    # None rather than 0 -- an unknown age must not read as a fresh one, which
    # is the same rule this whole field exists to enforce.
    assert _age_hours("not-a-date") is None
    assert _age_hours("") is None


def test_the_coverage_report_surfaces_the_oldest_sim(tmp_path):
    # An operator reads coverage first; staleness belongs there too, not only
    # on individual rows.
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=22)).isoformat()
    _write(tmp_path, "la_liga", "2026-08-15", old)
    index = load_soccer_projections([tmp_path], "2026-08-15")
    cov = attach_soccer_projections(
        [{"market": "h2h", "home_team": "Home FC", "away_team": "Away FC", "sides": ["home", "away"]}], index
    )
    assert cov["oldest_sim_age_hours"] > 500
    assert "la_liga" in cov["generated_at_by_league"]


def test_the_board_renders_the_age_rather_than_only_carrying_it():
    """A field nothing renders is invisible, which is the defect this fixes.

    The board already showed price age; the model behind it showed nothing, so a
    22-day-old sim and a fresh one looked identical to a reader.
    """
    import pathlib

    html = (pathlib.Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "shared" / "layer1_board.html").read_text(encoding="utf-8")
    assert "p.age_hours" in html, "the board never reads the age field"
    assert "projStale" in html
    # marked at 24h -- sims legitimately run on multi-hour cadences (4h for
    # soccer units), so a tighter bound would cry wolf every cycle
    assert "projAge >= 24" in html
    # and it must be visible, not just a tooltip
    assert 'projStale ? " *"' in html
