"""Play-card grader: EV at the closing line from the quote logs, the result from production's grader, the public record."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from syndicate.features.shared.opportunity_signals import devig

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location("grade_play_cards", ROOT / "scripts" / "grade_play_cards.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _card(**extra):
    card = {"card_id": "abc123", "generated_at": "2026-10-14T23:40:00Z", "sport": "nfl", "date": "2026-10-14",
            "event_id": "e1", "matchup": "Arizona Cardinals @ Los Angeles Rams", "commence_time": "2026-10-18T20:05:00Z",
            "player": "Tyler Allgeier", "market": "Receptions", "line": 2.5, "side": "under", "price": -139,
            "book": "betonlineag", "books_quoting": 4, "p_market": 0.6018, "p_model": 0.5456, "ev_market": 3.0,
            "result": None, "close": None}
    card.update(extra)
    return card


def _q(book, sel, price, t, **extra):
    q = {"event_id": "e1", "market": "Receptions", "player_name": "Tyler Allgeier", "line": 2.5, "bookmaker": book,
         "selection": sel, "price": price, "captured_at": t}
    q.update(extra)
    return q


def test_closing_fair_is_the_median_shin_fair_of_each_books_last_pregame_pair():
    m = _module()
    quotes = [
        _q("dk", "under", -150, "2026-10-18T12:00:00Z"), _q("dk", "over", 120, "2026-10-18T12:00:00Z"),
        _q("dk", "under", -160, "2026-10-18T19:00:00Z"), _q("dk", "over", 130, "2026-10-18T19:00:00Z"),   # dk's last pair
        _q("fd", "under", -155, "2026-10-18T18:00:00Z"), _q("fd", "over", 125, "2026-10-18T18:00:00Z"),
        _q("mgm", "under", -170, "2026-10-18T19:30:00Z"), _q("mgm", "over", 140, "2026-10-18T19:30:00Z"),
        _q("dk", "under", -300, "2026-10-18T21:00:00Z"), _q("dk", "over", 240, "2026-10-18T21:00:00Z"),  # in-play: ignored
        _q("czr", "under", -165, "2026-10-18T19:00:00Z"),                                                  # one side: no pair
        _q("fd", "under", -500, "2026-10-18T19:00:00Z", line=3.5),                                        # other line
        _q("fd", "under", -500, "2026-10-18T19:00:00Z", player_name="Bijan Robinson"),                    # other player
    ]
    close = m.closing_fair(quotes, _card())
    fairs = sorted(dict(zip(["over", "under"], devig([o, u], method="shin")))["under"]
                   for o, u in ((130, -160), (125, -155), (140, -170)))
    assert close["books"] == 3 and close["p_close"] == round(fairs[1], 4)
    assert close["ev_close_pct"] == round(100 * (fairs[1] * (1 + 100 / 139) - 1), 2)
    assert close["clv_pp"] == round(100 * (fairs[1] - 0.6018), 2) and close["best_close_price"] == -155
    assert m.closing_fair([], _card()) is None and m.closing_fair(quotes, _card(commence_time=None)) is None


def test_match_key_uses_the_population_keys_normalisation():
    m = _module()
    assert m.match_key("NFL", "Receptions", "Tyler Allgeier", "Under", 2.5) == m.match_key("nfl", "receptions ", "tyler allgeier", "under", "2.5")
    assert m.match_key("soccer", "player_goal_scorer_anytime", "Kobe Franklin", "yes", None)[-1] is None


def test_results_come_from_productions_grader_full_segment_only(monkeypatch, tmp_path):
    m = _module()
    pulls = []

    class FakeSrb:
        @staticmethod
        def main(argv):
            pulls.append(argv[argv.index("--start") + 1])
            out = Path(argv[argv.index("--out") + 1])
            rows = [{"sport": "nfl", "market": "receptions", "player": "tyler allgeier", "side": "under", "line": 2.5,
                     "segment": "full", "y": 0.0, "game": "ARI @ LAR"},
                    {"sport": "nfl", "market": "receptions", "player": "tyler allgeier", "side": "under", "line": 2.5,
                     "segment": "1h", "y": 1.0, "game": "g"},                                   # another segment, read last
                    {"sport": "nfl", "market": "receptions", "player": "bijan robinson", "side": "over", "line": 4.5,
                     "segment": "full", "y": None, "game": "g"}]                               # not final yet
            out.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            return 0

    real_load = m._load
    monkeypatch.setattr(m, "_load", lambda name: FakeSrb if name == "score_ranking_backtest" else real_load(name))
    res = m.results_for([_card(), _card(card_id="b", player="Bijan Robinson", side="over", line=4.5, price=110)], work=tmp_path)
    assert sorted(set(pulls)) == ["2026-10-14", "2026-10-18"]                  # the card's date and the game's date
    assert res == {"abc123": {"y": 0.0, "units": -1.0, "graded_game": "ARI @ LAR"}}


def test_units_are_paid_at_the_card_price(monkeypatch, tmp_path):
    m = _module()

    class FakeSrb:
        @staticmethod
        def main(argv):
            Path(argv[argv.index("--out") + 1]).write_text(json.dumps(
                {"sport": "nfl", "market": "receptions", "player": "tyler allgeier", "side": "under", "line": 2.5,
                 "segment": "full", "y": 1.0}) + "\n", encoding="utf-8")
            return 0

    real_load = m._load
    monkeypatch.setattr(m, "_load", lambda name: FakeSrb if name == "score_ranking_backtest" else real_load(name))
    assert m.results_for([_card()], work=tmp_path)["abc123"]["units"] == pytest.approx(0.719, abs=1e-3)


def test_main_settles_only_started_games_and_writes_the_record(monkeypatch, tmp_path):
    m = _module()
    led = tmp_path / "playcards" / "ledger.jsonl"
    led.parent.mkdir(parents=True)
    future = _card(card_id="later", date="2026-10-15", commence_time="2999-01-01T00:00:00Z")
    led.write_text(json.dumps(_card(date="2026-10-15")) + "\n" + json.dumps(future) + "\n", encoding="utf-8")
    monkeypatch.setattr(m._npf(), "load_quotes", lambda root, sport, start, end: [
        _q("dk", "under", -160, "2026-10-18T19:00:00Z"), _q("dk", "over", 130, "2026-10-18T19:00:00Z")])
    monkeypatch.setattr(m, "results_for", lambda cards, work: {"abc123": {"y": 1.0, "units": 0.719, "graded_game": "g"}})
    assert m.main(["--data-root", str(tmp_path), "--now", "2026-10-18T23:00:00Z"]) == 0   # 2h55m after kickoff: too soon
    assert json.loads(led.read_text(encoding="utf-8").splitlines()[0])["result"] is None
    assert m.main(["--data-root", str(tmp_path), "--now", "2026-10-19T12:00:00Z"]) == 0
    cards = {c["card_id"]: c for c in map(json.loads, led.read_text(encoding="utf-8").splitlines())}
    assert cards["abc123"]["result"]["y"] == 1.0 and cards["abc123"]["close"]["books"] == 1
    assert cards["later"]["result"] is None and cards["later"]["close"] is None
    record = (tmp_path / "playcards" / "record.html").read_text(encoding="utf-8")
    assert "1-0" in record and "+0.72u" in record and "PENDING" in record and "WIN" in record


def test_beta_cards_stay_out_of_the_public_record(tmp_path):
    m = _module()
    official = _card(card_id="o1", date="2026-10-15", result={"y": 1.0, "units": 0.719}, close={"ev_close_pct": 2.0})
    beta = _card(card_id="b1", date="2026-10-14", result={"y": 0.0, "units": -1.0}, close={"ev_close_pct": -5.0})
    out = tmp_path / "record.html"
    m.render_record([official, beta], out)
    html = out.read_text(encoding="utf-8")
    assert "1-0" in html and "+0.72u" in html and "+2.00%" in html and "(1 cards)" in html


def test_a_syndicate_pick_card_grades_on_its_own_segment(monkeypatch, tmp_path):
    # 2026-10-15: pick graphics for the board's suggested opps -- a 1st-3-innings moneyline settles on that segment.
    m = _module()

    class FakeSrb:
        @staticmethod
        def main(argv):
            rows = [{"sport": "mlb", "market": "h2h", "player": None, "side": "away", "line": None, "segment": "first3", "y": 1.0, "game": "mlb|e7"},
                    {"sport": "mlb", "market": "h2h", "player": None, "side": "away", "line": None, "segment": "full", "y": 0.0, "game": "mlb|e7"}]
            Path(argv[argv.index("--out") + 1]).write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            return 0

    real_load = m._load
    monkeypatch.setattr(m, "_load", lambda name: FakeSrb if name == "score_ranking_backtest" else real_load(name))
    card = _card(card_id="l2_129acb8c9c927fb9", pick_id="l2_129acb8c9c927fb9", sport="mlb", event_id="e7", player=None,
                 market="h2h", side="away", line=None, segment="first3", price=138, commence_time="2026-10-16T00:00:00Z")
    assert m.results_for([card], work=tmp_path) == {"l2_129acb8c9c927fb9": {"y": 1.0, "units": 1.38, "graded_game": "mlb|e7"}}


def test_closes_are_read_from_a_gzipped_day_log_too(tmp_path):
    # 10-23: the NBA day log is gzipped the next evening, and reading only `.jsonl` turned every later reconcile's closes
    # into `no_close` (10-21: 60 closes -> 0). Plain, gzipped, and neither.
    import gzip

    m = _module()
    quotes = [_q("dk", "under", -160, "2026-10-18T19:00:00Z"), _q("dk", "over", 130, "2026-10-18T19:00:00Z")]
    book = tmp_path / "nfl_source" / "tracking" / "book_quotes"
    book.mkdir(parents=True)
    body = "".join(json.dumps(q) + "\n" for q in quotes)
    card = _card(date="2026-10-18")
    (book / "2026-10-18.jsonl").write_text(body, encoding="utf-8")
    plain = m.closing_fairs(tmp_path, "nfl", "2026-10-18", [card])
    (book / "2026-10-18.jsonl").unlink()
    assert m.closing_fairs(tmp_path, "nfl", "2026-10-18", [card]) == {}            # off: no file, no close
    with gzip.open(book / "2026-10-18.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(body)
    packed = m.closing_fairs(tmp_path, "nfl", "2026-10-18", [card])
    assert packed and packed == plain and packed["abc123"]["books"] == 1
