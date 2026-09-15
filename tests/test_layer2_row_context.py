"""Headshots and explainers for Layer 2 cards (lane `layer2-row-parity`).

Baseline on the served board 2026-09-15 15:25Z: 0 of 2,959 Layer 2 rows carried a
headshot or an explainer, while 58 legacy rows carried both -- and 16 of those 39
legacy MLB props were the same bet as a Layer 2 row with contradictory numbers.
These tests pin that the Layer 2 row gets both from its OWN numbers.
"""
from __future__ import annotations

import json

from syndicate.features.shared import layer2_row_context as ctx
from syndicate.features.shared.layer2_row_context import (
    clean_narrative,
    load_layer2_row_context,
    narrative_key,
    row_explainer,
    row_identity,
)

LEAD = "The model lands on the over side in 92.2% of sims, while the market is pricing it closer to 53.3%. "
CONTEXT_SENTENCES = "Across his last 5 starts, he has averaged 18.2 outs. The model baseline sits around 14.8 outs against a line of 11.5."


def _prop_row(**over):
    row = {
        "sport": "mlb",
        "event_id": "e1",
        "market": "outs",
        "segment": "full",
        "side": "over",
        "line": 11.5,
        "player_name": "Kyle Freeland",
        "projection": {"model_prob_over": 0.62, "projected": 14.8, "player_id": "607536"},
    }
    row.update(over)
    return row


def _quote(**over):
    quote = {"price": -133, "bookmaker": "kalshi", "fair_probability": 0.533, "books_quoting": 7}
    quote.update(over)
    return quote


# ---------------------------------------------------------------------------
# The vendor write-up: keep the baseball, drop the vendor's own price claim.
# ---------------------------------------------------------------------------


def test_the_vendor_price_sentence_is_dropped_and_the_context_kept():
    assert clean_narrative(LEAD + CONTEXT_SENTENCES) == CONTEXT_SENTENCES


def test_the_low_sample_lead_is_dropped_too():
    text = (
        "This snapshot only used 12 sims, so the model-side frequency is too coarse to quote; "
        "the market is pricing the over side closer to 53.3%. He is projected to hit in the 6 spot."
    )
    assert clean_narrative(text) == "He is projected to hit in the 6 spot."


def test_a_write_up_that_is_only_the_price_sentence_leaves_nothing():
    assert clean_narrative(LEAD) is None


def test_narrative_keys_join_props_by_player_and_games_by_event():
    assert narrative_key(player_name="Kyle Freeland", market="outs", side="over", line="11.5") == (
        "prop", "kyle freeland", "outs", "over", 11.5
    )
    assert narrative_key(event_id="abc", market="totals", side="under", line=8) == ("game", "abc", "totals", "under", 8.0)
    # A moneyline has no line; the vendor's `market_line` must not leak into the key.
    assert narrative_key(event_id="abc", market="h2h", side="home", line=-130) == ("game", "abc", "h2h", "home", None)
    assert narrative_key(market="outs", side="over") is None


# ---------------------------------------------------------------------------
# Loaders: IO once per build, and never raising.
# ---------------------------------------------------------------------------


def _locked_policy(tmp_path):
    payload = {
        "markets": {
            "pitcher_props": {
                "other_playable_candidates": [
                    {
                        "pitcher_name": "Kyle Freeland", "pitcher_id": 607536, "prop": "outs",
                        "selection": "over", "market_line": 11.5, "reasons": [LEAD + CONTEXT_SENTENCES],
                    }
                ]
            },
            "totals": {
                "recommendations": [
                    {
                        "market": "totals", "event_id": "ev9", "selection": "under", "market_line": 8.0,
                        "reason_summary": "The game is projecting around 7.1 runs.",
                    }
                ]
            },
        }
    }
    path = tmp_path / "daily_summary_2026_09_15_locked_policy.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_mlb_write_ups_index_by_bet(tmp_path, monkeypatch):
    path = _locked_policy(tmp_path)
    import syndicate.features.mlb.sources as sources

    monkeypatch.setattr(sources, "daily_artifact_path", lambda date, suffix="": path)
    index = ctx._mlb_narratives("2026-09-15")
    prop = index[("prop", "kyle freeland", "outs", "over", 11.5)]
    assert prop == {"text": CONTEXT_SENTENCES, "player_id": "607536"}
    assert index[("game", "ev9", "totals", "under", 8.0)]["text"] == "The game is projecting around 7.1 runs."


def test_nfl_espn_ids_drop_a_name_two_players_share(tmp_path, monkeypatch):
    roster = tmp_path / "roster_2026.csv"
    roster.write_text(
        "full_name,espn_id,team\n"
        "Jahmyr Gibbs,4429795,DET\n"
        "Josh Allen,3918298,BUF\n"
        "Josh Allen,3046399,JAX\n"
        "No Id,NA,DET\n",
        encoding="utf-8",
    )
    import syndicate.features.nfl.fantasy_players as fantasy

    monkeypatch.setattr(fantasy, "roster_path", lambda season: roster)
    ids = ctx._nfl_espn_ids("2026-09-15")
    assert ids == {"jahmyr gibbs": "4429795"}, "an ambiguous name gets no face rather than the wrong one"


def test_the_context_loader_never_raises(monkeypatch):
    def boom(_date):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(ctx, "_mlb_narratives", boom)
    monkeypatch.setattr(ctx, "_nfl_espn_ids", boom)
    out = load_layer2_row_context("2026-09-15")
    assert out["narratives"] == {} and out["nfl_espn_ids"] == {}
    assert set(out["errors"]) == {"mlb_narratives", "nfl_espn_ids"}


# ---------------------------------------------------------------------------
# Identity: a face only where the id is real.
# ---------------------------------------------------------------------------


def test_mlb_headshot_comes_from_the_projected_player_id():
    out = row_identity(_prop_row(), None)
    assert out["player_id"] == "607536"
    assert "/people/607536/headshot/" in out["headshot_url"]


def test_mlb_headshot_falls_back_to_the_write_up_id():
    row = _prop_row(projection={"model_prob_over": 0.62})
    context = {"narratives": {("prop", "kyle freeland", "outs", "over", 11.5): {"text": None, "player_id": "607536"}}}
    assert "/people/607536/" in row_identity(row, context)["headshot_url"]


def test_nfl_headshot_uses_espn_and_does_not_set_player_id():
    row = {"sport": "nfl", "player_name": "Jahmyr Gibbs", "market": "Rushing Yards", "side": "over", "line": 74.5}
    out = row_identity(row, {"nfl_espn_ids": {"jahmyr gibbs": "4429795"}})
    assert out == {"headshot_url": "https://a.espncdn.com/i/headshots/nfl/players/full/4429795.png"}


def test_no_player_or_no_id_means_no_face():
    assert row_identity({"sport": "mlb", "market": "totals"}, None) == {}
    assert row_identity(_prop_row(projection={}), None) == {}
    assert row_identity({"sport": "soccer", "player_name": "Somebody"}, None) == {}


# ---------------------------------------------------------------------------
# The explainer: the row's own numbers first.
# ---------------------------------------------------------------------------


def test_a_modelled_prop_reads_sim_against_market_then_projection():
    text = row_explainer(_prop_row(), _quote())
    assert text.startswith("Our sim has Kyle Freeland over 11.5 outs at 62.0%; the no-vig market across 7 books says 53.3%.")
    assert "It projects 14.8 against the 11.5 line." in text


def test_the_write_up_context_follows_but_its_price_sentence_does_not():
    context = {"narratives": {("prop", "kyle freeland", "outs", "over", 11.5): {"text": CONTEXT_SENTENCES, "player_id": None}}}
    text = row_explainer(_prop_row(), _quote(), context)
    assert text.endswith(CONTEXT_SENTENCES)
    assert "92.2%" not in text and "closer to" not in text


def test_a_live_resim_says_so():
    row = _prop_row(projection={"model_prob_over": 0.4, "basis": "live_resim"})
    assert row_explainer(row, _quote()).startswith("The live re-sim has")


def test_no_model_reads_as_price_led():
    row = {"sport": "soccer", "market": "alternate_totals_corners", "side": "over", "line": 9.5, "event_id": "x"}
    text = row_explainer(row, _quote(price=120, bookmaker="betmgm", fair_probability=0.47, books_quoting=6))
    assert text.startswith("No sim view on total corners over 9.5; it is ranked on price: BETMGM +120 against a no-vig fair of +113 across 6 books.")


def test_game_subjects():
    base = {"sport": "ncaaf", "home_team": "Alabama Crimson Tide", "away_team": "Florida State Seminoles", "event_id": "e"}
    q = _quote(fair_probability=None)
    assert "Alabama Crimson Tide -3.5" in row_explainer({**base, "market": "spreads", "side": "home", "line": -3.5}, q)
    assert "Florida State Seminoles to win" in row_explainer({**base, "market": "h2h", "side": "away", "line": None}, q)
    assert "the under 49.5 (1st half)" in row_explainer({**base, "market": "totals", "side": "under", "line": 49.5, "segment": "h1"}, q)


def test_a_first_five_total_does_not_borrow_a_full_game_write_up():
    context = {"narratives": {("game", "ev9", "totals", "under", 8.0): {"text": "Full-game story.", "player_id": None}}}
    full = {"sport": "mlb", "market": "totals", "side": "under", "line": 8.0, "event_id": "ev9", "segment": "full"}
    first5 = dict(full, segment="first5")
    assert row_explainer(full, _quote(), context).endswith("Full-game story.")
    assert "Full-game story." not in row_explainer(first5, _quote(), context)
