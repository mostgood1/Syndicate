"""`#348` — the game-state join asked for one date while the board spanned days.

The shard is keyed by CAPTURE date, so a Thursday fixture quoted on Tuesday
lands in Tuesday's artifact. `attach_game_state` asked the scoreboard for
Tuesday only, so it could never resolve it. Measured 2026-08-11: all 16 NFL
preseason fixtures (kickoff 08-13/08-14, quoted 08-11) reported
`chips: 0, reason: no_chips_for_date` and rendered `unknown`.

`#329` made the board multi-day and left this join single-date.
"""

from __future__ import annotations

from syndicate.features.shared import board_enrichment


def _row(home, away, commence):
    return {"home_team": home, "away_team": away, "commence_time": commence}


def _chip(home, away, state="pregame"):
    return {"home": {"name": home, "abbr": home[:3].upper()},
            "away": {"name": away, "abbr": away[:3].upper()},
            "state": state, "start_time_utc": None, "status_token": None, "matchup": f"{away} @ {home}"}


def test_a_fixture_quoted_days_early_still_gets_its_state(monkeypatch):
    grid = [_row("Cincinnati Bengals", "Detroit Lions", "2026-08-13T23:00:00Z")]
    asked = []

    def fake_chips(date_str, sports):
        asked.append(date_str)
        # The scoreboard only knows about the day the game is PLAYED.
        return [_chip("Cincinnati Bengals", "Detroit Lions")] if date_str == "2026-08-13" else []

    monkeypatch.setattr(board_enrichment, "build_game_chips", fake_chips, raising=False)
    import syndicate.features.shared.game_chip_scoreboard as gcs
    monkeypatch.setattr(gcs, "build_game_chips", fake_chips)

    cov = board_enrichment.attach_game_state(grid, sport="nfl", selected_date="2026-08-11")
    assert "2026-08-13" in asked, "the join never asked about the date the game is played"
    assert cov["rows_matched"] == 1
    assert grid[0]["game"]["state"] == "pregame"


def test_the_artifacts_own_date_is_always_asked_first(monkeypatch):
    asked = []
    import syndicate.features.shared.game_chip_scoreboard as gcs
    monkeypatch.setattr(gcs, "build_game_chips", lambda d, s: asked.append(d) or [])
    board_enrichment.attach_game_state(
        [_row("A", "B", "2026-08-15T00:00:00Z")], sport="nfl", selected_date="2026-08-11"
    )
    assert asked[0] == "2026-08-11"


def test_the_number_of_scoreboard_calls_is_bounded(monkeypatch):
    # An artifact can hold weeks of forward fixtures -- 1,246 NFL rows across
    # many dates, measured the same day. Unbounded, this becomes one scoreboard
    # call per distinct future date on every build.
    grid = [_row("H", "A", f"2026-09-{d:02d}T00:00:00Z") for d in range(1, 29)]
    asked = []
    import syndicate.features.shared.game_chip_scoreboard as gcs
    monkeypatch.setattr(gcs, "build_game_chips", lambda d, s: asked.append(d) or [])
    board_enrichment.attach_game_state(grid, sport="nfl", selected_date="2026-08-11")
    assert len(asked) <= board_enrichment._MAX_GAME_STATE_DATES + 1


def test_one_bad_date_does_not_cost_the_others_their_state(monkeypatch):
    grid = [_row("Bengals", "Lions", "2026-08-13T23:00:00Z")]
    def flaky(date_str, sports):
        if date_str == "2026-08-11":
            raise RuntimeError("scoreboard unavailable")
        return [_chip("Bengals", "Lions")]
    import syndicate.features.shared.game_chip_scoreboard as gcs
    monkeypatch.setattr(gcs, "build_game_chips", flaky)
    cov = board_enrichment.attach_game_state(grid, sport="nfl", selected_date="2026-08-11")
    assert cov["rows_matched"] == 1
