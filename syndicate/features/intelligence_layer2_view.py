"""The ONE pick list, as every surface reads it.

User 2026-10-07: "we shouldnt have seperate lists being generated". The Layer 2
board is the list: execution trades it, `/intelligence` and Ask already read
it through `read_combined_intelligence_response` (Layer 2 first, measured
10-07: 4,478 of 4,500 served rows were `layer2_shortlist`). Two surfaces still
read the LEGACY per-date state instead: `/api/intelligence/status` (77 legacy
recommendations on 10-07) and Home's top-edges rail (12 MLB rows reading
"Under 0"). They read this instead.

Read-only by construction: `read_combined_intelligence_response` never computes
(its own invariant), so this is safe on web. Returns {} on any failure so a
caller keeps its old path rather than serving nothing.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Mapping

PICK_LIST_KEYS = ("recommendations", "top_opportunities", "ranked_all", "board_contract", "by_sport", "candidate_count")


def layer2_board_view(selected_date: str | None = None, *, sport: str = "all", limit: int | None = None) -> dict[str, Any]:
    try:
        from pipeline.intelligence_state import read_combined_intelligence_response

        combined = read_combined_intelligence_response(
            dates=[selected_date] if selected_date else None, sport=sport or "all", limit=limit
        )
    except Exception as exc:  # noqa: BLE001 -- a view must degrade, never break the page
        print(f"[layer2_view] READ_FAILED date={selected_date} error={type(exc).__name__}: {exc}", flush=True)
        return {}
    if not isinstance(combined, Mapping):
        return {}
    body = combined.get("response") if isinstance(combined.get("response"), Mapping) else combined
    picks = [item for item in (body.get("top_opportunities") or body.get("ranked_all") or []) if isinstance(item, Mapping)]
    if not picks:
        return {}
    by_sport: "OrderedDict[str, list[Mapping[str, Any]]]" = OrderedDict()
    for item in picks:
        slug = str(item.get("sport_slug") or item.get("sport") or "").strip().lower() or "other"
        by_sport.setdefault(slug, []).append(item)
    return {
        "recommendations": picks,
        "top_opportunities": picks,
        "ranked_all": [item for item in (body.get("ranked_all") or picks) if isinstance(item, Mapping)],
        "board_contract": body.get("board_contract") if isinstance(body.get("board_contract"), Mapping) else {},
        "by_sport": dict(by_sport),
        "candidate_count": len(picks),
        "pick_list_source": "layer2_combined_board",
        "layer2_rows": sum(1 for item in picks if str(item.get("source") or "").startswith("layer2")),
    }


def overlay_pick_lists(payload: Mapping[str, Any], view: Mapping[str, Any]) -> dict[str, Any]:
    """`payload` with its pick lists replaced by the Layer 2 view's.

    Every other field (freshness, state_meta, portfolio, layer2_shortlist...) is
    kept: those describe the build, not the list. The legacy recommendations are
    kept under `legacy_recommendations` for the comparison window, and only
    when the view actually has picks.
    """
    out = dict(payload or {})
    if not view or not view.get("recommendations"):
        return out
    out["legacy_recommendations"] = list(out.get("recommendations") or [])
    out["legacy_candidate_count"] = out.get("candidate_count")
    for key in PICK_LIST_KEYS:
        out[key] = view.get(key)
    out["pick_list_source"] = view.get("pick_list_source")
    return out
