from __future__ import annotations

from collections.abc import MutableMapping
from dataclasses import dataclass, field
from datetime import datetime as _datetime
from typing import Any, Mapping

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _parse_candidate_timestamp_to_central_date(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = _datetime.fromisoformat(normalized)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CENTRAL_TIMEZONE)
    return parsed.astimezone(CENTRAL_TIMEZONE).date().isoformat()


def resolve_candidate_game_date(payload: Mapping[str, Any], *, fallback: str | None = None) -> str | None:
    """The candidate's OWN game date, not "which build produced it".

    UniversalCandidate.from_raw used to fold every candidate's date tag down
    to payload["selected_date"]/["date"] -- the date the outer overview was
    built for, identical for every candidate from that one build. A
    per-game timestamp (when the raw row carries one, e.g. WNBA's
    start_time_utc in cards.py) is what actually varies per candidate, and
    is what a cross-date combined board needs in order to filter by date
    correctly. See #93 follow-up: the combined-board work that motivated
    this needs per-candidate dates that are genuinely per-candidate.
    """
    for key in ("commence_time", "start_time_utc", "game_time_utc", "game_date"):
        resolved = _parse_candidate_timestamp_to_central_date(payload.get(key))
        if resolved:
            return resolved
    text = str(fallback or "").strip()
    return text or None


def _copy_sequence_of_strings(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _first_text(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _parse_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except Exception:
        return None


def _parse_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", ""))
    except Exception:
        return None


def _parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _as_text_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return _copy_sequence_of_strings(value)
    if value is None:
        return ()
    text = str(value).strip()
    return (text,) if text else ()


def _normalize_probability_value(value: Any) -> float | None:
    probability = _parse_float(value)
    if probability is None:
        return None
    if probability > 1.0:
        probability /= 100.0
    if probability < 0.0:
        return None
    if probability > 1.0:
        return None
    return round(probability, 4)


def _normalize_odds_value(value: Any) -> float | None:
    odds = _parse_float(value)
    return odds if odds is not None else None


def _normalize_edge_value(value: Any) -> float | None:
    edge = _parse_float(value)
    if edge is None:
        return None
    if abs(edge) > 1.0 and abs(edge) <= 100.0:
        edge /= 100.0
    return round(edge, 4)


def _first_number(*values: Any) -> float | None:
    for value in values:
        number = _parse_float(value)
        if number is not None:
            return number
    return None


def _first_bool(*values: Any) -> bool | None:
    for value in values:
        boolean = _parse_bool(value)
        if boolean is not None:
            return boolean
    return None


def _normalize_source_strength(value: Any) -> float:
    source_strength = _parse_float(value)
    if source_strength is None:
        return 0.5
    if source_strength > 1.0:
        source_strength /= 100.0
    if source_strength < 0.0:
        return 0.5
    if source_strength > 1.0:
        return 1.0
    return round(source_strength, 4)


def _string_or_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


@dataclass
class UniversalCandidate(MutableMapping[str, Any]):
    schema_version: int = 1
    candidate_id: str | None = None
    sport: str | None = None
    type: str | None = None
    selection: str | None = None
    market: str | None = None
    # #223 -- IDENTITY AND PRICE, promoted out of `raw`/`sport_context`.
    #
    # `market` above is display-first by construction (from_raw prefers
    # payload["market"] over payload["market_key"]), so it holds "Hits" where
    # the odds log holds "batter_hits". Collapsing the canonical key and the
    # human label into one field is what made board rows unjoinable to prices;
    # they are now separate, and `market_key` is never populated from a label.
    market_key: str | None = None
    market_label: str | None = None
    segment: str | None = None
    line: float | None = None
    # Who the wager is on. A prop cannot be identified without it, and the
    # display label ("Rae Burrell UNDER 15.5 PTS") is not a substitute.
    entity_id: Any = None
    entity_name: str | None = None
    # Which game. event_id alone is not enough across sports -- MLB board rows
    # carry a StatsAPI gamePk while quotes carry an OddsAPI hash -- so the team
    # pair is carried too and either can satisfy identity.
    event_id: str | None = None
    game_date: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    # odds_book_quotes.quote_ref: book, price, both clocks, rank, consensus,
    # alternatives. Attached at PRODUCTION so CLV has an opening price and the
    # board has a book to name.
    quote: dict[str, Any] | None = None
    odds: float | None = None
    projection: float | None = None
    model_probability: float | None = None
    implied_probability: float | None = None
    edge: float | None = None
    normalized_edge: float | None = None
    confidence: float | None = None
    score: float | None = None
    scoring_mode: str | None = None
    source_strength: float = 0.5
    is_live: bool = False
    timestamp: str | None = None
    sport_context: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self.raw[key] = value
        if key == "candidate_id":
            self.candidate_id = _string_or_none(value)
        elif key == "sport":
            self.sport = _string_or_none(value)
        elif key == "type":
            self.type = _string_or_none(value)
        elif key == "selection":
            self.selection = _string_or_none(value)
        elif key == "market":
            self.market = _string_or_none(value)
        elif key == "odds":
            self.odds = _normalize_odds_value(value)
        elif key == "projection":
            self.projection = _first_number(value)
        elif key == "model_probability":
            self.model_probability = _normalize_probability_value(value)
        elif key == "implied_probability":
            self.implied_probability = _normalize_probability_value(value)
        elif key == "edge":
            self.edge = _normalize_edge_value(value)
        elif key == "normalized_edge":
            self.normalized_edge = _normalize_edge_value(value)
        elif key == "confidence":
            self.confidence = _normalize_probability_value(value)
        elif key == "score":
            self.score = _parse_float(value)
        elif key == "scoring_mode":
            self.scoring_mode = _string_or_none(value)
        elif key == "source_strength":
            self.source_strength = _normalize_source_strength(value)
        elif key == "is_live":
            parsed = _parse_bool(value)
            self.is_live = bool(parsed) if parsed is not None else bool(value)
        elif key == "timestamp":
            self.timestamp = _string_or_none(value)
        elif key == "sport_context" and isinstance(value, Mapping):
            self.sport_context = dict(value)
        elif key == "provenance" and isinstance(value, Mapping):
            self.provenance = dict(value)
        elif key == "quality" and isinstance(value, Mapping):
            self.quality = dict(value)

    def __delitem__(self, key: str) -> None:
        self.raw.pop(key, None)
        if key == "candidate_id":
            self.candidate_id = None
        elif key == "sport":
            self.sport = None
        elif key == "type":
            self.type = None
        elif key == "selection":
            self.selection = None
        elif key == "market":
            self.market = None
        elif key == "odds":
            self.odds = None
        elif key == "projection":
            self.projection = None
        elif key == "model_probability":
            self.model_probability = None
        elif key == "implied_probability":
            self.implied_probability = None
        elif key == "edge":
            self.edge = None
        elif key == "normalized_edge":
            self.normalized_edge = None
        elif key == "confidence":
            self.confidence = None
        elif key == "score":
            self.score = None
        elif key == "scoring_mode":
            self.scoring_mode = None
        elif key == "source_strength":
            self.source_strength = 0.5
        elif key == "is_live":
            self.is_live = False
        elif key == "timestamp":
            self.timestamp = None
        elif key == "sport_context":
            self.sport_context = {}
        elif key == "provenance":
            self.provenance = {}
        elif key == "quality":
            self.quality = {}

    def __iter__(self):
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())

    def get(self, key: str, default: Any = None) -> Any:
        return self.to_dict().get(key, default)

    @classmethod
    def from_raw(cls, raw: Any) -> UniversalCandidate | None:
        payload = _copy_mapping(raw)
        if not payload:
            return None
        sport_context_payload = _copy_mapping(payload.get("sport_context"))
        provenance_payload = _copy_mapping(payload.get("provenance"))
        quality_payload = _copy_mapping(payload.get("quality"))
        candidate_id = _first_text(payload.get("candidate_id"), payload.get("id"), payload.get("prediction_id"), payload.get("recommendation_id"))
        sport = _first_text(payload.get("sport"), payload.get("sport_slug"))
        candidate_type = _first_text(payload.get("type"), payload.get("candidate_type"), payload.get("market_type"))
        selection = _first_text(payload.get("selection"), payload.get("pick"), payload.get("name"))
        market = _first_text(payload.get("market"), payload.get("market_key"), payload.get("market_label"))
        odds = _normalize_odds_value(payload.get("odds"))
        projection = _first_number(payload.get("projection"), payload.get("projected"), payload.get("live_projection"), payload.get("live_total"), payload.get("mean"))
        model_probability = _normalize_probability_value(payload.get("model_probability") or payload.get("fair_probability") or payload.get("confidence"))
        implied_probability = _normalize_probability_value(payload.get("implied_probability") or payload.get("market_probability") or payload.get("implied_prob"))
        edge = _normalize_edge_value(payload.get("edge") or payload.get("adjusted_edge") or payload.get("normalized_edge"))
        normalized_edge = _normalize_edge_value(payload.get("normalized_edge"))
        if normalized_edge is None and edge is not None:
            normalized_edge = edge
        if model_probability is None and implied_probability is not None and edge is not None:
            model_probability = max(0.0, min(1.0, implied_probability + edge))
        if implied_probability is None and odds is not None:
            if odds > 0:
                implied_probability = 100.0 / (odds + 100.0)
            elif odds < 0:
                implied_probability = abs(odds) / (abs(odds) + 100.0)
        if edge is None and model_probability is not None and implied_probability is not None:
            edge = round(model_probability - implied_probability, 4)
        # Canonical key ONLY -- never payload["market"], which is the display
        # string. If a producer has no canonical key this stays None and
        # validate() says so, rather than silently accepting "Hits".
        market_key = _first_text(payload.get("market_key"), payload.get("prop"), payload.get("prop_market_key"), payload.get("stat"))
        market_label = _first_text(payload.get("market_label"), payload.get("market"))
        segment = _first_text(payload.get("segment"), payload.get("period"))
        line = _first_number(payload.get("line"), payload.get("market_line"), payload.get("prop_line"))
        entity_name = _first_text(payload.get("entity_name"), payload.get("player_name"), payload.get("player"), payload.get("entity"))
        entity_id = payload.get("entity_id") or payload.get("player_id")
        event_id = _first_text(payload.get("event_id"), payload.get("game_pk"), payload.get("gamePk"), payload.get("game_id"))
        game_date = _first_text(payload.get("game_date"), payload.get("gameDate"), payload.get("officialDate"), payload.get("selected_date"))
        home_team = _first_text(payload.get("home_team"), payload.get("home_label"))
        away_team = _first_text(payload.get("away_team"), payload.get("away_label"))
        quote_payload = _copy_mapping(payload.get("quote")) or None
        score = _parse_float(payload.get("score"))
        source_strength = _normalize_source_strength(payload.get("source_strength"))
        is_live = _first_bool(payload.get("is_live"), payload.get("live"), payload.get("in_play")) or False
        timestamp = _first_text(payload.get("timestamp"), payload.get("created_at"), payload.get("updated_at"), payload.get("selected_date"))
        scoring_mode = _first_text(payload.get("scoring_mode"), quality_payload.get("scoring_mode"))
        score_inputs_missing = _as_text_list(payload.get("score_inputs_missing") or quality_payload.get("score_inputs_missing"))

        sport_context = {
            "matchup": _first_text(sport_context_payload.get("matchup"), payload.get("matchup")),
            "team_key": _first_text(sport_context_payload.get("team_key"), payload.get("team_key"), payload.get("team")),
            "subject_key": _first_text(sport_context_payload.get("subject_key"), payload.get("subject_key")),
            "line": _first_number(sport_context_payload.get("line"), payload.get("line")),
            "market_key": _first_text(sport_context_payload.get("market_key"), payload.get("market_key")),
            "market_shape": _first_text(sport_context_payload.get("market_shape"), payload.get("market_shape")),
        }
        sport_context = {key: value for key, value in sport_context.items() if value is not None}

        shared_selected_date = _first_text(provenance_payload.get("selected_date"), payload.get("selected_date"), payload.get("date"))
        provenance = {
            "source": _first_text(provenance_payload.get("source"), payload.get("source"), payload.get("source_path")),
            "source_id": _first_text(provenance_payload.get("source_id"), payload.get("source_id"), payload.get("prediction_id"), payload.get("recommendation_id")),
            "selected_date": resolve_candidate_game_date(payload, fallback=shared_selected_date),
            "created_at": _first_text(provenance_payload.get("created_at"), payload.get("created_at")),
        }
        provenance = {key: value for key, value in provenance.items() if value is not None}

        quality = {
            "score_inputs_missing": list(score_inputs_missing),
            "has_model": model_probability is not None,
            "has_market_price": odds is not None or implied_probability is not None,
        }
        quality = {key: value for key, value in quality.items() if value is not None}

        return cls(
            candidate_id=candidate_id,
            sport=sport,
            type=candidate_type,
            selection=selection,
            market=market,
            market_key=market_key,
            market_label=market_label,
            segment=segment,
            line=line,
            entity_id=entity_id,
            entity_name=entity_name,
            event_id=event_id,
            game_date=game_date,
            home_team=home_team,
            away_team=away_team,
            quote=quote_payload,
            odds=odds,
            projection=projection,
            model_probability=model_probability,
            implied_probability=implied_probability,
            edge=edge,
            normalized_edge=normalized_edge,
            confidence=_normalize_probability_value(payload.get("confidence")),
            score=score,
            scoring_mode=scoring_mode,
            source_strength=source_strength,
            is_live=is_live,
            timestamp=timestamp,
            sport_context=sport_context,
            provenance=provenance,
            quality=quality,
            raw=payload,
        )

    def is_prop(self) -> bool:
        """A wager on a person rather than a team outcome."""
        if self.entity_name:
            return True
        token = " ".join(str(part or "").lower() for part in (self.market_key, self.market_label, self.type))
        return any(word in token for word in ("player", "batter", "pitcher", "prop"))

    def validate(self) -> list[str]:
        """Reasons this cannot be emitted as an opportunity. Empty means valid.

        Returns reasons rather than raising: a producer should reject on them, a
        migration should count them. Silently emitting an unidentifiable row is
        the one option that is never right -- it is what produced
        `player_name: null` cards and 0-of-14 price coverage on the live board.
        """
        reasons: list[str] = []
        if not self.market_key:
            # Deliberately NOT satisfied by `market`/`market_label`: a display
            # string cannot be joined to an odds feed, which is the whole point.
            reasons.append("missing_market_key")
        if not (self.event_id or (self.home_team and self.away_team)):
            reasons.append("missing_event_identity")
        if self.is_prop() and not self.entity_name:
            reasons.append("missing_entity_name")
        if not self.selection:
            reasons.append("missing_selection")
        return reasons

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload["schema_version"] = self.schema_version
        if self.candidate_id is not None:
            payload["candidate_id"] = self.candidate_id
        if self.sport is not None:
            payload["sport"] = self.sport
        if self.type is not None:
            payload["type"] = self.type
        if self.selection is not None:
            payload["selection"] = self.selection
        if self.market is not None:
            payload["market"] = self.market
        # self.odds is the normalized-for-math float (from_raw's own
        # implied-probability derivation needs the sign as a number). The
        # display-facing american-odds text ("+124", "-155") -- already
        # sitting in `payload` from `dict(self.raw)` above -- carries
        # information self.odds can't reconstruct (a bare 124.0 is
        # ambiguous between "+124" and "124"), so only synthesize odds from
        # the numeric field when the raw candidate never had a display value
        # to begin with. Confirmed live 2026-07-28: unconditionally
        # overwriting here silently flattened every candidate's odds text to
        # a raw float the moment it passed through collect_candidates (which
        # wraps every candidate in UniversalCandidate).
        if self.odds is not None and not payload.get("odds"):
            payload["odds"] = self.odds
        if self.projection is not None:
            payload["projection"] = self.projection
        if self.model_probability is not None:
            payload["model_probability"] = self.model_probability
        if self.implied_probability is not None:
            payload["implied_probability"] = self.implied_probability
        if self.edge is not None:
            payload["edge"] = self.edge
        if self.normalized_edge is not None:
            payload["normalized_edge"] = self.normalized_edge
        if self.confidence is not None:
            payload["confidence"] = self.confidence
        if self.score is not None:
            payload["score"] = self.score
        if self.scoring_mode is not None:
            payload["scoring_mode"] = self.scoring_mode
        payload["source_strength"] = self.source_strength
        payload["is_live"] = self.is_live
        if self.timestamp is not None:
            payload["timestamp"] = self.timestamp
        for field_name in ("market_key", "market_label", "segment", "line", "entity_id",
                           "entity_name", "event_id", "game_date", "home_team", "away_team"):
            value = getattr(self, field_name)
            if value is not None:
                payload[field_name] = value
        if self.quote:
            payload["quote"] = dict(self.quote)
        if self.sport_context:
            payload["sport_context"] = dict(self.sport_context)
        if self.provenance:
            payload["provenance"] = dict(self.provenance)
        if self.quality:
            payload["quality"] = dict(self.quality)
        return payload


@dataclass(frozen=True)
class IntelligenceQueryRecord:
    schema_version: int = 1
    question: str | None = None
    selected_date: str | None = None
    query_type: str | None = None
    intent: str | None = None
    sport: str | None = None
    subject: str | None = None
    preview_subject: str | None = None
    player_subject: str | None = None
    requested_sports: tuple[str, ...] = ()
    requested_markets: tuple[str, ...] = ()
    limit: int | None = None
    timing: str | None = None
    mode: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: Any) -> IntelligenceQueryRecord:
        payload = _copy_mapping(raw)
        subject = _first_text(payload.get("subject"), payload.get("preview_subject"), payload.get("player_subject"), payload.get("team"))
        return cls(
            question=_first_text(payload.get("question"), payload.get("query"), payload.get("prompt")),
            selected_date=_first_text(payload.get("selected_date"), payload.get("date")),
            query_type=_first_text(payload.get("query_type"), payload.get("intent")),
            intent=_first_text(payload.get("intent"), payload.get("query_type")),
            sport=_first_text(payload.get("sport"), payload.get("sport_slug")),
            subject=subject,
            preview_subject=_first_text(payload.get("preview_subject")),
            player_subject=_first_text(payload.get("player_subject")),
            requested_sports=_as_text_list(payload.get("requested_sports")),
            requested_markets=_as_text_list(payload.get("requested_markets")),
            limit=_parse_int(payload.get("limit")),
            timing=_first_text(payload.get("timing")),
            mode=_first_text(payload.get("mode")),
            raw=payload,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload["schema_version"] = self.schema_version
        if self.question is not None:
            payload["question"] = self.question
        if self.selected_date is not None:
            payload["selected_date"] = self.selected_date
        if self.query_type is not None:
            payload["query_type"] = self.query_type
        if self.intent is not None:
            payload["intent"] = self.intent
        if self.sport is not None:
            payload["sport"] = self.sport
        if self.subject is not None:
            payload["subject"] = self.subject
        if self.preview_subject is not None:
            payload["preview_subject"] = self.preview_subject
        if self.player_subject is not None:
            payload["player_subject"] = self.player_subject
        if self.requested_sports:
            payload["requested_sports"] = list(self.requested_sports)
        if self.requested_markets:
            payload["requested_markets"] = list(self.requested_markets)
        if self.limit is not None:
            payload["limit"] = self.limit
        if self.timing is not None:
            payload["timing"] = self.timing
        if self.mode is not None:
            payload["mode"] = self.mode
        return payload


@dataclass(frozen=True)
class IntelligenceEvaluationRecord:
    schema_version: int = 1
    query: IntelligenceQueryRecord = field(default_factory=IntelligenceQueryRecord)
    response: dict[str, Any] = field(default_factory=dict)
    outcome: dict[str, Any] = field(default_factory=dict)
    recommendation_count: int = 0
    top_recommendation: dict[str, Any] = field(default_factory=dict)
    analysis_focus: str | None = None
    headline: str | None = None
    summary: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.raw)
        payload["schema_version"] = self.schema_version
        payload["query"] = self.query.to_dict()
        payload["response"] = dict(self.response)
        payload["outcome"] = dict(self.outcome)
        payload["recommendation_count"] = self.recommendation_count
        payload["top_recommendation"] = dict(self.top_recommendation)
        if self.analysis_focus is not None:
            payload["analysis_focus"] = self.analysis_focus
        if self.headline is not None:
            payload["headline"] = self.headline
        if self.summary is not None:
            payload["summary"] = self.summary
        return payload

    @classmethod
    def from_payloads(
        cls,
        *,
        query: Any,
        response: Any,
        outcome: Any = None,
    ) -> IntelligenceEvaluationRecord:
        query_record = IntelligenceQueryRecord.from_raw(query)
        response_payload = _copy_mapping(response)
        recommendations = response_payload.get("recommendations") if isinstance(response_payload.get("recommendations"), list) else []
        recommendation_rows = [item for item in recommendations if isinstance(item, Mapping)]
        top_recommendation = dict(recommendation_rows[0]) if recommendation_rows else {}
        analysis_views = response_payload.get("analysis_views") if isinstance(response_payload.get("analysis_views"), Mapping) else {}
        response_summary = {
            "headline": _first_text(response_payload.get("headline")),
            "summary": _first_text(response_payload.get("summary")),
            "recommendation_count": len(recommendation_rows),
            "analysis_focus": _first_text(analysis_views.get("focus")),
            "top_recommendation": top_recommendation,
        }
        outcome_payload = _copy_mapping(outcome)
        return cls(
            query=query_record,
            response=response_summary,
            outcome=outcome_payload,
            recommendation_count=len(recommendation_rows),
            top_recommendation=top_recommendation,
            analysis_focus=_first_text(analysis_views.get("focus")),
            headline=_first_text(response_payload.get("headline")),
            summary=_first_text(response_payload.get("summary")),
            raw={"query": query_record.to_dict(), "response": response_summary, "outcome": outcome_payload},
        )


def build_intelligence_evaluation_record(*, query: Any, response: Any, outcome: Any = None) -> dict[str, Any]:
    return IntelligenceEvaluationRecord.from_payloads(query=query, response=response, outcome=outcome).to_dict()


__all__ = [
    "IntelligenceEvaluationRecord",
    "IntelligenceQueryRecord",
    "build_intelligence_evaluation_record",
    "UniversalCandidate",
]