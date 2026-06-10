from __future__ import annotations

import re
from typing import Any


def _safe_text(value: Any, fallback: str = "-") -> str:
    text = str(value or "").strip()
    return text or fallback


def _numeric_hint(value: Any) -> float | None:
    text = str(value or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except Exception:
        return None


def _pct_hint(value: Any) -> float | None:
    number = _numeric_hint(value)
    if number is None:
        return None
    if abs(number) <= 1.0:
        number *= 100.0
    return float(number)