"""Soccer's live re-sim, in the shape `build_live_gameline_index` expects.

WHY A SEPARATE SOURCE MODULE. MLB and WNBA both publish a single
`live/<sport>_live_lens.json` whose `games[].gameLens[]` rows carry
`modelHomeWinProb` + `simsRun`. Soccer publishes neither that path nor that
shape: `scripts/poll_soccer_live_state.py` writes ONE FILE PER LEAGUE to
`soccer_source/<league>/api/live_state/live_state_<date>.json`, and the live
projection sits at `games[event_id].projection` as a
`LiveMatchProjection.to_dict()`. `live/soccer_live_lens.json` exists but is
`live_lens_loop.py`'s own tick-status snapshot -- its docstring says so -- and
reading it here would parse a real file and index zero matches.

WHAT SOCCER HAS THAT WNBA DOES NOT: a real `simulations` count (400 on the
2026-08-21 artifacts). `price_moneyline` needs n for `prob_std_err`, and WNBA's
absence of one is why it publishes a live projection and refuses to price it
(`REASON_UNUSABLE_SIMS`). Soccer's n is genuine, so soccer can be priced. No n
is invented here for any sport that lacks one.

THREE-WAY IS THE WHOLE DIFFICULTY, and it is handled by the CALLER, not here.
Soccer h2h has home/draw/away and Layer 2 emits one row per side, while
`attach_live_gamelines` prices every h2h row home-framed
(`model_prob=hit["home_win_prob"]`). So this module publishes the full
three-way vector under `side_probabilities` alongside the home-framed
`home_win_prob` the existing pricer reads. A caller that cannot select by side
MUST withhold draw rows by name rather than price them against
`home_win_prob` -- see `.syndicate/plan_2026-08-21_soccer_live_gates.md`.
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


def soccer_live_gameline_index(
    selected_date: str, *, data_root: Any = None
) -> dict[tuple[str, str], dict[str, Any]]:
    """(away_team, home_team) -> live moneyline projection, for in-play matches.

    Keyed on FULL TEAM NAMES with no alias table, matching
    `build_live_gameline_index`'s deliberate choice. Gate 1 measured that this
    join is exact for soccer: the ESPN names in the live-state artifact matched
    the OddsAPI grid on 286 rows for the 2026-08-20 la_liga fixture.

    Reads `games`, NOT `match_box`: `games` is in-play only and carries the
    `projection`; `match_box` spans in+post and carries a BOX SCORE with no
    projection at all. Gate 1 wanted the opposite map for the opposite reason.
    """
    from syndicate.features.shared.refresh_state_store import (
        data_root as default_root,
        read_json_file,
    )

    root = (data_root or default_root()) / "soccer_source"
    index: dict[tuple[str, str], dict[str, Any]] = {}
    if not root.exists():
        return index

    for league_dir in sorted(root.iterdir()):
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
        as_of = payload.get("generated_at")
        for event_id, game in games.items():
            if not isinstance(game, Mapping):
                continue
            projection = game.get("projection")
            if not isinstance(projection, Mapping):
                continue
            home_p = _f(projection.get("home_win_probability"))
            if home_p is None or not (0.0 <= home_p <= 1.0):
                continue
            key = (_norm(game.get("away_team")), _norm(game.get("home_team")))
            if not key[0] or not key[1]:
                continue

            draw_p = _f(projection.get("draw_probability"))
            away_p = _f(projection.get("away_win_probability"))
            home_goals = _f(projection.get("projected_final_home_goals"))
            away_goals = _f(projection.get("projected_final_away_goals"))

            index[key] = {
                "home_win_prob": home_p,
                # THE FULL THREE-WAY VECTOR. `home_win_prob` above exists so the
                # shared pricer works unchanged; this is what a side-aware
                # caller must read so a DRAW row is never priced against the
                # HOME probability.
                "side_probabilities": {
                    "home": home_p,
                    "draw": draw_p,
                    "away": away_p,
                },
                "sims_run": projection.get("simulations"),
                "total_mean": _f(projection.get("projected_final_total")),
                "home_margin": (
                    round(home_goals - away_goals, 4)
                    if home_goals is not None and away_goals is not None
                    else None
                ),
                # NO DISTRIBUTIONS. The live projection publishes summary
                # probabilities and means only, so totals/spreads must be
                # refused by name downstream rather than answered from a mean.
                # `{}` is what every consumer already reads as "no shape".
                "total_runs_dist": {},
                "margin_dist": {},
                # ONE analytic line, WNBA-shaped (`price_analytic_line_market`).
                "analytic_markets": (
                    {
                        "totals": {
                            "line": SOCCER_LIVE_TOTALS_LINE,
                            "prob_over": _f(projection.get("over_2_5_probability")),
                        }
                    }
                    if _f(projection.get("over_2_5_probability")) is not None
                    else {}
                ),
                "as_of": as_of,
                # Soccer's poller rewrites every tick and never carries a stale
                # projection forward, unlike MLB's lens.
                "carried_forward": False,
                "lane": "soccer_live_state",
                "game_pk": event_id,
                "league": payload.get("league"),
                # Context a reader needs to judge the projection, and which the
                # means alone do not convey.
                "live_score": {
                    "home": game.get("score_home"),
                    "away": game.get("score_away"),
                },
                "clock": game.get("status_display_clock"),
                "red_cards_applied": {
                    "home": bool(projection.get("home_red_card_applied")),
                    "away": bool(projection.get("away_red_card_applied")),
                },
            }
    return index
