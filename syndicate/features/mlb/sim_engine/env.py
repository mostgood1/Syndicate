from __future__ import annotations
_VENDORED_FILE = str(__import__("pathlib").Path(__file__).resolve().parents[4].joinpath('vendor', 'mlb_bettingv2', 'sim_engine', 'env.py'))  # EDIT: this module's path in vendor/, so every Path(_VENDORED_FILE).parents[k] is the vendored one

import os
from pathlib import Path
from typing import Dict, Optional


def _parse_dotenv_text(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        key = k.strip()
        val = v.strip().strip("\n").strip("\r")
        if not key:
            continue
        # Strip optional quotes
        if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        out[key] = val
    return out


def load_dotenv_if_present(dotenv_path: Optional[Path] = None) -> Dict[str, str]:
    """Load a .env file into process environment (best-effort).

    Existing environment variables are not overwritten.
    Returns the parsed key/value pairs.
    """
    try:
        path = Path(dotenv_path) if dotenv_path else (Path(_VENDORED_FILE).resolve().parents[1] / ".env")
        if not path.exists():
            return {}
        parsed = _parse_dotenv_text(path.read_text(encoding="utf-8"))
        for k, v in parsed.items():
            os.environ.setdefault(k, v)
        return parsed
    except Exception:
        return {}
