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
import unicodedata
from difflib import SequenceMatcher

_NOISE_TOKENS = {
    "fc", "cf", "afc", "sc", "ac", "as", "ss", "ssc", "cd", "rc", "rcd",
    "club", "de", "the",
    # Added 2026-08-20. Same class as the entries above -- a club-type
    # prefix one source carries and another does not -- found by comparing
    # each league's players_*.csv club names against its own schedule:
    #   "TSG Hoffenheim" vs "Hoffenheim", "AJ Auxerre" vs "Auxerre".
    #   "Hamburger SV" vs "Hamburg SV" -- "sv" (Sportverein) is the same
    #   class of club-type token as "fc"/"sc" already in this set.
    "tsg", "aj", "sv",
}

_ALIASES: dict[str, str] = {
    # Added 2026-08-20, from a measured comparison of every league's
    # players_*.csv club names against that league's own schedule. These are
    # the variants that survive accent-folding and noise-stripping and still
    # differ -- genuine short/long forms, not spelling noise. Left as
    # explicit entries rather than loosening the fuzzy threshold, because the
    # same-club and different-club score ranges OVERLAP: same-club pairs run
    # 0.833-0.933 and different-club pairs 0.722-0.812 (Manchester City vs
    # Manchester United is 0.812), so no threshold separates them and one
    # tuned to today's six collisions would be a coincidence.
    "internazionale": "inter",
    "inter milan": "inter",
    "hamburger sv": "hamburg",
    "hamburger": "hamburg",
    "borussia m.gladbach": "borussia monchengladbach",
    "borussia mgladbach": "borussia monchengladbach",
    "m.gladbach": "borussia monchengladbach",
    "mainz 05": "mainz",
    "1. union berlin": "union berlin",
    "1 union berlin": "union berlin",
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
    # ESPN's own full club name for this team ("Red Bull New York") shares
    # every token with the Odds API's "New York Red Bulls" but in a
    # different order with a singular/plural mismatch ("bull" vs "bulls"),
    # which scores too low on SequenceMatcher's character-sequence ratio to
    # clear match_team_name's fuzzy threshold -- confirmed 2026-07-24 while
    # wiring the market board's odds<->sim join (match_team_name returned
    # None for this exact pair without this alias).
    "red bull new york": "new york red bulls",
    "dc united": "d.c. united",
    "sporting kansas city": "sporting kc",
    "vancouver whitecaps": "vancouver whitecaps fc",
    "san jose earthquakes": "san jose",
    "columbus crew sc": "columbus crew",
}


def _fold_accents(text: str) -> str:
    """`alaves`, not `alav s`.

    THE DEFECT THIS FIXES. `canonical_team_name`'s ASCII scrub
    (`[^a-z0-9' .]+` -> " ") treats every non-ASCII character as noise and
    replaces it with a SPACE, which does not strip an accent -- it splits the
    word in half:

        Alaves           -> "alaves"
        Alaves (accented)-> "alav s"
        Atletico Madrid  -> "atletico madrid"
        Atletico (acc.)  -> "atl tico madrid"
        Monchengladbach  -> "m nchengladbach"

    So an accented club name NEVER canonicalized to its unaccented twin, in
    any of the five leagues that have them (la_liga, serie_a, ligue_1,
    bundesliga, primeira_liga). `match_team_name`'s fuzzy fallback has been
    compensating for that all along, and **that is why its threshold had to
    be as low as 0.72** -- low enough to survive a word split, and therefore
    also low enough to match Real Oviedo to Real Sociedad at 0.750 and
    absorb an entire squad. Fixing the canonicalizer is what makes exact
    binding possible downstream.

    NFKD then drop combining marks, BEFORE the scrub, so the base letter
    survives. Measured across all ten leagues' club lists: **0 distinct
    clubs collapse into each other** as a result.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def canonical_team_name(name: str) -> str:
    text = str(name or "").strip().lower()
    text = text.replace("&", "and")
    text = _fold_accents(text)
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
