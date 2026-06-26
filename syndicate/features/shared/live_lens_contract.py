from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE
from syndicate.features.shared.timezone import central_now


def _safe_text(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    return text or fallback


def _refresh_interval_ms(value: Any, fallback: int = 30000) -> int:
    try:
        interval_ms = int(value)
    except Exception:
        interval_ms = fallback
    return max(1, interval_ms)


def _centralize_iso_timestamp(value: Any) -> str | None:
    text = _safe_text(value)
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=CENTRAL_TIMEZONE)
        return stamp.astimezone(CENTRAL_TIMEZONE).isoformat(timespec="seconds")
    except Exception:
        return text


def attach_live_lens_contract(
    context: dict[str, Any],
    *,
    sport: str,
    module: str,
    refresh_interval_ms: int = 30000,
    refresh_enabled: bool = True,
    refresh_on_visible: bool = True,
    refresh_on_focus: bool = True,
) -> dict[str, Any]:
    out = dict(context)
    generated_at = _centralize_iso_timestamp(out.get("generatedAt") or out.get("generated_at")) or central_now().isoformat(timespec="seconds")
    odds_refreshed_at = _centralize_iso_timestamp(out.get("oddsRefreshedAt") or out.get("odds_refreshed_at") or generated_at) or generated_at
    refresh_policy = {
        "enabled": bool(refresh_enabled),
        "intervalMs": _refresh_interval_ms(refresh_interval_ms),
        "refreshOnVisible": bool(refresh_on_visible),
        "refreshOnFocus": bool(refresh_on_focus),
        "poller": "shared.polling",
    }
    if generated_at is not None:
        out["generatedAt"] = generated_at
        out["generated_at"] = generated_at
    if odds_refreshed_at is not None:
        out["oddsRefreshedAt"] = odds_refreshed_at
        out["odds_refreshed_at"] = odds_refreshed_at
    out["refresh_policy"] = refresh_policy
    out["live_lens_contract"] = {
        "schema": "live_lens_v1",
        "sport": _safe_text(sport, "sport").lower(),
        "module": _safe_text(module, "live_lens").lower(),
        "generatedAt": generated_at,
        "oddsRefreshedAt": odds_refreshed_at,
        "refresh": refresh_policy,
        "source_path": out.get("source_path"),
        "source_title": out.get("source_title"),
        "route_path": out.get("route_path"),
    }
    return out


__all__ = ["attach_live_lens_contract"]