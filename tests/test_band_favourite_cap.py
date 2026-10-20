"""The band's heavy-favourite cap (user 2026-10-20, "C: -1000 cutoff + $5 cap").

"Refuse live band bets shorter than -1000, and cap favourites shorter than -200
at $5 of maximum loss. ... Near-evens and underdogs keep the band's size."
Prices and stakes below are today's Kalshi live plan (21:29Z build).
"""

from __future__ import annotations

import pytest

from syndicate.features.shared import live_stake_band as band


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (band.MODE_ENV, band.SMALL_EDGE_ENV, band.FAVOURITE_CAP_ENV,
                 "SYNDICATE_LIVE_BAND_REFUSE_SHORTER_THAN", "SYNDICATE_LIVE_BAND_FAVOURITE_SHORTER_THAN",
                 "SYNDICATE_LIVE_BAND_FAVOURITE_MAX_LOSS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(band.MODE_ENV, "on")
    monkeypatch.setenv(band.SMALL_EDGE_ENV, "0.001")
    yield


def _position(key, american, kelly, fraction=0.005):
    return {"position_key": key, "sport": "ncaaf", "market": "h2h", "price": american,
            "stake_fraction": fraction, "stake_dollars": 1.0, "sizing": {"kelly_fraction": kelly},
            "compounding": {"known": True, "capital": 465.0, "shard_cash": 240.0}}


def _today():
    return [
        _position("sas_alt", -1329, 0.0548),
        _position("fav_567", -567, 0.0241),
        _position("fav_317", -317, 0.0183),
        _position("dog_108", 108, 0.0064),
        _position("small", -186, None, fraction=0.0004),   # one contract, left small by option C
    ]


def _run():
    plan = {"positions": _today(), "totals": {}}
    plan["positions"][-1]["stake_dollars"] = 0.67
    refusals = {}
    band.apply_live_stake_band(plan, venue="kalshi", refusals=refusals, by_market={}, by_sport={})
    return {p["position_key"]: p["stake_dollars"] for p in plan["positions"]}, refusals, plan


def test_cap_reaches_the_band_off_differs_from_on(monkeypatch):
    off, off_refusals, _ = _run()
    monkeypatch.setenv(band.FAVOURITE_CAP_ENV, "on")
    on, on_refusals, plan = _run()
    assert off != on
    assert off["sas_alt"] == 10.0 and "sas_alt" not in on              # refused, shorter than -1000
    assert on_refusals == {"stake_band_heavy_favourite": 1} and off_refusals == {}
    assert off["fav_567"] > 5.0 and on["fav_567"] == 5.0               # favourite capped at $5 max loss
    assert off["fav_317"] > 5.0 and on["fav_317"] == 5.0
    assert on["dog_108"] == off["dog_108"] > 5.0                      # underdog keeps the band
    assert on["small"] == off["small"] == 0.67                        # one-contract bets untouched
    assert plan["stake_band"]["favourite_capped"] == 2


@pytest.mark.parametrize(
    "american, kelly, expected",
    [
        (-1000, 0.05, ("refused", 0.0)),     # AT the cutoff is refused
        (-999, 0.05, ("capped", 5.0)),
        (-200, 0.05, ("capped", 5.0)),       # AT the favourite line is capped
        (-199, 0.05, ("band", 10.0)),
        (-400, 0.0, ("band", 5.0)),          # already at or under $5: unchanged
    ],
)
def test_verdict_boundaries(monkeypatch, american, kelly, expected):
    monkeypatch.setenv(band.FAVOURITE_CAP_ENV, "on")
    cfg = band.band_config()
    stake = band.band_stake(kelly, cfg)
    assert band.favourite_cap_verdict({"price": american}, stake, band.favourite_cap_config()) == expected


def test_thresholds_are_env_tunable(monkeypatch):
    monkeypatch.setenv(band.FAVOURITE_CAP_ENV, "on")
    monkeypatch.setenv("SYNDICATE_LIVE_BAND_REFUSE_SHORTER_THAN", "-500")
    monkeypatch.setenv("SYNDICATE_LIVE_BAND_FAVOURITE_SHORTER_THAN", "-150")
    monkeypatch.setenv("SYNDICATE_LIVE_BAND_FAVOURITE_MAX_LOSS", "3")
    cap = band.favourite_cap_config()
    assert band.favourite_cap_verdict({"price": -567}, 7.41, cap) == ("refused", 0.0)
    assert band.favourite_cap_verdict({"price": -186}, 7.0, cap) == ("capped", 3.0)


@pytest.mark.parametrize("raw", ["abc", "100", "-50", ""])
def test_unusable_thresholds_fall_back_to_the_defaults(monkeypatch, raw):
    monkeypatch.setenv("SYNDICATE_LIVE_BAND_REFUSE_SHORTER_THAN", raw)
    assert band.favourite_cap_config()["refuse_shorter_than"] == band.DEFAULT_REFUSE_SHORTER_THAN
