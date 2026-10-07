"""Venue-quote matching memo (lane `web-restart-healthz`, 2026-10-07).

py-spy on the fleet: the today shortlist refresh spent 58% in the venue-quote fan-in, 27% in
`_kalshi_game_token` (every split of every ticker's event blob tried against the schedule, once
per market though many markets share a blob) and 13.6% re-tokenising every game per Polymarket
row. Both are now computed once per pass. The answers must not change.
"""

from __future__ import annotations

import syndicate.features.shared.kalshi_catalogue as kc
import syndicate.features.shared.venue_quote_adapters as vqa

GAMES = [
    {"event_id": "1", "home_team": "Tampa Bay Rays", "away_team": "San Diego Padres"},
    {"event_id": "2", "home_team": "New York Yankees", "away_team": "Boston Red Sox"},
]
TICKERS = [
    "KXMLBTOTAL-26AUG291610SDTB-14", "KXMLBTOTAL-26AUG291610SDTB-15", "KXMLBSPREAD-26AUG291610SDTB-TB2",
    "KXMLBTOTAL-26AUG291910BOSNYY-9", "KXMLBTOTAL-26AUG291910BOSNYY-10", "KXMLBGAME-26AUG291910BOSNYY-NYY",
    "NOT-A-TICKER", "", None,
]


def test_memo_answers_exactly_like_the_uncached_path(monkeypatch):
    calls = {"n": 0}
    real = kc.match_event_blob

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(kc, "match_event_blob", counting)
    expected = [vqa._kalshi_game_token_uncached(t, "mlb", GAMES) for t in TICKERS]
    uncached_calls = calls["n"]
    calls["n"] = 0
    memo: dict = {}
    got = [vqa._kalshi_game_token(t, "mlb", GAMES, memo=memo) for t in TICKERS]
    assert got == expected
    assert calls["n"] < uncached_calls          # 6 game tickers share 2 blobs
    assert [vqa._kalshi_game_token(t, "mlb", GAMES) for t in TICKERS] == expected   # no memo: unchanged


def test_no_games_is_still_none():
    assert vqa._kalshi_game_token("KXMLBTOTAL-26AUG291610SDTB-14", "mlb", [], memo={}) is None
