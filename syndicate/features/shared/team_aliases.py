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

import unicodedata
from functools import lru_cache
from typing import Any


def normalize(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def fold_accents(value: Any) -> str:
    """`normalize`, plus stripped diacritics and dots.

    ESPN spells clubs with their real diacritics ("Vitória de Guimaraes",
    "Alavés", "CF Montréal", "Union St.-Gilloise"); OddsAPI routinely does not.
    A join that only casefolds treats those as different clubs.
    """
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return normalize(stripped.replace(".", " "))


# Pure club-type designators: they say what KIND of entity a club is, never
# which one. Feeds disagree on whether to print them ("SC Telstar"/"Telstar",
# "Houston Dynamo FC"/"Houston Dynamo", "KVC Westerlo"/"Westerlo"), so a
# designator-free form is generated as an ADDITIONAL key -- and only kept when
# it still names exactly one club (see `_soccer_alias_to_name`).
_CLUB_TYPE_TOKENS = frozenset(
    {
        "fc", "cf", "sc", "cs", "sk", "ac", "afc", "ksv", "kvc", "kv", "kaa",
        "cd", "ud", "sv", "vfb", "vfl", "bsc", "ssc", "as", "us", "rc", "ogc",
        "rcd", "sd", "ca", "aj", "sl", "fk", "bk", "if", "ff",
    }
)


def strip_club_tokens(value: Any) -> str:
    """`fold_accents` with club-type designators removed. May return ""."""
    return " ".join(word for word in fold_accents(value).split() if word not in _CLUB_TYPE_TOKENS)


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


# Soccer club names OddsAPI prints that no mechanical rule reaches from the
# ESPN spelling -- a different name for the same club, not a different
# formatting of it. MEASURED against production's own 2026-08-08 board (the
# only honest way to build this): 18 of the slate's 22 clubs resolved straight
# out of the team artifacts, and these four did not.
#
# Kept deliberately small. Anything a rule CAN reach (diacritics, "SC "/" FC"
# designators) is reached by rule, so this table does not grow with every
# fixture -- only with genuine vendor disagreements. `attach_game_state`
# reports the club names it could not resolve so the next one is legible
# instead of showing up as a silently unjoined row.
_SOCCER_VENDOR_NAME_ALIASES: dict[str, str] = {
    "sint truiden": "sint-truidense",
    "sporting lisbon": "sporting cp",
    "union saint gilloise": "union st.-gilloise",
    "vitoria sc": "vitória de guimaraes",
    # `#374`. Five clubs the ODDS FEED names differently from the team artifacts,
    # each verified against a real 0-projection fixture on the served board where
    # the sim HAD the match under its own name. Not a sweep of every unresolved
    # club: 23 board clubs miss this map and most join anyway, because the index
    # also matches on the normalised name directly. Only a name the sim spells
    # differently actually costs a fixture.
    #
    # `SK Beveren` is the cleanest proof of the class -- on 2026-08-16 three of
    # four belgian fixtures projected and this one did not, same league, same
    # date, same sim file, differing only in that the club was renamed from
    # Waasland-Beveren in 2022 and the artifacts still carry the old name.
    "sk beveren": "waasland-beveren",
    "fc twente enschede": "fc twente",
    "fc zwolle": "pec zwolle",
    "real racing club de santander": "racing santander",
    # Word-order reversal, so string similarity scores it 0.46 -- below the bar
    # that correctly rejected `Real Salt Lake`/`Austin FC` (0.17). Kept because
    # MLS has exactly one New York Red Bulls and the identity is not in doubt;
    # a similarity threshold is a filter for candidates, not the decision.
    "new york red bulls": "red bull new york",
}


@lru_cache(maxsize=1)
def _soccer_alias_to_name() -> dict[str, str]:
    """Club token -> canonical ESPN club name, across every configured league.

    Built FROM THE TEAM ARTIFACTS, not hand-written. ~10 leagues of ~200 clubs
    with no stable tri-code convention is exactly the table that would be large
    and wrong at the edges if typed out; but the repo already stores each
    club's name, short name and abbreviation per league, so the map is derived.

    AMBIGUOUS KEYS ARE DROPPED, not first-wins. Soccer tri-codes collide ACROSS
    leagues far more than they do inside one -- measured on the real artifacts,
    11 keys name two different clubs, and `stl` is both Standard Liege and
    St. Louis CITY SC. First-wins would have joined a Belgian board row to an
    MLS scoreboard. This is the same trap `_basketball_alias_to_name` documents
    for the merged NBA/WNBA map: a confidently wrong answer is worse than none,
    because the map is authoritative and skips the heuristics.
    """
    try:
        from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
        from syndicate.features.soccer.sources import all_teams
    except Exception:
        return {}

    candidates: dict[str, set[str]] = {}
    for league in LEAGUE_DISPLAY_NAMES:
        try:
            teams = all_teams(league) or []
        except Exception:
            continue
        for team in teams:
            canonical = normalize((team or {}).get("name"))
            if not canonical:
                continue
            for raw in (team.get("name"), team.get("short_name"), team.get("abbreviation")):
                for key in (normalize(raw), fold_accents(raw), strip_club_tokens(raw)):
                    if key:
                        candidates.setdefault(key, set()).add(canonical)

    mapping = {key: next(iter(names)) for key, names in candidates.items() if len(names) == 1}
    for vendor_name, espn_name in _SOCCER_VENDOR_NAME_ALIASES.items():
        canonical = mapping.get(normalize(espn_name)) or mapping.get(fold_accents(espn_name))
        if canonical:
            mapping.setdefault(normalize(vendor_name), canonical)
            mapping.setdefault(fold_accents(vendor_name), canonical)
    return mapping


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
    if slug == "soccer":
        return _soccer_alias_to_name()
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
    # The map carries diacritic-free and designator-free keys, so a caller
    # holding "Vitória SC" or "Houston Dynamo FC" resolves without having to
    # spell the club the way the artifact does. Tried only after the literal
    # forms, so an exact name always wins over a reduced one.
    for reduced in (fold_accents(value), strip_club_tokens(value)):
        if reduced and reduced != token and reduced in mapping:
            return mapping[reduced]
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
