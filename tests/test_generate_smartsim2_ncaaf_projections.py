"""Regression coverage for the 2026 season-bootstrap fixes in
scripts/generate_smartsim2_ncaaf_projections.py:

1. PPA ratings have no fallback for a brand-new season with no games played
   yet (confirmed live: CFBD's /ppa/teams returns [] for 2026). Fixed with a
   whole-index fallback to the prior season's final ratings.
2. The legacy engine's predicted-totals schedule is a single, non-season-
   partitioned file only ever refreshed for the engine's own season -- for a
   season the engine has no rows for, the games-to-simulate list must come
   directly from the already-fetched real CFBD games instead.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import scripts.generate_smartsim2_ncaaf_projections as gen


class LoadPpaRatingsWithFallbackTests(unittest.TestCase):
    def test_uses_current_season_when_populated(self) -> None:
        def fake_load(season):
            if season == 2026:
                return {"ohio st": {"team": "Ohio State"}}
            raise AssertionError("should not fetch prior season when current season is populated")

        with patch.object(gen, "load_ppa_ratings", side_effect=fake_load):
            index, rating_source = gen.load_ppa_ratings_with_fallback(2026)
        self.assertEqual(index, {"ohio st": {"team": "Ohio State"}})
        self.assertEqual(rating_source, "cfbd_ppa_season_2026")

    def test_falls_back_to_prior_season_when_current_is_empty(self) -> None:
        def fake_load(season):
            return {} if season == 2026 else {"ohio st": {"team": "Ohio State"}}

        with patch.object(gen, "load_ppa_ratings", side_effect=fake_load):
            index, rating_source = gen.load_ppa_ratings_with_fallback(2026)
        self.assertEqual(index, {"ohio st": {"team": "Ohio State"}})
        self.assertEqual(rating_source, "cfbd_ppa_season_2025_fallback_for_2026")

    def test_both_empty_returns_empty_index_and_current_season_label(self) -> None:
        with patch.object(gen, "load_ppa_ratings", return_value={}):
            index, rating_source = gen.load_ppa_ratings_with_fallback(2026)
        self.assertEqual(index, {})
        self.assertEqual(rating_source, "cfbd_ppa_season_2026")


class GamesFromCfbdWhenEngineScheduleEmptyTests(unittest.TestCase):
    def test_filters_to_strict_fbs_vs_fbs(self) -> None:
        cfbd_games = {
            ("a", "b"): {"homeTeam": "TCU", "awayTeam": "North Carolina", "homeClassification": "fbs", "awayClassification": "fbs"},
            ("c", "d"): {"homeTeam": "Delaware State", "awayTeam": "Stony Brook", "homeClassification": "fcs", "awayClassification": "fcs"},
            ("e", "f"): {"homeTeam": "Texas Tech", "awayTeam": "Abilene Christian", "homeClassification": "fbs", "awayClassification": "fcs"},
        }
        rows = gen.games_from_cfbd_when_engine_schedule_empty(cfbd_games)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {"home_team": "TCU", "away_team": "North Carolina"})

    def test_skips_games_missing_team_names(self) -> None:
        cfbd_games = {("a", "b"): {"homeTeam": "", "awayTeam": "North Carolina", "homeClassification": "fbs", "awayClassification": "fbs"}}
        rows = gen.games_from_cfbd_when_engine_schedule_empty(cfbd_games)
        self.assertEqual(rows, [])

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(gen.games_from_cfbd_when_engine_schedule_empty({}), [])


# ---------------------------------------------------------------------------
# SP+ IN-SEASON REFRESH (lane `ncaaf-sim-inseason-ratings`, 2026-09-18).
#
# Measured that day: the cached 2026 SP+ was the 2026-09-05 snapshot and a live
# `/ratings/sp?year=2026` had moved every one of 105 name-matched teams. Every
# test below pins the clock and injects the fetcher, so none touches CFBD.
# ---------------------------------------------------------------------------

import json
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc).timestamp()
STALE = {"alabama": (30.0, 20.0), "auburn": (25.0, 24.0), "ohio st": (35.0, 12.0)}
FRESH_ROWS = [
    {"team": "Alabama", "offense": {"rating": 38.0}, "defense": {"rating": 14.0}},
    {"team": "Auburn", "offense": {"rating": 21.0}, "defense": {"rating": 29.0}},
    {"team": "Ohio State", "offense": {"rating": 36.0}, "defense": {"rating": 11.0}},
    {"team": "nationalAverages", "offense": {"rating": 28.0}, "defense": {"rating": 28.0}},
]


def _iso(days_before_now: float) -> str:
    return (datetime.fromtimestamp(NOW, tz=timezone.utc) - timedelta(days=days_before_now)).isoformat()


def _write_copy(path, teams, *, fetched_at, verified=True, season=2026):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"season": season, "fetched_at": fetched_at, "source": "cfbd /ratings/sp",
           "teams": {k: list(v) for k, v in teams.items()}}
    if verified:
        doc["fetched_at_source"] = "cfbd_fetch"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


class _Fetcher:
    def __init__(self, result=None, exc=None):
        self.result, self.exc, self.calls = result, exc, []

    def __call__(self, season):
        self.calls.append(season)
        if self.exc is not None:
            raise self.exc
        return self.result


@pytest.fixture()
def sp_dir(tmp_path, monkeypatch):
    """One directory for every SP+ read and write, and no loader gzip cache."""
    monkeypatch.setenv("SYNDICATE_SP_RATINGS_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(gen, "_SP_CACHE_REFRESH", False, raising=False)
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("real CFBD call")))
    from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader as loader

    monkeypatch.setattr(loader, "load_cached_ratings", lambda season, **k: None)
    gen._SP_PROVENANCE.clear()
    yield tmp_path
    gen._SP_PROVENANCE.clear()


def _refresh(fetcher, published=None, **kw):
    published = [] if published is None else published
    return gen.refresh_sp_ratings_cache(
        kw.pop("season", 2026), now=kw.pop("now", NOW), fetch=fetcher,
        publish=lambda path: published.append(path) or True,
    )


def test_a_fresh_copy_is_not_refetched(sp_dir):
    _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(2))
    fetcher = _Fetcher(FRESH_ROWS)
    result = _refresh(fetcher)
    assert result["status"] == "fresh"
    assert fetcher.calls == []
    assert result["teams"] == 3


def test_a_stale_copy_is_refetched_written_and_published(sp_dir):
    path = _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(7))
    fetcher, published = _Fetcher(FRESH_ROWS), []
    result = _refresh(fetcher, published)
    assert result["status"] == "refreshed", result
    assert fetcher.calls == [2026]
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["teams"]["alabama"] == [38.0, 14.0]
    assert "nationalaverages" not in written["teams"]
    assert written["fetched_at_source"] == "cfbd_fetch"
    assert gen._parse_fetched_at(written["fetched_at"]) == pytest.approx(NOW)
    assert published == [path]


def test_an_unverified_copy_counts_as_stale_even_when_recently_stamped(sp_dir):
    """The live re-sim used to RE-STAMP a stale copy with `now` once a day, so a
    legacy `fetched_at` cannot be trusted as a fetch time. Unknown -> stale."""
    _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(0.1), verified=False)
    fetcher = _Fetcher(FRESH_ROWS)
    assert _refresh(fetcher)["status"] == "refreshed"
    assert fetcher.calls == [2026]


def test_a_short_payload_is_refused_and_the_good_copy_kept(sp_dir):
    path = _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(9))
    before = path.read_text(encoding="utf-8")
    result = _refresh(_Fetcher(FRESH_ROWS[:2]))
    assert result["status"] == "short_payload_refused"
    assert result["incoming_teams"] == 2 and result["teams"] == 3
    assert path.read_text(encoding="utf-8") == before
    assert _refresh(_Fetcher([]), now=NOW + 7 * 3600)["status"] == "short_payload_refused"
    assert path.read_text(encoding="utf-8") == before


def test_a_failed_fetch_keeps_the_stale_copy_and_throttles_retries(sp_dir):
    path = _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(9))
    before = path.read_text(encoding="utf-8")
    result = _refresh(_Fetcher(exc=RuntimeError("HTTP 500")))
    assert result["status"] == "fetch_failed"
    assert path.read_text(encoding="utf-8") == before
    marker = sp_dir / "sp_ratings_2026.refresh_attempt"
    assert float(marker.read_text(encoding="utf-8")) == pytest.approx(NOW)

    # Within 6 h: no call at all.
    again = _Fetcher(FRESH_ROWS)
    throttled = _refresh(again, now=NOW + 5 * 3600)
    assert throttled["status"] == "throttled" and again.calls == []
    # Stale beats blank: the generator still gets the old ratings.
    assert gen.load_sp_ratings(2026)["alabama"] == (30.0, 20.0)

    # After 6 h the throttle lifts.
    later = _Fetcher(FRESH_ROWS)
    assert _refresh(later, now=NOW + 6 * 3600 + 1)["status"] == "refreshed"
    assert later.calls == [2026]


def test_a_quota_exhaustion_is_a_fetch_failure_not_a_crash(sp_dir):
    from syndicate.features.ncaaf.cfbd_quota_latch import QuotaExhausted

    _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(9))
    assert _refresh(_Fetcher(exc=QuotaExhausted("monthly quota")))["status"] == "fetch_failed"


@pytest.mark.parametrize("season", [2025, 2024, 2027])
def test_a_season_other_than_the_current_one_is_never_refetched(sp_dir, season):
    """A past season's SP+ is FINAL (and leaky); a future one does not exist."""
    _write_copy(sp_dir / f"sp_ratings_{season}.json", STALE, fetched_at=_iso(400), season=season)
    fetcher = _Fetcher(FRESH_ROWS)
    assert _refresh(fetcher, season=season)["status"] == "not_current_season"
    # Even with NO copy at all.
    (sp_dir / f"sp_ratings_{season}.json").unlink()
    assert _refresh(fetcher, season=season)["status"] == "not_current_season"
    assert fetcher.calls == []


def test_the_season_boundary_is_august():
    at = lambda *ymd: datetime(*ymd, tzinfo=timezone.utc).timestamp()
    assert gen.current_ncaaf_season(at(2026, 9, 18)) == 2026
    assert gen.current_ncaaf_season(at(2027, 1, 10)) == 2026
    assert gen.current_ncaaf_season(at(2027, 7, 31)) == 2026
    assert gen.current_ncaaf_season(at(2027, 8, 1)) == 2027


def test_a_mirror_of_a_loaded_copy_keeps_its_original_fetch_time(sp_dir):
    """The ratchet this lane found: `run_refresh_worker._ncaaf_sp_ratings_index`
    rewrites the durable mirror from `load_sp_ratings` via `_write_sp_cache`
    with no timestamp. That rewrite must carry the loaded copy's fetch time,
    or the six-day rule reads a fortnight-old rating as brand new forever."""
    path = _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(5))
    index = gen.load_sp_ratings(2026)
    assert gen._write_sp_cache(path, 2026, index) is True
    rewritten = json.loads(path.read_text(encoding="utf-8"))
    assert rewritten["fetched_at"] == _iso(5)
    assert rewritten["fetched_at_source"] == "cfbd_fetch"
    # An index nobody loaded here is stamped now and NOT vouched for.
    other = sp_dir / "other.json"
    gen._write_sp_cache(other, 2026, {"x": (1.0, 2.0)})
    assert "fetched_at_source" not in json.loads(other.read_text(encoding="utf-8"))


def test_the_newest_copy_wins_across_the_durable_and_checkout_paths(tmp_path, monkeypatch):
    """Render holds TWO copies: the git one in the ephemeral checkout and the
    refreshed one on the mounted disk. Whichever is newer must be served."""
    monkeypatch.delenv("SYNDICATE_SP_RATINGS_CACHE_DIR", raising=False)
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "disk" / "ncaaf_source"))
    checkout = tmp_path / "checkout" / "sp_ratings_2026.json"
    monkeypatch.setattr(gen, "sp_ratings_cache_path", lambda season: checkout)
    monkeypatch.setattr(gen, "_SP_CACHE_REFRESH", False, raising=False)
    monkeypatch.setattr(gen, "_cfbd_get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("real CFBD call")))
    from syndicate.features.football.sim_engine.smartsim2.historical_truth import ncaaf_historical_loader as loader

    monkeypatch.setattr(loader, "load_cached_ratings", lambda season, **k: None)
    durable = gen.sp_ratings_durable_path(2026)
    assert durable == tmp_path / "disk" / "ncaaf_source" / "historical_truth" / "sp_ratings_2026.json"

    _write_copy(checkout, {"alabama": (1.0, 1.0)}, fetched_at=_iso(13), verified=False)
    _write_copy(durable, {"alabama": (2.0, 2.0)}, fetched_at=_iso(1))
    assert gen.load_sp_ratings(2026)["alabama"] == (2.0, 2.0)
    _write_copy(checkout, {"alabama": (3.0, 3.0)}, fetched_at=_iso(0.5), verified=False)
    assert gen.load_sp_ratings(2026)["alabama"] == (3.0, 3.0)


def test_the_refresh_lands_where_the_live_resim_reads_it(tmp_path, monkeypatch):
    """WRITE PATH == READ PATH, checked rather than assumed."""
    import scripts.run_refresh_worker as rw

    monkeypatch.delenv("SYNDICATE_SP_RATINGS_CACHE_DIR", raising=False)
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "ncaaf_source"))
    assert gen.sp_ratings_durable_path(2026) == rw._ncaaf_sp_ratings_durable_path(2026)


def test_the_refresh_line_names_season_status_fetched_at_and_teams():
    line = gen.format_sp_refresh_line({"status": "fresh", "season": 2026, "fetched_at": "x", "teams": 138, "age_hours": 3})
    assert line.startswith("SP_RATINGS_REFRESH season=2026 status=fresh fetched_at=x teams=138")
    assert "age_hours=3" in line


def test_REACHABILITY_refreshed_values_reach_build_projection(sp_dir, capsys):
    """Not "the file changed": the margin the generator PRICES changed.

    `resolve_sp_ratings` is the hop `main` takes. With a stale copy on disk and
    a fetcher returning different ratings, the projection built from what it
    returns must equal a projection built from the fetched ratings and differ
    from one built from the stale ones.
    """
    _write_copy(sp_dir / "sp_ratings_2026.json", STALE, fetched_at=_iso(8))

    def margin(index):
        return gen.build_projection(
            season=2026, week=4, home_team="Auburn", away_team="Alabama", game_id="g",
            ppa_index={}, rating_source="test", seeds=4,
            sp_index=index, sp_means=gen.sp_league_means(index),
        ).margin_mean

    stale_margin = margin(dict(STALE))
    index, result = gen.resolve_sp_ratings(2026, now=NOW, fetch=_Fetcher(FRESH_ROWS), publish=lambda p: False)
    assert result["status"] == "refreshed"
    assert index["alabama"] == (38.0, 14.0)
    expected = margin(gen._sp_index_from_payload(FRESH_ROWS))
    assert margin(index) == expected
    assert margin(index) != stale_margin, "the refresh did not reach the projection"
    out = capsys.readouterr().out
    assert out.count("SP_RATINGS_REFRESH ") == 1
    assert "SP_RATINGS_REFRESH season=2026 status=refreshed" in out


if __name__ == "__main__":
    unittest.main()
