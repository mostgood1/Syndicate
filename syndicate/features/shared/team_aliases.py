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


# NFL, static. The 32 franchises are stable, and unlike MLB/NBA there is no
# in-repo source that carries BOTH the tri-code and the full club name: the
# schedule CSVs hold tri-codes only, while OddsAPI rows hold full names only.
# Deriving one from the other is exactly the string heuristic #218 established
# cannot work ("GB" is neither a prefix of "green bay" nor its initials as a
# whole word).
#
# MEASURED 2026-08-08: with no map, `teams_match("nfl", "Carolina Panthers",
# "CAR")` was False, so `attach_game_state` matched 0 rows and every NFL board
# row carried `game.state = None`. That silently disables `opportunity_gate`'s
# dead-market rule -- a SETTLED NFL market could rank -- and it is the hard
# blocker on the S2 cadence tiers, which key on game state.
_NFL_ALIAS_TO_NAME: dict[str, str] = {
    "ari": "arizona cardinals", "atl": "atlanta falcons", "bal": "baltimore ravens",
    "buf": "buffalo bills", "car": "carolina panthers", "chi": "chicago bears",
    "cin": "cincinnati bengals", "cle": "cleveland browns", "dal": "dallas cowboys",
    "den": "denver broncos", "det": "detroit lions", "gb": "green bay packers",
    "hou": "houston texans", "ind": "indianapolis colts", "jax": "jacksonville jaguars",
    "kc": "kansas city chiefs", "lv": "las vegas raiders", "lac": "los angeles chargers",
    "lar": "los angeles rams", "mia": "miami dolphins", "min": "minnesota vikings",
    "ne": "new england patriots", "no": "new orleans saints", "nyg": "new york giants",
    "nyj": "new york jets", "phi": "philadelphia eagles", "pit": "pittsburgh steelers",
    "sf": "san francisco 49ers", "sea": "seattle seahawks", "tb": "tampa bay buccaneers",
    "ten": "tennessee titans", "was": "washington commanders",
    # Alternates real feeds emit. ESPN uses WSH/JAC/LVR; nflverse uses OAK/SD/STL
    # for relocated clubs in historical rows.
    "wsh": "washington commanders", "jac": "jacksonville jaguars",
    "lvr": "las vegas raiders", "oak": "las vegas raiders",
    "sd": "los angeles chargers", "stl": "los angeles rams",
}

# WNBA gaps. The vendored `_WNBA_TEAM_ALIASES_LOCAL` resolves SEA and LVA but
# NOT min/por -- measured 2026-08-08, and today's slate carried a POR chip, so
# this is a live gap rather than a theoretical one. Supplemented rather than
# replaced: the vendored map is the source of truth where it answers, and this
# only fills what it leaves None.
_WNBA_ALIAS_SUPPLEMENT: dict[str, str] = {
    "min": "minnesota lynx", "por": "portland fire", "gs": "golden state valkyries",
    "gsv": "golden state valkyries", "tor": "toronto tempo",
}


def _alias_map(sport: str) -> dict[str, str]:
    slug = normalize(sport)
    if slug == "mlb":
        return _mlb_alias_to_name()
    if slug == "nfl":
        return dict(_NFL_ALIAS_TO_NAME)
    if slug in {"nba", "wnba"}:
        mapping = _basketball_alias_to_name(slug)
        if slug == "wnba":
            # setdefault direction matters: the vendored map wins where it has
            # an answer, so a future vendor fix silently takes precedence over
            # this supplement rather than being shadowed by it.
            merged = dict(_WNBA_ALIAS_SUPPLEMENT)
            merged.update(mapping)
            return merged
        return mapping
    # Soccer deliberately returns {} still. It is ~10 leagues of clubs with no
    # stable tri-code convention across feeds, so a hand-written table would be
    # both large and wrong at the edges. It needs its own pass against the real
    # chip abbreviations, not a guess appended here.
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
