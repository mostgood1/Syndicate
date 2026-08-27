"""Resolve a WNBA bet's CURRENT value from the live player box score.

The sibling of `bet_status_mlb`, and deliberately the same shape: it answers
"what is the thing this bet is on worth right now" and leaves every judgement
about winning and losing to `resolve_bet_status`.

--------------------------------------------------------------------------
KEYED ON `event_id`, WHICH SIDESTEPS MLB'S WHOLE PROBLEM
--------------------------------------------------------------------------

MLB cost a day because the board stamps `game_pk` from `row["event_id"]` -- the
OddsAPI hash -- while StatsAPI wants a numeric gamePk, and `int()` cannot parse
a hash. Every MLB order resolved to `no_game_pk`.

WNBA WAS BELIEVED TO HAVE NO SUCH GAP. IT HAS THE IDENTICAL ONE, AND THIS
PARAGRAPH USED TO SAY OTHERWISE: "the id on the record is the id in the
artifact". MEASURED IN PRODUCTION 2026-08-26 -- WNBA had settled ZERO orders
all-time while MLB had settled 157, and the refusal was `game_not_in_live_box`
on every one:

    order   event_id "1fb615886a5e9855f01b8c3824e8d937"  (the OddsAPI board hash)
    box     event_id "WSH@PHX"                           (2026-08-25)
    box     event_id "401857177"                         (2026-08-26, ESPN)

`_public_live_player_boxscore_payload` echoes back whatever event id its CALLER
passed, and that caller works in ESPN ids. The board hash is never among them,
so the two namespaces cannot meet and the lookup could never hit. The old claim
was an assumption written as a fact and never measured; the fixture that
'proved' it set both ids to the same string.

So this now does what `bet_status_mlb` does: try the id, then RECOVER FROM THE
MATCHUP. The recovery key is the WNBA tri-code pair, because the players in the
box already carry a canonical `team_tri` and `team_aliases.canonical_team`
deliberately refuses the tri-codes WNBA shares with the NBA (PHX, CHI and DAL
all return None) -- which is precisely the game this was failing on.

--------------------------------------------------------------------------
NO FINAL FLAG IN THIS ARTIFACT, AND THAT IS STATED RATHER THAN GUESSED
--------------------------------------------------------------------------

The capture stores what `/wnba/api/live_player_boxscore` returns: minutes,
points, rebounds, assists, threes. **There is no game-status field.** So this
resolver reports `is_final=False` ALWAYS, and never claims a game has ended.

That is not a shrug -- it is exactly right for the bets in question, because it
loses nothing on the OVER side. Points, rebounds, assists and threes are
counting stats, so `bet_status.is_monotone_market` returns True for all of them
and an over DECIDES the instant it crosses its line, final flag or not. What it
costs is the under side: an under cannot be settled until the game is known to
be over, so it stays `live_ahead` rather than grading.

Claiming a game was final on a guess would be the opposite trade: it would
settle unders early, and an under graded at halftime is a confident wrong
answer on a bet that was still live. Waiting is recoverable; that is not.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = ["wnba_status_resolver"]

REASON_NO_EVENT_ID = "no_event_id"
REASON_NO_BOX = "no_live_box_for_date"
REASON_GAME_NOT_IN_BOX = "game_not_in_live_box"
# The market IS gradeable in principle -- `game_line_bet` handles spreads and
# moneylines for any sport that can supply two team scores. This capture is a
# PLAYER box and has none, so the fix is upstream in the capture rather than a
# missing entry in a table here.
REASON_NO_TEAM_SCORES = "no_team_scores_in_player_box"
REASON_UNMAPPED_MARKET = "unmapped_market"
REASON_PLAYER_NOT_FOUND = "player_not_in_box"
REASON_NO_STAT = "stat_not_in_box"
# The box has no row under the order's event id AND the order carries no teams
# to recover from. Distinct from `game_not_in_live_box`, which now means "we
# tried the matchup too and the game genuinely is not in the capture" -- the
# same split `bet_status_mlb` draws between `no_matchup_on_order` and
# `matchup_not_on_schedule`.
REASON_NO_MATCHUP_ON_ORDER = "no_matchup_on_order"

# Canonical board market -> the key the live box row carries.
# Canonical because `market_keys` owns that vocabulary (`#224`); the RAW board
# name is canonicalised on the way in, so both spellings resolve. Four separate
# market tables drifted apart in this codebase on 2026-08-23 and every one of
# them was a private list exactly like this one would have been.
_MARKET_TO_BOX_KEY: dict[str, str] = {
    "player_points": "pts",
    "player_rebounds": "reb",
    "player_assists": "ast",
    "player_threes": "threes_made",
}

# Combination markets the box does not carry directly but can SUM. Listed
# explicitly rather than parsed out of the market name: `player_points_rebounds`
# and `player_points_rebounds_assists` differ by one token and a prefix rule
# would price one as the other.
# THE SAME STATS IN THE FINAL BOXSCORE'S SPELLING. `boxscores_<date>.csv` is
# written by `scripts/build_wnba_boxscores.py` from ESPN's official box AFTER a
# game is complete, so unlike the live capture it carries a value that will not
# change again -- which is the whole reason settlement can trust it as final.
#
# A SEPARATE TABLE RATHER THAN A RENAME, because the two artifacts genuinely
# spell these differently (`threes_made` vs `FG3M`) and folding them would make
# a future divergence silent.
_BOX_KEY_TO_CSV: dict[str, str] = {
    "pts": "PTS",
    "reb": "REB",
    "ast": "AST",
    "threes_made": "FG3M",
    "mp": "MIN",
}


_MARKET_TO_BOX_SUM: dict[str, tuple[str, ...]] = {
    "player_points_rebounds": ("pts", "reb"),
    "player_points_assists": ("pts", "ast"),
    "player_rebounds_assists": ("reb", "ast"),
    "player_points_rebounds_assists": ("pts", "reb", "ast"),
}


def _as_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return None if parsed != parsed else parsed


def _canonical(market: Any) -> str:
    from syndicate.features.shared.market_keys import canonical_market_key

    raw = str(market or "").strip().lower()
    return canonical_market_key("wnba", raw) or raw


def wnba_status_resolver(selected_date: str):
    """A resolver `bet_status`/`paper_settlement` can inject, for WNBA orders.

    The box is read ONCE per resolver, not once per order: a slate of forty
    orders must not mean forty reads of one unchanging artifact.
    """
    from syndicate.features.shared.game_line_bet import is_game_line_market
    from syndicate.features.shared.wnba_live_prop_rows import normalize_name

    cache: dict[str, Any] = {}

    def box_index() -> dict[str, dict[str, Mapping[str, Any]]] | None:
        if "index" in cache:
            return cache["index"]
        cache["index"] = _load_box_index(selected_date, normalize_name)
        return cache["index"]

    def final_box():
        # Read ONCE per resolver, same rule as the live box: a slate of forty
        # orders must not mean forty reads of one unchanging artifact.
        if "final" in cache:
            return cache["final"]
        cache["final"] = _load_final_box(selected_date, normalize_name)
        return cache["final"]

    def resolve(order: Mapping[str, Any]) -> dict[str, Any]:
        if str(order.get("sport") or "").strip().lower() != "wnba":
            # This resolver is handed every order; a non-WNBA one is not a
            # defect in anything and must not be reported as a WNBA failure.
            return {"unavailable_reason": f"not_a_wnba_order"}

        # THE MARKET CHECK COMES FIRST, before the artifact read. "We have no
        # box key for this market" is permanent; "the box is not captured yet"
        # is temporary, and checking the transient one first hides the
        # structural one -- measured on the MLB grader this morning, where
        # `no_live_feed: 50` concealed 40 orders that could never grade.
        market = _canonical(order.get("market"))
        box_key = _MARKET_TO_BOX_KEY.get(market)
        sum_keys = _MARKET_TO_BOX_SUM.get(market)
        if box_key is None and sum_keys is None:
            # A GAME LINE IS NOT AN UNMAPPED PROP, and lumping the two together
            # is what made this invisible. `game_line_bet` can grade spreads
            # and moneylines for any sport that supplies two team scores; this
            # artifact is a PLAYER box and carries none, so the blocker is the
            # capture, not the vocabulary.
            #
            # MLB gained game-line grading on 2026-08-24; WNBA did not, and
            # this reason is the difference between "add four market names"
            # (wrong, and would have been tried) and "the box needs team
            # scores in it" (right). Reported honestly rather than made to
            # look like the same fix.
            if is_game_line_market("wnba", market):
                return {"unavailable_reason": REASON_NO_TEAM_SCORES}
            return {"unavailable_reason": REASON_UNMAPPED_MARKET}

        event_id = str(order.get("event_id") or "").strip()
        if not event_id:
            return {"unavailable_reason": REASON_NO_EVENT_ID}

        # THE FINAL BOXSCORE FIRST, because it is the only reading that can be
        # DECIDED. It exists only for completed games, so a hit here means the
        # game is over and the value will not change again -- which is what lets
        # a losing over settle instead of waiting forever.
        finals = final_box()
        if finals is not None:
            row = finals.get(normalize_name(order.get("player_name")))
            if row is not None:
                if sum_keys is not None:
                    parts = [row.get(key) for key in sum_keys]
                    if any(part is None for part in parts):
                        # A partial sum is a smaller number that looks real.
                        return {"unavailable_reason": REASON_NO_STAT}
                    value = sum(parts)
                else:
                    value = row.get(box_key)
                    if value is None:
                        return {"unavailable_reason": REASON_NO_STAT}
                return {
                    "matched_by": "final_boxscore",
                    "current_value": value,
                    # THE POINT OF ALL OF THIS.
                    "is_final": True,
                    "started": True,
                }
            # The player is not in the final box. FALLS THROUGH to the live box
            # rather than refusing: a box for the date can exist while an
            # earlier game of a doubleheader is still being written, and a DNP
            # is deliberately absent rather than zeroed.

        index = box_index()
        if index is None:
            return {"unavailable_reason": REASON_NO_BOX}
        players = index["by_event"].get(event_id)
        recovered = False
        if players is None:
            # THE ID MISSING IS THE NORMAL CASE, NOT AN ERROR: the order carries
            # the board's OddsAPI hash and the box carries an ESPN id. Recover
            # from the matchup, exactly as MLB does.
            key_pair = _matchup_key(order.get("away_team"), order.get("home_team"))
            if key_pair is None:
                # The ledger row is too thin to recover from -- a different fact
                # from "the game is not in the capture", and the two must not
                # share a counter or the work list points at the wrong job.
                return {"unavailable_reason": REASON_NO_MATCHUP_ON_ORDER}
            players = index["by_matchup"].get(key_pair)
            if players is None:
                return {"unavailable_reason": REASON_GAME_NOT_IN_BOX}
            recovered = True

        row = players.get(normalize_name(order.get("player_name")))
        if row is None:
            # The player is not in this game's box, OR the name did not match.
            # Named rather than defaulted to 0: a bet reported as "0 points,
            # Under is fine" when we simply failed to find her is the worst
            # possible wrong answer, and it is the one `bet_status_mlb` calls
            # out for the same reason.
            return {"unavailable_reason": REASON_PLAYER_NOT_FOUND}

        if sum_keys is not None:
            parts = [_as_float(row.get(key)) for key in sum_keys]
            if any(part is None for part in parts):
                # A partial sum is a smaller number that looks like a real one.
                return {"unavailable_reason": REASON_NO_STAT}
            value = sum(parts)
        else:
            value = _as_float(row.get(box_key))
            if value is None:
                return {"unavailable_reason": REASON_NO_STAT}

        return {
            # How the game was found. A recovery that is invisible is a recovery
            # nobody can audit on the day it joins the wrong game.
            "matched_by": "matchup" if recovered else "event_id",
            "current_value": value,
            # ALWAYS False -- this artifact carries no game status. See the
            # module docstring: overs still decide on crossing because these are
            # counting stats, and unders wait rather than being settled on a
            # guess about whether the game ended.
            "is_final": False,
            "started": True,
        }

    return resolve




def _load_final_box(selected_date: str, normalize_name):
    """`normalized player name -> {stat -> float}` from the FINAL boxscore, or None.

    THE FINAL FLAG THIS MODULE NEVER HAD. The live player box carries no game
    status, so `is_final` was hardcoded False and `resolve_bet_status` decides
    only on `is_final` OR the value crossing its line. An over that falls short
    therefore NEVER decided, and ONLY WINNING OVERS SETTLED.

    MEASURED 2026-08-25 against ESPN: Sonia Citron 1 rebound against over 3.5
    and Georgia Amoore 3 assists against over 3.5 are losses that could never be
    recorded, while Natasha Mack's over 7.5 (8 rebounds) graded within minutes.
    A win rate computed over that is 100% by construction.

    `build_wnba_boxscores` writes ONLY completed games, so a player's presence
    here IS the assertion that their game is over. None means no final box for
    the date -- NOT that the game is unfinished, which is why the caller falls
    back to the live box rather than refusing.
    """
    import csv as _csv
    import io as _io

    from syndicate.features.shared.refresh_state_store import data_root, read_text_file

    try:
        raw = read_text_file(
            data_root() / f"wnba_source/data/processed/boxscores_{selected_date}.csv"
        )
    except Exception:
        return None
    if not raw:
        return None
    try:
        rows = list(_csv.DictReader(_io.StringIO(str(raw))))
    except Exception:
        return None

    index: dict[str, dict[str, float]] = {}
    for row in rows:
        key = normalize_name(row.get("PLAYER_NAME"))
        if not key:
            continue
        stats: dict[str, float] = {}
        for box_key, column in _BOX_KEY_TO_CSV.items():
            value = _as_float(row.get(column))
            if value is not None:
                stats[box_key] = value
        if stats:
            index[key] = stats
    return index or None


def _wnba_tri(value):
    """A WNBA tri-code for a team name, or None.

    `wnba/cards.py` owns this vocabulary and already maps full names onto the
    same codes the box's `team_tri` carries. Imported rather than restated: a
    second table here is how two spellings drift, and `bet_status_mlb` reaches
    into `mlb/cards.py` for `_schedule_raw_games` for exactly the same reason.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        from syndicate.features.wnba.cards import _canonical_wnba_tri
    except Exception:
        return None
    try:
        tri = _canonical_wnba_tri(text)
    except Exception:
        return None
    tri = str(tri or "").strip().upper()
    return tri or None


def _matchup_key(one, two):
    """An order-independent key for the two clubs in a game.

    A frozenset, not a tuple: home/away is exactly the convention most likely to
    be written the other way round on one of the two sides, and a swapped pair
    that silently fails to join is indistinguishable from an absent game.
    """
    left, right = _wnba_tri(one), _wnba_tri(two)
    if not left or not right or left == right:
        return None
    return frozenset((left, right))

def _load_box_index(selected_date: str, normalize_name) -> dict[str, dict[str, Mapping[str, Any]]] | None:
    """Both indexes over the box, or None if unreadable.

    `{"by_event": {event_id: {player -> row}},
      "by_matchup": {frozenset(tri, tri): {player -> row}}}`

    None means "we could not read the box", which is NOT the same as a box with
    no games in it -- the caller reports them as different reasons.
    """
    from syndicate.features.shared.refresh_state_store import data_root, read_json_file

    try:
        record = read_json_file(
            data_root() / f"wnba_source/data/live/live_player_box_{selected_date}.json"
        )
    except Exception:
        return None
    if not isinstance(record, Mapping):
        return None
    payload = record.get("payload") if isinstance(record.get("payload"), Mapping) else record

    index: dict[str, dict[str, Mapping[str, Any]]] = {}
    by_matchup: dict[Any, dict[str, Mapping[str, Any]]] = {}
    for game in payload.get("games") or []:
        if not isinstance(game, Mapping):
            continue
        event_id = str(game.get("event_id") or "").strip()
        if not event_id:
            continue
        players: dict[str, Mapping[str, Any]] = {}
        tris: set[str] = set()
        for player in game.get("players") or []:
            if not isinstance(player, Mapping):
                continue
            key = normalize_name(player.get("player") or player.get("player_name"))
            if key:
                players[key] = player
            tri = str(player.get("team_tri") or "").strip().upper()
            if tri:
                tris.add(tri)
        index[event_id] = players

        # THE MATCHUP, from the two clubs actually present in the box. Taken
        # from the PLAYERS because that is the only place this artifact records
        # a team at all -- the game object carries an id and a player list and
        # nothing else. An `AAA@BBB` event id is a second source, since the
        # live-lens path emits that shape on some dates and bare ESPN ids on
        # others.
        if len(tris) != 2 and "@" in event_id:
            parts = [part.strip() for part in event_id.split("@", 1)]
            if len(parts) == 2 and all(parts):
                tris = {t for t in (_wnba_tri(parts[0]), _wnba_tri(parts[1])) if t}
        if len(tris) == 2:
            # A DOUBLEHEADER WOULD COLLIDE HERE, so the first game wins and the
            # second keeps only its event id rather than overwriting. Recovering
            # the WRONG game of a pair grades a bet against the wrong score,
            # which is worse than not grading it.
            by_matchup.setdefault(frozenset(tris), players)
    return {"by_event": index, "by_matchup": by_matchup}
