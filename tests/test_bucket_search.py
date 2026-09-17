"""`scripts/bucket_search.py` and `measured_bucket_skill` -- where a model succeeds INSIDE a category.

Lane `accuracy-assessment-0914`, user request 2026-09-14: "then build the bucket search on
the recorder data".

The load-bearing tests:
- ONE DEFINITION: a candidate the scorer sees and the record the recorder wrote from it
  fall into exactly the same buckets;
- a planted pocket IS validated;
- when outcomes follow the MARKET's own probability, no skill pocket and no profit pocket
  is validated (the corrected null, recorded in the lane before any test ran);
- a bucket whose effect sits on ONE date is NOT validated (leave-one-date-out);
- a validated pocket cancels the category demotion at score time, and never raises.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import random

import pytest

import syndicate.features.shared.measured_bucket_skill as mbs
from syndicate.features.shared.opportunity_population_ledger import population_key, population_record

_SRC = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "bucket_search.py"
_spec = importlib.util.spec_from_file_location("bucket_search", _SRC)
bs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bs)

# Small enough to run fast, large enough for the planted effect to clear FDR.
FAST = {"min_games": 60, "min_dates": 5, "resamples": 1000, "seed": 7, "q": 0.10}


def _candidate(**overrides):
    row = {
        "sport": "mlb", "event_id": "evt-1", "kind": "game", "market": "totals", "segment": "full",
        "side": "over", "line": 8.5, "home_team": "Home Team", "away_team": "Away Team",
        "commence_time": "2026-09-01T23:00:00Z", "game_state": "pregame", "model_edge_pct": 12.0,
        "ev_pct": 1.0, "board_lane": "opportunity",
        "quote": {"price": 100, "fair_probability": 0.5, "fair_method": "consensus",
                  "books_quoting": 8, "book_age_seconds": 60.0},
        "score": {"score": 1.0, "value_pct": 1.0},
    }
    row.update(overrides)
    return row


def _record_from(candidate):
    key = population_key(candidate)
    return population_record(candidate, key, "2026-09-01T18:00:00Z", sport=candidate["sport"])


# --------------------------------------------------------------------------
# one definition
# --------------------------------------------------------------------------


@pytest.mark.parametrize("overrides", [
    {},
    {"model_edge_pct": -3.0, "quote": {"price": -150, "fair_probability": 0.7, "fair_method": "sharp_anchor",
                                        "books_quoting": 2, "book_age_seconds": 900.0}},
    {"market": "h2h", "side": "home", "line": None, "game_state": "live", "model_edge_pct": 0.5},
    {"quote": {"price": 300, "fair_probability": 0.2, "fair_method": "book_margin_model",
               "books_quoting": 1, "book_age_seconds": 200.0}},
])
def test_a_candidate_and_its_record_fall_into_the_same_buckets(overrides):
    candidate = _candidate(**overrides)
    record = _record_from(candidate)
    assert mbs.bucket_ids(mbs.view_from_candidate(candidate)) == mbs.bucket_ids(mbs.view_from_record(record))
    assert mbs.bucket_ids(mbs.view_from_candidate(candidate)), "fixture must land in buckets"


def test_band_edges_are_lower_inclusive():
    view = mbs.view_from_candidate(_candidate(model_edge_pct=5.0, quote={
        "fair_probability": 0.35, "book_age_seconds": 120.0, "books_quoting": 3, "fair_method": "weird"}))
    bands = mbs.dimension_bands(view)
    assert bands == {"disagreement": "5-10", "direction": "for", "price": "mid",
                     "quote_age": "aging", "books": "3-6", "fair_method": "other"}


def test_one_bucket_per_dimension_never_a_cross_product():
    ids = mbs.bucket_ids(mbs.view_from_candidate(_candidate()))
    assert len(ids) == len(mbs.DIMENSIONS)
    assert all(bucket.startswith("mlb|totals|full|pregame|") for bucket in ids)


# --------------------------------------------------------------------------
# the table -> score factor
# --------------------------------------------------------------------------

POCKET_ID = "mlb|totals|full|pregame|disagreement=10+"
LOSS_ID = "mlb|totals|full|pregame|books=7+"


def test_an_empty_table_changes_nothing():
    assert mbs.bucket_factor(mbs.view_from_candidate(_candidate()), table={}) is None


def test_a_pocket_returns_one_and_a_loss_returns_its_scaled_factor():
    view = mbs.view_from_candidate(_candidate())
    assert mbs.bucket_factor(view, table={POCKET_ID: {"verdict": "skill_pocket"}}) == 1.0
    factor = mbs.bucket_factor(view, table={LOSS_ID: {"verdict": "skill_loss", "established_loss_rel": 0.04}})
    assert factor == pytest.approx(1.0 - mbs.SKILL_GAIN * 0.04)


def test_a_pocket_and_a_loss_on_one_row_leave_the_category_factor():
    view = mbs.view_from_candidate(_candidate())
    table = {POCKET_ID: {"verdict": "skill_pocket"},
             LOSS_ID: {"verdict": "skill_loss", "established_loss_rel": 0.04}}
    assert mbs.bucket_factor(view, table=table) is None


def test_load_table_keeps_only_validated_verdicts(tmp_path):
    path = tmp_path / "table.json"
    path.write_text(json.dumps({"buckets": {
        POCKET_ID: {"verdict": "skill_pocket"},
        "x|y|full|pregame|books=1-2": {"verdict": "parity"},
        LOSS_ID: {"verdict": "skill_loss", "established_loss_rel": 0.02},
    }}), encoding="utf-8")
    assert set(mbs.load_table(path)) == {POCKET_ID, LOSS_ID}
    assert mbs.load_table(tmp_path / "missing.json") == {}


def test_the_shipped_table_is_empty():
    """Shipped inert: nothing moves until a search validates a bucket and the table is reviewed."""
    assert mbs.load_table() == {}


# --------------------------------------------------------------------------
# grading
# --------------------------------------------------------------------------


def _chip(day_home, day_away, away_score, home_score, sport="mlb", state="final"):
    return {"sport": sport, "state": state, "matchup": f"{day_away} @ {day_home}",
            "away": {"name": day_away, "key": day_away.lower(), "score": away_score},
            "home": {"name": day_home, "key": day_home.lower(), "score": home_score}}


def test_records_grade_through_the_scorecards_own_rules():
    over = _record_from(_candidate())
    under = _record_from(_candidate(side="under"))
    home_ml = _record_from(_candidate(market="h2h", side="home", line=None))
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", away_score=4, home_score=6)]}   # total 10
    graded, ungraded = bs.grade_population([over, under, home_ml], chips)
    outcomes = {(tuple(sorted(r["buckets"]))[0].split("|")[1], r["y"]) for r in graded}
    assert ("totals", 1.0) in outcomes and ("totals", 0.0) in outcomes and ("h2h", 1.0) in outcomes
    assert ungraded == {}


def test_what_cannot_be_graded_is_counted_by_reason():
    prop = _record_from(_candidate(market="batter_hits", player_name="A Hitter", line=0.5))
    corners = _record_from(_candidate(sport="soccer", market="alternate_totals_corners", line=9.5))
    segment = _record_from(_candidate(segment="first5"))
    no_final = _record_from(_candidate(event_id="evt-2", home_team="Other Home", away_team="Other Away"))
    chips = {"2026-09-01": [_chip("Other Home", "Other Away", 1, 2, state="live")]}
    _graded, ungraded = bs.grade_population([prop, corners, segment, no_final], chips)
    assert ungraded == {"player_prop": 1, "market_not_gradeable_from_score": 1,
                        "segment_not_full_game": 1, "game_not_final": 1}


def test_a_player_prop_is_counted_as_a_prop_whatever_its_market():
    """83% of one soccer day (12,337 of 14,776) was player props; they must not read as 'market not gradeable'."""
    scorer = _record_from(_candidate(sport="soccer", market="player_goal_scorer_anytime",
                                     player_name="A Striker", side="yes", line=None))
    _graded, ungraded = bs.grade_population([scorer], {})
    assert ungraded == {"player_prop": 1}


@pytest.mark.parametrize("away, home, side, expected", [
    (1, 1, "home", "loss"), (1, 1, "away", "loss"), (1, 1, "draw", "win"),
    (1, 2, "home", "win"), (1, 2, "away", "loss"), (1, 2, "draw", "loss"),
])
def test_a_soccer_draw_is_a_result_not_a_push(away, home, side, expected):
    record = {"sport": "soccer", "market": "h2h", "side": side, "line": None}
    assert bs.settle_from_score(record, away, home) == expected


def test_a_two_way_moneyline_tie_is_still_the_scorecards_push():
    assert bs.settle_from_score({"sport": "nfl", "market": "h2h", "side": "home"}, 20, 20) == "push"


@pytest.mark.parametrize("away, home, side, expected", [
    (1, 1, "yes", "win"), (1, 1, "no", "loss"), (0, 2, "yes", "loss"), (0, 0, "no", "win"), (0, 0, "maybe", None),
])
def test_both_teams_to_score_settles_from_the_final(away, home, side, expected):
    assert bs.settle_from_score({"sport": "soccer", "market": "btts", "side": side}, away, home) == expected


def test_drawn_soccer_games_reach_the_graded_population():
    """All three sides of a 1-1 game are graded; before, home/away were pushes and draw was unsettleable."""
    sides = [_candidate(sport="soccer", market="h2h", side=side, line=None,
                        quote={"price": 200, "fair_probability": 0.3, "fair_method": "consensus",
                               "books_quoting": 8, "book_age_seconds": 60.0})
             for side in ("home", "draw", "away")]
    btts = _candidate(sport="soccer", market="btts", side="yes", line=None)
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", 1, 1, sport="soccer")]}
    graded, ungraded = bs.grade_population([_record_from(c) for c in sides + [btts]], chips)
    assert ungraded == {}
    assert sorted(row["y"] for row in graded) == [0.0, 0.0, 1.0, 1.0]


def test_a_record_without_team_names_joins_through_the_event_map():
    record = _record_from(_candidate())
    record.pop("ht"), record.pop("at")
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", 4, 6)]}
    graded, ungraded = bs.grade_population([record], chips)
    assert graded == [] and ungraded == {"no_team_names": 1}
    graded, _ = bs.grade_population([record], chips, {("mlb", "evt-1"): ("Home Team", "Away Team")})
    assert len(graded) == 1


def test_a_later_sighting_lends_its_team_names_to_the_earliest_one():
    """Dedup keeps the EARLIEST sighting; one written before the recorder carried names still joins."""
    early = _record_from(_candidate())
    early.pop("ht"), early.pop("at")
    early["t"] = "2026-09-01T12:00:00Z"
    late = _record_from(_candidate())
    other_side = _record_from(_candidate(side="under"))
    other_side.pop("ht"), other_side.pop("at")
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", 4, 6)]}
    graded, ungraded = bs.grade_population([early, late, other_side], chips)
    assert ungraded == {} and len(graded) == 2


def test_a_game_that_has_not_started_reads_not_started_not_unnamed():
    """On soccer 09-14, ~800 of 802 'no_team_names' were games days from kickoff."""
    record = _record_from(_candidate(commence_time="2026-09-05T23:00:00Z"))
    record.pop("ht"), record.pop("at")
    _graded, ungraded = bs.grade_population([record], {}, today="2026-09-02")
    assert ungraded == {"not_started": 1}
    _graded, ungraded = bs.grade_population([record], {})
    assert ungraded == {"no_team_names": 1}


def test_mlb_props_grade_through_the_prop_settler_and_other_sports_props_do_not():
    hitter = _record_from(_candidate(market="batter_hits", player_name="A Hitter", side="over", line=0.5))
    pitcher = _record_from(_candidate(event_id="evt-2", market="strikeouts", player_name="A Pitcher",
                                      side="over", line=5.5))
    striker = _record_from(_candidate(sport="soccer", market="player_shots", player_name="A Striker",
                                      side="over", line=1.5))
    calls = []

    def settler(shaped):
        calls.append(shaped["player_name"])
        return ("win", None) if shaped["market"] == "batter_hits" else (None, "game_not_final")

    graded, ungraded = bs.grade_population([hitter, pitcher, striker], {}, prop_settler=settler)
    assert [tuple(sorted(row["buckets"]))[0].split("|")[1] for row in graded] == ["batter_hits"]
    assert graded[0]["y"] == 1.0 and graded[0]["game"] == "mlb|evt-1"
    assert ungraded == {"prop_game_not_final": 1, "player_prop": 1}
    assert sorted(calls) == ["a hitter", "a pitcher"]
    _graded, ungraded = bs.grade_population([hitter], {})
    assert ungraded == {"player_prop": 1}


def test_a_published_opening_falls_into_the_same_buckets_as_its_recorder_record():
    """One definition across populations: an opening is converted through the recorder's own builders."""
    from syndicate.features.shared import clv_opening_ledger as clv

    for candidate in (_candidate(), _candidate(market="batter_hits", player_name="A Hitter", line=0.5,
                                               game_state="live", model_edge_pct=-4.0)):
        opening = clv._opening_record(candidate, clv._opening_key(candidate), "2026-09-01T18:00:00Z")
        [record] = bs.records_from_openings([opening])
        expected = _record_from(candidate)
        assert record["k"] == expected["k"]
        assert mbs.bucket_ids(mbs.view_from_record(record)) == mbs.bucket_ids(mbs.view_from_record(expected))
        assert (record["ht"], record["at"], record["t"]) == ("Home Team", "Away Team", "2026-09-01T18:00:00Z")


def test_without_a_game_state_the_phase_comes_from_when_it_was_sighted():
    """Published openings carried no game state before 2026-09-12; the sighting time decides instead."""
    from datetime import datetime, timezone

    pre = _record_from(_candidate(game_state=None))          # sighted 18:00Z, first pitch 23:00Z
    assert mbs.view_from_record(pre)["phase"] == "pregame"
    assert mbs.view_from_record(dict(pre, t="2026-09-01T23:30:00Z"))["phase"] == "live"
    assert mbs.view_from_record(dict(pre, gs="live"))["phase"] == "live"      # the field wins when present
    assert mbs.view_from_record(dict(pre, ct=None))["phase"] == "unknown"
    candidate = _candidate(game_state=None)
    assert mbs.view_from_candidate(candidate, now=datetime(2026, 9, 1, 18, tzinfo=timezone.utc))["phase"] == "pregame"
    assert mbs.view_from_candidate(candidate, now=datetime(2026, 9, 1, 23, 30, tzinfo=timezone.utc))["phase"] == "live"


def test_ungraded_reasons_are_also_counted_per_sport():
    prop = _record_from(_candidate(market="batter_hits", player_name="A Hitter", line=0.5))
    corners = _record_from(_candidate(sport="soccer", market="alternate_totals_corners", line=9.5))
    by_sport = {}
    _graded, ungraded = bs.grade_population([prop, corners], {}, ungraded_by_sport=by_sport)
    assert by_sport == {"mlb": {"player_prop": 1}, "soccer": {"market_not_gradeable_from_score": 1}}
    assert ungraded == {"player_prop": 1, "market_not_gradeable_from_score": 1}


def test_a_scoreless_mlb_chip_settles_from_the_score_source_and_other_sports_do_not():
    record = _record_from(_candidate())                                            # mlb totals over 8.5
    soccer = _record_from(_candidate(sport="soccer", market="totals", side="over", line=2.5))
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", None, None),
                            _chip("Home Team", "Away Team", None, None, sport="soccer")]}
    calls = []

    def source(shaped):
        calls.append(shaped["sport"])
        return (4, 6), None

    graded, ungraded = bs.grade_population([record, soccer], chips, score_source=source)
    assert [(row["sport"], row["y"]) for row in graded] == [("mlb", 1.0)]         # 10 runs > 8.5
    assert ungraded == {"final_score_unparseable": 1} and calls == ["mlb"]
    _graded, ungraded = bs.grade_population([record], chips)
    assert ungraded == {"final_score_unparseable": 1}
    live = {"2026-09-01": [_chip("Home Team", "Away Team", 1, 2, state="live")]}
    _graded, ungraded = bs.grade_population([record], live, score_source=source)
    assert ungraded == {"game_not_final": 1}


def test_the_published_population_can_never_write_the_scoring_table(tmp_path):
    before = mbs.TABLE_PATH.read_bytes()
    with pytest.raises(SystemExit):
        bs.main(["--population", "published", "--openings-dir", str(tmp_path), "--no-props",
                 "--out-dir", str(tmp_path / "out"), "--write-table"])
    assert mbs.TABLE_PATH.read_bytes() == before


def test_team_lookups_try_the_kickoff_date_then_the_sighting_date_one_market_at_a_time():
    """A board date carries games for days ahead, and a late kickoff can sit only on the next date's grid."""
    first = _record_from(_candidate(event_id="evt-1"))
    second = _record_from(_candidate(event_id="evt-2", home_team="B Home", away_team="B Away"))
    late = _record_from(_candidate(event_id="evt-6", home_team="D Home", away_team="D Away"))
    late["t"] = "2026-09-02T15:00:00Z"
    future = _record_from(_candidate(event_id="evt-3", commence_time="2026-09-03T23:00:00Z"))
    prop = _record_from(_candidate(event_id="evt-4", market="batter_hits", player_name="A Hitter", line=0.5))
    named = _record_from(_candidate(event_id="evt-5", home_team="C Home", away_team="C Away"))
    for record in (first, second, late, future, prop):
        record.pop("ht"), record.pop("at")
    grids = {("2026-09-01", "h2h"): {("mlb", "evt-1"): ("Home Team", "Away Team")},
             ("2026-09-01", "totals"): {("mlb", "evt-2"): ("B Home", "B Away")},
             ("2026-09-02", "h2h"): {("mlb", "evt-6"): ("D Home", "D Away")}}
    calls = []

    def fetch(day, sport, market):
        calls.append((day, sport, market))
        return grids.get((day, market), {})

    teams, lookups = bs.resolve_event_teams([first, second, late, future, prop, named], fetch, today="2026-09-02")
    assert calls == [("2026-09-01", "mlb", "h2h"), ("2026-09-01", "mlb", "totals"),
                     ("2026-09-01", "mlb", "spreads"), ("2026-09-02", "mlb", "h2h")]
    assert lookups == 4
    assert teams == {("mlb", "evt-1"): ("Home Team", "Away Team"), ("mlb", "evt-2"): ("B Home", "B Away"),
                     ("mlb", "evt-6"): ("D Home", "D Away")}


def test_a_session_worktree_finds_the_token_in_the_main_worktree(tmp_path, monkeypatch):
    """REPO_ROOT is the session worktree, which has no .env; the main worktree's is used."""
    session_tree, main_tree = tmp_path / "session", tmp_path / "main"
    session_tree.mkdir()
    main_tree.mkdir()
    (main_tree / ".env").write_text('OTHER=1\nADMIN_TOKEN_OLD=nope\nADMIN_TOKEN="from-main"\n', encoding="utf-8")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(bs, "REPO_ROOT", session_tree)
    monkeypatch.setattr(bs, "_main_worktree", lambda: main_tree)
    assert bs._admin_token() == "from-main"
    explicit = tmp_path / "explicit.env"
    explicit.write_text("ADMIN_TOKEN=from-flag\n", encoding="utf-8")
    assert bs._admin_token(explicit) == "from-flag"
    monkeypatch.setenv("ADMIN_TOKEN", "from-env")
    assert bs._admin_token(explicit) == "from-env"


def test_no_token_anywhere_is_empty_not_a_guess(tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setattr(bs, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(bs, "_main_worktree", lambda: None)
    assert bs._admin_token() == ""
    assert bs.env_file_candidates() == [tmp_path / ".env"]


# --------------------------------------------------------------------------
# statistics
# --------------------------------------------------------------------------


def test_benjamini_hochberg_on_a_known_list():
    p = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205]
    assert bs.benjamini_hochberg(p, 0.05) == {0, 1}
    assert bs.benjamini_hochberg([], 0.1) == set()


def test_bootstrap_is_deterministic_under_a_seed():
    values = [random.Random(3).uniform(-1, 1) for _ in range(50)]
    assert bs.bootstrap_mean(values, resamples=500, seed=11) == bs.bootstrap_mean(values, resamples=500, seed=11)


def test_leave_one_date_out():
    assert bs.leave_one_date_out_stable([("a", -1.0), ("b", -0.5), ("c", -0.2)]) is True
    assert bs.leave_one_date_out_stable([("a", -3.0), ("b", 0.0), ("c", 0.0)]) is False
    assert bs.leave_one_date_out_stable([("a", -1.0)]) is False


# --------------------------------------------------------------------------
# the search, end to end on synthetic populations
# --------------------------------------------------------------------------


def _population(seed, *, true_p, dates=10, games_per_date=24, edge=25.0, effect_dates=None):
    """One MLB totals row per game: fair 0.5, the model says over at 0.5 + edge/100, and the
    over lands with probability `true_p`.

    With `effect_dates`, the model has its edge ONLY on those dates and agrees with the
    market (edge 0) everywhere else, where outcomes are 50/50. A confident model on
    coin-flip dates would be a real, stable LOSS -- a different test."""
    rng = random.Random(seed)
    records, chips = [], {}
    for d in range(dates):
        day = f"2026-09-{d + 1:02d}"
        day_chips = []
        on_effect_date = effect_dates is None or d in effect_dates
        for g in range(games_per_date):
            home, away = f"Home {d}-{g}", f"Away {d}-{g}"
            p = true_p if on_effect_date else 0.5
            over = rng.random() < p
            away_score, home_score = (4, 5) if over else (2, 3)
            day_chips.append(_chip(home, away, away_score, home_score))
            candidate = _candidate(event_id=f"e{d}-{g}", home_team=home, away_team=away,
                                   commence_time=f"{day}T23:00:00Z",
                                   model_edge_pct=edge if on_effect_date else 0.0)
            records.append(_record_from(candidate))
        chips[day] = day_chips
    return records, chips


def _search(records, chips):
    graded, _ = bs.grade_population(records, chips)
    return {r["bucket_id"]: r for r in bs.evaluate_buckets(graded, **FAST)}


def test_a_planted_pocket_is_validated():
    results = _search(*_population(1, true_p=0.75))
    pocket = results[POCKET_ID]
    assert pocket["verdict"] == mbs.VERDICT_SKILL_POCKET, pocket
    assert pocket["games"] == 240 and pocket["dates"] == 10
    assert pocket["ci95"][1] < 0 and pocket["lodo_stable"] and pocket["fdr_pass"]


def test_when_outcomes_follow_the_market_no_pocket_is_validated():
    """The corrected null. A confident model on market-true outcomes may validate as a LOSS
    (that is correct); it must never validate as a pocket, for skill or for profit."""
    results = _search(*_population(2, true_p=0.5))
    assert not [b for b, r in results.items() if r["verdict"] == mbs.VERDICT_SKILL_POCKET]
    assert not [b for b, r in results.items() if r["profit_verdict"]]


def test_an_effect_on_one_date_is_not_validated():
    """Every row shares the consensus bucket; the model only disagrees (and wins) on one
    date. Drop that date and the effect is gone, so leave-one-date-out must refuse it."""
    results = _search(*_population(3, true_p=0.98, effect_dates={4}))
    common = "mlb|totals|full|pregame|fair_method=consensus"
    assert results[common]["dates"] == 10 and results[common]["games"] == 240
    assert results[common]["lodo_stable"] is False
    assert results[common]["verdict"] != mbs.VERDICT_SKILL_POCKET


def test_too_few_dates_is_insufficient_not_parity():
    results = _search(*_population(4, true_p=0.75, dates=4, games_per_date=40))
    assert results[POCKET_ID]["verdict"] == mbs.VERDICT_INSUFFICIENT


def test_the_table_carries_only_validated_skill_buckets():
    graded, _ = bs.grade_population(*_population(1, true_p=0.75))
    results = bs.evaluate_buckets(graded, **FAST)
    payload = bs.table_payload(results, window="test", method={})
    assert POCKET_ID in payload["buckets"]
    assert all(entry["verdict"] in ("skill_pocket", "skill_loss") for entry in payload["buckets"].values())
    assert payload["buckets_tested"] == len(results)


def test_the_report_renders():
    records, chips = _population(1, true_p=0.75, dates=6, games_per_date=12)
    graded, ungraded = bs.grade_population(records, chips)
    results = bs.evaluate_buckets(graded, **FAST)
    text = bs.markdown_report(results, bs.coverage(records, chips, graded), ungraded)
    assert "| bucket | verdict |" in text and POCKET_ID in text


# --------------------------------------------------------------------------
# the scorer
# --------------------------------------------------------------------------


def test_a_validated_pocket_cancels_the_category_demotion(monkeypatch):
    import syndicate.features.shared.layer2_board as l2

    monkeypatch.setattr(mbs, "MEASURED_BUCKET_SKILL", {POCKET_ID: {"verdict": "skill_pocket"}})
    loss_note = {"model_skill": {"status": "measured", "established_loss_rel": 0.09722}}
    score = {"score": 4.0, "value_pct": 5.0}
    assert l2._apply_skill_reliability(score, loss_note, row=_candidate())["score"] == 4.0
    # without the row, the category demotion still applies
    assert l2._apply_skill_reliability(score, loss_note)["score"] < 4.0


def test_a_validated_bucket_loss_demotes_a_parity_category_row(monkeypatch):
    import syndicate.features.shared.layer2_board as l2

    monkeypatch.setattr(mbs, "MEASURED_BUCKET_SKILL",
                        {LOSS_ID: {"verdict": "skill_loss", "established_loss_rel": 0.04}})
    parity_note = {"model_skill": {"status": "measured", "established_loss_rel": 0.0}}
    out = l2._apply_skill_reliability({"score": 4.0, "value_pct": 5.0}, parity_note, row=_candidate())
    assert out["score"] == pytest.approx(round(4.0 * (1.0 - mbs.SKILL_GAIN * 0.04), 4))
    assert out["skill_source"] == "bucket"


def test_the_board_build_passes_the_row_to_the_scorer(monkeypatch):
    """Reachability: a table entry must change a real `build_layer2_rows` score."""
    import syndicate.features.shared.layer2_board as l2

    monkeypatch.setattr(l2, "blended_score", lambda **_: {"score": 4.0, "value_pct": 5.0})
    grid_row = {
        "sport": "wnba", "event_id": "evt-1", "kind": "prop", "market": "player_points", "segment": "full",
        "line": 18.5, "player_name": "A. Player", "home_team": "Home", "away_team": "Away",
        "commence_time": "2099-01-01T00:00:00Z", "sides": ["over", "under"], "books_quoting": 2, "cells": {},
        "best": {"over": {"price": -110, "bookmaker": "draftkings", "books_quoting": 2, "age_seconds": 30.0},
                 "under": {"price": -110, "bookmaker": "fanduel", "books_quoting": 2, "age_seconds": 30.0}},
        "projection": {"edge_vs_market_pct": 6.0},
    }
    baseline = {r["side"]: r["score"]["score"] for r in l2.build_layer2_rows([dict(grid_row)])["opportunities"]}
    assert baseline and all(value == 4.0 for value in baseline.values())
    opportunities = l2.build_layer2_rows([dict(grid_row)])["opportunities"]
    bucket_table = {}
    for row in opportunities:
        for bucket_id in mbs.bucket_ids(mbs.view_from_candidate(row)):
            bucket_table[bucket_id] = {"verdict": "skill_loss", "established_loss_rel": 0.05}
    monkeypatch.setattr(mbs, "MEASURED_BUCKET_SKILL", bucket_table)
    moved = {r["side"]: r["score"]["score"] for r in l2.build_layer2_rows([dict(grid_row)])["opportunities"]}
    assert all(moved[side] < baseline[side] for side in baseline)


# --------------------------------------------------------------------------
# the extra settler and one sighting per phase  [2026-09-17, lane model-scorecard-cron]
# --------------------------------------------------------------------------


def test_an_extra_settler_grades_what_the_skips_would_drop_and_none_passes_through():
    segment = _record_from(_candidate(segment="first5"))
    prop = _record_from(_candidate(sport="soccer", market="player_goal_scorer_anytime",
                                   player_name="A Striker", side="yes", line=None))
    full = _record_from(_candidate())
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", away_score=4, home_score=6)]}
    seen = []

    def settler(shaped, view):
        seen.append((shaped["segment"], shaped["market"]))
        if shaped["segment"] == "first5":
            return "win", None
        if shaped["player_name"]:
            return None, "dnp_void"
        return None

    without, ungraded_without = bs.grade_population([segment, prop, full], chips)
    graded, ungraded = bs.grade_population([segment, prop, full], chips, extra_settler=settler)
    assert ungraded_without == {"segment_not_full_game": 1, "player_prop": 1}
    assert len(without) == 1
    assert len(graded) == 2 and ungraded == {"extra_dnp_void": 1}
    assert any(r["y"] == 1.0 and "|first5|" in r["buckets"][0] for r in graded)
    assert ("full", "totals") in seen, "the settler is asked about every record"


def test_an_extra_settler_does_not_grade_a_game_that_has_not_started():
    segment = _record_from(_candidate(segment="first5", commence_time="2099-01-01T23:00:00Z"))
    graded, ungraded = bs.grade_population([segment], {}, today="2026-09-17",
                                           extra_settler=lambda shaped, view: ("win", None))
    assert graded == [] and ungraded == {"not_started": 1}


def test_a_side_sighted_pregame_and_live_grades_once_per_phase():
    """Off != on: keyed on (sport, k) the live sighting of an unmoved h2h side was dropped."""
    pregame = _record_from(_candidate(market="h2h", side="home", line=None))
    live = dict(pregame, t="2026-09-02T00:30:00Z", gs="live")
    chips = {"2026-09-01": [_chip("Home Team", "Away Team", away_score=4, home_score=6)]}
    graded, _ = bs.grade_population([pregame, live], chips)
    phases = sorted(r["buckets"][0].split("|")[3] for r in graded)
    assert phases == ["live", "pregame"]
