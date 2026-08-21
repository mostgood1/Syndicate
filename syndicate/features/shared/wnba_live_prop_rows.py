"""Join the live per-player capture to its pregame sim anchor, per stat.

PHASE 3(a) of live WNBA props, and the shape of it is a recorded user decision
`[2026-08-21]`. Phase 1 persists the live lines; phase 2 projects one stat from
one line; this pairs each live player with their pregame anchor and emits a row
per stat.

**IT NOW EMITS `liveModelProbOver`, AND ONLY BECAUSE THE ERROR WAS MEASURED.**
Phase 3(a) deliberately published a projection and no probability, because the
live remainder distribution was unmeasured and a probability off an unmeasured
estimator is the same act as pricing the un-backtested totals transform this
board refuses by name. Phase 3(b) removed that objection the honest way:
`scripts/grade_wnba_live_prop_projection.py` replayed ESPN play-by-play, drove
the SHIPPED projection at every scoring play and scored it against the official
final -- n=796 over 5 slates, the replay reconciling 100% against the official
boxscore on every one. `wnba_live_prop_probability` turns that measurement into
`P(final >= line)`; see it for the bucketed sigma and the three choices behind
it.

A ROW IS PRICED ONLY WHEN A LINE IS SUPPLIED for its `(player, market)`. A
probability needs something to be a probability ABOUT, and inventing a line
would price a market nobody quoted. Rows without one still carry
`liveProjectedStat` and say why they are unpriced.

THIS DOES NOT OPEN THE JOIN'S GATE. `attach_live_projections_for_sport` still
returns early on `sport != "mlb"`; that is phase 4 and a separate decision.
Emitting the field makes these rows ELIGIBLE, and the join's own
`prob_std_err`/`PRICEABLE_SIGMA` refusal still applies on top exactly as it does
for MLB.

MATCHING IS BY NAME, AND THE MISSES ARE COUNTED. The live capture carries
`player` + `team_tri`; the sim carries `player_name` under `sim.players.{home,
away}`. There is no shared id, so this normalises and joins on the name. That is
the same machinery whose 91% miss rate the prop join records
(`miss_no_market_alias` 903 of 989), so the counters here are deliberate: a
silent zero and a zero with a named cause need different fixes, and the first
has already cost this project a full investigation.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Iterable, Mapping

from syndicate.features.shared.wnba_live_prop_probability import live_prop_prob_over
from syndicate.features.shared.wnba_live_prop_projection import project_live_player_stat

# (live-capture key, sim mean key, market label). Declared rather than derived:
# the capture and the sim use different vocabularies for the same stat
# (`threes_made` vs `threes_mean`), and a loop that guessed the mapping would
# silently drop whichever side it guessed wrong.
STAT_MAP: tuple[tuple[str, str, str], ...] = (
    ("pts", "pts_mean", "points"),
    ("reb", "reb_mean", "rebounds"),
    ("ast", "ast_mean", "assists"),
    ("threes_made", "threes_mean", "threes"),
)

# AN APOSTROPHE IS INTRA-WORD; A HYPHEN SEPARATES WORDS. They cannot share a
# rule. Caught by this module's own test: substituting a space for BOTH turned
# `A'ja Wilson` into `a ja wilson`, which matches nothing -- the player would
# have been silently absent from the board, which is exactly the name-join
# failure this file's counters exist to make visible. Apostrophes (straight and
# typographic) are DELETED; everything else non-alphanumeric becomes a space.
_APOSTROPHE = re.compile(r"['‘’ʼ]+")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalize_name(value: Any) -> str:
    """Fold accents, drop punctuation, collapse spaces.

    Names arrive from two independent feeds. `A'ja Wilson` and `Aja Wilson`,
    `Nelson-Ododa` and `Nelson Ododa` must land on the same key or the player
    is simply absent from the board with no reason attached.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = _APOSTROPHE.sub("", text.lower())
    text = _PUNCT.sub(" ", text.replace("-", " "))
    return " ".join(text.split())


def index_sim_players(sim_game: Any) -> dict[str, dict[str, Any]]:
    """`normalized name -> sim row`, across both sides of one game."""
    out: dict[str, dict[str, Any]] = {}
    if not isinstance(sim_game, Mapping):
        return out
    players = sim_game.get("players")
    if not isinstance(players, Mapping):
        return out
    for side in ("home", "away"):
        rows = players.get(side)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            key = normalize_name(row.get("player_name"))
            if key and key not in out:
                out[key] = dict(row)
    return out


def build_live_prop_rows(
    live_players: Iterable[Mapping[str, Any]],
    sim_game: Any,
    *,
    game_minutes_remaining: Any = None,
    lines: Mapping[tuple[str, str], Any] | None = None,
) -> dict[str, Any]:
    """One row per (player, stat), plus the counters that make a zero readable."""
    sim_index = index_sim_players(sim_game)
    rows: list[dict[str, Any]] = []
    players_seen = 0
    players_matched = 0
    players_unmatched: list[str] = []
    projected = 0
    priced_rows = 0
    withheld_by_reason: dict[str, int] = {}
    unpriced_by_reason: dict[str, int] = {}

    for player in live_players or ():
        if not isinstance(player, Mapping):
            continue
        players_seen += 1
        name = player.get("player")
        anchor = sim_index.get(normalize_name(name))
        if anchor is None:
            # NAMED, not dropped. An unmatched player is the failure mode this
            # join family has already paid for once.
            players_unmatched.append(str(name))
            continue
        players_matched += 1
        for live_key, mean_key, market in STAT_MAP:
            verdict = project_live_player_stat(
                current_stat=player.get(live_key),
                minutes_played=player.get("mp"),
                pregame_stat=anchor.get(mean_key),
                pregame_minutes=anchor.get("min_mean"),
                game_minutes_remaining=game_minutes_remaining,
            )
            row = {
                "player": name,
                "team_tri": player.get("team_tri"),
                "market": market,
                "current": verdict.get("current"),
                "minutes_played": verdict.get("minutes_played"),
                "minutes_remaining": verdict.get("minutes_remaining"),
                "pregame_mean": anchor.get(mean_key),
                "pregame_minutes": anchor.get("min_mean"),
                "liveProjectedStat": verdict.get("projected"),
                "basis": verdict.get("basis"),
                "unavailable_reason": verdict.get("unavailable_reason"),
            }
            # PHASE 3(b): the probability the prop join keys on, from the
            # MEASURED residual (see `wnba_live_prop_probability`). Emitted ONLY
            # when a line is supplied for this (player, market) -- a probability
            # needs something to be a probability ABOUT, and inventing a line
            # would price a market nobody quoted.
            line = None
            if lines:
                line = lines.get((normalize_name(name), market))
            priced = live_prop_prob_over(
                projected=row["liveProjectedStat"],
                line=line,
                minutes_remaining=verdict.get("minutes_remaining"),
            )
            row["line"] = line
            row["residual_sigma"] = priced.get("residual_sigma")
            if priced.get("prob_over") is None:
                row["liveModelProbOver"] = None
                row["not_priced_reason"] = priced.get("unavailable_reason")
            else:
                row["liveModelProbOver"] = priced["prob_over"]
                row["not_priced_reason"] = None
            if row["liveProjectedStat"] is None:
                reason = str(verdict.get("unavailable_reason") or "unknown")
                withheld_by_reason[reason] = withheld_by_reason.get(reason, 0) + 1
            else:
                projected += 1
            if row.get("liveModelProbOver") is not None:
                priced_rows += 1
            elif row["liveProjectedStat"] is not None:
                reason = str(row.get("not_priced_reason") or "unknown")
                unpriced_by_reason[reason] = unpriced_by_reason.get(reason, 0) + 1
            rows.append(row)

    return {
        "rows": rows,
        "players_seen": players_seen,
        "players_matched": players_matched,
        "players_unmatched": players_unmatched,
        "rows_projected": projected,
        "withheld_by_reason": withheld_by_reason,
        "priced": priced_rows,
        "unpriced_by_reason": unpriced_by_reason,
    }
