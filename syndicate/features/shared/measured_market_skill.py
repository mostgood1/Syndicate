"""Measured skill for markets whose PRODUCER attaches no `model_skill` note.

WHY THIS EXISTS. `projection_skill.attach_projection_skill` stamps
`status: "unmeasured"` ("model never backtested -- projection is unvalidated")
on every projection whose producer attached no note. That is the honest answer
when nothing was measured. It was also the answer on markets that HAD been
measured. Census of the served Layer 2 shortlist, 2026-09-14, lane
`accuracy-assessment-0914`: 605 of 1,394 rows carried the label (mlb 268,
soccer 268, nfl 69). They included MLB full-game moneyline and totals
(482 finals, `state_mlb.md [mlb-sim-edge-is-anti-predictive]`) and soccer 1X2
(the 1,112-match backtest, `state.md` user decision 7). The measurement
existed; the row said it did not.

WHY A TABLE HERE AND NOT IN EACH PRODUCER. `projection_skill`'s docstring
prefers a producer attaching its own note, and producers that do
(`nfl_preseason_calibration`, `ncaaf.game_projections`, `mlb_prop_calibration`)
keep precedence: this table is consulted ONLY where no note exists. The game
producers it covers are reached through `board_enrichment`'s per-sport return
sites. One lookup behind the choke point every caller already shares covers all
of them; per-producer wiring is `#334`'s failure (three of four paths patched).

WHAT AN ENTRY IS. A measurement on the full projection population against the
de-vigged market -- or against the closing LINE, for spreads and totals --
with its window, its sample and its sign. It is NOT a claim that the model is
good. Most entries say it loses to the market, and a reader is entitled to that
number either way. An entry that cannot cite where it was measured does not
belong here: `source` is required.

PHASE IS PART OF THE KEY. A pregame measurement says nothing about a live
re-sim's number (`projection["live_aware"]`, set by `live_projection_join`).
MLB's live model has its own, different record, and a pregame note on a live
row would be the inherited-number failure `live_gameline_join` names.

ADMISSION. `layer2_board._row_rests_on_unmeasured_model` withholds ONE-SIDED
(`book_margin_model`) rows whose model is not `measured`, so relabelling a
market can re-admit rows. On the 2026-09-14 shortlist every row in the markets
this table covers was priced `consensus` (two-sided) and none changed admission.
`TWO_SIDED_GAME_MARKETS` pins that: an entry outside it whose verdict is not
`beats_market` needs `admission_checked` naming the reading that cleared it.

PAYLOAD DISCIPLINE, same as `projection_skill`: the per-row note is six short
keys. The numbers behind a verdict live in the entry, not on the row.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PHASE_PREGAME = "pregame"
PHASE_LIVE = "live"

VERDICT_BEATS = "beats_market"
VERDICT_PARITY = "parity"
VERDICT_LOSES = "loses_to_market"
VERDICT_CLASSES = frozenset({VERDICT_BEATS, VERDICT_PARITY, VERDICT_LOSES})

TWO_SIDED_GAME_MARKETS = frozenset({"h2h", "spreads", "totals", "btts", "team_totals"})

NOTE_BASIS = "measured_market_skill"

REQUIRED_ENTRY_KEYS = ("sample_games", "seasons", "verdict", "verdict_class", "source")

# (sport, market, segment, phase) -> entry.
MEASURED_MARKET_SKILL: dict[tuple[str, str, str, str], dict[str, Any]] = {}


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def projection_phase(projection: Mapping[str, Any]) -> str:
    """`live` only when the projection itself knows the game state."""
    return PHASE_LIVE if projection.get("live_aware") else PHASE_PREGAME


def skill_note(
    *, sport: Any, market: Any, segment: Any = "full", phase: str = PHASE_PREGAME
) -> dict[str, Any] | None:
    """The compact per-row note for a measured market, or None.

    None is load-bearing, as in `mlb_prop_calibration.skill_note`: the caller
    then stamps `unmeasured`, which is the honest answer, instead of this
    module inventing one. No `status` key -- `projection_skill` adds it, so
    there is one place that decides what `measured` means.
    """
    key = (_norm(sport), _norm(market), _norm(segment) or "full", _norm(phase))
    entry = MEASURED_MARKET_SKILL.get(key)
    if not entry:
        return None
    return {
        "correlation": entry.get("correlation"),
        "sample_games": entry["sample_games"],
        "seasons": entry["seasons"],
        "verdict": entry["verdict"],
        "verdict_class": entry["verdict_class"],
        "basis": NOTE_BASIS,
    }
