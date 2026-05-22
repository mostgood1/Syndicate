from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from syndicate.app import create_app

REFERENCE_SURFACES = (
    "cards",
    "game",
    "live-lens",
    "daily archive",
    "season betting-card",
    "hub",
)

DEPENDENCY_TIERS: dict[str, dict[str, object]] = {
    "owned_local": {
        "score": 100,
        "label": "Owned local",
        "description": "Primary workflows are backed by Syndicate-owned artifacts or refresh paths.",
    },
    "artifact_backed": {
        "score": 85,
        "label": "Artifact-backed",
        "description": "Primary workflows are driven by local mirrored or committed artifacts.",
    },
    "mixed_local_and_source": {
        "score": 65,
        "label": "Mixed local and source",
        "description": "Primary workflows are local-first, but important routes still depend on sibling source helpers.",
    },
    "source_backed": {
        "score": 45,
        "label": "Source-backed",
        "description": "Primary workflows still rely on source-app or subprocess-backed fallbacks for normal operation.",
    },
}


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit a snapshot of Syndicate module status versus the MLB reference contract.")
    parser.add_argument("--json", action="store_true", help="Emit the snapshot as JSON.")
    parser.add_argument("--write", type=Path, help="Optional output path for the generated JSON snapshot.")
    parser.add_argument("--write-text", type=Path, help="Optional output path for a human-readable parity gap summary.")
    return parser.parse_args(argv)


def normalize_runtime_contract(item: dict[str, Any], surfaces: list[str], *, reference_module: bool) -> dict[str, Any]:
    contract = item.get("runtime_contract") if isinstance(item.get("runtime_contract"), dict) else {}
    tier = str(contract.get("dependency_tier") or ("owned_local" if reference_module else "mixed_local_and_source")).strip()
    tier_meta = DEPENDENCY_TIERS.get(tier, DEPENDENCY_TIERS["mixed_local_and_source"])
    ownership_goal = str(contract.get("ownership_goal") or "mirror_first")
    fallback_surfaces = [
        str(value).strip() for value in (contract.get("fallback_surfaces") or []) if str(value).strip()
    ]
    score = int(tier_meta["score"])
    if tier == "artifact_backed" and not fallback_surfaces:
        if ownership_goal == "mirror_first":
            score = min(100, score + 5)
        elif ownership_goal == "artifact_backed":
            score = min(100, score + 3)
    if fallback_surfaces:
        score = max(0, score - (len(fallback_surfaces) * 3))
    mirror_ready_surfaces = [surface for surface in surfaces if surface not in set(fallback_surfaces)]
    blockers = [f"{surface} still depends on source fallback" for surface in fallback_surfaces]
    return {
        "dependency_tier": tier,
        "dependency_label": str(tier_meta["label"]),
        "dependency_description": str(tier_meta["description"]),
        "ownership_goal": ownership_goal,
        "source_of_truth": str(contract.get("source_of_truth") or "Mixed local and source-backed workflows"),
        "ownership_score": score,
        "fallback_surfaces": fallback_surfaces,
        "mirror_ready_surfaces": mirror_ready_surfaces,
        "fallback_blockers": blockers,
    }


def has_mlb_shaped_primary(item: dict[str, Any], slug: str, *, reference_module: bool) -> bool:
    if reference_module:
        return True
    primary_href = str(item.get("primary_href") or "").strip()
    return primary_href.startswith(f"/{slug}")


def module_snapshot() -> dict[str, Any]:
    app = create_app()
    modules = []
    for item in app.config.get("SYNDICATE_SPORTS", []):
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip()
        surfaces = [str(value).strip() for value in (item.get("surfaces") or []) if str(value).strip()]
        lower_surfaces = {value.lower() for value in surfaces}
        reference_module = slug == "mlb"
        mlb_shaped_primary = has_mlb_shaped_primary(item, slug, reference_module=reference_module)
        missing_reference_surfaces = [value for value in REFERENCE_SURFACES if value not in lower_surfaces]
        parity_gap_count = len(missing_reference_surfaces) + (0 if mlb_shaped_primary else 1)
        runtime_contract = normalize_runtime_contract(item, surfaces, reference_module=reference_module)
        modules.append(
            {
                "slug": slug,
                "name": item.get("name"),
                "status": item.get("status"),
                "phase": item.get("phase"),
                "summary": item.get("summary"),
                "primary_href": item.get("primary_href"),
                "primary_label": item.get("primary_label"),
                "surfaces": surfaces,
                "next_step": item.get("next_step"),
                "runtime_contract": runtime_contract,
                "contract_alignment": {
                    "reference_module": reference_module,
                    "mlb_shaped_primary": mlb_shaped_primary,
                    "has_cards": "cards" in lower_surfaces,
                    "has_game": "game" in lower_surfaces,
                    "has_live_lens": "live-lens" in lower_surfaces,
                    "has_hub": "hub" in lower_surfaces,
                    "archive_like_surfaces": [
                        value for value in surfaces if "archive" in value.lower() or "historical" in value.lower() or "results" in value.lower()
                    ],
                    "missing_reference_surfaces": missing_reference_surfaces,
                    "parity_gap_count": parity_gap_count,
                },
            }
        )
    gap_summary = build_gap_summary(modules)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reference_module": "mlb",
        "reference_surfaces": list(REFERENCE_SURFACES),
        "modules": modules,
        "gap_summary": gap_summary,
    }


def build_gap_summary(modules: list[dict[str, Any]]) -> dict[str, Any]:
    non_reference_modules = [module for module in modules if not module["contract_alignment"]["reference_module"]]
    ranked_modules = sorted(
        non_reference_modules,
        key=lambda module: (
            module["contract_alignment"]["parity_gap_count"],
            len(module["contract_alignment"]["missing_reference_surfaces"]),
            module["slug"],
        ),
    )
    ownership_ranked_modules = sorted(
        non_reference_modules,
        key=lambda module: (
            int(module["runtime_contract"]["ownership_score"]),
            len(module["runtime_contract"]["fallback_surfaces"]),
            module["slug"],
        ),
    )
    surface_gap_counts = []
    for surface in REFERENCE_SURFACES:
        missing_modules = [module["slug"] for module in non_reference_modules if surface in module["contract_alignment"]["missing_reference_surfaces"]]
        surface_gap_counts.append(
            {
                "surface": surface,
                "module_count": len(missing_modules),
                "modules": missing_modules,
            }
        )
    surface_gap_counts.sort(key=lambda item: (-item["module_count"], item["surface"]))
    return {
        "aligned_modules": [module["slug"] for module in non_reference_modules if module["contract_alignment"]["parity_gap_count"] == 0],
        "modules_needing_primary_alignment": [
            module["slug"] for module in non_reference_modules if not module["contract_alignment"]["mlb_shaped_primary"]
        ],
        "modules_ranked_by_gap_count": [
            {
                "slug": module["slug"],
                "name": module["name"],
                "parity_gap_count": module["contract_alignment"]["parity_gap_count"],
                "missing_reference_surfaces": module["contract_alignment"]["missing_reference_surfaces"],
                "next_step": module.get("next_step"),
            }
            for module in ranked_modules
        ],
        "modules_ranked_by_ownership": [
            {
                "slug": module["slug"],
                "name": module["name"],
                "ownership_score": module["runtime_contract"]["ownership_score"],
                "dependency_tier": module["runtime_contract"]["dependency_tier"],
                "fallback_surfaces": module["runtime_contract"]["fallback_surfaces"],
                "next_step": module.get("next_step"),
            }
            for module in ownership_ranked_modules
        ],
        "surface_gap_counts": surface_gap_counts,
        "highest_leverage_gaps": [item for item in surface_gap_counts if item["module_count"] > 0][:3],
        "lowest_ownership_modules": [
            {
                "slug": module["slug"],
                "name": module["name"],
                "ownership_score": module["runtime_contract"]["ownership_score"],
                "dependency_tier": module["runtime_contract"]["dependency_tier"],
                "fallback_surfaces": module["runtime_contract"]["fallback_surfaces"],
            }
            for module in ownership_ranked_modules[:3]
        ],
    }


def render_text_report(snapshot: dict[str, Any]) -> str:
    gap_summary = snapshot["gap_summary"]
    ranked_modules = [
        module for module in (gap_summary.get("modules_ranked_by_gap_count") or []) if int(module.get("parity_gap_count") or 0) > 0
    ]
    lines = [
        f"Generated: {snapshot['generated_at']}",
        f"Reference module: {snapshot['reference_module'].upper()}",
        "",
        "Highest leverage MLB parity gaps:",
    ]
    highest_leverage_gaps = gap_summary.get("highest_leverage_gaps") or []
    if highest_leverage_gaps:
        lines.extend(
            f"- {item['surface']}: {item['module_count']} modules ({', '.join(item['modules'])})"
            for item in highest_leverage_gaps
        )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "Modules ranked by remaining gap count:",
        ]
    )
    if ranked_modules:
        for module in ranked_modules:
            missing_surfaces = ", ".join(module["missing_reference_surfaces"]) or "none"
            lines.append(
                f"- {module['slug']}: gaps={module['parity_gap_count']}; missing={missing_surfaces}; next={module['next_step']}"
            )
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "Lowest ownership / source-independence modules:",
        ]
    )
    lowest_ownership_modules = gap_summary.get("lowest_ownership_modules") or []
    if lowest_ownership_modules:
        for module in lowest_ownership_modules:
            fallback_surfaces = ", ".join(module["fallback_surfaces"]) or "none"
            lines.append(
                f"- {module['slug']}: score={module['ownership_score']}; tier={module['dependency_tier']}; fallback={fallback_surfaces}"
            )
    else:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(list(argv) if argv is not None else sys.argv[1:])
    snapshot = module_snapshot()
    output = json.dumps(snapshot, indent=2) + "\n"
    text_output = render_text_report(snapshot)
    if args.write:
        output_path = args.write if args.write.is_absolute() else ROOT / args.write
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    if args.write_text:
        text_output_path = args.write_text if args.write_text.is_absolute() else ROOT / args.write_text
        text_output_path.parent.mkdir(parents=True, exist_ok=True)
        text_output_path.write_text(text_output, encoding="utf-8")
    if args.json or not args.write:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())