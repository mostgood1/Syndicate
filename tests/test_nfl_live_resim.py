"""The NFL live re-sim must be OFF by default and must refuse a broken rating.

Every test here is written so that DISABLING the thing it tests turns it red.
A suite that stays green with its subject removed is measuring nothing, which is
the failure `sim_output_checklist.py` was written to catch one layer up.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.nfl.live_resim import (  # noqa: E402
    RATING_SEPARATION_FLOOR,
    NflLiveGameState,
    NflResimRefusal,
    build_game_lens,
    nfl_live_resim_enabled,
    ratings_are_degenerate,
    resim_live_game,
    summarise,
)

# A mid-third-quarter state: decided enough to be interesting, not decided.
STATE = NflLiveGameState(
    away_team="Dallas Cowboys", home_team="Philadelphia Eagles",
    period=3, clock_seconds=600, home_score=17, away_score=13,
    down=2, distance=7, field_position=41, possession_owner="home",
)

# Ratings that separate the two sides comfortably.
SEPARATED = dict(home_offense=27.0, home_defense=19.0,
                 away_offense=20.0, away_defense=24.0)


def test_absent_flag_reads_as_OFF():
    """CLAUDE.md: absent is not automatically off, so it is asserted. This
    module publishes live money edges on an engine that loses to the close, so
    the default must be off explicitly rather than by convention."""
    assert nfl_live_resim_enabled({}) is False
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": ""}) is False
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "0"}) is False
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "false"}) is False


def test_the_flag_can_actually_be_turned_ON():
    """off != on. Without this the test above passes on a function that returns
    False unconditionally, which is a real way to ship a dead feature."""
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "1"}) is True
    assert nfl_live_resim_enabled({"SYNDICATE_NFL_LIVE_RESIM": "on"}) is True


def test_disabled_refuses_and_NAMES_the_reason():
    out = resim_live_game(STATE, **SEPARATED, env={})
    assert isinstance(out, NflResimRefusal)
    assert out.reason == "nfl_live_resim_disabled"
    # The refusal has to carry WHY, not just THAT -- a bare reason string sends
    # the next reader to the code to find out whether it is a bug.
    assert "skill gate" in out.detail or "t=+3.34" in out.detail


def test_identical_net_ratings_are_DEGENERATE():
    """The measured failure: `nfl-rating-units` found across-game margin stdev
    2.16 against NCAAF's 15.37, i.e. the engine reporting its prior. Equal net
    strength on both sides is that case in its purest form."""
    assert ratings_are_degenerate(home_offense=25.0, home_defense=22.0,
                                  away_offense=25.0, away_defense=22.0) is True


def test_separated_ratings_are_NOT_degenerate():
    """off != on for the guard itself. A check that fires on everything is the
    same as no check -- it just moves the failure to 'nothing ever publishes'."""
    assert ratings_are_degenerate(**SEPARATED) is False


def test_degeneracy_is_measured_on_the_SIDES_not_the_four_numbers():
    """Two teams can have different individual ratings and identical NET
    strength. The simulation acts on home-offense vs away-defense and vice
    versa, so that pair is indistinguishable and must refuse."""
    assert ratings_are_degenerate(home_offense=30.0, home_defense=10.0,
                                  away_offense=20.0, away_defense=20.0) is True


def test_the_floor_is_a_floor_not_a_quality_bar():
    """Just past the floor must PASS. This pins the intent: it is a guard
    against publishing noise, not a judgement about whether the rating is good
    -- that belongs to `nfl-rating-units`. If someone later raises this to a
    quality threshold, this test tells them they changed its meaning."""
    just_over = RATING_SEPARATION_FLOOR * 1.05
    assert ratings_are_degenerate(home_offense=20.0 + just_over, home_defense=20.0,
                                  away_offense=20.0, away_defense=20.0) is False


def test_enabled_but_degenerate_STILL_refuses():
    """The flag protects against being on by accident. It does nothing about
    being on while the model is broken, which is the live condition today."""
    out = resim_live_game(
        STATE, home_offense=25.0, home_defense=22.0,
        away_offense=25.0, away_defense=22.0,
        env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    assert isinstance(out, NflResimRefusal)
    assert out.reason == "degenerate_ratings"


def test_a_refusal_still_produces_a_LANE():
    """A lane that vanishes on refusal is indistinguishable from a game the
    producer never saw. That ambiguity is what made NCAAF's original zero
    unreadable for a day."""
    lanes = build_game_lens(STATE, NflResimRefusal("degenerate_ratings", "x"))
    assert len(lanes) == 1
    assert lanes[0]["ok"] is False
    assert lanes[0]["refusal"]["reason"] == "degenerate_ratings"
    # `pregame`, not `live_resim`, since 2026-09-24. The board join keys on the
    # stamp first, so a refusal wearing the LIVE stamp was excluded only by
    # carrying no probability -- the "keying on presence" trap that
    # `live_gameline_from_lens` documents. ncaaf has always stamped refusals
    # this way; nfl defined the constant and never used it.
    assert lanes[0]["source"] == "pregame"


def test_summarise_reports_the_BREAKDOWN_not_just_a_count():
    """A zero with no refusal breakdown is not a result -- it cannot tell
    'nothing was live' from 'everything refused'."""
    games = [{"gameLens": build_game_lens(STATE, NflResimRefusal("degenerate_ratings"))},
             {"gameLens": build_game_lens(STATE, NflResimRefusal("bad_clock"))}]
    out = summarise(games)
    assert out["live_resimmed"] == 0
    assert out["refused"] == 2
    assert out["refusals_by_reason"] == {"degenerate_ratings": 1, "bad_clock": 1}
    assert out["enabled"] is False


def test_overtime_is_refused_before_the_sim_runs():
    out = resim_live_game(
        NflLiveGameState(away_team="A", home_team="B", period=5, clock_seconds=300,
                         home_score=20, away_score=20),
        **SEPARATED, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    assert isinstance(out, NflResimRefusal)
    assert out.reason == "overtime_not_resumable"


# --------------------------------------------------------------------------
# THE OUTPUT GUARD. Added 2026-09-07 after lane soccer-unfed-inputs showed the
# input floor covered 13% of a 93.8% defect -- arithmetic re-derived before
# accepting: NFL rating sd 2.16 -> gap sd 3.05 -> P(|gap|<0.5) = 13.0%, against
# a measured 93.8% of games landing inside P(home) 0.35-0.65. At least 80.8% of
# games cleared the floor AND were uninformative.
# --------------------------------------------------------------------------
from syndicate.features.nfl.live_resim import UNINFORMATIVE_BAND  # noqa: E402


def test_a_coin_flip_output_is_REFUSED_even_with_separated_ratings():
    """The case the input floor could not see: ratings that clear the gap floor
    and still produce a probability inside the band the engine cannot beat the
    close in. This is ~81% of NFL games today."""
    out = resim_live_game(
        NflLiveGameState(away_team="A", home_team="B", period=1,
                         clock_seconds=900, home_score=0, away_score=0),
        **SEPARATED, sims=40, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    if isinstance(out, NflResimRefusal):
        assert out.reason in {"uninformative_probability", "degenerate_ratings"}
        if out.reason == "uninformative_probability":
            assert "skill gate" in out.detail or "t=+3.34" in out.detail
    else:
        # If it published, it must be OUTSIDE the band -- never inside it.
        lo, hi = UNINFORMATIVE_BAND
        p = out["model_home_win_prob"]
        assert not (lo <= p <= hi), (
            f"published p={p} inside the uninformative band {lo}-{hi}")


def test_a_decided_game_still_publishes():
    """off != on for the output guard. A guard that refuses everything is the
    same as no producer -- a blowout late must still price, because that is a
    probability the engine CAN express."""
    out = resim_live_game(
        NflLiveGameState(away_team="A", home_team="B", period=4,
                         clock_seconds=60, home_score=38, away_score=3),
        **SEPARATED, sims=40, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    assert not isinstance(out, NflResimRefusal), getattr(out, "detail", "")
    lo, hi = UNINFORMATIVE_BAND
    assert out["model_home_win_prob"] > hi


def test_the_band_is_the_measured_one_not_an_invented_one():
    """Pins the constant to the measurement it came from. If someone widens it,
    this test makes them say why."""
    assert UNINFORMATIVE_BAND == (0.35, 0.65)


# --------------------------------------------------------------------------
# THE SNAPSHOT HALF. `_run_ncaaf_live_resim_tick` calls five things from its
# producer; this module shipped with two. These cover the three that were
# missing, and the property that matters most: the snapshot cannot bypass
# `resim_live_game`, so the flag and the band still apply to every game in it.
# --------------------------------------------------------------------------
from syndicate.features.nfl.live_resim import (  # noqa: E402
    build_live_lens_snapshot,
    live_lens_snapshot_path,
    live_state_from_row,
    validate_live_lens_snapshot,
)

LIVE_ROW = {
    "state": "live", "period": 3, "clock_seconds": 600,
    "home_score": 17, "away_score": 13, "possession_owner": "home",
    "down": 2, "distance": 7, "field_position": 41,
}
GAMES = [{"away_team": "Dallas Cowboys", "home_team": "Philadelphia Eagles",
          "live_key": "g1"}]
RATINGS = {"Philadelphia Eagles": (27.0, 19.0), "Dallas Cowboys": (20.0, 24.0)}


def test_snapshot_path_is_the_KEYVALUE_route():
    """`data/live/` routes to Redis on Render; a date-scoped path would never be
    carried by `pull_hot_artifacts`' `*<date>*` glob, and the symptom would look
    exactly like the producer never running."""
    p = str(live_lens_snapshot_path("/opt/render/project/data")).replace("\\", "/")
    # `nfl_live_resim.json`, not `nfl_live_lens.json`. They were the same file
    # until 2026-09-24, which made this module and `nfl/live_lens.py` two
    # writers on ONE Redis key from two services. Still the keyvalue route --
    # that is what this test is about -- just no longer a shared key.
    assert p.endswith("/live/nfl_live_resim.json")


def test_validator_REJECTS_a_snapshot_with_no_games_list():
    ok, why = validate_live_lens_snapshot({"sport": "nfl"})
    assert ok is False and why == "snapshot_carries_no_games_list"


def test_validator_ACCEPTS_a_real_snapshot():
    """off != on. A validator that rejects everything is the same as one that
    rejects nothing -- it just moves where the silence happens."""
    snap = build_live_lens_snapshot("2026-09-14", games=GAMES,
                                    live_index={"g1": LIVE_ROW}, ratings=RATINGS,
                                    sims=20, env={})
    ok, why = validate_live_lens_snapshot(snap)
    assert ok is True, why


def test_the_snapshot_CANNOT_bypass_the_flag():
    """The whole safety argument rests on this. If the snapshot path could reach
    the sim without going through `resim_live_game`, the flag and the band would
    both be decorative."""
    snap = build_live_lens_snapshot("2026-09-14", games=GAMES,
                                    live_index={"g1": LIVE_ROW}, ratings=RATINGS,
                                    sims=20, env={})
    lanes = snap["games"][0]["gameLens"]
    assert lanes[0]["ok"] is False
    assert lanes[0]["refusal"]["reason"] == "nfl_live_resim_disabled"
    assert snap["coverage"]["live_resimmed"] == 0


def test_a_missing_live_row_refuses_BY_NAME():
    snap = build_live_lens_snapshot("2026-09-14", games=GAMES, live_index={},
                                    ratings=RATINGS, sims=20, env={})
    assert snap["coverage"]["refusals_by_reason"] == {"no_live_state": 1}


def test_an_incomplete_payload_names_the_MISSING_KEY():
    """NFL's ESPN `situation` shape has never been checked against the one
    NCAAF's transform assumes. A mismatch must surface as a named refusal
    carrying the missing key, not as a confident state built from defaults."""
    out = live_state_from_row({"state": "live", "period": 2},
                              away_team="A", home_team="B")
    assert out.reason == "incomplete_live_state"
    assert "clock_seconds" in out.detail


def test_a_final_game_is_refused_not_simulated():
    out = live_state_from_row({**LIVE_ROW, "state": "final"},
                              away_team="A", home_team="B")
    assert out.reason == "game_final"


def test_budget_exhaustion_refuses_BY_NAME_rather_than_shortening_the_slate():
    """A short slate and a refused slate look identical from the board. `#241`
    is why the budget exists; naming it is why the zero is readable."""
    many = [{"away_team": f"A{i}", "home_team": f"H{i}", "live_key": f"g{i}"}
            for i in range(6)]
    index = {f"g{i}": LIVE_ROW for i in range(6)}
    snap = build_live_lens_snapshot(
        "2026-09-14", games=many, live_index=index,
        ratings={f"H{i}": (27.0, 19.0) for i in range(6)}
        | {f"A{i}": (20.0, 24.0) for i in range(6)},
        # 0.0, not 1.0: the budget is checked BEFORE each game, and on a fast
        # runner all six finished inside 1.0s (measured 1.13s, 0 refused), so
        # the old assertion depended on machine speed and went red on CI
        # 2026-09-28. A zero budget refuses every game, deterministically.
        sims=20, budget_seconds=0.0, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
    )
    reasons = snap["coverage"]["refusals_by_reason"]
    assert snap["coverage"]["games"] == 6
    # Every game is accounted for: resimmed + refused == games. A game that
    # simply vanished would break this and nothing else would notice.
    assert snap["coverage"]["live_resimmed"] + snap["coverage"]["refused"] == 6
    assert "budget_seconds" in snap["coverage"]
    assert reasons == {"tick_budget_exhausted": 6}, "refused BY NAME, every game"


# --------------------------------------------------------------------------
# THE RATING SEPARATION FLOOR, re-calibrated 2026-09-27. Nothing tested the old
# behaviour, which is how a constant fitted to the wrong rating scale survived.
# --------------------------------------------------------------------------

def test_UNFED_ratings_are_named_separately_from_two_close_teams():
    """`(0.0, 0.0)` is MISSING DATA, not an evenly-matched game.

    `sp_offense_defense_rating` returns zeros for a team it cannot find, and on
    2026-09-27 there was no week-4 ratings artifact at all -- so a live week-4
    tick rated both sides zero. The old code spelled that `degenerate_ratings`,
    the same string as a genuinely close game, and a cutoff-replay grade then
    attributed 45% of its sample to a CLOSED lane's rating compression instead of
    to an absent file.
    """
    from syndicate.features.nfl import live_resim as lr

    state = lr.NflLiveGameState(away_team="B", home_team="A", period=2,
                               clock_seconds=900, home_score=7, away_score=0)
    refusal = lr.resim_live_game(state, home_offense=0.0, home_defense=0.0,
                                 away_offense=0.0, away_defense=0.0, sims=8,
                                 env={"SYNDICATE_NFL_LIVE_RESIM": "1"})
    assert isinstance(refusal, lr.NflResimRefusal)
    assert refusal.reason == "unfed_ratings", (
        "an absent ratings artifact is being reported as a close game"
    )
    assert lr.ratings_are_unfed(home_offense=0.0, home_defense=0.0,
                                away_offense=0.0, away_defense=0.0) is True
    # Real ratings that happen to net out level are NOT unfed -- they are a
    # genuinely even game, and the separation check owns that case.
    assert lr.ratings_are_unfed(home_offense=0.4, home_defense=0.4,
                                away_offense=0.4, away_defense=0.4) is False


def test_the_floor_no_longer_refuses_a_SIX_POINT_favourite():
    """off != on for the re-calibration, at the scale production's ratings use.

    MEASURED: ~11-12 margin points per 1.0 of net separation, so the old 0.5
    floor refused every game the model thought closer than about a six-point
    spread -- 63.1% / 28.4% / 68.3% of all pairings on the wk1/wk2/wk3 artifacts.
    A separation of 0.1 is a ~1.2-point edge and must survive the input check.
    """
    from syndicate.features.nfl import live_resim as lr

    assert lr.RATING_SEPARATION_FLOOR == 0.02, (
        "the floor moved; re-derive it from the engine's measured sensitivity "
        "rather than adjusting it to taste"
    )
    # A 0.1 separation: refused under the old 0.5 floor, allowed now.
    assert lr.ratings_are_degenerate(home_offense=0.1, home_defense=0.0,
                                     away_offense=0.0, away_defense=0.0) is False
    # And the guard still catches ratings that genuinely cannot separate.
    assert lr.ratings_are_degenerate(home_offense=0.005, home_defense=0.0,
                                     away_offense=0.0, away_defense=0.0) is True


def test_the_separation_check_compares_SIDES_not_the_four_numbers():
    """Unchanged behaviour, pinned because the re-calibration touched this code.

    What the simulation acts on is home-offense against away-defense and vice
    versa, so two teams with identical NET strength are indistinguishable even
    when their individual numbers differ a lot.
    """
    from syndicate.features.nfl import live_resim as lr

    # home net = 2.0 - 1.0 = 1.0 ; away net = 2.0 - 1.0 = 1.0 -> no separation
    assert lr.ratings_are_degenerate(home_offense=2.0, home_defense=1.0,
                                     away_offense=2.0, away_defense=1.0) is True


# --------------------------------------------------------------------------
# RATING UNCERTAINTY PROPAGATION, added 2026-09-27. Ships INERT.
# --------------------------------------------------------------------------

def _sd_of(dist):
    pairs = [(float(k), int(v)) for k, v in dist.items()]
    n = sum(c for _, c in pairs)
    mu = sum(v * c for v, c in pairs) / n
    return (sum(c * (v - mu) ** 2 for v, c in pairs) / n) ** 0.5


def _resim(sd):
    from syndicate.features.nfl import live_resim as lr
    state = lr.NflLiveGameState(away_team="B", home_team="A", period=2,
                                clock_seconds=900, home_score=7, away_score=0)
    return lr.resim_live_game(state, home_offense=0.30, home_defense=0.10,
                              away_offense=0.05, away_defense=0.05,
                              sims=200, env={"SYNDICATE_NFL_LIVE_RESIM": "1"},
                              rating_sd=sd)


def test_it_ships_INERT_and_off_is_bit_identical():
    """Default OFF, and off must reproduce the point-estimate run exactly.

    NFL live re-sim is ENABLED in production and prices the moneyline, so a
    mechanism that changed published probabilities the moment it landed would
    be switched on by merging rather than by deciding. `rating_sd=0` must take
    the untouched `base` path, not a perturbation that happens to be small.
    """
    a, b = _resim(0.0), _resim(0.0)
    assert a["rating_sd"] == 0.0
    assert a["margin_dist"] == b["margin_dist"], "the off path is not deterministic"
    assert a["model_home_win_prob"] == b["model_home_win_prob"]


def test_turning_it_ON_widens_the_distribution_off_eq_on_would_be_inert():
    """off != on, on the quantity the mechanism exists to move."""
    off, on = _resim(0.0), _resim(0.75)
    assert _sd_of(on["margin_dist"]) > _sd_of(off["margin_dist"]) * 1.05, (
        "rating_sd is not widening anything -- the mechanism is inert"
    )
    assert on["rating_sd"] == 0.75, "the published result does not say it was used"


def test_it_is_DETERMINISTIC_so_two_variants_compare_on_the_same_draws():
    """A harness that cannot reproduce its own rows compares random seeds."""
    a, b = _resim(0.5), _resim(0.5)
    assert a["margin_dist"] == b["margin_dist"]


def test_an_UNKNOWN_rating_source_is_never_MORE_CONFIDENT_than_a_known_one():
    """Unknown must not take the permissive branch.

    Here "permissive" means "this rating is well determined", which would
    publish a confident probability off a source nobody has measured.

    THE ASSERTION IS `>= max(known)`, NOT `> some narrow entry`. An earlier
    version compared a narrow source against a wide one, which baked in the
    assumption that the table HAS distinct values. The empirical fit collapsed
    it to a single value -- at rating_sd 1.0 the two sources came back at ratio
    1.088 and 0.906, straddling 1.0, so a per-source distinction is not
    warranted by evidence. A test that fails when the table becomes honest was
    testing the table, not the rule.
    """
    from syndicate.features.nfl import live_resim as lr

    widest = max(lr._RATING_UNCERTAINTY_BY_SOURCE.values())
    for unknown in ("", None, "some_new_source_nobody_graded"):
        assert lr.rating_uncertainty_for_source(unknown) >= widest, (
            f"{unknown!r} is treated as better determined than a measured source"
        )
    for known, sd in lr._RATING_UNCERTAINTY_BY_SOURCE.items():
        assert lr.rating_uncertainty_for_source(known) == sd


# --------------------------------------------------------------------------
# The prop-capture SWEEP runs on any tick, not only on a capturable boundary.
# --------------------------------------------------------------------------

def test_the_capture_sweep_runs_on_a_NON_capturable_row(monkeypatch):
    """The recovery must not depend on the thing it exists to recover from.

    `publish_pending_captures` pushes captures written before the push existed.
    Hooked inside `record_quarter_snapshot` it fires only on a genuine boundary
    ATTEMPT -- and MEASURED 2026-09-28, this tick ran every ~5 min emitting
    `PROP_CAPTURE_TICK no_period_or_clock=16` while the next boundary was 9.5 h
    away (one game, kickoff 00:15Z). A file already sitting on disk would have
    waited those 9.5 h. So the sweep sits ABOVE every early return, and this
    pins it there with the most hostile row: one that returns immediately.
    """
    import syndicate.features.nfl.live_prop_capture as cap
    from syndicate.features.nfl import live_resim as lr

    calls: list = []
    monkeypatch.setattr(cap, "publish_pending_captures",
                        lambda *a, **k: calls.append(1) or 0)

    # `no_row` -- the earliest return there is.
    assert lr._maybe_capture_prop_snapshot(None, None, date_str="2026-09-28") == "no_row"
    assert calls, "the sweep never ran on a non-capturable row"

    # and the real production shape: a row with neither period nor clock, which
    # is what 16 of 16 games reported all afternoon.
    calls.clear()
    got = lr._maybe_capture_prop_snapshot({"state": "pre"}, None, date_str="2026-09-28")
    assert got == "no_period_or_clock"
    assert calls, "the sweep never ran on the shape production actually emits"
