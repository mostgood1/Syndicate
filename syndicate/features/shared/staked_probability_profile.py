"""The versioned per-(sport, market, segment) weight profile for `staked_probability`.

Pricing plane v1, P2 (`lane p2-sizer-blend`, 2026-09-08).

`opportunity_signals.staked_probability` is the seam -- a logit blend
``alpha*logit(market) + beta*logit(model)`` -- and it had ZERO callers. This
module is what a caller reads its coefficient from, and `portfolio_commit` is
the caller. The store is `calibration_profile_store.load_versioned_profile`,
the same one football's engines load through; a second storage approach is
exactly what that module's falsification test exists to refuse.

--------------------------------------------------------------------------
WHAT AN ABSENT CELL MEANS, AND WHY IT IS NOT THE SEAM'S OWN beta = 0
--------------------------------------------------------------------------

The seam documents ``beta = 0`` as "market only, model mute". The SIZER today is
not that: `sizing_inputs_from_row` derives ``model_probability = fair +
model_edge_pct/100`` -- the raw model, which is nearer the seam's ``beta = 1``
than its ``beta = 0``. So routing the default through ``staked_probability(...,
beta=0)`` would have returned `fair` and silently deleted the model edge from
every stake on the book: 100% of the portfolio switched to market-only sizing
in the commit that "added a seam". That is the unreviewed global change this
repo refuses by habit (`_market_fair_sports` opts sports in BY NAME for a
smaller version of the same move).

Therefore, in THIS profile:

  * an ABSENT cell, or a cell with ``beta <= 0``, means UNFITTED -- the sizer
    keeps its additive derivation, bit for bit, and stamps ``blend_beta = 0.0``
    with ``staked_probability_version = "unfitted"``;
  * a cell with ``beta > 0`` means FITTED -- the sizer replaces the raw model
    with ``staked_probability(fair, raw_model, beta=cell.beta)`` and stamps the
    profile's version and the beta.

The harness (`scripts/fit_staked_probability.py`) only ever writes ``beta > 0``
cells, because it refuses any fit that does not beat the market-only Brier on a
chronological hold-out. A cell whose best beta is 0 -- "the market alone beats
every blend" -- is REPORTED and NOT WRITTEN, which leaves the sizer on the raw
model for that cell. That is a known gap, not a hidden one: expressing
"fitted, market only" needs a distinct flag on the cell and a decision about
whether the sizer should ever stake price-shopping alone on a model-edge row.
Neither belongs in the commit that makes the seam reachable.

--------------------------------------------------------------------------
WHERE THE ARTIFACT LIVES
--------------------------------------------------------------------------

``<SYNDICATE_DATA_ROOT>/calibration/staked_probability_profile.json`` -- one
cross-sport document, disk-backed, allowlisted in
`artifact_publisher.HOT_ARTIFACT_PATTERNS` as
``calibration/staked_probability_profile.json``. Override the whole path with
``SYNDICATE_STAKED_PROBABILITY_PROFILE_PATH`` (a shadow evaluation pins one
candidate; the same reason `calibration_profile_paths` has a per-engine env).

Cells are keyed ``"<sport>|<market>|<segment>"``, lowercased and stripped; a
missing segment is the empty string. Lookup is EXACT. No wildcard fallback: a
beta fitted on ``mlb|h2h|full_game`` says nothing about ``mlb|totals|1st_5``,
and `learnings.md` forbids pooling across cells that were not fitted together.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.calibration_profile_store import load_versioned_profile

UNFITTED_VERSION = "unfitted"
PROFILE_PATH_ENV = "SYNDICATE_STAKED_PROBABILITY_PROFILE_PATH"
#: Relative to `data_root()`. This string IS the allowlist entry in
#: `artifact_publisher.HOT_ARTIFACT_PATTERNS`; change both or neither.
PROFILE_RELATIVE_PATH = "calibration/staked_probability_profile.json"


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out:  # NaN
        return None
    return out


def cell_key(sport: Any, market: Any, segment: Any) -> str:
    """``"<sport>|<market>|<segment>"``, normalised the way the sizer reads rows."""
    parts = (
        str(sport or "").strip().lower(),
        str(market or "").strip().lower(),
        str(segment or "").strip().lower(),
    )
    return "|".join(parts)


@dataclass(frozen=True)
class BlendCell:
    """One fitted coefficient and the evidence it rests on."""

    beta: float
    fitted_on: str | None = None
    n_train: int | None = None
    n_test: int | None = None
    brier_beta0: float | None = None
    brier_fit: float | None = None
    source: str | None = None

    @property
    def fitted(self) -> bool:
        return self.beta > 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "beta": self.beta,
            "fitted_on": self.fitted_on,
            "n_train": self.n_train,
            "n_test": self.n_test,
            "brier_beta0": self.brier_beta0,
            "brier_fit": self.brier_fit,
            "source": self.source,
        }

    @classmethod
    def from_mapping(cls, payload: Any) -> "BlendCell | None":
        if not isinstance(payload, Mapping):
            return None
        beta = _as_float(payload.get("beta"))
        if beta is None:
            return None
        # Clamped to the convex range the seam guarantees. A beta above 1 would
        # extrapolate PAST the model, which `staked_probability` only permits
        # through an explicit `alpha`; the profile never carries one.
        beta = max(0.0, min(1.0, beta))

        def _int(value: Any) -> int | None:
            number = _as_float(value)
            return int(number) if number is not None else None

        return cls(
            beta=beta,
            fitted_on=str(payload["fitted_on"]) if payload.get("fitted_on") is not None else None,
            n_train=_int(payload.get("n_train")),
            n_test=_int(payload.get("n_test")),
            brier_beta0=_as_float(payload.get("brier_beta0")),
            brier_fit=_as_float(payload.get("brier_fit")),
            source=str(payload["source"]) if payload.get("source") is not None else None,
        )


@dataclass(frozen=True)
class StakedProbabilityProfile:
    """The whole document. `cells` is the only field the store round-trips;
    `version` is carried at the payload's top level by the store and copied in
    on load so a consumer can stamp it."""

    cells: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    version: str = UNFITTED_VERSION

    def to_dict(self) -> dict[str, Any]:
        # `version` deliberately NOT here: `save_versioned_profile` writes it at
        # the top level, and a copy inside `fields` would be a second source of
        # truth the loader would then have to reconcile.
        return {"cells": {key: dict(value) for key, value in self.cells.items()}}

    def lookup(self, sport: Any, market: Any, segment: Any) -> BlendCell | None:
        """The cell for one (sport, market, segment), or None. EXACT match only."""
        if not isinstance(self.cells, Mapping):
            return None
        return BlendCell.from_mapping(self.cells.get(cell_key(sport, market, segment)))

    def beta_for(self, sport: Any, market: Any, segment: Any) -> float:
        """0.0 unless a FITTED cell exists. This is what the sizer reads."""
        cell = self.lookup(sport, market, segment)
        return cell.beta if cell is not None and cell.fitted else 0.0

    def with_cells(self, cells: Mapping[str, BlendCell | Mapping[str, Any]], *, version: str) -> "StakedProbabilityProfile":
        merged: dict[str, dict[str, Any]] = {key: dict(value) for key, value in self.cells.items()}
        for key, value in cells.items():
            merged[str(key)] = value.to_dict() if isinstance(value, BlendCell) else dict(value)
        return replace(self, cells=merged, version=version)


DEFAULT_PROFILE = StakedProbabilityProfile()


def profile_path() -> Path | None:
    """Where the artifact is read from. None only when no data root can be
    resolved at all, which the loader treats exactly like an absent file."""
    explicit = str(os.environ.get(PROFILE_PATH_ENV) or "").strip()
    if explicit:
        return Path(explicit)
    try:
        from syndicate.features.shared.refresh_state_store import data_root

        return data_root() / PROFILE_RELATIVE_PATH
    except Exception:  # noqa: BLE001 -- strict hosted storage with no root set
        return None


_CACHE: dict[str, tuple[int | None, StakedProbabilityProfile, dict[str, Any]]] = {}


def clear_profile_cache() -> None:
    _CACHE.clear()


def load_staked_probability_profile(
    path: Path | None = None,
) -> tuple[StakedProbabilityProfile, dict[str, Any]]:
    """Returns ``(profile, metadata)``; `DEFAULT_PROFILE` when absent/invalid.

    Cached per (path, mtime_ns) so a 108-row commit reads the file once, and a
    rewritten artifact is picked up on the next call without a restart.
    """
    resolved = path if path is not None else profile_path()
    if resolved is None:
        return DEFAULT_PROFILE, {"source": "default", "path": None}
    key = str(resolved)
    try:
        stamp: int | None = resolved.stat().st_mtime_ns
    except OSError:
        stamp = None
    cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1], dict(cached[2])

    profile, metadata = load_versioned_profile(default_profile=DEFAULT_PROFILE, artifact_path=resolved)
    if metadata.get("source") == "artifact":
        version = str(metadata.get("version") or "").strip() or UNFITTED_VERSION
        profile = replace(profile, version=version)
    _CACHE[key] = (stamp, profile, dict(metadata))
    return profile, dict(metadata)


__all__ = [
    "BlendCell",
    "DEFAULT_PROFILE",
    "PROFILE_PATH_ENV",
    "PROFILE_RELATIVE_PATH",
    "StakedProbabilityProfile",
    "UNFITTED_VERSION",
    "cell_key",
    "clear_profile_cache",
    "load_staked_probability_profile",
    "profile_path",
]
