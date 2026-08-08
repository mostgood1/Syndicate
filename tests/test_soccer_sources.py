from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from syndicate.features.soccer import sources


class RecommendationsPayloadFreshnessTests(unittest.TestCase):
    """2026-07-24 fix: recommendations_payload/picks_rows used to be
    @lru_cache-wrapped, on the (wrong) assumption that a date's file is
    written once and never changes. In reality build_soccer_artifacts.py
    rewrites the SAME recommendations_{date}.json path repeatedly as a
    match moves from pregame ("pre") through live ("in") to final ("post")
    with the real score -- and since the web dyno's gunicorn workers never
    auto-recycle (no --max-requests configured), the first read for a
    given (league, date) used to get cached forever, serving a stale
    pregame 0-0 snapshot days after the real game had finished. Confirmed
    live in production: 2026-07-22's MLS matches all stayed
    status_state="pre" with 0-0 scores for two days after ESPN's own
    scoreboard showed real final results.
    """

    def test_second_read_reflects_file_rewritten_after_first_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec_dir = root / "mls" / "api" / "recommendations"
            rec_dir.mkdir(parents=True)
            rec_path = rec_dir / "recommendations_2026-07-22.json"
            rec_path.write_text(json.dumps({"matches": [{"event_id": "1", "status_state": "pre"}]}), encoding="utf-8")

            with patch.object(sources, "_source_roots", return_value=[root]):
                first = sources.recommendations_payload("mls", "2026-07-22")
                self.assertEqual(first["matches"][0]["status_state"], "pre")

                rec_path.write_text(
                    json.dumps({"matches": [{"event_id": "1", "status_state": "post", "live_home_score": 2, "live_away_score": 1}]}),
                    encoding="utf-8",
                )
                second = sources.recommendations_payload("mls", "2026-07-22")

            self.assertEqual(second["matches"][0]["status_state"], "post")
            self.assertEqual(second["matches"][0]["live_home_score"], 2)

    def test_applies_to_every_league_not_just_mls(self) -> None:
        for league in ("epl", "la_liga", "mls", "bundesliga"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                rec_dir = root / league / "api" / "recommendations"
                rec_dir.mkdir(parents=True)
                rec_path = rec_dir / "recommendations_2026-07-22.json"
                rec_path.write_text(json.dumps({"matches": [{"event_id": "1", "status_state": "pre"}]}), encoding="utf-8")

                with patch.object(sources, "_source_roots", return_value=[root]):
                    sources.recommendations_payload(league, "2026-07-22")
                    rec_path.write_text(json.dumps({"matches": [{"event_id": "1", "status_state": "post"}]}), encoding="utf-8")
                    second = sources.recommendations_payload(league, "2026-07-22")

                self.assertEqual(second["matches"][0]["status_state"], "post", league)


class LeagueNormalizationTests(unittest.TestCase):
    def test_normalize_league_passes_through_known_slugs(self) -> None:
        self.assertEqual(sources.normalize_league("la_liga"), "la_liga")

    def test_normalize_league_falls_back_to_default_for_unknown(self) -> None:
        self.assertEqual(sources.normalize_league("not_a_real_league"), sources.DEFAULT_LEAGUE)
        self.assertEqual(sources.normalize_league(None), sources.DEFAULT_LEAGUE)

    def test_league_display_name(self) -> None:
        self.assertEqual(sources.league_display_name("epl"), "EPL")
        self.assertEqual(sources.league_display_name("belgian_pro_league"), "Belgian Pro League")


class SparseRosterTeamsTests(unittest.TestCase):
    def test_flags_teams_under_threshold_and_skips_full_squads(self) -> None:
        roster_rows = (
            {"team_id": "1"},
            {"team_id": "1"},
            {"team_id": "2"},
        ) + tuple({"team_id": "3"} for _ in range(20))
        teams = [
            {"team_id": "1", "name": "Sparse FC"},
            {"team_id": "2", "name": "Barely There FC"},
            {"team_id": "3", "name": "Full Squad FC"},
            {"team_id": "4", "name": "No Data FC"},
        ]
        with patch.object(sources, "roster_rows", return_value=roster_rows), \
             patch.object(sources, "all_teams", return_value=teams):
            sparse = sources.sparse_roster_teams("epl", 2026)
        sparse_ids = {row["team_id"] for row in sparse}
        self.assertEqual(sparse_ids, {"1", "2", "4"})
        by_id = {row["team_id"]: row["player_count"] for row in sparse}
        self.assertEqual(by_id["1"], 2)
        self.assertEqual(by_id["4"], 0)

    def test_no_sparse_teams_when_everyone_meets_threshold(self) -> None:
        roster_rows = tuple({"team_id": "1"} for _ in range(20))
        teams = [{"team_id": "1", "name": "Full Squad FC"}]
        with patch.object(sources, "roster_rows", return_value=roster_rows), \
             patch.object(sources, "all_teams", return_value=teams):
            self.assertEqual(sources.sparse_roster_teams("epl", 2026), [])

    def test_custom_threshold_is_respected(self) -> None:
        roster_rows = tuple({"team_id": "1"} for _ in range(10))
        teams = [{"team_id": "1", "name": "Ten Player FC"}]
        with patch.object(sources, "roster_rows", return_value=roster_rows), \
             patch.object(sources, "all_teams", return_value=teams):
            self.assertEqual(sources.sparse_roster_teams("epl", 2026, threshold=5), [])
            self.assertEqual(len(sources.sparse_roster_teams("epl", 2026, threshold=15)), 1)


class WeekResolutionTests(unittest.TestCase):
    def _payload(self) -> dict:
        return {
            "weeks": [
                {"week": 1, "start_date": "2026-08-01", "end_date": "2026-08-07"},
                {"week": 2, "start_date": "2026-08-08", "end_date": "2026-08-14"},
                {"week": 3, "start_date": "2026-08-15", "end_date": "2026-08-21"},
            ]
        }

    def test_available_weeks_sorted_and_deduped(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()):
            self.assertEqual(sources.available_weeks("epl", 2026), [1, 2, 3])

    # default_week resolves "today" through central_today_iso() (2026-07-24
    # timezone fix: date.today() drifted to tomorrow after 19:00 CDT on UTC
    # dynos), so tests pin that instead of date_cls.today to stay
    # deterministic regardless of the real wall clock.
    def test_default_week_picks_the_week_containing_today(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()), \
             patch.object(sources, "central_today_iso", return_value="2026-08-10"):
            self.assertEqual(sources.default_week("epl", 2026), 2)

    def test_default_week_picks_nearest_upcoming_when_today_is_before_season(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()), \
             patch.object(sources, "central_today_iso", return_value="2026-07-01"):
            self.assertEqual(sources.default_week("epl", 2026), 1)

    def test_default_week_falls_back_to_last_week_when_season_is_over(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()), \
             patch.object(sources, "central_today_iso", return_value="2026-12-01"):
            self.assertEqual(sources.default_week("epl", 2026), 3)

    def test_default_week_is_1_when_no_weeks_stored(self) -> None:
        with patch.object(sources, "schedule_payload", return_value={}):
            self.assertEqual(sources.default_week("epl", 2026), 1)

    def test_default_week_reference_date_overrides_real_today(self) -> None:
        # 2026-07-24 fix: requesting "tomorrow" (or any other date) from the
        # Betting Board must resolve the WEEK CONTAINING THAT DATE, not
        # whatever week real wall-clock today happens to fall in -- without
        # this, a future date crossing a matchweek boundary silently
        # returned the wrong week's games/props.
        with patch.object(sources, "schedule_payload", return_value=self._payload()), \
             patch.object(sources, "central_today_iso", return_value="2026-07-01"):
            self.assertEqual(sources.default_week("epl", 2026, reference_date="2026-08-10"), 2)

    def test_default_week_invalid_reference_date_falls_back_to_today(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()), \
             patch.object(sources, "central_today_iso", return_value="2026-08-10"):
            self.assertEqual(sources.default_week("epl", 2026, reference_date="not-a-date"), 2)

    def test_week_label_includes_date_range_when_known(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()):
            self.assertEqual(sources.week_label("epl", 2026, 1), "Week 1 (2026-08-01 to 2026-08-07)")

    def test_week_label_falls_back_without_a_matching_entry(self) -> None:
        with patch.object(sources, "schedule_payload", return_value=self._payload()):
            self.assertEqual(sources.week_label("epl", 2026, 99), "Week 99")


class WeekMatchesTests(unittest.TestCase):
    def test_week_matches_filters_by_week_number(self) -> None:
        payload = {
            "matches": [
                {"event_id": "1", "week": 1, "date": "2026-08-01T15:00Z"},
                {"event_id": "2", "week": 2, "date": "2026-08-08T15:00Z"},
                {"event_id": "3", "week": 1, "date": "2026-08-02T15:00Z"},
            ]
        }
        with patch.object(sources, "schedule_payload", return_value=payload):
            week_1 = sources.week_matches("epl", 2026, 1)
            self.assertEqual({row["event_id"] for row in week_1}, {"1", "3"})
            self.assertEqual(sources.week_date_list("epl", 2026, 1), ["2026-08-01", "2026-08-02"])


class BuildModuleLinksTests(unittest.TestCase):
    def test_carries_week_and_season_query_and_marks_active(self) -> None:
        links = sources.build_module_links("epl", 5, 2026, "Props")
        by_label = {link["label"]: link for link in links}
        self.assertTrue(by_label["Props"]["active"])
        self.assertFalse(by_label["Cards"]["active"])
        self.assertIn("?week=5&season=2026", by_label["Cards"]["href"])


class LeagueSelectControlTests(unittest.TestCase):
    def test_includes_every_league_and_navigates_on_change(self) -> None:
        control = sources.league_select_control("mls", page_path="/cards", query_suffix="?week=1&season=2026")
        self.assertEqual(control["value"], "mls")
        self.assertEqual({opt["value"] for opt in control["options"]}, set(sources.LEAGUE_DISPLAY_NAMES))
        self.assertIn("/cards?week=1&season=2026", control["onchange"])


if __name__ == "__main__":
    unittest.main()


def test_api_reads_fall_back_to_the_repo_root_when_the_runtime_disk_lacks_them(tmp_path, monkeypatch):
    """The soccer sim's whole failure mode, in one assertion.

    `_api_root` resolved `_source_roots()[0]` -- the runtime disk only -- and
    discarded the repo fallback `preferred_source_roots` appends on Render. With
    an empty runtime disk the schedule read returns nothing, so:

        available_weeks -> 0
        default_week    -> 1        (the "no weeks" fallback, NOT the real week)
        week_date_list  -> []
        build_soccer_artifacts.py --week ... -> SystemExit in 2s, no artifact

    Measured on production 2026-08-08: nine of ten leagues' sim processes lived
    under a minute against an 1800s step timeout and wrote no
    recommendations_*.json, and the process list showed them scoped to `week=1`
    while their real matchweek was 2 -- both symptoms of exactly this.
    """
    from syndicate.features.soccer import sources as soccer_sources

    empty_runtime = tmp_path / "runtime"
    empty_runtime.mkdir()
    repo_root = Path(soccer_sources.__file__).resolve().parents[3] / "data" / "soccer_source"

    monkeypatch.setattr(
        soccer_sources,
        "_source_roots",
        lambda: [empty_runtime, repo_root],
    )
    soccer_sources.schedule_payload.cache_clear()

    try:
        resolved = soccer_sources.schedule_path("eredivisie", 2026)
        assert resolved.is_file(), "must resolve to the root that actually has the schedule"
        assert repo_root in resolved.parents

        assert len(soccer_sources.available_weeks("eredivisie", 2026)) > 0
        assert soccer_sources.week_date_list("eredivisie", 2026, 2), "empty list is what raised SystemExit"
    finally:
        soccer_sources.schedule_payload.cache_clear()


def test_api_read_path_reports_the_runtime_location_when_nothing_has_the_file(tmp_path, monkeypatch):
    """Absence must still name the canonical runtime path, not a fallback that
    never held the artifact -- otherwise a missing-file error points somewhere
    misleading."""
    from syndicate.features.soccer import sources as soccer_sources

    first = tmp_path / "runtime"
    second = tmp_path / "repo"
    first.mkdir()
    second.mkdir()
    monkeypatch.setattr(soccer_sources, "_source_roots", lambda: [first, second])

    resolved = soccer_sources.schedule_path("eredivisie", 2026)

    assert first in resolved.parents
    assert not resolved.exists()


def test_week_dates_within_horizon_bounds_the_sim_to_what_the_board_can_rank():
    """The measured cost this exists to remove.

    One sweep across the ten active leagues on 2026-08-08 was 26 league-dates
    and only FOUR were today -- la_liga's week 1 alone spans six dates
    Aug 15-21. At ~145s per league-date that is ~63 minutes of continuous sim
    per sweep, on 4h/8h intervals, for fixtures up to twenty days out.
    """
    from syndicate.features.soccer import sources as soccer_sources

    # la_liga week 1 is the worst case: six dates, none of them today.
    full = soccer_sources.week_dates_within_horizon("la_liga", 2026, 1)
    assert len(full) >= 4, "expected the full week when no horizon is given"

    bounded = soccer_sources.week_dates_within_horizon(
        "la_liga", 2026, 1, reference_date="2026-08-08", horizon_days=1
    )
    assert bounded == [], "a league whose next fixture is a week away simulates nothing today"

    # eredivisie is mid-season: today and tomorrow are in the week, Aug 14 is not.
    bounded = soccer_sources.week_dates_within_horizon(
        "eredivisie", 2026, 2, reference_date="2026-08-08", horizon_days=1
    )
    assert bounded == ["2026-08-08", "2026-08-09"]


def test_week_dates_within_horizon_defaults_to_the_whole_week():
    """`horizon_days=None` must preserve the pre-existing CLI behaviour, so a
    deliberate backfill still gets every date."""
    from syndicate.features.soccer import sources as soccer_sources

    assert soccer_sources.week_dates_within_horizon(
        "eredivisie", 2026, 2
    ) == soccer_sources.week_date_list("eredivisie", 2026, 2)
