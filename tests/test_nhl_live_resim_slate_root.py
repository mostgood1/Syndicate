"""The NHL live re-sim reads its slate features from the PRODUCER's root, not the checkout's mirror.

`[2026-11-08, lane nhl-live-resim-slate-root]`. `build_live_lens_snapshot` called
`build_slate_features(date)` with no `root`, so the hockeysim loader fell back to
`<repo>/data/nhl_source` -- on the fleet the checkout `~/Syndicate`, whose odds scoreboards stop at
2026-06-14. Every live game refused `no_slate_features` while `~/syndicate-prod/data/nhl_source`
(where the pregame producer writes) listed it. Measured on the fleet 11-08: 0 games vs 6.

These run the REAL loader over a temp root (no stub of `build_slate_features`), so they fail on the
pre-fix code: there the env root is ignored and the game refuses `no_slate_features`.
"""

from __future__ import annotations

import csv

import pytest

from syndicate.features.nhl import live_resim as LR
from syndicate.features.shared.source_roots import clear_source_root_caches

DATE = "2026-10-08"
GAME_PK = "2026020123"


def _score_row():
    """A `/v1/score/<date>` row in NHL's real shape: home trails 2-3, 5:00 left in the third."""
    return {
        "id": int(GAME_PK),
        "gameState": "LIVE",
        "periodDescriptor": {"number": 3, "periodType": "REG"},
        "clock": {"timeRemaining": "05:00", "secondsRemaining": 300, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": "Toronto Maple Leafs"}, "score": 2},
        "awayTeam": {"id": 9, "name": {"default": "Ottawa Senators"}, "score": 3},
    }


def _write_scoreboard(nhl_root, date=DATE, pk=GAME_PK):
    out = nhl_root / "data" / "odds" / "games" / f"date={date}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "scoreboard.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["gamePk", "gameDate", "home", "away", "home_abbr", "away_abbr", "gameState"])
        w.writeheader()
        w.writerow({"gamePk": pk, "gameDate": f"{date}T23:00:00Z", "home": "Toronto Maple Leafs",
                    "away": "Ottawa Senators", "home_abbr": "TOR", "away_abbr": "OTT", "gameState": "LIVE"})


@pytest.fixture
def nhl_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SYNDICATE_ARTIFACT_ROOT_NHL", raising=False)
    monkeypatch.delenv("SYNDICATE_DATA_ROOT", raising=False)
    monkeypatch.setenv("SYNDICATE_NHL_SOURCE_ROOT", str(tmp_path / "nhl_source"))
    clear_source_root_caches()
    yield tmp_path / "nhl_source"
    clear_source_root_caches()


def _lane(snap):
    assert len(snap["games"]) == 1
    return snap["games"][0]["gameLens"][0]


def test_the_root_is_the_configured_nhl_source_root(nhl_env):
    assert LR._slate_features_root().resolve() == nhl_env.resolve()


def test_a_live_game_on_the_producers_scoreboard_is_not_refused_no_slate_features(nhl_env):
    _write_scoreboard(nhl_env)
    snap = LR.build_live_lens_snapshot(DATE, sims=5, score_rows=[_score_row()], slate_features=None)
    lane = _lane(snap)
    # THE BRANCH, not just the outcome: the features WERE found under the configured root ...
    assert snap["coverage"]["slateFeatureGames"] == 1
    # ... so the game is not refused for the reason the wrong root produced.
    assert lane.get("liveResimRefusal") != "no_slate_features", lane


def test_the_control_an_empty_configured_root_still_refuses_by_name(nhl_env):
    nhl_env.mkdir(parents=True, exist_ok=True)
    snap = LR.build_live_lens_snapshot(DATE, sims=5, score_rows=[_score_row()], slate_features=None)
    assert snap["coverage"]["slateFeatureGames"] == 0
    assert _lane(snap)["liveResimRefusal"] == "no_slate_features"


def test_an_explicit_artifact_root_keeps_its_precedence(nhl_env, monkeypatch, tmp_path):
    bundle = tmp_path / "bundle"
    _write_scoreboard(bundle)
    monkeypatch.setenv("SYNDICATE_ARTIFACT_ROOT_NHL", str(bundle))
    # None hands the loader its own default, which honours SYNDICATE_ARTIFACT_ROOT_NHL.
    assert LR._slate_features_root() is None
