"""The WNBA final boxscore producer — Syndicate-owned, no vendor.

WHY IT EXISTS. `wnba_source/data/processed/boxscores_<date>.csv` stopped being
produced after 2026-05-24 (one orphan file on 2026-08-18, then nothing), and
NOTHING IN SYNDICATE EVER PRODUCED IT — every caller of the vendor's
`fetch_boxscores_for_date` lives inside `vendor/*_betting_repo/`, while
`scripts/artifact_freshness.py:67` monitored the family for three months with no
writer behind it.

It is also the only source that can tell WNBA settlement a game is OVER.
`bet_status_wnba` hardcodes `is_final=False`, so an over that never crosses can
never decide and ONLY WINNING OVERS SETTLE. Measured on 2026-08-25: Sonia Citron
1 rebound vs over 3.5 and Georgia Amoore 3 assists vs over 3.5 are losses that
can never be recorded.
"""
from __future__ import annotations

import csv
import io

import pytest

from scripts import build_wnba_boxscores as mod


def _scoreboard(*states):
    return {"events": [
        {"id": f"40185717{n}", "status": {"type": {"state": s, "completed": s == "post"}}}
        for n, s in enumerate(states)
    ]}


def _summary(stats, *, name="Sonia Citron", abbreviation="WSH"):
    return {"boxscore": {"players": [{
        "team": {"abbreviation": abbreviation},
        "statistics": [{
            "keys": ["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
                     "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
                     "freeThrowsMade-freeThrowsAttempted", "rebounds", "assists",
                     "turnovers", "steals", "blocks", "offensiveRebounds",
                     "defensiveRebounds", "fouls", "plusMinus"],
            "athletes": [{
                "athlete": {"id": "4433403", "displayName": name},
                "starter": True,
                "position": {"abbreviation": "G"},
                "stats": stats,
            }],
        }],
    }]}}


def test_only_COMPLETED_games_are_written(monkeypatch):
    """A game still in progress is EXCLUDED, not written with partial stats.

    A boxscore that grows is worse than one that is absent: a consumer cannot
    tell a half-game from a low-scoring one, and a prop settles differently on
    each.
    """
    monkeypatch.setattr(mod, "_get", lambda url, timeout=30: _scoreboard("post", "in", "pre"))
    assert mod.completed_event_ids("2026-08-25") == ["401857170"]


def test_the_column_contract_is_the_EXISTING_one():
    """Taken verbatim from a real artifact so the readers that already join
    against this file keep working. `game_id` and `gameId` are both present and
    identical in the real files, and both are kept for that reason."""
    assert list(mod.COLUMNS) == [
        "game_id", "gameId", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME",
        "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "OREB", "DREB", "PF",
        "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "PLUS_MINUS",
        "STARTER", "START_POSITION", "source", "date",
    ]
    header = mod.to_csv([]).splitlines()[0]
    assert header == ",".join(mod.COLUMNS)


def test_a_players_line_maps_onto_the_contract(monkeypatch):
    """The real ESPN keys, read from event 401857175 rather than guessed."""
    monkeypatch.setattr(mod, "_get", lambda url, timeout=30: _summary(
        ["29", "19", "7-12", "3-5", "2-2", "1", "9", "2", "1", "0", "0", "1", "3", "+8"]
    ))
    rows = mod.rows_for_event("401857175", "2026-08-25")
    assert len(rows) == 1
    row = rows[0]
    assert row["PLAYER_NAME"] == "Sonia Citron"
    assert row["TEAM_ABBREVIATION"] == "WSH"
    assert (row["MIN"], row["PTS"], row["REB"], row["AST"]) == ("29", "19", "1", "9")
    # The made-attempted pairs arrive as ONE "7-12" string and must be split.
    assert (row["FGM"], row["FGA"]) == ("7", "12")
    assert (row["FG3M"], row["FG3A"]) == ("3", "5")
    assert (row["FTM"], row["FTA"]) == ("2", "2")
    assert row["game_id"] == row["gameId"] == "401857175"
    assert row["source"] == "espn" and row["date"] == "2026-08-25"


def test_a_DNP_is_skipped_rather_than_written_as_zeros(monkeypatch):
    """"Did not play" and "played and scored nothing" are different facts, and a
    prop settles differently on each."""
    monkeypatch.setattr(mod, "_get", lambda url, timeout=30: _summary([]))
    assert mod.rows_for_event("401857175", "2026-08-25") == []


def test_an_empty_slate_writes_NOTHING(monkeypatch, tmp_path):
    """Same rule as `capture_wnba_live_player_box`: a well-formed file carrying
    no data reads as an answer to every consumer, and a persisted empty is
    served in preference to real data afterwards."""
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setattr(mod, "completed_event_ids", lambda d: [])
    result = mod.build_date("2026-08-25")
    assert result["status"] == "no_final_games"
    assert not list(tmp_path.rglob("boxscores_*.csv"))


def test_one_bad_event_does_not_cost_the_rest_of_the_slate(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setattr(mod, "completed_event_ids", lambda d: ["bad", "good"])

    def _rows(event_id, date_str):
        if event_id == "bad":
            raise RuntimeError("espn timeout")
        return [{c: "" for c in mod.COLUMNS} | {"PLAYER_NAME": "A", "date": date_str}]

    monkeypatch.setattr(mod, "rows_for_event", _rows)
    result = mod.build_date("2026-08-25")
    assert result["status"] == "ok" and result["rows"] == 1


def test_the_written_file_round_trips(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    monkeypatch.setattr(mod, "completed_event_ids", lambda d: ["401857175"])
    monkeypatch.setattr(mod, "_get", lambda url, timeout=30: _summary(
        ["25", "19", "8-14", "0-1", "3-4", "8", "0", "1", "0", "2", "3", "5", "2", "-4"],
        name="Natasha Mack", abbreviation="PHX",
    ))
    assert mod.build_date("2026-08-25")["status"] == "ok"

    written = tmp_path / "wnba_source" / "data" / "processed" / "boxscores_2026-08-25.csv"
    assert written.exists()
    rows = list(csv.DictReader(io.StringIO(written.read_text(encoding="utf-8"))))
    assert len(rows) == 1
    # The real value behind the one WNBA bet that DID settle: over 7.5 rebounds,
    # graded WON. If this producer disagreed with that, one of them is wrong.
    assert rows[0]["PLAYER_NAME"] == "Natasha Mack"
    assert rows[0]["REB"] == "8"


# ---------------------------------------------------------------------------
# The settlement-side gate. This runs on EVERY settlement pass (~3 min), so what
# it does NOT do matters as much as what it does.
# ---------------------------------------------------------------------------

def _state(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("SYNDICATE_REFRESH_STATE_BACKEND", "file")
    import pipeline.intelligence_state as istate
    return istate


def test_a_covered_slate_does_NOT_refetch(monkeypatch, tmp_path):
    """One scoreboard call says how many games are final. If the artifact already
    covers them, nothing else is fetched.

    Without this the producer would refetch every three minutes for the rest of
    the day, which is the shape `#241` turned into a production restart loop.
    """
    istate = _state(monkeypatch, tmp_path)
    written = tmp_path / "wnba_source" / "data" / "processed" / "boxscores_2026-08-25.csv"
    written.parent.mkdir(parents=True)
    written.write_text(
        ",".join(mod.COLUMNS) + "\n"
        + "401857173," + ",".join([""] * (len(mod.COLUMNS) - 1)) + "\n"
        + "401857175," + ",".join([""] * (len(mod.COLUMNS) - 1)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "completed_event_ids", lambda d: ["401857173", "401857175"])

    called = {"n": 0}
    monkeypatch.setattr(mod, "build_date", lambda d, **kw: called.__setitem__("n", called["n"] + 1))
    istate._refresh_wnba_boxscores("2026-08-25")
    assert called["n"] == 0, "a covered slate must not refetch"


def test_a_slate_that_has_MOVED_is_rebuilt(monkeypatch, tmp_path):
    """A slate finishing through the evening is picked up as each game ends --
    the artifact covering 1 of 3 finals is not "done"."""
    istate = _state(monkeypatch, tmp_path)
    written = tmp_path / "wnba_source" / "data" / "processed" / "boxscores_2026-08-25.csv"
    written.parent.mkdir(parents=True)
    written.write_text(
        ",".join(mod.COLUMNS) + "\n"
        + "401857173," + ",".join([""] * (len(mod.COLUMNS) - 1)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "completed_event_ids",
                        lambda d: ["401857173", "401857174", "401857175"])
    called = {"n": 0}
    monkeypatch.setattr(mod, "build_date", lambda d, **kw: called.__setitem__("n", called["n"] + 1))
    istate._refresh_wnba_boxscores("2026-08-25")
    assert called["n"] == 1


def test_no_final_games_fetches_nothing_further(monkeypatch, tmp_path):
    istate = _state(monkeypatch, tmp_path)
    monkeypatch.setattr(mod, "completed_event_ids", lambda d: [])
    called = {"n": 0}
    monkeypatch.setattr(mod, "build_date", lambda d, **kw: called.__setitem__("n", called["n"] + 1))
    istate._refresh_wnba_boxscores("2026-08-25")
    assert called["n"] == 0


def test_a_producer_failure_NEVER_reaches_settlement(monkeypatch, tmp_path):
    """Settlement failing because a producer failed would be a worse outcome
    than the gap this closes."""
    istate = _state(monkeypatch, tmp_path)

    def _boom(_date):
        raise RuntimeError("espn down")

    monkeypatch.setattr(mod, "completed_event_ids", _boom)
    istate._refresh_wnba_boxscores("2026-08-25")  # must not raise
