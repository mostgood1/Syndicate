"""Team-name canonicalization and matching across soccer data sources.

The three live sources spell teams differently: football-data.co.uk uses
short names ("Man City", "Nott'm Forest"), Understat uses full names
("Manchester City"), and The Odds API uses market names ("Manchester City",
"Wolverhampton Wanderers", "Inter Miami CF"). Canonicalization strips
noise tokens and applies a small alias table; matching falls back to fuzzy
comparison so new spellings degrade softly instead of dropping teams.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_NOISE_TOKENS = {
    "fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "cd", "rc", "rcd",
    "club", "de", "the",
}

_ALIASES: dict[str, str] = {
    # EPL — football-data.co.uk short forms and market variants.
    "man city": "manchester city",
    "man united": "manchester united",
    "man utd": "manchester united",
    "nott'm forest": "nottingham forest",
    "nottm forest": "nottingham forest",
    "spurs": "tottenham",
    "tottenham hotspur": "tottenham",
    "wolves": "wolverhampton",
    "wolverhampton wanderers": "wolverhampton",
    "west brom": "west bromwich albion",
    "sheffield utd": "sheffield united",
    "newcastle utd": "newcastle united",
    "newcastle": "newcastle united",
    "leeds": "leeds united",
    "brighton and hove albion": "brighton",
    "brighton & hove albion": "brighton",
    "west ham united": "west ham",
    "leicester city": "leicester",
    "norwich city": "norwich",
    "coventry city": "coventry",
    "hull city": "hull",
    "ipswich town": "ipswich",
    "luton town": "luton",
    "stoke city": "stoke",
    "swansea city": "swansea",
    "cardiff city": "cardiff",
    "birmingham city": "birmingham",
    "sunderland afc": "sunderland",
    # MLS — Odds API market names vs ASA names.
    "la galaxy": "los angeles galaxy",
    # Identity alias: keeps "fc" so LAFC cannot collapse into a
    # "los angeles" stem that collides with the Galaxy.
    "los angeles fc": "los angeles fc",
    "lafc": "los angeles fc",
    "inter miami": "inter miami cf",
    "atlanta united": "atlanta united fc",
    "austin": "austin fc",
    "charlotte": "charlotte fc",
    "chicago fire": "chicago fire fc",
    "st. louis city": "st louis city",
    "st. louis city sc": "st louis city",
    "minnesota united": "minnesota united fc",
    "new york city": "new york city fc",
    "nycfc": "new york city fc",
    "ny red bulls": "new york red bulls",
    "dc united": "d.c. united",
    "sporting kansas city": "sporting kc",
    "vancouver whitecaps": "vancouver whitecaps fc",
    "san jose earthquakes": "san jose",
    "columbus crew sc": "columbus crew",
}


def canonical_team_name(name: str) -> str:
    text = str(name or "").strip().lower()
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9' .]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text in _ALIASES:
        return _ALIASES[text]
    tokens = [token for token in text.replace(".", " ").split(" ") if token and token not in _NOISE_TOKENS]
    stripped = " ".join(tokens)
    return _ALIASES.get(stripped, stripped)


def match_team_name(name: str, candidates: list[str] | tuple[str, ...], *, threshold: float = 0.72) -> str | None:
    """Find the candidate whose canonical form best matches ``name``.

    Exact canonical matches win outright; otherwise the best fuzzy match at
    or above ``threshold`` is returned, and ``None`` when nothing is close.
    """
    target = canonical_team_name(name)
    if not target:
        return None
    best_candidate: str | None = None
    best_score = 0.0
    for candidate in candidates:
        canonical = canonical_team_name(candidate)
        if canonical == target:
            return candidate
        score = SequenceMatcher(None, target, canonical).ratio()
        # Token containment (e.g. "arsenal" in "arsenal london") is strong.
        if target and (target in canonical or canonical in target):
            score = max(score, 0.9)
        if score > best_score:
            best_score = score
            best_candidate = candidate
    if best_score >= threshold:
        return best_candidate
    return None


__all__ = ["canonical_team_name", "match_team_name"]
