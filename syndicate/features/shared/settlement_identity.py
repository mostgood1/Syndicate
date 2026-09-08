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
`game_not_graded`, `game_id_absent`, `unclassified`) because the autorun's
counters are the ONLY production instrument for this join.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

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
# gap this module can close; a graded-side gap ("game_not_graded") is the
# grader's; an absent id is the producer's.
REASON_TEAM_UNRESOLVED = "team_unresolved"
REASON_SELECTION_UNMAPPED = "selection_unmapped"
REASON_GAME_NOT_GRADED = "game_not_graded"
REASON_GAME_ID_ABSENT = "game_id_absent"
REASON_UNCLASSIFIED = "unclassified"
NO_KEY_MATCH_REASONS: tuple[str, ...] = (
    REASON_TEAM_UNRESOLVED,
    REASON_SELECTION_UNMAPPED,
    REASON_GAME_NOT_GRADED,
    REASON_GAME_ID_ABSENT,
    REASON_UNCLASSIFIED,
)


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
        self.by_game_id: dict[str, list[int]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            identity = graded_row_identity(row)
            index = len(self.rows)
            self.rows.append(row)
            self.identities.append(identity)
            for game_id in identity.game_ids:
                self.by_game_id.setdefault(game_id, []).append(index)

    def __len__(self) -> int:
        return len(self.rows)

    @property
    def carries_game_ids(self) -> bool:
        return bool(self.by_game_id)


@dataclass(frozen=True)
class MatchOutcome:
    row: Mapping[str, Any] | None
    phase: str | None  # "game_id" | "club" | "loose" | None
    reason: str | None  # one of NO_KEY_MATCH_REASONS when row is None


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

    # Phase 1: the same game, by id. Only rows that share an id are eligible,
    # and if the index carries ids at all, a record that shares NONE stops
    # here -- it names a game the grader did not grade (or a different one),
    # and the club paths below must not be allowed to find a look-alike.
    if record_id.game_ids and index.carries_game_ids:
        candidates: list[int] = []
        for game_id in record_id.game_ids:
            candidates.extend(index.by_game_id.get(game_id, ()))
        for position in sorted(set(candidates)):
            row = index.rows[position]
            row_id = index.identities[position]
            if not _market_ok(row):
                continue
            if not _lines_agree(record_id, row_id) or not _players_agree(record_id, row_id):
                continue
            if _selection_agrees(sport_slug, record_id, row_id):
                return MatchOutcome(row=row, phase="game_id", reason=None)
        return MatchOutcome(row=None, phase=None, reason=_classify_miss(record_id, game_not_graded=True))

    # Phase 2: canonical club + side, bounded to the same fixture.
    for position, row in enumerate(index.rows):
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
        row_id = index.identities[position]
        row_keys = _loose_row_keys(row)
        if record_keys and row_keys and record_keys.isdisjoint(row_keys):
            continue
        if not _market_ok(row):
            continue
        if not _lines_agree(record_id, row_id):
            continue
        return MatchOutcome(row=row, phase="loose", reason=None)

    return MatchOutcome(row=None, phase=None, reason=_classify_miss(record_id, game_not_graded=False))


def _classify_miss(record_id: SettlementIdentity, *, game_not_graded: bool) -> str:
    if record_id.team_unresolved:
        return REASON_TEAM_UNRESOLVED
    if record_id.selection_unmapped:
        return REASON_SELECTION_UNMAPPED
    if game_not_graded:
        return REASON_GAME_NOT_GRADED
    if not record_id.game_ids:
        return REASON_GAME_ID_ABSENT
    return REASON_UNCLASSIFIED


__all__ = [
    "GradedRowIndex",
    "MatchOutcome",
    "NO_KEY_MATCH_REASONS",
    "SettlementIdentity",
    "club_key",
    "find_graded_row",
    "graded_row_identity",
    "record_identity",
    "resolve_selection",
    "same_club",
]
