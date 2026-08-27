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
        resolved = {normalize(alias): normalize(name) for alias, name in mapping.items() if name}
        if league == "wnba":
            resolved.update(
                {normalize(alias): normalize(name) for alias, name in _WNBA_EXTRA_ALIASES.items()}
            )
        return resolved
    except Exception:
        return {}


# WNBA-ONLY, AND DELIBERATELY NOT IN `basketball_props_smart_sim`.
#
# MEASURED 2026-08-25T01:22:04Z, on the first live run of the unresolved-club
# counter:
#
#   wnba polymarket_us reason="spreads_refused:40
#                              clubs_unresolved:2:['Portland', 'Toronto']"
#
# Polymarket names these two clubs by CITY. `_WNBA_TEAM_ALIASES_LOCAL` carries
# both franchises by NICKNAME only -- `fire` -> Portland Fire, `tempo` ->
# Toronto Tempo -- while every other club in that map also carries its city
# (`atlanta`/`dream`, `dallas`/`wings`, `seattle`/`storm`). The two newest
# franchises went in nickname-only and nothing noticed, because nothing asked
# by city until this venue did.
#
# THEY LIVE HERE RATHER THAN IN THAT MAP, and that is the whole point. That
# module also exposes `_TEAM_ALIASES_LOCAL = {**_NBA..., **_WNBA...}`, where
# WNBA WINS, and NBA already holds `por` -> Portland Trail Blazers and `tor` ->
# Toronto Raptors. Adding these there would silently reassign both NBA clubs in
# the merged map that `basketball_props_smart_sim` itself reads -- precisely the
# collision `_basketball_alias_to_name`'s docstring documents, where a merged
# map turned ("wnba", "min") against "Minnesota Lynx" into a WRONG answer,
# arrived at from the other direction. An overlay applied only on the wnba
# branch cannot reach the merged map at all.
_WNBA_EXTRA_ALIASES: dict[str, str] = {
    "portland": "Portland Fire",
    "por": "Portland Fire",
    "toronto": "Toronto Tempo",
    "tor": "Toronto Tempo",
}


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
#
# THE GAP IS SYSTEMATIC, not a list of one-offs, and the 2026-08-27 additions
# below are the rest of it. `_basketball_alias_to_name` merges NBA and WNBA and
# drops any key naming two clubs, so EVERY city fielding both loses its standard
# three-letter code. `min` above is that rule's first casualty (Lynx vs
# Timberwolves); `phx`, `atl`, `chi`, `dal` and `ind` are the others, and they
# were absent for the same reason rather than by any separate accident.
#
# MEASURED IN PRODUCTION 2026-08-27T19:33Z, reported by lane
# `polymarket-catalogue-pagination` and re-derived here before acting:
#
#     board:   'Washington Mystics @ Phoenix Mercury'   want 'h2h|home'
#     offered: ['gsv-ny@None', 'wsh-phx@None']          -> refused no_match
#
# `wsh` resolved and `phx` did not, so a fixture the venue was plainly offering
# went unjoined. Roughly 22 rows (`no_match|wnba|h2h: 7`, `|totals: 15`).
#
# SAFE BECAUSE THE SUPPLEMENT IS WNBA-ONLY. `_alias_map` applies it for
# `slug == "wnba"` and the vendored map still wins where it answers, so NBA's
# `phx -> Phoenix Suns` is untouched. Each key added here names exactly ONE
# WNBA club -- verified against the live club list, where every one of these
# cities fields a single WNBA team -- so nothing ambiguous is being resolved by
# fiat. This is the opposite of the soccer `stl` case, where two leagues really
# do both claim the token and the correct answer is to refuse.
_WNBA_ALIAS_SUPPLEMENT: dict[str, str] = {
    # Added 2026-08-27 -- the NBA-colliding city codes, see the note above.
    "phx": "phoenix mercury",
    "atl": "atlanta dream",
    "chi": "chicago sky",
    "dal": "dallas wings",
    "ind": "indiana fever",
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
    # `#503`. SIX MORE, and unlike `#374`'s five these were not found by hand --
    # `PREGAME_PROJECTION_JOIN` prints the board-side and sim-side spelling of
    # the same unmatched fixture on one line, so each pair below is quoted from
    # a single production reading (refresh-worker 2026-08-22 17:36:42Z and
    # 17:39:37Z) rather than reconstructed.
    #
    # Every one was checked BOTH ways before being written: `canonical_team`
    # returns None for the board spelling and a real club for the sim spelling,
    # which is precisely the shape this map repairs. Pairs where the board and
    # sim spellings ALREADY matched (TSG Hoffenheim, Borussia Dortmund,
    # Eintracht Frankfurt, Genk/Racing Genk) are deliberately absent -- adding a
    # working pair buys nothing and hides which entries are load-bearing.
    #
    # Note `Genk`: the fixture `Royal Antwerp v Genk` missed even though Genk
    # matches fine, because `match_for` requires BOTH sides. One bad name costs
    # the whole fixture, which is why a single alias can recover 500+ rows.
    "royal antwerp": "Antwerp",
    "1. fc köln": "FC Cologne",
    "hamburger sv": "Hamburg SV",
    "fsv mainz 05": "Mainz",
    "sc paderborn": "SC Paderborn 07",
    "union berlin": "1. FC Union Berlin",
    # SEVEN MORE, from the first reading taken with the sim-side sample SCOPED
    # to the leagues that actually miss (refresh-worker 2026-08-22 18:04:56Z).
    # The unscoped version could only ever answer about alphabetically-early
    # leagues; with it fixed, all twelve unmatched fixtures became pairable at
    # once and these are the seven that needed help.
    "brighton and hove albion": "Brighton & Hove Albion",
    "athletic bilbao": "Athletic Club",
    "rennes": "Stade Rennais",
    "los angeles fc": "LAFC",
    "atalanta bc": "Atalanta",
    "inter milan": "Internazionale",
    # THIS ONE RUNS THE OTHER WAY, and it is why the map is not named
    # "board_name -> sim_name". Here the BOARD spelling resolves
    # (`deportivo la coruña` is the artifact name) and the SIM's short
    # `Deportivo` does not -- so the unresolvable side is the sim's. The map's
    # actual contract is "spelling nothing can resolve" -> "spelling the
    # artifacts know", whichever feed happens to hold which.
    #
    # `Deportivo` alone is the kind of generic club word that should be
    # suspected of colliding, so it was checked rather than assumed: across all
    # ten configured leagues exactly ONE canonical name contains "deportivo"
    # (`deportivo la coruña`); Alavés is `alavés`, not `deportivo alavés`. If a
    # second Deportivo ever enters the configured set this entry must go --
    # `_soccer_alias_to_name` drops ambiguous DERIVED keys but cannot police a
    # hand-written one.
    "deportivo": "Deportivo La Coruña",
    # `#576`. FIVE MORE, and unlike every batch above these were not found by
    # hand or by reading a join log -- `#541`'s `CHIP_JOIN_COVERAGE` named them,
    # with the exact spelling, on the line it prints every build:
    #
    #   sport=soccer ... unknown_no_key=7 samples=[
    #     {'matchup': 'Ajax @ SC Telstar',        'away_key': None, ...},
    #     {'matchup': 'ADO Den Haag @ Feyenoord', 'home_key': None, ...},
    #     {'matchup': 'Charleroi @ KV Kortrijk',  'away_key': None, ...},
    #     {'matchup': 'Standard Liege @ Leuven',  'home_key': None, ...},
    #     {'matchup': 'SK Beveren @ Genk',        'home_key': None, ...}]
    #
    # `away_key`/`home_key` is `canonical_team`'s own answer, so a None names
    # the UNRESOLVABLE side directly and the other side proves the fixture
    # itself is fine. No bisecting a board, no guessing which half missed.
    #
    # Every one is the club's SHORT name where the artifacts carry the long one.
    # Checked for ambiguity the way `deportivo` documents rather than assumed:
    # across all ten configured leagues each token below appears in EXACTLY ONE
    # canonical name (204 names in `_soccer_alias_to_name`), so none can collide.
    "ajax": "Ajax Amsterdam",
    "feyenoord": "Feyenoord Rotterdam",
    "charleroi": "Royal Charleroi SC",
    "leuven": "OH Leuven",
    # `Genk` LOOKS REDUNDANT AND IS NOT, and the reason is the whole point of
    # this block. `#503`'s note says "Genk matches fine" and it is RIGHT --
    # about `teams_match`, which falls through to a shared-suffix heuristic when
    # the map cannot answer, and which `test_the_pairs_that_already_agreed_are_
    # not_in_the_map` pins for exactly this pair.
    #
    # `canonical_team` has NO heuristics; it is map-only. `teams_match` can
    # afford a loose rule because it holds BOTH names and is only ever asked
    # "are these the same club". The chip index holds ONE name and must mint a
    # KEY that is globally unique, so a heuristic there would be minting
    # collisions rather than comparing candidates. That asymmetry is why the
    # answer is an exact map entry and NOT a looser `canonical_team`.
    #
    # So this entry is dead weight for the fixture join and load-bearing for the
    # chip join. Measured 2026-08-26: `canonical_team("soccer", "Genk")` was
    # None while `teams_match("soccer", "Genk", "Racing Genk")` was True.
    "genk": "Racing Genk",
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


@lru_cache(maxsize=1)
def _soccer_alias_by_league() -> dict[str, dict[str, str]]:
    """Per-league club maps. Same derivation as `_soccer_alias_to_name`, but the
    ambiguity is resolved WITHIN a league instead of across all of them.

    `_soccer_alias_to_name` drops a key that names two clubs, and that is right:
    `stl` is Standard Liege AND St. Louis CITY SC, and first-wins would have
    joined a Belgian board row to an MLS scoreboard. But the collisions it drops
    are almost entirely CROSS-league. Inside one competition the same token is
    usually unique -- `fcb` is Bayern in the Bundesliga and Barcelona in La Liga,
    and it is never both in either.

    So this keeps the per-league maps intact and lets the caller supply the
    missing context. A key that is ambiguous inside a single league is still
    dropped here, for the same reason as before.
    """
    try:
        from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES, all_teams
    except Exception:
        return {}

    by_league: dict[str, dict[str, str]] = {}
    for league in LEAGUE_DISPLAY_NAMES:
        try:
            teams = all_teams(league) or []
        except Exception:
            continue
        candidates: dict[str, set[str]] = {}
        for team in teams:
            canonical = normalize((team or {}).get("name"))
            if not canonical:
                continue
            for raw in (team.get("name"), team.get("short_name"), team.get("abbreviation")):
                for key in (normalize(raw), fold_accents(raw), strip_club_tokens(raw)):
                    if key:
                        candidates.setdefault(key, set()).add(canonical)
        resolved = {k: next(iter(v)) for k, v in candidates.items() if len(v) == 1}
        if resolved:
            by_league[league] = resolved
    return by_league


def soccer_fixture_clubs(home_code: Any, away_code: Any) -> tuple[str, str] | None:
    """Two club tokens from ONE fixture -> `(home, away)` canonical names, or None.

    THE PAIR IS THE DISAMBIGUATOR, which is why this can answer where
    `canonical_team` cannot. Measured 2026-08-27 on the Polymarket join: after
    the competition fold made the venue's markets reachable, 119 soccer h2h rows
    still refused as `no_match` because `fcb`, `stu`, `koe` and `hof` are dropped
    from the global map as cross-league collisions. Asked as a PAIR they are not
    ambiguous at all -- only the Bundesliga contains both `fcb` and `stu`, and
    Bayern never plays Stuttgart in La Liga.

    STRICTER THAN THE GLOBAL MAP, NOT LOOSER, and that is the safety argument.
    It requires BOTH codes to resolve inside the SAME league and requires
    EXACTLY ONE league to satisfy that. Two leagues that both explain the
    fixture return None rather than a guess, so the `stl` failure this table
    exists to prevent -- a Belgian row joined to an MLS scoreboard -- cannot
    happen through this path: MLS would have to contain Standard Liege's
    opponent too.

    Returns names in the SAME canonical vocabulary as `canonical_team`, so a
    caller can compare the two halves of a join without a second normalisation.
    """
    home_key, away_key = normalize(home_code), normalize(away_code)
    if not home_key or not away_key:
        return None

    hits: list[tuple[str, str]] = []
    for mapping in _soccer_alias_by_league().values():
        home_name = mapping.get(home_key) or mapping.get(fold_accents(home_code))
        away_name = mapping.get(away_key) or mapping.get(fold_accents(away_code))
        if home_name and away_name and home_name != away_name:
            pair = (home_name, away_name)
            if pair not in hits:
                hits.append(pair)
    if len(hits) == 1:
        return hits[0]
    return None


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


@lru_cache(maxsize=16)
def _nickname_alias_map(sport: str) -> dict[str, str]:
    """Bare nicknames -> canonical club, DERIVED from the sport's own map.

    WHY DERIVED AND NOT WRITTEN OUT. A second hand-maintained list is the drift
    this module exists to prevent -- `canonical_team`'s callers already learned
    that two resolvers disagreeing is how the halves of a join end up on
    different vocabularies. This reads the ONE map's values, so a club added
    there gains its nickname automatically and cannot fall out of step.

    THE GAP THIS CLOSES WAS PREDICTED IN PLACE, in
    `venue_quote_adapters._polymarket_sides`: "`canonical_team` resolves a bare
    WNBA nickname ("Sky" -> `chicago sky`) but NOT an MLB or NFL one --
    "Padres" and "Chargers" both return None. Production sends MLB clubs in
    full today, so nothing is lost right now; the day it sends nicknames
    instead, this counter is the difference between a visible alias-map gap and
    a feed that quietly halves."

    That day arrived. Measured on production 2026-08-27, polymarket_us offered
    2,048 NFL quotes and reported
    `clubs_unresolved:64:['49ers','Bears','Bengals','Bills','Broncos','Browns']`.
    Every one of those is a club we know perfectly well.

    AMBIGUOUS NICKNAMES ARE DROPPED, never resolved by preference -- the same
    refusal `player_name_index` and `_candidate_keys` already make. MLB's "Sox"
    names both Chicago and Boston, so it resolves to neither. Counted here:
    nfl 32 nicknames added and 0 dropped; mlb 27 added, 1 dropped; nba 26 added;
    wnba 0 added, because its vendored supplement already carries them.
    """
    mapping = _alias_map(sport)
    clubs = set(mapping.values())
    by_last: dict[str, set[str]] = {}
    for club in clubs:
        parts = club.split()
        if len(parts) < 2:
            # A single-word club IS its own nickname and is already a value;
            # deriving one would add a key identical to it.
            continue
        by_last.setdefault(parts[-1], set()).add(club)
    return {
        nickname: next(iter(owners))
        for nickname, owners in by_last.items()
        if len(owners) == 1 and nickname not in mapping
    }


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
    # LAST, so every literal and reduced form above still wins. A bare
    # nickname is the least specific thing a feed can send, and it is what
    # Polymarket sends for NFL. Ambiguous ones are absent from this map by
    # construction, so an unresolvable nickname still returns None rather than
    # picking a club.
    nicknames = _nickname_alias_map(normalize(sport))
    if token in nicknames:
        return nicknames[token]
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
