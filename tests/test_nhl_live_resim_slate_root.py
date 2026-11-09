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


# --- The names the snapshot publishes are the BOARD's names `[2026-11-09]` -------------------------
#
# `/v1/score` names clubs by `name.default`, the SHORT name ('Senators'); the board's rows and the
# scoreboard say 'Ottawa Senators', and the game-line join compares full names lowercased. Measured on
# the fleet 11-09: snapshot ('Rangers', 'Oilers') vs 107 served rows ('New York Rangers',
# 'Edmonton Oilers') -- no live NHL lane could be indexed. These use the REAL row shape (short names).


def _real_shape_row(away_short="Senators", home_short="Maple Leafs"):
    row = _score_row()
    row["awayTeam"] = dict(row["awayTeam"], name={"default": away_short}, abbrev="OTT")
    row["homeTeam"] = dict(row["homeTeam"], name={"default": home_short}, abbrev="TOR")
    return row


def _write_scoreboard_named(nhl_root, home, away, date=DATE, pk=GAME_PK):
    out = nhl_root / "data" / "odds" / "games" / f"date={date}"
    out.mkdir(parents=True, exist_ok=True)
    with (out / "scoreboard.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["gamePk", "gameDate", "home", "away", "home_abbr", "away_abbr", "gameState"])
        w.writeheader()
        w.writerow({"gamePk": pk, "gameDate": f"{date}T23:00:00Z", "home": home, "away": away,
                    "home_abbr": "TOR", "away_abbr": "OTT", "gameState": "LIVE"})


def test_a_live_game_publishes_the_scoreboards_full_names_not_the_short_ones(nhl_env):
    _write_scoreboard(nhl_env)
    snap = LR.build_live_lens_snapshot(DATE, sims=5, score_rows=[_real_shape_row()], slate_features=None)
    game = snap["games"][0]
    assert (game["away_name"], game["home_name"]) == ("Ottawa Senators", "Toronto Maple Leafs")


def test_a_refused_game_publishes_the_same_full_names(nhl_env):
    _write_scoreboard(nhl_env)
    row = _real_shape_row()
    row["clock"] = dict(row["clock"], inIntermission=True)  # refused in_intermission, by design
    snap = LR.build_live_lens_snapshot(DATE, sims=5, score_rows=[row], slate_features=None)
    game = snap["games"][0]
    assert game["gameLens"][0].get("liveResimRefusal") == "in_intermission"
    assert (game["away_name"], game["home_name"]) == ("Ottawa Senators", "Toronto Maple Leafs")


def test_the_scoreboards_accented_spelling_wins_over_an_alias_table(nhl_env):
    # canonical_team('nhl', 'Canadiens') is 'montreal canadiens'; the scoreboard and the board say
    # 'Montréal Canadiens'. Publishing the scoreboard's spelling is what makes the exact join match.
    _write_scoreboard_named(nhl_env, home="Toronto Maple Leafs", away="Montréal Canadiens")
    snap = LR.build_live_lens_snapshot(DATE, sims=5, score_rows=[_real_shape_row("Canadiens")], slate_features=None)
    assert snap["games"][0]["away_name"] == "Montréal Canadiens"


def test_without_slate_features_the_raw_names_are_kept(nhl_env):
    nhl_env.mkdir(parents=True, exist_ok=True)
    snap = LR.build_live_lens_snapshot(DATE, sims=5, score_rows=[_real_shape_row()], slate_features=None)
    game = snap["games"][0]
    assert game["gameLens"][0]["liveResimRefusal"] == "no_slate_features"
    assert (game["away_name"], game["home_name"]) == ("Senators", "Maple Leafs")


def test_the_board_join_indexes_the_live_game_under_the_board_rows_names(nhl_env):
    """REACHABILITY: the join's own index call finds the game under the board row's key."""
    from syndicate.features.shared.live_gameline_join import (
        _norm_team,
        build_live_gameline_index,
        lens_sources_for_sport,
    )

    # Stub features carry rosters (a temp root's real loader has none, so it refuses `no_rosters`)
    # and the scoreboard's FULL names, as `build_slate_features` does; the row keeps NHL's short ones.
    from tests.test_nhl_live_resim import _StubFeatures

    feats = _StubFeatures(GAME_PK, "Toronto Maple Leafs", "Ottawa Senators")
    snap = LR.build_live_lens_snapshot(DATE, sims=20, score_rows=[_real_shape_row()], slate_features=[feats])
    lane = snap["games"][0]["gameLens"][0]
    assert lane.get("source") == LR.LIVE_RESIM_LENS_SOURCE, lane  # the branch that publishes a probability
    index = build_live_gameline_index(snap, sources=lens_sources_for_sport("nhl"), sport="nhl", slate_date=DATE)
    board_key = (_norm_team("Ottawa Senators"), _norm_team("Toronto Maple Leafs"))
    assert board_key in index, sorted(index)
