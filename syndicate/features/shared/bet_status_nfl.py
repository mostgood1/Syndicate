"""Resolve an NFL bet's CURRENT value from the captured live-state artifact.

The fourth sibling of `bet_status_mlb`, `bet_status_wnba` and
`bet_status_soccer`, and deliberately the same shape: it answers "what is the
thing this bet is on worth right now" and leaves every judgement about winning
and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
WHY THIS EXISTS: NFL BETS COULD NEVER SETTLE
--------------------------------------------------------------------------

`paper_settlement._default_resolver` had builders for `mlb`, `wnba` and
`soccer` only, so every NFL order returned `no_resolver_for_nfl` -- forever.
Measured on refresh-worker 2026-08-28T02:37-02:50Z:

    SETTLED date=2026-08-28 orders=21 graded=0
      ungraded={..., 'no_resolver_for_nfl': 6, ...}          6 of 21 = 29%
    BET_STATUS orders=158 resolved=98
      reasons={..., 'no_resolver_for_nfl': 16, ...}

NFL was the only sport producing orders with no resolver at all, and Week 1 is
where its volume starts rather than ends.

--------------------------------------------------------------------------
JOINED ON THE TEAM PAIR, NOT ON `event_id`
--------------------------------------------------------------------------

The same trap soccer documents and `bet_status_wnba` says cost MLB a day: the
order's `event_id` is the OddsAPI event hash, while the capture is keyed by
ESPN's event id. Different namespaces, and no amount of parsing bridges them.
WNBA got to key on `event_id` only because its box and its board share one id.

So this joins on `home_team`/`away_team` through `team_aliases`, whose NFL map
carries all 32 clubs; `poll_nfl_live_state` stores BOTH the display name and
the tri-code so the join does not depend on which form the board stored. An
order without the team fields refuses BY NAME rather than falling back to an id
that cannot match.

--------------------------------------------------------------------------
A TIE IS A PUSH HERE, AND THAT IS `draw_possible=False`
--------------------------------------------------------------------------

Counter-intuitive, so it is stated: NFL regular-season games CAN end level, and
a level moneyline is a PUSH -- the stake comes back. `game_line_view` encodes
exactly that under `draw_possible=False`, whose own comment names "the sports
where a tie is merely rare rather than impossible". Passing `True` -- the
soccer setting -- would make `three_way` true and grade a tie as a LOSS.

The board does emit `h2h_3_way` for NFL (measured in `VENUE_REPRICE_KEYS`
board_wanted samples, 2026-08-28T02:10Z). That market is in
`game_line_bet._ALWAYS_THREE_WAY`, so it is graded three-way off the MARKET
NAME regardless of this flag, and needs no special case here.

--------------------------------------------------------------------------
PROPS ARE GRADED OFF ESPN'S PER-PLAYER BOX (since 2026-09-10)
--------------------------------------------------------------------------

The scoreboard capture carries team scores and nothing per-player. Until
2026-09-10 that made every prop a PERMANENT refusal
(`nfl_props_not_gradeable_from_scoreboard`) -- which, once the board began
staking NFL props on 2026-09-09, meant real exposure with no production grade.
It was already firing on the first order the morning after.

Props now read ESPN's summary for the game (`nfl/live_player_box`), found
through the capture's own `event_id`. The rules that stay:

  * PERMANENT BEFORE TRANSIENT. An unmapped player market or a non-full segment
    refuses by name before anything is read, the order the game-line path below
    has always used -- `bet_status_wnba` states the rule and paid for it.
  * ABSENT IS NOT ZERO. A player missing from a FINAL box may have been
    inactive (books void that) or active with no touch; this box cannot tell
    them apart, so it refuses. A player who appears in ANY stat group played,
    so his zeros are real zeros and settle.
  * ONE READ PER GAME. The box is cached per resolver, like the live state.

--------------------------------------------------------------------------
ABSENT FROM THE BOX IS ANSWERED BY THE GAME ROSTER (2026-10-27, #744 H6)
--------------------------------------------------------------------------

ESPN's summary lists a player only in a stat group he recorded something in.
A receiver with no catch and no carry is in NO group, so "absent" was the
refusal for every quiet game. Measured on the fleet 2026-10-27 over the 28
stale rows (11 player-games) refused `nfl_player_not_in_final_box`:

    8 played and recorded zero    ESPN core game roster `didNotPlay: false`
                                  + per-player `gamesPlayed: 1`, receptions 0
                                  (Troy Franklin, Jeremy Ruckert, Jonnu Smith,
                                  Ted Hurst III, Cam Skattebo -- "on the field
                                  for six snaps", 0 carries, per ESPN's own
                                  recap -- Foster Moreau, Pierre Strong Jr.,
                                  Christian Kirk)
    2 inactive                    `didNotPlay: true`, no stats (Tyler Warren,
                                  Tyjae Spears)
    1 name form                   the board's "Zonovan Knight" is ESPN's "Bam
                                  Knight" (no "Zonovan" anywhere in ESPN's
                                  athlete record), and he IS in the box

So a final-box absence now asks ESPN's core API for that game's roster:

  * PLAYED is proved only when the roster says `didNotPlay: false` AND his
    per-player game statistics say `gamesPlayed >= 1`. The value is then read
    from those statistics -- ESPN's explicit zero, never a zero inferred from
    absence -- and a stat missing there refuses.
  * DID NOT PLAY is `didNotPlay: true` with no statistics. Books void that; this
    module refuses it BY NAME (`REASON_DNP_VOID`), as `bet_status_nhl`
    (`dnp_void`) and `bet_status_soccer` do. No new outcome type.
  * Anything else refuses by name: the two flags disagreeing, not on either
    roster, two candidates. Measured over the 1,237 roster rows of those 11
    games: 2 carry `didNotPlay: true` WITH statistics (`gamesPlayed: 1`), and
    49 carry `didNotPlay: false` with no statistics at all. Neither proves
    anything, so neither grades.

THE READ IS SETTLEMENT-ONLY. It happens for a FINAL game whose kickoff is more
than `SETTLEMENT_MIN_HOURS_AFTER_KICKOFF` hours old, so `portfolio_commit`'s
per-tick resolve on a live slate never reaches it; each URL is read once per
resolver, on a timeout, and every failure is a named refusal.

College football has no equivalent signal -- measured 2026-10-27 on USC @
Wisconsin: the college game roster is the whole 128-man roster, every row
`didNotPlay: false`, with statistics only for the players already in the box
-- so `bet_status_ncaaf` grades in-box players only and refuses the rest.
"""

from __future__ import annotations

import collections
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from syndicate.features.shared.segment_actuals import (
    FULL_GAME_SEGMENT,
    REASON_UNSUPPORTED_SEGMENT_PREFIX,
    order_segment,
    segment_actuals,
    segment_periods,
)

__all__ = [
    "EspnSettlementFeed",
    "match_box_player",
    "nfl_status_resolver",
    "prop_field",
    "prop_view",
    "roster_participation",
    "settlement_memo_get",
    "settlement_memo_key",
    "settlement_memo_put",
    "settlement_window_open",
]

REASON_NOT_NFL = "not_an_nfl_order"
REASON_NO_MATCHUP = "no_home_away_teams_on_order"
REASON_NO_LIVE_STATE = "no_nfl_live_state_for_date"
REASON_GAME_NOT_FOUND = "game_not_in_nfl_live_state"
REASON_UNKNOWN_MARKET = "unmapped_market"
# PLAYER PROPS, graded off ESPN's per-player box since 2026-09-10. Until then
# every one refused as `nfl_props_not_gradeable_from_scoreboard`, which made
# NFL props stakeable but unmeasurable. Each refusal below is named, and each is
# one of two kinds: PERMANENT (this market or segment can never be graded here)
# or TRANSIENT (the box is not there yet).
REASON_PROP_MARKET = "nfl_prop_market_not_mapped"
REASON_PROP_SEGMENT = "nfl_prop_needs_full_game"
REASON_NO_EVENT_ID = "nfl_game_has_no_espn_event_id"
REASON_NO_BOX = "nfl_player_box_unavailable"
# A player absent from a FINAL box may have been inactive -- which books VOID --
# or active with no touch in any stat group. Those settle differently and this
# box cannot tell them apart, so it refuses rather than grading a zero. Since
# 2026-10-27 the game roster answers it once the settlement window opens; this
# reason now means "absent, and the roster not yet asked" (inside the window,
# or no readable kickoff to open it).
REASON_PLAYER_NOT_IN_BOX = "nfl_player_not_in_final_box"
REASON_PLAYER_NOT_IN_BOX_YET = "nfl_player_not_in_live_box_yet"
REASON_PLAYER_AMBIGUOUS = "nfl_player_ambiguous_in_box"
# THE GAME-ROSTER READ behind a final-box absence (2026-10-27). Each names what
# stopped it, so the counter says which job is left. Only the DNP one is a
# fact about the PLAYER; the rest are facts about the read.
REASON_DNP_VOID = "nfl_player_did_not_play_void"
REASON_ROSTER_UNAVAILABLE = "nfl_game_roster_unavailable"
REASON_NOT_ON_GAME_ROSTER = "nfl_player_not_on_game_roster"
REASON_ROSTER_AMBIGUOUS = "nfl_player_ambiguous_on_game_roster"
REASON_PARTICIPATION_UNKNOWN = "nfl_player_participation_unproven"
REASON_GAME_STATS_UNAVAILABLE = "nfl_player_game_stats_unavailable"
REASON_STAT_NOT_IN_GAME_STATS = "nfl_stat_not_in_player_game_stats"
REASON_PARTICIPATION_READ_FAILED = "nfl_game_roster_read_failed"
# Set on a resolved prop ONLY by the roster path, so a reading can say which
# path graded it -- and a test can prove that path was reached.
VALUE_SOURCE_CORE_GAME_STATS = "espn_core_player_game_stats"
# A team total is ONE side's points. Grading it off the combined score would
# roughly double the value and settle overs that lost, so it refuses until the
# side token is read properly. Same refusal soccer makes, same reason.
REASON_TEAM_TOTAL = "team_totals_needs_a_per_team_score"
REASON_NO_SCORES = "game_carries_no_scores"

# The combined-points family. `team_totals` is deliberately ABSENT -- see above.
_GAME_TOTAL_MARKETS = frozenset({"totals", "total", "totals_alt", "alternate_totals"})
_TEAM_TOTAL_MARKETS = frozenset({"team_totals", "team_total", "team_totals_alt"})


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _as_float(value: Any) -> float | None:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


# Board market -> the box field that settles it. BOTH vocabularies, because both
# reach orders: the board writes display labels ("Receiving Yards") and a
# minority of rows still carry the raw OddsAPI key -- 28 of 1,422 served NFL
# prop rows on 2026-09-09 arrived as `player_receptions` / `player_pass_tds`.
# `interceptions` here is the QB's prop, interceptions THROWN, which is why the
# box reads it from ESPN's `passing` group only.
_PROP_FIELDS = {
    "passing yards": "pass_yards",
    "player_pass_yds": "pass_yards",
    "passing attempts": "pass_attempts",
    "player_pass_attempts": "pass_attempts",
    "passing completions": "completions",
    "player_pass_completions": "completions",
    "passing tds": "pass_td",
    "passing touchdowns": "pass_td",
    "player_pass_tds": "pass_td",
    "interceptions": "pass_int",
    "player_pass_interceptions": "pass_int",
    "rushing yards": "rush_yards",
    "player_rush_yds": "rush_yards",
    "rushing attempts": "rush_attempts",
    "player_rush_attempts": "rush_attempts",
    "receptions": "receptions",
    "player_receptions": "receptions",
    "receiving yards": "rec_yards",
    "player_reception_yds": "rec_yards",
    "anytime td": "td_scored",
    "player_anytime_td": "td_scored",
}
# Anytime TD is a yes/no market with no line on the board. "Scored at least
# once" is `td_scored > 0.5`, and `paper_settlement` honours a line the resolver
# supplies (`resolved.get("line", order.get("line"))`).
_ANYTIME_TD_FIELD = "td_scored"
_ANYTIME_TD_LINE = 0.5
_NAME_SUFFIXES = frozenset({"jr", "sr", "ii", "iii", "iv", "v"})


def _player_key(value: Any) -> str:
    """A player name folded for joining a board order to ESPN's box.

    Built ON `prop_projections._norm_name`, which already folds accents and
    ligatures correctly, and fixes the two things it cannot: INITIALS and
    SUFFIXES. `_norm_name` turns "A.J. Brown" into "a j brown" while the board
    writes "AJ Brown" -> "aj brown", so runs of single letters are merged here;
    and ESPN and the books disagree on "Jr." / "III", so suffixes are dropped.
    Measured on the opener: ESPN's box carries "A.J. Brown", the board "AJ Brown".
    """
    from syndicate.features.shared.prop_projections import _norm_name

    tokens = [token for token in _norm_name(value).split() if token not in _NAME_SUFFIXES]
    merged: list[str] = []
    initials = ""
    for token in tokens:
        if len(token) == 1:
            initials += token
            continue
        if initials:
            merged.append(initials)
            initials = ""
        merged.append(token)
    if initials:
        merged.append(initials)
    return " ".join(merged)


# A NAME FORM NO FOLD CAN BRIDGE: the board's legal first name against ESPN's
# chosen one. `_player_key` form on both sides, board -> ESPN. Each entry is a
# MEASUREMENT, not a guess -- an alias that is wrong grades the wrong player.
#   zonovan knight -> bam knight   ESPN athlete 4427728 is "Bam Knight" in its
#       fullName, displayName and firstName alike; ARI @ DEN 2026-10-25 box.
_PLAYER_NAME_ALIASES: Mapping[str, tuple[str, ...]] = {
    "zonovan knight": ("bam knight",),
}


def _player_keys(value: Any) -> frozenset[str]:
    """Every `_player_key` form this name may appear under in ESPN's data."""
    key = _player_key(value)
    if not key:
        return frozenset()
    return frozenset((key, *_PLAYER_NAME_ALIASES.get(key, ())))


def prop_field(canonical_market: str) -> str | None:
    """The box field that settles this (normalised) player market, or None.

    Shared with `bet_status_ncaaf`: ESPN's college box is the same shape, so the
    same market reads the same field."""
    return _PROP_FIELDS.get(canonical_market)


def match_box_player(rows: list[Mapping[str, Any]], player_name: Any) -> tuple[Mapping[str, Any] | None, str | None]:
    """`(row, None)`, or `(None, "absent" | "ambiguous")`. Never a guess."""
    keys = _player_keys(player_name)
    matches = [row for row in rows if keys and _player_key(row.get("player_name")) in keys]
    if len(matches) > 1:
        return None, "ambiguous"
    if not matches:
        return None, "absent"
    return matches[0], None


def prop_view(row: Mapping[str, Any], field: str, order: Mapping[str, Any], *, is_final: bool) -> dict[str, Any]:
    """The resolved value of one player's field, with Anytime TD's implicit line."""
    resolved: dict[str, Any] = {
        "current_value": _as_float(row.get(field)),
        "is_final": is_final,
        "started": True,
    }
    if field == _ANYTIME_TD_FIELD and _as_float(order.get("line")) is None:
        resolved["line"] = _ANYTIME_TD_LINE
    return resolved


# ---------------------------------------------------------------------------
# SETTLEMENT-ONLY ESPN READS (2026-10-27). See the module docstring.
# ---------------------------------------------------------------------------

_ESPN_SUMMARY_URLS: Mapping[str, str] = {
    "nfl": "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary",
    "ncaaf": "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary",
}
_ESPN_CORE_EVENTS_URLS: Mapping[str, str] = {
    "nfl": "https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events",
    "ncaaf": "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football/events",
}
# The core API answers with `$ref` links to itself. Only that host is followed,
# and always over https (the links come back as http://).
_ESPN_CORE_HOST = "sports.core.api.espn.com"
_SETTLEMENT_FETCH_TIMEOUT_SECONDS = 6.0
# A game is read for settlement only once its kickoff is this old. The live
# slate is resolved every `portfolio_commit` tick; this keeps those ticks off
# the network, and a game that started six hours ago is over.
SETTLEMENT_MIN_HOURS_AFTER_KICKOFF = 6.0
# More surname matches than this on two game rosters is not a lookup any more.
_MAX_ROSTER_NAME_CANDIDATES = 4

# Per-player game statistics (`category.name`) -> the box field it settles.
# Measured on 401872975 (Troy Franklin) and 401873019 (Bam Knight: 7 rushes,
# 3 catches for 15 -- identical to the summary box).
_CORE_STAT_FIELDS: Mapping[str, str] = {
    "passing.passingYards": "pass_yards",
    "passing.passingAttempts": "pass_attempts",
    "passing.completions": "completions",
    "passing.passingTouchdowns": "pass_td",
    "passing.interceptions": "pass_int",
    "rushing.rushingYards": "rush_yards",
    "rushing.rushingAttempts": "rush_attempts",
    "rushing.rushingTouchdowns": "rush_td",
    "receiving.receptions": "receptions",
    "receiving.receivingYards": "rec_yards",
    "receiving.receivingTouchdowns": "rec_td",
}
_CORE_GAMES_PLAYED = "general.gamesPlayed"


def _default_fetch_json(url: str) -> Any:
    """GET -> parsed JSON, or None. Never raises.

    NO CUSTOM HEADERS, deliberately: ESPN 403s browser-spoof User-Agents from a
    datacentre IP (`nfl/live_player_box`'s docstring carries the probes)."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(  # noqa: S310 -- fixed https hosts only
            urllib.request.Request(url), timeout=_SETTLEMENT_FETCH_TIMEOUT_SECONDS
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:
        return None


def _utcnow() -> datetime:
    """A seam, so a test can fix the clock the settlement window reads."""
    return datetime.now(timezone.utc)


def _parse_kickoff(value: Any) -> datetime | None:
    """An ISO stamp WITH an hour, or None. A bare date cannot open a 6 h window."""
    text = str(value or "").strip()
    if len(text) <= 10:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def settlement_window_open(record: Mapping[str, Any] | None, order: Mapping[str, Any]) -> bool:
    """True only when a READABLE kickoff is more than six hours in the past.

    ESPN's own start (`start_time` on the capture record) first, the order's
    OddsAPI `commence_time` second. Neither readable means False: an unknown
    kickoff must not default to "long enough ago" and put a live tick on the
    network."""
    for stamp in ((record or {}).get("start_time"), order.get("commence_time")):
        moment = _parse_kickoff(stamp)
        if moment is not None:
            return (_utcnow() - moment).total_seconds() > SETTLEMENT_MIN_HOURS_AFTER_KICKOFF * 3600.0
    return False


class EspnSettlementFeed:
    """Settlement-only reads of ESPN for ONE league, one per path per instance.

    `bet_status_nhl.NhlFeed`'s shape: `fetch_json(url) -> payload | None`, and
    None means the module default, RESOLVED AT CALL TIME so a test substitutes
    it without network. Construction reads nothing; a failed read is
    remembered for this instance only and retried by the next resolver."""

    def __init__(self, league: str, *, fetch_json: Callable[[str], Any] | None = None) -> None:
        self.league = league
        self._fetch_json = fetch_json
        self._memo: dict[str, Any] = {}
        self.counters: collections.Counter[str] = collections.Counter()

    @property
    def memoisable(self) -> bool:
        """Only a feed on the real fetch writes the process-wide refusal memo.
        An injected `fetch_json` is a test's private world and must not leak
        into the next test, or into the process."""
        return self._fetch_json is None

    def _get(self, url: str) -> Any:
        if url in self._memo:
            return self._memo[url]
        fetch = self._fetch_json or _default_fetch_json
        self.counters["espn_requests"] += 1
        try:
            payload = fetch(url)
        except Exception:
            payload = None
        if payload is None:
            self.counters["espn_failures"] += 1
        self._memo[url] = payload
        return payload

    def _follow(self, link: Any) -> Any:
        from urllib.parse import urlsplit, urlunsplit

        url = link.get("$ref") if isinstance(link, Mapping) else None
        parts = urlsplit(str(url or ""))
        if parts.hostname != _ESPN_CORE_HOST:
            return None
        return self._get(urlunsplit(parts._replace(scheme="https")))

    def summary_rows(self, event_id: str) -> list[dict[str, Any]] | None:
        """Every athlete in the game's summary box (unfiltered), or None = NOT READ."""
        from urllib.parse import quote

        from syndicate.features.nfl.live_player_box import player_stat_rows_from_summary

        base = _ESPN_SUMMARY_URLS.get(self.league)
        event_id = str(event_id or "").strip()
        if not base or not event_id:
            return None
        payload = self._get(f"{base}?event={quote(event_id)}")
        try:
            return player_stat_rows_from_summary(payload)
        except Exception:
            return None

    def game_roster(self, event_id: str) -> list[Mapping[str, Any]] | None:
        """Both teams' game-roster entries, or None when either could not be read.

        Half a roster is not a roster: a player missing from the half that was
        read says nothing about the half that was not."""
        base = _ESPN_CORE_EVENTS_URLS.get(self.league)
        event_id = str(event_id or "").strip()
        if not base or not event_id:
            return None
        competition = f"{base}/{event_id}/competitions/{event_id}"
        competitors = self._get(f"{competition}/competitors")
        items = competitors.get("items") if isinstance(competitors, Mapping) else None
        if not isinstance(items, list) or len(items) != 2:
            return None
        entries: list[Mapping[str, Any]] = []
        for item in items:
            team_id = str(item.get("id") or "").strip() if isinstance(item, Mapping) else ""
            if not team_id:
                return None
            roster = self._get(f"{competition}/competitors/{team_id}/roster")
            rows = roster.get("entries") if isinstance(roster, Mapping) else None
            if not isinstance(rows, list) or not rows:
                return None
            entries.extend(row for row in rows if isinstance(row, Mapping))
        return entries

    def athlete_names(self, entry: Mapping[str, Any]) -> list[str] | None:
        """The athlete's full-name forms. The roster row itself carries only a surname."""
        athlete = self._follow(entry.get("athlete"))
        if not isinstance(athlete, Mapping):
            return None
        first, last = str(athlete.get("firstName") or "").strip(), str(athlete.get("lastName") or "").strip()
        names = [athlete.get("fullName"), athlete.get("displayName"), f"{first} {last}".strip()]
        return [str(name).strip() for name in names if str(name or "").strip()]

    def game_stats(self, entry: Mapping[str, Any]) -> dict[str, float] | None:
        """`{"category.stat": value}` for this player in this game, or None."""
        payload = self._follow(entry.get("statistics"))
        splits = payload.get("splits") if isinstance(payload, Mapping) else None
        categories = splits.get("categories") if isinstance(splits, Mapping) else None
        if not isinstance(categories, list):
            return None
        out: dict[str, float] = {}
        for category in categories:
            if not isinstance(category, Mapping):
                continue
            for stat in category.get("stats") or ():
                if not isinstance(stat, Mapping):
                    continue
                value = _as_float(stat.get("value"))
                if value is not None:
                    out[f"{category.get('name')}.{stat.get('name')}"] = value
        return out or None


# ---------------------------------------------------------------------------
# PROCESS-WIDE REFUSAL MEMO (2026-10-27)
# ---------------------------------------------------------------------------
# A refused row is RE-ASKED: every settlement tick while it sits in the live
# ledger document (`settle_orders` re-runs its straggler dates), then hourly by
# the archived pass for 14 days after eviction. Each pass builds a NEW resolver,
# so the per-instance memo above does not survive it, and one refused player
# would cost ~8 ESPN reads (summary, competitors, two rosters, athletes, stats)
# per tick, indefinitely. This remembers the REFUSAL across resolvers:
#
#   key      (league, ESPN event_id, `_player_key(player_name)`)
#   value    the refusal dict, until an expiry on `_utcnow()`
#   TTL      6 h for a DEFINITIVE answer about the player (did not play, not on
#            the game roster, ambiguous, participation unproven, not in the
#            final box); 1 h for a READ FAILURE, which is retried after it
#   bound    `SETTLEMENT_MEMO_MAX` entries, oldest written evicted first
#
# A "played" answer is not remembered: that row grades and is never asked again.
# Only a final game inside the settlement window can reach it, so a live tick
# never reads or writes it.
_SETTLEMENT_MEMO: dict[tuple[str, str, str], tuple[datetime, dict[str, Any]]] = {}
_SETTLEMENT_MEMO_LOCK = threading.Lock()
SETTLEMENT_MEMO_MAX = 512
SETTLEMENT_MEMO_DEFINITIVE_TTL = timedelta(hours=6)
SETTLEMENT_MEMO_READ_FAILURE_TTL = timedelta(hours=1)

# Facts about the PLAYER (6 h) versus facts about the READ (1 h). A reason in
# neither is never remembered.
_DEFINITIVE_ROSTER_REFUSALS = frozenset(
    {REASON_DNP_VOID, REASON_NOT_ON_GAME_ROSTER, REASON_ROSTER_AMBIGUOUS, REASON_PARTICIPATION_UNKNOWN}
)
_READ_FAILURE_ROSTER_REFUSALS = frozenset(
    {REASON_ROSTER_UNAVAILABLE, REASON_PARTICIPATION_READ_FAILED, REASON_GAME_STATS_UNAVAILABLE}
)


def settlement_memo_key(league: str, event_id: Any, player_name: Any) -> tuple[str, str, str] | None:
    """`(league, event_id, player key)`, or None when either part is empty."""
    event_id = str(event_id or "").strip()
    key = _player_key(player_name)
    if not event_id or not key:
        return None
    return (str(league), event_id, key)


def settlement_memo_get(feed: EspnSettlementFeed, key: tuple[str, str, str] | None) -> dict[str, Any] | None:
    """The remembered refusal (a copy), or None: no key, a test's feed, a miss, or expired."""
    if key is None or not feed.memoisable:
        return None
    now = _utcnow()
    with _SETTLEMENT_MEMO_LOCK:
        hit = _SETTLEMENT_MEMO.get(key)
        if hit is None:
            return None
        if hit[0] <= now:
            _SETTLEMENT_MEMO.pop(key, None)
            return None
    feed.counters["settlement_memo_hits"] += 1
    return dict(hit[1])


def settlement_memo_put(
    feed: EspnSettlementFeed, key: tuple[str, str, str] | None, refusal: Mapping[str, Any], *, definitive: bool
) -> None:
    """Remember a REFUSAL for 6 h (`definitive`) or 1 h (a read failure)."""
    if key is None or not feed.memoisable or not refusal.get("unavailable_reason"):
        return
    ttl = SETTLEMENT_MEMO_DEFINITIVE_TTL if definitive else SETTLEMENT_MEMO_READ_FAILURE_TTL
    with _SETTLEMENT_MEMO_LOCK:
        # Re-inserted at the END, so eviction stays oldest-WRITTEN first.
        _SETTLEMENT_MEMO.pop(key, None)
        _SETTLEMENT_MEMO[key] = (_utcnow() + ttl, dict(refusal))
        while len(_SETTLEMENT_MEMO) > SETTLEMENT_MEMO_MAX:
            _SETTLEMENT_MEMO.pop(next(iter(_SETTLEMENT_MEMO)))


def roster_participation(feed: EspnSettlementFeed, event_id: str, player_name: Any) -> dict[str, Any]:
    """`{"played": row}` -- the player's own game line -- or `{"unavailable_reason": ...}`.

    For a player ABSENT from a final box. Identity is the athlete record behind
    a game-roster row (the row carries a surname only), so a surname shared
    with a teammate or an opponent cannot stand in for him. Played is proved by
    BOTH `didNotPlay: false` and `gamesPlayed >= 1`; did-not-play by
    `didNotPlay: true` with no statistics. See the module docstring."""
    entries = feed.game_roster(event_id)
    if entries is None:
        return {"unavailable_reason": REASON_ROSTER_UNAVAILABLE}
    keys = _player_keys(player_name)
    surnames = {key.split()[-1] for key in keys}
    candidates = []
    for entry in entries:
        roster_key = _player_key(entry.get("displayName"))
        if roster_key and roster_key.split()[-1] in surnames:
            candidates.append(entry)
    if len(candidates) > _MAX_ROSTER_NAME_CANDIDATES:
        return {"unavailable_reason": REASON_ROSTER_AMBIGUOUS}

    matched = []
    for entry in candidates:
        names = feed.athlete_names(entry)
        if names is None:
            # An unreadable candidate may be him, so "not on the roster" would
            # be a claim this read cannot make.
            return {"unavailable_reason": REASON_ROSTER_UNAVAILABLE}
        if any(_player_key(name) in keys for name in names):
            matched.append(entry)
    if not matched:
        return {"unavailable_reason": REASON_NOT_ON_GAME_ROSTER}
    if len(matched) > 1:
        return {"unavailable_reason": REASON_ROSTER_AMBIGUOUS}

    entry = matched[0]
    did_not_play = entry.get("didNotPlay")
    has_stats = isinstance(entry.get("statistics"), Mapping)
    if did_not_play is True and not has_stats:
        return {"unavailable_reason": REASON_DNP_VOID}
    if did_not_play is not False or not has_stats:
        return {"unavailable_reason": REASON_PARTICIPATION_UNKNOWN}
    stats = feed.game_stats(entry)
    if stats is None:
        return {"unavailable_reason": REASON_GAME_STATS_UNAVAILABLE}
    games_played = stats.get(_CORE_GAMES_PLAYED)
    if games_played is None or games_played < 1:
        return {"unavailable_reason": REASON_PARTICIPATION_UNKNOWN}

    # ONLY THE FIELDS ESPN STATED. A missing one stays missing, and the caller
    # refuses on it rather than reading it as zero.
    row: dict[str, Any] = {field: stats[key] for key, field in _CORE_STAT_FIELDS.items() if key in stats}
    if "rush_td" in row and "rec_td" in row:
        row["td_scored"] = row["rush_td"] + row["rec_td"]
    return {"played": row}


def _fetch_box(event_id: str) -> list[dict[str, Any]] | None:
    """Every athlete in this game's ESPN box, every field. None means NOT READ.

    A module-level seam so tests can substitute a real captured payload without
    network access. One GET per game per resolver construction -- see the
    resolver's own cache -- and no new periodic task, for the reason
    `_load_games` gives.
    """
    try:
        from syndicate.features.nfl.live_player_box import fetch_player_stat_rows
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None
    return fetch_player_stat_rows(event_id)


def _load_games(selected_date: str) -> list[dict[str, Any]] | None:
    """Every NFL game captured for this date, in play or finished.

    None means "we could not read any live state", which is NOT the same as "no
    games today" -- the caller reports them as different reasons.

    READ THROUGH `refresh_state_store`, the matching half of the poller's
    `write_json_file`. Settlement runs on refresh-worker and Render cannot share
    a disk between services, so a filesystem read here would find nothing in
    production while passing every test on a dev box.

    ONE LAZY CAPTURE ON A MISS, and this is the deliberate part. A resolver
    whose producer runs on some other schedule is inert exactly when it is
    needed -- the failure `model_engine_standard.md` exists to prevent. Rather
    than add a periodic task to a worker with 110 OOM kills on record
    (`worker_periodic_work_never_free` is a standing rule), the capture happens
    at most ONCE per resolver construction, behind a cache, on a 6s timeout
    that already fails soft. A settlement pass over forty NFL orders is one
    scoreboard GET, not forty, and zero when the artifact is already there.
    """
    from syndicate.features.shared.refresh_state_store import read_json_file

    try:
        from scripts.poll_nfl_live_state import live_state_path, poll_nfl_live_state
    except ImportError:  # pragma: no cover - deploy-skew guard
        return None

    record = None
    try:
        record = read_json_file(live_state_path(selected_date))
    except Exception:
        record = None

    if not isinstance(record, Mapping) or not record.get("games"):
        try:
            fetched = poll_nfl_live_state(selected_date)
        except Exception:
            fetched = None
        if isinstance(fetched, Mapping) and fetched.get("status") == "ok":
            record = fetched

    if not isinstance(record, Mapping):
        return None
    games = record.get("games")
    if not isinstance(games, list):
        return None
    return [game for game in games if isinstance(game, Mapping)]


# ESPN FILES A GAME UNDER ITS US-EASTERN DATE. Measured 2026-09-10 on the
# scoreboard's `?dates=`: NE @ SEA, kicking off 2026-09-10T00:20Z, is listed
# under 20260909, and SF @ LAR (2026-09-11T00:35Z, in Melbourne) under 20260910.
# The college scoreboard agrees: FAMU @ MIA, 2026-09-11T00:00Z, under 20260910.
_ESPN_SCHEDULE_TZ = "America/New_York"

# BUT ESPN'S DAY RUNS PAST EASTERN MIDNIGHT. Measured 2026-09-10: New Mexico
# State @ Hawai'i kicks off at 2026-09-13T04:00Z by OddsAPI (00:00 ET, Sunday)
# and 03:59Z by ESPN, which files it under 20260912 (Saturday). The two feeds
# put one game on either side of midnight, and 16 NCAAF orders read
# `game_not_in_ncaaf_live_state` because Sunday's capture could not hold it.
# A kickoff before this Eastern hour is therefore ALSO looked up under the
# previous day, first. No game on either board starts between 00:00 and 06:00
# ET on purpose, so this only ever catches a late West Coast or Hawai'i game.
_ESPN_DAY_ROLLOVER_HOUR = 6


def kickoff_capture_date(commence_time: Any) -> str | None:
    """The ESPN capture date that holds a game kicking off at `commence_time`.

    None when the stamp is absent or unreadable; the caller then falls back to
    the plan date, which is what it always did, never to a guess. A bare date
    is taken as already being the game's date: reading it as midnight UTC would
    move it to the previous Eastern day.

    Public because `bet_status_ncaaf` has the same plan-date lookup and uses it.
    """
    from datetime import date, datetime, timezone
    from zoneinfo import ZoneInfo

    text = str(commence_time or "").strip()
    if not text:
        return None
    if len(text) == 10:
        try:
            return date.fromisoformat(text).isoformat()
        except ValueError:
            return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(ZoneInfo(_ESPN_SCHEDULE_TZ)).date().isoformat()


def kickoff_capture_dates(commence_time: Any) -> list[str]:
    """Every ESPN capture date that can hold this kickoff, most likely first.

    Usually one: the Eastern date. A kickoff before `_ESPN_DAY_ROLLOVER_HOUR`
    Eastern also gets the previous day, and gets it FIRST, because that is the
    day ESPN files it under. [] when the stamp is absent or unreadable.
    """
    from datetime import datetime, timedelta, timezone
    from zoneinfo import ZoneInfo

    day = kickoff_capture_date(commence_time)
    if day is None:
        return []
    text = str(commence_time or "").strip()
    if len(text) == 10:
        # A bare date carries no hour, so there is nothing to roll over.
        return [day]
    moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(ZoneInfo(_ESPN_SCHEDULE_TZ))
    if local.hour < _ESPN_DAY_ROLLOVER_HOUR:
        return [(local.date() - timedelta(days=1)).isoformat(), day]
    return [day]


def order_capture_dates(order: Mapping[str, Any], selected_date: str) -> list[str]:
    """Capture dates to search for this order's game, most likely first.

    The KICKOFF date first, the plan date second. An order carries the PLAN's
    date (`portfolio_commit` stamps `selected_date` on every row), and a plan
    commits games days ahead. Measured 2026-09-10: the one NFL prop order dated
    09-10 read `game_not_in_nfl_live_state` against a 09-10 capture holding only
    SF @ LAR, and 281 NCAAF orders read `game_not_in_ncaaf_live_state` against a
    09-10 capture holding one FBS game. Searching the plan date alone meant a
    Saturday or Sunday bet placed on a Thursday could never find its game, and
    never grade. The plan date stays as the fallback: an order with no readable
    `commence_time` was graded that way before, and still must be.
    """
    dates: list[str] = []
    for capture_date in (*kickoff_capture_dates(order.get("commence_time")), str(selected_date or "").strip()):
        if capture_date and capture_date not in dates:
            dates.append(capture_date)
    return dates


def nfl_status_resolver(selected_date: str):
    """A resolver `paper_settlement` can inject, for NFL orders.

    The live-state read happens ONCE per capture date per resolver, not once per
    order: a slate of forty NFL orders must not mean forty reads of one artifact
    that does not change between them.
    """
    from syndicate.features.shared.game_line_bet import game_line_view, is_game_line_market
    from syndicate.features.shared.team_aliases import teams_match

    cache: dict[str, Any] = {}
    # Settlement-only reads behind a final-box absence. Constructing it reads
    # nothing; every URL is read at most once per resolver.
    feed = EspnSettlementFeed("nfl")

    def games(capture_date: str) -> list[dict[str, Any]] | None:
        # ONE READ PER CAPTURE DATE PER RESOLVER. A Sunday card committed on a
        # Thursday plan is thirteen games on one date: one read, not thirteen.
        slot = f"games:{capture_date}"
        if slot not in cache:
            cache[slot] = _load_games(capture_date)
        return cache[slot]

    def box(event_id: str) -> list[dict[str, Any]] | None:
        # ONCE PER GAME PER RESOLVER, like the live-state read above: a slate of
        # forty prop orders on one game is one ESPN GET, not forty. A failed
        # read is remembered for this pass only and retried on the next.
        slot = f"box:{event_id}"
        if slot not in cache:
            cache[slot] = _fetch_box(event_id)
        return cache[slot]

    def locate(order: Mapping[str, Any]) -> tuple[Mapping[str, Any] | None, str | None]:
        """`(record, None)` or `(None, refusal)`, in the order the refusals
        have always been made: matchup, then capture, then game. The game is
        searched under its KICKOFF date first; see `order_capture_dates`."""
        home_team, away_team = order.get("home_team"), order.get("away_team")
        if not home_team or not away_team:
            # `event_id` is the OddsAPI hash and cannot address an ESPN-keyed
            # capture, so there is no fallback here that would be anything but
            # a guess.
            return None, REASON_NO_MATCHUP
        capture_dates = order_capture_dates(order, selected_date)
        if not capture_dates:
            return None, REASON_NO_LIVE_STATE
        for capture_date in capture_dates:
            for candidate in games(capture_date) or ():
                # BOTH FORMS TRIED. The capture stores the display name and the
                # tri-code; the board may hold either, and `canonical_team`
                # resolves both, so a miss on one is not a miss on the game.
                home_hit = teams_match("nfl", home_team, candidate.get("home_team")) or teams_match(
                    "nfl", home_team, candidate.get("home_abbr")
                )
                away_hit = teams_match("nfl", away_team, candidate.get("away_team")) or teams_match(
                    "nfl", away_team, candidate.get("away_abbr")
                )
                if home_hit and away_hit:
                    return candidate, None
        # THE REFUSAL NAMES THE CAPTURE THAT SHOULD HAVE HELD THE GAME. When the
        # kickoff date's capture could not be read, "not found" in the plan
        # date's is not evidence the game is missing. That is the transient
        # reason, and it must read as one. (Cached: no second read.)
        if games(capture_dates[0]) is None:
            return None, REASON_NO_LIVE_STATE
        return None, REASON_GAME_NOT_FOUND

    def resolve_prop(order: Mapping[str, Any], canonical: str, segment: str) -> dict[str, Any]:
        # PERMANENT REFUSALS FIRST, before any read -- the rule the game-line
        # path below already follows, for the same reason.
        field = prop_field(canonical)
        if field is None:
            return {"unavailable_reason": REASON_PROP_MARKET}
        if segment != FULL_GAME_SEGMENT:
            # ESPN's box is whole-game. A quarter prop graded off it would be
            # graded off the wrong quantity.
            return {"unavailable_reason": REASON_PROP_SEGMENT}

        record, refusal = locate(order)
        if refusal:
            return {"unavailable_reason": refusal}
        is_final = bool(record.get("final"))
        if not (bool(record.get("in_progress")) or is_final):
            # Not unanswerable -- not yet asked.
            return {"current_value": None, "is_final": False, "started": False}
        event_id = str(record.get("event_id") or "").strip()
        if not event_id:
            return {"unavailable_reason": REASON_NO_EVENT_ID}

        # A REMEMBERED ROSTER REFUSAL ends it before ANY read, the box
        # included: an entry exists only for a player already found absent
        # from this game's final box. Final games in the window only.
        memo_key = None
        if is_final and settlement_window_open(record, order):
            memo_key = settlement_memo_key("nfl", event_id, order.get("player_name"))
            remembered = settlement_memo_get(feed, memo_key)
            if remembered is not None:
                return remembered

        rows = box(event_id)
        if rows is None:
            return {"unavailable_reason": REASON_NO_BOX}
        row, why = match_box_player(rows, order.get("player_name"))
        if why == "ambiguous":
            return {"unavailable_reason": REASON_PLAYER_AMBIGUOUS}
        if row is not None:
            return prop_view(row, field, order, is_final=is_final)
        if not is_final:
            return {"unavailable_reason": REASON_PLAYER_NOT_IN_BOX_YET}

        # ABSENT FROM A FINAL BOX: inactive, or active with nothing to record.
        # Only the game roster can tell them apart, and it is read only once
        # the game is safely in the settlement window (see the docstring).
        if memo_key is None:
            return {"unavailable_reason": REASON_PLAYER_NOT_IN_BOX}
        try:
            found = roster_participation(feed, event_id, order.get("player_name"))
        except Exception:  # never raise into the settlement loop
            found = {"unavailable_reason": REASON_PARTICIPATION_READ_FAILED}
        line = found.get("played")
        if line is None:
            refusal = {"unavailable_reason": found.get("unavailable_reason") or REASON_PARTICIPATION_UNKNOWN}
            reason = refusal["unavailable_reason"]
            if reason in _DEFINITIVE_ROSTER_REFUSALS or reason in _READ_FAILURE_ROSTER_REFUSALS:
                settlement_memo_put(feed, memo_key, refusal, definitive=reason in _DEFINITIVE_ROSTER_REFUSALS)
            return refusal
        if field not in line:
            # He played, but ESPN did not state THIS number. Not a zero.
            return {"unavailable_reason": REASON_STAT_NOT_IN_GAME_STATS}
        resolved = prop_view(line, field, order, is_final=True)
        resolved["value_source"] = VALUE_SOURCE_CORE_GAME_STATS
        return resolved

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if _norm(order.get("sport")) != "nfl":
            # This resolver is handed every order; a non-NFL one is not a
            # defect in anything and must not be reported as an NFL failure.
            return {"unavailable_reason": REASON_NOT_NFL}

        # SEGMENT BEFORE MARKET -- the more permanent of the two. A segment
        # this sport does not play (`first5` on an NFL order) is a join defect
        # that no capture will ever answer, so it refuses here BY NAME. A
        # segment it does play (`q1..q4`, `h1`, `h2`) is graded below off the
        # poller's per-period linescores -- and refuses by name when a record
        # lacks them, never off the whole-game score (`segment_actuals`).
        # Absent or `full` means the whole game, the one permissive default,
        # for the reason `bet_status.segment_refusal` states.
        segment = order_segment(order)
        if segment != FULL_GAME_SEGMENT and segment_periods("nfl", segment) is None:
            return {"unavailable_reason": f"{REASON_UNSUPPORTED_SEGMENT_PREFIX}{segment}"}

        # THE MARKET CHECK COMES FIRST, before the artifact read: "we cannot
        # grade this market" is permanent, "the capture is not there yet" is
        # transient, and checking the transient one first hides the structural
        # one behind a reason that looks like it will fix itself.
        market = order.get("market")
        canonical = _norm(market)
        # ORDER MATTERS. `team_totals` must be caught BEFORE the combined-total
        # test, or a permissive match would swallow it and grade one team's
        # points against the whole scoreline.
        if canonical in _TEAM_TOTAL_MARKETS:
            return {"unavailable_reason": REASON_TEAM_TOTAL}
        if order.get("player_name"):
            # A PLAYER PROP, graded off ESPN's per-player box. Routed before the
            # game-line test, so a prop is never reported as an unmapped game
            # market.
            return resolve_prop(order, canonical, segment)
        is_total = canonical in _GAME_TOTAL_MARKETS
        is_line = is_game_line_market("nfl", market)
        if not (is_total or is_line):
            return {"unavailable_reason": REASON_UNKNOWN_MARKET}

        home_team, away_team = order.get("home_team"), order.get("away_team")
        record, refusal = locate(order)
        if refusal:
            return {"unavailable_reason": refusal}

        if segment == FULL_GAME_SEGMENT:
            home = _as_float(record.get("home_score"))
            away = _as_float(record.get("away_score"))
            is_final = bool(record.get("final"))
            started = bool(record.get("in_progress")) or is_final
            if not started:
                # NOT STARTED, NOT A REFUSAL. A game that has not kicked off
                # has no score by definition, and reporting that as a missing
                # score put 289 pregame rows on the refusal counter on
                # 2026-09-10 (`no_team_scores` + `..._carries_no_scores`), while
                # props and segments on the same games already read
                # not-started. The capture's `None` pregame scores still can
                # never settle a total as an under: nothing grades until the
                # game has started.
                return {"current_value": None, "is_final": False, "started": False}
        else:
            # THE SEGMENT'S OWN SCORE PAIR, or a named refusal. `is_final` is
            # the SEGMENT's: a first-half total is decided at the half, not at
            # the final whistle, and `h2` (overtime included) only with the
            # game. A segment that has not begun yet reports `started=False`
            # rather than a refusal -- not unanswerable, not yet asked.
            actual = segment_actuals("nfl", segment, record)
            if actual.get("unavailable_reason"):
                return actual
            if not actual.get("started"):
                return {"current_value": None, "is_final": False, "started": False}
            home = _as_float(actual.get("home_score"))
            away = _as_float(actual.get("away_score"))
            is_final = bool(actual.get("is_final"))
            started = True

        if is_total:
            # NO TRANSLATION. The order already carries `side="over"` and a
            # numeric line, so the grader needs only the combined points --
            # exactly what `bet_status_mlb._combined_score` hands it. Routing a
            # total through `game_line_view` is what produced soccer's
            # `unmapped_market` count, because `is_game_line_market` is False
            # for totals BY DESIGN: it is the spread-and-moneyline test.
            if home is None or away is None:
                # A half-known score is not a score. Refusing both together
                # stops a missing away total reading as a shutout.
                return {"unavailable_reason": REASON_NO_SCORES}
            return {
                "current_value": home + away,
                "is_final": is_final,
                "started": True,
            }

        view = game_line_view(
            sport="nfl",
            market=market,
            side=order.get("side"),
            line=order.get("line"),
            home_team=home_team,
            away_team=away_team,
            home_score=home,
            away_score=away,
            # See the module docstring. A level NFL moneyline is a PUSH, not a
            # loss, and that is what False encodes -- for a quarter or a half
            # exactly as for the game. `h2h_3_way` is graded three-way off the
            # market name regardless.
            draw_possible=False,
        )
        if "unavailable_reason" in view:
            return view
        view["is_final"] = is_final
        view["started"] = started
        return view

    return resolve
