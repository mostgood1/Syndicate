from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field


class Pick(BaseModel):
    sport: str
    market: str
    selection: str
    edge: float | None = None
    expected_value: float | None = None
    confidence: float | None = None

    model_config = ConfigDict(extra="allow")


class Portfolio(BaseModel):
    total_exposure: float | None = None
    risk_level: str

    model_config = ConfigDict(extra="allow")


class Parlay(BaseModel):
    legs: list[dict[str, Any]] = Field(default_factory=list)
    combined_probability: float | None = None
    combined_edge: float | None = None
    combined_expected_value: float | None = None
    combined_odds: Any | None = None
    combined_decimal_odds: float | None = None
    leg_count: int | None = None

    model_config = ConfigDict(extra="allow")


class IntelligenceResponse(BaseModel):
    picks: list[Pick]
    portfolio: Portfolio
    parlays: list[Parlay]

    model_config = ConfigDict(extra="allow")