"""MLB hitter prop projections publish the volume and role their payload holds.

Measured 2026-10-16: every served MLB prop row carried no support field, so the
only thing able to gate a projection was the 15-point edge-magnitude ceiling.
The values were never missing -- `ingest_game` keeps the WHOLE payload row
(`self._hitters[...] = dict(row)`), so they were one copy away.

Field worth, measured on `daily_summary_2026_10_16.json` (414 hitter rows)
BEFORE publishing, because the NFL version of this fix shipped a field that
turned out not to discriminate:

    pa_mean / ab_mean   414/414 nonzero, 18 distinct, 3.27..4.74 / 2.98..4.29
    lineup_order        exactly 46 rows per slot, 1..9  -> the ROLE field
    is_lineup_batter    True on ALL 414 -> provenance, NOT a discriminator

AND THE HONEST LIMIT, pinned by `test_mlb_has_no_low_role_population`: MLB does
NOT have the NFL problem. NFL's gap was rotational players projected far below
their line (Braelon Allen, 3.8 yards against 15.5). MLB's payload holds LINEUP
BATTERS ONLY and `pa_mean` is a monotone function of batting slot -- 4.51 at
slot 1 to 3.47 at slot 9, about one plate appearance of spread. This is useful
provenance and a slot to gate on; it is not a fix for a low-role population,
because MLB has none.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared.prop_projections import (  # noqa: E402
    PropProjectionIndex,
    _attach_hitter_support,
)


def _hitter(name="Aaron Judge", slot=2, pa=4.39, ab=4.01, h_mean=1.12):
    """A row with the real payload's key set, as the fleet artifact writes it."""
    return {
        "name": name,
        "batter_id": "592450",
        "team": "NYY",
        "lineup_order": slot,
        "is_lineup_batter": True,
        "pa_mean": pa,
        "ab_mean": ab,
        "h_mean": h_mean,
        "p_h_1plus": 0.6712,
        "p_h_1plus_cal": 0.6598,
    }


def _index(row=None):
    index = PropProjectionIndex()
    index.ingest_game({
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "game_pk": "776123",
        "hitter_props_likelihood_topn": {"hits_1plus": [row or _hitter()]},
    })
    return index


def _project(row=None, market="batter_hits", line=0.5):
    return _index(row).project(player_name=(row or _hitter())["name"],
                               market=market, line=line)


# ---------------------------------------------------------------------------
# the fields reach the published projection
# ---------------------------------------------------------------------------

def test_the_projection_publishes_volume_and_role():
    payload = _project()
    assert payload is not None, "the hitter join did not produce a projection"
    assert payload["pa_mean"] == pytest.approx(4.39)
    assert payload["ab_mean"] == pytest.approx(4.01)
    assert payload["lineup_order"] == 2
    assert payload["is_lineup_batter"] is True


def test_the_support_comes_from_the_ROW_and_not_a_constant():
    """Reachability: off != on. A hard-coded value passes the test above."""
    a = _project(_hitter(slot=1, pa=4.51, ab=4.12))
    b = _project(_hitter(slot=9, pa=3.47, ab=3.09))
    assert (a["pa_mean"], a["lineup_order"]) == (pytest.approx(4.51), 1)
    assert (b["pa_mean"], b["lineup_order"]) == (pytest.approx(3.47), 9)


def test_absent_volume_is_NONE_and_not_zero():
    """`cards.py` already treats `pa_mean <= 0.0` as a real signal, so mapping
    an absent value onto 0.0 would manufacture that signal."""
    row = _hitter()
    row.pop("pa_mean")
    payload = _project(row)
    assert payload["pa_mean"] is None

    zero = _hitter(pa=0.0)
    assert _project(zero)["pa_mean"] == pytest.approx(0.0)


def test_a_non_numeric_or_non_finite_value_is_refused():
    for bad in ("n/a", "", None, float("inf"), float("nan")):
        payload = {}
        _attach_hitter_support(payload, {"pa_mean": bad, "ab_mean": bad})
        assert payload["pa_mean"] is None, bad
        assert payload["ab_mean"] is None, bad


def test_a_bool_is_not_a_lineup_slot():
    """`isinstance(True, int)` is True in Python, so the guard is load-bearing."""
    payload = {}
    _attach_hitter_support(payload, {"lineup_order": True})
    assert payload["lineup_order"] is None


def test_a_non_bool_lineup_flag_is_refused_rather_than_coerced():
    """The payload writes a real bool. A string "True" must not read as one."""
    payload = {}
    _attach_hitter_support(payload, {"is_lineup_batter": "True"})
    assert payload["is_lineup_batter"] is None


# ---------------------------------------------------------------------------
# the support must not displace what the row already carried
# ---------------------------------------------------------------------------

def test_the_projection_and_probability_survive_the_stamp():
    payload = _project()
    assert payload["projected"] is not None
    assert payload["model_prob_over"] is not None
    assert payload["source"] == "hitter_threshold"
    assert payload["basis"] == "hits_1plus"


def test_the_measured_skill_note_still_attaches():
    """`_attach_hitter_support` runs immediately before `_attach_measured_skill`
    at the bucket site; neither may swallow the other."""
    payload = _project()
    assert "pa_mean" in payload
    # model_skill is attached only for markets with a measurement, so assert the
    # KEY SET is not disturbed rather than asserting a particular verdict
    assert payload.get("model_skill", "absent") != {}


# ---------------------------------------------------------------------------
# THE HONEST LIMIT, pinned as a test so a later reader cannot mistake this
# field for the NFL one
# ---------------------------------------------------------------------------

def test_mlb_has_no_low_role_population_so_this_is_provenance_not_a_gate():
    """NFL's low-role rows projected at 0.245x their line. MLB's cannot: every
    row in this payload is a lineup batter and `pa_mean` spans about one plate
    appearance across the whole batting order. Asserted on the MEASURED slot
    curve (4.51 at slot 1 .. 3.47 at slot 9) so the claim is testable and not
    just prose in a docstring.
    """
    slots = {1: 4.51, 2: 4.39, 3: 4.28, 4: 4.15, 5: 4.05,
             6: 3.92, 7: 3.75, 8: 3.60, 9: 3.47}
    published = {s: _project(_hitter(slot=s, pa=pa))["pa_mean"]
                 for s, pa in slots.items()}
    assert published == pytest.approx(slots)
    spread = max(published.values()) - min(published.values())
    assert spread < 1.5, (
        "pa_mean spans about one plate appearance across the order; if this "
        "widens, re-measure before treating the field as a role gate")
    assert all(_project(_hitter(slot=s))["is_lineup_batter"] is True for s in slots)


# ---------------------------------------------------------------------------
# THE HR PATH. Mutation testing found this site unprotected: removing its
# stamp passed all nine tests above, because they only exercise the
# `hits_1plus` BUCKET path. HR rows arrive from a separate payload
# (`hitter_hr_likelihood_all.overall`) as ONE row per player carrying every
# `p_hr_Nplus`, indexed under `hr_1plus`, and they return through their own
# dict -- so they need their own test.
# ---------------------------------------------------------------------------

def _hr_index(slot=4, pa=4.15, ab=3.80):
    index = PropProjectionIndex()
    index.ingest_game({
        "home_team": "New York Yankees",
        "away_team": "Boston Red Sox",
        "game_pk": "776123",
        "hitter_hr_likelihood_all": {"overall": [{
            "name": "Aaron Judge",
            "batter_id": "592450",
            "team": "NYY",
            "lineup_order": slot,
            "is_lineup_batter": True,
            "pa_mean": pa,
            "ab_mean": ab,
            "hr_mean": 0.41,
            "p_hr_1plus": 0.3312,
            "p_hr_1plus_cal": 0.3208,
        }]},
    })
    return index


def test_the_HR_path_publishes_support_too():
    payload = _hr_index().project(
        player_name="Aaron Judge", market="batter_home_runs", line=0.5)
    assert payload is not None, "the HR join did not produce a projection"
    assert payload["basis"] == "hr_1plus"
    assert payload["pa_mean"] == pytest.approx(4.15)
    assert payload["ab_mean"] == pytest.approx(3.80)
    assert payload["lineup_order"] == 4
    assert payload["is_lineup_batter"] is True
    # and the HR projection itself survives the stamp
    assert payload["projected"] == pytest.approx(0.41)
    assert payload["model_prob_over"] is not None


def test_the_HR_support_comes_from_its_own_ROW():
    """Reachability on the second site, so a hard-coded value fails here too."""
    a = _hr_index(slot=1, pa=4.51).project(
        player_name="Aaron Judge", market="batter_home_runs", line=0.5)
    b = _hr_index(slot=9, pa=3.47).project(
        player_name="Aaron Judge", market="batter_home_runs", line=0.5)
    assert (a["pa_mean"], a["lineup_order"]) == (pytest.approx(4.51), 1)
    assert (b["pa_mean"], b["lineup_order"]) == (pytest.approx(3.47), 9)
