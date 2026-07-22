"""Uniform per-sport data-sourcing contract for the betting board.

Historically, whether a sport's games/props ever reached the board was
decided independently by four hand-written per-sport dispatch chains in
``syndicate/blueprints/home.py`` (``_is_active_today``, ``_load_home_games``,
``_load_home_pregame_prop_items``, ``_load_home_live_prop_items``). A sport
missing from any one of them silently produced an empty board for that
sport -- this is how soccer went completely missing despite having a real
manifest, sim engine, and cards/props modules.

``SportDataProvider`` gives every sport one registration point instead.
Concrete providers live in ``home.py`` (where the imports and helper
functions they wrap already live); this module only defines the shared
shape so an unregistered sport is an explicit, visible gap -- a ``None``
from ``registry.get(slug)`` -- rather than a branch nobody remembered to add.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root


@dataclass(frozen=True)
class SportContext:
    """Normalized time-period selector.

    ``resolve_context`` is a thin packaging step, not a reimplementation of
    a sport's own "which date/week is selected" logic -- that selection
    still happens in ``home.py`` (available dates, live-game overrides,
    etc.) exactly as it does today. This class just gives every downstream
    dispatch call a single, uniform shape to pass around instead of each
    sport's raw date/week/league keying scheme.
    """

    slug: str
    context_label: str
    season: int | None = None
    week: int | None = None
    league: str | None = None


class SportDataProvider(Protocol):
    slug: str

    def is_active(self, *, today_value: str, context_label: str) -> bool: ...

    def resolve_context(
        self,
        *,
        requested_date: str | None = None,
        season: int | None = None,
        week: int | None = None,
    ) -> SportContext: ...

    def games(self, context: SportContext, *, is_active_today: bool) -> list[dict[str, Any]]: ...

    def pregame_props(
        self,
        context: SportContext,
        home_games: list[dict[str, Any]],
        *,
        is_active_today: bool,
    ) -> list[dict[str, Any]]: ...

    def live_props(
        self,
        context: SportContext,
        home_games: list[dict[str, Any]],
        *,
        is_active_today: bool,
    ) -> list[dict[str, Any]]: ...

    def data_sources(self, context: SportContext) -> dict[str, Any]: ...


def artifact_signature(path: str | Path | None) -> dict[str, Any]:
    """Same {path, exists, size, mtime_ns} shape as
    ``pipeline.intelligence_state.IntelligenceStateService._artifact_signature``,
    reused here so a provider's ``data_sources()`` output is directly
    comparable to the canonical board-state diagnostics."""
    path_text = str(path or "").strip()
    if not path_text:
        return {"path": "", "exists": False, "size": None, "mtime_ns": None}
    resolved = Path(path_text)
    try:
        stat_result = resolved.stat()
    except OSError:
        return {"path": path_text, "exists": False, "size": None, "mtime_ns": None}
    return {
        "path": path_text,
        "exists": True,
        "size": int(stat_result.st_size),
        "mtime_ns": int(stat_result.st_mtime_ns),
    }


def sport_manifest_signature(sport_slug: str) -> dict[str, Any]:
    manifest_path = reports_root() / "manifests" / f"{str(sport_slug or '').strip().lower()}.json"
    signature = artifact_signature(manifest_path)
    manifest = read_json_file(manifest_path)
    if isinstance(manifest, dict):
        signature.update(
            {
                "sport": str(manifest.get("sport") or "").strip().lower(),
                "last_updated": str(manifest.get("last_updated") or "").strip(),
                "status": str(manifest.get("status") or "").strip().lower(),
                "post_refresh_ok": manifest.get("post_refresh_ok"),
            }
        )
    return signature


SPORT_DATA_PROVIDERS: dict[str, SportDataProvider] = {}


def register_sport_data_provider(provider: SportDataProvider) -> None:
    SPORT_DATA_PROVIDERS[provider.slug] = provider


def get_sport_data_provider(slug: str) -> SportDataProvider | None:
    return SPORT_DATA_PROVIDERS.get(str(slug or "").strip().lower())
