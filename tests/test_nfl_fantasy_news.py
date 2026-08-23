"""Tests for the news archive read path (`recent_news_by_player`).

`capture_news_snapshot` polls the SAME live ESPN feed on every run, so a
story that stays newsworthy for several days is written to the archive once
PER DAY it was still on the feed -- not once. Before this fix,
`recent_news_by_player` attached every one of those rows to the player it
named, so the Buzz popup showed the same headline repeated instead of
distinct coverage, and the `[:6]` cap in `fantasy.py` meant a player with one
story captured six times could show nothing else at all.
"""

from __future__ import annotations

import json

import syndicate.features.nfl.fantasy_news as fantasy_news
from syndicate.features.nfl.fantasy_news import recent_news_by_player

SEASON = 2026


def _patch_source_root(monkeypatch, root):
    # `default_nfl_source_root()` PROBES several candidates for an unrelated
    # artifact family (`upcoming_recs_*.csv`) and, when none of them have it,
    # falls back to a `source_artifacts/` variant of the env var -- and in
    # THIS checkout, the real repo's `data/nfl_source/` genuinely carries that
    # probe file, so an env-var-only patch resolves to the real repo tree
    # instead of the tmp dir (`test_nfl_fantasy_artifact.py` documents the
    # same trap). Patching the function directly, at the module the read path
    # imports it from, is the only way to guarantee an isolated root.
    monkeypatch.setattr(fantasy_news, "default_nfl_source_root", lambda: root, raising=False)
    import syndicate.features.nfl.sources as nfl_sources

    monkeypatch.setattr(nfl_sources, "default_nfl_source_root", lambda: root)


def _write_archive_day(root, day: str, articles: list[dict]) -> None:
    path = root / "fantasy" / "news_archive" / f"nfl_news_{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"season": SEASON, "captured_date": day, "articles": articles}),
        encoding="utf-8",
    )


def test_the_same_story_captured_on_consecutive_days_counts_once(tmp_path, monkeypatch):
    from datetime import date, timedelta

    root = tmp_path / "nfl_source"
    _patch_source_root(monkeypatch, root)

    today = date.today()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)

    # The SAME article (same id), captured three days running because it
    # stayed on ESPN's feed -- this is the normal, expected shape of the
    # archive, not a malformed fixture.
    story = {
        "id": "espn-1",
        "headline": "Player X named the starter",
        "description": "The team's coach confirmed the move on Wednesday.",
        "published": "2026-08-20T12:00:00Z",
        "players": ["00-000001"],
    }
    _write_archive_day(root, today.isoformat(), [story])
    _write_archive_day(root, yesterday.isoformat(), [story])
    _write_archive_day(root, two_days_ago.isoformat(), [story])

    entries = recent_news_by_player(SEASON)["00-000001"]
    assert len(entries) == 1
    assert entries[0]["description"] == story["description"]


def test_distinct_stories_about_the_same_player_are_both_kept(tmp_path, monkeypatch):
    from datetime import date, timedelta

    root = tmp_path / "nfl_source"
    _patch_source_root(monkeypatch, root)

    today = date.today()
    yesterday = today - timedelta(days=1)

    story_new = {
        "id": "espn-2",
        "headline": "Player X impresses at practice",
        "description": "A second, unrelated report.",
        "published": "2026-08-21T12:00:00Z",
        "players": ["00-000001"],
    }
    story_old = {
        "id": "espn-1",
        "headline": "Player X named the starter",
        "description": "The team's coach confirmed the move on Wednesday.",
        "published": "2026-08-20T12:00:00Z",
        "players": ["00-000001"],
    }
    _write_archive_day(root, today.isoformat(), [story_new])
    _write_archive_day(root, yesterday.isoformat(), [story_old])

    entries = recent_news_by_player(SEASON)["00-000001"]
    assert [item["id"] for item in entries] == ["espn-2", "espn-1"]


def test_articles_missing_an_id_fall_back_to_the_headline_for_dedup(tmp_path, monkeypatch):
    from datetime import date, timedelta

    root = tmp_path / "nfl_source"
    _patch_source_root(monkeypatch, root)

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Archive rows written before the `id` field existed carry none -- the
    # same real-world case `fantasy.html`'s optional-link comment documents.
    story = {
        "headline": "Player X on track to play Sunday",
        "description": "Beat writer update.",
        "published": "2026-08-20T12:00:00Z",
        "players": ["00-000002"],
    }
    _write_archive_day(root, today.isoformat(), [story])
    _write_archive_day(root, yesterday.isoformat(), [story])

    entries = recent_news_by_player(SEASON)["00-000002"]
    assert len(entries) == 1


def test_no_archive_directory_degrades_to_empty(tmp_path, monkeypatch):
    root = tmp_path / "nfl_source"
    _patch_source_root(monkeypatch, root)
    assert recent_news_by_player(SEASON) == {}
