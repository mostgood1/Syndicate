"""UEFA results history fetcher (todo #699 step 1). Hermetic: no network."""

from __future__ import annotations

import csv

import pytest

from syndicate.features.soccer.ingestion import uefa_history as uh


def _event(event_id, when, home, away, hs, as_, *, completed=True, name="STATUS_FULL_TIME"):
    return {
        "id": event_id,
        "date": when,
        "competitions": [{
            "status": {"type": {"completed": completed, "state": "post" if completed else "pre", "name": name}},
            "competitors": [
                {"homeAway": "home", "score": str(hs), "team": {"id": home[0], "displayName": home[1]}},
                {"homeAway": "away", "score": str(as_), "team": {"id": away[0], "displayName": away[1]}},
            ],
        }],
    }


ARS, GAL, BRU = ("359", "Arsenal"), ("432", "Galatasaray"), ("570", "Club Brugge")
PAYLOADS = {
    # Calendar 2024 holds the END of season 2023 (Mar) and the START of season 2024 (Oct).
    ("uefa.champions", 2024): {"events": [
        _event("e1", "2024-03-12T20:00Z", ARS, GAL, 2, 1),
        _event("e2", "2024-10-01T19:00Z", GAL, BRU, 0, 0),
        _event("e3", "2024-10-02T19:00Z", BRU, ARS, 1, 3, completed=False),        # not played yet
        _event("e4", "2024-10-03T19:00Z", ARS, BRU, 0, 0, name="STATUS_POSTPONED"),  # filed as post, never played
    ]},
    ("uefa.champions", 2025): {"events": [_event("e5", "2025-02-18T20:00Z", BRU, GAL, 2, 2)]},
    # The same match listed under the qualifier slug too must count once.
    ("uefa.champions_qual", 2024): {"events": [_event("e2", "2024-10-01T19:00Z", GAL, BRU, 0, 0)]},
}


def _fake_fetch(slug, year):
    return PAYLOADS.get((slug, year), {"events": []})


def test_season_of_splits_the_calendar_year_in_july():
    assert uh.season_of("2024-06-30T20:00Z") == 2023
    assert uh.season_of("2024-07-01T20:00Z") == 2024
    assert uh.season_of("2025-05-28T19:00Z") == 2024


def test_collect_regroups_by_season_dedupes_and_drops_unplayed():
    out = uh.collect("ucl", [2024], pause_seconds=0, fetch=_fake_fetch)
    rows = out[2024]
    assert [r["event_id"] for r in rows] == ["e2", "e5"]          # e1 is season 2023; e3/e4 never played
    assert rows[0]["stage"] == "main"                              # main slug wins the dedupe
    assert (rows[1]["home_team_id"], rows[1]["away_team_id"]) == ("570", "432")
    assert (rows[1]["home_score"], rows[1]["away_score"]) == (2, 2)


def test_collect_fetches_both_calendar_years_of_each_season():
    asked = []
    uh.collect("uel", [2021, 2022], pause_seconds=0, fetch=lambda s, y: asked.append((s, y)) or {"events": []})
    assert sorted({y for _, y in asked}) == [2021, 2022, 2023]
    assert {s for s, _ in asked} == {"uefa.europa", "uefa.europa_qual"}


def test_only_uefa_competitions_are_accepted():
    with pytest.raises(ValueError):
        uh.slugs_for("epl")


def test_write_season_is_atomic_and_round_trips(tmp_path):
    rows = uh.collect("ucl", [2024], pause_seconds=0, fetch=_fake_fetch)[2024]
    path = uh.write_season(tmp_path, "ucl", 2024, rows)
    assert path == tmp_path / "ucl" / "history" / "uefa_results_2024.csv"
    assert not path.with_suffix(".csv.tmp").exists()
    back = list(csv.DictReader(path.open(encoding="utf-8")))
    assert [r["event_id"] for r in back] == ["e2", "e5"]
    assert list(back[0]) == list(uh.COLUMNS)


def test_a_failed_build_never_truncates_the_existing_file(tmp_path, monkeypatch):
    path = uh.write_season(tmp_path, "ucl", 2024, [])
    before = path.read_bytes()

    def _boom(*_a, **_k):
        raise RuntimeError("csv failed mid-build")

    monkeypatch.setattr(uh.csv, "DictWriter", _boom)
    with pytest.raises(RuntimeError):
        uh.write_season(tmp_path, "ucl", 2024, [{"season": 2024}])
    assert path.read_bytes() == before
