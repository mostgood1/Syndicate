"""Confirmed ESPN starters resolve to season rows across name forms (lane soccer-starter-name-match, 2026-10-13).

Measured on 10-09..10-12 (101 matches, 202 confirmed sides, match_box starters vs season rows): exact names resolved
2,058 of 2,222 starters (92.6%), 87 sides all 11; with the fallback 2,130 (95.9%), 123 sides all 11 (2026-10-14,
after the one-word step was removed for a wrong pairing and the short-first-name step added).
"""
from __future__ import annotations

from syndicate.features.soccer.features import lineups as L


def _rows(*names):
    return [{"player_id": f"understat_{i}", "player_name": n} for i, n in enumerate(names)]


def _resolve(rows, *espn):
    return L.resolve_starter_ids(rows, {L._norm_player_name(n) for n in espn})


def test_name_forms_resolve():
    rows = _rows("Eren Sami Dinkci", "Woo-Yeong Jeong", "Lukas Pinckert", "Dayotchanculle Upamecano", "Pape Sarr")
    got = _resolve(rows, "Eren Dinkci", "Jeong Woo-yeong", "Lukas Finn Pinckert", "Dayot Upamecano", "Pape Matar Sarr")
    assert got == {"understat_0", "understat_1", "understat_2", "understat_3", "understat_4"}


def test_exact_names_still_win_and_no_row_is_claimed_twice():
    rows = _rows("Bukayo Saka", "Bukayo Saka Junior")
    assert _resolve(rows, "Bukayo Saka") == {"understat_0"}


def test_two_candidates_refuse_rather_than_guess():
    rows = _rows("Matthew Cash", "Matteo Cash")
    assert _resolve(rows, "Matt Cash") == set()


def test_a_one_word_name_never_matches():
    """10-10 FC Dallas: ESPN's starting goalkeeper "Daniel" is NOT the squad's attacking midfielder Daniel Job
    (both in the same box). A one-word step matched them; it is gone."""
    assert _resolve(_rows("Daniel Job"), "Daniel") == set()


def test_short_and_legal_first_names_with_the_same_surname():
    rows = _rows("Matthew Cash", "Santiago Comesaña", "Mat Ryan")
    assert _resolve(rows, "Matty Cash", "Santi Comesaña", "Mathew Ryan") == {"understat_0", "understat_1", "understat_2"}


def test_html_entities_are_decoded():
    assert L._norm_player_name("Ngal&#039;ayel Mukau") == L._norm_player_name("Ngal'ayel Mukau")


def test_a_shared_surname_alone_never_matches():
    """The Kalulu brothers: a surname step would cross them; there is none."""
    rows = _rows("Pierre Kalulu Kyatengwa")
    assert _resolve(rows, "Joseph Kalulu") == set()


def test_off_is_not_on_exact_matching_alone_misses_these(monkeypatch):
    """Reachability: with no fallback steps the same rows resolve nothing, so the matches above are the
    fallback's doing."""
    rows = _rows("Eren Sami Dinkci", "Woo-Yeong Jeong")
    monkeypatch.setattr(L, "_NAME_FORM_STEPS", ())
    assert _resolve(rows, "Eren Dinkci", "Jeong Woo-yeong") == set()


def test_an_espn_id_pins_the_starter_whatever_the_names():
    """Primeira Liga rows carry ESPN ids; the deduped row keeps the season with the most minutes, so it reads
    "Jonathan Buatu" while ESPN's starter is "Buatu" (10-09..12: Buatu, Gorby, Chissumba, Vinicius Lopes)."""
    rows = [{"player_id": "183070", "player_name": "Jonathan Buatu"}, {"player_id": "1", "player_name": "Other Player"}]
    assert L.resolve_starter_ids(rows, {"buatu"}, {"183070": "buatu"}) == {"183070"}
    assert L.resolve_starter_ids(rows, {"buatu"}) == set()          # off != on: names alone cannot pin a one-word name


def test_an_id_does_not_cross_sources():
    rows = [{"player_id": "understat_183070", "player_name": "Somebody Else"}]
    assert L.resolve_starter_ids(rows, {"buatu"}, {"183070": "buatu"}) == set()


def test_a_single_name_row_matches_the_one_starter_containing_it():
    """Understat 'Gabriel' / ESPN 'Gabriel Magalhaes' (lane soccer-single-name-starters, 2026-10-15)."""
    rows = _rows("Gabriel", "Gabriel Martinelli", "Alisson")
    got = _resolve(rows, "Gabriel Magalhães", "Gabriel Martinelli", "Alisson Becker")
    assert got == {"understat_0", "understat_1", "understat_2"}


def test_single_name_refuses_when_two_starters_contain_the_word():
    rows = _rows("Gabriel")
    assert _resolve(rows, "Gabriel Magalhães", "Gabriel Jesus") == set()


def test_single_name_refuses_when_two_rows_carry_the_word():
    rows = _rows("Gabriel", "Gabriel")
    assert _resolve(rows, "Gabriel Magalhães") == set()


def test_a_one_word_ESPN_name_still_never_matches_a_longer_row():
    """The other direction stays closed (FC Dallas 'Daniel' vs 'Daniel Job')."""
    assert _resolve(_rows("Daniel Job"), "Daniel") == set()
