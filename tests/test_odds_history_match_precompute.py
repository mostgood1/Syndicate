"""Odds-history matching derives its features once, and scores EXACTLY as before.

Lane `odds-history-match-precompute`, 2026-09-18. cProfile on refresh-worker
`ef3fb857` put 114.0 s of soccer's 133.6 s `_consume_sport` in
`_candidate_odds_history_match_score`: 1,190,510 calls for 260 candidates, each
re-parsing the entry's market key and re-normalising the candidate. The fix
derives each side once. These tests pin:

  1. every score equals the pre-change scorer's, frozen below verbatim, with
     comments stripped (the WHY lives on the new scorer in intelligence.py);
  2. the entry `_candidate_odds_history_state` chooses is the one the
     pre-change scorer would choose;
  3. market keys are parsed O(entries) per enrichment pass, not
     O(candidates x entries);
  4. the per-pass cache holds nothing after the pass, and never serves a
     feature built from another state.
"""

from __future__ import annotations

import itertools

import pytest

from syndicate.features import intelligence
from syndicate.features.intelligence import (
    _GAME_ONLY_ODDS_HISTORY_MARKET_TYPES,
    _GAME_SIDE_MARKETS,
    _ODDS_HISTORY_MARKET_TYPES_BY_GAME_SIDE,
    _candidate_selection_direction,
    _candidate_selection_text,
    _candidate_subject_key,
    _candidate_team_key,
    _expand_mlb_team_abbreviations,
    _normalized_market_text,
    _numeric_hint,
    _parse_odds_history_market_key,
    _safe_text,
)


# THE PRE-CHANGE SCORER, frozen verbatim from `syndicate/features/intelligence.py`
# at 2012007f (comments stripped). It is the specification the new scorer must
# match exactly; do not "fix" it here.
def _reference_score(candidate: dict[str, Any], market_key: Any, state: Mapping[str, Any]) -> float:
    parsed_key = _parse_odds_history_market_key(market_key)
    if not parsed_key:
        return 0.0

    score = 0.0
    candidate_matchup = _normalized_market_text(_safe_text(candidate.get("matchup"), ""))
    candidate_market = _normalized_market_text(_safe_text(candidate.get("market"), ""))
    subject_source = _candidate_subject_key(candidate) or candidate.get("subject_key") or candidate.get("player_name") or candidate.get("entity")
    candidate_subject = _normalized_market_text(_safe_text(subject_source, ""))
    candidate_team = _normalized_market_text(_safe_text(_candidate_team_key(candidate), ""))
    expanded_team_names: list[str] = []
    if _normalized_market_text(_safe_text(candidate.get("sport_slug"), candidate.get("sport"))) == "mlb":
        expanded_team_names = [
            _normalized_market_text(name)
            for name in (
                *_expand_mlb_team_abbreviations(_safe_text(candidate.get("matchup"), "")),
                *_expand_mlb_team_abbreviations(_safe_text(_candidate_team_key(candidate), "")),
            )
        ]
    candidate_selection = _candidate_selection_text(candidate)
    candidate_selection_direction = _candidate_selection_direction(candidate)
    candidate_selection_hint = "over" if candidate_selection_direction > 0 else "under" if candidate_selection_direction < 0 else ""
    entry_event = " ".join(
        _safe_text(parsed_key.get(field), "")
        for field in ("event_key", "event_id", "matchup", "home_team", "away_team", "player_name", "player_key", "team", "team_key")
    ).strip()
    entry_market = _safe_text(parsed_key.get("market"), "")
    entry_selection = _safe_text(parsed_key.get("selection"), "")
    entry_book = _safe_text(parsed_key.get("bookmaker") or parsed_key.get("book"), "")

    candidate_type_text = _safe_text(candidate.get("candidate_type"), "")
    if candidate_type_text in ("prop", "steam") and entry_market.strip().lower() in _GAME_ONLY_ODDS_HISTORY_MARKET_TYPES:
        candidate_market_key = _normalized_market_text(_safe_text(candidate.get("market_key"), ""))
        if candidate_type_text == "steam" and candidate_market_key in _GAME_SIDE_MARKETS:
            entry_team_names = [
                _normalized_market_text(_safe_text(parsed_key.get(field), ""))
                for field in ("home_team", "away_team", "team", "team_key")
            ]
            entry_team_names = [name for name in entry_team_names if name]
            if not candidate_subject or not any(name in candidate_subject for name in entry_team_names):
                return 0.0
            if entry_market.strip().lower() not in _ODDS_HISTORY_MARKET_TYPES_BY_GAME_SIDE.get(candidate_market_key, set()):
                return 0.0
        elif not candidate_subject or candidate_subject not in entry_event:
            return 0.0

    for value in (candidate_matchup, candidate_subject, candidate_team, candidate_selection, *expanded_team_names):
        if not value or not entry_event:
            continue
        if value == entry_event or value in entry_event or entry_event in value:
            score += 2.0

    if candidate_market and entry_market:
        if candidate_market == entry_market or candidate_market in entry_market or entry_market in candidate_market:
            score += 3.0

    if candidate_selection and entry_selection:
        if candidate_selection == entry_selection or candidate_selection in entry_selection or entry_selection in candidate_selection:
            score += 2.5
    if candidate_selection_hint and entry_selection and candidate_selection_hint in entry_selection:
        score += 1.0

    if entry_book and _normalized_market_text(_safe_text(candidate.get("book"), _safe_text(candidate.get("bookmaker"), ""))):
        candidate_book = _normalized_market_text(_safe_text(candidate.get("book"), _safe_text(candidate.get("bookmaker"), "")))
        if candidate_book == entry_book or candidate_book in entry_book or entry_book in candidate_book:
            score += 0.5

    candidate_line = _numeric_hint(candidate.get("line"))
    state_line = _numeric_hint(state.get("last_line"))
    if candidate_line is not None and state_line is not None:
        score += max(0.0, 1.5 - min(abs(candidate_line - state_line), 1.5))

    return score


# --------------------------------------------------------------------------
# A grid that reaches every rule: prop / steam (player and game) / game / MLB
# abbreviations / soccer names, against game, prop, garbage and empty keys,
# with and without lines and books.
# --------------------------------------------------------------------------

CANDIDATES = [
    {"candidate_type": "prop", "matchup": "COL @ MIL", "market": "pitcher strikeouts", "name": "OVER Tomoyuki Sugano",
     "pick": "OVER Tomoyuki Sugano", "line": "3.5", "sport_slug": "mlb", "book": "DraftKings"},
    {"candidate_type": "prop", "matchup": "NYY @ BOS", "market": "batter hits", "name": "Aaron Judge over 1.5 hits",
     "pick": "Over", "line": 1.5, "sport_slug": "mlb", "team": "NYY"},
    {"candidate_type": "game", "matchup": "COL @ MIL", "market": "Moneyline", "pick": "Home ML", "name": "Home ML",
     "line": "-258", "sport_slug": "mlb", "team_key": "MIL", "market_key": "moneyline"},
    {"candidate_type": "game", "matchup": "LAD @ CHC", "market": "Total", "pick": "Over 8.5", "name": "Over 8.5",
     "line": 8.5, "sport": "mlb", "market_key": "total", "bookmaker": "fanduel"},
    {"candidate_type": "steam", "matchup": "SSF @ PT", "market": "Shots · Steam", "name": "Gage Guerra Shots steam move",
     "pick": "Gage Guerra steam move", "selection": "Gage Guerra steam move", "subject_key": "gage guerra",
     "player_name": "Gage Guerra", "entity": "Gage Guerra", "line": "2.5", "sport_slug": "soccer"},
    {"candidate_type": "steam", "matchup": "SSF @ PT", "market": "Moneyline · Steam", "name": "San Francisco FC steam move",
     "pick": "San Francisco FC steam move", "subject_key": "san francisco fc", "player_name": "San Francisco FC",
     "entity": "San Francisco FC", "line": "-120", "market_key": "moneyline", "sport_slug": "soccer"},
    {"candidate_type": "steam", "matchup": "WSH @ PHI", "market": "Total · Steam", "name": "philadelphia phillies total steam move",
     "subject_key": "philadelphia phillies total steam move", "market_key": "total", "line": 9.0, "sport_slug": "mlb"},
    {"candidate_type": "game", "matchup": "Arsenal vs Chelsea", "market": "Spread", "pick": "Arsenal -0.5",
     "name": "Arsenal -0.5", "line": -0.5, "sport_slug": "soccer", "team": "Arsenal", "book": "bet365"},
    {"candidate_type": "prop", "matchup": "", "market": "", "name": "", "pick": ""},
    {},
]

ENTRIES = [
    ("event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=h2h|bookmaker=draftkings", {"last_line": -258.0}),
    ("event_id=abc|home_team=Milwaukee Brewers|away_team=Colorado Rockies|market=totals|selection=Over|bookmaker=fanduel", {"last_line": 8.0}),
    ("event_id=abc|player_name=Tomoyuki Sugano|market=pitcher_strikeouts|selection=Over|bookmaker=draftkings", {"last_line": 3.5}),
    ("event_id=nyybos|player_name=Aaron Judge|market=batter_hits|selection=Over|bookmaker=draftkings", {"last_line": 1.5}),
    ("event_id=lc|home_team=Chicago Cubs|away_team=Los Angeles Dodgers|market=totals|selection=Over|bookmaker=fanduel", {"last_line": 8.5}),
    ("event_id=lc|home_team=Chicago Cubs|away_team=Los Angeles Dodgers|market=h2h|selection=Chicago Cubs", {"last_line": -130}),
    ("event_id=52ee1a58|home_team=New York City FC|away_team=Toronto FC|market=spreads|bookmaker=draftkings", {"last_line": -0.25}),
    ("event_id=abc|player_name=Gage Guerra|market=player_shots_on_target|bookmaker=draftkings", {"last_line": 2.5}),
    ("event_id=xyz|home_team=San Francisco FC|away_team=Portland Timbers|market=h2h|bookmaker=draftkings", {"last_line": -120.0}),
    ("event_id=xyz|home_team=San Francisco FC|away_team=Portland Timbers|market=totals|bookmaker=draftkings", {"last_line": 2.5}),
    ("event_id=wp|home_team=Philadelphia Phillies|away_team=Washington Nationals|market=totals|selection=Under", {"last_line": 9.5}),
    ("event_key=arsenal chelsea|home_team=Arsenal|away_team=Chelsea|market=spreads|selection=Arsenal|book=bet365", {"last_line": "-0.5"}),
    ("matchup=Arsenal vs Chelsea|market=h2h|selection=Draw", {}),
    ("no equals sign here", {"last_line": 1.0}),
    ("", {"last_line": None}),
]


def _ids(prefix, n):
    return [f"{prefix}{i}" for i in range(n)]


@pytest.mark.parametrize("ci", range(len(CANDIDATES)), ids=_ids("c", len(CANDIDATES)))
def test_every_score_equals_the_pre_change_scorer(ci):
    candidate = CANDIDATES[ci]
    for market_key, state in ENTRIES:
        new = intelligence._candidate_odds_history_match_score(candidate, market_key, state)
        ref = _reference_score(candidate, market_key, state)
        assert new == ref, (candidate, market_key, new, ref)
        # And the hot path's pieces, used directly, agree too.
        hot = intelligence._odds_history_match_score_from_features(
            intelligence._candidate_odds_history_match_features(candidate),
            intelligence._odds_history_entry_match_features_cached(market_key, state),
        )
        assert hot == ref, (candidate, market_key, hot, ref)
    intelligence._ODDS_HISTORY_ENTRY_FEATURES.clear()


def test_the_grid_is_not_trivial():
    """A grid where every score is 0 would pass the equality test vacuously."""
    scores = [_reference_score(c, k, s) for c, (k, s) in itertools.product(CANDIDATES, ENTRIES)]
    assert sum(1 for x in scores if x > 0) >= 15
    assert len({round(x, 6) for x in scores}) >= 6


def _index():
    markets = {key: dict(state) for key, state in ENTRIES if key}
    return intelligence._build_odds_history_player_index({"markets": markets})


def _chosen_with(scorer, candidate, index, monkeypatch):
    """`_candidate_odds_history_state`, with its scoring swapped for `scorer`."""
    with monkeypatch.context() as m:
        m.setattr(intelligence, "_candidate_odds_history_match_features", lambda c: c)
        m.setattr(intelligence, "_odds_history_entry_match_features_cached", lambda k, s: (k, s))
        m.setattr(intelligence, "_odds_history_match_score_from_features", lambda c, e: scorer(c, *e))
        return intelligence._candidate_odds_history_state(candidate, index)


@pytest.mark.parametrize("ci", range(len(CANDIDATES)), ids=_ids("c", len(CANDIDATES)))
def test_the_chosen_entry_is_the_one_the_pre_change_scorer_chooses(ci, monkeypatch):
    candidate = CANDIDATES[ci]
    index = _index()
    new_key, new_state = intelligence._candidate_odds_history_state(candidate, index)
    ref_key, ref_state = _chosen_with(_reference_score, candidate, index, monkeypatch)
    assert new_key == ref_key
    assert new_state is ref_state
    intelligence._ODDS_HISTORY_ENTRY_FEATURES.clear()


def test_some_candidates_do_choose_an_entry():
    """The choice test above is vacuous if nothing is ever chosen."""
    index = _index()
    chosen = [intelligence._candidate_odds_history_state(c, index)[0] for c in CANDIDATES]
    assert sum(1 for key in chosen if key) >= 5
    intelligence._ODDS_HISTORY_ENTRY_FEATURES.clear()


# --------------------------------------------------------------------------
# The cost the lane exists to remove
# --------------------------------------------------------------------------


def _soccer_pass(n_candidates, n_entries):
    """Game candidates whose event bucket misses, forcing the full-scan fallback
    for every one of them -- the production soccer shape."""
    markets = {
        f"event_id=e{j}|home_team=Home {j}|away_team=Away {j}|market=h2h|selection=Home {j}|bookmaker=book{j % 7}": {"last_line": 100 + j}
        for j in range(n_entries)
    }
    candidates = [
        {"candidate_type": "game", "sport_slug": "soccer", "matchup": f"Unmatched {i} vs Nobody {i}", "market": "Moneyline",
         "pick": f"Unmatched {i}", "name": f"Unmatched {i}", "line": 100 + i}
        for i in range(n_candidates)
    ]
    return candidates, {"soccer": {"markets": markets}}


def test_market_keys_are_parsed_once_per_entry_not_once_per_pair(monkeypatch):
    candidates, history = _soccer_pass(n_candidates=20, n_entries=50)
    real = intelligence._parse_odds_history_market_key
    calls = {"n": 0}

    def counted(key):
        calls["n"] += 1
        return real(key)

    monkeypatch.setattr(intelligence, "_parse_odds_history_market_key", counted)
    intelligence._enrich_candidates_with_odds_history(candidates, history)
    # Index build (50) + features once per entry (50). Was 20 x 50 = 1,000 more.
    assert calls["n"] <= 2 * 50, calls


def test_the_cache_is_empty_after_the_pass_and_never_serves_another_states_features():
    candidates, history = _soccer_pass(n_candidates=3, n_entries=5)
    intelligence._enrich_candidates_with_odds_history(candidates, history)
    assert intelligence._ODDS_HISTORY_ENTRY_FEATURES == {}

    key = "event_id=e1|home_team=Home|away_team=Away|market=h2h"
    first = intelligence._odds_history_entry_match_features_cached(key, {"last_line": 1.0})
    second = intelligence._odds_history_entry_match_features_cached(key, {"last_line": 2.0})
    assert (first["state_line"], second["state_line"]) == (1.0, 2.0)
    intelligence._ODDS_HISTORY_ENTRY_FEATURES.clear()


def test_the_cache_is_cleared_even_when_the_pass_raises(monkeypatch):
    candidates, history = _soccer_pass(n_candidates=2, n_entries=3)

    def boom(*_a, **_k):
        intelligence._odds_history_entry_match_features_cached("event_id=x|market=h2h", {})
        raise RuntimeError("mid-pass")

    monkeypatch.setattr(intelligence, "_enrich_candidates_with_odds_history_pass", boom)
    with pytest.raises(RuntimeError, match="mid-pass"):
        intelligence._enrich_candidates_with_odds_history(candidates, history)
    assert intelligence._ODDS_HISTORY_ENTRY_FEATURES == {}
