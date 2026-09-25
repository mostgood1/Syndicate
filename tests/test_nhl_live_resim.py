"""hockeysim can be RESUMED from a live game state.

REACHABILITY BEFORE CORRECTNESS (`model_engine_standard` §4.3). The first test
here is the IDENTITY: resuming at the opening faceoff with a full clock and no
score must reproduce the pregame run EXACTLY, seed for seed. That is what makes
the resume a restatement of the existing engine rather than a second, subtly
different one -- and it is the check ncaaf's live re-sim led with for the same
reason ("resuming at kickoff is not an approximation of the pregame sim, it IS
the pregame sim").

The second is `off != on`: a resumed state must produce a DIFFERENT answer. A
resume that silently returned the pregame number would be `#414` wearing a live
label -- the defect where a live mean shipped beside a probability that was
bit-identical to the pregame one on 24 of 28 rows.
"""

from __future__ import annotations

import pytest

from syndicate.features.nhl.sim_engine.hockeysim.models import RateModels
from syndicate.features.nhl.sim_engine.hockeysim.runtime import (
    run_hockeysim_game,
    run_hockeysim_game_from_state,
)

HOME = "Toronto Maple Leafs"
AWAY = "Ottawa Senators"

# A full period, in seconds -- the engine's own default (`SimConfig`).
PERIOD_SECONDS = 20 * 60


def _roster(team: str, base_id: int):
    """12 forwards, 6 defencemen, 1 goalie -- a legal NHL dress."""
    rows = []
    for i in range(12):
        rows.append({
            "player_id": base_id + i,
            "full_name": f"{team} F{i}",
            "position": "F",
            "proj_toi": 16.0 - (i * 0.5),
        })
    for i in range(6):
        rows.append({
            "player_id": base_id + 100 + i,
            "full_name": f"{team} D{i}",
            "position": "D",
            "proj_toi": 20.0 - (i * 1.5),
        })
    rows.append({
        "player_id": base_id + 200,
        "full_name": f"{team} G",
        "position": "G",
        "proj_toi": 60.0,
    })
    return rows


def _lineup(base_id: int):
    """Four forward lines and three defence pairs, in `line_slot` terms."""
    rows = []
    for line in range(4):
        for k in range(3):
            rows.append({"player_id": base_id + line * 3 + k, "line_slot": f"L{line + 1}"})
    for pair in range(3):
        for k in range(2):
            rows.append({"player_id": base_id + 100 + pair * 2 + k, "line_slot": f"D{pair + 1}"})
    return rows


ROSTER_H, ROSTER_A = _roster(HOME, 1000), _roster(AWAY, 2000)
LINEUP_H, LINEUP_A = _lineup(1000), _lineup(2000)


def _pregame(seed: int):
    return run_hockeysim_game(
        HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(),
        lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=seed,
    )


def _resumed(seed: int, *, period_idx: int, seconds_remaining: int, hs: int, as_: int):
    return run_hockeysim_game_from_state(
        HOME, AWAY, ROSTER_H, ROSTER_A, RateModels.baseline(),
        period_idx=period_idx, seconds_remaining=seconds_remaining,
        home_score=hs, away_score=as_,
        lineup_home=LINEUP_H, lineup_away=LINEUP_A, seed=seed,
    )


def _home_win_prob(runs) -> float:
    wins = sum(1 for gs in runs if gs.home.score > gs.away.score)
    return wins / float(len(runs))


# ---------------------------------------------------------------------------
# 1. IDENTITY -- the resume at the opening faceoff IS the pregame sim
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 7, 42, 1234])
def test_resuming_at_the_opening_faceoff_reproduces_the_pregame_run_exactly(seed):
    """Seed for seed, not merely in distribution.

    This is the check that the resume parameters are ADDITIVE. If resuming at
    0-0 with a full clock drifted from the pregame path -- a different RNG draw
    order, an extra period, an off-by-one on the period index -- every live
    number downstream would inherit that drift with nothing to reveal it.
    """
    pre_gs, _ = _pregame(seed)
    res_gs, _ = _resumed(seed, period_idx=0, seconds_remaining=PERIOD_SECONDS, hs=0, as_=0)

    assert (res_gs.home.score, res_gs.away.score) == (pre_gs.home.score, pre_gs.away.score), (
        f"resume-at-start diverged from pregame on seed {seed}: "
        f"{res_gs.home.score}-{res_gs.away.score} vs {pre_gs.home.score}-{pre_gs.away.score}"
    )


def test_the_identity_holds_over_a_whole_distribution_not_just_four_seeds():
    seeds = range(1, 151)
    pre = [_pregame(s)[0] for s in seeds]
    res = [_resumed(s, period_idx=0, seconds_remaining=PERIOD_SECONDS, hs=0, as_=0)[0] for s in seeds]
    assert _home_win_prob(res) == _home_win_prob(pre)


# ---------------------------------------------------------------------------
# 2. REACHABILITY -- off != on. A resumed state must MOVE the answer.
# ---------------------------------------------------------------------------


def test_a_two_goal_deficit_late_is_not_the_pregame_number():
    """The `off != on` test. If this ever passes trivially -- i.e. the two
    probabilities match -- the resume is inert and every live edge built on it
    is the pregame number wearing a live label (`#414`)."""
    seeds = range(1, 201)
    pregame_p = _home_win_prob([_pregame(s)[0] for s in seeds])
    trailing_p = _home_win_prob([
        _resumed(s, period_idx=2, seconds_remaining=5 * 60, hs=1, as_=3)[0] for s in seeds
    ])

    assert trailing_p != pregame_p, "resumed state produced the pregame probability -- resume is inert"
    # And it moved the RIGHT WAY, by a lot: two down with five minutes left.
    assert trailing_p < pregame_p
    assert trailing_p < 0.10, f"home trailing 1-3 with 5:00 left reads {trailing_p:.3f}"


def test_a_two_goal_lead_late_is_near_certain():
    seeds = range(1, 201)
    leading_p = _home_win_prob([
        _resumed(s, period_idx=2, seconds_remaining=5 * 60, hs=3, as_=1)[0] for s in seeds
    ])
    assert leading_p > 0.90, f"home leading 3-1 with 5:00 left reads {leading_p:.3f}"


def test_the_probability_is_monotone_in_the_scoreline():
    """Not a calibration claim -- an ordering one. A live probability that did
    not order the scorelines correctly would be worse than no live number."""
    seeds = range(1, 121)

    def p(hs, as_):
        return _home_win_prob([
            _resumed(s, period_idx=2, seconds_remaining=10 * 60, hs=hs, as_=as_)[0] for s in seeds
        ])

    down_two, down_one, level, up_one, up_two = p(0, 2), p(1, 2), p(2, 2), p(2, 1), p(2, 0)
    assert down_two <= down_one <= level <= up_one <= up_two, (
        f"not monotone: {down_two:.3f} {down_one:.3f} {level:.3f} {up_one:.3f} {up_two:.3f}"
    )


# ---------------------------------------------------------------------------
# 3. THE SEEDED SCORE IS CARRIED, not discarded
# ---------------------------------------------------------------------------


def test_the_returned_score_is_final_and_includes_what_was_already_banked():
    """`gs.home.score` must be banked + rest-of-game. If the seed were dropped,
    a 4-0 lead would read as a tie game and the win probability would be ~0.5
    on a decided game -- the shape of `#340`."""
    gs, _ = _resumed(11, period_idx=2, seconds_remaining=30, hs=4, as_=0)
    assert gs.home.score >= 4
    assert gs.away.score >= 0


def test_a_period_boundary_resume_plays_no_zero_length_period():
    """Resuming with 0 seconds left in the current period must skip it rather
    than simulate a zero-length one."""
    gs, events = _resumed(3, period_idx=1, seconds_remaining=0, hs=1, as_=1)
    # Period index 1 is the SECOND period (zero-based); nothing may be emitted
    # for it, but the third period must still be played.
    assert not any(getattr(e, "period", None) == 2 for e in events), (
        "events emitted for a period with no time left on it"
    )
    assert gs.home.score >= 1 and gs.away.score >= 1


# ---------------------------------------------------------------------------
# 4. THE PRODUCER -- state parsing, and the refusal contract
# ---------------------------------------------------------------------------

import json  # noqa: E402
from syndicate.features.nhl import live_resim as LR  # noqa: E402


def _score_row(**over):
    """A `/v1/score/<date>` game row in NHL's real shape."""
    row = {
        "id": 2026020123,
        "gameState": "LIVE",
        "periodDescriptor": {"number": 3, "periodType": "REG"},
        "clock": {"timeRemaining": "05:00", "secondsRemaining": 300, "inIntermission": False},
        "homeTeam": {"id": 10, "name": {"default": "Toronto Maple Leafs"}, "score": 2},
        "awayTeam": {"id": 9, "name": {"default": "Ottawa Senators"}, "score": 3},
    }
    row.update(over)
    return row


def test_a_live_score_row_parses_into_a_resume_state():
    st = LR.live_state_from_score_row(_score_row())
    assert isinstance(st, LR.NhlLiveGameState)
    assert (st.period, st.clock_seconds) == (3, 300)
    assert (st.home_score, st.away_score) == (2, 3)
    assert st.game_pk == "2026020123"


@pytest.mark.parametrize("over,reason", [
    ({"gameState": "FUT"}, "game_not_started"),
    ({"gameState": "FINAL"}, "game_final"),
    ({"gameState": "WEIRD"}, "game_state_unrecognised"),
    ({"clock": {"timeRemaining": None}}, "no_clock"),
    ({"clock": {"timeRemaining": "05:00", "inIntermission": True}}, "in_intermission"),
    ({"periodDescriptor": {}}, "no_period"),
    ({"homeTeam": {"name": {"default": "X"}}}, "no_score"),
])
def test_every_unusable_row_refuses_BY_NAME(over, reason):
    """A refusal is a stable token, never a None the caller reads as 'no games'."""
    out = LR.live_state_from_score_row(_score_row(**over))
    assert isinstance(out, LR.NhlResimRefusal), f"expected a refusal, got {out}"
    assert out.reason == reason


def test_an_unrecognised_game_state_is_NOT_treated_as_live():
    """Unknown must not take the permissive branch -- the cost of being wrong
    is a live-stamped probability on a finished game."""
    out = LR.live_state_from_score_row(_score_row(gameState="SOMETHING_NEW"))
    assert isinstance(out, LR.NhlResimRefusal)


def test_a_missing_clock_is_never_silently_a_full_period():
    """`/v1/schedule` returns `clock: null` on live games -- 7 of 7 measured.
    Defaulting to 20:00 would publish a confident number about a game seconds
    from over."""
    out = LR.live_state_from_score_row(_score_row(clock={"timeRemaining": ""}))
    assert isinstance(out, LR.NhlResimRefusal) and out.reason == "no_clock"


def test_a_REFUSED_lane_carries_no_win_probability_at_all():
    """`#414`: not the pregame one, not a zero, not a null a downstream `or`
    could turn into a number."""
    lanes = LR.build_game_lens(None, LR.NhlResimRefusal("no_clock", "null"), live_state_as_of="t")
    assert len(lanes) == 1
    lane = lanes[0]
    assert lane["source"] == LR.PREGAME_LENS_SOURCE
    assert "modelHomeWinProb" not in lane
    assert "simsRun" not in lane
    assert lane["liveResimRefusal"] == "no_clock"


def test_a_priced_lane_is_stamped_live_resim_and_carries_sims_run():
    st = LR.live_state_from_score_row(_score_row())
    lanes = LR.build_game_lens(st, {
        "home_win_prob": 0.23, "sims_run": 200,
        "home_margin_mean": -0.8, "total_mean": 5.6,
    })
    lane = lanes[0]
    assert lane["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert lane["modelHomeWinProb"] == 0.23
    assert lane["simsRun"] == 200
    # Distributions are DELIBERATELY absent -- no NHL live totals estimator has
    # been graded, and the join would price them the moment they appeared.
    assert "totalRunsDist" not in lane and "marginDist" not in lane


class _StubFeatures:
    """The `HockeyGameFeatures` surface `resim_live_game` actually reads."""

    def __init__(self, pk, home_name, away_name):
        from syndicate.features.nhl.sim_engine.hockeysim.contracts import HockeyTeamFeatures
        self.game_pk = pk
        self.home = HockeyTeamFeatures(name=home_name)
        self.away = HockeyTeamFeatures(name=away_name)
        self.home_players = tuple(_stub_players(1000))
        self.away_players = tuple(_stub_players(2000))


def _stub_players(base_id):
    class P:
        def __init__(self, pid, pos, slot, toi):
            self.player_id, self.position, self.line_slot, self.proj_toi = pid, pos, slot, toi
        def roster_row(self):
            return {"player_id": self.player_id, "full_name": f"P{self.player_id}",
                    "position": self.position, "proj_toi": self.proj_toi}
        def lineup_row(self):
            return {"player_id": self.player_id, "line_slot": self.line_slot}
    out = []
    for line in range(4):
        for k in range(3):
            out.append(P(base_id + line * 3 + k, "F", f"L{line + 1}", 15.0))
    for pair in range(3):
        for k in range(2):
            out.append(P(base_id + 100 + pair * 2 + k, "D", f"D{pair + 1}", 18.0))
    out.append(P(base_id + 200, "G", None, 60.0))
    return out


def test_the_snapshot_publishes_a_live_lane_for_a_live_game():
    feats = _StubFeatures("2026020123", "Toronto Maple Leafs", "Ottawa Senators")
    snap = LR.build_live_lens_snapshot(
        "2026-10-08", sims=30,
        score_rows=[_score_row()], slate_features=[feats],
    )
    assert snap["sport"] == "nhl" and len(snap["games"]) == 1
    lane = snap["games"][0]["gameLens"][0]
    assert lane["source"] == LR.LIVE_RESIM_LENS_SOURCE
    assert lane["simsRun"] == 30
    # Home trails 2-3 with 5:00 left -- the number must reflect that.
    assert lane["modelHomeWinProb"] < 0.35, lane["modelHomeWinProb"]


def test_a_game_with_no_slate_features_refuses_rather_than_vanishing():
    snap = LR.build_live_lens_snapshot(
        "2026-10-08", sims=5, score_rows=[_score_row()], slate_features=[],
    )
    lane = snap["games"][0]["gameLens"][0]
    assert lane["source"] == LR.PREGAME_LENS_SOURCE
    assert lane["liveResimRefusal"] == "no_slate_features"


# ---------------------------------------------------------------------------
# 5. THE WIRING -- registered, allowlisted, and able to cross services
# ---------------------------------------------------------------------------


def test_nhl_is_registered_in_the_live_lens_loop_with_all_three_entries():
    """A sport in `_LIVE_LENS_SPORTS` with no builder raises at tick time, on
    the worker, where nobody is watching. Assert the registry is COMPLETE rather
    than that nhl appears in the tuple."""
    from syndicate.features.shared.live_lens_loop import (
        _LIVE_LENS_BUILDERS,
        _LIVE_LENS_SNAPSHOT_PATHS,
        _LIVE_LENS_SPORTS,
        _LIVE_LENS_VALIDATORS,
    )

    assert "nhl" in _LIVE_LENS_SPORTS
    for registry in (_LIVE_LENS_BUILDERS, _LIVE_LENS_VALIDATORS, _LIVE_LENS_SNAPSHOT_PATHS):
        missing = [s for s in _LIVE_LENS_SPORTS if s not in registry]
        assert not missing, f"registered sports with no entry: {missing}"


def test_the_nhl_snapshot_path_is_allowlisted_so_it_can_cross_services():
    """The producer runs on live-odds-worker and the board is built on
    refresh-worker. An unallowlisted snapshot is a file that exists and cannot
    cross -- `#124`, and `model_engine_standard` §3."""
    from syndicate.features.shared.artifact_publisher import is_hot_artifact_relative_path

    assert is_hot_artifact_relative_path("live/nhl_live_lens.json")


def test_the_snapshot_path_is_under_the_mounted_data_root_not_the_checkout():
    """An input under the repo checkout is destroyed by the next deploy."""
    from syndicate.features.shared.refresh_state_store import data_root

    assert LR.live_lens_snapshot_path() == data_root() / "live" / "nhl_live_lens.json"


def test_the_validator_rejects_a_non_finite_probability():
    """A NaN serialises to invalid JSON and poisons every reader downstream."""
    good = LR.build_live_lens_snapshot(
        "2026-10-08", sims=5,
        score_rows=[_score_row()],
        slate_features=[_StubFeatures("2026020123", "Toronto Maple Leafs", "Ottawa Senators")],
    )
    assert LR.validate_live_lens_snapshot(good)

    bad = json.loads(json.dumps(good))
    bad["games"][0]["gameLens"][0]["modelHomeWinProb"] = float("nan")
    assert not LR.validate_live_lens_snapshot(bad)

    out_of_range = json.loads(json.dumps(good))
    out_of_range["games"][0]["gameLens"][0]["modelHomeWinProb"] = 1.4
    assert not LR.validate_live_lens_snapshot(out_of_range)


def test_the_validator_accepts_an_EMPTY_slate():
    """Out of season the builder returns no games. Refusing to publish that
    would leave YESTERDAY's snapshot in place to be read as today's."""
    empty = LR.build_live_lens_snapshot("2026-07-04", sims=5, score_rows=[], slate_features=[])
    assert empty["games"] == []
    assert LR.validate_live_lens_snapshot(empty)


def test_a_refused_lane_still_validates():
    """A refusal is a publishable lane, not a broken snapshot."""
    snap = LR.build_live_lens_snapshot(
        "2026-10-08", sims=5,
        score_rows=[_score_row(clock={"timeRemaining": None})], slate_features=[],
    )
    assert LR.validate_live_lens_snapshot(snap)
    assert snap["games"][0]["gameLens"][0]["liveResimRefusal"] == "no_clock"


# ---------------------------------------------------------------------------
# 6. THE BOARD WIRING -- registered, and the refusal stamp REJECTED
# ---------------------------------------------------------------------------


def test_nhl_is_registered_for_live_game_lines():
    from syndicate.features.shared.board_enrichment import _LIVE_GAMELINE_SPORTS

    assert "nhl" in _LIVE_GAMELINE_SPORTS


def test_nhl_is_NOT_registered_for_live_props():
    """There is no NHL live PROP producer. An unlisted sport must fail closed
    and say so -- registering it would light up a column nothing feeds."""
    from syndicate.features.shared.board_enrichment import _LIVE_PROP_SPORTS

    assert "nhl" not in _LIVE_PROP_SPORTS


def test_the_join_accepts_the_resim_stamp_and_REJECTS_the_refusal_stamp():
    """The `#414` guard, stated as a pair.

    `live_resim` must be accepted or nothing prices. `pregame_only` must NOT
    be, or a game the producer explicitly refused -- no clock, intermission,
    unknown state -- gets priced off whatever that lane carries. The refused
    lane carries no probability at all, but accepting its stamp would still be
    the bug: it would make a refusal look like a producer that had an opinion.
    """
    from syndicate.features.shared.live_gameline_join import lens_sources_for_sport

    sources = lens_sources_for_sport("nhl")
    assert LR.LIVE_RESIM_LENS_SOURCE in sources
    assert LR.PREGAME_LENS_SOURCE not in sources


def test_nhl_has_no_analytic_error_bar_so_the_sim_count_governs():
    """NHL publishes `simsRun`; `prob_std_err` derives the interval from it.
    An analytic value here would substitute a number nobody measured for one
    the producer already reports."""
    from syndicate.features.shared.live_gameline_join import analytic_std_err_for_sport

    assert analytic_std_err_for_sport("nhl") is None


def test_out_of_season_nhl_reports_a_NAMED_empty_not_an_unsupported_sport():
    """Until October there is no snapshot. The join must say WHICH absence it
    is -- `supported: True` with a named reason -- so "not wired" and "wired and
    empty" stay distinguishable on the day the season opens."""
    from syndicate.features.shared.board_enrichment import attach_live_gamelines_for_sport

    cov = attach_live_gamelines_for_sport([], sport="nhl", selected_date="2026-09-24")
    assert cov["supported"] is True
    assert cov["rows_live_gameline_edged"] == 0
    assert "reason" in cov and cov["reason"]


# --- the 2026-09-24 production failure, pinned -------------------------------

def test_a_failed_slate_fetch_is_not_spelled_like_an_empty_slate(monkeypatch):
    """The defect that cost a full live NHL slate.

    `fetch_score_rows` swallowed every exception and returned `[]`, so a 403
    from `api-web.nhle.com` (which refuses Python's default User-Agent) was
    indistinguishable from "no games scheduled". The producer reported ok in
    under a second while six games were live, and the board read
    `games_in_snapshot: 0` with nothing to diagnose.
    """
    import syndicate.features.nhl.live_resim as mod

    def boom(*_a, **_k):
        raise mod.NhlSlateFetchFailed("HTTPError 403")

    monkeypatch.setattr(mod, "fetch_score_rows", boom)
    failed = mod.build_live_lens_snapshot("2026-09-24", slate_features=[])

    empty = mod.build_live_lens_snapshot("2026-09-24", score_rows=[], slate_features=[])

    # Both have no games -- and that is exactly why the COVERAGE must differ.
    assert failed["games"] == [] and empty["games"] == []
    assert failed["coverage"]["slateError"] == "HTTPError 403"
    assert empty["coverage"]["slateError"] is None


def test_the_score_request_sends_a_user_agent(monkeypatch):
    """Without it the endpoint 403s -- measured, not assumed (see the docstring)."""
    import syndicate.features.nhl.live_resim as mod

    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return b'{"games": []}'

    def fake_urlopen(request, timeout=None):
        seen["ua"] = request.get_header("User-agent")
        return _Resp()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mod.json, "load", lambda _r: {"games": []})
    mod.fetch_score_rows("2026-09-24")
    assert seen["ua"], "the request went out with no User-Agent -- the endpoint 403s that"
