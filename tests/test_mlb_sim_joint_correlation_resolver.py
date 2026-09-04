"""`#621` Phase 4 -- the resolver, and its seam into the LIVE consumer.

The consumer (`compute_correlation(..., measured_lookup=...)`) shipped inert at
`1bbcc246`. These tests are the proof that the producer's artifact actually
reaches it, which is the one thing a passing producer test cannot show.

Ordered by `model_engine_standard` §4.3: REACHABILITY (`off != on`) first, then
correctness. A resolver that returns `None` for everything passes every
correctness test in this file and is worth nothing.
"""
from __future__ import annotations

import json
import os
import random
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "vendor", "mlb_bettingv2"))

from sim_engine.joint_outcomes import (  # noqa: E402
    JointAccumulator,
    build_labels,
    hitter_label,
)
from sim_engine.joint_outcomes import lookup as producer_lookup  # noqa: E402

from syndicate.features.correlation_engine import (  # noqa: E402
    CORRELATION_BASIS_HEURISTIC,
    CORRELATION_BASIS_MEASURED,
    compute_correlation,
)
from syndicate.features.mlb.sim_joint_correlation import (  # noqa: E402
    JointCorrelationIndex,
    build_measured_lookup,
)

JUDGE = 592450
SOTO = 665742
GAME_PK = 776001


def _coupled_game(seed: int = 5, n: int = 800, hr_tb_coupling: bool = True):
    """A one-game joint where HR and TB are coupled by construction.

    Values are deliberately NOT drawn from the real sim -- this fixture exists to
    prove the PLUMBING carries a number, not to assert what the number is. The
    real coefficient is measured separately, over a real sim run.
    """
    rng = random.Random(seed)
    labels = build_labels([JUDGE, SOTO])
    acc = JointAccumulator(labels, n)
    for i in range(n):
        hr = 1 if rng.random() < 0.12 else 0
        singles = rng.randint(0, 2)
        tb = (4 * hr + singles) if hr_tb_coupling else rng.randint(0, 4)
        acc.record(
            i,
            {
                hitter_label(JUDGE, "home_runs"): hr,
                hitter_label(JUDGE, "total_bases"): tb,
                hitter_label(JUDGE, "hits"): hr + singles,
                hitter_label(JUDGE, "rbi"): hr + rng.randint(0, 1),
                hitter_label(SOTO, "home_runs"): 1 if rng.random() < 0.09 else 0,
                hitter_label(SOTO, "total_bases"): rng.randint(0, 4),
                "team|full|home": rng.randint(0, 9),
                "team|full|away": rng.randint(0, 9),
            },
        )
    return acc.to_payload(
        players={
            str(JUDGE): {"name": "Aaron Judge", "team": "NYY", "side": "home"},
            str(SOTO): {"name": "Juan Soto", "team": "NYM", "side": "away"},
        }
    )


def _index(joint=None, game_pk: int = GAME_PK) -> JointCorrelationIndex:
    index = JointCorrelationIndex()
    index.add_game(game_pk, joint if joint is not None else _coupled_game())
    return index


def _candidate(player: str, market: str, *, pick: str = "Over 1.5", game_pk: int = GAME_PK, **extra):
    row = {
        "sport": "mlb",
        "sport_slug": "mlb",
        "game_pk": game_pk,
        "matchup": "NYM @ NYY",
        "player": player,
        "market_key": market,
        "pick": pick,
        "team": "NYY",
    }
    row.update(extra)
    return row


# --- 1. REACHABILITY: the seam must change the ANSWER, not just the label -----


def test_reachability_resolver_off_vs_on_changes_the_score_and_the_basis():
    """`off != on`. Without the resolver, byte-identical to before."""
    a = _candidate("Aaron Judge", "batter_home_runs")
    b = _candidate("Aaron Judge", "batter_total_bases")

    off = compute_correlation(a, b)
    on = compute_correlation(a, b, measured_lookup=_index().as_lookup())

    assert off["correlation_basis"] == CORRELATION_BASIS_HEURISTIC
    assert on["correlation_basis"] == CORRELATION_BASIS_MEASURED
    assert on["correlation_score"] != off["correlation_score"]
    # And the measured number must be a real coefficient, not a clamp artifact.
    assert -1.0 <= on["correlation_score"] <= 1.0
    assert on["correlation_score"] > 0.3, on["correlation_score"]


def test_a_resolver_that_never_answers_leaves_the_result_identical():
    """The fallback must be EXACT, not merely similar -- otherwise wiring the
    resolver up would silently move every unmeasured pair on the board."""
    a = _candidate("Aaron Judge", "batter_home_runs")
    b = _candidate("Juan Soto", "batter_hits")
    assert compute_correlation(a, b, measured_lookup=lambda _x, _y: None) == compute_correlation(a, b)


def test_measured_zero_is_used_and_is_NOT_treated_as_absent():
    """0.0 is a measurement -- 'these legs are independent' -- and it is the
    single most valuable thing this can say, because the heuristic gives a
    same-game same-team pair 0.25 + 0.14 no matter what."""
    a = _candidate("Aaron Judge", "batter_home_runs")
    b = _candidate("Juan Soto", "batter_hits")
    result = compute_correlation(a, b, measured_lookup=lambda _x, _y: 0.0)
    assert result["correlation_basis"] == CORRELATION_BASIS_MEASURED
    assert result["correlation_score"] == 0.0
    assert compute_correlation(a, b)["correlation_score"] > 0.2  # what it replaced


# --- 2. The resolver agrees with the producer's own reader --------------------


def test_resolver_agrees_with_the_producers_own_reader():
    """Closes the drift risk created by duplicating `triangle_index`.

    `syndicate/` cannot import `sim_engine`, so the unpacking is written twice.
    This asserts the two readers agree on EVERY pair of a real payload, over the
    published artifact contract -- which is the thing that actually crosses
    between the producer process and the board process.
    """
    joint = _coupled_game()
    index = _index(joint)
    labels = joint["labels"]
    checked = 0
    for i, first in enumerate(labels):
        for second in labels[:i]:
            theirs = producer_lookup(joint, first, second)
            mine = index._lookup_for_test(GAME_PK, first, second)
            assert mine == theirs, (first, second, mine, theirs)
            checked += 1
    assert checked == len(labels) * (len(labels) - 1) // 2
    assert checked > 0


def test_undefined_pair_resolves_to_None_not_zero():
    """A constant column -- e.g. `mlb-hitter-so-dead-field`'s `strikeouts` --
    must fall back to the heuristic, not assert independence."""
    labels = [hitter_label(JUDGE, "hits"), hitter_label(JUDGE, "home_runs")]
    acc = JointAccumulator(labels, 300)
    for i in range(300):
        acc.record(i, {labels[0]: i % 4, labels[1]: 0})  # HR constant
    joint = acc.to_payload(players={str(JUDGE): {"name": "Aaron Judge"}})
    index = _index(joint)

    a = _candidate("Aaron Judge", "batter_hits")
    b = _candidate("Aaron Judge", "batter_home_runs")
    assert index.measured(a, b) is None
    assert index.reasons.get("undefined_pair") == 1
    assert compute_correlation(a, b, measured_lookup=index.as_lookup())["correlation_basis"] == CORRELATION_BASIS_HEURISTIC


# --- 3. Candidate keying ------------------------------------------------------


def test_market_aliases_resolve_through_the_canonical_normalizer():
    """`hr`, `home runs`, `batter_home_runs` are one market. The alias table is
    `market_keys.py`'s, not a second copy living here."""
    index = _index()
    base = _candidate("Aaron Judge", "batter_total_bases")
    measured = []
    for alias in ("batter_home_runs", "home_runs", "home runs", "hr", "HR"):
        value = index.measured(_candidate("Aaron Judge", alias), base)
        measured.append(value)
    assert all(v is not None for v in measured), measured
    assert len(set(measured)) == 1, measured


def test_player_resolves_by_id_by_name_and_by_display_string():
    index = _index()
    other = _candidate("Aaron Judge", "batter_total_bases")
    by_name = index.measured(_candidate("Aaron Judge", "batter_home_runs"), other)
    by_id = index.measured(
        _candidate("", "batter_home_runs", player_id=JUDGE), other
    )
    display = dict(_candidate("", "batter_home_runs"))
    display.pop("player")
    display["name"] = "Aaron Judge Over 0.5 Home Runs"
    by_display = index.measured(display, other)
    assert by_name is not None
    assert by_id == by_name
    assert by_display == by_name


def test_accents_and_suffixes_fold_for_name_matching():
    joint = _coupled_game()
    joint["players"] = {str(JUDGE): {"name": "Aaron Júdge Jr."}}
    index = _index(joint)
    value = index.measured(
        _candidate("aaron judge", "batter_home_runs"),
        _candidate("Aaron Judge", "batter_total_bases"),
    )
    assert value is not None


def test_unknown_player_and_unknown_market_return_None_with_a_REASON():
    index = _index()
    assert index.measured(
        _candidate("Nobody At All", "batter_hits"),
        _candidate("Aaron Judge", "batter_total_bases"),
    ) is None
    assert index.reasons.get("player_not_in_any_sim", 0) >= 1

    index2 = _index()
    assert index2.measured(
        _candidate("Aaron Judge", "batter_stolen_bases"),
        _candidate("Aaron Judge", "batter_total_bases"),
    ) is None
    assert index2.reasons.get("market_has_no_joint_dimension", 0) >= 1


def test_cross_game_pairs_are_refused():
    index = JointCorrelationIndex()
    index.add_game(GAME_PK, _coupled_game())
    index.add_game(GAME_PK + 1, _coupled_game(seed=9))
    a = _candidate("Aaron Judge", "batter_home_runs", game_pk=GAME_PK)
    b = _candidate("Aaron Judge", "batter_total_bases", game_pk=GAME_PK + 1)
    assert index.measured(a, b) is None


def test_same_dimension_is_refused_rather_than_returning_1():
    """A dimension against itself is 1.0 by construction and says nothing."""
    index = _index()
    a = _candidate("Aaron Judge", "batter_home_runs")
    assert index.measured(a, dict(a)) is None
    assert index.reasons.get("same_dimension", 0) >= 1


def test_ambiguous_name_within_one_game_refuses_rather_than_guessing():
    """Attaching one player's measured correlation to another's bet is worse
    than falling back to the heuristic."""
    joint = _coupled_game()
    joint["players"] = {
        str(JUDGE): {"name": "Will Smith"},
        str(SOTO): {"name": "Will Smith"},
    }
    index = _index(joint)
    assert index.measured(
        _candidate("Will Smith", "batter_home_runs"),
        _candidate("Will Smith", "batter_total_bases"),
    ) is None
    assert index.reasons.get("ambiguous_name_in_game", 0) >= 1


# --- 4. Absence is counted, never silent --------------------------------------


def test_an_empty_index_answers_None_and_says_so():
    index = JointCorrelationIndex()
    assert index.games_with_joint == 0
    assert index.measured(
        _candidate("Aaron Judge", "batter_home_runs"),
        _candidate("Aaron Judge", "batter_total_bases"),
    ) is None


def test_a_sim_artifact_without_a_joint_is_COUNTED_not_ignored(tmp_path, monkeypatch):
    """Until the producer ships, every artifact lands here. 'The resolver is
    inert' must be a number on a counter, not a silence."""
    sims = tmp_path / "data" / "daily" / "sims" / "2026-09-04"
    sims.mkdir(parents=True)
    path = sims / f"sim_0_NYM_at_NYY_pk{GAME_PK}.json"
    path.write_text(json.dumps({"game_pk": GAME_PK, "sim": {"sims": 1000}}), encoding="utf-8")

    monkeypatch.setattr(
        "syndicate.features.mlb.ladders_build.discover_game_pks", lambda _d: [GAME_PK]
    )
    monkeypatch.setattr(
        "syndicate.features.mlb.sources.daily_sim_artifact_path", lambda _d, _pk: path
    )
    lookup, index = build_measured_lookup("2026-09-04")
    assert index.games_with_joint == 0
    assert index.reasons.get("joint_field_absent") == 1
    assert lookup(
        _candidate("Aaron Judge", "batter_home_runs"),
        _candidate("Aaron Judge", "batter_total_bases"),
    ) is None


def test_a_sim_artifact_WITH_a_joint_is_indexed_end_to_end(tmp_path, monkeypatch):
    """The full path: artifact on disk -> index -> measured_lookup -> the live
    consumer stamping `measured_joint`."""
    sims = tmp_path / "data" / "daily" / "sims" / "2026-09-04"
    sims.mkdir(parents=True)
    path = sims / f"sim_0_NYM_at_NYY_pk{GAME_PK}.json"
    path.write_text(
        json.dumps({"game_pk": GAME_PK, "sim": {"sims": 800, "joint": _coupled_game()}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "syndicate.features.mlb.ladders_build.discover_game_pks", lambda _d: [GAME_PK]
    )
    monkeypatch.setattr(
        "syndicate.features.mlb.sources.daily_sim_artifact_path", lambda _d, _pk: path
    )

    lookup, index = build_measured_lookup("2026-09-04")
    assert index.games_with_joint == 1
    result = compute_correlation(
        _candidate("Aaron Judge", "batter_home_runs"),
        _candidate("Aaron Judge", "batter_total_bases"),
        measured_lookup=lookup,
    )
    assert result["correlation_basis"] == CORRELATION_BASIS_MEASURED
    assert index.reasons.get("measured", 0) >= 1


def test_resolver_never_raises_into_the_board():
    """`compute_correlation` swallows resolver exceptions, so a raising resolver
    is a SILENT permanent fallback. Assert it does not raise in the first place."""
    index = _index()
    for bad in ({}, {"player": None}, {"market_key": 12345}, {"player_id": "x"}):
        assert index.measured(bad, _candidate("Aaron Judge", "batter_hits")) is None
