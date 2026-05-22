from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar


T = TypeVar("T")


def resolve_selected_value(selected: T, values: Sequence[T], fallback: T) -> T:
    if values and selected in values:
        return selected
    if values:
        return values[-1]
    return fallback


def neighboring_values(values: Sequence[T], selected: T, *, fallback: T) -> tuple[T, T]:
    resolved = resolve_selected_value(selected, values, fallback)
    if not values:
        return resolved, resolved
    index = values.index(resolved)
    prev_value = values[max(index - 1, 0)]
    next_value = values[min(index + 1, len(values) - 1)]
    return prev_value, next_value