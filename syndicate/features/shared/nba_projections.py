"""NBA PLAYER-PROP projections for the Layer 2 board `[2026-10-03, lane nba-layer2-projections]`.

Same contract as `wnba_projections` -- the probability comes ONLY from the
SmartSim's own empirical `hitProb` ladder, never from a mean plus an assumed
shape -- with one difference in where the MEAN is read, measured rather than
assumed:

    fleet 2026-10-04, 72 of 72 sim players:
        props_predictions_<d>.csv  mean_pts
     == cards_sim_detail_<d>.json  players[side][i].pts_mean
     == the same row's prop_ladders.pts.mean

`props_recommendations_<d>.csv`'s `model` block is built from those same
`mean_*` columns (`basketball_props_recommendations._build_model_map`), so it is
a COPY of the sim mean, and it is not written at all on a date with no prop
lines (the producer skips the export). `cards_sim_detail` is therefore the one
source for both numbers: the mean and the probability come from the same
500-draw distribution and can never disagree in direction. When the model is
fixed upstream (minutes bias, dispersion -- `findings_2026-10-02_nba_lines_props
_backtest.md`), the ladder changes and this join carries it with no edit.

EVERY LINE IS ITS OWN DECISION (user, 2026-10-02). No market-level withhold. A
line is refused only on its own facts, and each refusal is counted by reason:
  - the player is not in this game's sim (`missing_prop_players`, or absent);
  - the sim's game for that player is not this row's game;
  - the row has no line (no context);
  - double-double / triple-double: the sim publishes per-stat marginals, not
    the joint draws those need -- stated, not guessed from a mean;
  - in-play rows keep the projection and lose the edge (live-edge policy);
  - every draw on one side of the line (`refuse_published_certainty`).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from syndicate.features.shared.live_edge_policy import live_edge_unavailable_reason
from syndicate.features.shared.nba_game_projections import (
    NbaGameProjectionIndex,
    nba_processed_file,
    window_dates,
)
from syndicate.features.shared.probability_refusal import refuse_published_certainty
from syndicate.features.shared.nba_prop_calibration import served_prop_probability
from syndicate.features.shared.prop_projections import _no_vig_over_probability, _norm_name
from syndicate.features.shared.timezone import central_date_from_iso
from syndicate.features.shared.wnba_game_projections import _attach_sim_probability_edge
from syndicate.features.shared.wnba_projections import (
    _MARKET_TO_MODEL_KEY,
    _UNSUPPORTED_MARKETS,
    _hit_prob_over,
)

SOURCE = "nba_smart_sim_ladder"
_JOINT_STAT_REASON = (
    "the NBA sim publishes per-stat marginal ladders, not the joint draws a "
    "double-double/triple-double probability needs"
)


@dataclass
class NbaPlayerEntry:
    slate_date: str
    home_tri: str
    away_tri: str
    side: str
    player_name: str
    player_id: str
    ladders: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    means: dict[str, float] = field(default_factory=dict)
    sim_draws: Any = None


@dataclass
class NbaPropProjectionIndex:
    by_player: dict[str, list[NbaPlayerEntry]] = field(default_factory=dict)
    #: (slate_date, home_tri, away_tri) -> normalised names the sim dropped
    missing: dict[tuple[str, str, str], set[str]] = field(default_factory=dict)
    games: NbaGameProjectionIndex = field(default_factory=NbaGameProjectionIndex)
    source_files: list[str] = field(default_factory=list)

    @property
    def players(self) -> int:
        return len(self.by_player)


def _float(value: Any) -> float | None:
    try:
        return None if value is None or str(value).strip() == "" else float(value)
    except (TypeError, ValueError):
        return None


def load_nba_prop_projections(
    selected_date: str, games: NbaGameProjectionIndex | None = None
) -> NbaPropProjectionIndex:
    """Index every sim player in `cards_sim_detail_<d>.json` over D-1..D+1.

    Keyed by normalised NAME (accent-folded, `prop_projections._norm_name`),
    because a book's prop row carries a name and nothing else. The sim's
    `player_id` (NBA stats ids, e.g. 202685) and `game_cards.game_id` (ESPN
    ids, e.g. 401914127) are never used to join -- neither appears on a board
    row, and OddsAPI's `event_id` is a third id space. Each entry keeps its game
    (slate date + tri-codes) so a name collision across games is resolved by the
    ROW's teams, and refused when it cannot be.
    """
    index = NbaPropProjectionIndex(games=games if games is not None else NbaGameProjectionIndex())
    for slate_date in window_dates(selected_date):
        path = nba_processed_file(f"cards_sim_detail_{slate_date}.json")
        if path is None:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        index.source_files.append(str(path))
        game_list = payload.get("games") if isinstance(payload, Mapping) else None
        if isinstance(game_list, Mapping):
            game_list = list(game_list.values())
        for game in game_list or []:
            if not isinstance(game, Mapping):
                continue
            home_tri = str(game.get("home_tri") or "").strip().upper()
            away_tri = str(game.get("away_tri") or "").strip().upper()
            sim = game.get("sim") if isinstance(game.get("sim"), Mapping) else {}
            missing = sim.get("missing_prop_players") if isinstance(sim.get("missing_prop_players"), Mapping) else {}
            dropped = {
                _norm_name(name)
                for side_names in missing.values()
                if isinstance(side_names, list)
                for name in side_names
                if name
            }
            if dropped:
                index.missing[(slate_date, home_tri, away_tri)] = dropped
            players = sim.get("players") if isinstance(sim.get("players"), Mapping) else {}
            for side in ("home", "away"):
                for player in players.get(side) or []:
                    if not isinstance(player, Mapping) or not player.get("player_name"):
                        continue
                    entry = NbaPlayerEntry(
                        slate_date=slate_date,
                        home_tri=home_tri,
                        away_tri=away_tri,
                        side=side,
                        player_name=str(player.get("player_name")),
                        player_id=str(player.get("player_id") or ""),
                    )
                    ladders = player.get("prop_ladders") if isinstance(player.get("prop_ladders"), Mapping) else {}
                    for stat, block in ladders.items():
                        if not isinstance(block, Mapping) or not isinstance(block.get("ladder"), list) or not block["ladder"]:
                            continue
                        key = str(stat).strip().lower()
                        entry.ladders[key] = block["ladder"]
                        mean = _float(block.get("mean"))
                        if mean is None:
                            mean = _float(player.get(f"{key}_mean"))
                        if mean is not None:
                            entry.means[key] = mean
                        if entry.sim_draws is None:
                            entry.sim_draws = block.get("simCount")
                    bucket = index.by_player.setdefault(_norm_name(entry.player_name), [])
                    # A re-read of the same game (same slate, same pair) replaces it.
                    bucket[:] = [
                        e
                        for e in bucket
                        if not (e.slate_date == slate_date and e.home_tri == home_tri and e.away_tri == away_tri)
                    ]
                    bucket.append(entry)
    return index


def _row_game_tris(index: NbaPropProjectionIndex, row: Mapping[str, Any]) -> tuple[str, str, str] | None:
    """The row's game as (slate_date, home_tri, away_tri), via game_cards' team names."""
    entry = index.games.lookup(row.get("home_team"), row.get("away_team"), row.get("commence_time"))
    if entry is None:
        return None
    return entry.slate_date, entry.home_tri.upper(), entry.away_tri.upper()


def _match_player(
    index: NbaPropProjectionIndex, row: Mapping[str, Any]
) -> tuple[NbaPlayerEntry | None, str | None]:
    """(entry, refusal_reason). Exactly one is set."""
    name = _norm_name(row.get("player_name"))
    if not name:
        return None, "row has no player name"
    game = _row_game_tris(index, row)
    candidates = index.by_player.get(name) or []
    if game is not None:
        exact = [e for e in candidates if (e.slate_date, e.home_tri, e.away_tri) == game]
        if exact:
            return exact[-1], None
        if name in index.missing.get(game, set()):
            return None, "player not in this game's sim (missing_prop_players)"
        if candidates:
            return None, "player's sim game is not this row's game"
        return None, "player not in the NBA sim for this game"
    # The row's game could not be identified from game_cards. Accept only a
    # candidate on the row's own central slate date, and only if it is unique.
    central = central_date_from_iso(row.get("commence_time"))
    if central is not None:
        same_day = [e for e in candidates if e.slate_date == central.isoformat()]
        if len(same_day) == 1:
            return same_day[0], None
        if len(same_day) > 1:
            return None, "player name matches more than one sim game"
    if not candidates:
        return None, "player not in the NBA sim for this game"
    return None, "no NBA sim for this row's game"


def attach_nba_prop_projections(
    grid: Iterable[Mapping[str, Any]], index: NbaPropProjectionIndex
) -> dict[str, Any]:
    """Stamp `projection` onto NBA player-prop rows. Returns coverage."""
    considered = 0
    attached = 0
    with_probability = 0
    with_edge = 0
    unmatched_player_rows = 0
    unsupported_market_rows = 0
    refused: Counter[str] = Counter()
    edge_side: Counter[str] = Counter()

    for row in grid:
        if str(row.get("kind") or "") != "prop":
            continue
        considered += 1
        market = str(row.get("market") or "").strip().lower()
        if market in _UNSUPPORTED_MARKETS:
            unsupported_market_rows += 1
            refused[_JOINT_STAT_REASON] += 1
            continue
        stat = _MARKET_TO_MODEL_KEY.get(market)
        if stat is None:
            unsupported_market_rows += 1
            refused[f"market not modelled: {market or '?'}"] += 1
            continue
        entry, reason = _match_player(index, row)
        if entry is None:
            unmatched_player_rows += 1
            refused[reason or "unknown"] += 1
            continue
        ladder = entry.ladders.get(stat)
        mean = entry.means.get(stat)
        if ladder is None or mean is None:
            unmatched_player_rows += 1
            refused[f"sim has no {stat} ladder for this player"] += 1
            continue

        line = _float(row.get("line"))
        projection: dict[str, Any] = {
            "projected": round(mean, 3),
            "source": SOURCE,
            "basis": "empirical_sim_ladder",
            "sim_draws": entry.sim_draws,
            "model_prob_over": None,
            "edge_vs_market_pct": None,
        }
        if line is None:
            projection["probability_unavailable_reason"] = "row has no line to price"
        else:
            hit_prob = _hit_prob_over(ladder, line)
            if hit_prob is None:
                projection["probability_unavailable_reason"] = "sim ladder could not be read at this line"
            else:
                # NBA book blend (lane nba-prop-calibration, user decision 2026-10-05): measured, the model
                # carries no information beyond the de-vigged book, so the served probability is the
                # per-stat logit blend toward the consensus fair price; the raw ladder probability and the
                # weight ride along on the projection. Falls back to the ladder WITH a reason.
                served_prob, blend_meta = served_prop_probability(hit_prob, _no_vig_over_probability(row), stat)
                projection.update(blend_meta)
                _attach_sim_probability_edge(projection, row=row, model_prob=served_prob)
                # Display ladder (lane layer2-board-ui-redesign, user-approved
                # 2026-10-08): the RAW sim ladder. The served number is the book
                # blend, so the page checks this against `p_model_raw` and labels
                # the chart "sim, before the book blend".
                from syndicate.features.shared.price_ladder import price_ladder
                from syndicate.features.shared.wnba_projections import _hit_prob_over as _ladder_prob

                projection["ladder"] = price_ladder(lambda t, _l=ladder: _ladder_prob(_l, t), line)
            edge = round(mean - line, 3)
            # `side` NAMES THE FRAMING OF `model_prob_over`, never the model's lean
            # `[2026-10-08, user: "fix all three sports", lane layer2-board-ui-redesign]`.
            # Every reader (`layer2_board._model_prob_for_side` / `_model_edge_for`,
            # `board_enrichment`, the Ask adapter) complements the probability when
            # this differs from the row's side. Writing the LEAN here ("under" when
            # the mean is below the line) told them an OVER probability was an UNDER
            # one, so every under-leaning prop shipped P(under) and a sign-flipped
            # edge on its OVER row. Measured on the served board 2026-10-08 15:47Z:
            # 297 of 520 NHL prop rows (Gage Goncalves o0.5 assists showed 76.4%,
            # the sim's own P(over) 23.6%) and 7 WNBA rows, 273 tagged "sim agrees".
            # The lean is kept, under its own name.
            projection["side"] = "over"
            projection["lean"] = "over" if edge > 0 else "under"
            live_reason = live_edge_unavailable_reason(row)
            projection["edge_vs_line"] = None if live_reason else edge
        if projection.get("edge_vs_market_pct") is None and not projection.get("edge_unavailable_reason"):
            probability_reason = projection.get("probability_unavailable_reason")
            projection["edge_unavailable_reason"] = (
                "no probability to price: %s" % probability_reason
                if probability_reason
                else "this projection carries no probability, so no edge was priced"
            )
        row["projection"] = refuse_published_certainty(projection)  # type: ignore[index]
        attached += 1
        published = row["projection"]  # type: ignore[index]
        if published.get("model_prob_over") is not None:
            with_probability += 1
        edge_pct = published.get("edge_vs_market_pct")
        if edge_pct is not None:
            with_edge += 1
            # THE ONE-SIDED-PILE CHECK, published rather than left to a script:
            # model_prob_over minus the no-vig over: > 0 favours the over,
            # < 0 the under. Counted apart, so a sim that is biased low reads as a lopsided pair here
            # before anyone trusts a ranking built on it (NHL's 10-03 under-bias).
            if edge_pct > 0:
                edge_side["favours_over"] += 1
            elif edge_pct < 0:
                edge_side["favours_under"] += 1

    return {
        "supported": True,
        "players_in_source": index.players,
        "rows_considered": considered,
        "rows_with_projection": attached,
        "rows_with_probability": with_probability,
        "rows_with_edge": with_edge,
        "unmatched_player_rows": unmatched_player_rows,
        "unsupported_market_rows": unsupported_market_rows,
        "unprojected_by_reason": dict(sorted(refused.items())),
        "edge_sign_by_side": dict(edge_side),
        "pct_projected": round(100.0 * attached / considered, 1) if considered else 0.0,
        "probability_fields": "empirical SmartSim hitProb ladder (cards_sim_detail), per line",
        "source_artifacts": index.source_files,
    }
