from __future__ import annotations

from typing import Any


def format_pct(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number * 100:.1f}%"


def format_num(value: Any) -> str:
    try:
        number = float(value)
    except Exception:
        return "-"
    return f"{number:.1f}".rstrip("0").rstrip(".")


def format_signed_price(value: Any) -> str:
    try:
        number = int(round(float(value)))
    except Exception:
        return "-"
    return f"+{number}" if number > 0 else str(number)