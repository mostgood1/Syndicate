"""Settle the soccer rows `bucket_search.grade_population` cannot: props, corners, halves.

`grade_population` grades soccer full-game h2h (3-way), totals and btts off a final score
and skips everything else. Measured 2026-09-15/16 the skipped share was most of the priced
population: 16,607 player props, 1,511 corners rows and 80 first-half rows. This is the
`extra_settler(shaped, view)` hook for those rows. It returns None for a row it does not
handle, so the full-game lines keep their existing grader, and `(result, reason)` for one it
does: `result` is 'win' | 'loss' | 'push', or None with a named reason.

SOURCE. `soccer_source/<league>/api/live_state/live_state_<date>.json`, written by
`scripts/poll_soccer_live_state.py`. Its `match_box` (`ingestion/espn_match_box.py`) carries,
per `in`/`post` match: the full matchday roster with an `appeared` flag and recorded goals,
assists, shots and shots on target; every scoring play with scorer, minute and `own_goal`;
per-half goals; team stats including corners. `bet_status_soccer` refuses props because
`live_player_props` is capped at 12 players; `match_box` is not capped -- measured on the
2026-09-15/16 La Liga and Eredivisie files, 22-23 players per side, 15-16 of them `appeared`.
The file's date is the date ESPN's scoreboard was asked for (US Eastern), which the poller
passes as its Central date; both, plus the UTC day, are probed.

JOINED ON THE TEAM PAIR, like `bet_status_soccer`: the recorder's `event_id` is an OddsAPI
hash and the box is keyed by ESPN's id. Both teams must match, and more than one candidate
refuses (`match_ambiguous`). `team_aliases.canonical_team` is authoritative where it resolves
both names; otherwise `teams_match`, then accent/designator-free equality, the vendor alias
table, and a whole-token subset (`Deportivo` / `Deportivo La Coruña`).

PLAYERS are matched inside ONE match's roster with the rule `soccer_projections._lookup_player`
states: exact `prop_projections._norm_name`, else a UNIQUE token subset. The feed spells
`arnau comas feixas` where ESPN has `Arnau Comas`. A name that matches nobody is
`player_not_in_box`, never a void: it cannot be told apart from a spelling miss.

WHAT IS REFUSED, BY NAME:
- player and match cards -- the box carries team yellow/red counts only;
- anything whose match is not final (a half: not yet at the interval), never read off a clock;
- a goal-scorer row when the box's goals disagree with the score or the player tallies;
- a first/last-scorer row when the deciding goals cannot be put in order;
- an Asian quarter line whose two half-stakes settle differently (half win / half push).

DECISIONS A READER SHOULD KNOW:
- own goals score for nobody: excluded from anytime, first and last scorer;
- a player who did not appear is `dnp_void` in every player market, the first/last scorer
  markets included;
- first/last scorer with no qualifying goal is a loss for every player who appeared, and a
  win for a `no scorer` selection;
- a substitute who came on after the first goal loses first scorer here; books that void
  that case would disagree.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

GRADER_VERSION = "soccer/1"

LIVE_STATE_PATH_TEMPLATE = "soccer_source/{league}/api/live_state/live_state_{date}.json"

REASON_NOT_HANDLED = "not_handled"
REASON_CARDS = "cards_not_gradeable"
REASON_PROP_SEGMENT = "player_prop_segment_not_gradeable"
REASON_CORNERS_SEGMENT = "corners_segment_not_gradeable"
REASON_NO_COMMENCE = "no_commence_time"
REASON_NOT_STARTED = "not_started"
REASON_NO_TEAMS = "no_team_names"
REASON_NO_LIVE_STATE = "no_live_state_for_date"
REASON_MATCH_NOT_FOUND = "match_not_in_live_state"
REASON_MATCH_AMBIGUOUS = "match_ambiguous"
REASON_NOT_FINAL = "match_not_final"
REASON_SEGMENT_NOT_STARTED = "segment_not_started"
REASON_SEGMENT_NOT_FINAL = "segment_not_final"
REASON_LINESCORES_INCONSISTENT = "linescores_inconsistent"
REASON_NO_PLAYER_BOX = "no_player_box"
REASON_PLAYER_NOT_IN_BOX = "player_not_in_box"
REASON_PLAYER_AMBIGUOUS = "player_ambiguous"
REASON_DNP = "dnp_void"
REASON_STAT_MISSING = "player_stat_missing"
REASON_GOALS_INCONSISTENT = "goal_list_inconsistent"
REASON_GOAL_ORDER = "goal_order_unavailable"
REASON_NO_CORNERS = "corners_unavailable"
REASON_TEAM_CORNERS_SIDE = "team_corners_side_unparsed"
REASON_QUARTER_SPLIT = "asian_quarter_line_split"
REASON_UNSETTLEABLE = "unsettleable_side_or_line"

_GOALSCORER_MARKETS = {
    "player_goal_scorer_anytime": "anytime",
    "player_first_goal_scorer": "first",
    "player_last_goal_scorer": "last",
}
_PLAYER_STAT_MARKETS = {
    "player_shots": "shots",
    "player_shots_on_target": "shots_on_target",
    "player_assists": "assists",
}
# Game-line markets on a HALF. The full-game versions stay with `grade_population`.
_SEGMENT_LINE_MARKETS = frozenset(
    {"h2h", "h2h_3_way", "totals", "totals_alt", "alternate_totals", "spreads", "alternate_spreads", "btts"}
)
_FULL_SEGMENTS = frozenset({"", "full", "full_game", "game"})
_NO_SCORER_NAMES = frozenset({"no scorer", "no goalscorer", "no goal scorer", "no goal"})

_EASTERN = ZoneInfo("America/New_York")
_CENTRAL = ZoneInfo("America/Chicago")
_CLOCK_RE = re.compile(r"^\s*(\d+)\s*'?\s*(?:\+\s*(\d+)\s*'?)?\s*$")


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _segment(shaped: Mapping[str, Any], view: Mapping[str, Any] | None) -> str:
    segment = _norm(shaped.get("segment")) or _norm((view or {}).get("segment"))
    return "full" if segment in _FULL_SEGMENTS else segment


def _market(shaped: Mapping[str, Any], view: Mapping[str, Any] | None) -> str:
    return _norm(shaped.get("market")) or _norm((view or {}).get("market"))


def _is_card_market(market: str) -> bool:
    return "card" in market


def _is_corner_market(market: str) -> bool:
    return "corner" in market


def _as_int(value: Any) -> int | None:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return int(number)


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return None if number != number else number


def _kickoff(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)


def candidate_dates(kickoff: datetime) -> list[str]:
    """ESPN's scoreboard day (US Eastern), the Central day the poller files under, the UTC day."""
    out: list[str] = []
    for zone in (_EASTERN, _CENTRAL, timezone.utc):
        day = kickoff.astimezone(zone).date().isoformat()
        if day not in out:
            out.append(day)
    return out


# --------------------------------------------------------------------------------------------
# line arithmetic
# --------------------------------------------------------------------------------------------


def _single(margin: float) -> str:
    return "win" if margin > 0 else ("loss" if margin < 0 else "push")


def _halves(line: float) -> list[float]:
    """An Asian quarter line is two half-stakes at the neighbouring half lines."""
    if (abs(line) * 4) % 2 == 1:
        return [line - 0.25, line + 0.25]
    return [line]


def _combine(results: set[str]) -> tuple[str | None, str | None]:
    if len(results) == 1:
        return next(iter(results)), None
    return None, REASON_QUARTER_SPLIT


def settle_over_under(value: float, side: Any, line: Any) -> tuple[str | None, str | None]:
    side_token = _norm(side)
    number = _as_float(line)
    if number is None or side_token not in {"over", "under"}:
        return None, REASON_UNSETTLEABLE
    sign = 1.0 if side_token == "over" else -1.0
    return _combine({_single(sign * (value - part)) for part in _halves(number)})


def settle_spread(margin_for_side: float, line: Any) -> tuple[str | None, str | None]:
    number = _as_float(line)
    if number is None:
        return None, REASON_UNSETTLEABLE
    return _combine({_single(margin_for_side + part) for part in _halves(number)})


# --------------------------------------------------------------------------------------------
# names
# --------------------------------------------------------------------------------------------


def _token_subset(a: str, b: str) -> bool:
    """Whole-token containment, the shorter name inside the longer one, with a 4-char floor."""
    left, right = set(a.split()), set(b.split())
    if not left or not right:
        return False
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    if max(len(token) for token in shorter) < 4:
        return False
    return shorter <= longer


def team_names_match(record_team: Any, box_team: Any) -> bool:
    """Does an odds-feed club name name the same club as the ESPN box's?"""
    from syndicate.features.shared import team_aliases as ta

    if not _norm(record_team) or not _norm(box_team):
        return False
    left, right = ta.canonical_team("soccer", record_team), ta.canonical_team("soccer", box_team)
    if left and right:
        # The derived map is authoritative where it answers for both; a mismatch is real.
        return left == right
    if ta.teams_match("soccer", record_team, box_team):
        return True
    reduced_left = ta.strip_club_tokens(record_team) or ta.fold_accents(record_team)
    reduced_right = ta.strip_club_tokens(box_team) or ta.fold_accents(box_team)
    if reduced_left == reduced_right:
        return True
    vendor = getattr(ta, "_SOCCER_VENDOR_NAME_ALIASES", {}) or {}
    folded_vendor = {ta.fold_accents(key): value for key, value in vendor.items()}
    for mine, theirs in ((record_team, reduced_right), (box_team, reduced_left)):
        alias = folded_vendor.get(ta.fold_accents(mine))
        if alias and (ta.strip_club_tokens(alias) or ta.fold_accents(alias)) == theirs:
            return True
    return _token_subset(reduced_left, reduced_right)


def _norm_player(value: Any) -> str:
    from syndicate.features.shared.prop_projections import _norm_name

    return _norm_name(value)


def _unique(hits: list[Mapping[str, Any]]) -> tuple[Mapping[str, Any] | None, str | None] | None:
    """The tier's answer: one player, a refusal on several, or None to try the next tier."""
    distinct = list({id(player): player for player in hits}.values())
    if len(distinct) == 1:
        return distinct[0], None
    if len(distinct) > 1:
        return None, REASON_PLAYER_AMBIGUOUS
    return None


def find_player(box: Mapping[str, Any], player_name: Any) -> tuple[Mapping[str, Any] | None, str | None]:
    """One player of this match's roster, or `(None, reason)`.

    Three tiers, each required to be UNIQUE in this one match's roster, and a tier that finds
    several players refuses rather than falling through to a looser one:
      1. exact `_norm_name`, including the hyphen-glued form (`Lee Kang-In` / `kangin lee`
         compares as a token set);
      2. whole-token subset -- the feed's full legal name (`pablo barrios rivas`) holds ESPN's
         common name (`Pablo Barrios`); a one-token side needs 4+ characters;
      3. same surname (ESPN's last token, inside the feed's name after its first token) and the
         first names share their first three letters: `javier guerra` / `Javi Guerra`,
         `alex grimaldo` / `Alejandro Grimaldo`. Measured on the 2026-09-15/16 La Liga boxes.
    """
    roster: list[Mapping[str, Any]] = []
    for side in (box.get("players") or {}).values():
        for player in (side or {}).get("players") or []:
            if isinstance(player, Mapping) and _norm_player(player.get("player_name")):
                roster.append(player)
    if not roster:
        return None, REASON_NO_PLAYER_BOX
    key = _norm_player(player_name)
    if not key:
        return None, REASON_PLAYER_NOT_IN_BOX
    tokens = key.split()
    token_set = set(tokens)

    def forms(player: Mapping[str, Any]) -> list[list[str]]:
        raw = str(player.get("player_name") or "")
        return [_norm_player(raw).split(), _norm_player(raw.replace("-", "")).split()]

    found = _unique(
        [p for p in roster if any(form == tokens or set(form) == token_set for form in forms(p))]
    )
    if found:
        return found
    subset: list[Mapping[str, Any]] = []
    for player in roster:
        for form in forms(player):
            pool_tokens = set(form)
            shorter, longer = (pool_tokens, token_set) if len(pool_tokens) <= len(token_set) else (token_set, pool_tokens)
            if shorter <= longer and not (len(shorter) == 1 and len(next(iter(shorter))) < 4):
                subset.append(player)
                break
    found = _unique(subset)
    if found:
        return found
    surname: list[Mapping[str, Any]] = []
    if len(tokens) >= 2:
        for player in roster:
            form = forms(player)[0]
            if len(form) >= 2 and form[-1] in tokens[1:] and len(form[-1]) >= 3 and form[0][:3] == tokens[0][:3]:
                surname.append(player)
    found = _unique(surname)
    return found if found else (None, REASON_PLAYER_NOT_IN_BOX)


# --------------------------------------------------------------------------------------------
# the box
# --------------------------------------------------------------------------------------------


def is_final(box: Mapping[str, Any]) -> bool:
    return bool(box.get("final")) or _norm(box.get("status_state")) == "post"


def _player_goal_total(box: Mapping[str, Any]) -> int:
    total = 0
    for side in (box.get("players") or {}).values():
        for player in (side or {}).get("players") or []:
            total += _as_int((player or {}).get("goals")) or 0
    return total


def qualifying_goals(box: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]] | None, str | None]:
    """Non-own goals, checked against the score and the per-player tallies."""
    goals = [goal for goal in (box.get("goals") or []) if isinstance(goal, Mapping)]
    home, away = _as_int(box.get("score_home")), _as_int(box.get("score_away"))
    if home is None or away is None or len(goals) != home + away:
        return None, REASON_GOALS_INCONSISTENT
    scored = [goal for goal in goals if not goal.get("own_goal")]
    if len(scored) != _player_goal_total(box):
        return None, REASON_GOALS_INCONSISTENT
    return scored, None


def _goal_key(goal: Mapping[str, Any]) -> tuple[int, int, float] | None:
    match = _CLOCK_RE.match(str(goal.get("clock") or ""))
    if not match:
        return None
    seconds = _as_float(goal.get("clock_seconds"))
    return int(match.group(1)), int(match.group(2) or 0), seconds if seconds is not None else -1.0


def deciding_scorer(goals: list[Mapping[str, Any]], which: str) -> tuple[str | None, str | None]:
    """Normalised scorer of the first or last qualifying goal, or `(None, reason)`."""
    keyed = []
    for goal in goals:
        key = _goal_key(goal)
        if key is None:
            return None, REASON_GOAL_ORDER
        keyed.append((key, goal))
    target = min(k for k, _ in keyed) if which == "first" else max(k for k, _ in keyed)
    scorers = {_norm_player(goal.get("scorer")) for key, goal in keyed if key == target}
    if len(scorers) != 1 or "" in scorers:
        return None, REASON_GOAL_ORDER
    return next(iter(scorers)), None


def team_corners(box: Mapping[str, Any]) -> tuple[int, int] | None:
    teams = box.get("teams") or {}
    home = _as_int(((teams.get("home") or {}).get("stats") or {}).get("Corners"))
    away = _as_int(((teams.get("away") or {}).get("stats") or {}).get("Corners"))
    return None if home is None or away is None else (home, away)


# --------------------------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------------------------


def local_fetch_export(relative_path: str) -> str | None:
    """Read the artifact off this service's own data root (`SYNDICATE_DATA_ROOT`)."""
    from syndicate.features.shared.refresh_state_store import data_root

    try:
        return (data_root() / Path(relative_path)).read_text(encoding="utf-8")
    except (OSError, RuntimeError):
        return None


def export_fetcher(base_url: str, token: str, *, timeout: float = 180.0) -> Callable[[str], str | None]:
    """`fetch_export` over web's `/api/ops/artifacts/export?path=`; None when web has no file."""
    import urllib.error
    import urllib.parse
    import urllib.request

    def fetch(relative_path: str) -> str | None:
        url = f"{base_url.rstrip('/')}/api/ops/artifacts/export?path={urllib.parse.quote(relative_path, safe='')}"
        request = urllib.request.Request(url, headers={"X-Admin-Token": token, "User-Agent": "syndicate-soccer-settler"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                envelope = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 404):
                return None
            raise
        artifacts = envelope.get("artifacts") if isinstance(envelope, Mapping) else None
        if not isinstance(artifacts, Mapping) or relative_path not in artifacts:
            return None
        return str(artifacts[relative_path])

    return fetch


class SoccerPopulationSettler:
    """`extra_settler(shaped, view)` for soccer. One read per league-date per run.

    `fetch_export(relative_path) -> text | None`; the default reads the local data root.
    With `cache_dir`, a league-date file is kept on disk once it is at least two days old and
    every box in it is final, so a rerun does not export it again. `now` is injectable.
    """

    def __init__(
        self,
        *,
        fetch_export: Callable[[str], str | None] | None = None,
        cache_dir: Path | str | None = None,
        now: Callable[[], datetime] | None = None,
        leagues: list[str] | None = None,
    ) -> None:
        self._fetch = fetch_export or local_fetch_export
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._leagues = list(leagues) if leagues is not None else None
        self._payloads: dict[str, Mapping[str, Any] | None] = {}
        self._matches: dict[tuple[Any, ...], tuple[Mapping[str, Any] | None, str | None]] = {}
        self.fetches = 0
        self.join_attempts = 0
        self.join_hits = 0

    # -- which rows ---------------------------------------------------------------------------

    def handles(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> bool:
        if _norm(shaped.get("sport") or (view or {}).get("sport")) != "soccer":
            return False
        market = _market(shaped, view)
        if market in _GOALSCORER_MARKETS or market in _PLAYER_STAT_MARKETS:
            return bool(_norm(shaped.get("player_name")))
        if _is_card_market(market) or _is_corner_market(market):
            return True
        return _segment(shaped, view) != "full" and market in _SEGMENT_LINE_MARKETS

    def __call__(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None):
        if not self.handles(shaped, view):
            return None
        return self.settle(shaped, view)

    # -- settling -----------------------------------------------------------------------------

    def settle(self, shaped: Mapping[str, Any], view: Mapping[str, Any] | None = None) -> tuple[str | None, str | None]:
        if not self.handles(shaped, view):
            return None, REASON_NOT_HANDLED
        market, segment = _market(shaped, view), _segment(shaped, view)
        # Structural refusals first: they are permanent, and must not wait on a fetch.
        if _is_card_market(market):
            return None, REASON_CARDS
        is_player = market in _GOALSCORER_MARKETS or market in _PLAYER_STAT_MARKETS
        if is_player and segment != "full":
            return None, REASON_PROP_SEGMENT
        if _is_corner_market(market) and segment != "full":
            return None, REASON_CORNERS_SEGMENT

        kickoff = _kickoff(shaped.get("commence_time"))
        if kickoff is None:
            return None, REASON_NO_COMMENCE
        if kickoff > self._now():
            return None, REASON_NOT_STARTED
        if not (_norm(shaped.get("home_team")) and _norm(shaped.get("away_team"))):
            return None, REASON_NO_TEAMS

        box, why = self.find_match(shaped)
        if box is None:
            return None, why

        if segment != "full":
            return self._settle_segment(box, market, segment, shaped)
        if not is_final(box):
            return None, REASON_NOT_FINAL
        if market in _GOALSCORER_MARKETS:
            return self._settle_goalscorer(box, _GOALSCORER_MARKETS[market], shaped)
        if market in _PLAYER_STAT_MARKETS:
            return self._settle_player_stat(box, _PLAYER_STAT_MARKETS[market], shaped)
        return self._settle_corners(box, market, shaped)

    def _settle_goalscorer(self, box, kind, shaped):
        goals, why = qualifying_goals(box)
        if goals is None:
            return None, why
        if _norm_player(shaped.get("player_name")) in _NO_SCORER_NAMES:
            return ("win" if not goals else "loss"), None
        player, why = find_player(box, shaped.get("player_name"))
        if player is None:
            return None, why
        if not player.get("appeared"):
            return None, REASON_DNP
        if kind == "anytime":
            scored = _as_int(player.get("goals"))
            if scored is None:
                return None, REASON_STAT_MISSING
            return ("win" if scored >= 1 else "loss"), None
        if not goals:
            return "loss", None
        scorer, why = deciding_scorer(goals, kind)
        if scorer is None:
            return None, why
        return ("win" if scorer == _norm_player(player.get("player_name")) else "loss"), None

    def _settle_player_stat(self, box, stat, shaped):
        player, why = find_player(box, shaped.get("player_name"))
        if player is None:
            return None, why
        if not player.get("appeared"):
            return None, REASON_DNP
        value = _as_float(player.get(stat))
        if value is None:
            return None, REASON_STAT_MISSING
        return settle_over_under(value, shaped.get("side"), shaped.get("line"))

    def _settle_corners(self, box, market, shaped):
        corners = team_corners(box)
        if corners is None:
            return None, REASON_NO_CORNERS
        home, away = corners
        side = _norm(shaped.get("side")).replace("_", " ")
        if "team" not in market:
            return settle_over_under(home + away, side, shaped.get("line"))
        # A team corners total needs the team AND the direction in the side token. No such row
        # has been recorded yet, so anything but an explicit `home|away` + `over|under` refuses.
        words = set(side.split())
        slot = words & {"home", "away"}
        direction = words & {"over", "under"}
        if len(slot) != 1 or len(direction) != 1:
            return None, REASON_TEAM_CORNERS_SIDE
        value = home if slot == {"home"} else away
        return settle_over_under(value, next(iter(direction)), shaped.get("line"))

    def _settle_segment(self, box, market, segment, shaped):
        from syndicate.features.shared.segment_actuals import segment_actuals

        record = {
            "home_linescores": box.get("home_linescores"),
            "away_linescores": box.get("away_linescores"),
            "final": is_final(box),
            "in_progress": _norm(box.get("status_state")) == "in",
            "period": box.get("status_period"),
            "status_detail": box.get("status_detail"),
        }
        actual = segment_actuals("soccer", segment, record)
        if actual.get("unavailable_reason"):
            return None, actual["unavailable_reason"]
        if not actual.get("started"):
            return None, REASON_SEGMENT_NOT_STARTED
        if not actual.get("is_final"):
            return None, REASON_SEGMENT_NOT_FINAL
        if is_final(box):
            halves_home = [_as_int(v) for v in box.get("home_linescores") or []]
            halves_away = [_as_int(v) for v in box.get("away_linescores") or []]
            if None in halves_home or None in halves_away or (
                sum(halves_home) != _as_int(box.get("score_home")) or sum(halves_away) != _as_int(box.get("score_away"))
            ):
                return None, REASON_LINESCORES_INCONSISTENT
        home, away = int(actual["home_score"]), int(actual["away_score"])
        side = self._side_slot(shaped, box)
        if market in {"h2h", "h2h_3_way"}:
            if side == "draw":
                return ("win" if home == away else "loss"), None
            if side in {"home", "away"}:
                mine, theirs = (home, away) if side == "home" else (away, home)
                return ("win" if mine > theirs else "loss"), None
            return None, REASON_UNSETTLEABLE
        if market == "btts":
            if side not in {"yes", "no"}:
                return None, REASON_UNSETTLEABLE
            return ("win" if (home > 0 and away > 0) == (side == "yes") else "loss"), None
        if market in {"spreads", "alternate_spreads"}:
            if side not in {"home", "away"}:
                return None, REASON_UNSETTLEABLE
            margin = home - away if side == "home" else away - home
            return settle_spread(margin, shaped.get("line"))
        return settle_over_under(home + away, side, shaped.get("line"))

    @staticmethod
    def _side_slot(shaped, box) -> str:
        side = _norm(shaped.get("side"))
        if side in {"home", "away", "draw", "over", "under", "yes", "no"}:
            return side
        for slot, name in (("home", shaped.get("home_team")), ("away", shaped.get("away_team"))):
            if name and team_names_match(side, name):
                return slot
        return side

    # -- the join -----------------------------------------------------------------------------

    def find_match(self, shaped: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str | None]:
        home, away = shaped.get("home_team"), shaped.get("away_team")
        kickoff = _kickoff(shaped.get("commence_time"))
        if kickoff is None:
            return None, REASON_NO_COMMENCE
        memo_key = (_norm(home), _norm(away), kickoff.isoformat())
        self.join_attempts += 1
        if memo_key not in self._matches:
            self._matches[memo_key] = self._find_match(home, away, kickoff)
        found = self._matches[memo_key]
        if found[0] is not None:
            self.join_hits += 1
        return found

    def _find_match(self, home, away, kickoff):
        readable = False
        hinted = self._league_hint(home, away)
        for day in candidate_dates(kickoff):
            hits: list[Mapping[str, Any]] = []
            for league in self._leagues_for(hinted, day):
                payload = self._payload(league, day)
                if payload is None:
                    continue
                readable = True
                for box in (payload.get("match_box") or {}).values():
                    if isinstance(box, Mapping) and team_names_match(home, box.get("home_team")) and team_names_match(
                        away, box.get("away_team")
                    ):
                        hits.append(box)
                # Both clubs resolve inside exactly one league and it holds exactly one match:
                # nothing another league holds could be the same fixture.
                if league == hinted and len(hits) == 1:
                    return hits[0], None
            if len(hits) == 1:
                return hits[0], None
            if len(hits) > 1:
                return None, REASON_MATCH_AMBIGUOUS
        return None, (REASON_MATCH_NOT_FOUND if readable else REASON_NO_LIVE_STATE)

    def _league_hint(self, home, away) -> str | None:
        try:
            from syndicate.features.shared.team_aliases import _soccer_alias_by_league, fold_accents, normalize

            leagues = [
                league
                for league, mapping in _soccer_alias_by_league().items()
                if (mapping.get(normalize(home)) or mapping.get(fold_accents(home)))
                and (mapping.get(normalize(away)) or mapping.get(fold_accents(away)))
            ]
        except Exception:
            return None
        return leagues[0] if len(leagues) == 1 else None

    def _leagues_for(self, hint: str | None, day: str) -> list[str]:
        if self._leagues is not None:
            leagues = list(self._leagues)
        else:
            try:
                from syndicate.features.soccer.sources import active_leagues_for_date

                leagues = list(active_leagues_for_date(day))
            except Exception:
                leagues = []
        if hint in leagues:
            leagues.remove(hint)
            leagues.insert(0, hint)
        return leagues

    def _payload(self, league: str, day: str) -> Mapping[str, Any] | None:
        relative = LIVE_STATE_PATH_TEMPLATE.format(league=league, date=day)
        if relative in self._payloads:
            return self._payloads[relative]
        cached = self._cache_dir / relative.replace("/", "__") if self._cache_dir else None
        text = None
        if cached is not None and cached.is_file():
            text = cached.read_text(encoding="utf-8")
        else:
            text = self._fetch(relative)
            self.fetches += 1
        payload = None
        if text:
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            payload = parsed if isinstance(parsed, Mapping) else None
        if payload is not None and cached is not None and not cached.is_file() and self._keep(payload, day):
            cached.parent.mkdir(parents=True, exist_ok=True)
            cached.write_text(text, encoding="utf-8")
        self._payloads[relative] = payload
        return payload

    def _keep(self, payload: Mapping[str, Any], day: str) -> bool:
        boxes = [box for box in (payload.get("match_box") or {}).values() if isinstance(box, Mapping)]
        try:
            old_enough = date.fromisoformat(day) <= self._now().astimezone(_CENTRAL).date() - timedelta(days=2)
        except ValueError:
            return False
        return old_enough and bool(boxes) and all(is_final(box) for box in boxes)


__all__ = [
    "GRADER_VERSION",
    "SoccerPopulationSettler",
    "candidate_dates",
    "export_fetcher",
    "find_player",
    "local_fetch_export",
    "settle_over_under",
    "settle_spread",
    "team_names_match",
]
