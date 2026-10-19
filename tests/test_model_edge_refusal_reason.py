"""`_model_edge_for` names its refusals, and the name lands PER SIDE.

Until 2026-10-15 all four `return None` paths were silent, so a coverage count
could not tell a REFUSED model opinion from an ABSENT one. Measured that day on
the served board: of 809 rows carrying a projection and no `model_edge_pct`,
**464 (57.4%) were the plausibility CEILING alone** — and naming them required
`scripts/audit_model_edge_gap.py` to re-derive this function's branches from
outside, which is the drift the module's own comments warn about.

THE DESIGN CONSTRAINT THESE TESTS EXIST TO PIN. The obvious fix — stamp
`projection["edge_unavailable_reason"]` the way the per-sport builders do — is
WRONG here: `_model_edge_for` receives the GRID row, whose `projection` is shared
by both sides of a market, while the per-side object is the `candidate` the
fan-out builds. Stamping the projection would leak one side's reason onto the
other, last-writer-wins. So the reason travels in an out-param and the caller
stamps the candidate, and `edge_unavailable_reason` is never touched.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.features.shared import layer2_board as L  # noqa: E402


def _row(side="over", **projection):
    return {"side": side, "home_team": "Home FC", "away_team": "Away FC",
            "projection": dict(projection)}


# --------------------------------------------------------------------------
# one test per refusal path, each naming the measured population it covers
# --------------------------------------------------------------------------

def test_the_plausibility_bound_names_itself_and_carries_actionable_numbers():
    """Was `test_the_ceiling_names_itself_and_carries_both_numbers`, which used a
    15.87-point edge with an ORDINARY implied probability (0.728). The bound was
    replaced on 2026-10-19 (user: "replace the ceiling") and that row is now
    correctly ALLOWED, so the case was restated on a row the new bound refuses:
    an extreme model against an ordinary market. The original intent is
    unchanged -- the refusal is NAMED and carries the numbers that make
    "dropped, not clamped" actionable."""
    refusal = {}
    row = _row(edge_vs_market_pct=39.38, model_prob_over=0.862, market_fair_prob_over=0.468)
    assert L._model_edge_for(row, "over", None, refusal=refusal) is None
    assert refusal["reason"] == "model_probability_extreme_against_ordinary_market"
    assert refusal["model_prob_over"] == pytest.approx(0.862)
    assert refusal["market_fair_prob_over"] == pytest.approx(0.468)
    assert refusal["edge"] == pytest.approx(39.38)


def test_an_ordinary_implied_probability_is_no_longer_refused():
    """The 470-row case, pinned here too: the old bound dropped this row purely
    for magnitude and the new one allows it."""
    refusal = {}
    row = _row(edge_vs_market_pct=15.87, model_prob_over=0.728, market_fair_prob_over=0.5693)
    assert L._model_edge_for(row, "over", None, refusal=refusal) == pytest.approx(15.87)
    assert refusal == {}


def test_a_missing_projection_names_itself():
    refusal = {}
    assert L._model_edge_for({"side": "over", "projection": None}, "over",
                             None, refusal=refusal) is None
    assert refusal["reason"] == "no_projection"


def test_the_not_an_opposite_case_names_both_sides():
    """The soccer draw leg: 3 rows measured, and the pair is what makes it readable."""
    refusal = {}
    row = _row(side="draw", edge_vs_market_pct=4.72, side_hint=None,
               model_prob_over=0.825, market_fair_prob_over=0.7746)
    row["projection"]["side"] = "home"
    assert L._model_edge_for(row, "draw", None, refusal=refusal) is None
    assert refusal["reason"] == "projection_side_not_an_opposite"
    assert refusal["projected_side"] == "home"
    assert refusal["row_side"] == "draw"


def test_an_accepted_edge_records_NO_refusal():
    """The control. A reason on an accepted row would make every count wrong the
    other way, and a test suite that only checks the refusals would not notice."""
    refusal = {}
    row = _row(edge_vs_market_pct=4.2, model_prob_over=0.6, market_fair_prob_over=0.55)
    row["projection"]["side"] = "over"
    got = L._model_edge_for(row, "over", None, refusal=refusal)
    assert got == pytest.approx(4.2)
    assert refusal == {}


# --------------------------------------------------------------------------
# the properties that make it safe
# --------------------------------------------------------------------------

def test_omitting_the_out_param_is_inert():
    """Every caller that has not opted in must behave exactly as before."""
    # extreme model (0.9) against an ORDINARY market (0.45) -- refused by the
    # bound as replaced on 2026-10-19. The original used market 0.1, which is
    # itself extreme, so under the new rule both ends agree and the row passes.
    row = _row(edge_vs_market_pct=45.0, model_prob_over=0.9, market_fair_prob_over=0.45)
    assert L._model_edge_for(row, "over") is None          # positional, no refusal
    assert L._model_edge_for(row, "over", None) is None    # explicit fair, no refusal


def test_the_shared_projection_is_NEVER_mutated():
    """THE constraint. The grid row's projection is shared by both sides, so a
    stamp there leaks. This asserts the function leaves it byte-identical."""
    row = _row(edge_vs_market_pct=15.87, model_prob_over=0.728, market_fair_prob_over=0.5693)
    before = dict(row["projection"])
    L._model_edge_for(row, "over", None, refusal={})
    assert row["projection"] == before
    assert "edge_unavailable_reason" not in row["projection"]
    assert "model_edge_refusal" not in row["projection"]


def test_two_sides_of_one_market_get_their_own_reasons():
    """The leak this design prevents, demonstrated: one shared projection, two
    sides, two out-dicts, and neither reason reaches the other."""
    shared = {"edge_vs_market_pct": 39.38, "side": "home",
              "model_prob_over": 0.862, "market_fair_prob_over": 0.468}
    row = {"side": "home", "home_team": "Home FC", "away_team": "Away FC",
           "projection": shared}
    a, b = {}, {}
    L._model_edge_for(row, "home", None, refusal=a)
    L._model_edge_for(row, "draw", None, refusal=b)
    assert a.get("reason") and b.get("reason")
    # the ceiling fires for both here; what must NOT happen is one dict carrying
    # the other's side fields, nor the shared projection carrying either
    assert "model_edge_refusal" not in shared
    assert a is not b


def test_an_upstream_edge_unavailable_reason_is_left_alone():
    """The per-sport builders own that field; 49 soccer rows carried
    `prob_interval_swamps_edge` when this was measured. Overwriting it would
    destroy provenance the board already serves."""
    row = _row(edge_vs_market_pct=15.87, model_prob_over=0.728,
               market_fair_prob_over=0.5693)
    row["projection"]["edge_unavailable_reason"] = "prob_interval_swamps_edge"
    L._model_edge_for(row, "over", None, refusal={})
    assert row["projection"]["edge_unavailable_reason"] == "prob_interval_swamps_edge"


def test_note_refusal_is_a_no_op_on_none():
    L._note_refusal(None, "anything")  # must not raise
    got = {}
    L._note_refusal(got, "r", a=1)
    assert got == {"reason": "r", "a": 1}


# --------------------------------------------------------------------------
# THE CALL SITE. A SOURCE guard, and it is labelled as one.
#
# The tests above drive `_model_edge_for` directly and therefore do NOT protect
# the call site, where the design constraint actually lives. Mutation testing
# proved it: moving the stamp from `candidate` to `row["projection"]` passed all
# nine tests. No cheap behavioural fixture for `build_layer2_rows` exists in
# this suite (the lightest candidate only mentions it in prose), so this reads
# the source.
#
# A structural guard misses meaning -- this repo's own rule. It cannot tell that
# the stamp is CORRECT, only that it is not writing the shared projection. That
# is exactly the one mistake worth blocking, and it is cheaper than the fixture
# by two orders of magnitude.
# --------------------------------------------------------------------------

def _call_site_source():
    src = (ROOT / "syndicate/features/shared/layer2_board.py").read_text(encoding="utf-8")
    marker = "model_edge = _model_edge_for(row, side, fair"
    assert marker in src, "the call site moved; this guard needs updating"
    start = src.index(marker)
    return src[start:start + 600]


def test_the_call_site_stamps_the_candidate_not_the_shared_projection():
    window = _call_site_source()
    assert 'candidate["model_edge_refusal"]' in window, (
        "the refusal must land on the PER-SIDE candidate")
    assert 'row["projection"]["model_edge_refusal"]' not in window, (
        "stamping the GRID row's projection leaks one side's reason onto the other")
    assert 'projection["model_edge_refusal"]' not in window.replace(
        'candidate["model_edge_refusal"]', ""), (
        "no variant may write the refusal into any projection dict")


def test_the_call_site_only_stamps_when_the_edge_was_refused():
    """A reason on a row that HAS an edge would make every count wrong the other
    way -- the same failure as the accepted-edge control, one level up."""
    window = _call_site_source()
    assert "if model_edge is None" in window, (
        "the stamp must be guarded on the edge actually being absent")
