"""A TYPED question about an NCAAF player gets his last-N games, a season-to-date
row and (when published) his prop projection -- lane `ncaaf-player-data`.

Before this, `_ncaaf_player_log_evidence` answered only from a board row, so
"how has Arch Manning played this season" carried no player evidence at all.
The data half lives in `ncaaf.player_stats.question_player_section`; the Ask
blueprint's `_ncaaf_player_question_evidence` wraps it (that file is co-held;
the wrapper tests below run once it is applied).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syndicate.features.ncaaf import player_stats

COLUMNS = (
    "season", "week", "game_id", "player_id", "player_name", "team", "passing_completions", "passing_attempts",
    "passing_yards", "passing_tds", "interceptions", "rushing_attempts", "rushing_yards", "rushing_tds", "receptions",
    "receiving_yards", "receiving_tds", "anytime_td", "source_system", "source_snapshot_date",
)


def _row(**kw) -> dict:
    row = {c: "0" for c in COLUMNS}
    row.update({"source_system": "cfbd", "source_snapshot_date": "2026-09-14"})
    row.update({k: str(v) for k, v in kw.items()})
    return row


def _qb(season, week, yds, tds, *, pid="QB1", name="Arch Manning", team="Texas", opp="Ohio State", game=None):
    gid = game or f"{season}-{week}-{team}"
    return [
        _row(season=season, week=week, game_id=gid, player_id=pid, player_name=name, team=team,
             passing_attempts=30, passing_yards=yds, passing_tds=tds, rushing_attempts=6, rushing_yards=25),
        _row(season=season, week=week, game_id=gid, player_id=f"OPP{season}{week}", player_name="Someone Else", team=opp,
             receptions=3, receiving_yards=30),
    ]


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    path = tmp_path / "ncaaf_player_game_stats_snapshot.csv"
    monkeypatch.setattr(player_stats, "player_game_stats_snapshot_path", lambda: path)
    player_stats.load_player_game_rows.cache_clear()

    def write(rows: list[dict]) -> Path:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        player_stats.load_player_game_rows.cache_clear()
        return path

    yield write
    player_stats.load_player_game_rows.cache_clear()


@pytest.fixture(autouse=True)
def _no_projection_by_default(monkeypatch):
    monkeypatch.setattr(player_stats, "_projection_table", lambda *a, **k: None)


def _season_rows() -> list[dict]:
    rows = []
    for week, yds, tds in ((1, 260, 2), (2, 310, 3), (3, 180, 1)):
        rows += _qb(2026, week, yds, tds)
    for week in range(1, 12):
        rows += _qb(2025, week, 200 + week, 1, team="Texas", opp=f"Opp{week}")
    return rows


def test_a_typed_question_gets_last_n_and_a_season_to_date_row(snapshot):
    snapshot(_season_rows())
    section = player_stats.question_player_section("how has Arch Manning played this season?", selected_date="2026-09-18")
    table = section["tables"][0]
    assert table["title"] == "Last 10 games — Arch Manning (Texas, CFBD box scores)"
    assert table["columns"] == ["Season", "Week", "Team", "Opp", "Att", "Pass yds", "Pass TD", "INT", "Rush yds"]
    # Newest first, crossing into last season to fill ten.
    assert [r[:2] for r in table["rows"][:4]] == [["2026", "3"], ["2026", "2"], ["2026", "1"], ["2025", "11"]]
    assert table["rows"][0][3] == "Ohio State"
    labels = [r[0] for r in table["rows"]]
    total = table["rows"][labels.index("2026 season to date — total (3 games)")]
    per_game = table["rows"][labels.index("2026 season to date — per game")]
    assert total[5] == "750" and per_game[5] == "250.0"   # pass yds 260 + 310 + 180
    assert total[6] == "6" and per_game[6] == "2.0"       # pass TDs
    assert section["evidence"]["players"][0]["season_games"] == 3
    assert section["charts"][0]["title"] == "Passing yards by game — Arch Manning"
    assert section["sport"] == "ncaaf" and section["as_of"]


def test_a_possessive_and_accents_still_match_the_full_name(snapshot):
    snapshot(_qb(2026, 1, 250, 2, pid="X", name="José Pérez Jr.", team="Texas"))
    section = player_stats.question_player_section("what are jose perez's numbers", selected_date="2026-09-18")
    assert section["tables"][0]["title"].startswith("Last 1 games — José Pérez Jr. (Texas")


def test_a_bare_surname_is_not_an_identity(snapshot):
    snapshot(_season_rows())
    assert player_stats.question_player_section("how has Manning played", selected_date="2026-09-18") is None
    assert player_stats.question_player_section("best bets tonight", selected_date="2026-09-18") is None


def test_a_namesake_is_refused_by_name_not_guessed(snapshot):
    snapshot(_qb(2026, 1, 250, 2, pid="A", name="Joseph Williams", team="Colorado")
             + _qb(2026, 1, 150, 1, pid="B", name="Joseph Williams", team="Holy Cross", opp="Opp"))
    section = player_stats.question_player_section("joseph williams stats", selected_date="2026-09-18")
    table = section["tables"][0]
    assert table["title"].startswith("Last games — 'joseph williams' matches 2 NCAAF players; refused rather than guessed")
    assert sorted(r[1] for r in table["rows"]) == ["Colorado", "Holy Cross"]
    assert section["evidence"]["players"] == []


def test_naming_the_school_resolves_the_namesake(snapshot):
    snapshot(_qb(2026, 1, 250, 2, pid="A", name="Joseph Williams", team="Colorado")
             + _qb(2026, 1, 150, 1, pid="B", name="Joseph Williams", team="Holy Cross", opp="Opp"))
    section = player_stats.question_player_section("joseph williams colorado", selected_date="2026-09-18",
                                                   question_teams=lambda: ["Colorado"])
    assert section["tables"][0]["title"] == "Last 1 games — Joseph Williams (Colorado, CFBD box scores)"
    assert section["evidence"]["players"][0]["player_id"] == "A"


def test_the_school_lookup_runs_only_for_an_ambiguous_name(snapshot):
    snapshot(_season_rows())

    def forbidden():
        raise AssertionError("an unambiguous name must not pay for the school lookup")

    assert player_stats.question_player_section("arch manning", selected_date="2026-09-18", question_teams=forbidden)


def test_a_transfers_old_school_games_join_by_player_id_not_name(snapshot):
    rows = _qb(2026, 1, 280, 3, pid="T", name="Portal Passer", team="New School")
    rows += _qb(2025, 9, 199, 1, pid="T", name="Portal Passer", team="Old School", opp="Rival")
    rows += _qb(2025, 9, 999, 9, pid="Z", name="Other Portal", team="Elsewhere", opp="Nobody")
    snapshot(rows)
    section = player_stats.question_player_section("portal passer", selected_date="2026-09-18")
    rows_out = section["tables"][0]["rows"]
    assert [r[2] for r in rows_out[:2]] == ["New School", "Old School"]
    assert "999" not in [r[5] for r in rows_out]


def test_a_player_with_no_season_game_says_so_instead_of_a_zero_row(snapshot):
    snapshot(_qb(2025, 5, 220, 2, pid="V", name="Last Year Only", team="Texas"))
    section = player_stats.question_player_section("last year only", selected_date="2026-09-18")
    labels = [r[0] for r in section["tables"][0]["rows"]]
    assert "2026 season to date: no 2026 games in the CFBD snapshot" in labels


def test_the_projection_table_reads_the_published_artifact(snapshot, tmp_path, monkeypatch):
    """The typed path shows the worker-built projection by player_id."""
    from syndicate.features.ncaaf import prop_projections as pp
    from syndicate.features.ncaaf import sources

    monkeypatch.undo()  # re-enable the real _projection_table and the snapshot patch below
    path = tmp_path / "ncaaf_player_game_stats_snapshot.csv"
    monkeypatch.setattr(player_stats, "player_game_stats_snapshot_path", lambda: path)
    monkeypatch.setenv("SYNDICATE_NCAAF_SOURCE_ROOT", str(tmp_path / "root"))
    monkeypatch.setattr(pp, "current_week_from_state", lambda season, **kw: 4)

    def forbidden(season):
        raise AssertionError("the games-cache fallback (17.9 s, 41 MB measured) must never run on a read path")

    monkeypatch.setattr(sources, "ncaaf_target_week", forbidden)
    pp._index_cached.cache_clear()
    snapshot(_season_rows())
    payload = {"schema": pp.SCHEMA, "season": 2026, "week": 4, "generated_at": "2026-09-18T10:00:00Z",
               "players": [{"player_id": "QB1", "name": "Arch Manning", "team": "Texas", "games": 3,
                            "markets": {"passing_yards": {"mean": 248.5, "dist": "gamma", "sd": 70.0, "season_mean": 250.0,
                                                          "season_games": 3, "prior_mean": 244.0,
                                                          "prior_source": "prior_season+role:lead"}}}]}
    artifact = pp.artifact_path(2026, 4)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_text(json.dumps(payload), encoding="utf-8")
    section = player_stats.question_player_section("arch manning", selected_date="2026-09-18")
    projection = next(t for t in section["tables"] if t["title"].startswith("Prop model projections"))
    assert projection["title"].startswith("Prop model projections — Arch Manning (2026 week 4")
    assert projection["rows"][0][:2] == ["Passing Yards", "248.50"]
    assert section["evidence"]["players"][0]["projection"] is True
    pp._index_cached.cache_clear()


def test_titles_map_to_their_prop_evidence_layers(snapshot):
    """Ask tags legacy tables by title; these must land on recent_form/player_sim."""
    from syndicate.blueprints import ask_the_syndicate_data as ask_data

    items = [{"title": "Last 10 games — Arch Manning (Texas, CFBD box scores)"},
             {"title": "Last games — 'joseph williams' matches 2 NCAAF players; refused rather than guessed (name the school)"},
             {"title": "Prop model projections — Arch Manning (2026 week 4, from games before week 4; unmeasured against prices)"},
             {"title": "Passing yards by game — Arch Manning"}]
    ask_data._tag_legacy_layers(items)
    assert [i["layer"] for i in items] == ["recent_form", "recent_form", "player_sim", "recent_form"]


# ---------------------------------------------------------------------------
# The Ask wrapper and its registration (co-held file; applied at landing)
# ---------------------------------------------------------------------------

_ask = pytest.importorskip("syndicate.blueprints.ask_the_syndicate_data")
_WRAPPER = getattr(_ask, "_ncaaf_player_question_evidence", None)
needs_wrapper = pytest.mark.skipif(
    _WRAPPER is None,
    reason="_ncaaf_player_question_evidence not applied yet -- the co-held Ask diff from lane ncaaf-player-data",
)


@needs_wrapper
def test_the_wrapper_is_registered_for_ncaaf_and_for_an_unrouted_question():
    assert _ask._entity_fetchers_for_sport("ncaaf", "q")[0] is _ask._ncaaf_player_log_evidence
    assert _WRAPPER in _ask._entity_fetchers_for_sport("ncaaf", "how has arch manning played")
    assert _WRAPPER in _ask._entity_fetchers_for_sport("", "how has arch manning played")


@needs_wrapper
def test_the_wrapper_answers_a_typed_question_and_stands_aside_for_a_board_row(snapshot):
    snapshot(_season_rows())
    section = _WRAPPER("how has Arch Manning played this season", {"selected_date": "2026-09-18"})
    assert section["tables"][0]["title"] == "Last 10 games — Arch Manning (Texas, CFBD box scores)"
    board_row = {"sport": "ncaaf", "player_name": "Arch Manning", "market": "Passing Yards"}
    assert _WRAPPER("arch manning", {"board_row": board_row, "selected_date": "2026-09-18"}) is None
