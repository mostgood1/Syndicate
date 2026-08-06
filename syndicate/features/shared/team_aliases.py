"""Resolve a team token to a canonical club, across the vocabularies each
surface happens to use (#218).

WHY THIS EXISTS
---------------
Board rows say `TOR @ CHC`. Quote rows say "Toronto Blue Jays" / "Chicago Cubs".
Joining a bet to the price it was struck at needs both to resolve to the same
club, and there is no string rule that does it:

  - a first-word PREFIX handles "tor" -> "toronto blue jays" and
    "bos" -> "boston red sox";
  - INITIALS handle "nyy" -> "new york yankees" and "lad" -> "los angeles
    dodgers", where no single word starts with the code;
  - **neither handles "chc" -> "chicago cubs"** -- not a prefix of "chicago"
    (chi != chc), not the initials (cc).

That last case is not an edge case. Measured on production 2026-08-06, it is why
0 of 108 board candidates carried a quote: `TOR @ CHC` matched one team of two
and the (correctly strict) identity filter rejected it.

So this defers to the real per-sport maps the repo already maintains rather than
inventing a fourth heuristic. Heuristics remain as a LAST resort for sports with
no map, because a partial join beats none -- but they are the fallback, not the
mechanism.

Every map is imported lazily and defensively: this module is on the board's
read path, and a per-sport module failing to import must degrade the join, not
take the board down.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any


def normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


@lru_cache(maxsize=1)
def _mlb_alias_to_name() -> dict[str, str]:
    """MLB tri-code -> full club name, from cards.py's own authoritative map
    (the one carrying MLB's official numeric team ids)."""
    out: dict[str, str] = {}
    try:
        from syndicate.features.mlb.cards import _MLB_TEAM_META_BY_ABBR

        for abbr, meta in (_MLB_TEAM_META_BY_ABBR or {}).items():
            name = normalize((meta or {}).get("name"))
            if name:
                out[normalize(abbr)] = name
    except Exception:
        return {}
    try:
        from syndicate.features.mlb.cards import _MLB_TEAM_ABBR_ALIASES

        # Alternate codes (e.g. the several spellings of the Athletics/White
        # Sox that different feeds use) point at a primary abbr, not a name.
        for alias, primary in (_MLB_TEAM_ABBR_ALIASES or {}).items():
            name = out.get(normalize(primary))
            if name:
                out.setdefault(normalize(alias), name)
    except Exception:
        pass
    return out


@lru_cache(maxsize=2)
def _basketball_alias_to_name(league: str) -> dict[str, str]:
    """NBA or WNBA, kept SEPARATE on purpose.

    The smart-sim module also exposes a merged `_TEAM_ALIASES_LOCAL`, and using
    it here is a trap: the two leagues share tri-codes (MIN, ATL, PHX, LA, ...),
    so the merge lets NBA's "min" -> Minnesota Timberwolves shadow WNBA's
    Minnesota Lynx. Measured while building this: a merged map resolved
    ("wnba", "min") against "Minnesota Lynx" to FALSE -- a wrong answer, and
    worse than no answer, because the map is treated as authoritative and skips
    the heuristic fallback.
    """
    attr = "_WNBA_TEAM_ALIASES_LOCAL" if league == "wnba" else "_NBA_TEAM_ALIASES_LOCAL"
    try:
        import syndicate.features.shared.basketball_props_smart_sim as smart_sim

        mapping = getattr(smart_sim, attr, None) or {}
        return {normalize(alias): normalize(name) for alias, name in mapping.items() if name}
    except Exception:
        return {}


def _alias_map(sport: str) -> dict[str, str]:
    slug = normalize(sport)
    if slug == "mlb":
        return _mlb_alias_to_name()
    if slug in {"nba", "wnba"}:
        return _basketball_alias_to_name(slug)
    return {}


def canonical_team(sport: Any, value: Any) -> str | None:
    """The canonical club name for a token, or None if unresolvable.

    Accepts either direction -- a tri-code or an already-full name -- because
    callers genuinely have both and should not have to know which they hold.
    """
    token = normalize(value)
    if not token:
        return None
    mapping = _alias_map(sport)
    if token in mapping:
        return mapping[token]
    # Already a full name the map knows as a value.
    if token in set(mapping.values()):
        return token
    return None


def teams_match(sport: Any, token: Any, row_team: Any) -> bool:
    """Does a caller's team token name the same club as a row's team field?

    Map first; heuristics only when the map cannot answer, so a sport with no
    map still joins as well as it did before this module existed.
    """
    token_norm = normalize(token)
    row_norm = normalize(row_team)
    if not token_norm or not row_norm:
        return False
    if token_norm == row_norm:
        return True

    canonical_token = canonical_team(sport, token_norm)
    canonical_row = canonical_team(sport, row_norm)
    if canonical_token and canonical_row:
        # Both resolved: the map is authoritative and a mismatch is a real
        # mismatch. Do NOT fall through to heuristics here -- that is how
        # "CHI" would quietly match both Chicago clubs.
        return canonical_token == canonical_row
    if canonical_token and canonical_token == row_norm:
        return True
    if canonical_row and canonical_row == token_norm:
        return True

    words = row_norm.split()
    if not words:
        return False
    # Initials of ANY leading run of words, not just all of them. Codes are
    # routinely built from the city alone and drop the nickname: "kc" is
    # kansas+city, "tb" tampa+bay, "sf" san+francisco, "ny" new+york -- none of
    # which equal the initials of the full name ("kcc", "tbr", "sfg", "nyy").
    # Checked before the prefix rule because it is the more specific test.
    for count in range(2, len(words) + 1):
        if token_norm == "".join(word[0] for word in words[:count]):
            return True
    return len(token_norm) >= 3 and any(word.startswith(token_norm) for word in words)
