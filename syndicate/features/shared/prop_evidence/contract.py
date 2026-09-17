"""`prop_evidence_v1`: the seven evidence layers every player-prop answer is built from.

WHY THIS EXISTS. An MLB prop asked from the board used to come back with eight
tables and three charts, and every other sport with zero to three. The data was
not the gap -- WNBA publishes a 100-draw distribution per player per stat, NFL a
weekly usage share per player, soccer a P(over) ladder per player -- the READERS
were. Each sport had its own hand-written fetchers in a 4,000-line blueprint, so
a layer built for one sport never reached another, and nothing said which layers
a sport was missing.

This module is the shared shape. A provider (one per sport) returns a
`PropEvidence` whose `layers` holds EVERY `Layer`: filled with tables/charts, or
carrying a named `absent_reason`. An unfed layer is therefore a stated fact on
the answer, not a silent blank -- the same declared-absence rule
`projection_skill.unmeasured_note` applies to model skill, and the rule
`docs/ai_context/model_engine_standard.md` applies to sim inputs.

THE LAYERS, in the order they are rendered:

    player_sim     the model's own view of THIS player and stat: mean, spread,
                   P(over the board line), distribution chart
    recent_form    last-N actual games and the hit rate against the board line
    matchup        this opponent: head-to-head history, opposing unit/defence
    advanced       underlying usage/quality: minutes, shares, per-90 rates
    game_sim       the game the prop lives in: win prob, team scoring, totals
    environment    pace, rest, venue, weather, injuries, market anchor
    track_record   graded record of THIS market for THIS sport, and model skill

NOTHING HERE COMPUTES A PROJECTION. Providers read published artifacts and shape
them; the web service does no modelling (`CLAUDE.md`, worker split).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

SCHEMA = "prop_evidence_v1"


class Layer(str, Enum):
    PLAYER_SIM = "player_sim"
    RECENT_FORM = "recent_form"
    MATCHUP = "matchup"
    ADVANCED = "advanced"
    GAME_SIM = "game_sim"
    ENVIRONMENT = "environment"
    TRACK_RECORD = "track_record"


LAYER_ORDER: tuple[Layer, ...] = (
    Layer.PLAYER_SIM,
    Layer.RECENT_FORM,
    Layer.MATCHUP,
    Layer.ADVANCED,
    Layer.GAME_SIM,
    Layer.ENVIRONMENT,
    Layer.TRACK_RECORD,
)

LAYER_LABELS: dict[Layer, str] = {
    Layer.PLAYER_SIM: "Player sim",
    Layer.RECENT_FORM: "Recent form",
    Layer.MATCHUP: "Matchup",
    Layer.ADVANCED: "Usage and advanced",
    Layer.GAME_SIM: "Game sim",
    Layer.ENVIRONMENT: "Environment",
    Layer.TRACK_RECORD: "Track record",
}

# Absent reasons are short machine-readable slugs, optionally followed by
# ":" and detail. The prefix is what the checklist groups on.
ABSENT_NO_PRODUCER = "no_producer"          # nothing in the platform writes this data
ABSENT_NOT_PUBLISHED = "not_published"      # a worker has it; web cannot read it
ABSENT_NO_ARTIFACT = "artifact_missing"     # the reader is wired; today's file is not on disk
ABSENT_NO_MATCH = "player_not_found"        # the file exists; this player/game is not in it
ABSENT_NOT_APPLICABLE = "not_applicable"    # the layer has no meaning for this market
ABSENT_NO_SAMPLE = "insufficient_sample"    # data exists but below the reporting bar
ABSENT_PROVIDER_ERROR = "provider_error"    # the reader raised; logged, never served as data
ABSENT_NOT_SHOWN = "not_shown"              # MLB reference fetchers built no table for this layer

ABSENT_REASON_PREFIXES = frozenset({
    ABSENT_NOT_SHOWN,
    ABSENT_NO_PRODUCER,
    ABSENT_NOT_PUBLISHED,
    ABSENT_NO_ARTIFACT,
    ABSENT_NO_MATCH,
    ABSENT_NOT_APPLICABLE,
    ABSENT_NO_SAMPLE,
    ABSENT_PROVIDER_ERROR,
})


def _norm_side(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    if text in {"over", "o"}:
        return "over"
    if text in {"under", "u"}:
        return "under"
    if text in {"yes", "no"}:
        return text
    return text or None


def _to_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class PropSubject:
    """The one bet the evidence is about -- taken from the board row, never guessed."""

    sport: str
    player_name: str
    market: str
    line: float | None
    side: str | None
    event_id: str
    home_team: str
    away_team: str
    selected_date: str
    commence_time: str = ""
    segment: str = "full"
    projection: dict[str, Any] = field(default_factory=dict)

    @property
    def market_key(self) -> str:
        """Lowercased board market -- the key the model scorecard files cells under."""
        return str(self.market or "").strip().lower()

    @classmethod
    def from_board_row(cls, row: dict[str, Any], *, selected_date: str) -> "PropSubject | None":
        """None unless the row is a PLAYER prop with a sport, player and market."""
        if not isinstance(row, dict):
            return None
        sport = str(row.get("sport") or "").strip().lower()
        player = str(row.get("player_name") or "").strip()
        market = str(row.get("market") or "").strip()
        if not sport or not player or not market:
            return None
        commence = str(row.get("commence_time") or "").strip()
        projection = row.get("projection")
        fallback_date = ""
        if not str(selected_date or "").strip() and commence:
            # The tip's EASTERN date, not its UTC date: an 8 PM ET game is
            # T00:00Z the next day and would read tomorrow's slate files.
            from syndicate.features.shared.prop_evidence.common import eastern_date

            fallback_date = eastern_date(commence) or commence[:10]
        return cls(
            sport=sport,
            player_name=player,
            market=market,
            line=_to_float(row.get("line")),
            side=_norm_side(row.get("side")),
            event_id=str(row.get("event_id") or "").strip(),
            home_team=str(row.get("home_team") or "").strip(),
            away_team=str(row.get("away_team") or "").strip(),
            selected_date=str(selected_date or "").strip() or fallback_date,
            commence_time=commence,
            segment=str(row.get("segment") or "full").strip().lower() or "full",
            projection=dict(projection) if isinstance(projection, dict) else {},
        )


@dataclass
class LayerEvidence:
    layer: Layer
    tables: list[dict[str, Any]] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, Any] = field(default_factory=dict)
    source: str | None = None
    as_of: str | None = None
    absent_reason: str | None = None

    @property
    def filled(self) -> bool:
        return bool(self.tables or self.charts)

    def status(self) -> str:
        if self.filled:
            return "filled"
        return self.absent_reason or f"{ABSENT_NO_PRODUCER}:undeclared"


def absent(layer: Layer, reason: str, *, source: str | None = None) -> LayerEvidence:
    prefix = str(reason or "").split(":", 1)[0]
    if prefix not in ABSENT_REASON_PREFIXES:
        raise ValueError(f"absent reason {reason!r} must start with one of {sorted(ABSENT_REASON_PREFIXES)}")
    return LayerEvidence(layer=layer, source=source, absent_reason=reason)


def table(title: str, columns: list[str], rows: list[list[Any]], layer: Layer) -> dict[str, Any]:
    """A table dict in the shape `ask_bar.js` renders, tagged with its layer."""
    return {"title": title, "columns": list(columns), "rows": [list(r) for r in rows], "layer": layer.value}


def chart(title: str, x_label: str, y_label: str, points: list[dict[str, Any]], layer: Layer,
          *, chart_type: str = "bar", marker: dict[str, Any] | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": chart_type,
        "title": title,
        "x_label": x_label,
        "y_label": y_label,
        "points": list(points),
        "layer": layer.value,
    }
    if marker:
        out["marker"] = dict(marker)
    return out


@dataclass
class PropEvidence:
    subject: PropSubject
    provider: str
    layers: dict[Layer, LayerEvidence] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A provider that forgets a layer must not produce a silently shorter
        # answer: the missing layer is recorded as undeclared, which the
        # checklist and the provider tests both treat as a failure.
        for layer in LAYER_ORDER:
            if layer not in self.layers:
                self.layers[layer] = LayerEvidence(layer=layer, absent_reason=f"{ABSENT_NO_PRODUCER}:undeclared")

    def set(self, evidence: LayerEvidence) -> None:
        self.layers[evidence.layer] = evidence

    def coverage(self) -> dict[str, str]:
        return {layer.value: self.layers[layer].status() for layer in LAYER_ORDER}

    def filled_layers(self) -> list[str]:
        return [layer.value for layer in LAYER_ORDER if self.layers[layer].filled]

    def as_of(self) -> str:
        stamps = [str(self.layers[layer].as_of or "") for layer in LAYER_ORDER]
        return max(stamps) if stamps else ""

    def to_section(self) -> dict[str, Any]:
        """The dict shape `collect_focused_evidence` merges, plus the coverage block."""
        tables: list[dict[str, Any]] = []
        charts: list[dict[str, Any]] = []
        facts: dict[str, Any] = {}
        for layer in LAYER_ORDER:
            item = self.layers[layer]
            tables.extend(item.tables)
            charts.extend(item.charts)
            if item.facts:
                facts[layer.value] = item.facts
        return {
            "evidence": {
                "source": f"prop_evidence:{self.provider}",
                "schema": SCHEMA,
                "player": self.subject.player_name,
                "market": self.subject.market,
                "line": self.subject.line,
                "side": self.subject.side,
                "layers": facts,
            },
            "tables": tables,
            "charts": charts,
            "as_of": self.as_of() or self.subject.selected_date,
            "sport": self.subject.sport,
            "prop_evidence": {
                "schema": SCHEMA,
                "provider": self.provider,
                "coverage": self.coverage(),
            },
        }
