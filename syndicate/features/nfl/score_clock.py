"""NFL live margin from SCORE AND CLOCK. No ratings, on purpose.

    load_score_clock_model(path)       -> ScoreClockModel | None
    model.margin_distribution(...)     -> {margin: count} for the FINAL margin
    model.home_win_probability(...)    -> float | None

WHY A SECOND LIVE MODEL EXISTS AT ALL. smartsim2's live re-sim loses to a frozen
baseline on NFL -- measured 2026-09-27 over 32 completed games, MAE 9.596
against 7.522 -- and it still loses after its too-narrow distribution is fixed
by propagating rating uncertainty. The diagnosis was in one comparison: the
simulator's spread was FLAT (sim_sd 8.414 / 8.504) while the residual spread
swung with the RATING SOURCE (10.219 / 14.153). Those ratings carry about as
much noise as signal -- their implied uncertainty is the same order as their own
dispersion -- so a model leaning on them inherits the noise and beats nothing.

This leans on the two quantities that are OBSERVED rather than estimated.

WHAT IT IS. `final_margin = margin_at_cutoff + REST`, and REST is drawn from the
empirical distribution of what actually happened in prior seasons from the same
quarter and a similar scoreline. That is the whole model. It has no parameters
to overfit, which after a night of fitted constants going wrong in production is
a feature rather than a limitation.

THE MARGIN CONDITIONER IS SIGNED, AND THAT IS THE POINT OF SCHEMA 2. A team
trailing by 21 in the fourth throws on every down; a team leading by 21 runs the
clock out, so REST is not independent of the margin it follows. Schema 1
additionally MIRRORED each observation onto "the leader", assuming leading-home
and leading-away were the same thing. Measured on 2025 they are not: REST is
home-positive whoever leads (home leading +1.076, away leading +1.176, tied
-0.011), so the mirror discarded about +2.25 points of home-field advantage.
Schema 2 keeps everything home-positive and buckets by SIGNED margin, so
`H4-10` and `A4-10` are different cells and home advantage lives in the data.

THE COST IS CELL SIZE, and it is real: signed buckets are roughly half the size,
so a fit on too few seasons falls back to the pooled quarter for most requests
and quietly stops conditioning on margin at all -- measured, a 3-season fit
answered 90 of 99 requests from the pool. `rest_distribution` names its source
for exactly this reason: `cell:2|A4-10` and `pooled:2` are different claims.

WHAT IT DELIBERATELY DOES NOT DO:

  * **It does not publish.** Nothing here reaches `build_game_lens`, a lens or a
    pricer. It is graded first, by the same cutoff-replay harness and against
    the same `#499` bar, and turned on only on the strength of that.
  * **It does not read ratings.** Adding them back as a weak prior is a separate,
    testable change; mixing it in now would make the comparison against the
    re-sim uninterpretable, which is the whole point of building it.
  * **It refuses rather than extrapolating.** No fitted artifact, an unknown
    quarter, or an empty cell returns None. A live model that invents a
    distribution when its evidence is missing is exactly the failure the NFL
    `unfed_ratings` split was introduced to make visible.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "ScoreClockModel",
    "load_score_clock_model",
    "score_clock_model_path",
]

# The same cutoffs the fit used. A request for any other period is REFUSED
# rather than mapped onto the nearest one -- "end of Q2" and "eight minutes into
# Q2" are different amounts of remaining football and the fit only knows one.
SUPPORTED_PERIODS = (1, 2, 3)

# SCHEMA 2 IS UNFOLDED. Schema 1 mirrored observations onto "the leader's
# perspective" and required the caller to negate a trailing team's draw back.
# Reading a schema-1 artifact with schema-2 code would apply a LEADER's
# distribution to a trailing team without negating it -- a home team down ten
# reported as a ten-point favourite, which is precisely the inversion
# `price_distribution_market` warns about. So the version is CHECKED, not
# assumed, and an old artifact is refused rather than silently misread.
SUPPORTED_SCHEMA_VERSIONS = (2,)


def score_clock_model_path(data_root: Any) -> Path:
    """Where the fitted artifact lives, beside the other NFL source data."""
    return Path(data_root) / "nfl_source" / "score_clock_margin.json"


@dataclass(frozen=True)
class ScoreClockModel:
    """A fitted rest-of-game margin distribution, and nothing else."""

    fit_seasons: tuple[int, ...]
    games: int
    observations: int
    min_cell_n: int
    margin_buckets: tuple[str, ...]
    correlation_by_period: Mapping[str, Any]
    pooled: Mapping[str, Mapping[str, int]]
    cells: Mapping[str, Mapping[str, int]]
    cell_n: Mapping[str, int]

    def _bucket(self, margin: int) -> str:
        """SIGNED, in the home-positive frame: `H4-10`, `A11-17`, `TIED`."""
        m = int(margin)
        if m == 0:
            return "TIED"
        side = "H" if m > 0 else "A"
        a = abs(m)
        for label in self.margin_buckets:
            if not label or label == "TIED" or label[0] != side:
                continue
            lo, _, hi = label[1:].partition("-")
            try:
                if int(lo) <= a <= int(hi):
                    return label
            except ValueError:
                continue
        return ""

    def rest_distribution(self, *, period: int, margin_at: int
                          ) -> tuple[dict[str, int], str] | None:
        """`({rest: count}, source)` from the LEADER's perspective, or None.

        `source` names which cell answered -- `cell:2|4-10` or
        `pooled:2` -- because a distribution that silently fell back to the
        quarter-only pool is a different claim from one backed by its own cell,
        and a caller that cannot tell them apart cannot report honestly.
        """
        if int(period) not in SUPPORTED_PERIODS:
            return None
        key = f"{int(period)}|{self._bucket(margin_at)}"
        cell = self.cells.get(key)
        if cell and int(self.cell_n.get(key, 0)) >= int(self.min_cell_n):
            return dict(cell), f"cell:{key}"
        pooled = self.pooled.get(str(int(period)))
        if not pooled:
            return None
        return dict(pooled), f"pooled:{int(period)}"

    def margin_distribution(self, *, period: int, margin_at: int
                            ) -> tuple[dict[str, int], str] | None:
        """`({final_margin: count}, source)` in the HOME-POSITIVE frame.

        THERE IS NO SIGN TO UNFOLD. Schema 2 keeps every observation
        home-positive and conditions on a SIGNED margin bucket, so the cell for
        a trailing home team already describes trailing home teams -- including
        the home-field advantage that the schema-1 fold averaged away (measured
        +2.25 points). The draw is simply added to the board.
        """
        got = self.rest_distribution(period=period, margin_at=margin_at)
        if got is None:
            return None
        rest, source = got
        out: dict[str, int] = {}
        for raw, count in rest.items():
            try:
                value = int(margin_at) + int(float(raw))
            except (TypeError, ValueError):
                return None
            key = str(value)
            out[key] = out.get(key, 0) + int(count)
        return out, source

    def home_win_probability(self, *, period: int, margin_at: int) -> float | None:
        """P(home finishes ahead), ties excluded from the denominator.

        NFL regular-season games can end tied, so a tie is neither a home win
        nor an away win and is removed rather than split. Splitting it would
        move the probability by half the tie mass toward 0.5 and make a model
        that knows about ties look less confident than one that does not.
        """
        got = self.margin_distribution(period=period, margin_at=margin_at)
        if got is None:
            return None
        dist, _ = got
        wins = total = 0
        for raw, count in dist.items():
            try:
                value, n = int(float(raw)), int(count)
            except (TypeError, ValueError):
                return None
            if value == 0:
                continue
            total += n
            if value > 0:
                wins += n
        if total <= 0:
            return None
        return wins / total


def load_score_clock_model(path: Any) -> ScoreClockModel | None:
    """Read a fitted artifact, or None. Never raises into a tick."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    try:
        version = int(raw.get("schema_version") or 0)
        if version not in SUPPORTED_SCHEMA_VERSIONS:
            # REFUSED, not migrated. A schema-1 artifact is FOLDED and this code
            # does not unfold; reading it would point a trailing team's
            # distribution the wrong way. Refit rather than reinterpret.
            return None
        pooled = raw["pooled_by_period"]
        cells = raw["cells"]
        if not pooled:
            return None
        return ScoreClockModel(
            fit_seasons=tuple(int(s) for s in raw.get("fit_seasons") or ()),
            games=int(raw.get("games") or 0),
            observations=int(raw.get("observations") or 0),
            min_cell_n=int(raw.get("min_cell_n") or 0),
            margin_buckets=tuple(str(b) for b in raw.get("margin_buckets") or ()),
            correlation_by_period=dict(raw.get("margin_rest_correlation_by_period") or {}),
            pooled=pooled,
            cells=cells,
            cell_n=dict(raw.get("cell_n") or {}),
        )
    except Exception:  # noqa: BLE001
        return None
