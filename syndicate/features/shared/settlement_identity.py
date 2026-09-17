"""One identity for both halves of the evaluation-ledger settlement join (WP8).

Context: Syndicate learning loop, "Restore measurement" plan.
See also: evaluation_settlement.py, graded_outcomes.py.

WHY THIS EXISTS -- measured on production 2026-09-08
-----------------------------------------------------
The settlement autorun ran to completion (state=completed, 7-day lookback)
and settled **0 of 29,630** records: 23,080 `no_key_match`, 6,550
`no_graded_rows`. Every unmatched MLB sample had the same shape, and the
graded side had moneyline rows available for the same date:

    record keys (`_evaluation_record_keys`)   {"823983", "home ml", "laa", "moneyline"}
    graded row keys (`_graded_row_keys`)      {"home", "laa @ sea home ml"}

The record is a board candidate (`blueprints/home.py:_append_game_bet_candidate`):
`game_id` = the StatsAPI gamePk, `pick` = "Home ML", `team` = the tri-code,
`market` = "Moneyline". The graded row is a season-betting-day row reshaped by
`mlb/market_accuracy._normalized_rows`: `selection` = "home" (the SIDE, not
"home ml"), `team` = None on game markets, `title` = "LAA @ SEA Home Ml" (the
tri-code buried inside a sentence), and `game_pk` -- which `_normalized_rows`
DID carry -- dropped on the floor by `graded_outcomes._mlb_graded_rows_for_date`.

So the two key sets were built from different vocabularies of the same fact
and could never intersect:

  * the game id existed on both sides and was emitted by neither grader;
  * the side was "home ml" on one side and "home" on the other;
  * the club was a bare tri-code on one side and a substring of a title on
    the other.

`match_graded_row` was a set intersection over normalised strings, so there
was no place to say "these two tokens name the same club" or "this selection
means the home side". This module gives both sides ONE identity -- game id,
side, club, player, line -- and joins on that, in order of certainty:

  1. **game id** when both sides carry one (MLB gamePk, soccer ESPN event id),
  2. **canonical club + side** through the platform's own resolver
     (`team_aliases.chip_join_key` / `teams_match` -- never a private alias
     table, per learnings), bounded to the same fixture,
  3. the legacy loose token overlap, kept LAST as a fallback only.

A record that names a game the graded side also names by id, but with a
DIFFERENT id, is never allowed to fall through to the club paths: that is the
one way a record could settle against another game, and it is what the
doubleheader / cross-game test pins.

Every miss is classified (`team_unresolved`, `selection_unmapped`,
`game_absent`, `market_not_graded`, `game_id_absent`, `unclassified`) because
the autorun's counters are the ONLY production instrument for this join.

SCORE ROWS (2026-09-17). A grader may emit one `game_score` row per game and
segment instead of pre-graded rows (`graded_outcomes.SCORE_ROW_MARKET`). Such a
row is reachable ONLY through the game-id phase, and only after every ordinary
row for that game has failed, and it settles a record through
`graded_outcomes.grade_score_bet` -- for any line and either side -- or refuses
with a named `detail`.

SEGMENTS. A record's segment (explicit `segment`, a suffixed market key, or a
label such as "First 5 Total") must equal the row's (absent = `full`). Before
this, "First 5 Moneyline" fell through `_markets_compatible`'s keyword family to
`moneyline` and settled against the card's FULL-GAME `ml` row. An unrecognised
segment word matches nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from syndicate.features.shared.graded_outcomes import SCORE_BET_MONEYLINE
from syndicate.features.shared.graded_outcomes import SCORE_BET_SPREAD
from syndicate.features.shared.graded_outcomes import SCORE_BET_TOTAL
from syndicate.features.shared.graded_outcomes import grade_score_bet
from syndicate.features.shared.graded_outcomes import is_score_row
from syndicate.features.shared.team_aliases import _alias_map
from syndicate.features.shared.team_aliases import chip_join_key
from syndicate.features.shared.team_aliases import fold_accents
from syndicate.features.shared.team_aliases import normalize
from syndicate.features.shared.team_aliases import teams_match


# Sides that are not a club. `home`/`away` resolve to a club through the
# fixture; these never do, and a record on one of them can only agree with a
# row on the SAME one.
_NON_CLUB_SIDES = frozenset({"over", "under", "draw", "yes", "no"})
_SIDE_WORDS: dict[str, str] = {
    "home": "home",
    "away": "away",
    "draw": "draw",
    "tie": "draw",
    "over": "over",
    "o": "over",
    "under": "under",
    "u": "under",
    "yes": "yes",
    "no": "no",
}
# Words a selection label carries that describe the MARKET, not the pick:
# "Home ML", "LAA Run Line", "Over Total". Stripped before the remainder is
# read as a side word or a club.
_MARKET_WORDS = frozenset(
    {
        "ml", "moneyline", "money", "line", "spread", "spreads", "ats", "run",
        "runline", "puck", "puckline", "rl", "pl", "total", "totals", "h2h",
        "win", "wins", "to", "team", "the",
    }
)
_NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_TITLE_MATCHUP_RE = re.compile(r"^(?P<away>\S+) @ (?P<home>\S+)")
_PLACEHOLDERS = frozenset({"", "-", "?", "n/a", "none", "null", "nan"})

# Reason tokens, in the order they are reported when several apply. The most
# ACTIONABLE first: an unresolved club or an unmapped selection is a vocabulary
# gap this module can close; a graded-side gap is the grader's; an absent id is
# the producer's.
#
# `game_not_graded` was SPLIT 2026-09-17 into the two graded-side gaps it hid.
# Production 09-17 reported 6,815 `game_not_graded` while every sample named a
# game the index DID hold -- a totals record on a game graded only for props.
#   game_absent        no graded row carries this game id at all
#   market_not_graded  the game is indexed; no row settles this market/line/side
#                      (the finer cause is `MatchOutcome.detail`)
# The old key is gone rather than kept as an alias: summing the reason dict must
# still equal the parent counter, and nothing in code reads the old key.
REASON_TEAM_UNRESOLVED = "team_unresolved"
REASON_SELECTION_UNMAPPED = "selection_unmapped"
REASON_GAME_ABSENT = "game_absent"
REASON_MARKET_NOT_GRADED = "market_not_graded"
REASON_GAME_ID_ABSENT = "game_id_absent"
REASON_UNCLASSIFIED = "unclassified"
NO_KEY_MATCH_REASONS: tuple[str, ...] = (
    REASON_TEAM_UNRESOLVED,
    REASON_SELECTION_UNMAPPED,
    REASON_GAME_ABSENT,
    REASON_MARKET_NOT_GRADED,
    REASON_GAME_ID_ABSENT,
    REASON_UNCLASSIFIED,
)

SEGMENT_FULL = "full"
SEGMENT_UNRECOGNIZED = "unrecognized"

# Segment phrases in a market label or key, most specific first. The sport's
# own vocabulary (`market_segments.SPORT_SEGMENTS`) is the target namespace.
_SEGMENT_PATTERNS: tuple[tuple["re.Pattern[str]", str], ...] = (
    (re.compile(r"\b(?:first|1st)\s*(?:5|five)(?:\s*innings?)?\b|\bf5\b"), "first5"),
    (re.compile(r"\b(?:first|1st)\s*(?:3|three)(?:\s*innings?)?\b|\bf3\b"), "first3"),
    (re.compile(r"\b(?:first|1st)\s*(?:1|one)(?:\s*innings?)?\b|\b(?:first|1st)\s+inning\b|\bf1\b"), "first1"),
    (re.compile(r"\b(?:first|1st)\s+half\b|\b1h\b|\bh1\b"), "h1"),
    (re.compile(r"\b(?:second|2nd)\s+half\b|\b2h\b|\bh2\b"), "h2"),
    (re.compile(r"\b(?:first|1st)\s+quarter\b|\b1q\b|\bq1\b"), "q1"),
    (re.compile(r"\b(?:second|2nd)\s+quarter\b|\b2q\b|\bq2\b"), "q2"),
    (re.compile(r"\b(?:third|3rd)\s+quarter\b|\b3q\b|\bq3\b"), "q3"),
    (re.compile(r"\b(?:fourth|4th)\s+quarter\b|\b4q\b|\bq4\b"), "q4"),
    (re.compile(r"\b(?:first|1st)\s+period\b|\b1p\b|\bp1\b"), "p1"),
    (re.compile(r"\b(?:second|2nd)\s+period\b|\b2p\b|\bp2\b"), "p2"),
    (re.compile(r"\b(?:third|3rd)\s+period\b|\b3p\b|\bp3\b"), "p3"),
)
_FULL_GAME_PATTERN = re.compile(r"\bfull\s*game\b")
# A segment-shaped word none of the patterns above consumed ("2nd inning",
# "half time"). Refused as unrecognised rather than read as the full game.
_UNMAPPED_SEGMENT_WORDS = re.compile(r"\b(?:innings?|half|halves|halftime|quarters?|periods?|segment)\b")
_KNOWN_SEGMENTS = frozenset(name for pattern, name in _SEGMENT_PATTERNS)
_FULL_SEGMENT_WORDS = frozenset({"full", "fg", "game", "full game", "full_game", "match"})


def _text(value: Any) -> str:
    text = str(value if value is not None else "").strip()
    return "" if text.lower() in _PLACEHOLDERS else text


def _coerce_float(value: Any) -> float | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _game_id_token(value: Any) -> str | None:
    """A game id as a comparable string. Ints and numeric strings agree
    ("823983" == 823983); placeholders and zero are absent."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not value:
            return None
        return str(int(value)) if float(value).is_integer() else str(value)
    text = _text(value)
    if not text:
        return None
    if _NUMBER_RE.match(text):
        try:
            return str(int(float(text))) if float(text) else None
        except Exception:
            return None
    return text.lower()


def _game_ids(mapping: Mapping[str, Any], keys: Sequence[str]) -> frozenset[str]:
    out: set[str] = set()
    for key in keys:
        token = _game_id_token(mapping.get(key))
        if token:
            out.add(token)
    return frozenset(out)


def _sport_has_club_map(sport: str | None) -> bool:
    try:
        return bool(_alias_map(sport or ""))
    except Exception:
        return False


def club_key(sport: str | None, value: Any) -> str | None:
    """The canonical club for a token, through the platform's resolver.

    Returns the canonical name when the sport's map (or the NCAAF registry)
    knows the token. For a sport with NO map at all (nhl, ncaab) the normalised
    raw text is returned so two rows in the same vocabulary still compare
    equal; `teams_match`'s heuristics bridge the rest at comparison time.
    Returns None ONLY when the sport has a map and the token is not in it --
    that is the `team_unresolved` signal.
    """
    token = normalize(value)
    if not token:
        return None
    try:
        resolved = chip_join_key(sport, token)
    except Exception:
        resolved = None
    if resolved:
        return resolved
    if not _sport_has_club_map(sport):
        return token
    return None


def same_club(sport: str | None, left: Any, right: Any) -> bool:
    """Do two club tokens name the same club? Map first, heuristics after --
    the same order `teams_match` uses, applied in both directions."""
    a = normalize(left)
    b = normalize(right)
    if not a or not b:
        return False
    if a == b:
        return True
    ca = club_key(sport, a)
    cb = club_key(sport, b)
    if ca and cb:
        return ca == cb
    try:
        return teams_match(sport, a, b) or teams_match(sport, b, a)
    except Exception:
        return False


@dataclass(frozen=True)
class SelectionResolution:
    side: str | None = None
    subject: str | None = None  # a club or player named by the selection text
    line: float | None = None
    unmapped: bool = False


def resolve_selection(sport: str | None, text: Any) -> SelectionResolution:
    """Map free selection text onto the graded row's vocabulary.

        "Home ML"          -> side=home
        "Away ML"          -> side=away
        "Over 8.5"         -> side=over, line=8.5
        "home -1.5"        -> side=home, line=-1.5
        "LAA -1.5"         -> subject=laa, line=-1.5
        "over drew anderson" -> side=over, subject="drew anderson"
        "Los Angeles Angels" -> subject="los angeles angels"
        "Draw" / "Yes"     -> side=draw / yes

    A subject is returned as normalised text; whether it is a club or a player
    is decided by the identity that carries it. `unmapped` is True only when
    text was present and nothing above applied.
    """
    # `normalize` folds "-" into a space, which turns "home -1.5" into
    # "home 1.5" and loses the spread's sign. Tokenise first, and only
    # normalise the WORDS.
    tokens: list[str] = []
    for piece in str(text if text is not None else "").strip().lower().split():
        if _NUMBER_RE.match(piece):
            tokens.append(piece)
        else:
            tokens.extend(normalize(piece).split())
    if not tokens:
        return SelectionResolution()
    line: float | None = None
    if tokens and _NUMBER_RE.match(tokens[-1]):
        line = _coerce_float(tokens[-1])
        tokens = tokens[:-1]
    elif tokens and _NUMBER_RE.match(tokens[0]):
        line = _coerce_float(tokens[0])
        tokens = tokens[1:]
    side: str | None = None
    if tokens and tokens[0] in _SIDE_WORDS:
        side = _SIDE_WORDS[tokens[0]]
        tokens = tokens[1:]
    elif tokens and tokens[-1] in _SIDE_WORDS:
        side = _SIDE_WORDS[tokens[-1]]
        tokens = tokens[:-1]
    core = [token for token in tokens if token not in _MARKET_WORDS]
    subject = " ".join(core) or None
    if side is None and subject is None:
        return SelectionResolution(line=line, unmapped=True)
    return SelectionResolution(side=side, subject=subject, line=line)


@dataclass(frozen=True)
class SettlementIdentity:
    sport: str | None = None
    market: str | None = None
    game_ids: frozenset[str] = field(default_factory=frozenset)
    side: str | None = None
    team: str | None = None  # normalised raw club token
    team_resolved: str | None = None  # canonical club, when the resolver knows it
    team_unresolved: bool = False
    selection_unmapped: bool = False
    home: str | None = None
    away: str | None = None
    player: str | None = None
    line: float | None = None

    def side_club(self) -> str | None:
        if self.side == "home":
            return self.home
        if self.side == "away":
            return self.away
        return None

    def backed_club(self) -> str | None:
        return self.team or self.side_club()

    def clubs(self) -> tuple[str, ...]:
        return tuple(value for value in (self.home, self.away, self.team) if value)

    def summary(self) -> dict[str, Any]:
        return {
            "game_ids": sorted(self.game_ids),
            "side": self.side,
            "team": self.team,
            "team_resolved": self.team_resolved,
            "home": self.home,
            "away": self.away,
            "player": self.player,
            "line": self.line,
        }


def _split_matchup(value: Any) -> tuple[str | None, str | None]:
    """"AWY @ HOM" -> (home, away)."""
    text = _text(value)
    if " @ " not in text:
        return None, None
    away, _, home = text.partition(" @ ")
    return (normalize(home) or None, normalize(away) or None)


def _finish_identity(
    *,
    sport: str | None,
    market: Any,
    game_ids: frozenset[str],
    selection_text: Any,
    team_text: Any,
    home_text: Any,
    away_text: Any,
    player_text: Any,
    explicit_side: Any,
    explicit_line: Any,
    fallback_line: Any = None,
) -> SettlementIdentity:
    home = normalize(_text(home_text)) or None
    away = normalize(_text(away_text)) or None
    player = fold_accents(_text(player_text)) or None
    team = normalize(_text(team_text)) or None
    side = _SIDE_WORDS.get(normalize(_text(explicit_side))) if _text(explicit_side) else None

    resolution = resolve_selection(sport, _text(selection_text))
    if side is None:
        side = resolution.side
    subject = resolution.subject
    if subject:
        if player is None and team is None and side in _NON_CLUB_SIDES:
            # "over drew anderson": the subject of an over/under is a player.
            player = fold_accents(subject)
        elif player and fold_accents(subject) == player:
            pass
        elif team is None:
            # A club named by the selection ("LAA -1.5", "Los Angeles Angels").
            # Only if it looks like one: a resolvable club, or a bare token in a
            # sport with no map. Anything else is a player-shaped subject.
            if club_key(sport, subject) or same_club(sport, subject, home or "") or same_club(sport, subject, away or ""):
                team = subject
            elif player is None:
                player = fold_accents(subject)

    # A side names a club through the fixture, and a club names a side.
    if team is None and side in {"home", "away"}:
        team = home if side == "home" else away
    if side is None and team:
        if home and same_club(sport, team, home):
            side = "home"
        elif away and same_club(sport, team, away):
            side = "away"

    team_resolved = club_key(sport, team) if team else None
    team_unresolved = bool(team) and team_resolved is None

    line = _coerce_float(explicit_line)
    if line is None:
        line = resolution.line
    if line is None:
        line = _coerce_float(fallback_line)

    return SettlementIdentity(
        sport=sport,
        market=_text(market) or None,
        game_ids=game_ids,
        side=side,
        team=team,
        team_resolved=team_resolved,
        team_unresolved=team_unresolved,
        selection_unmapped=resolution.unmapped,
        home=home,
        away=away,
        player=player,
        line=line,
    )


_RECORD_GAME_ID_KEYS = ("game_id", "gamePk", "game_pk", "event_id", "match_id")
_ROW_GAME_ID_KEYS = ("game_id", "game_pk", "gamePk", "event_id", "match_id")


def record_identity(record: Mapping[str, Any], *, sport: str | None = None) -> SettlementIdentity:
    """The identity of a ledger record, read from its recommendation."""
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    sport_slug = normalize(sport or record.get("sport") or recommendation.get("sport_slug") or recommendation.get("sport")) or None
    game_ids = _game_ids(recommendation, _RECORD_GAME_ID_KEYS) | _game_ids(record, ("event_id", "game_id"))
    home = recommendation.get("home") or recommendation.get("home_team")
    away = recommendation.get("away") or recommendation.get("away_team")
    if not _text(home) and not _text(away):
        home, away = _split_matchup(recommendation.get("matchup"))
    return _finish_identity(
        sport=sport_slug,
        market=recommendation.get("market") or recommendation.get("market_family") or recommendation.get("market_label"),
        game_ids=game_ids,
        selection_text=recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name"),
        team_text=recommendation.get("team") or recommendation.get("player_team"),
        home_text=home,
        away_text=away,
        player_text=recommendation.get("player") or recommendation.get("player_name") or recommendation.get("entity"),
        explicit_side=recommendation.get("side"),
        explicit_line=recommendation.get("line"),
        fallback_line=recommendation.get("projected"),
    )


def graded_row_identity(row: Mapping[str, Any]) -> SettlementIdentity:
    """The identity of a graded row (the `GRADED_OUTCOME_FIELDS` shape)."""
    sport_slug = normalize(row.get("sport")) or None
    home = row.get("home")
    away = row.get("away")
    if not _text(home) and not _text(away):
        home, away = _split_matchup(row.get("matchup"))
    if not _text(home) and not _text(away):
        matched = _TITLE_MATCHUP_RE.match(_text(row.get("title")))
        if matched:
            home, away = matched.group("home"), matched.group("away")
    return _finish_identity(
        sport=sport_slug,
        market=row.get("market"),
        game_ids=_game_ids(row, _ROW_GAME_ID_KEYS),
        selection_text=row.get("selection") if _text(row.get("selection")) else row.get("side"),
        team_text=row.get("team"),
        home_text=home,
        away_text=away,
        player_text=row.get("player") or row.get("player_name"),
        explicit_side=None,
        explicit_line=row.get("line"),
    )


def _lines_agree(record: SettlementIdentity, row: SettlementIdentity) -> bool:
    if record.line is None or row.line is None:
        return True
    return abs(record.line - row.line) <= 1e-6


def _players_agree(record: SettlementIdentity, row: SettlementIdentity) -> bool:
    if record.player and row.player:
        return record.player == row.player
    # A prop record against a game row (or the reverse) is never the same bet.
    return not record.player and not row.player


def _selection_agrees(sport: str | None, record: SettlementIdentity, row: SettlementIdentity) -> bool:
    if record.side in _NON_CLUB_SIDES or row.side in _NON_CLUB_SIDES:
        return record.side == row.side
    record_club = record.backed_club()
    row_club = row.backed_club()
    if record_club and row_club:
        return same_club(sport, record_club, row_club)
    if record.side and row.side:
        return record.side == row.side
    return False


def _same_fixture(sport: str | None, record: SettlementIdentity, row: SettlementIdentity) -> bool:
    """Phase-2 fixture agreement, for sides that carry no shared game id."""
    if record.home and record.away and row.home and row.away:
        return same_club(sport, record.home, row.home) and same_club(sport, record.away, row.away)
    record_clubs = record.clubs()
    row_clubs = row.clubs()
    if record_clubs and row_clubs:
        return any(same_club(sport, a, b) for a in record_clubs for b in row_clubs)
    # A player plays one game a day; a shared player is fixture identity.
    return bool(record.player and row.player)


MarketsCompatible = Callable[[Any, Any, Any], bool]


# ---------------------------------------------------------------------------
# Segments
# ---------------------------------------------------------------------------


def _label_text(value: Any) -> str:
    return " ".join(re.sub(r"[_\-/+]+", " ", str(value if value is not None else "").strip().lower()).split())


def _segments_in_label(value: Any) -> tuple[set[str], str]:
    """(segments named, remaining text) for a market label or key."""
    text = _label_text(value)
    found: set[str] = set()
    if not text:
        return found, text
    for pattern, name in _SEGMENT_PATTERNS:
        if pattern.search(text):
            found.add(name)
            text = pattern.sub(" ", text)
    if _FULL_GAME_PATTERN.search(text):
        found.add(SEGMENT_FULL)
        text = _FULL_GAME_PATTERN.sub(" ", text)
    if _UNMAPPED_SEGMENT_WORDS.search(text):
        found.add(SEGMENT_UNRECOGNIZED)
    return found, " ".join(text.split())


def _explicit_segment(value: Any) -> str | None:
    text = _label_text(value)
    if not text:
        return None
    if text in _FULL_SEGMENT_WORDS:
        return SEGMENT_FULL
    if text.replace(" ", "") in _KNOWN_SEGMENTS:
        return text.replace(" ", "")
    found, _rest = _segments_in_label(text)
    return next(iter(found)) if len(found) == 1 else SEGMENT_UNRECOGNIZED


def _resolve_segments(found: set[str]) -> str:
    if not found:
        return SEGMENT_FULL
    if len(found) == 1:
        return next(iter(found))
    return SEGMENT_UNRECOGNIZED


def record_segment(record: Mapping[str, Any]) -> str:
    """The segment a ledger record is on: `full`, a sport segment, or
    `unrecognized` (a segment word nothing maps, or two sources that disagree)."""
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else record
    found: set[str] = set()
    explicit = _explicit_segment(recommendation.get("segment") or recommendation.get("market_segment"))
    if explicit:
        found.add(explicit)
    for key in ("market_key", "market", "market_label", "market_family"):
        segments, _rest = _segments_in_label(recommendation.get(key))
        found |= segments
    # Two different answers ("full" beside "first5") is a record that says two
    # things, and resolves to `unrecognized`.
    return _resolve_segments(found)


def graded_row_segment(row: Mapping[str, Any]) -> str:
    found: set[str] = set()
    explicit = _explicit_segment(row.get("segment"))
    if explicit:
        found.add(explicit)
    segments, _rest = _segments_in_label(row.get("market"))
    found |= segments
    return _resolve_segments(found)


# ---------------------------------------------------------------------------
# Score rows: turn a record into a bet `grade_score_bet` can decide
# ---------------------------------------------------------------------------

_SCORE_KIND_BY_MARKET_KEY: dict[str, tuple[str, bool | None]] = {
    "totals": (SCORE_BET_TOTAL, None),
    "totals_alt": (SCORE_BET_TOTAL, None),
    "spreads": (SCORE_BET_SPREAD, None),
    "spreads_alt": (SCORE_BET_SPREAD, None),
    "h2h": (SCORE_BET_MONEYLINE, None),
    "h2h_3_way": (SCORE_BET_MONEYLINE, True),
}
_MACHINE_MARKET_KEYS = frozenset(_SCORE_KIND_BY_MARKET_KEY)
# Words that say which FEED or WHEN, not which bet: an alternate total is the
# same wager at a non-main line (`market_segments.base_market_for_alternate`),
# and a live total settles on the same final score as a pregame one.
_MARKET_NOISE = re.compile(r"\b(?:alt|alternate|alternative|live|in play|game)\b")
_THREE_WAY = re.compile(r"\b(?:3|three)\s*way\b")
_TWO_WAY = re.compile(r"\b(?:2|two)\s*way\b")


def score_market_kind(sport: str | None, record: Mapping[str, Any]) -> tuple[str | None, bool | None]:
    """(`total`|`spread`|`moneyline`|None, three_way) for a record's market.

    The FIRST non-empty market field decides, so a prop key cannot be rescued
    into a game market by a looser label further down. `three_way` is True for
    an explicit 3-way market, False for the machine key `h2h` (OddsAPI's two-way
    moneyline, whose segment tie refunds), None when only a display label
    ("Moneyline") says it -- `grade_score_bet` refuses a segment tie then.
    """
    from syndicate.features.shared.market_keys import canonical_market_key
    from syndicate.features.shared.market_segments import split_segment_market_key

    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else record
    for key in ("market_key", "market", "market_label", "market_family"):
        raw = str(recommendation.get(key) or "").strip().lower()
        if not raw:
            continue
        machine = False
        base: str | None = None
        split = None
        try:
            split = split_segment_market_key(sport or "", raw)
        except Exception:
            split = None
        if split:
            base, machine = split[1], True
        elif raw in _MACHINE_MARKET_KEYS:
            base, machine = raw, True
        three_way: bool | None = None
        if base is None:
            _segments, rest = _segments_in_label(raw)
            if _THREE_WAY.search(rest):
                three_way = True
                rest = _THREE_WAY.sub(" ", rest)
            elif _TWO_WAY.search(rest):
                three_way = False
                rest = _TWO_WAY.sub(" ", rest)
            rest = " ".join(_MARKET_NOISE.sub(" ", rest).split())
            try:
                base = canonical_market_key(sport, raw) or (canonical_market_key(sport, rest) if rest else None)
            except Exception:
                base = None
        if base not in _SCORE_KIND_BY_MARKET_KEY:
            return None, None
        kind, key_three_way = _SCORE_KIND_BY_MARKET_KEY[base]
        if key_three_way is not None:
            three_way = key_three_way
        elif kind == SCORE_BET_MONEYLINE and machine and base == "h2h":
            three_way = False
        return kind, three_way
    return None, None


def _club_is(sport: str | None, token: str | None, *names: Any) -> bool:
    return bool(token) and any(same_club(sport, token, name) for name in names if _text(name))


def _score_side_and_line(
    sport: str | None,
    record: Mapping[str, Any],
    record_id: SettlementIdentity,
    kind: str,
    row: Mapping[str, Any],
) -> tuple[str | None, float | None, str | None]:
    """(side, line, refusal) for one record against one score row's fixture."""
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    row_home = (row.get("home"), row.get("home_name"))
    row_away = (row.get("away"), row.get("away_name"))

    # The fixture must be the same way round. The record's clubs came from the
    # board's matchup; the scores come from the feed. Pairing a score with a
    # name from a different source is how a game gets graded backwards.
    if record_id.home and record_id.away:
        home_ok = _club_is(sport, record_id.home, *row_home)
        away_ok = _club_is(sport, record_id.away, *row_away)
        if not (home_ok and away_ok):
            swapped = _club_is(sport, record_id.home, *row_away) and _club_is(sport, record_id.away, *row_home)
            return None, None, "fixture_orientation_disagrees" if swapped else "fixture_clubs_disagree"

    # The MARKET line only: the explicit `line`, or the number in the pick
    # text. Never `projected` -- `record_identity` falls back to it, and a
    # model projection is not a line anyone bet. Two present and different is
    # a record that says two things (a lens row stores its projection in
    # `line` beside "Over 4.5" in the pick), so it refuses.
    explicit_line = _coerce_float(recommendation.get("line"))
    text_line = resolve_selection(sport, recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name")).line
    if explicit_line is not None and text_line is not None and abs(explicit_line - text_line) > 1e-9:
        return None, None, "line_disagrees_with_selection"
    line = explicit_line if explicit_line is not None else text_line

    side = record_id.side
    if kind == SCORE_BET_TOTAL:
        return side, line, None

    team = record_id.team
    if side in {"home", "away"}:
        side_names = row_home if side == "home" else row_away
        if team and not _club_is(sport, team, *side_names):
            return None, None, "team_side_disagrees"
        return side, line, None
    if side is None and team:
        if _club_is(sport, team, *row_home):
            return "home", line, None
        if _club_is(sport, team, *row_away):
            return "away", line, None
        return None, None, "team_not_in_fixture"
    return side, line, None


def grade_record_on_score_rows(
    record: Mapping[str, Any],
    record_id: SettlementIdentity,
    rows: Sequence[Mapping[str, Any]],
    *,
    sport: str | None,
    segment: str,
) -> tuple[dict[str, Any] | None, str]:
    """(graded row, detail). The graded row has the ordinary shape
    (`GRADED_OUTCOME_FIELDS`), with `odds`/`pnl` left None so settlement prices
    the record at ITS OWN odds and never stamps its own price as the close."""
    if segment == SEGMENT_UNRECOGNIZED:
        return None, "segment_unrecognized"
    if record_id.player:
        return None, "prop_not_graded"
    kind, three_way = score_market_kind(sport, record)
    if kind is None:
        return None, "not_a_score_market"
    segment_rows = [row for row in rows if str(row.get("segment") or SEGMENT_FULL) == segment]
    if not segment_rows:
        return None, "segment_score_unavailable"
    if len(segment_rows) > 1:
        return None, "score_rows_ambiguous"
    row = segment_rows[0]
    side, line, refusal = _score_side_and_line(sport, record, record_id, kind, row)
    if refusal:
        return None, refusal
    result, actual, refusal = grade_score_bet(
        kind=kind,
        segment=segment,
        side=side,
        line=line,
        three_way=three_way,
        home_score=row.get("home_score"),
        away_score=row.get("away_score"),
    )
    if result is None:
        return None, refusal or "score_bet_refused"
    market_key = {SCORE_BET_TOTAL: "totals", SCORE_BET_SPREAD: "spreads"}.get(kind) or ("h2h_3_way" if three_way else "h2h")
    graded = {
        "sport": row.get("sport") or sport,
        "game_id": row.get("game_id"),
        "game_pk": row.get("game_pk"),
        "market": market_key,
        "segment": segment,
        "selection": side,
        "player": None,
        "team": (row.get("home") if side == "home" else row.get("away") if side == "away" else None),
        "home": row.get("home"),
        "away": row.get("away"),
        "title": row.get("title"),
        "line": line if kind != SCORE_BET_MONEYLINE else None,
        "actual": actual,
        "odds": None,
        "result": result,
        "pnl": None,
        "home_score": row.get("home_score"),
        "away_score": row.get("away_score"),
        "graded_from": "final_score",
    }
    return graded, "graded"


class GradedRowIndex:
    """Graded rows with their identities computed ONCE per settlement pass.

    The autorun matches ~30k records against ~15-350 rows per (sport, date);
    rebuilding every row's identity per record would put the resolver on the
    hot path 30k times over. Built once per sport in `settle_ledger_for_date`
    and handed to `match_graded_row`, which also accepts a plain list for
    callers (and tests) that hold one.
    """

    def __init__(self, rows: Iterable[Mapping[str, Any]]):
        self.rows: list[Mapping[str, Any]] = []
        self.identities: list[SettlementIdentity] = []
        self.segments: list[str] = []
        self.score_row: list[bool] = []
        self.by_game_id: dict[str, list[int]] = {}
        # Rows, not games: `by_game_id` has one key per GAME, and reading its
        # length as a row count is what made `graded_rows_with_game_id` report
        # 15 on a date with 980 rows.
        self.rows_with_game_id = 0
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identity = graded_row_identity(row)
            index = len(self.rows)
            self.rows.append(row)
            self.identities.append(identity)
            self.segments.append(graded_row_segment(row))
            self.score_row.append(is_score_row(row))
            if identity.game_ids:
                self.rows_with_game_id += 1
            for game_id in identity.game_ids:
                self.by_game_id.setdefault(game_id, []).append(index)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def carries_game_ids(self) -> bool:
        return bool(self.by_game_id)

    @property
    def games_indexed(self) -> int:
        return len(self.by_game_id)


@dataclass(frozen=True)
class MatchOutcome:
    row: Mapping[str, Any] | None
    phase: str | None  # "game_id" | "game_score" | "club" | "loose" | None
    reason: str | None  # one of NO_KEY_MATCH_REASONS when row is None
    # The finer cause behind `market_not_graded` (e.g. `prop_not_graded`,
    # `line_disagrees_with_selection`, `no_score_rows_for_game`). None otherwise.
    detail: str | None = None


def _loose_record_keys(record: Mapping[str, Any]) -> set[str]:
    recommendation = record.get("recommendation") if isinstance(record.get("recommendation"), Mapping) else {}
    keys = {
        normalize(recommendation.get("market") or recommendation.get("market_family")),
        normalize(recommendation.get("selection") or recommendation.get("pick") or recommendation.get("name")),
    }
    for key in ("event_id", "game_id", "player", "player_name", "team", "name", "home", "away"):
        keys.add(normalize(recommendation.get(key)))
    return {item for item in keys if item}


def _loose_row_keys(row: Mapping[str, Any]) -> set[str]:
    keys = {normalize(row.get(key)) for key in ("selection", "player", "team", "home", "away", "title")}
    return {item for item in keys if item}


def find_graded_row(
    record: Mapping[str, Any],
    rows: GradedRowIndex | Iterable[Mapping[str, Any]],
    *,
    sport: str | None,
    markets_compatible: MarketsCompatible,
) -> MatchOutcome:
    index = rows if isinstance(rows, GradedRowIndex) else GradedRowIndex(rows)
    record_id = record_identity(record, sport=sport)
    record_market = record_id.market
    sport_slug = record_id.sport or sport

    def _market_ok(row: Mapping[str, Any]) -> bool:
        return markets_compatible(record_market, row.get("market"), sport_slug)

    segment = record_segment(record)

    # Phase 1: the same game, by id. Only rows that share an id are eligible,
    # and if the index carries ids at all, a record that shares NONE stops
    # here -- it names a game the grader did not grade (or a different one),
    # and the club paths below must not be allowed to find a look-alike.
    if record_id.game_ids and index.carries_game_ids:
        candidates: list[int] = []
        for game_id in record_id.game_ids:
            candidates.extend(index.by_game_id.get(game_id, ()))
        if not candidates:
            return MatchOutcome(row=None, phase=None, reason=_classify_miss(record_id, game_reason=REASON_GAME_ABSENT))
        score_rows: list[Mapping[str, Any]] = []
        for position in sorted(set(candidates)):
            row = index.rows[position]
            if index.score_row[position]:
                score_rows.append(row)
                continue
            if index.segments[position] != segment:
                continue
            row_id = index.identities[position]
            if not _market_ok(row):
                continue
            if not _lines_agree(record_id, row_id) or not _players_agree(record_id, row_id):
                continue
            if _selection_agrees(sport_slug, record_id, row_id):
                return MatchOutcome(row=row, phase="game_id", reason=None)
        # Every ordinary row for the game failed; only now may its final score
        # decide. Ordinary rows first keeps every pre-existing settlement (and
        # its card pnl) exactly as it was.
        if score_rows:
            graded, detail = grade_record_on_score_rows(record, record_id, score_rows, sport=sport_slug, segment=segment)
            if graded is not None:
                return MatchOutcome(row=graded, phase="game_score", reason=None)
        else:
            detail = "prop_not_graded" if record_id.player else "no_score_rows_for_game"
        return MatchOutcome(
            row=None,
            phase=None,
            reason=_classify_miss(record_id, game_reason=REASON_MARKET_NOT_GRADED),
            detail=detail,
        )

    # Phase 2: canonical club + side, bounded to the same fixture. Score rows
    # are reachable only by game id (doubleheaders share both clubs).
    for position, row in enumerate(index.rows):
        if index.score_row[position] or index.segments[position] != segment:
            continue
        row_id = index.identities[position]
        if not _market_ok(row):
            continue
        if not _lines_agree(record_id, row_id) or not _players_agree(record_id, row_id):
            continue
        if not _same_fixture(sport_slug, record_id, row_id):
            continue
        if _selection_agrees(sport_slug, record_id, row_id):
            return MatchOutcome(row=row, phase="club", reason=None)

    # Phase 3: the legacy loose overlap, unchanged in spirit -- first row whose
    # normalised tokens overlap, whose market agrees, and whose line agrees.
    record_keys = _loose_record_keys(record)
    for position, row in enumerate(index.rows):
        if index.score_row[position] or index.segments[position] != segment:
            continue
        row_id = index.identities[position]
        row_keys = _loose_row_keys(row)
        if record_keys and row_keys and record_keys.isdisjoint(row_keys):
            continue
        if not _market_ok(row):
            continue
        if not _lines_agree(record_id, row_id):
            continue
        return MatchOutcome(row=row, phase="loose", reason=None)

    return MatchOutcome(row=None, phase=None, reason=_classify_miss(record_id, game_reason=None))


def _classify_miss(record_id: SettlementIdentity, *, game_reason: str | None) -> str:
    if record_id.team_unresolved:
        return REASON_TEAM_UNRESOLVED
    if record_id.selection_unmapped:
        return REASON_SELECTION_UNMAPPED
    if game_reason:
        return game_reason
    if not record_id.game_ids:
        return REASON_GAME_ID_ABSENT
    return REASON_UNCLASSIFIED


__all__ = [
    "GradedRowIndex",
    "MatchOutcome",
    "NO_KEY_MATCH_REASONS",
    "REASON_GAME_ABSENT",
    "REASON_MARKET_NOT_GRADED",
    "SEGMENT_FULL",
    "SEGMENT_UNRECOGNIZED",
    "SettlementIdentity",
    "club_key",
    "find_graded_row",
    "grade_record_on_score_rows",
    "graded_row_identity",
    "graded_row_segment",
    "record_identity",
    "record_segment",
    "resolve_selection",
    "same_club",
    "score_market_kind",
]
