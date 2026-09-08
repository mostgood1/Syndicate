"""The live quote-age ceiling is 120s for MLB and stays 600s where unmeasured.

WHY IT MOVED. The 600s ceiling shipped with a note saying 120s "is the
population the model was actually validated on and is the defensible research
cut", that choosing it "would be a product decision disguised as a safety fix",
and asking someone to "tighten with the env knob once someone owns that
decision". `[2026-09-08, user decision]` owns it.

TWO INDEPENDENT MEASUREMENTS, both baseball, both saying the same thing:

  * Brier, on the accumulated ledger: at <=120s the model HONESTLY LOSES to the
    market (0.20000 against 0.17403); at >1800s it "wins" (0.16459 against
    0.21897). The model does not improve with quote age -- the MARKET decays.
  * Realised outcomes, 93 `spreads q4_late` games: +14.22pp of edge at +2.93
    sigma over all quotes, falling to +9.88pp at +1.12 sigma once restricted to
    quotes <=120s. Games where the model "disagrees" most carried quotes a
    median 254s old against 172s for the rest.

An edge harvested from a 186-second-old median quote is not collectable. This
gate removes a fake edge; it does not create a real one, and at 120s roughly 77%
of live rows stop being priced.

PER SPORT, BECAUSE ONLY MLB WAS MEASURED. Both readings are baseball. A sport
whose quotes legitimately sit still between plays could be badly served by 120s,
so everything else keeps 600s until somebody measures it -- the same reason
`lens_sources_for_sport` is an explicit table rather than a relaxed default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared.live_gameline_join import (  # noqa: E402
    REASON_QUOTE_AGE_ABSENT,
    REASON_STALE_QUOTE,
    max_quote_age_seconds,
    quote_age_verdict,
)

ENV = "SYNDICATE_LIVE_GAMELINE_MAX_QUOTE_AGE_SECONDS"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)


class TestTheCeilingIsPerSport:
    def test_mlb_is_120s(self):
        assert max_quote_age_seconds("mlb") == pytest.approx(120.0)

    @pytest.mark.parametrize("sport", ["ncaaf", "nfl", "wnba", "soccer", "nba", "nhl"])
    def test_every_UNMEASURED_sport_keeps_600s(self, sport):
        """Only MLB has a measurement behind it. An unmeasured sport must not
        inherit baseball's number -- that would be a guess wearing the clothes
        of a safety fix, which is what the 600s note warned against."""
        assert max_quote_age_seconds(sport) == pytest.approx(600.0)

    def test_an_absent_sport_keeps_600s_not_the_tighter_value(self):
        """The conservative direction here is the OLD behaviour: a caller that
        does not know its sport is left exactly as it was rather than silently
        tightened."""
        assert max_quote_age_seconds() == pytest.approx(600.0)
        assert max_quote_age_seconds(None) == pytest.approx(600.0)
        assert max_quote_age_seconds("") == pytest.approx(600.0)

    def test_the_sport_key_is_case_and_space_insensitive(self):
        assert max_quote_age_seconds(" MLB ") == pytest.approx(120.0)


class TestTheVerdict:
    def test_an_mlb_quote_between_120_and_600_is_now_REFUSED(self):
        """The heart of the change: 186s was the MEDIAN quote age in the bucket
        that looked most profitable, and it used to price."""
        assert quote_age_verdict(186.0, sport="mlb")["withheld_reason"] == REASON_STALE_QUOTE
        assert quote_age_verdict(186.0, sport="ncaaf") is None

    @pytest.mark.parametrize("age", [0.0, 27.0, 119.9, 120.0])
    def test_a_fresh_mlb_quote_still_prices(self, age):
        assert quote_age_verdict(age, sport="mlb") is None

    def test_absent_age_is_still_REFUSED_not_passed(self):
        """`unknown must not default permissive` -- unchanged by this edit."""
        for bad in (None, "120", True):
            assert quote_age_verdict(bad, sport="mlb")["withheld_reason"] == REASON_QUOTE_AGE_ABSENT

    def test_nan_is_refused(self):
        assert quote_age_verdict(float("nan"), sport="mlb")["withheld_reason"] == REASON_STALE_QUOTE


class TestTheEnvKnob:
    def test_it_overrides_EVERY_sport(self, monkeypatch):
        """An operator turning this down during an incident should not have to
        know the per-sport table."""
        monkeypatch.setenv(ENV, "45")
        assert max_quote_age_seconds("mlb") == pytest.approx(45.0)
        assert max_quote_age_seconds("ncaaf") == pytest.approx(45.0)
        assert quote_age_verdict(60.0, sport="ncaaf")["withheld_reason"] == REASON_STALE_QUOTE

    @pytest.mark.parametrize("raw", ["0", "-1", "off", "", "   "])
    def test_a_junk_or_disabling_value_falls_back_to_the_TABLE(self, monkeypatch, raw):
        """A knob that can be typo'd into "off" is the shape this repo has been
        burned by. Falling back must land on the per-sport value, not on the
        global default -- otherwise a typo silently loosens MLB from 120 to 600."""
        monkeypatch.setenv(ENV, raw)
        assert max_quote_age_seconds("mlb") == pytest.approx(120.0)
        assert max_quote_age_seconds("nfl") == pytest.approx(600.0)
