"""Expand the SmartSim 2.0 NCAAF public-trial cohort with new tiers.

Appends new cryptographically random tokens (same `secrets.token_urlsafe(18)`
scheme used for the original 10-slot cohort in Public Trial Operations) to
`data/ncaaf_source/data/smartsim2_trial_cohort.json`. Existing entries are
never modified or removed -- this is strictly additive, matching the "expand
access" (not "replace access") intent of `smartsim_expanded_trial_plan.md`.

This script only manages trial-access tokens (an allowlist config artifact).
It does not touch SmartSim 2.0, the Enhanced Totals Engine, calibration
profiles, blend formulas, or the decision policy.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.ncaaf.sources import default_ncaaf_source_root  # noqa: E402

COHORT_PATH = default_ncaaf_source_root() / "data" / "smartsim2_trial_cohort.json"

# (role, count) -- sizes taken from smartsim_expanded_trial_plan.md Task 1
# ("+5-10" for extended internal, "+15-25" for opt-in beta); mid-range values chosen.
DEFAULT_TIERS: tuple[tuple[str, int], ...] = (
    ("extended_internal", 8),
    ("opt_in_beta", 20),
)


def load_cohort(path: Path = COHORT_PATH) -> dict:
    if not path.exists():
        return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), "note": "", "cohort": []}
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def expand_cohort(data: dict, tiers: tuple[tuple[str, int], ...]) -> dict:
    existing_slots = {entry["slot"] for entry in data["cohort"]}
    for role, count in tiers:
        existing_count = sum(1 for entry in data["cohort"] if entry["role"] == role)
        for i in range(existing_count + 1, existing_count + count + 1):
            slot = f"{role}-{i}"
            if slot in existing_slots:
                continue
            data["cohort"].append(
                {
                    "slot": slot,
                    "role": role,
                    "token": secrets.token_urlsafe(18),
                    "status": "active",
                }
            )
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    return data


def write_cohort(data: dict, path: Path = COHORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        action="append",
        default=None,
        metavar="role:count",
        help="Add a tier as role:count (repeatable). Defaults to extended_internal:8,opt_in_beta:20.",
    )
    args = parser.parse_args()

    tiers = DEFAULT_TIERS
    if args.tier:
        tiers = tuple((role, int(count)) for role, count in (t.split(":", 1) for t in args.tier))

    data = load_cohort()
    before_by_role: dict[str, int] = {}
    for entry in data["cohort"]:
        before_by_role[entry["role"]] = before_by_role.get(entry["role"], 0) + 1

    data = expand_cohort(data, tiers)
    write_cohort(data)

    after_by_role: dict[str, int] = {}
    for entry in data["cohort"]:
        after_by_role[entry["role"]] = after_by_role.get(entry["role"], 0) + 1

    print(f"cohort_path={COHORT_PATH}")
    print(f"before_by_role={before_by_role}")
    print(f"after_by_role={after_by_role}")
    print(f"total_before={sum(before_by_role.values())}")
    print(f"total_after={sum(after_by_role.values())}")


if __name__ == "__main__":
    main()
