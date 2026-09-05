from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import urlparse
from typing import Any

from syndicate.features.nba.sources import load_json
from syndicate.features.nba.sources import season_betting_card_day_path
from syndicate.features.nba.sources import season_betting_card_manifest_path
from syndicate.features.shared.source_roots import preferred_source_roots


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _safe_probability(value: Any) -> float | None:
    probability = _safe_float(value)
    if probability is None:
        return None
    if probability > 1.0:
        probability /= 100.0
    if probability < 0.0:
        return None
    return max(0.0, min(1.0, probability))


def _enrich_recommendation_like_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        enriched = {key: _enrich_recommendation_like_payload(value) for key, value in payload.items()}
        if any(key in enriched for key in ("recommendation_id", "pick", "selection", "name")) and any(key in enriched for key in ("odds", "score", "line", "projected", "live_projection")):
            historical_context = enriched.get("historical_context") if isinstance(enriched.get("historical_context"), dict) else {"roi_segment": None, "sample_size": None}
            if "expected_value" not in enriched:
                enriched["expected_value"] = _safe_float(enriched.get("expected_value"))
            if "edge_pct" not in enriched:
                edge_value = _safe_float(enriched.get("edge"))
                enriched["edge_pct"] = round(edge_value * 100.0, 2) if edge_value is not None else None
            if "confidence" not in enriched:
                enriched["confidence"] = _safe_probability(enriched.get("confidence"))
            if "model_probability" not in enriched:
                enriched["model_probability"] = _safe_probability(enriched.get("model_probability") or enriched.get("confidence"))
            if "market_probability" not in enriched:
                enriched["market_probability"] = _safe_probability(enriched.get("market_probability") or enriched.get("implied_probability"))
            enriched["historical_context"] = historical_context
            if "reasoning" not in enriched:
                reasoning = enriched.get("reasoning_text") or enriched.get("rationale") or enriched.get("why")
                if isinstance(reasoning, list):
                    enriched["reasoning"] = reasoning
                elif reasoning:
                    enriched["reasoning"] = [str(reasoning)]
                else:
                    enriched["reasoning"] = []
        return enriched
    if isinstance(payload, list):
        return [_enrich_recommendation_like_payload(item) for item in payload]
    return payload


def _artifact_roots() -> list[Path]:
    """Candidate roots for NBA `web/` assets, in preference order.

    `SYNDICATE_NBA_ARTIFACT_ROOT` stays FIRST, so every path that resolves
    today resolves to exactly the same file. What changes is that it is no
    longer the ONLY root -- and a single-root lookup was structurally unable
    to serve these two files at all.

    `betting-card-v2.{css,js}` are git-tracked under `data/nba_source/web/`
    and appear in NO publish allowlist, so nothing ever copies them onto a
    Render disk; on Render they exist only inside the ephemeral checkout.
    Production points `SYNDICATE_NBA_ARTIFACT_ROOT` at the DISK
    (`/opt/render/project/data/nba_source/source_artifacts`), so the old
    lookup asked the one location the assets can never be in and had no
    second candidate to fall through to.

    MEASURED IN PRODUCTION 2026-09-05, before the fix:

        404      0 bytes  /nba/assets/betting-card-v2.js
        404     30 bytes  /nba/assets/betting-card-v2.css
        200 57,864 bytes  /wnba/assets/betting-card-v2.js
        200 17,881 bytes  /wnba/assets/betting-card-v2.css

    while `/nba/season/2026/betting-card` (HTTP 200) referenced both of the
    404s. WNBA served because its copy is VENDORED into the code tree at
    `syndicate/static/wnba/` -- it never depended on a root at all. The
    `?v=1` in that page's asset URLs was the same defect showing through
    `source_betting_card_asset_version`: `1` is its both-files-missing
    fallback, so the page had been announcing the breakage all along.

    `preferred_source_roots` supplies the remaining candidates and is what
    `nba/sources.py` in this same package already uses -- this function was
    the package's lone hand-rolled resolver. It also means these assets now
    honour `SYNDICATE_DATA_ROOT`, which they never did.
    """
    roots: list[Path] = []

    def _append(candidate: Path) -> None:
        resolved = candidate.resolve()
        if resolved not in roots:
            roots.append(resolved)

    env_value = str(os.environ.get("SYNDICATE_NBA_ARTIFACT_ROOT") or "").strip()
    if env_value:
        _append(Path(env_value))

    try:
        for root in preferred_source_roots(
            __file__,
            env_var="SYNDICATE_NBA_SOURCE_ROOT",
            local_dir_name="nba_source",
        ):
            _append(root)
    except Exception:
        # `preferred_source_roots` raises when strict hosted storage is on and
        # no data root is set. An asset route must still answer 404, not 500.
        pass

    # Unconditional last resort. These assets are git-tracked, so the checkout
    # is the one root that is present wherever this code is.
    _append(Path(__file__).resolve().parents[3] / "data" / "nba_source")
    return roots


def _web_asset_paths(filename: str) -> list[Path]:
    return [(root / "web" / filename).resolve() for root in _artifact_roots()]


def source_web_text(filename: str) -> str | None:
    # Resolve PER REQUESTED FILE across the candidate list rather than picking
    # a root up front -- `source_roots.py` says so in its own comment, and
    # "does this directory exist" is not "does it hold the file you asked for".
    for path in _web_asset_paths(filename):
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            continue
        except Exception:
            return None
    return None


@lru_cache(maxsize=1)
def source_betting_card_asset_version() -> str:
    paths = [
        path
        for name in ("betting-card-v2.css", "betting-card-v2.js")
        for path in _web_asset_paths(name)
    ]
    mtimes: list[int] = []
    for path in paths:
        try:
            mtimes.append(int(path.stat().st_mtime_ns))
        except OSError:
            continue
    if mtimes:
        return str(max(mtimes))
    return "1"


def _normalize_route_value(key: str, value: str, date_str: str) -> str:
    text = str(value or "").strip()
    if not text:
        return text
    parsed = urlparse(text)
    query_date = parse_qs(parsed.query).get("date", [""])[0].strip()
    resolved_date = query_date or date_str
    if key == "cards_url" and text == "/":
        return f"/nba/cards?date={resolved_date}"
    if key == "cards_url" and parsed.path == "/" and query_date:
        return f"/nba/cards?date={query_date}"
    if text.startswith("/api/season/"):
        return f"/nba{text}"
    if parsed.path == "/betting-card" and query_date:
        return f"/nba/cards?date={query_date}"
    if parsed.path == "/live-player-props-audit" and query_date:
        return f"/nba/season/{query_date[:4]}/live-lens?date={query_date}&profile=retuned"
    return text


def _normalize_payload_routes(payload: Any, date_str: str) -> Any:
    if isinstance(payload, dict):
        normalized: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(key, str) and key.endswith(("_url", "_href")) and isinstance(value, str):
                normalized[key] = _normalize_route_value(key, value, date_str)
            else:
                normalized[key] = _normalize_payload_routes(value, date_str)
        return normalized
    if isinstance(payload, list):
        return [_normalize_payload_routes(item, date_str) for item in payload]
    return payload


@lru_cache(maxsize=64)
def build_season_betting_card_manifest_payload(season: int, profile: str, selected_date: str) -> dict[str, Any] | None:
    payload = load_json(
        season_betting_card_manifest_path(int(season), profile=profile, requested_date=selected_date)
    )
    if not isinstance(payload, dict):
        return None
    return _enrich_recommendation_like_payload(_normalize_payload_routes(payload, selected_date))


@lru_cache(maxsize=256)
def build_season_betting_card_day_payload(
    season: int,
    date_str: str,
    profile: str,
    *,
    include_prop_insights: bool = False,
) -> dict[str, Any] | None:
    payload = load_json(
        season_betting_card_day_path(
            int(season),
            date_str,
            profile=profile,
            include_prop_insights=include_prop_insights,
        )
    )
    if not isinstance(payload, dict):
        return None
    return _enrich_recommendation_like_payload(_normalize_payload_routes(payload, date_str))


@lru_cache(maxsize=1)
def source_betting_card_css() -> str | None:
    return source_web_text("betting-card-v2.css")


@lru_cache(maxsize=1)
def source_betting_card_js() -> str | None:
    content = source_web_text("betting-card-v2.js")
    if content is None:
        return None
    content = re.sub(
        r"window\.location\.pathname\.match\(/\\/season\\/\(\\d\+\)\\/betting-card\\/\?\$/\)",
        r"window.location.pathname.match(/\\/nba\\/season\\/(\\d+)\\/betting-card\\/?$/)",
        content,
    )
    content = content.replace("/api/season/", "/nba/api/season/")
    content = content.replace("/betting-card?date=", "/nba/cards?date=")
    content = re.sub(
        r"root\.liveAuditLink\.href\s*=\s*`/live-player-props-audit\?date=\$\{encodeURIComponent\(state\.selectedDate\)\}`;",
        "root.liveAuditLink.href = `/nba/season/${encodeURIComponent(state.season)}/live-lens?date=${encodeURIComponent(state.selectedDate)}&profile=${encodeURIComponent(state.profile)}`;",
        content,
    )
    content = content.replace(
        "    nextUrl.searchParams.set('date', state.selectedDate);\n    nextUrl.searchParams.set('profile', state.profile);",
        "    nextUrl.searchParams.set('profile', state.profile);\n    nextUrl.searchParams.set('date', state.selectedDate);",
    )
    return content