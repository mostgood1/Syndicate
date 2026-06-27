from __future__ import annotations

import re
from typing import Any


def _safe_text(value: Any, fallback: str = "-", *fallbacks: Any) -> str:
    text = str(value or "").strip()
    if text:
        return text
    for candidate in (fallback, *fallbacks):
        candidate_text = str(candidate or "").strip()
        if candidate_text:
            return candidate_text
    return ""


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace("%", "")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None
    return None


def _numeric_hint(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    return _safe_float(match.group(1))


def _pct_hint(value: Any) -> float | None:
    number = _numeric_hint(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        number *= 100.0
    return number