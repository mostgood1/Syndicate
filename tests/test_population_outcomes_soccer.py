"""`population_outcomes_soccer.SoccerPopulationSettler` -- the soccer `extra_settler`.

Every fixture is REAL and trimmed, never invented:
- `records.jsonl`: recorder rows (`opportunity_population_ledger`), each the earliest sighting
  of its key in the 2026-09-14..18 soccer parts, copied verbatim;
- `soccer_source__la_liga__api__live_state__live_state_2026-09-16.json`: web's file exported
  2026-09-17 with two of its three `match_box` records kept (Barcelona 7-2 Racing Santander,
  Deportivo 0-1 Sevilla);
- `..._2026-09-15.json`: one of three kept (Alavés 0-1 Valencia, 0-0 at half-time).

The two join sides come from different feeds -- OddsAPI names on the rows (`Real Racing Club
de Santander`, `miguel angel sierra ortega`), ESPN names in the box (`Racing Santander`,
`Miguel Sierra`) -- so a passing join is evidence, not a tautology.

Hand-verified against the payload (not against this module):
1. `lamine yamal` anytime scorer -> WIN: the Barcelona roster has Lamine Yamal appeared=True,
   goals=1.0, and `goals` lists his 89' strike.
2. corners over 13.5 -> WIN: `teams.home.stats.Corners` "18" + `teams.away.stats.Corners` "0".
3. Alavés-Valencia first-half draw -> WIN: `home_linescores` [0, 0], `away_linescores` [0, 1].
"""

from __future__ import annotations

import copy
import importlib.util
import inspect
import json
import pathlib
from datetime import datetime, timezone

import pytest

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared import team_aliases
from syndicate.features.shared.population_outcomes_soccer import (
    GRADER_VERSION,
    SoccerPopulationSettler,
    candidate_dates,
    settle_over_under,
    settle_spread,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bucket_search", _ROOT / "scripts" / "bucket_search.py")
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "population_outcomes" / "soccer"
NOW = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)
BARCA = "4a3400b0763bcc367171537f40b27a4f"
DEPOR = "e8d1b34cb3e1f52f67538ad554811b56"
ALAVES = "d6474326396cdd0e300afd0193c7c93d"
BOX_0916 = "soccer_source/la_liga/api/live_state/live_state_2026-09-16.json"


@pytest.fixture(autouse=True)
def _no_team_artifacts(monkeypatch):
    """The derived club maps read team artifacts under `data/`; tests read none of it, so the
    join runs on the fallbacks a checkout without team artifacts has."""
    monkeypatch.setattr(team_aliases, "_soccer_alias_to_name", lambda: {})
    monkeypatch.setattr(team_aliases, "_soccer_alias_by_league", lambda: {})
    monkeypatch.setattr(team_aliases, "_nickname_alias_map", lambda sport: {})


def _fixture_fetch(overrides=None, calls=None):
    def fetch(relative_path):
        if calls is not None:
            calls.append(relative_path)
        if overrides and relative_path in overrides:
            return overrides[relative_path]
        path = FIXTURES / relative_path.replace("/", "__")
        return path.read_text(encoding="utf-8") if path.is_file() else None

    return fetch


def _settler(**kwargs):
    kwargs.setdefault("fetch_export", _fixture_fetch())
    return SoccerPopulationSettler(now=lambda: NOW, **kwargs)


RECORDS = {r["k"]: r for r in bs.parse_records_text((FIXTURES / "records.jsonl").read_text(encoding="utf-8"))}


def _row(key, **shaped_overrides):
    record = RECORDS[key]
    shaped, why = bs.scorecard_record(record)
    assert shaped is not None, why
    shaped.update(shaped_overrides)
    return shaped, mbs.view_from_record(record)


def _settle(key, settler=None, **overrides):
    return (settler or _settler())(*_row(key, **overrides))


# --- goal scorers ---------------------------------------------------------------------------


def test_anytime_scorer_win_for_a_real_goal():
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|lamine yamal|full|yes|") == ("win", None)
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|maguette gueye|full|yes|") == ("win", None)


def test_anytime_scorer_loss_for_a_player_who_played_and_did_not_score():
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|dani olmo|full|yes|") == ("loss", None)


def test_own_goal_scores_for_nobody():
    # Asier Villalibre's 36' own goal counts in Barcelona's 7 but is no goal of his.
    box = json.loads((FIXTURES / BOX_0916.replace("/", "__")).read_text(encoding="utf-8"))["match_box"]["401882871"]
    own = [g for g in box["goals"] if g["own_goal"]]
    assert [g["scorer"] for g in own] == ["Asier Villalibre"]
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|asier villalibre|full|yes|") == ("loss", None)
    assert _settle(f"{BARCA}|player_first_goal_scorer|asier villalibre|full|yes|") == ("loss", None)


def test_player_who_did_not_appear_is_void_not_a_loss():
    # Jules Koundé is in the matchday 23 with appeared=False.
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|jules kounde|full|yes|") == (None, "dnp_void")


def test_a_name_matching_nobody_is_not_a_void():
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|frenkie de jong|full|yes|") == (None, "player_not_in_box")


def test_first_and_last_scorer():
    # Sevilla 1-0: `miguel angel sierra ortega` (OddsAPI) is ESPN's `Miguel Sierra`, 52'.
    assert _settle(f"{DEPOR}|player_first_goal_scorer|miguel angel sierra ortega|full|yes|") == ("win", None)
    # Barcelona-Racing: first goal João Cancelo 8', last Lamine Yamal 89'.
    assert _settle(f"{BARCA}|player_first_goal_scorer|maguette gueye|full|yes|") == ("loss", None)
    assert _settle(f"{BARCA}|player_last_goal_scorer|lamine yamal|full|yes|") == ("win", None)
    assert _settle(f"{BARCA}|player_last_goal_scorer|maguette gueye|full|yes|") == ("loss", None)


def test_no_scorer_selection_loses_when_goals_were_scored():
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|no scorer|full|yes|") == ("loss", None)


def test_first_scorer_with_only_own_goals_is_a_loss_and_ties_refuse():
    payload = json.loads((FIXTURES / BOX_0916.replace("/", "__")).read_text(encoding="utf-8"))
    # Deportivo 0-1 Sevilla with its one goal (Miguel Sierra 52') turned into an own goal.
    only_own = copy.deepcopy(payload)
    goal = only_own["match_box"]["401882873"]["goals"][0]
    goal["own_goal"] = True
    for side in only_own["match_box"]["401882873"]["players"].values():
        for player in side["players"]:
            player["goals"] = 0.0
    settler = _settler(fetch_export=_fixture_fetch({BOX_0916: json.dumps(only_own)}))
    assert _settle(f"{DEPOR}|player_first_goal_scorer|miguel angel sierra ortega|full|yes|", settler) == ("loss", None)

    tied = copy.deepcopy(payload)
    tied_box = tied["match_box"]["401882871"]
    # Raphinha's 25' penalty moved onto João Cancelo's 8' opener: the first goal has two scorers.
    tied_box["goals"][1]["clock"], tied_box["goals"][1]["clock_seconds"] = "8'", 437.0
    settler = _settler(fetch_export=_fixture_fetch({BOX_0916: json.dumps(tied)}))
    assert _settle(f"{BARCA}|player_first_goal_scorer|maguette gueye|full|yes|", settler) == (None, "goal_order_unavailable")


def test_goal_list_disagreeing_with_the_score_refuses():
    payload = json.loads((FIXTURES / BOX_0916.replace("/", "__")).read_text(encoding="utf-8"))
    payload["match_box"]["401882871"]["goals"].pop()
    settler = _settler(fetch_export=_fixture_fetch({BOX_0916: json.dumps(payload)}))
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|lamine yamal|full|yes|", settler) == (None, "goal_list_inconsistent")


# --- player stats ---------------------------------------------------------------------------


def test_shots_on_target_over_under_push():
    # Lamine Yamal: shots_on_target 2.0, shots 7.0, assists 2.0.
    assert _settle(f"{BARCA}|player_shots_on_target|lamine yamal|full|over|1.5") == ("win", None)
    assert _settle(f"{BARCA}|player_shots_on_target|lamine yamal|full|over|2.5") == ("loss", None)
    # No recorded row sits on an integer line or on the under; the real row, re-lined.
    assert _settle(f"{BARCA}|player_shots_on_target|lamine yamal|full|over|2.5", side="under") == ("win", None)
    assert _settle(f"{BARCA}|player_shots_on_target|lamine yamal|full|over|2.5", line=2.0) == ("push", None)
    assert _settle(f"{BARCA}|player_shots|lamine yamal|full|over|5.5") == ("win", None)
    assert _settle(f"{BARCA}|player_assists|lamine yamal|full|over|0.5") == ("win", None)


# --- corners, cards, halves ------------------------------------------------------------------


def test_corners_match_total():
    assert _settle(f"{BARCA}|alternate_totals_corners||full|over|13.5") == ("win", None)
    assert _settle(f"{BARCA}|alternate_totals_corners||full|under|13.5") == ("loss", None)
    assert _settle(f"{BARCA}|alternate_totals_corners||full|over|18.5") == ("loss", None)


def test_cards_refuse_without_reading_anything():
    calls = []
    settler = _settler(fetch_export=_fixture_fetch(calls=calls))
    assert _settle(f"{BARCA}|player_to_receive_card|dani olmo|full|yes|", settler) == (None, "cards_not_gradeable")
    assert _settle(f"{BARCA}|player_to_receive_red_card|lamine yamal|full|yes|", settler) == (None, "cards_not_gradeable")
    assert calls == []


def test_first_half_three_way_and_lines():
    assert _settle(f"{ALAVES}|h2h||h1|draw|") == ("win", None)
    assert _settle(f"{ALAVES}|h2h||h1|home|") == ("loss", None)
    assert _settle(f"{ALAVES}|h2h||h1|away|") == ("loss", None)
    # 0-0 at the interval: +0.75 wins both half-stakes, -0.75 loses both.
    assert _settle(f"{ALAVES}|spreads||h1|away|0.75") == ("win", None)
    assert _settle(f"{ALAVES}|spreads||h1|home|-0.75") == ("loss", None)
    assert _settle(f"{ALAVES}|totals||h1|over|0.5") == ("loss", None)
    assert _settle(f"{ALAVES}|totals||h1|under|0.5") == ("win", None)


def test_quarter_line_that_splits_refuses():
    assert settle_spread(1, -0.75) == (None, "asian_quarter_line_split")  # half win, half push
    assert settle_spread(0, 0.25) == (None, "asian_quarter_line_split")
    assert settle_over_under(2, "over", 2.25) == (None, "asian_quarter_line_split")
    assert settle_over_under(3, "over", 2.25) == ("win", None)


# --- unfinished -----------------------------------------------------------------------------


def test_unfinished_match_refuses():
    # The real final box put back in play (only these status fields changed).
    payload = json.loads((FIXTURES / BOX_0916.replace("/", "__")).read_text(encoding="utf-8"))
    box = payload["match_box"]["401882871"]
    box.update({"final": False, "status_state": "in", "status_detail": "67'", "status_period": 2})
    settler = _settler(fetch_export=_fixture_fetch({BOX_0916: json.dumps(payload)}))
    for key in (
        f"{BARCA}|player_goal_scorer_anytime|lamine yamal|full|yes|",
        f"{BARCA}|player_shots_on_target|lamine yamal|full|over|1.5",
        f"{BARCA}|alternate_totals_corners||full|over|13.5",
    ):
        assert _settle(key, settler) == (None, "match_not_final")


def test_first_half_in_play_refuses_and_kickoff_in_future_is_not_started():
    box_0915 = "soccer_source/la_liga/api/live_state/live_state_2026-09-15.json"
    payload = json.loads((FIXTURES / box_0915.replace("/", "__")).read_text(encoding="utf-8"))
    box = payload["match_box"]["401882876"]
    box.update({"final": False, "status_state": "in", "status_detail": "38'", "status_period": 1,
                "home_linescores": [0], "away_linescores": [0]})
    settler = _settler(fetch_export=_fixture_fetch({box_0915: json.dumps(payload)}))
    assert _settle(f"{ALAVES}|h2h||h1|draw|", settler) == (None, "segment_not_final")

    calls = []
    early = SoccerPopulationSettler(fetch_export=_fixture_fetch(calls=calls),
                                    now=lambda: datetime(2026, 9, 16, 12, 0, tzinfo=timezone.utc))
    assert _settle(f"{BARCA}|player_goal_scorer_anytime|lamine yamal|full|yes|", early) == (None, "not_started")
    assert calls == []


# --- routing --------------------------------------------------------------------------------


def test_full_game_lines_pass_through_untouched():
    settler = _settler()
    for key in (f"{BARCA}|h2h||full|home|", f"{BARCA}|totals||full|over|4.5", f"{BARCA}|btts||full|yes|"):
        shaped, view = _row(key)
        assert settler.handles(shaped, view) is False
        assert settler(shaped, view) is None
    assert settler.fetches == 0


def test_one_read_per_league_date_and_join_is_recorded():
    calls = []
    settler = _settler(fetch_export=_fixture_fetch(calls=calls))
    for key in RECORDS:
        if key.startswith(BARCA):
            _settle(key, settler)
    assert len(calls) == len(set(calls))
    assert BOX_0916 in calls
    assert settler.join_hits == settler.join_attempts > 0


def test_kickoff_dates_probe_espn_day_first():
    late = datetime(2026, 9, 20, 2, 30, tzinfo=timezone.utc)  # 22:30 ET / 21:30 CT on the 19th
    assert candidate_dates(late) == ["2026-09-19", "2026-09-20"]
    assert GRADER_VERSION == "soccer/1"


def test_reachability_a_real_prop_row_is_graded_only_through_the_settler():
    record = RECORDS[f"{BARCA}|player_goal_scorer_anytime|lamine yamal|full|yes|"]
    graded, ungraded = bs.grade_population([record], {})
    assert graded == [] and ungraded == {"player_prop": 1}

    settler = _settler()
    shaped, _ = bs.scorecard_record(record)
    assert settler(shaped, mbs.view_from_record(record)) == ("win", None)

    if "extra_settler" not in inspect.signature(bs.grade_population).parameters:
        pytest.skip("bucket_search.grade_population has no extra_settler hook in this checkout yet")
    graded, ungraded = bs.grade_population([record], {}, extra_settler=settler)
    assert len(graded) == 1 and graded[0]["y"] == 1.0
    assert "player_prop" not in ungraded
