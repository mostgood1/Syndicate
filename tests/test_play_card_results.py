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


def test_a_miss_is_placed_against_the_sims_own_range():
    prop = {"kind": "prop", "side": "over", "line": 50.5, "projected": 58.0, "projected_sd": 15.0}
    j = pcr.sim_judgement(prop, "SYNDICATE PICK", 40.0)
    assert j["z"] == -1.2 and "outside the sim's own range, 1.2 sd" in j["text"]
    assert "inside the sim's own range" in pcr.sim_judgement(prop, "SYNDICATE PICK", 49.0)["text"]
    # no mean on file: the side it backed is judged, never an invented error
    side_only = pcr.sim_judgement({"kind": "prop", "side": "over", "line": 2.5, "p_model": 0.58}, "SYNDICATE PICK", 4.0)
    assert side_only["right_side"] is True and side_only["error"] is None and "had the over at 58%" in side_only["text"]


def _sheet():
    from syndicate.features.shared import cheat_sheets as cs

    row = lambda player, verdict="value", p_model=0.60: {
        "player": player, "event_id": "e1", "market": "Receptions", "line": 4.5, "side": "over", "books_quoting": 6,
        "projected": 5.6, "check": {"verdict": verdict, "ev_market": 3.0, "price": 110, "book": "fanduel",
                                    "p_market": 0.50, "p_model": p_model, "reasons": []}}
    rows = [row("Featured Win"), row("Featured Loss", p_model=0.40), row("Not Featured"), row("Ungraded")]
    pick = {"pick_id": "l2_x", "kind": "game", "event_id": "e1", "market": "spreads", "side": "home", "line": -3.5,
            "segment": "full", "price": -110, "p_model": 0.58, "p_market": 0.5, "ev_pct": 2.5, "label": "SYNDICATE PICK",
            "player_name": None, "matchup": "A @ B", "home_team": "B", "away_team": "A"}
    sheet = {"sport": "nfl", "date": "2026-10-15", "rows": rows, "picks": [pick], "game_lines": [],
             "sections": {"value": [0, 1, 3], "every_prop": [0, 1, 2, 3]}, "games": [{"event_id": "e1", "commence_time": "x"}]}
    rec = {"props": {cs.prop_result_key(rows[0]): {"y": 1.0, "v": 7.0}, cs.prop_result_key(rows[1]): {"y": 0.0, "v": 2.0},
                     cs.prop_result_key(rows[2]): {"y": 1.0, "v": 6.0}},
           "picks": {cs.pick_result_key(pick): {"y": 0.0}}, "scores": {"e1": {"home": 20.0, "away": 21.0}}}
    return sheet, rec


def test_every_graded_featured_bet_lands_in_the_engine_ledger():
    sheet, rec = _sheet()
    seen = []
    out = pcr.sheet_postmortem(sheet, rec, usage=lambda card, item: seen.append(card["player"]) or None,
                               closes={})
    players = [r.get("player") for r in out]
    assert "Featured Win" in players and "Featured Loss" in players
    assert "Not Featured" not in players and "Ungraded" not in players            # every_prop is not featured; no result
    win = next(r for r in out if r["player"] == "Featured Win")
    assert win["label"] == "SYNDICATE PICK" and win["sim"]["right_side"] is True and win["actual"] == 7.0
    assert win["result"]["units"] == 1.1 and win["sections"] == ["value"] and win["source"] == "sheet"
    loss = next(r for r in out if r["player"] == "Featured Loss")
    assert loss["label"] == "PRICE PLAY" and loss["sim"] is None                  # the sim is judged only where it backed it
    pick = next(r for r in out if r.get("pick_id") == "l2_x")
    assert pick["outcome"] == "loss" and pick["actual"] == -1.0 and pick["sim"]["right_side"] is False
    assert seen == ["Featured Win", "Featured Loss"]                             # usage asked for props only
    s = pcr.engine_summary(out)
    assert s["graded"] == 3 and s["sim_judged"] == 2 and s["sim_right_side"] == 1 and s["sim_mean_error"] == 1.4


def test_the_reconcile_writes_the_engine_ledger_beside_the_sheet(tmp_path):
    # Reachability: the reconcile's own hook writes <sport>/<date>.postmortem.jsonl.
    sheet, rec = _sheet()
    d = tmp_path / "cheatsheets" / "nfl"
    d.mkdir(parents=True)
    path = d / "2026-10-15.json"
    path.write_text("{}", encoding="utf-8")
    summary = _script("reconcile_cheat_sheets").write_postmortem(tmp_path, path, sheet, rec, "2026-10-15")
    lines = (d / "2026-10-15.postmortem.jsonl").read_text(encoding="utf-8").splitlines()
    assert summary["graded"] == 3 and len(lines) == 3
