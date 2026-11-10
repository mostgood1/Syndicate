"""NBA prop rows whose BOOK spelling differs from the ENGINE's get the same model fields
`[2026-11-10, lane nba-prop-engine-name-join]`.

Measured on the fleet's 11-04..11-09 book grids with fleet code 564f8dbde: 15 player-slates, 610 prop rows
missed the pregame sim only by spelling (Herb/Herbert Jones, Paul Reed Jr/Paul Reed, C.J./CJ McCollum,
Carlton/Bub Carrington, ...). Every one resolves uniquely under the engine key, and 0 were ambiguous. Served
2026-11-10 03:20Z: Herb Jones's 20 live rows had a Live proj. but no sim_projection, model edge, face, side or
recent form, while teammate Saddiq Bey's row carried all of them.

The fixture reuses the producer's real file shapes (`test_nba_layer2_projections`) on disk, and the tests drive
the entry point every grid producer calls (`board_enrichment.attach_projections` -> `attach_nba_prop_projections`).
Every behaviour test has an OFF arm, the pre-fix code path, which must differ (off != on).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from syndicate.features.shared import nba_projections as P
from syndicate.features.shared import nba_player_identity as I
from syndicate.features.shared.nba_game_projections import load_nba_game_projections

D = "2026-11-09"
HOME, AWAY = "Golden State Warriors", "New Orleans Pelicans"
HOME2, AWAY2 = "Los Angeles Clippers", "Detroit Pistons"
COMMENCE = f"{D}T23:10:00Z"
COMMENCE2 = f"{D}T23:40:00Z"


def _ladder(counts: dict[int, int]) -> dict:
    n = sum(counts.values())
    ladder = []
    for t in sorted(counts):
        hit = sum(c for v, c in counts.items() if v >= t)
        ladder.append({"total": t, "hitCount": hit, "hitProb": round(hit / n, 4), "exactCount": counts[t], "exactProb": round(counts[t] / n, 4)})
    mean = sum(v * c for v, c in counts.items()) / n
    return {"simCount": n, "mean": round(mean, 3), "ladder": ladder, "ladderShape": "exact"}


# 10 draws: P(>= 10) = 0.6, mean 10.3
_PTS = {6: 1, 7: 1, 8: 2, 10: 2, 12: 2, 14: 1, 16: 1}


def _player(name: str, pid: str) -> dict:
    ladder = _ladder(_PTS)
    return {"player_name": name, "player_id": pid, "min_mean": 28.0, "pts_mean": ladder["mean"], "prop_ladders": {"pts": ladder}}


def _write(root: Path, games: list[dict]) -> None:
    processed = root / "data" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    cols = ["date", "game_id", "home_team", "visitor_team", "commence_time", "home_tri", "away_tri", "pred_margin", "pred_total"]
    with (processed / f"game_cards_{D}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=cols)
        writer.writeheader()
        writer.writerow({"date": D, "game_id": "401", "home_team": HOME, "visitor_team": AWAY, "commence_time": COMMENCE, "home_tri": "GSW", "away_tri": "NOP", "pred_margin": 3.0, "pred_total": 228.0})
        writer.writerow({"date": D, "game_id": "402", "home_team": HOME2, "visitor_team": AWAY2, "commence_time": COMMENCE2, "home_tri": "LAC", "away_tri": "DET", "pred_margin": 1.0, "pred_total": 224.0})
    (processed / f"cards_sim_detail_{D}.json").write_text(json.dumps({"date": D, "games": games}), encoding="utf-8")


def _game(home_tri: str, away_tri: str, home: list[dict], away: list[dict]) -> dict:
    return {"home_tri": home_tri, "away_tri": away_tri, "sim": {"players": {"home": home, "away": away}, "missing_prop_players": {"home": [], "away": []}}}


@pytest.fixture
def nba_root(tmp_path, monkeypatch):
    root = tmp_path / "nba_source"
    monkeypatch.setenv("SYNDICATE_NBA_SOURCE_ROOT", str(root))
    monkeypatch.setenv("SYNDICATE_DATA_ROOT", str(tmp_path / "unused_data_root"))
    _write(root, [
        _game("GSW", "NOP",
              home=[_player("Stephen Curry", "201939"), _player("Gary Payton II", "1627780"), _player("Gary Payton", "1")],
              away=[_player("Herbert Jones", "1630529"), _player("Saddiq Bey", "1630180"), _player("CJ McCollum", "203468")]),
        _game("LAC", "DET",
              home=[_player("Derrick Jones Jr.", "1627884")],
              away=[_player("Paul Reed", "1630194"), _player("Ronald Holland II", "1641842")]),
    ])
    return root


def _prop(player: str, market: str = "player_points", *, line=9.5, home=HOME, away=AWAY, commence=COMMENCE) -> dict:
    return {
        "sport": "nba", "kind": "prop", "event_id": "evt", "market": market, "segment": "full",
        "player_name": player, "line": line, "home_team": home, "away_team": away,
        "commence_time": commence, "sides": ["over", "under"], "consensus": {"over": -110, "under": -110},
    }


def _attach(rows: list[dict]) -> dict:
    return P.attach_nba_prop_projections(rows, P.load_nba_prop_projections(D, load_nba_game_projections(D)))


@pytest.fixture
def off(monkeypatch):
    """The pre-fix code path: no resolution is stamped, so every join reads the book's own spelling."""
    monkeypatch.setattr(P, "stamp_engine_player_names", lambda grid, index: {})


# ------------------------------------------------------------------ the resolver


@pytest.mark.parametrize("book, engine", [
    ("Herb Jones", "Herbert Jones"),
    ("Paul Reed Jr", "Paul Reed"),
    ("C.J. McCollum", "CJ McCollum"),
    ("Carlton Carrington", "Bub Carrington"),
    ("Derrick Jones", "Derrick Jones Jr."),
    ("Ron Holland", "Ronald Holland II"),
    ("R.J. Barrett", "RJ Barrett"),
    ("A.J. Green", "AJ Green"),
])
def test_each_measured_split_resolves_to_the_engine_name(book, engine):
    assert I.resolve_engine_name(book, [engine, "Saddiq Bey"]) == (engine, I.ALIAS)


def test_an_exact_name_is_never_resolved():
    assert I.resolve_engine_name("Saddiq Bey", ["Saddiq Bey"]) == (None, I.EXACT)
    assert I.resolve_engine_name("Gary Payton II", ["Gary Payton II", "Gary Payton"]) == (None, I.EXACT)


def test_an_ambiguous_engine_key_resolves_to_no_one():
    assert I.resolve_engine_name("Gary Payton III", ["Gary Payton II", "Gary Payton"]) == (None, I.AMBIGUOUS)


def test_a_player_the_engine_does_not_have_stays_absent():
    assert I.resolve_engine_name("Bobby Portis", ["Herbert Jones"]) == (None, I.ABSENT)
    assert I.resolve_engine_name("", ["Herbert Jones"]) == (None, I.NO_NAME)


def test_the_resolver_key_is_the_live_joins_key():
    """One definition: the pregame stamp and the live join can never disagree about who a player is."""
    from syndicate.features.shared.live_projection_join import _canonical_player

    for name in ("Herb Jones", "Nikola Jokić", "Paul Reed Jr.", "C.J. McCollum"):
        assert I.engine_key(name) == _canonical_player(name)


# ------------------------------------------------------------------ the choke point: the pregame projection


def test_herb_jones_gains_the_projection_probability_and_edge(nba_root):
    rows = [_prop("Herb Jones"), _prop("Saddiq Bey")]
    cov = _attach(rows)
    herb, bey = rows
    assert herb["engine_player_name"] == "Herbert Jones"
    assert "engine_player_name" not in bey, "an exact row is never stamped"
    for row in rows:
        p = row["projection"]
        assert p["projected"] == pytest.approx(10.3)
        assert p["model_prob_over"] is not None
        assert p["edge_vs_market_pct"] is not None
    # The two players share one ladder in the fixture, so the numbers must be IDENTICAL: same join, same math.
    assert herb["projection"]["model_prob_over"] == bey["projection"]["model_prob_over"]
    assert cov["engine_name_resolution"]["alias_rows"] == 1
    assert cov["engine_name_resolution"]["alias_players"] == {"Herb Jones": "Herbert Jones"}


def test_off_is_not_on_herb_jones_without_the_stamp(nba_root, off):
    rows = [_prop("Herb Jones"), _prop("Saddiq Bey")]
    cov = _attach(rows)
    herb, bey = rows
    assert "projection" not in herb and "engine_player_name" not in herb
    assert bey["projection"]["model_prob_over"] is not None
    assert cov["unprojected_by_reason"] == {"player not in the NBA sim for this game": 1}


@pytest.mark.parametrize("book, home, away, commence", [
    ("Paul Reed Jr", HOME2, AWAY2, COMMENCE2),
    ("C.J. McCollum", HOME, AWAY, COMMENCE),
    ("Derrick Jones", HOME2, AWAY2, COMMENCE2),
    ("Ron Holland", HOME2, AWAY2, COMMENCE2),
])
def test_every_measured_split_is_priced_on_and_unpriced_off(nba_root, monkeypatch, book, home, away, commence):
    on = [_prop(book, home=home, away=away, commence=commence)]
    _attach(on)
    assert on[0]["projection"]["model_prob_over"] is not None
    with monkeypatch.context() as m:
        m.setattr(P, "stamp_engine_player_names", lambda grid, index: {})
        off_rows = [_prop(book, home=home, away=away, commence=commence)]
        _attach(off_rows)
    assert "projection" not in off_rows[0]


def test_ambiguity_refuses_and_is_counted(nba_root):
    rows = [_prop("Gary Payton III")]
    cov = _attach(rows)
    assert "projection" not in rows[0] and "engine_player_name" not in rows[0]
    assert cov["engine_name_resolution"]["ambiguous_rows"] == 1
    assert cov["engine_name_resolution"]["ambiguous_players"] == ["Gary Payton III"]


def test_an_exact_name_never_takes_the_fallback(nba_root):
    rows = [_prop("Gary Payton II")]
    _attach(rows)
    assert "engine_player_name" not in rows[0]
    assert rows[0]["projection"]["model_prob_over"] is not None


def test_a_simmed_game_only_resolves_to_its_own_players(nba_root):
    """'Derrick Jones' on GSW@NOP must not borrow LAC@DET's Derrick Jones Jr.: the GSW@NOP sim exists, and
    a book's prop for a game is about a player in that game."""
    rows = [_prop("Derrick Jones", home=HOME, away=AWAY, commence=COMMENCE)]
    cov = _attach(rows)
    assert "engine_player_name" not in rows[0] and "projection" not in rows[0]
    assert cov["engine_name_resolution"]["alias_rows"] == 0


def test_a_market_with_no_ladder_is_still_stamped(nba_root):
    """A double-double has no ladder (joint stat), but its face and side read the same resolution."""
    rows = [_prop("Herb Jones", market="player_double_double", line=None)]
    _attach(rows)
    assert rows[0]["engine_player_name"] == "Herbert Jones"
    assert "projection" not in rows[0]


def test_the_board_entry_point_runs_the_stamp(nba_root):
    """`board_enrichment.attach_projections` is what all three grid producers call."""
    from syndicate.features.shared import board_enrichment

    rows = [_prop("Herb Jones")]
    board_enrichment.attach_projections(rows, sport="nba", selected_date=D)
    assert rows[0]["engine_player_name"] == "Herbert Jones"
    assert rows[0]["projection"]["model_prob_over"] is not None


# ------------------------------------------------------------------ the readers downstream of the stamp


@pytest.fixture
def id_index(monkeypatch):
    from syndicate.blueprints import home
    from syndicate.features.shared import player_headshots as H

    monkeypatch.setitem(home._BASKETBALL_PLAYER_ID_CACHE, "nba", {
        ("NOP", "herbert jones"): 1630529, ("", "herbert jones"): 1630529,
        ("NOP", "saddiq bey"): 1630180, ("", "saddiq bey"): 1630180,
    })
    H._basketball_teams.cache_clear()
    yield
    H._basketball_teams.cache_clear()


def test_the_face_reads_the_engine_name(id_index):
    from syndicate.features.shared.player_headshots import headshot_url

    stamped = {**_prop("Herb Jones"), "engine_player_name": "Herbert Jones"}
    assert headshot_url(stamped) == "https://cdn.nba.com/headshots/nba/latest/1040x760/1630529.png"
    assert headshot_url(_prop("Herb Jones")) is None  # off: the book's spelling is not in player_ids.csv


def test_the_side_reads_the_engine_name(id_index):
    from syndicate.features.shared.player_headshots import player_side

    stamped = {**_prop("Herb Jones"), "engine_player_name": "Herbert Jones"}
    assert player_side(stamped) == player_side(_prop("Saddiq Bey")) == "away"
    assert player_side(_prop("Herb Jones")) is None  # off


def test_the_evidence_subject_reads_the_engine_name():
    from syndicate.features.shared.prop_evidence.contract import PropSubject

    stamped = PropSubject.from_board_row({**_prop("Herb Jones"), "engine_player_name": "Herbert Jones"}, selected_date=D)
    plain = PropSubject.from_board_row(_prop("Herb Jones"), selected_date=D)
    assert stamped.player_name == "Herbert Jones" and plain.player_name == "Herb Jones"


def test_the_stamp_reaches_the_layer2_candidate_and_card():
    from syndicate.features.shared.layer2_board import build_layer2_rows, layer2_rows_to_board_cards

    def grid_row(**extra):
        row = {
            # A future tip: a past one is settled and never reaches `opportunities`.
            **_prop("Herb Jones", commence="2099-01-01T00:00:00Z"), "books_quoting": 2, "cells": {},
            "projection": {"edge_vs_market_pct": 6.0, "projected": 10.3, "model_prob_over": 0.6, "side": "over"},
            "best": {
                "over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
                "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0},
            },
        }
        row.update(extra)
        return row

    on = list(build_layer2_rows([grid_row(engine_player_name="Herbert Jones")]).get("opportunities") or [])
    off = list(build_layer2_rows([grid_row()]).get("opportunities") or [])
    assert on and off, "fixture must produce candidates"
    assert all(c.get("engine_player_name") == "Herbert Jones" for c in on)
    assert all("engine_player_name" not in c for c in off)
    assert all(c["player_name"] == "Herb Jones" for c in on), "the bet's identity keeps the book's spelling"
    cards = layer2_rows_to_board_cards(on)
    assert cards and all(card.get("engine_player_name") == "Herbert Jones" for card in cards)
    assert all(card["player_name"] == "Herb Jones" for card in cards)
    assert [c["pick_id"] for c in cards] == [c["pick_id"] for c in layer2_rows_to_board_cards(off)], (
        "pick_id must not move: the ledger already holds these bets under the book's name")


# ------------------------------------------------------------------ the OUT flag must see the same resolution


@pytest.fixture
def out_feed(monkeypatch, tmp_path):
    """The official report spells him HERBERT JONES; the book prints Herb Jones."""
    from syndicate.features.shared import basketball_props_availability as A
    from syndicate.features.shared import board_enrichment as BE

    monkeypatch.setattr(BE, "_injury_feed_root", lambda sport: tmp_path)
    monkeypatch.setattr(A, "out_players_for_date", lambda **_: {
        "feed_status": "ok", "snapshot_date": D,
        "out": {"HERBERT JONES": {"status": "OUT", "feed_date": D, "team": "NOP"}},
    })


def _priced(player: str, sport: str = "nba", **extra) -> dict:
    return {**_prop(player), "sport": sport, "projection": {"edge_vs_market_pct": 5.0, "edge_vs_line": 1.2}, **extra}


def test_an_out_player_under_the_engine_spelling_loses_his_edge(out_feed):
    from syndicate.features.shared import board_enrichment as BE
    from syndicate.features.shared.basketball_props_availability import player_key

    stamped, unstamped = _priced("Herb Jones", engine_player_name="Herbert Jones"), _priced("Herb Jones")
    summary = BE._flag_out_player_props([stamped, unstamped], sport="nba", selected_date=D)["out_player_props"]
    for row in (stamped, unstamped):
        assert row["player_availability"]["status"] == "OUT"
        assert row["projection"]["edge_vs_market_pct"] is None
    assert summary["rows_flagged"] == summary["rows_flagged_via_engine_name"] == 2
    # OFF: the pre-fix lookup was this key alone, and it misses.
    assert player_key("Herb Jones") != "HERBERT JONES"


def test_off_is_not_on_for_the_out_flag_outside_nba(out_feed):
    """The engine key is NBA's; another basketball sport keeps the exact `player_key` lookup only."""
    from syndicate.features.shared import board_enrichment as BE

    row = _priced("Herb Jones", sport="wnba")
    summary = BE._flag_out_player_props([row], sport="wnba", selected_date=D)["out_player_props"]
    assert "player_availability" not in row and row["projection"]["edge_vs_market_pct"] == 5.0
    assert summary["rows_flagged"] == 0


# ------------------------------------------------------------------ the NBA cards-page board (a sibling join)


def _cards_board(league: str, raw_names: list[str], sim_names: list[str]):
    from syndicate.features.shared import basketball_market_board as board

    sim_players = {"home": [], "away": [{"player_name": n, "pts_mean": 10.3, "pts_sd": 3.0} for n in sim_names]}
    raw = {board._canonical_player_key(n): {"points": {"line": 9.5, "over_odds": -110, "under_odds": -110}} for n in raw_names}
    odds_rows, sim_rows = board.basketball_market_board_rows_for_game(
        game_pk=1, betting={}, prop_recommendations={}, raw_player_props=raw, sim_players=sim_players, league=league)
    return {r["entity"] for r in odds_rows if r.get("market_type") == "prop"}, {r["entity"] for r in sim_rows if r.get("entity")}


def test_cards_board_attributes_the_book_quote_to_the_engine_player():
    odds, priced = _cards_board("nba", ["Herb Jones", "Saddiq Bey"], ["Herbert Jones", "Saddiq Bey"])
    assert odds == priced == {"Herbert Jones", "Saddiq Bey"}


def test_off_is_not_on_for_the_cards_board_outside_nba():
    odds, priced = _cards_board("wnba", ["Herb Jones", "Saddiq Bey"], ["Herbert Jones", "Saddiq Bey"])
    assert odds == priced == {"Saddiq Bey"}, "the pre-fix join: the book's Herb Jones is never attributed"


def test_cards_board_never_borrows_another_players_exact_quotes():
    """Gary Payton has his own exact quotes; Gary Payton II (no quotes of his own) must not take them."""
    odds, _ = _cards_board("nba", ["Gary Payton"], ["Gary Payton", "Gary Payton II"])
    assert odds == {"Gary Payton"}
