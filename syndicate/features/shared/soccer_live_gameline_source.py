"""Soccer's live re-sim, in the shape the live-board joins expect.

WHERE THE DATA ACTUALLY IS, and this was got wrong once already.
`scripts/poll_soccer_live_state.py` writes a per-league file to
`soccer_source/<league>/api/live_state/live_state_<date>.json` with a DIRECT
`out_path.write_text()` -- a filesystem write on **live-odds-worker**. The board
is built on **refresh-worker**, a different service with a different disk, so
enumerating that tree from the board build finds NOTHING. Measured 2026-08-21
17:05Z: gate 1 reported `no published live-state artifact for any league` while
all ten files existed and were seconds old, because the enumeration was
`Path.iterdir()` and the files are not on that box.

WHAT DOES CROSS SERVICES: `live/soccer_live_lens.json`, written by
`live_lens_loop.py` through `refresh_state_store.write_json_file`, i.e. through
the KEYVALUE backend, whose key is the absolute path and whose store is shared
by all three services. `soccer/live_lens.py`'s docstring calls that path a
"bookkeeping/validation snapshot only" -- **that describes intent, not
behaviour**. The loop writes `poll_active_leagues_for_tick`'s FULL return there,
which carries every in-play match with its `projection` and
`live_player_props`. Trusting the comment over the code is what produced the
inert first version.

So this reads the aggregate snapshot FIRST and falls back to the per-league
files, which are the real thing wherever they happen to be local (live-odds-worker,
a dev box, the tests).

SOCCER IS PRICED, NOT MERELY PUBLISHED: it carries a real `simulations` count
(400 on the 2026-08-21 artifacts), which is what `prob_std_err` needs. WNBA has
none and is correctly withheld by `REASON_UNUSABLE_SIMS`. No n is invented here
for any sport.
"""


from __future__ import annotations

from typing import Any, Mapping

# The one line soccer's LIVE projection can answer as a probability. The pregame
# artifact carries `scoreline_probabilities` and can price any line; the live
# one does NOT, so this is the WNBA-shaped single-analytic-line case. Applying
# the pregame distribution here would answer "from kickoff" to a question asked
# "from the current score".
SOCCER_LIVE_TOTALS_LINE = 2.5


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _f(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def soccer_live_games(selected_date: str, *, data_root: Any = None) -> list[dict[str, Any]]:
    """Every soccer match IN PLAY, from whichever store this service can reach.

    Returns the per-match dicts the poller builds (`projection`,
    `live_player_props`, teams, score, clock), each carrying `league` and
    `event_id`.

    AGGREGATE FIRST, because it is the only one that crosses services. The
    per-league files are a filesystem write on live-odds-worker; the aggregate
    goes through the keyvalue store and is therefore readable from
    refresh-worker, where the board is actually built.

    The fallback is not dead code: on live-odds-worker and on a dev box the
    per-league files ARE local, and the tests exercise that path.
    """
    from syndicate.features.shared.refresh_state_store import (
        data_root as default_root,
        read_json_file,
    )

    root = data_root or default_root()

    snapshot = read_json_file(root / "live" / "soccer_live_lens.json")
    if isinstance(snapshot, Mapping):
        # Only this date's snapshot may answer for this date. A stale one would
        # price today's board off yesterday's match state.
        if str(snapshot.get("date") or "") == str(selected_date):
            games = snapshot.get("games")
            if isinstance(games, list):
                out = [g for g in games if isinstance(g, Mapping)]
                if out:
                    return [dict(g) for g in out]

    # Per-league fallback.
    source = root / "soccer_source"
    try:
        if not source.exists():
            return []
        league_dirs = sorted(source.iterdir())
    except OSError:
        return []

    out: list[dict[str, Any]] = []
    for league_dir in league_dirs:
        if not league_dir.is_dir():
            continue
        payload = read_json_file(
            league_dir / "api" / "live_state" / f"live_state_{selected_date}.json"
        )
        if not isinstance(payload, Mapping):
            continue
        games = payload.get("games")
        if not isinstance(games, Mapping):
            continue
        for event_id, game in games.items():
            if isinstance(game, Mapping):
                out.append({"league": payload.get("league"), "event_id": event_id, **dict(game)})
    return out


def _histograms_from_scorelines(scorelines: Any) -> tuple[dict[float, float], dict[float, float]]:
    """(total-goals histogram, home-margin histogram) from a scoreline dict.

    THE LIVE TOTALS LENS. `price_distribution_market` prices ANY line off a
    histogram keyed by NUMBER, while the sim publishes exact scorelines keyed
    "H-A" -- so this is the one transformation between them. Without it the live
    board could answer 2.5 and nothing else, via the single analytic
    probability, which is least useful exactly when the live tier matters most:
    a 2-0 at 60' is quoted at 3.5 and 4.5, not 2.5.

    `margin_dist` is HOME-POSITIVE (`home - away`), matching `run_margin_dist`'s
    frame, because `price_distribution_market` documents that the pregame spread
    rule transfers unchanged only under that frame -- getting it backwards
    produced measured 19-28 point phantom edges on 2026-08-08.

    Summing rather than sampling: two scorelines can share a total (2-1 and 3-0
    are both 3) and a margin (2-1 and 3-2 are both +1), so the mass must be
    accumulated, not overwritten.
    """
    totals: dict[float, float] = {}
    margins: dict[float, float] = {}
    if not isinstance(scorelines, Mapping):
        return totals, margins
    for key, raw in scorelines.items():
        prob = _f(raw)
        if prob is None:
            continue
        parts = str(key).replace(":", "-").split("-")
        if len(parts) != 2:
            continue
        try:
            home, away = int(parts[0]), int(parts[1])
        except (TypeError, ValueError):
            continue
        totals[float(home + away)] = totals.get(float(home + away), 0.0) + prob
        margins[float(home - away)] = margins.get(float(home - away), 0.0) + prob
    # A distribution that does not sum to ~1 cannot be priced against; returning
    # empty makes the caller refuse by name rather than price against missing
    # mass.
    if not 0.99 <= sum(totals.values()) <= 1.01:
        return {}, {}
    return totals, margins


def soccer_live_gameline_index(
    selected_date: str, *, data_root: Any = None
) -> dict[tuple[str, str], dict[str, Any]]:
    """(away_team, home_team) -> live moneyline projection, for in-play matches.

    Keyed on FULL TEAM NAMES with no alias table, matching
    `build_live_gameline_index`'s deliberate choice. Gate 1 measured that this
    join is exact for soccer: the ESPN names in the live-state artifact matched
    the OddsAPI grid on 286 rows for the 2026-08-20 la_liga fixture.

    In-play only, by the producer's contract: a finished match leaves `games`
    and lives in `match_box`, so a settled market can never be priced from here.
    """
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for game in soccer_live_games(selected_date, data_root=data_root):
        projection = game.get("projection")
        if not isinstance(projection, Mapping):
            continue
        home_p = _f(projection.get("home_win_probability"))
        if home_p is None or not (0.0 <= home_p <= 1.0):
            continue
        key = (_norm(game.get("away_team")), _norm(game.get("home_team")))
        if not key[0] or not key[1]:
            continue

        home_goals = _f(projection.get("projected_final_home_goals"))
        away_goals = _f(projection.get("projected_final_away_goals"))
        over = _f(projection.get("over_2_5_probability"))
        _live_totals, _live_margins = _histograms_from_scorelines(
            projection.get("scoreline_probabilities")
        )

        index[key] = {
            "home_win_prob": home_p,
            # THE FULL THREE-WAY VECTOR, published alongside the home-framed
            # probability the shared pricer reads.
            "side_probabilities": {
                "home": home_p,
                "draw": _f(projection.get("draw_probability")),
                "away": _f(projection.get("away_win_probability")),
            },
            "sims_run": projection.get("simulations"),
            "total_mean": _f(projection.get("projected_final_total")),
            "home_margin": (
                round(home_goals - away_goals, 4)
                if home_goals is not None and away_goals is not None
                else None
            ),
            # THE LIVE SHAPES. Derived from the resumed sim's own scoreline
            # distribution, so totals and spreads price at ANY line instead of
            # only at the one analytic threshold below. Empty on a snapshot
            # written before the producer carried `scoreline_probabilities`,
            # and `{}` reads as "no distribution" everywhere downstream -- so an
            # older lens degrades to the previous behaviour rather than to a
            # wrong number.
            "total_runs_dist": _live_totals,
            "margin_dist": _live_margins,
            # ONE analytic line, WNBA-shaped (`price_analytic_line_market`).
            "analytic_markets": (
                {"totals": {"line": SOCCER_LIVE_TOTALS_LINE, "prob_over": over}}
                if over is not None
                else {}
            ),
            "as_of": game.get("generated_at"),
            # The poller rewrites every tick and never carries a stale
            # projection forward, unlike MLB's lens.
            "carried_forward": False,
            "lane": "soccer_live_state",
            "game_pk": game.get("event_id"),
            "league": game.get("league"),
            "live_score": {"home": game.get("score_home"), "away": game.get("score_away")},
            "clock": game.get("status_display_clock"),
            "red_cards_applied": {
                "home": bool(projection.get("home_red_card_applied")),
                "away": bool(projection.get("away_red_card_applied")),
            },
        }
    return index


# Market key the grid uses for soccer shot props. `shots_over_probabilities` is
# a shots distribution and prices this market and no other -- deliberately NOT
# mapped onto `player_shots_on_target`, which is a different statistic with its
# own pregame field.
SOCCER_LIVE_PROP_MARKET = "player_shots"


def soccer_live_prop_index(
    selected_date: str, *, data_root: Any = None
) -> dict[str, Any]:
    """(player, market, line) -> live prop projection, in gate 2's contract.

    Soccer's live re-sim publishes `shots_over_probabilities` -- a real P(over)
    per line from the RESUMED Monte Carlo, keyed by `live_lens._SHOT_LINES`
    (0.5..4.5). That is what MLB's `liveModelProbOver` is, under another name,
    so it maps onto the gate-2 contract without inventing anything.

    THE PRODUCER CAPS AT 12 PLAYERS PER MATCH
    (`poll_soccer_live_state.py`: `sorted(...)[:12]`). Downstream a capped-out
    player is indistinguishable from one the re-sim never projected, so the cap
    is REPORTED rather than inherited silently.
    """
    from syndicate.features.shared.live_projection_join import _norm_name

    index: dict[tuple[str, str, float], dict[str, Any]] = {}
    report: dict[str, Any] = {
        "index": index,
        "games_seen": 0,
        "live_games": 0,
        "rows_seen": 0,
        "rows_indexed": 0,
        "skipped_no_live_projection": 0,
        "skipped_no_key": 0,
        "players_at_producer_cap": 0,
        "producer_player_cap": 12,
    }

    for game in soccer_live_games(selected_date, data_root=data_root):
        report["games_seen"] += 1
        # Everything in `games` is in play by the producer's contract.
        report["live_games"] += 1
        props = game.get("live_player_props")
        if not isinstance(props, list):
            continue
        if len(props) >= report["producer_player_cap"]:
            report["players_at_producer_cap"] += 1
        for prop in props:
            if not isinstance(prop, Mapping):
                continue
            player = _norm_name(prop.get("player_name"))
            over = prop.get("shots_over_probabilities")
            projected = _f(prop.get("projected_final_shots"))
            if not player or not isinstance(over, Mapping) or not over:
                report["skipped_no_key"] += 1
                continue
            if projected is None:
                # The live projection IS the live-awareness evidence, the same
                # rule gate 2 applies to MLB.
                report["skipped_no_live_projection"] += 1
                continue
            for raw_line, raw_prob in over.items():
                line = _f(raw_line)
                prob = _f(raw_prob)
                report["rows_seen"] += 1
                if line is None or prob is None:
                    report["skipped_no_key"] += 1
                    continue
                index[(player, SOCCER_LIVE_PROP_MARKET, line)] = {
                    "live_projection": projected,
                    # Soccer publishes no PREGAME probability on this row, and
                    # `model_prob_over` is the pregame slot. Leaving it None
                    # keeps the live number from being read as one.
                    "model_prob_over": None,
                    "live_prob_over": prob,
                    "actual_so_far": prop.get("shots_so_far"),
                    "live_edge_hint": None,
                    "side": "over",
                }
                report["rows_indexed"] += 1
    return report
