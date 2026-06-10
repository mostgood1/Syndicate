from __future__ import annotations

from typing import Any

from syndicate.features.intelligence_analysis_common import signal_value


def build_mlb_prop_analysis_views(
    candidates: list[dict[str, Any]],
    preferences: dict[str, Any],
    *,
    safe_text,
    candidate_market_focuses,
    advanced_signal_text,
    mlb_statcast_market_text,
) -> dict[str, Any] | None:
    if preferences.get("analysis_focus") != "mlb_props":
        return None
    requested_markets = {str(item).strip().lower() for item in (preferences.get("requested_markets") or []) if str(item).strip()}
    filtered = [candidate for candidate in candidates if safe_text(candidate.get("sport_slug"), "").lower() == "mlb"]
    if requested_markets:
        filtered = [candidate for candidate in filtered if candidate_market_focuses(candidate) & requested_markets]
    top_rows = filtered[: min(int(preferences.get("limit") or 5), 10)]
    if not top_rows:
        return None

    table_rows: list[dict[str, Any]] = []
    chart_rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(top_rows, start=1):
        market_focuses = candidate_market_focuses(candidate)
        market_key = next(iter(sorted(requested_markets & market_focuses))) if requested_markets & market_focuses else next(iter(sorted(market_focuses)), "general_market")
        statcast_profile = candidate.get("mlb_statcast_profile") if isinstance(candidate.get("mlb_statcast_profile"), dict) else {}
        batter_profile = statcast_profile.get("batter") if isinstance(statcast_profile.get("batter"), dict) else {}
        pitcher_profile = statcast_profile.get("pitcher") if isinstance(statcast_profile.get("pitcher"), dict) else {}
        pitch_mix = pitcher_profile.get("top_pitch_mix") if isinstance(pitcher_profile.get("top_pitch_mix"), list) else []
        pitch_mix_text = ", ".join(
            f"{safe_text(item.get('pitch_type'), '?')} {float(item.get('share') or 0.0) * 100.0:.0f}%"
            for item in pitch_mix[:3]
            if isinstance(item, dict)
        )
        why = mlb_statcast_market_text(statcast_profile, market_key) or advanced_signal_text(candidate, limit=3) or safe_text(candidate.get("writeup"), "-")
        row = {
            "rank": index,
            "label": safe_text(candidate.get("name"), "Play"),
            "matchup": safe_text(candidate.get("matchup"), "-"),
            "market": safe_text(candidate.get("market"), "Market"),
            "market_key": market_key,
            "pick": safe_text(candidate.get("pick"), "-"),
            "line": safe_text(candidate.get("line"), "-"),
            "projected": safe_text(candidate.get("projected"), "-"),
            "odds": safe_text(candidate.get("odds"), "-"),
            "score": round(float(candidate.get("score") or 0.0), 2),
            "advanced_signal_score": round(float(candidate.get("advanced_signal_score") or 0.0), 2),
            "batter_ev_mean": round(float(batter_profile.get("ev_mean") or 0.0), 1) if batter_profile.get("ev_mean") is not None else None,
            "batter_hardhit_rate": round(float(batter_profile.get("hardhit_rate") or 0.0) * 100.0, 1) if batter_profile.get("hardhit_rate") is not None else None,
            "batter_xwoba": round(float(batter_profile.get("xwoba") or 0.0), 3) if batter_profile.get("xwoba") is not None else None,
            "batter_k_mult": signal_value(candidate, "batter_statcast_k_mult") or batter_profile.get("k_mult"),
            "pitcher_k_mult": signal_value(candidate, "pitcher_statcast_k_mult") or pitcher_profile.get("k_mult"),
            "batter_inplay_mult": signal_value(candidate, "batter_statcast_inplay_mult") or batter_profile.get("inplay_mult"),
            "pitcher_inplay_mult": signal_value(candidate, "pitcher_statcast_inplay_mult") or pitcher_profile.get("inplay_mult"),
            "pitcher_xwoba_allowed": round(float(pitcher_profile.get("xwoba_allowed") or 0.0), 3) if pitcher_profile.get("xwoba_allowed") is not None else None,
            "pitch_mix": pitch_mix_text or None,
            "why": why,
        }
        table_rows.append(row)
        chart_rows.append(
            {
                "label": row["label"],
                "score": row["score"],
                "advanced_signal_score": row["advanced_signal_score"],
                "batter_k_mult": row["batter_k_mult"],
                "pitcher_k_mult": row["pitcher_k_mult"],
                "batter_inplay_mult": row["batter_inplay_mult"],
                "pitcher_inplay_mult": row["pitcher_inplay_mult"],
                "batter_ev_mean": row["batter_ev_mean"],
            }
        )

    return {
        "focus": "mlb_props",
        "title": "Top MLB prop matchups",
        "table": {
            "title": "Top Statcast-backed MLB prop targets",
            "columns": [
                "rank",
                "label",
                "matchup",
                "market",
                "pick",
                "line",
                "projected",
                "odds",
                "expected_value",
                "edge_pct",
                "confidence",
                "model_probability",
                "market_probability",
                "historical_context",
                "reasoning",
                "score",
                "advanced_signal_score",
                "batter_ev_mean",
                "batter_hardhit_rate",
                "batter_xwoba",
                "batter_k_mult",
                "pitcher_k_mult",
                "batter_inplay_mult",
                "pitcher_inplay_mult",
                "pitcher_xwoba_allowed",
                "pitch_mix",
                "why",
            ],
            "rows": table_rows,
        },
        "chart": {
            "title": "MLB prop score grid",
            "type": "bar",
            "x_key": "label",
            "series": ["score", "advanced_signal_score", "batter_k_mult", "pitcher_k_mult", "batter_inplay_mult", "pitcher_inplay_mult", "batter_ev_mean"],
            "rows": chart_rows,
        },
    }