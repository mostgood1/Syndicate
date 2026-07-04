from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from syndicate.features.shared.source_roots import repo_root_from
from syndicate.features.shared.source_roots import preferred_source_roots
from syndicate.features.shared.refresh_state_store import read_json_file
from syndicate.features.shared.refresh_state_store import reports_root


ARTIFACT_CATEGORIES = ("predictions", "edges", "recommendations", "live_data")


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_slug(value: Any, default: str = "unknown") -> str:
    text = str(value or "").strip().lower()
    return text or default


def _normalize_date(value: Any) -> str | None:
    text = str(value or "").strip()
    return text if text else None


def _normalize_category(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    aliases = {
        "prediction": "predictions",
        "pred": "predictions",
        "edge": "edges",
        "recommendation": "recommendations",
        "rec": "recommendations",
        "live": "live_data",
        "live_data": "live_data",
    }
    return aliases.get(text, text)


def _is_data_file(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    return not name.startswith(".") and name not in {".ds_store", "thumbs.db"}


def _infer_date_from_text(text: str) -> str | None:
    for token in text.replace("_", "-").split("-"):
        if len(token) == 10 and token[4] == "-" and token[7] == "-":
            return token
    return None


@dataclass(frozen=True)
class ArtifactReference:
    category: str
    path: str
    label: str | None = None
    sport_slug: str | None = None
    date: str | None = None
    source_kind: str | None = None
    source_name: str | None = None
    exists: bool = False
    size_bytes: int | None = None
    relative_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        category: str,
        sport_slug: str | None = None,
        date: str | None = None,
        label: str | None = None,
        source_kind: str | None = None,
        source_name: str | None = None,
        root: Path | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ArtifactReference:
        resolved = path.expanduser().resolve()
        try:
            size_bytes = resolved.stat().st_size if resolved.exists() else None
        except OSError:
            size_bytes = None
        relative_path = None
        if root is not None:
            try:
                relative_path = str(resolved.relative_to(root.resolve())).replace("\\", "/")
            except Exception:
                relative_path = str(resolved).replace("\\", "/")
        return cls(
            category=_normalize_category(category),
            path=str(resolved).replace("\\", "/"),
            label=_first_text(label) or path.stem,
            sport_slug=_normalize_slug(sport_slug) if sport_slug else None,
            date=_normalize_date(date),
            source_kind=_first_text(source_kind),
            source_name=_first_text(source_name),
            exists=resolved.exists(),
            size_bytes=size_bytes,
            relative_path=relative_path,
            metadata=_copy_mapping(metadata),
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "category": self.category,
            "path": self.path,
            "exists": self.exists,
        }
        if self.label is not None:
            payload["label"] = self.label
        if self.sport_slug is not None:
            payload["sport_slug"] = self.sport_slug
        if self.date is not None:
            payload["date"] = self.date
        if self.source_kind is not None:
            payload["source_kind"] = self.source_kind
        if self.source_name is not None:
            payload["source_name"] = self.source_name
        if self.size_bytes is not None:
            payload["size_bytes"] = self.size_bytes
        if self.relative_path is not None:
            payload["relative_path"] = self.relative_path
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True)
class ArtifactManifest:
    sport_slug: str
    selected_date: str | None = None
    source_root: str | None = None
    data_root: str | None = None
    predictions: tuple[ArtifactReference, ...] = ()
    edges: tuple[ArtifactReference, ...] = ()
    recommendations: tuple[ArtifactReference, ...] = ()
    live_data: tuple[ArtifactReference, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload["sport_slug"] = self.sport_slug
        if self.selected_date is not None:
            payload["selected_date"] = self.selected_date
        if self.source_root is not None:
            payload["source_root"] = self.source_root
        if self.data_root is not None:
            payload["data_root"] = self.data_root
        payload["predictions"] = [item.to_dict() for item in self.predictions]
        payload["edges"] = [item.to_dict() for item in self.edges]
        payload["recommendations"] = [item.to_dict() for item in self.recommendations]
        payload["live_data"] = [item.to_dict() for item in self.live_data]
        payload["counts"] = {
            "predictions": len(self.predictions),
            "edges": len(self.edges),
            "recommendations": len(self.recommendations),
            "live_data": len(self.live_data),
        }
        return payload


def _repo_root() -> Path:
    return repo_root_from(__file__)


def _candidate_data_roots() -> list[Path]:
    env_root = str((__import__("os").environ.get("SYNDICATE_DATA_ROOT") or "")).strip()
    roots: list[Path] = []
    if env_root:
        roots.append(Path(env_root).expanduser().resolve())
    roots.append((_repo_root() / "data").resolve())
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)
    return deduped


def _sport_roots(sport_slug: str) -> list[Path]:
    slug = _normalize_slug(sport_slug)
    env_map = {
        "mlb": "SYNDICATE_MLB_SOURCE_ROOT",
        "nba": "SYNDICATE_NBA_ARTIFACT_ROOT",
        "wnba": "SYNDICATE_WNBA_SOURCE_ROOT",
        "nhl": "SYNDICATE_NHL_SOURCE_ROOT",
        "nfl": "SYNDICATE_NFL_SOURCE_ROOT",
        "ncaaf": "SYNDICATE_NCAAF_SOURCE_ROOT",
        "ncaab": "SYNDICATE_NCAAB_SOURCE_ROOT",
    }
    env_var = env_map.get(slug)
    roots: list[Path] = []
    if env_var:
        env_value = str((__import__("os").environ.get(env_var) or "")).strip()
        if env_value:
            roots.append(Path(env_value).expanduser().resolve())
    for data_root in _candidate_data_roots():
        roots.append((data_root / f"{slug}_source").resolve())
    roots.append((_repo_root() / "data" / f"{slug}_source").resolve())
    deduped: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        deduped.append(root)
    return deduped


def _sport_directories(root: Path) -> list[Path]:
    candidates = [root]
    for suffix in ("source_artifacts", "data", "data/processed", "data/daily", "data/live_lens", "api", "processed"):
        candidates.append((root / suffix).resolve())
    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _category_from_path(path: Path) -> str | None:
    name = path.name.lower()
    stem = path.stem.lower()
    parent = path.parent.name.lower()
    grandparent = path.parent.parent.name.lower() if path.parent.parent else ""
    if any(token in name for token in ("prediction", "predictions", "projected", "projection", "sim")):
        return "predictions"
    if any(token in name for token in ("edge", "edges", "calibration", "prob_calibration")):
        return "edges"
    if any(token in name for token in ("recommendation", "recommendations", "cards", "picks", "props", "ladders", "betting")):
        return "recommendations"
    if any(token in name for token in ("live", "odds", "scoreboard", "snapshot", "pbp", "shift", "live_lens", "live_state")):
        return "live_data"
    if parent in {"predictions", "prediction", "edges", "edge", "recommendations", "recommendation", "live", "live_data", "live_lens", "live_state"}:
        return _normalize_category(parent)
    if grandparent in {"predictions", "edges", "recommendations", "live_data", "live_lens"}:
        return _normalize_category(grandparent)
    if stem.startswith("props_edges_"):
        return "edges"
    if stem.startswith("props_recommendations_") or stem.startswith("recommendations_slate_"):
        return "recommendations"
    return None


def _guess_date_from_path(path: Path) -> str | None:
    parts = list(path.parts)
    for part in reversed(parts):
        candidate = _infer_date_from_text(part)
        if candidate:
            return candidate
    stem = path.stem
    candidate = _infer_date_from_text(stem)
    if candidate:
        return candidate
    return None


def _published_manifest_path(sport_slug: str) -> Path:
    return reports_root() / "manifests" / f"{_normalize_slug(sport_slug)}.json"


def _manifest_artifact_paths(payload: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()

    def add_path(value: Any) -> None:
        text = str(value or "").strip()
        if not text or text in seen:
            return
        seen.add(text)
        paths.append(text)

    direct_paths = payload.get("artifact_paths")
    if isinstance(direct_paths, list):
        for item in direct_paths:
            add_path(item)

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else None
    if isinstance(metadata, Mapping):
        odds_control_plane = metadata.get("odds_control_plane") if isinstance(metadata.get("odds_control_plane"), Mapping) else None
        if isinstance(odds_control_plane, Mapping):
            nested_paths = odds_control_plane.get("artifact_paths")
            if isinstance(nested_paths, list):
                for item in nested_paths:
                    add_path(item)

    return paths


def _published_manifest_references(manifest_path: Path, payload: Mapping[str, Any], sport_slug: str) -> list[ArtifactReference]:
    artifact_paths = _manifest_artifact_paths(payload)
    if not artifact_paths:
        return []

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else None
    selected_date = _normalize_date(
        payload.get("selected_date")
        or payload.get("date")
        or (metadata or {}).get("selected_date")
        or (metadata or {}).get("date")
    )
    references: list[ArtifactReference] = []
    for artifact_path_text in artifact_paths:
        artifact_path = Path(artifact_path_text)
        references.append(
            ArtifactReference.from_path(
                artifact_path,
                category=_category_from_path(artifact_path) or "recommendations",
                sport_slug=sport_slug,
                date=selected_date or _guess_date_from_path(artifact_path),
                source_kind="published_manifest",
                source_name=manifest_path.name,
                metadata={"matched_by": "published_manifest"},
            )
        )
    return references


def _published_manifest_for_sport(sport_slug: str, selected_date: str | None = None) -> ArtifactManifest | None:
    manifest_path = _published_manifest_path(sport_slug)
    payload = read_json_file(manifest_path)
    if not isinstance(payload, dict):
        return None

    references = _published_manifest_references(manifest_path, payload, sport_slug)
    if not references:
        return None

    grouped = _group_by_category(references)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else None
    effective_date = _normalize_date(selected_date) or _normalize_date(
        payload.get("selected_date")
        or payload.get("date")
        or (metadata or {}).get("selected_date")
        or (metadata or {}).get("date")
    )
    return ArtifactManifest(
        sport_slug=_normalize_slug(sport_slug),
        selected_date=effective_date,
        source_root=str(manifest_path.parent),
        data_root=str(reports_root()),
        predictions=tuple(grouped["predictions"]),
        edges=tuple(grouped["edges"]),
        recommendations=tuple(grouped["recommendations"]),
        live_data=tuple(grouped["live_data"]),
        raw={
            "roots": [str(manifest_path.parent)],
            "selected_date": effective_date,
            "published_manifest_path": str(manifest_path),
            "published_manifest": dict(payload),
        },
    )


def _references_from_directory(root: Path, sport_slug: str) -> list[ArtifactReference]:
    if not root.exists() or not root.is_dir():
        return []
    references: list[ArtifactReference] = []
    for path in sorted(root.rglob("*")):
        if not _is_data_file(path):
            continue
        category = _category_from_path(path)
        if category is None:
            continue
        references.append(
            ArtifactReference.from_path(
                path,
                category=category,
                sport_slug=sport_slug,
                date=_guess_date_from_path(path),
                source_kind="filesystem",
                source_name=root.name,
                root=root,
                metadata={"matched_by": "path_scan"},
            )
        )
    return references


def _group_by_category(references: Iterable[ArtifactReference]) -> dict[str, list[ArtifactReference]]:
    grouped = {category: [] for category in ARTIFACT_CATEGORIES}
    for reference in references:
        if reference.category in grouped:
            grouped[reference.category].append(reference)
    for category in grouped:
        grouped[category] = sorted(grouped[category], key=lambda item: (item.date or "", item.label or item.path), reverse=True)
    return grouped


def load_artifact_manifest(*, sport_slug: str, selected_date: str | None = None) -> ArtifactManifest:
    slug = _normalize_slug(sport_slug)
    published_manifest = _published_manifest_for_sport(slug, selected_date=selected_date)
    if published_manifest is not None:
        return published_manifest

    roots = _sport_roots(slug)
    scanned: list[ArtifactReference] = []
    for root in roots:
        for candidate_root in _sport_directories(root):
            scanned.extend(_references_from_directory(candidate_root, slug))
    grouped = _group_by_category(scanned)
    source_root = str(roots[0]) if roots else None
    data_root = str(roots[0].parent) if roots else None
    return ArtifactManifest(
        sport_slug=slug,
        selected_date=_normalize_date(selected_date),
        source_root=source_root,
        data_root=data_root,
        predictions=tuple(grouped["predictions"]),
        edges=tuple(grouped["edges"]),
        recommendations=tuple(grouped["recommendations"]),
        live_data=tuple(grouped["live_data"]),
        raw={"roots": [str(root) for root in roots], "selected_date": selected_date},
    )


def load_artifact_manifests(*, selected_date: str | None = None, sport_slugs: Iterable[str] | None = None) -> list[ArtifactManifest]:
    slugs = tuple(sport_slugs) if sport_slugs is not None else ("mlb", "nba", "wnba", "nhl", "nfl", "ncaaf", "ncaab")
    manifests = [load_artifact_manifest(sport_slug=slug, selected_date=selected_date) for slug in slugs]
    return manifests


def manifest_by_sport(*, selected_date: str | None = None, sport_slugs: Iterable[str] | None = None) -> dict[str, ArtifactManifest]:
    manifests = load_artifact_manifests(selected_date=selected_date, sport_slugs=sport_slugs)
    return {manifest.sport_slug: manifest for manifest in manifests}


__all__ = [
    "ARTIFACT_CATEGORIES",
    "ArtifactManifest",
    "ArtifactReference",
    "load_artifact_manifest",
    "load_artifact_manifests",
    "manifest_by_sport",
]