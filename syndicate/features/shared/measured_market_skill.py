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

_MLB_LIVE_SOURCE = (
    "lane accuracy-assessment-0914: production live_gameline_ledger (web copy) vs "
    "StatsAPI finals, fresh quotes <=120s, paired rows, bootstrap over games"
)
_SOCCER_SOURCE = (
    "lane accuracy-assessment-0914: production odds_history closes (per book, "
    "proportional de-vig, averaged) vs soccer projection artifacts vs ESPN finals, "
    "draws counted, bootstrap over matches"
)

# (sport, market, segment, phase) -> entry.
MEASURED_MARKET_SKILL: dict[tuple[str, str, str, str], dict[str, Any]] = {
    # ---- MLB, LIVE ------------------------------------------------------------
    # Full-game h2h is the market MLB live publication was switched off for
    # (lane `mlb-stop-publishing-edges`). This window re-confirms the loss.
    # Since the 09-08 changes it reads parity (+0.00356 [-0.00966, +0.01610],
    # 69 games) -- under-powered, so the pooled window is what the row carries.
    ("mlb", "h2h", "full", PHASE_LIVE): {
        "sample_games": 176,
        "seasons": "2026-08-31..09-13 live",
        "brier_model": 0.16949,
        "brier_market": 0.15931,
        "diff": 0.01019,
        "ci95": (0.00089, 0.02045),
        "verdict": "live: loses to the market, Brier +0.010 [+0.001, +0.020] over 176 games; worst where it disagrees most",
        "verdict_class": VERDICT_LOSES,
        "source": _MLB_LIVE_SOURCE,
    },
    ("mlb", "h2h", "first5", PHASE_LIVE): {
        "sample_games": 67,
        "seasons": "2026-09-08..09-13 live",
        "brier_model": 0.16821,
        "brier_market": 0.15916,
        "diff": 0.00905,
        "ci95": (-0.00869, 0.02806),
        "verdict": "live first-5: parity with the market, Brier +0.009 [-0.009, +0.028] over 67 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_LIVE_SOURCE + "; first5 observation rows, ties dropped, no quote age",
    },
    ("mlb", "totals", "full", PHASE_LIVE): {
        "sample_games": 159,
        "seasons": "2026-08-31..09-13 live (no 09-09)",
        "brier_model": 0.24824,
        "brier_market": 0.24342,
        "diff": 0.00482,
        "ci95": (-0.00847, 0.01889),
        "verdict": "live: parity with the market, Brier +0.005 [-0.008, +0.019] over 159 games; runs high early",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_LIVE_SOURCE,
    },
    ("mlb", "spreads", "full", PHASE_LIVE): {
        "sample_games": 159,
        "seasons": "2026-08-31..09-13 live (no 09-09)",
        "brier_model": 0.22852,
        "brier_market": 0.22849,
        "diff": 0.00002,
        "ci95": (-0.0139, 0.01468),
        "verdict": "live: parity with the market, Brier +0.000 [-0.014, +0.015] over 159 games",
        "verdict_class": VERDICT_PARITY,
        "source": _MLB_LIVE_SOURCE,
    },
    # ---- SOCCER, PREGAME --------------------------------------------------------
    # Every projection artifact in the window was REBUILT after its match, so the
    # scored number is not the one published before kickoff. A leak can only
    # flatter the model: "loses" is robust, "parity" is an upper bound on skill.
    ("soccer", "h2h", "full", PHASE_PREGAME): {
        "sample_games": 121,
        "seasons": "2026-09-07..09-13 pregame, current model version",
        "brier_model": 0.6474,
        "brier_market": 0.6028,
        "diff": 0.0446,
        "ci95": (0.0148, 0.0742),
        "verdict": "loses to the de-vigged close: 1X2 Brier +0.045 [+0.015, +0.074] over 121 matches; under-prices favourites",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE,
    },
    ("soccer", "totals", "full", PHASE_PREGAME): {
        "sample_games": 194,
        "seasons": "2026-08-31..09-13 pregame, main line",
        "brier_model": 0.2603,
        "brier_market": 0.2505,
        "diff": 0.0099,
        "ci95": (-0.0037, 0.0237),
        "verdict": "parity with the de-vigged close: main-line Brier +0.010 [-0.004, +0.024] over 194 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SOURCE,
    },
    ("soccer", "spreads", "full", PHASE_PREGAME): {
        "sample_games": 100,
        "seasons": "2026-09-07..09-13 pregame, main Asian handicap line",
        "brier_model": 0.2698,
        "brier_market": 0.2433,
        "diff": 0.0265,
        "ci95": (0.0001, 0.0542),
        "verdict": "loses to the close, borderline: Asian handicap Brier +0.027 [+0.000, +0.054] over 100 matches",
        "verdict_class": VERDICT_LOSES,
        "source": _SOCCER_SOURCE,
    },
    # ---- SOCCER, LIVE -----------------------------------------------------------
    ("soccer", "h2h", "full", PHASE_LIVE): {
        "sample_games": 118,
        "seasons": "2026-08-31..09-13 live, fresh quotes",
        "brier_model": 0.1490,
        "brier_market": 0.1340,
        "diff": 0.0150,
        "ci95": (-0.0032, 0.0319),
        "verdict": "live: parity with the market, Brier +0.015 [-0.003, +0.032] over 118 matches; worse when it disagrees 10pp+",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SOURCE + "; live_gameline_ledger, quotes <=120s, 80 sims",
    },
    ("soccer", "totals", "full", PHASE_LIVE): {
        "sample_games": 44,
        "seasons": "2026-08-31..09-13 live, fresh quotes",
        "verdict": "live: parity, model-mean lean hit 52.7% [44.2%, 61.3%] over 44 matches",
        "verdict_class": VERDICT_PARITY,
        "source": _SOCCER_SOURCE + "; live_gameline_ledger point forecast, quotes <=120s",
    },
}


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
