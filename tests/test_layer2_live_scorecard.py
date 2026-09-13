"""`scripts/layer2_live_scorecard.py` (lane layer2-live-scorecard-gate).

The scorecard settles the worker's opening ledger against final scores. Every
rule here decides which cell a published bet lands in, so a wrong rule would
move results between "in play" and "pregame" or between age buckets silently.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "layer2_live_scorecard.py"
_spec = importlib.util.spec_from_file_location("layer2_live_scorecard", _SRC)
mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mod)


@pytest.fixture(autouse=True)
def _registry_absent(monkeypatch):
    # A session worktree has no `data/`, so the alias registry resolves nothing
    # and `_team_key` returns the lowercased name. Pin that here: it is the case
    # that joined 0 of 932 rows on 2026-09-12, and the join must survive it.
    monkeypatch.setattr(mod, "_team_key", lambda sport, name: str(name or "").strip().lower())


def _rec(**over):
    # 2026-09-12 WF @ PUR, the row that opened the lane, in the odds feed's names.
    rec = {
        "key": "k1",
        "sport": "ncaaf",
        "event_id": "5a8d98c3",
        "market": "spreads",
        "segment": "full",
        "side": "away",
        "line": -6.5,
        "player_name": None,
        "price": 107,
        "bookmaker": "prophetx",
        "ev_pct": 4.7563,
        "captured_at": "2026-09-12T18:34:57Z",
        "commence_time": "2026-09-12T16:00:00Z",
        "away_team": "Wake Forest Demon Deacons",
        "home_team": "Purdue Boilermakers",
        "game_state": "live",
        "quote_seen_age_seconds": 1013.2,
        "book_age_seconds": 618.0,
    }
    rec.update(over)
    return rec


def _chip(away="Wake Forest", home="Purdue", away_score=27, home_score=13, state="final", sport="ncaaf"):
    # The scoreboard's spelling: short name, lowercased key.
    return {
        "sport": sport,
        "state": state,
        "matchup": f"{away} @ {home}",
        "away": {"key": away.lower(), "name": away, "score": away_score},
        "home": {"key": home.lower(), "name": home, "score": home_score},
    }


@pytest.mark.parametrize(
    "over, away, home, expected",
    [
        ({}, 20, 13, "win"),  # 7 - 6.5
        ({}, 19, 13, "loss"),  # 6 - 6.5
        ({"line": -7.0}, 20, 13, "push"),
        ({"side": "home", "line": 6.5}, 20, 13, "loss"),
        ({"market": "totals", "side": "over", "line": 47.5}, 20, 28, "win"),
        ({"market": "totals", "side": "under", "line": 47.5}, 20, 28, "loss"),
        ({"market": "totals", "side": "over", "line": 48.0}, 20, 28, "push"),
        ({"market": "h2h", "side": "home", "line": None}, 20, 28, "win"),
        ({"market": "h2h", "side": "away", "line": None}, 21, 21, "push"),
        ({"market": "totals", "side": "away", "line": 47.5}, 20, 28, None),
        ({"market": "player_pass_yds"}, 20, 28, None),
    ],
)
def test_grade(over, away, home, expected):
    assert mod.grade(_rec(**over), away, home) == expected


def test_phase_prefers_the_recorded_state_and_labels_the_clock_fallback():
    assert mod.phase_of(_rec(game_state="live")) == "in_play"
    assert mod.phase_of(_rec(game_state="pregame")) == "pregame"
    assert mod.phase_of(_rec(game_state=None)) == "in_play_by_clock"
    assert mod.phase_of(_rec(game_state=None, captured_at="2026-09-12T15:59:00Z")) == "pregame_by_clock"
    assert mod.phase_of(_rec(game_state=None, commence_time=None)) == "unknown"


def test_age_prefers_the_observation_clock_over_the_book_clock():
    assert mod.age_bucket(_rec()) == ">900s"  # seen 1013 wins over book 618
    assert mod.age_bucket(_rec(quote_seen_age_seconds=100.0)) == "<=120s"
    assert mod.age_bucket(_rec(quote_seen_age_seconds=None, book_age_seconds=600.0)) == "<=900s"
    assert mod.age_bucket(_rec(quote_seen_age_seconds=None, book_age_seconds=None)) == "unclocked"


def test_a_feed_name_joins_the_scoreboard_name_without_the_registry():
    # Measured 2026-09-12: "Penn State Nittany Lions" vs chip key "penn state".
    record = _rec(away_team="Penn State Nittany Lions", home_team="Temple Owls")
    chip, reason = mod.match_chip(record, mod.index_chips([_chip("Penn State", "Temple")])["ncaaf"])
    assert reason is None and chip["scores"] == (27, 13)


def test_accents_and_apostrophes_do_not_break_the_join():
    # 2026-09-12 unmatched: Cal Poly @ San Jose State, New Mexico State @ Hawaii.
    chips = mod.index_chips([_chip("Cal Poly", "San José State"), _chip("New Mexico State", "Hawaiʻi", 20, 31)])["ncaaf"]
    sjsu, reason = mod.match_chip(_rec(away_team="Cal Poly Mustangs", home_team="San Jose State Spartans"), chips)
    assert reason is None and sjsu["scores"] == (27, 13)
    hawaii, reason = mod.match_chip(_rec(away_team="New Mexico State Aggies", home_team="Hawaii Rainbow Warriors"), chips)
    assert reason is None and hawaii["scores"] == (20, 31)


def test_the_longest_name_wins_and_both_teams_must_hit_the_same_chip():
    chips = mod.index_chips([_chip("Texas", "Oklahoma"), _chip("Texas Tech", "Oklahoma State", 10, 3)])["ncaaf"]
    tech, _ = mod.match_chip(_rec(away_team="Texas Tech Red Raiders", home_team="Oklahoma State Cowboys"), chips)
    assert tech["scores"] == (10, 3)
    longhorns, _ = mod.match_chip(_rec(away_team="Texas Longhorns", home_team="Oklahoma Sooners"), chips)
    assert longhorns["scores"] == (27, 13)
    # One team matching is not a match.
    assert mod.match_chip(_rec(away_team="Texas Longhorns", home_team="Baylor Bears"), chips) == (None, "no_chip_match")


def test_two_equally_good_chips_are_refused_as_ambiguous():
    chips = mod.index_chips([_chip(), _chip(away_score=3, home_score=0)])["ncaaf"]
    assert mod.match_chip(_rec(), chips) == (None, "ambiguous_chip_match")


def test_a_prefix_must_end_at_a_word_boundary():
    chips = mod.index_chips([_chip("Army", "Navy")])["ncaaf"]
    assert mod.match_chip(_rec(away_team="Armyish Knights", home_team="Navy Midshipmen"), chips) == (None, "no_chip_match")


def test_a_game_from_another_board_date_is_named_not_counted_as_unmatched():
    # 2026-09-12's ledger held Missouri @ Kansas at 00:00Z -- Friday 7 PM Central.
    friday = _rec(key="fri", event_id="fri", commence_time="2026-09-12T00:00:00Z",
                  away_team="Missouri Tigers", home_team="Kansas Jayhawks")
    # A 9:30 PM Central kickoff is 02:30Z the NEXT day and still belongs to 09-12.
    late = _rec(key="late", event_id="late", commence_time="2026-09-13T02:30:00Z")
    result = mod.settle([friday, late], [_chip()], board_date="2026-09-12")
    assert result["ungraded"] == {"not_on_board_date": 1}
    assert sum(1 for r in result["rows"] if r["result"]) == 1
    # Without a board date the same row falls to the honest join failure.
    assert mod.settle([friday], [_chip()])["ungraded"] == {"no_chip_match": 1}


def test_settle_counts_every_published_bet_once_and_names_what_it_could_not_grade():
    records = [
        _rec(),  # in-play spread: 27-13 covers -6.5 -> win at +107
        _rec(key="k1b", bookmaker="draftkings", price=-111, captured_at="2026-09-12T18:44:05Z"),  # later best book
        _rec(key="k2", market="totals", side="over", line=47.5, game_state="pregame",
             quote_seen_age_seconds=100.0, price=-110),  # 40 total -> loss
        _rec(key="k3", market="player_pass_yds", player_name="QB"),
        _rec(key="k4", segment="h1", market="h2h", side="away", line=None),
        _rec(key="k5", event_id="other", away_team="Army Black Knights", home_team="Navy Midshipmen"),
        _rec(key="k6", event_id="live", away_team="Ohio State Buckeyes", home_team="Michigan Wolverines"),
        _rec(key="k7", event_id="neg", ev_pct=-0.5),
    ]
    chips = [_chip(), _chip("Ohio State", "Michigan", 7, 7, state="live")]
    result = mod.settle(records, chips, sport="ncaaf", board_date="2026-09-12")
    assert len(result["rows"]) == 6
    assert result["skipped"] == {"duplicate_market_later_sighting": 1, "not_positive_ev": 1}
    assert result["ungraded"] == {
        "market_not_gradeable_from_score": 1,
        "segment_not_full_game": 1,
        "no_chip_match": 1,
        "game_not_final": 1,
    }
    graded = {(r["phase"], r["result"]): r["pnl"] for r in result["rows"] if r["result"]}
    assert graded[("in_play", "win")] == pytest.approx(1.07)
    assert graded[("pregame", "loss")] == -1.0


def test_dedupe_keeps_the_earliest_sighting_whatever_the_input_order():
    later = _rec(key="k1b", bookmaker="draftkings", price=-111, captured_at="2026-09-12T18:44:05Z")
    (row,) = mod.settle([later, _rec()], [_chip()])["rows"]
    assert row["book"] == "prophetx"
    assert mod.settle([later, _rec()], [], dedupe_markets=False)["skipped"] == {}


def test_summarize_keeps_ungraded_rows_in_n_but_not_in_roi_and_counts_games():
    result = mod.settle(
        [
            _rec(),
            _rec(key="k2", market="totals", side="under", line=47.5, price=-110),  # 40 total -> win, SAME game
            _rec(key="k3", event_id="pst", away_team="Penn State Nittany Lions", home_team="Temple Owls",
                 market="h2h", side="away", line=None, price=-500),  # a SECOND game
            _rec(key="k5", event_id="other", away_team="Army Black Knights", home_team="Navy Midshipmen"),
        ],
        [_chip(), _chip("Penn State", "Temple", 27, 9)],
    )
    (cell,) = mod.summarize(result["rows"], ["phase"])
    assert (cell["n"], cell["graded"], cell["games"], cell["w_l_p"]) == (4, 3, 2, "3-0-0")
    # `summarize` publishes units to 3 decimals.
    assert cell["units"] == pytest.approx(1.07 + 100 / 110 + 0.2, abs=5e-4)


def test_main_reads_local_files_and_emits_every_table(tmp_path, capsys):
    openings = tmp_path / "openings.jsonl"
    openings.write_text("\n".join(json.dumps(r) for r in [_rec(), {"bad": "row"}]) + "\nnot json\n", encoding="utf-8")
    chips = tmp_path / "chips.json"
    chips.write_text(json.dumps({"chips": [_chip(), _chip("A", "B", state="live")]}), encoding="utf-8")
    code = mod.main(["--date", "2026-09-12", "--sport", "ncaaf", "--openings-file", str(openings),
                     "--chips-file", str(chips), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert (payload["records_in"], payload["chips"], payload["finals"]) == (2, 2, 1)
    assert set(payload["tables"]) == {"phase", "phase_x_age", "phase_x_book", "phase_x_market"}
    phase = payload["tables"]["phase"][0]
    assert (phase["w_l_p"], phase["games"]) == ("1-0-0", 1)


def test_main_refuses_to_fetch_without_a_token(monkeypatch, capsys):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    assert mod.main(["--date", "2026-09-12"]) == 2
    assert "ADMIN_TOKEN" in capsys.readouterr().err


def test_window_is_decided_by_the_sighting_clock_and_a_boundary_starts_the_later_window():
    # 2026-09-12's live-odds-worker regimes, given out of order: order must not matter.
    boundaries = [mod._parse_ts("2026-09-13T00:14:31Z"), mod._parse_ts("2026-09-12T22:34:15Z")]
    assert mod.window_of("2026-09-12T22:34:14Z", boundaries) == "w0"
    assert mod.window_of("2026-09-12T22:34:15Z", boundaries) == "w1"
    assert mod.window_of("2026-09-13T00:14:30Z", boundaries) == "w1"
    assert mod.window_of("2026-09-13T00:14:31Z", boundaries) == "w2"
    assert mod.window_of("not a time", boundaries) == "unknown_time"
    assert mod.window_of(None, boundaries) == "unknown_time"
    assert mod.window_of("2026-09-12T22:34:14Z", []) == "all"
    assert mod.window_legend(boundaries) == [
        "w0: before 2026-09-12T22:34:15Z",
        "w1: 2026-09-12T22:34:15Z to 2026-09-13T00:14:31Z",
        "w2: from 2026-09-13T00:14:31Z",
    ]


def test_a_bet_stays_in_the_window_of_its_earliest_sighting():
    # The same market re-sighted at a later best book, after the boundary, is
    # still the decision published before it.
    boundary = [mod._parse_ts("2026-09-12T18:40:00Z")]
    later = _rec(key="k1b", bookmaker="draftkings", price=-111, captured_at="2026-09-12T18:44:05Z")
    (row,) = mod.settle([later, _rec()], [_chip()], split_at=boundary)["rows"]
    assert (row["book"], row["window"]) == ("prophetx", "w0")
    (unsplit,) = mod.settle([_rec()], [_chip()])["rows"]
    assert unsplit["window"] == "all"


def test_main_split_at_adds_the_window_tables_and_names_the_boundaries(tmp_path, capsys):
    openings = tmp_path / "openings.jsonl"
    openings.write_text("\n".join(json.dumps(r) for r in [
        _rec(),  # 18:34:57Z -> w0, 27-13 covers -6.5
        _rec(key="k2", event_id="pst", away_team="Penn State Nittany Lions", home_team="Temple Owls",
             market="h2h", side="away", line=None, price=-500, captured_at="2026-09-12T23:00:00Z"),  # w1, wins
    ]) + "\n", encoding="utf-8")
    chips = tmp_path / "chips.json"
    chips.write_text(json.dumps({"chips": [_chip(), _chip("Penn State", "Temple", 27, 9)]}), encoding="utf-8")
    code = mod.main(["--date", "2026-09-12", "--sport", "ncaaf", "--openings-file", str(openings),
                     "--chips-file", str(chips), "--split-at", "2026-09-12T22:34:15Z", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert {"window", "phase_x_window", "phase_x_window_x_age"} <= set(payload["tables"])
    assert payload["windows"] == ["w0: before 2026-09-12T22:34:15Z", "w1: from 2026-09-12T22:34:15Z"]
    assert {(c["window"], c["w_l_p"]) for c in payload["tables"]["window"]} == {("w0", "1-0-0"), ("w1", "1-0-0")}


def test_main_refuses_a_split_time_without_a_zone(capsys):
    assert mod.main(["--date", "2026-09-12", "--split-at", "2026-09-12 22:34:15"]) == 2
    assert "--split-at" in capsys.readouterr().err
