"""Manual portfolios. `[user request 2026-09-10, lane portfolio-login-multibook]`

Bets placed at other sportsbooks, entered and settled by hand, beside bets
logged from the board slip. The design constraint these tests pin hardest:
HAND-ENTERED BETS NEVER REACH `prediction_ledger.json`, because the
refresh-worker's reconciliation matcher would grade a typed bet off any result
row that shares a sport with it.
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from syndicate.app import app as flask_app
from syndicate.features import prediction_ledger
from syndicate.features.prediction_ledger import clear_result, load_all_predictions, record_prediction, record_result
from syndicate.features.shared import portfolio_auth
from syndicate.features.shared import portfolio_books as books

BET = {
    "sportsbook": "DraftKings",
    "sport": "nfl",
    "event": "Chiefs @ Ravens",
    "market": "Spread",
    "selection": "Chiefs -3.5",
    "odds": "-110",
    "stake": "110",
}


@pytest.fixture
def stores(monkeypatch, tmp_path):
    for key in (
        "SYNDICATE_PORTFOLIO_USERNAME",
        "SYNDICATE_PORTFOLIO_PASSWORD",
        "SYNDICATE_PORTFOLIO_PASSWORD_HASH",
        "SYNDICATE_PORTFOLIO_AUTH",
        "RENDER",
        "RENDER_EXTERNAL_URL",
        "RENDER_SERVICE_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    store = tmp_path / "portfolio_books.json"
    ledger = tmp_path / "prediction_ledger.json"
    monkeypatch.setattr(books, "store_path", lambda: store)
    monkeypatch.setattr(prediction_ledger, "_default_ledger_path", lambda: ledger)
    monkeypatch.setattr(books, "central_today", lambda: "2026-09-10")
    assert portfolio_auth.auth_mode() == "off"
    return {"store": store, "ledger": ledger}


@pytest.fixture
def client():
    return flask_app.test_client()


def _slip(stake=10.0, portfolio_id=None, **overrides):
    fields = {"sport": "mlb", "market": "moneyline", "selection": "Cubs ML", "odds": 120, "stake": stake}
    fields.update(overrides)
    return record_prediction(portfolio_id=portfolio_id, **fields)


# ---------------------------------------------------------------- books


def test_the_default_book_always_exists_and_cannot_be_deleted(stores):
    assert [b["id"] for b in books.list_books()] == [books.DEFAULT_BOOK_ID]
    assert books.get_book("manual")["name"] == "Other books"
    with pytest.raises(books.InputError):
        books.delete_book("manual")
    books.rename_book("manual", "Retail books")
    assert books.get_book("manual")["name"] == "Retail books"
    assert [b["id"] for b in books.list_books()] == ["manual"]


def test_creating_books_gives_stable_unique_ids(stores):
    fanduel = books.create_book("  FanDuel   parlays ")
    assert fanduel == {**fanduel, "id": "fanduel-parlays", "name": "FanDuel parlays"}
    # A name that would collide with a real /portfolio/<x> path gets another id.
    assert books.create_book("Live")["id"] == "live-2"
    assert books.create_book("Paper")["id"] == "paper-2"
    with pytest.raises(books.InputError):
        books.create_book("fanduel PARLAYS")
    with pytest.raises(books.InputError):
        books.create_book("   ")
    assert [b["id"] for b in books.list_books()] == ["manual", "fanduel-parlays", "live-2", "paper-2"]


def test_a_book_holding_bets_cannot_be_deleted(stores):
    book = books.create_book("Caesars")
    bet = books.add_bet(book["id"], BET)
    with pytest.raises(books.InputError, match="1 bet"):
        books.delete_book(book["id"])
    books.delete_bet(book["id"], bet["id"])
    _slip(portfolio_id=book["id"])
    with pytest.raises(books.InputError, match="1 bet"):
        books.delete_book(book["id"])


def test_deleting_an_empty_book_works(stores):
    book = books.create_book("Temp")
    books.delete_book(book["id"])
    assert books.get_book(book["id"]) is None


# ---------------------------------------------------------------- input


@pytest.mark.parametrize(
    "raw, expected",
    [("-110", -110.0), ("+150", 150.0), ("150", 150.0), ("-100", -100.0), ("even", 100.0), (" +2500 ", 2500.0)],
)
def test_american_odds_are_parsed(raw, expected):
    assert books.parse_american_odds(raw) == expected


@pytest.mark.parametrize("raw", ["1.91", "-50", "99", "0", "abc", "", "+-110", "nan"])
def test_anything_that_is_not_american_odds_is_refused_not_converted(raw):
    with pytest.raises(books.InputError) as caught:
        books.parse_american_odds(raw)
    assert "odds" in caught.value.errors


def test_every_bad_field_is_reported_at_once(stores):
    with pytest.raises(books.InputError) as caught:
        books.add_bet("manual", {"sport": "nfl", "odds": "1.9", "stake": "0"})
    assert set(caught.value.errors) == {"sportsbook", "selection", "odds", "stake"}
    assert not stores["store"].exists()


def test_a_bet_defaults_to_placed_today(stores):
    bet = books.add_bet("manual", BET)
    assert bet["placed_on"] == "2026-09-10"
    assert bet["odds"] == -110.0 and bet["stake"] == 110.0 and bet["result"] is None


# ---------------------------------------------------------------- settlement


@pytest.mark.parametrize(
    "odds, stake, outcome, cashout, pnl",
    [
        ("-110", "110", "win", None, 100.0),
        ("+150", "20", "win", None, 30.0),
        ("-110", "110", "loss", None, -110.0),
        ("-110", "110", "push", None, 0.0),
        ("-110", "110", "void", None, 0.0),
        ("+150", "20", "cashout", "35", 15.0),
        ("+150", "20", "cashout", "0", -20.0),
    ],
)
def test_settling_prices_pnl_from_the_bets_own_odds(stores, odds, stake, outcome, cashout, pnl):
    bet = books.add_bet("manual", {**BET, "odds": odds, "stake": stake})
    settled = books.settle_bet("manual", bet["id"], outcome, cashout)
    assert settled["result"]["outcome"] == outcome
    assert settled["result"]["pnl"] == pnl


def test_reopen_and_delete(stores):
    bet = books.add_bet("manual", BET)
    books.settle_bet("manual", bet["id"], "win")
    books.reopen_bet("manual", bet["id"])
    row = books.build_book_view("manual")["rows"][0]
    assert (row["status"], row["pnl"]) == ("pending", None)
    books.delete_bet("manual", bet["id"])
    assert books.build_book_view("manual")["rows"] == []


def test_a_bet_cannot_be_acted_on_through_another_book(stores):
    other = books.create_book("Other")
    bet = books.add_bet("manual", BET)
    with pytest.raises(books.BookNotFound):
        books.settle_bet(other["id"], bet["id"], "win")


def test_hand_entered_bets_never_reach_the_prediction_ledger(stores):
    """THE design constraint. The worker's reconciliation matcher accepts the
    first result row sharing ANY key with a bet; a typed bet in that ledger
    could be graded off another game."""
    bet = books.add_bet("manual", BET)
    books.settle_bet("manual", bet["id"], "loss")
    assert load_all_predictions() == []
    assert not stores["ledger"].exists()


# ---------------------------------------------------------------- the view


def test_the_view_merges_slip_bets_into_the_right_book(stores):
    fanduel = books.create_book("FanDuel")
    legacy = _slip(selection="Legacy ML")                            # no portfolio_id: default book
    tagged = _slip(selection="Tagged ML", portfolio_id=fanduel["id"])
    orphan = _slip(selection="Orphan ML", portfolio_id="deleted-book")  # a book that no longer exists
    record_prediction(sport="mlb", market="moneyline", selection="Auto-tracked", odds=110)  # stakeless: never shown
    books.add_bet("manual", BET)

    default_view = books.build_book_view("manual")
    assert {r["id"] for r in default_view["rows"] if r["source"] == "slip"} == {legacy["id"], orphan["id"]}
    assert default_view["sources"] == {"manual": 1, "slip": 2}
    assert [r["id"] for r in books.build_book_view(fanduel["id"])["rows"]] == [tagged["id"]]


def test_summary_roi_excludes_voids_and_win_rate_counts_only_decided(stores):
    rows = []
    for odds, stake, outcome in (("-110", "110", "win"), ("+100", "50", "loss"), ("-110", "30", "void"), ("+200", "10", None)):
        bet = books.add_bet("manual", {**BET, "odds": odds, "stake": stake})
        if outcome:
            books.settle_bet("manual", bet["id"], outcome)
        rows.append(bet)
    s = books.build_book_view("manual")["summary"]
    assert s["counts"]["win"] == 1 and s["counts"]["loss"] == 1 and s["counts"]["void"] == 1
    assert s["pnl"] == 50.0
    assert s["staked_settled"] == 160.0
    assert s["roi"] == pytest.approx(50.0 / 160.0)
    assert s["win_rate"] == 0.5
    assert (s["pending_count"], s["open_stake"], s["open_to_win"]) == (1, 10.0, 20.0)
    assert s["by_sportsbook"][0]["key"] == "DraftKings"


def test_a_corrupt_store_is_refused_never_overwritten(stores, client):
    stores["store"].write_text("{not json", encoding="utf-8")
    with pytest.raises(books.BookStoreError):
        books.add_bet("manual", BET)
    with pytest.raises(books.BookStoreError):
        books.create_book("Anything")
    assert stores["store"].read_text(encoding="utf-8") == "{not json"
    page = client.get("/portfolio/books/manual")
    assert page.status_code == 200
    assert "couldn't be read" in page.get_data(as_text=True)


# ---------------------------------------------------------------- slip bets settled by hand


def test_a_slip_bet_can_be_settled_reopened_and_deleted_from_the_page(stores, client):
    slip = _slip(stake=10.0, odds=120)
    url = f"/portfolio/books/manual/bets/{slip['id']}"
    assert client.post(f"{url}/settle", data={"source": "slip", "outcome": "win"}).status_code == 303
    assert load_all_predictions()[0]["result"]["outcome"] == "win"
    assert load_all_predictions()[0]["result"]["pnl"] == 12.0

    response = client.post(f"{url}/settle", data={"source": "slip", "outcome": "loss"})
    assert "Reopen it first" in parse_qs(urlsplit(response.headers["Location"]).query)["error"][0]

    assert client.post(f"{url}/reopen", data={"source": "slip"}).status_code == 303
    assert "result" not in load_all_predictions()[0]
    assert client.post(f"{url}/delete", data={"source": "slip"}).status_code == 303
    assert load_all_predictions() == []


def test_a_slip_cash_out_is_stored_inside_the_ledgers_closed_vocabulary(stores):
    slip = _slip(stake=20.0, odds=150)
    books.settle_slip_bet("manual", slip["id"], "cashout", "26")
    result = load_all_predictions()[0]["result"]
    assert (result["outcome"], result["pnl"]) == ("win", 6.0)


def test_clear_result_undoes_a_settlement_and_is_idempotent(stores):
    slip = _slip()
    record_result(prediction_id=slip["id"], outcome="loss", pnl=-10.0)
    assert clear_result(slip["id"]) is True
    assert "result" not in load_all_predictions()[0]
    assert clear_result(slip["id"]) is False
    assert clear_result("") is False


def test_portfolio_id_survives_the_workers_write_path(stores):
    """The refresh-worker writes this ledger through `record_result`. A field
    it dropped would re-file every settled slip bet into the default book."""
    slip = _slip(portfolio_id="fanduel")
    record_result(prediction_id=slip["id"], outcome="win", pnl=12.0)
    assert load_all_predictions()[0]["portfolio_id"] == "fanduel"


# ---------------------------------------------------------------- HTTP


def test_the_bet_endpoint_files_into_a_known_book_and_refuses_an_unknown_one(stores, client):
    book = books.create_book("BetMGM")
    ok = client.post("/api/portfolio/bets", json={"sport": "nba", "market": "moneyline", "selection": "Knicks ML", "odds": -120, "stake": 12, "portfolio_id": book["id"]})
    assert ok.status_code == 200
    assert ok.get_json()["bet"]["portfolio_id"] == book["id"]
    bad = client.post("/api/portfolio/bets", json={"sport": "nba", "market": "moneyline", "selection": "Knicks ML", "odds": -120, "stake": 12, "portfolio_id": "nope"})
    assert bad.status_code == 400
    assert len(load_all_predictions()) == 1
    plain = client.post("/api/portfolio/bets", json={"sport": "nba", "market": "moneyline", "selection": "Heat ML", "odds": 110, "stake": 5})
    assert plain.get_json()["bet"]["portfolio_id"] is None


def test_the_book_page_lists_every_portfolio_and_takes_a_bet(stores, client):
    books.create_book("FanDuel")
    page = client.get("/portfolio/books/manual").get_data(as_text=True)
    for label in ("Kalshi + Polymarket", "Paper", "Other books", "FanDuel"):
        assert label in page, label
    assert 'href="/portfolio"' in page and 'href="/portfolio/paper"' in page and 'href="/portfolio/books/fanduel"' in page
    assert 'action="/portfolio/books/manual/bets"' in page

    response = client.post("/portfolio/books/manual/bets", data=BET)
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["Location"]).query)["msg"] == ["added"]
    page = client.get("/portfolio/books/manual?msg=added").get_data(as_text=True)
    assert "Chiefs -3.5" in page and "Bet added." in page and "DraftKings" in page


def test_a_refused_form_keeps_what_was_typed_and_says_why(stores, client):
    response = client.post("/portfolio/books/manual/bets", data={**BET, "odds": "1.91"})
    assert response.status_code == 400
    body = response.get_data(as_text=True)
    assert "isn&#39;t American odds" in body or "isn't American odds" in body
    assert 'value="Chiefs -3.5"' in body
    assert not stores["store"].exists()


def test_an_unknown_book_is_a_404(stores, client):
    assert client.get("/portfolio/books/nope").status_code == 404
    assert client.get("/api/portfolio/books/nope").status_code == 404
    assert client.post("/portfolio/books/nope/bets", data=BET).status_code == 404


def test_books_can_be_created_and_listed_over_http(stores, client):
    response = client.post("/portfolio/books", data={"name": "Hard Rock"})
    assert urlsplit(response.headers["Location"]).path == "/portfolio/books/hard-rock"
    listing = client.get("/api/portfolio/books").get_json()
    assert listing["default"] == "manual"
    assert [b["id"] for b in listing["books"]] == ["manual", "hard-rock"]
    assert [b["id"] for b in listing["builtin"]] == ["live", "paper"]
