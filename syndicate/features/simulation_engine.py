from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


def _copy_mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _coerce_float(value: Any) -> float | None:
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


@dataclass(frozen=True)
class SimulationEngine:
    def run_simulation(self, game_context: Mapping[str, Any]) -> dict[str, Any]:
        context = _copy_mapping(game_context)
        base_probability = _coerce_float(context.get("model_probability"))
        if base_probability is None:
            base_probability = _coerce_float(context.get("confidence"))
        if base_probability is None:
            base_probability = 0.5
        base_probability = max(0.01, min(0.99, base_probability))

        edge = _coerce_float(context.get("edge")) or 0.0
        drift = max(-0.12, min(0.12, edge))
        win_probability = max(0.01, min(0.99, base_probability + drift))
        loss_probability = max(0.01, min(0.99, 1.0 - win_probability))
        push_probability = max(0.0, 1.0 - win_probability - loss_probability)

        distributions = {
            "win": round(win_probability, 4),
            "loss": round(loss_probability, 4),
            "push": round(push_probability, 4),
        }
        total = sum(distributions.values()) or 1.0
        normalized = {key: round(value / total, 4) for key, value in distributions.items()}

        return {
            "distribution": normalized,
            "probability_distributions": normalized,
            "inputs": {
                "sport": context.get("sport"),
                "market": context.get("market"),
                "selection": context.get("selection"),
                "line": context.get("current_line") or context.get("line"),
                "odds": context.get("odds"),
            },
        }


__all__ = ["SimulationEngine"]