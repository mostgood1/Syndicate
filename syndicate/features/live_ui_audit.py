from __future__ import annotations

import argparse
import copy
import json
from statistics import mean
from typing import Any


EDGE_THRESHOLD = 0.01
TIER_BOUNDS = (0.05, 0.08, 0.12)


def _tier_for_edge(edge: float) -> str:
    if edge < TIER_BOUNDS[0]:
        return "tier_1"
    if edge < TIER_BOUNDS[1]:
        return "tier_2"
    if edge < TIER_BOUNDS[2]:
        return "tier_3"
    return "tier_4"


def _movement_for_change(previous_edge: float, next_edge: float) -> dict[str, Any]:
    delta = round(next_edge - previous_edge, 4)
    if abs(delta) < EDGE_THRESHOLD:
        return {"trend": "flat", "edge_delta": delta, "highlight": "none", "should_render": False}
    if delta > 0:
        return {"trend": "up", "edge_delta": delta, "highlight": "green-pulse", "should_render": True}
    return {"trend": "down", "edge_delta": delta, "highlight": "red-fade", "should_render": True}


def _mock_picks() -> list[dict[str, Any]]:
    seeds = [
        ("pick-001", "MLB", "Player A over 1.5 hits", "hits", 0.032, 0.574, 0.542),
        ("pick-002", "NBA", "Team B -3.5", "spread", 0.046, 0.558, 0.512),
        ("pick-003", "NHL", "Goalie C under 29.5 saves", "saves", 0.071, 0.613, 0.542),
        ("pick-004", "WNBA", "Forward D over 7.5 rebounds", "rebounds", 0.088, 0.642, 0.554),
    ]
    picks: list[dict[str, Any]] = []
    for pick_id, sport, selection, market, edge, model_probability, implied_probability in seeds:
        picks.append(
            {
                "pick_id": pick_id,
                "sport": sport,
                "selection": selection,
                "market": market,
                "edge": round(edge, 4),
                "model_probability": round(model_probability, 4),
                "implied_probability": round(implied_probability, 4),
                "badge_tier": _tier_for_edge(edge),
                "movement": {"trend": "flat", "edge_delta": 0.0, "highlight": "none"},
                "badge_animation": False,
            }
        )
    return picks


def _copy_picks(picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [copy.deepcopy(pick) for pick in picks]


def _index_picks(picks: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    for pick in picks:
        pick_id = str(pick.get("pick_id") or "").strip()
        if pick_id:
            indexed[pick_id] = pick
    return indexed


def _changed_fields(previous: dict[str, Any] | None, next_pick: dict[str, Any] | None) -> list[str]:
    if previous is None and next_pick is not None:
        return ["added"]
    if previous is not None and next_pick is None:
        return ["removed"]
    if previous is None or next_pick is None:
        return []

    changed: list[str] = []
    for field in ("sport", "selection", "market", "edge", "model_probability", "implied_probability", "badge_tier", "badge_animation"):
        if previous.get(field) != next_pick.get(field):
            changed.append(field)

    previous_movement = previous.get("movement") if isinstance(previous.get("movement"), dict) else {}
    next_movement = next_pick.get("movement") if isinstance(next_pick.get("movement"), dict) else {}
    for field in ("trend", "edge_delta", "highlight"):
        if previous_movement.get(field) != next_movement.get(field):
            changed.append(f"movement.{field}")
    return changed


def _build_baseline_state() -> list[dict[str, Any]]:
    return _copy_picks(_mock_picks())


def _scenario_small_edge_change(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_state = _copy_picks(state)
    next_state[0]["edge"] = round(float(next_state[0]["edge"]) + 0.002, 4)
    return next_state


def _scenario_meaningful_edge_increase(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_state = _copy_picks(state)
    next_state[0]["edge"] = round(float(next_state[0]["edge"]) + 0.014, 4)
    return next_state


def _scenario_meaningful_edge_decrease(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_state = _copy_picks(state)
    next_state[1]["edge"] = round(float(next_state[1]["edge"]) - 0.016, 4)
    return next_state


def _scenario_edge_tier_crossing(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_state = _copy_picks(state)
    next_state[3]["edge"] = round(0.132, 4)
    return next_state


def _scenario_no_change(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _copy_picks(state)


def _scenario_new_pick_added(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_state = _copy_picks(state)
    next_state.append(
        {
            "pick_id": "pick-005",
            "sport": "NCAAB",
            "selection": "Guard E over 4.5 assists",
            "market": "assists",
            "edge": 0.028,
            "model_probability": 0.528,
            "implied_probability": 0.500,
            "badge_tier": _tier_for_edge(0.028),
            "movement": {"trend": "flat", "edge_delta": 0.0, "highlight": "none"},
            "badge_animation": False,
        }
    )
    return next_state


def _scenario_pick_removed(state: list[dict[str, Any]]) -> list[dict[str, Any]]:
    next_state = _copy_picks(state)
    return [pick for pick in next_state if str(pick.get("pick_id") or "") != "pick-005"]


def _scenario_definitions() -> list[tuple[str, str, Any]]:
    return [
        ("A", "SMALL EDGE CHANGE (Below Threshold)", _scenario_small_edge_change),
        ("B", "MEANINGFUL EDGE INCREASE", _scenario_meaningful_edge_increase),
        ("C", "MEANINGFUL EDGE DECREASE", _scenario_meaningful_edge_decrease),
        ("D", "EDGE TIER CROSSING", _scenario_edge_tier_crossing),
        ("E", "NO CHANGE", _scenario_no_change),
        ("F", "NEW PICK ADDED", _scenario_new_pick_added),
        ("G", "PICK REMOVED", _scenario_pick_removed),
    ]


def _evaluate_cycle(
    cycle_name: str,
    previous_state: list[dict[str, Any]],
    next_state: list[dict[str, Any]],
    animated_ids: set[str],
) -> dict[str, Any]:
    previous_index = _index_picks(previous_state)
    next_index = _index_picks(next_state)
    previous_ids = list(previous_index)
    next_ids = list(next_index)
    union_ids = list(previous_ids)
    for pick_id in next_ids:
        if pick_id not in previous_index:
            union_ids.append(pick_id)

    duplicate_ids = len(next_ids) != len(next_state)
    changed_rows: list[dict[str, Any]] = []
    re_rendered_count = 0
    threshold_failures: list[str] = []
    animation_failures: list[str] = []
    identity_failures: list[str] = []

    for pick_id in union_ids:
        previous_pick = previous_index.get(pick_id)
        next_pick = next_index.get(pick_id)

        if previous_pick is None and next_pick is not None:
            changed_rows.append(
                {
                    "pick_id": pick_id,
                    "changed_fields": ["added"],
                    "re_rendered": True,
                    "highlight": "none",
                    "animation_triggered": False,
                    "triggered_updates": ["added"],
                    "skipped_update": False,
                }
            )
            re_rendered_count += 1
            continue

        if previous_pick is not None and next_pick is None:
            changed_rows.append(
                {
                    "pick_id": pick_id,
                    "changed_fields": ["removed"],
                    "re_rendered": False,
                    "highlight": "none",
                    "animation_triggered": False,
                    "triggered_updates": ["removed"],
                    "skipped_update": False,
                }
            )
            continue

        if previous_pick is None or next_pick is None:
            continue

        previous_edge = float(previous_pick.get("edge") or 0.0)
        next_edge = float(next_pick.get("edge") or 0.0)
        movement = _movement_for_change(previous_edge, next_edge)
        tier_changed = previous_pick.get("badge_tier") != _tier_for_edge(next_edge)
        changed_fields = _changed_fields(previous_pick, next_pick)

        re_rendered = movement["should_render"]
        highlight = movement["highlight"] if re_rendered else "none"
        animation_triggered = False

        updated_pick = copy.deepcopy(next_pick)
        updated_pick["movement"] = {"trend": movement["trend"], "edge_delta": movement["edge_delta"], "highlight": highlight}
        updated_pick["badge_tier"] = _tier_for_edge(next_edge)

        if re_rendered and tier_changed:
            if pick_id in animated_ids:
                animation_failures.append(f"{cycle_name}:{pick_id} badge animation retriggered after tier crossing")
            else:
                animation_triggered = True
                animated_ids.add(pick_id)
                updated_pick["badge_animation"] = True
        else:
            updated_pick["badge_animation"] = False

        if abs(next_edge - previous_edge) < EDGE_THRESHOLD:
            if re_rendered:
                threshold_failures.append(f"{cycle_name}:{pick_id} below-threshold change triggered rerender")
            if animation_triggered:
                threshold_failures.append(f"{cycle_name}:{pick_id} below-threshold change triggered animation")
            if highlight != "none":
                threshold_failures.append(f"{cycle_name}:{pick_id} below-threshold change produced highlight {highlight}")

        if not changed_fields and re_rendered:
            identity_failures.append(f"{cycle_name}:{pick_id} rerendered with no changed fields")

        changed_rows.append(
            {
                "pick_id": pick_id,
                "changed_fields": changed_fields,
                "re_rendered": re_rendered,
                "highlight": highlight,
                "animation_triggered": animation_triggered,
                "triggered_updates": [value for value in (["rerender"] if re_rendered else []) + (["badge_animation"] if animation_triggered else [])],
                "skipped_update": not re_rendered,
            }
        )

        if re_rendered:
            re_rendered_count += 1

    compared_count = max(1, len(previous_index))
    render_rate = round((re_rendered_count / compared_count) * 100.0, 2)

    return {
        "cycle": cycle_name,
        "previous_count": len(previous_state),
        "next_count": len(next_state),
        "changed_rows": changed_rows,
        "rendered_count": re_rendered_count,
        "compared_count": compared_count,
        "render_rate_pct": render_rate,
        "threshold_failures": threshold_failures,
        "animation_failures": animation_failures,
        "identity_failures": identity_failures,
        "duplicate_ids": duplicate_ids,
        "added_ids": sorted(set(next_index) - set(previous_index)),
        "removed_ids": sorted(set(previous_index) - set(next_index)),
    }


def run_live_ui_audit() -> dict[str, Any]:
    state = _build_baseline_state()
    animated_ids: set[str] = set()
    tests_failed: list[str] = []
    cycle_scores: list[bool] = []
    render_rates: list[float] = []
    cycle_results: list[dict[str, Any]] = []
    threshold_ok = True
    animation_ok = True
    identity_ok = True

    print("Live UI audit starting")
    print(f"Baseline picks: {len(state)}")

    for cycle_name, description, scenario in _scenario_definitions():
        next_state = scenario(state)
        result = _evaluate_cycle(cycle_name, state, next_state, animated_ids)
        cycle_results.append(result)
        render_rates.append(result["render_rate_pct"])

        print(f"\nCycle {cycle_name} - {description}")
        print(f"  picks: {result['previous_count']} -> {result['next_count']}")
        print(f"  render_rate={result['render_rate_pct']}% rendered_count={result['rendered_count']}")
        if result["added_ids"]:
            print(f"  added={result['added_ids']}")
        if result["removed_ids"]:
            print(f"  removed={result['removed_ids']}")
        for row in result["changed_rows"]:
            print(
                "  pick {pick_id}: changed_fields={changed_fields} re_rendered={re_rendered} highlight={highlight} animation_triggered={animation_triggered}".format(
                    **row
                )
            )

        cycle_failed = False
        expected_by_cycle = {
            "A": (set(), set(), set(), set(), set()),
            "B": ({"pick-001"}, {"pick-001"}, set(), set(), set()),
            "C": ({"pick-002"}, {"pick-002"}, set(), set(), set()),
            "D": ({"pick-004"}, {"pick-004"}, {"pick-004"}, set(), set()),
            "E": (set(), set(), set(), set(), set()),
            "F": ({"pick-005"}, set(), set(), {"pick-005"}, set()),
            "G": (set(), set(), set(), set(), {"pick-005"}),
        }
        expected_rerendered, expected_highlight, expected_animation, expected_added, expected_removed = expected_by_cycle[cycle_name]
        observed_rerendered = {row["pick_id"] for row in result["changed_rows"] if row["re_rendered"]}
        observed_highlight = {row["pick_id"] for row in result["changed_rows"] if row["highlight"] != "none"}
        observed_animation = {row["pick_id"] for row in result["changed_rows"] if row["animation_triggered"]}
        observed_added = set(result["added_ids"])
        observed_removed = set(result["removed_ids"])
        if observed_rerendered != expected_rerendered:
            tests_failed.append(f"{cycle_name}: expected re-rendered {sorted(expected_rerendered)} got {sorted(observed_rerendered)}")
            cycle_failed = True
        if observed_highlight != expected_highlight:
            tests_failed.append(f"{cycle_name}: expected highlights {sorted(expected_highlight)} got {sorted(observed_highlight)}")
            cycle_failed = True
        if observed_animation != expected_animation:
            tests_failed.append(f"{cycle_name}: expected animation {sorted(expected_animation)} got {sorted(observed_animation)}")
            cycle_failed = True
        if observed_added != expected_added:
            tests_failed.append(f"{cycle_name}: expected added {sorted(expected_added)} got {sorted(observed_added)}")
            cycle_failed = True
        if observed_removed != expected_removed:
            tests_failed.append(f"{cycle_name}: expected removed {sorted(expected_removed)} got {sorted(observed_removed)}")
            cycle_failed = True

        if result["threshold_failures"]:
            threshold_ok = False
            tests_failed.extend(result["threshold_failures"])
            cycle_failed = True
        if result["animation_failures"]:
            animation_ok = False
            tests_failed.extend(result["animation_failures"])
            cycle_failed = True
        if result["identity_failures"] or result["duplicate_ids"]:
            identity_ok = False
            if result["duplicate_ids"]:
                tests_failed.append(f"{cycle_name}: duplicate ids detected")
            tests_failed.extend(result["identity_failures"])
            cycle_failed = True

        if result["render_rate_pct"] > 50.0 and cycle_name in {"A", "C", "E"}:
            tests_failed.append(f"{cycle_name}: excessive rerenders above 50% for a minimal-change cycle")
            cycle_failed = True

        cycle_scores.append(not cycle_failed)
        state = next_state

    final_ids = [pick["pick_id"] for pick in state]
    if len(final_ids) != len(set(final_ids)):
        identity_ok = False
        tests_failed.append("final_state: duplicate pick IDs detected")

    overall_render_rate = round(mean(render_rates), 2) if render_rates else 0.0
    health_score = max(0, min(100, 100 - (len(tests_failed) * 10)))
    tests_passed = sum(1 for passed in cycle_scores if passed) + int(threshold_ok) + int(animation_ok) + int(identity_ok)

    summary = {
        "total_cycles": len(cycle_results),
        "total_picks": len(state),
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "render_efficiency": {
            "average_render_rate_pct": overall_render_rate,
            "per_cycle": [
                {"cycle": cycle["cycle"], "render_rate_pct": cycle["render_rate_pct"], "rendered_count": cycle["rendered_count"]}
                for cycle in cycle_results
            ],
        },
        "threshold_integrity": "PASS" if threshold_ok else "FAIL",
        "animation_correctness": "PASS" if animation_ok else "FAIL",
        "health_score": health_score,
        "identity_stability": "PASS" if identity_ok else "FAIL",
        "cycles": cycle_results,
    }

    print("\nFinal summary")
    print(json.dumps({k: v for k, v in summary.items() if k != "cycles"}, indent=2, sort_keys=True, ensure_ascii=False, default=str))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a deterministic live intelligence UI audit")
    parser.add_argument("--json", action="store_true", help="Print the final summary JSON after debug output")
    args = parser.parse_args(argv)

    summary = run_live_ui_audit()
    if args.json:
        print(json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False, default=str))

    return 0 if not summary["tests_failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["run_live_ui_audit"]
