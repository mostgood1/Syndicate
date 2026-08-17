"""Where a versioned calibration profile artifact lives, per engine.

`#440` Part 4 Phase 5. `calibration_profile_store.load_versioned_profile` takes an
explicit `artifact_path` and deliberately defines no convention — it is a pure
load/save seam. Something has to decide the path, and this is that something.

WHY NOT IN `calibration_profile_store.py`. Phase 5's falsification test is: *if
wiring an engine requires CHANGING the store, the store is not the generic seam it
was built to be, and Phase 5 should stop rather than bend it.* Adding a path
convention to the store would have been a change to it, so the convention lives
here instead and the store stays untouched. That keeps the falsification test
meaningful rather than quietly satisfied.

WHY ENGINES SHARE ONE CONVENTION. Three engines with three ad-hoc paths is how
you get three calibration workflows, which is the opposite of Part 4's goal
("what should be uniform is the scaffolding around the physics"). The physics
stay different; the file location does not.
"""
from __future__ import annotations

import os
from pathlib import Path

from syndicate.features.shared.source_roots import repo_root_from

# Directory override, so a worker can point at a published bundle without a code
# change -- the same escape hatch every artifact root in this repo has.
_DIR_ENV = "SYNDICATE_CALIBRATION_PROFILE_DIR"

# Per-engine override, for pinning ONE engine to a candidate profile while the
# others stay on their baseline. That is what a shadow evaluation needs (Phase 8
# is "shadow-then-promote, never auto-apply") and a directory-level override
# cannot express it.
_ENGINE_ENV_TEMPLATE = "SYNDICATE_CALIBRATION_PROFILE_PATH_{engine}"


def calibration_profile_dir() -> Path:
    """Directory holding versioned calibration profile artifacts."""
    raw = str(os.environ.get(_DIR_ENV) or "").strip()
    if raw:
        return Path(raw)
    return repo_root_from(__file__) / "data" / "calibration"


def calibration_profile_path(engine: str) -> Path:
    """Artifact path for one engine, e.g. `calibration_profile_path("nhl")`.

    Returns a path that need not exist. `load_versioned_profile` treats an absent
    file as "use the in-source default", so a missing artifact is the NORMAL
    state, not an error — which is what makes Phase 5 a no-op deploy.
    """
    slug = str(engine or "").strip().lower()
    if not slug:
        raise ValueError("engine must be a non-empty slug")
    explicit = str(os.environ.get(_ENGINE_ENV_TEMPLATE.format(engine=slug.upper())) or "").strip()
    if explicit:
        return Path(explicit)
    return calibration_profile_dir() / f"{slug}_profile.json"
