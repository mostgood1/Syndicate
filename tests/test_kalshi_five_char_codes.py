"""Five-character Kalshi club codes (lane `kalshi-five-char-codes`, 2026-11-09).

`kalshi_catalogue._splits` capped a club code at 4 characters. Kalshi's college
series use two 5-character codes, `UTRGV` (UT Rio Grande Valley) and `MASSL`
(UMass Lowell), so a blob holding one had no correct split and resolved to
`no_match` whatever names Kalshi supplied. Measured on the fleet: the totals of
`KXNCAAMBTOTAL-26NOV07PVUTRGV-*` named no game against our Prairie View @ UT Rio
Grande Valley, and `#764` refused them.

These tests pin, for the matcher, the order path's resolver and the fan-in:
- the shipped default and the switch (off != on);
- the right game on;
- a wrong game stays unmatched;
- a 5-character collided code is refused;
- 2-4 character answers are unchanged.
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import kalshi_board_join as kbj
from syndicate.features.shared import kalshi_catalogue as kc
from syndicate.features.shared import venue_quote_adapters as vqa

PV_UTRGV = {
    "event_id": "evt-pv-utrgv",
    "away_team": "Prairie View Panthers",
    "home_team": "UT Rio Grande Valley Vaqueros",
    "commence_time": "2026-11-08T01:00:00Z",
}
MURRAY_UML = {
    "event_id": "evt-murray-uml",
    "away_team": "Murray State Racers",
    "home_team": "UMass Lowell River Hawks",
    "commence_time": "2026-11-08T17:00:00Z",
}
PV_TXSO = {
    "event_id": "evt-pv-txso",
    "away_team": "Prairie View Panthers",
    "home_team": "Texas Southern Tigers",
    "commence_time": "2026-11-08T01:00:00Z",
}
IW_UTEP = {
    "event_id": "evt-iw-utep",
    "away_team": "Incarnate Word Cardinals",
    "home_team": "UTEP Miners",
    "commence_time": "2026-11-09T02:00:00Z",
}

# Kalshi's own code -> name pairs, as `build_club_code_names` reads them off the
# "<Club> wins" markets (fleet code map 2026-11-09 16:56Z).
NAMES = {
    "PV": "Prairie View A&M",
    "UTRGV": "UT Rio Grande Valley",
    "MRST": "Murray St.",
    "MASSL": "UMass Lowell",
    "IW": "Incarnate Word",
    "UTEP": "UTEP",
}


def _switch(monkeypatch, on: bool) -> None:
    monkeypatch.setattr(kc, "_KALSHI_FIVE_CHAR_CODES_ENABLED", on)


def test_shipped_default_is_on():
    assert kc._KALSHI_FIVE_CHAR_CODES_ENABLED is True
    assert kc.club_code_lengths() == (2, 3, 4, 5)


def test_splits_off_vs_on(monkeypatch):
    _switch(monkeypatch, False)
    assert ("PV", "UTRGV") not in kc._splits("PVUTRGV")
    assert kc.club_code_lengths() == (2, 3, 4)
    _switch(monkeypatch, True)
    assert ("PV", "UTRGV") in kc._splits("PVUTRGV")
    assert ("MRST", "MASSL") in kc._splits("MRSTMASSL")


def test_matcher_off_vs_on_names_the_game(monkeypatch):
    games = [PV_UTRGV, IW_UTEP]
    _switch(monkeypatch, False)
    off = kc.match_event_blob("PVUTRGV", games, sport="ncaab", code_names=NAMES)
    assert off["status"] == "no_match"
    _switch(monkeypatch, True)
    on = kc.match_event_blob("PVUTRGV", games, sport="ncaab", code_names=NAMES)
    assert on["status"] == "ok"
    assert on["event_id"] == "evt-pv-utrgv"
    assert on["away_team"] == "Prairie View Panthers"
    assert on["home_team"] == "UT Rio Grande Valley Vaqueros"


def test_massl_on_the_right_side(monkeypatch):
    _switch(monkeypatch, True)
    on = kc.match_event_blob("MRSTMASSL", [MURRAY_UML, PV_UTRGV], sport="ncaab", code_names=NAMES)
    assert on["status"] == "ok" and on["event_id"] == "evt-murray-uml"


def test_a_five_character_code_never_names_another_game(monkeypatch):
    """Prairie View IS on this board, but against Texas Southern: the UTRGV half
    has to name the other club, so this stays unmatched."""
    _switch(monkeypatch, True)
    on = kc.match_event_blob("PVUTRGV", [PV_TXSO, IW_UTEP], sport="ncaab", code_names=NAMES)
    assert on["status"] == "no_match"


def test_without_kalshis_names_it_stays_unmatched(monkeypatch):
    """Our alias map does not carry `UTRGV`, so the name Kalshi supplies is what
    resolves it. No names, no match."""
    _switch(monkeypatch, True)
    assert kc.match_event_blob("PVUTRGV", [PV_UTRGV], sport="ncaab")["status"] == "no_match"


def test_two_to_four_character_answers_unchanged(monkeypatch):
    for on in (False, True):
        _switch(monkeypatch, on)
        result = kc.match_event_blob("IWUTEP", [PV_UTRGV, IW_UTEP], sport="ncaab", code_names=NAMES)
        assert result["status"] == "ok" and result["event_id"] == "evt-iw-utep"


def _family_names():
    return {"KXNCAAMB": dict(NAMES)}


def _total_market():
    return {"ticker": "KXNCAAMBTOTAL-26NOV07PVUTRGV-124", "series": "KXNCAAMBTOTAL"}


def test_order_path_resolver_off_vs_on(monkeypatch):
    for on, want in ((False, "no_match"), (True, "ok")):
        _switch(monkeypatch, on)
        result = kbj._resolve_event(
            _total_market(), (), _family_names(), games=[PV_UTRGV, IW_UTEP], memo={}, collided=None, event_names=None
        )
        assert result["status"] == want
    assert result["event_id"] == "evt-pv-utrgv"


def test_order_path_refuses_a_collided_five_character_code(monkeypatch):
    """A code the series family gives to two clubs is refused at the blob's ends.
    Those ends now run to 5 characters, as `_splits` does."""
    _switch(monkeypatch, True)
    refused = kbj._resolve_event(
        _total_market(), (), _family_names(), games=[PV_UTRGV], memo={},
        collided={"KXNCAAMB": {"UTRGV"}}, event_names=None,
    )
    assert refused["status"] == "ambiguous"
    assert refused["reason"] == "club_code_collides_in_series_family"
    assert refused["codes"] == ["UTRGV"]
    clean = kbj._resolve_event(
        _total_market(), (), _family_names(), games=[PV_UTRGV], memo={}, collided={"KXNCAAMB": set()}, event_names=None,
    )
    assert clean["status"] == "ok"


def _kalshi_rows():
    """The event's own markets, as the fleet lists them (`series` included: the
    resolver reads the sport and the code family from it)."""
    rows = []
    for code, name in (("PV", "Prairie View A&M"), ("UTRGV", "UT Rio Grande Valley")):
        rows.append({
            "ticker": f"KXNCAAMBGAME-26NOV07PVUTRGV-{code}",
            "event_ticker": "KXNCAAMBGAME-26NOV07PVUTRGV",
            "series": "KXNCAAMBGAME",
            "title": f"{name} wins",
            "yes_sub_title": name,
            "no_sub_title": name,
            "status": "active",
        })
    rows.append({
        "ticker": "KXNCAAMBTOTAL-26NOV07PVUTRGV-124",
        "event_ticker": "KXNCAAMBTOTAL-26NOV07PVUTRGV",
        "series": "KXNCAAMBTOTAL",
        "title": "Full Game: Over 123.5 points scored",
        "yes_sub_title": "Over 123.5 points",
        "no_sub_title": "Over 123.5 points",
        "status": "active",
    })
    return rows


def test_fanin_names_the_total_off_vs_on(monkeypatch):
    rows = _kalshi_rows()
    games = [dict(PV_UTRGV, start_dates=("2026-11-07",)), dict(IW_UTEP, start_dates=("2026-11-08",))]
    total = rows[-1]
    _switch(monkeypatch, False)
    assert vqa._kalshi_game_token_by_venue_names(total, "ncaab", games, vqa._kalshi_naming_context(rows)) is None
    _switch(monkeypatch, True)
    token = vqa._kalshi_game_token_by_venue_names(total, "ncaab", games, vqa._kalshi_naming_context(rows))
    assert token == vqa.game_token("ncaab", PV_UTRGV["home_team"], PV_UTRGV["away_team"])
    assert token


@pytest.mark.parametrize("blob", ["PVUTRGV", "MRSTMASSL", "IWUTEP", "MINATH"])
def test_every_split_is_within_the_lengths(blob):
    lengths = kc.club_code_lengths()
    for left, right in kc._splits(blob):
        assert len(left) in lengths and len(right) in lengths and left + right == blob
