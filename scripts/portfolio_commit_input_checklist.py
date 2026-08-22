"""Gating input checklist for Stage A's sizer. Exits non-zero on any gap.

Required by `docs/ai_context/model_engine_standard.md` for every engine, and
required HERE by a specific measured hazard: a Layer 2 shortlist row carries no
sizing fields at all, and `compute_bet_size` answers a row it cannot read with
`model_probability = 0.5`, `implied_probability = 0.5`, `edge = 0`, `stake = $0`
-- no exception, no log line. Every position would be sized at zero and the
portfolio would look empty rather than broken.

Two questions per field, which is the cross-reference the standard asks for:

  POPULATED  does `sizing_inputs_from_row` actually fill this field from a
             realistic row?
  CONSUMED   does the field reach the sizer -- i.e. does perturbing it CHANGE
             the stake? A field that can be moved without moving the output is
             inert, which is what "reachability test before correctness tests
             (`off != on`)" means.

Walks `dataclasses.fields(SizingInputs)` -- never a name grep, per the standard,
because a grep passes on a field that is mentioned and unused.

    python3 scripts/portfolio_commit_input_checklist.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from syndicate.features.bankroll_manager import compute_board_stake  # noqa: E402
from syndicate.features.shared.portfolio_commit import (  # noqa: E402
    SizingInputs,
    apply_price_reliability,
    commit_portfolio,
    sizing_candidate,
    sizing_input_field_names,
    sizing_inputs_from_row,
)
from syndicate.features.shared.portfolio_settings import PortfolioSettings  # noqa: E402

# A row shaped exactly like one `layer2_board.build_layer2_rows` emits: the
# identity fields, a quote, a score block, and the two derived facts. Kept
# minimal deliberately -- if the adapter starts needing a field this row does
# not have, the checklist should fail rather than the fixture quietly grow.
CANONICAL_ROW = {
    "sport": "mlb",
    "event_id": "evt-1",
    "kind": "game",
    "market": "h2h",
    "segment": "full_game",
    "line": None,
    "player_name": None,
    "home_team": "Home",
    "away_team": "Away",
    "commence_time": "2026-08-22T23:05:00Z",
    "side": "home",
    "quote": {"price": -110, "bookmaker": "draftkings"},
    "ev_pct": 4.5,
    "model_edge_pct": 3.2,
    "score": {"score": 5.1, "price_reliability": 0.82},
}

# How much to move a field when testing whether it is consumed. Each is well
# outside rounding and inside the field's legal range.
PERTURBATIONS = {
    "american_price": lambda value: 250.0 if value < 0 else -250.0,
    "market_fair_probability": lambda value: min(0.95, value + 0.20),
    "model_probability": lambda value: min(0.95, value + 0.20),
    "price_reliability": lambda value: max(0.05, value - 0.50),
}

# WHICH CONSUMER EACH FIELD HAS. Not every sizing input feeds the sizer, and
# testing them all against the stake would be the wrong test rather than a
# strict one -- `market_fair_probability` is an intermediate that produces
# `model_probability` and is then PUBLISHED for the CLV join Stage C needs.
#
# So each field declares where it is consumed and is checked there:
#   "stake"     perturbing it must move the committed stake
#   "position"  its value must appear on the committed position
#
# Both are mechanical checks against real output, never a grep of the source --
# a grep passes on a field that is mentioned and unused, which is the whole
# failure this file exists to catch.
CONSUMERS = {
    "american_price": "stake",
    "model_probability": "stake",
    "price_reliability": "stake",
    "market_fair_probability": "position",
}

SETTINGS = PortfolioSettings(
    bankroll_units=1000.0,
    max_slate_exposure_fraction=1.0,
    min_ev_pct=-100.0,
    max_positions=10,
    min_stake_units=0.0,
)


def _stake_for(inputs: SizingInputs) -> float:
    candidate = sizing_candidate(CANONICAL_ROW, inputs)
    candidate["stake"] = compute_board_stake(candidate, settled_sample_size=0)
    apply_price_reliability(candidate, inputs)
    return float((candidate.get("stake") or {}).get("stake_fraction") or 0.0)


def _committed_position() -> dict | None:
    plan = commit_portfolio([CANONICAL_ROW], selected_date="2026-08-22", settings=SETTINGS)
    positions = plan.get("positions") or []
    return positions[0] if positions else None


def run_checklist() -> tuple[bool, list[str]]:
    """The checklist as a function, so the commit runner can GATE on it.

    Pure computation -- no I/O, no network, no artifact reads -- so calling it
    before every plan write costs nothing worth measuring. It is a hard gate
    there rather than the reference implementation's `--warn-only`, because the
    failure it catches does not look like a failure: an unfed sizer writes a
    plan full of $0 positions, and a money artifact that is silently zero is
    worse than no artifact at all.
    """
    lines: list[str] = []

    def emit(text: str) -> None:
        lines.append(text)

    field_names = sizing_input_field_names()
    emit(f"SizingInputs fields (from dataclasses.fields): {', '.join(field_names)}")

    inputs, reason = sizing_inputs_from_row(CANONICAL_ROW)
    if inputs is None:
        emit(f"FAIL  the canonical row could not be adapted at all: {reason}")
        return False, lines

    baseline = _stake_for(inputs)
    position = _committed_position()
    if position is None:
        emit("FAIL  the canonical row produced no committed position")
        return False, lines
    emit(f"baseline stake_fraction = {baseline:.6f}  committed ${position.get('stake_dollars')}")
    if baseline <= 0.0:
        # The whole point of the checklist. A zero baseline means the sizer is
        # reading nothing, which is the failure mode this file exists to catch.
        emit("FAIL  baseline stake is zero -- the sizer is not being fed")
        return False, lines

    failures = 0
    for name in field_names:
        value = getattr(inputs, name, None)
        populated = isinstance(value, (int, float)) and not isinstance(value, bool)
        perturb = PERTURBATIONS.get(name)
        consumer = CONSUMERS.get(name)
        if perturb is None or consumer is None:
            emit(f"FAIL  {name:26s} POPULATED={populated}  CONSUMED=?  (no consumer declared)")
            failures += 1
            continue

        if consumer == "stake":
            moved = _stake_for(replace(inputs, **{name: perturb(float(value))}))
            consumed = abs(moved - baseline) > 1e-9
            detail = f"stake {baseline:.6f} -> {moved:.6f}"
        else:
            published = (position or {}).get(name)
            consumed = published is not None and abs(float(published) - float(value)) < 1e-4
            detail = f"published {published!r} vs input {round(float(value), 5)!r}"

        status = "ok  " if (populated and consumed) else "FAIL"
        emit(
            f"{status}  {name:26s} POPULATED={str(populated):5s} "
            f"CONSUMED={str(consumed):5s} via {consumer:8s} {detail}"
        )
        if not (populated and consumed):
            failures += 1

    # Refusals are part of the contract: a row missing an input must be turned
    # away by NAME, never sized on a default. Checked here so the guarantee is
    # gated rather than merely documented.
    for field_name, reason_expected in (
        ("quote", "no_quote_price"),
        ("ev_pct", "no_ev_pct"),
        ("model_edge_pct", "no_model_edge_pct"),
        ("score", "no_price_reliability"),
    ):
        stripped = {key: value for key, value in CANONICAL_ROW.items() if key != field_name}
        got_inputs, got_reason = sizing_inputs_from_row(stripped)
        ok = got_inputs is None and got_reason == reason_expected
        emit(f"{'ok  ' if ok else 'FAIL'}  missing {field_name:18s} -> {got_reason!r} (want {reason_expected!r})")
        if not ok:
            failures += 1

    if failures:
        emit(f"\nCHECKLIST FAILED: {failures} problem(s)")
        return False, lines
    emit("CHECKLIST PASSED")
    return True, lines



def main() -> int:
    ok, lines = run_checklist()
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
