"""Generic load/save for versioned sim-engine calibration profiles.

Context: docs/reports/syndicate_learning_loop_plan_2026_08_03.md, Stage 3.

Every sim engine in the repo already externalizes its league/sport-specific
tuning as a frozen dataclass profile -- football's CalibrationProfile,
soccer's CalibrationProfile, hockeysim's SimConfig (see each engine's own
calibration_profile.py) -- but every one of them is a hardcoded Python
constant. Nothing ever re-fits them: NFL's profile is literally all-1.0
multipliers (reproducing pre-profile-seam hardcoded literals byte-for-
byte) because it has never been calibrated through this seam at all, and
hockeysim's own Phase 3b truth-layer deltas were computed
(docs/reports/hockeysim_phase3_truth_baseline_report.md) and never written
back into the profile.

This module makes a profile a versioned ARTIFACT instead of a source
constant: load_versioned_profile reads a JSON override file and applies
only the fields that exist on the target dataclass (via dataclasses.replace),
falling back to the given in-source default -- unchanged, byte-for-byte --
whenever the artifact is missing, unreadable, or malformed. It is
deliberately generic over the profile's dataclass shape (works identically
for football's CalibrationProfile, soccer's, or hockeysim's SimConfig)
rather than hardcoding one sport's field set, since the pattern is the same
across all three engines.

Nothing calls this yet from a live sim path -- wiring the loader in is a
separate, per-engine change (each engine's call sites need to decide WHEN
to resolve a profile: once per process, once per sim run, etc.). This
module only makes loading/saving safe and generic; a future refit job
(Stage 3 continued) is what will actually produce candidate JSON files
for it to read.
"""

from __future__ import annotations

import json
from dataclasses import fields, is_dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

ProfileT = TypeVar("ProfileT")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def profile_with_overrides(default_profile: ProfileT, overrides: dict[str, Any]) -> ProfileT:
    """Apply only the keys in ``overrides`` that are real fields on
    ``default_profile``'s dataclass -- unknown keys (a typo, a field from a
    newer/older schema version) are silently ignored rather than raising,
    and every field not present in ``overrides`` keeps the default's value.
    Never mutates ``default_profile`` (frozen dataclasses can't be, and
    dataclasses.replace always returns a new instance)."""
    if not is_dataclass(default_profile):
        raise TypeError("default_profile must be a dataclass instance")
    valid_field_names = {f.name for f in fields(default_profile)}
    applicable = {key: value for key, value in overrides.items() if key in valid_field_names}
    if not applicable:
        return default_profile
    return replace(default_profile, **applicable)  # type: ignore[misc]


def load_versioned_profile(
    *,
    default_profile: ProfileT,
    artifact_path: Path,
) -> tuple[ProfileT, dict[str, Any]]:
    """Returns (profile, metadata). ``profile`` is ``default_profile``
    itself (not a copy) whenever the artifact is absent or invalid --
    callers can rely on identity-equality-free `==` comparisons against the
    frozen default in tests. ``metadata`` always has at least
    {"source": "default"|"artifact", "path": str(artifact_path)}; on a
    successful artifact load it also carries whatever "version"/
    "generated_at"/"fit_from" keys the artifact itself included, verbatim,
    for provenance/audit -- this function never invents them.

    Never raises: a corrupt or partially-invalid artifact degrades to the
    default profile rather than crashing whatever sim run triggered the
    load. That mirrors NFL_CALIBRATION_PROFILE's own framing ("every call
    site that does not pass profile= explicitly stays frozen") -- a load
    failure should behave exactly like the artifact never existed.
    """
    base_metadata = {"source": "default", "path": str(artifact_path)}
    if not artifact_path.exists():
        return default_profile, base_metadata
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except Exception:
        return default_profile, base_metadata
    if not isinstance(payload, dict):
        return default_profile, base_metadata
    fields_payload = payload.get("fields")
    if not isinstance(fields_payload, dict):
        return default_profile, base_metadata
    try:
        profile = profile_with_overrides(default_profile, fields_payload)
    except Exception:
        return default_profile, base_metadata

    metadata = {"source": "artifact", "path": str(artifact_path)}
    for key in ("version", "generated_at", "fit_from"):
        if key in payload:
            metadata[key] = payload[key]
    return profile, metadata


def save_versioned_profile(
    profile: Any,
    *,
    artifact_path: Path,
    version: str,
    fit_from: dict[str, Any] | None = None,
) -> Path:
    """Writes a profile as a versioned JSON artifact. ``profile`` must
    expose ``to_dict()`` (every CalibrationProfile in the repo already
    does) so ``fields`` round-trips through exactly the same shape
    load_versioned_profile reads back -- if it doesn't, this raises
    immediately rather than silently writing a payload nothing can load."""
    if not hasattr(profile, "to_dict"):
        raise TypeError("profile must implement to_dict() (every CalibrationProfile in this repo does)")
    payload = {
        "version": version,
        "generated_at": _utc_now(),
        "fit_from": fit_from or {},
        "fields": profile.to_dict(),
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return artifact_path


__all__ = ["profile_with_overrides", "load_versioned_profile", "save_versioned_profile"]
