"""The club-code work list must print on a PARTIAL join, not only a zero one.

MEASURED 2026-08-25 15:56:35Z:

    BOARD_JOIN kalshi_markets=883 board_rows=1290 matched=5
      reasons={'event_not_on_our_board': 20, 'market_is_for_another_date': 512,
               'no_matching_board_row': 120, 'unreadable_title': 216,
               'would_match_but_wrong_date': 10}

Five player props matched, so `matched` was truthy and `JOIN_EVENTS` -- which
sat inside `if not report.get("matched")` -- never printed. Meanwhile all 20
GAME LINES failed event resolution and nothing said which club codes they were.

**A partial match is the normal state, and it was the one state that suppressed
the diagnostic.** Same shape as every other computed-but-unprinted number this
week, with the twist that the suppressing condition was success.

Note what `reasons` does NOT contain: `game_lines_disabled`. That counter fires
only for a game line whose event RESOLVED, so its absence means zero resolved --
and therefore that turning `SYNDICATE_KALSHI_GAME_LINES` on would price nothing.
The blocker is the alias, not the flag.
"""

from __future__ import annotations


def _report(matched, unmatched):
    return {
        "kalshi_markets": 883,
        "board_rows": 1290,
        "matched": matched,
        "reasons": {"event_not_on_our_board": 20},
        "kalshi_key_sample": [],
        "board_key_sample": [],
        "board_market_vocabulary": {},
        "unmatched_events": unmatched,
        "board_event_sample": ["mlb|tex|cws"],
    }


def _run(monkeypatch, capsys, report):
    from pipeline import kalshi_odds_refresh as mod

    monkeypatch.setattr(
        "syndicate.features.shared.kalshi_board_join.join_kalshi_to_board",
        lambda *a, **k: report,
    )
    mod.join_to_board([], [], selected_date="2026-08-25")
    return capsys.readouterr().out


def test_the_event_samples_print_when_SOME_markets_matched(monkeypatch, capsys):
    """The production case: five props paired, twenty game lines did not."""
    out = _run(monkeypatch, capsys, _report(5, [{"kalshi": "26AUG25TEXCWS", "ticker": "KX-1"}]))

    assert "JOIN_EVENTS" in out
    assert "26AUG25TEXCWS" in out
    # And the board's own blobs beside it, because the alias is the PAIR.
    assert "mlb|tex|cws" in out


def test_they_still_print_on_a_zero_match_join(monkeypatch, capsys):
    out = _run(monkeypatch, capsys, _report(0, [{"kalshi": "26AUG25TEXCWS"}]))
    assert "JOIN_EVENTS" in out


def test_nothing_is_printed_when_every_event_resolved(monkeypatch, capsys):
    """An empty work list is not a line. A `JOIN_EVENTS unmatched=[]` every
    build is noise in the log money moves through."""
    out = _run(monkeypatch, capsys, _report(5, []))
    assert "JOIN_EVENTS" not in out


# --- the real game ticker, supplied from the Kalshi UI ----------------------


def test_the_REAL_game_ticker_parses_to_its_team_pair():
    """`KXMLBGAME-26AUG251840BOSMIA-BOS`, taken from the venue's own market URL:

        kalshi.com/markets/kxmlbgame/professional-baseball-game/
          kxmlbgame-26AUG251840bosmia?op_market_ticker=KXMLBGAME-26AUG251840BOSMIA-BOS

    Shape: `<series>-<YYMONDD><HHMM><away><home>-<outcome>`. The middle segment
    is the event; the trailing segment is the team the `yes` side buys.

    Pinned from a REAL ticker rather than a constructed one, because every
    earlier assumption about this format in this thread came from a prop ticker
    (`KXMLBKS-26AUG242140MINATH-MINZMATTHEWS52-8`) and a game ticker is a
    different, shorter shape.
    """
    from syndicate.features.shared.kalshi_catalogue import event_blob_from_ticker

    assert event_blob_from_ticker("KXMLBGAME-26AUG251840BOSMIA-BOS") == "BOSMIA"


def test_that_blob_resolves_to_the_right_game_and_the_right_SIDE():
    """The blob is `AWAY+HOME`, so getting it backwards buys the opponent.
    Asserted on both fields, not just `status: ok`."""
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    games = [
        {"away_team": "Boston Red Sox", "home_team": "Miami Marlins", "event_id": "evt-bos-mia"},
        {"away_team": "Texas Rangers", "home_team": "Chicago White Sox", "event_id": "evt-tex-cws"},
    ]
    got = match_event_blob("BOSMIA", games, sport="mlb")

    assert got["status"] == "ok"
    assert got["away_team"] == "Boston Red Sox"
    assert got["home_team"] == "Miami Marlins"
    assert got["event_id"] == "evt-bos-mia"


def test_a_blob_for_a_game_we_do_not_carry_is_no_match_not_a_guess():
    """`no_match` is the ALIAS work list, and softening it into a nearest
    neighbour is how a bet reaches the wrong game."""
    from syndicate.features.shared.kalshi_catalogue import match_event_blob

    games = [{"away_team": "Boston Red Sox", "home_team": "Miami Marlins"}]
    assert match_event_blob("TEXCWS", games, sport="mlb")["status"] == "no_match"
