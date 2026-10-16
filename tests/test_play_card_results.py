"""Result cards (lane result-cards, user 2026-10-16): won or lost, the actual result, and what we got wrong -- the close
judges the bet, the sim is judged only where it was the reason, and box-score usage splits a miss into opportunity
vs efficiency."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from syndicate.features.shared import play_card_results as pcr
from syndicate.features.shared import play_cards as pc

REPO = Path(__file__).resolve().parents[1]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_the_close_and_the_result_give_four_verdicts():
    beat, lost = {"ev_close_pct": 2.3}, {"ev_close_pct": -3.7}
    assert pcr.verdict("win", beat, "PRICE PLAY", None, None)["key"] == "right_side"
    assert pcr.verdict("loss", beat, "PRICE PLAY", None, None)["key"] == "good_bet_bad_result"
    assert pcr.verdict("win", lost, "PRICE PLAY", None, None)["key"] == "cashed_against_close"
    assert pcr.verdict("loss", lost, "PRICE PLAY", None, None)["key"] == "wrong_side"
    v = pcr.verdict("win", {}, "PRICE PLAY", None, None)
    assert v["key"] == "no_close" and v["tone"] == "neutral" and any("price play" in x.lower() for x in v["lines"])


def test_the_number_each_bet_settled_on():
    assert pcr.actual_value({"kind": "prop", "side": "over"}, {"y": 0, "v": 1.0}, None) == 1.0
    score = {"home": 66.0, "away": 27.0}
    assert pcr.actual_value({"kind": "game", "market": "totals", "side": "over", "segment": "full"}, None, score) == 93.0
    assert pcr.actual_value({"kind": "game", "market": "spreads", "side": "home"}, None, score) == 39.0
    assert pcr.actual_value({"kind": "game", "market": "h2h", "side": "away"}, None, score) == -39.0
    assert pcr.actual_value({"kind": "game", "market": "h2h", "side": "away", "segment": "h1"}, None, score) is None   # not in the final


def test_the_sim_is_judged_only_where_it_was_the_reason():
    prop = {"kind": "prop", "side": "under", "line": 2.5, "projected": 1.86}
    right = pcr.sim_judgement(prop, "SYNDICATE PICK", 1.0)
    assert right["right_side"] is True and right["error"] == -0.86 and "right about the side of 2.5" in right["text"]
    wrong = pcr.sim_judgement(prop, "SYNDICATE PICK", 4.0)
    assert wrong["right_side"] is False and "wrong about the side" in wrong["text"] and "2.1 low" in wrong["text"]
    assert pcr.sim_judgement(prop, "PRICE PLAY", 1.0) is None and pcr.sim_judgement(prop, "", 1.0) is None
    side = pcr.sim_judgement({"kind": "game", "market": "spreads", "side": "home", "line": -15, "p_model": 0.56, "p_market": 0.5},
                             "SYNDICATE PICK", 39.0)
    assert side["right_side"] is True and "SmartSim backed this side at 56% (the market said 50%): the side came in" == side["text"]
    assert pcr.sim_judgement({"kind": "game", "market": "spreads", "side": "home", "line": -15, "p_model": 0.56},
                             "SYNDICATE PICK", 13.0)["right_side"] is False             # won by 13: -15 not covered


def test_usage_splits_a_result_into_opportunity_or_efficiency():
    less = {"metric": "Batters faced", "per": "batter faced", "actual": 18, "usual": 21.3, "games": 10, "of": "starts", "count": True}
    under = pcr.usage_split(less, "under", "win")
    assert under["kind"] == "opportunity" and "carried it" in under["text"] and "over the last 10 starts (-15%)" in under["fact"]
    assert under["fact"] not in under["text"]                                          # each said once on the card
    assert "sank it" in pcr.usage_split(less, "over", "loss")["text"]                   # less time sinks an over
    normal = pcr.usage_split({"metric": "Ice time", "unit": " min", "per": "minute", "actual": 16.3, "usual": 16.6, "games": 10},
                             "over", "loss")
    assert normal["kind"] == "efficiency" and "output per minute decided it" in normal["text"]
    assert pcr.usage_split({"actual": 3, "usual": 0}, "over", "loss") is None and pcr.usage_split(None, "over", "loss") is None


def _pick():
    return {"pick_id": "l2_d4b4", "kind": "game", "sport": "ncaaf", "event_id": "e1", "matchup": "Colorado State Rams @ Texas State Bobcats",
            "home_team": "Texas State Bobcats", "away_team": "Colorado State Rams", "display_name": "Texas State Bobcats",
            "market": "spreads", "side": "home", "line": -15.0, "segment": "full", "price": 110, "book": "prophetx", "books": 1,
            "fair_price": 100, "p_market": 0.5, "p_model": 0.56, "ev_pct": 5.0, "sim_view": "agrees", "bet": "Texas State Bobcats -15",
            "label": "SYNDICATE PICK", "points": [], "commence_time": "2026-10-16T00:00:00Z"}


def test_a_result_card_renders_the_result_and_never_a_number():
    pick = _pick()
    fields = pc.pick_card_fields(pick, sport="ncaaf", date="2026-10-15", number=4)
    card = {"card_id": "l2_d4b4", "pick_id": "l2_d4b4", "sport": "ncaaf", "date": "2026-10-15", "price": 110, "market": "spreads",
            "side": "home", "line": -15.0, "result": {"y": 1.0, "units": 1.1}, "close": {}}
    over, cls = pcr.result_overrides(fields, pick, card, entry={"y": 1.0}, score={"home": 66.0, "away": 27.0})
    html = pc.render_card(fields, "data:,", overrides=over)
    body = html.split("</style>", 1)[1]
    assert '<div class="stamp win">WIN<small>+1.10u</small></div>' in body and "FINAL · 27–66" in body
    assert ">What happened<" in body and ">The verdict<" in body and "won by 39; -15 needed a win by more than 15" in body
    assert "PLAY #" not in html and "PICK #" not in html                               # never numbered (2026-10-16)
    assert cls["outcome"] == "win" and cls["verdict"] == "no_close" and cls["sim"]["right_side"] is True
    rec = pcr.postmortem(card, pick, cls)
    assert rec["label"] == "SYNDICATE PICK" and rec["actual"] == 39.0 and rec["verdict"] == "no_close" and rec["sim_view"] == "agrees"


def test_the_grader_renders_result_cards_and_the_engine_ledger(tmp_path):
    # Reachability: main() (not only the helper) writes the result card beside the day's cards and the postmortem ledger.
    root = tmp_path
    pick = _pick()
    (root / "cheatsheets" / "ncaaf").mkdir(parents=True)
    (root / "cheatsheets" / "ncaaf" / "2026-10-15.json").write_text(json.dumps({"sport": "ncaaf", "date": "2026-10-15",
                                                                                 "rows": [], "games": [], "picks": [pick]}), encoding="utf-8")
    (root / "cheatsheets" / "ncaaf" / "2026-10-15.reconciled.json").write_text(json.dumps(
        {"picks": {}, "scores": {"e1": {"home": 66.0, "away": 27.0}}}), encoding="utf-8")
    (root / "playcards").mkdir()
    card = {"card_id": "l2_d4b4", "pick_id": "l2_d4b4", "generated_at": "2026-10-15T14:15:00Z", "sport": "ncaaf", "date": "2026-10-15",
            "event_id": "e1", "matchup": pick["matchup"], "player": None, "commence_time": "2026-10-16T00:00:00Z", "kind": "game", "market": "spreads",
            "line": -15.0, "side": "home", "segment": "full", "price": 110, "book": "prophetx", "p_market": 0.5, "p_model": 0.56,
            "ev_market": 5.0, "result": {"y": 1.0, "units": 1.1}, "close": {}}
    (root / "playcards" / "ledger.jsonl").write_text(json.dumps(card) + "\n", encoding="utf-8")
    m = _script("grade_play_cards")
    m.main(["--data-root", str(root), "--no-results", "--now", "2026-10-17T12:00:00Z"])
    html = (root / "playcards" / "2026-10-15" / "01_ncaaf_l2_d4b4_result.html").read_text(encoding="utf-8")
    assert "stamp win" in html and "FINAL · 27–66" in html
    post = [json.loads(x) for x in (root / "playcards" / "postmortem.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(post) == 1 and post[0]["card_id"] == "l2_d4b4" and post[0]["outcome"] == "win"
