"""The Kalshi game-line resolver memo answers exactly like the unmemoised path.

Lane `web-restart-healthz` 2026-10-07 (loan from `mlb-doubleheader-e2e`): py-spy on the
fleet had `_resolve_event` at 96% of a ~500 s board join. Every one of 6,000 markets
rescanned ~5,600 board rows to rebuild the same distinct-games list, then re-matched
an event blob most markets share. The join now builds the games once and memoises per
(blob, series family, sport, ticker start). The ticker start is in the key, so the two
halves of a doubleheader can never share an answer.
"""

from __future__ import annotations

import syndicate.features.shared.kalshi_board_join as kbj
import syndicate.features.shared.kalshi_catalogue as kc


def _rows():
    games = [
        ("early", "Detroit Tigers", "Cleveland Guardians", "2026-09-04T18:11:00Z"),
        ("late", "Detroit Tigers", "Cleveland Guardians", "2026-09-04T23:16:00Z"),
        ("sea", "Athletics", "Seattle Mariners", "2026-09-05T02:11:00Z"),
        ("tb", "San Diego Padres", "Tampa Bay Rays", "2026-09-04T20:10:00Z"),
    ]
    rows = []
    for event_id, away, home, start in games:
        for market in ("h2h", "totals", "spreads", "pitcher_strikeouts"):
            rows.append({"event_id": event_id, "away_team": away, "home_team": home,
                         "commence_time": start, "market": market, "sport": "mlb"})
    rows.append({"event_id": "", "home_team": "Nobody", "away_team": "Noone", "market": "h2h"})
    return rows


MARKETS = [
    {"ticker": t, "series": t.split("-")[0]}
    for t in (
        "KXMLBGAME-26SEP041410DETCLEG1-DET", "KXMLBGAME-26SEP041410DETCLEG1-CLE",
        "KXMLBGAME-26SEP041915DETCLEG2-DET", "KXMLBTOTAL-26SEP041915DETCLEG2-8",
        "KXMLBTOTAL-26SEP041410DETCLEG1-8", "KXMLBTOTAL-26SEP041410DETCLEG1-9",
        "KXMLBGAME-26SEP041410DETCLE-DET",          # no half named: ambiguous
        "KXMLBTOTAL-26SEP042210ATHSEA-7", "KXMLBTOTAL-26SEP042210ATHSEA-8",
        "KXMLBSPREAD-26SEP041610SDTB-TB2", "KXMLBTOTAL-26SEP041610SDTB-9",
        "KXMLBTOTAL-26SEP041610NYYBOS-9",           # not on our board
        "NOT-A-TICKER", "",
    )
]


def test_memoised_answers_equal_the_unmemoised_ones_and_scan_less(monkeypatch):
    rows = _rows()
    calls = {"n": 0}
    real = kc.match_event_blob

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(kc, "match_event_blob", counting)
    expected = [kbj._resolve_event(m, rows, None) for m in MARKETS]
    plain = calls["n"]
    calls["n"] = 0
    games, memo = kbj._distinct_games(rows), {}
    got = [kbj._resolve_event(m, rows, None, games=games, memo=memo) for m in MARKETS]
    assert got == expected
    assert calls["n"] < plain                      # markets of one game share a blob
    # A second pass is all memo hits, and still identical.
    calls["n"] = 0
    assert [kbj._resolve_event(m, rows, None, games=games, memo=memo) for m in MARKETS] == expected
    assert calls["n"] == 0


def test_the_doubleheader_halves_still_resolve_to_themselves_through_the_memo():
    rows = _rows()
    games, memo = kbj._distinct_games(rows), {}
    by_ticker = {m["ticker"]: kbj._resolve_event(m, rows, None, games=games, memo=memo) for m in MARKETS}
    assert by_ticker["KXMLBGAME-26SEP041410DETCLEG1-DET"].get("event_id") == "early"
    assert by_ticker["KXMLBTOTAL-26SEP041915DETCLEG2-8"].get("event_id") == "late"


def test_a_memo_hit_is_a_copy_so_a_caller_cannot_poison_it():
    rows = _rows()
    games, memo = kbj._distinct_games(rows), {}
    first = kbj._resolve_event(MARKETS[0], rows, None, games=games, memo=memo)
    first["event_id"] = "tampered"
    again = kbj._resolve_event(MARKETS[1], rows, None, games=games, memo=memo)
    assert again.get("event_id") != "tampered"


def test_distinct_games_is_first_row_per_event_and_skips_blank_ids():
    games = kbj._distinct_games(_rows())
    assert [g["event_id"] for g in games] == ["early", "late", "sea", "tb"]
    assert set(games[0]) == {"event_id", "home_team", "away_team", "commence_time"}


def test_the_join_uses_the_memo_and_its_report_is_unchanged(monkeypatch):
    """End-to-end: the join's report with the memo equals the report with it disabled."""
    import json

    rows = _rows()
    names = {"DET": "Detroit Tigers", "CLE": "Cleveland Guardians"}
    markets = []
    for m in MARKETS:
        series, _, tail = m["ticker"].rpartition("-")
        if m["series"] == "KXMLBGAME":
            title = f"{names[tail]} wins?"
        elif m["series"] == "KXMLBTOTAL":
            title = f"Over {int(tail) - 0.5} runs scored?"
        else:
            continue
        markets.append(dict(m, title=title, yes_ask_dollars=0.52, no_ask_dollars=0.5))
    with_memo = kbj.join_kalshi_to_board(list(markets), [dict(r) for r in rows], selected_date="2026-09-04")

    real = kbj._resolve_event
    seen = {"memo_kwarg": 0}

    def no_memo(market, board_rows, code_names=None, **kw):
        if kw.get("memo") is not None:
            seen["memo_kwarg"] += 1
        return real(market, board_rows, code_names)

    monkeypatch.setattr(kbj, "_resolve_event", no_memo)
    without = kbj.join_kalshi_to_board(list(markets), [dict(r) for r in rows], selected_date="2026-09-04")
    assert json.dumps(with_memo, sort_keys=True, default=str) == json.dumps(without, sort_keys=True, default=str)
    assert seen["memo_kwarg"] > 0          # the game-line branch really passes the memo
