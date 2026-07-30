from __future__ import annotations

from datetime import datetime
from typing import Any

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE
from syndicate.features.soccer.sources import available_weeks
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import league_display_name
from syndicate.features.soccer.sources import league_select_control
from syndicate.features.soccer.sources import live_state_payload
from syndicate.features.soccer.sources import normalize_league
from syndicate.features.soccer.sources import picks_rows
from syndicate.features.soccer.sources import recommendations_payload
from syndicate.features.soccer.sources import schedule_path
from syndicate.features.soccer.sources import team_by_name
from syndicate.features.soccer.sources import week_date_list
from syndicate.features.soccer.sources import week_label
from syndicate.features.soccer.sources import week_matches
from syndicate.features.shared.game_board_contract import apply_game_board_contract


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def _fmt_pct(value: Any) -> str:
    number = _safe_float(value)
    return f"{number * 100:.1f}%" if number is not None else "-"


def _fmt_num(value: Any, digits: int = 2) -> str:
    number = _safe_float(value)
    return f"{number:.{digits}f}" if number is not None else "-"


def _team_roster_href(team: str, league: str) -> str | None:
    directory_team = team_by_name(league, team)
    team_id = str((directory_team or {}).get("team_id") or "").strip()
    return f"/soccer/{league}/team/{team_id}/roster" if team_id else None


def _abbr(team: str, league: str) -> str:
    directory_team = team_by_name(league, team)
    if directory_team and str(directory_team.get("abbreviation") or "").strip():
        return str(directory_team["abbreviation"]).strip().upper()
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    if len(tokens) == 1:
        return tokens[0][:3].upper()
    return "".join(token[0] for token in tokens[:3]).upper()


def _team_logo_url(team: str, league: str) -> str | None:
    directory_team = team_by_name(league, team)
    return str(directory_team.get("logo_url") or "").strip() or None if directory_team else None


def _team_primary_color(team: str, league: str) -> str | None:
    directory_team = team_by_name(league, team)
    value = str((directory_team or {}).get("color") or "").strip()
    return f"#{value}" if value else None


def _team_secondary_color(team: str, league: str) -> str | None:
    directory_team = team_by_name(league, team)
    value = str((directory_team or {}).get("alternate_color") or "").strip()
    return f"#{value}" if value else None


def _format_kickoff_display(kickoff: str | None) -> str:
    # Mirrors mlb/cards.py and wnba/cards.py's _format_start_time_local: the
    # raw value here is ESPN's ISO-8601 UTC event date, and without this it
    # renders straight through as e.g. "2026-07-22T23:30Z" -- confirmed live
    # on the MLS compact cards. Includes the day/date (unlike the MLB/WNBA
    # versions) since soccer's cards span a whole week, not one day.
    text = str(kickoff or "").strip()
    if not text:
        return "Scheduled"
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=CENTRAL_TIMEZONE)
        local_stamp = stamp.astimezone(CENTRAL_TIMEZONE)
        time_text = f"{local_stamp.strftime('%I').lstrip('0') or '12'}:{local_stamp.strftime('%M')} {local_stamp.strftime('%p')} CT"
        return f"{local_stamp.strftime('%a')}, {local_stamp.strftime('%b')} {local_stamp.strftime('%d').lstrip('0')} · {time_text}"
    except Exception:
        return "Scheduled"


def _status_label(status_state: str, kickoff: str | None) -> str:
    state = str(status_state or "pre").strip().lower()
    if state == "post":
        return "Final"
    if state == "in":
        return "Live"
    return _format_kickoff_display(kickoff)


def _box_score_line(
    *,
    away_abbr: str,
    home_abbr: str,
    periods: dict[str, Any],
    team_projection: dict[str, Any],
) -> str:
    h1 = periods.get("h1") if isinstance(periods.get("h1"), dict) else {}
    h2 = periods.get("h2") if isinstance(periods.get("h2"), dict) else {}
    if not h1 and not h2:
        return ""

    def _leg(entry: dict[str, Any]) -> str:
        return f"{_fmt_num(entry.get('away_mean'), 1)}-{_fmt_num(entry.get('home_mean'), 1)}"

    ft = f"{_fmt_num(team_projection.get('away_mean'), 1)}-{_fmt_num(team_projection.get('home_mean'), 1)}"
    return f"Proj {away_abbr}-{home_abbr} · 1H {_leg(h1)} · 2H {_leg(h2)} · FT {ft}"


def _prop_line(row: dict[str, Any]) -> str:
    name = str(row.get("player_name") or "Player").strip()
    team = str(row.get("team") or "").strip()
    scorer_prob = _fmt_pct(row.get("anytime_scorer_probability"))
    shots = _fmt_num(row.get("expected_shots"), 1)
    return f"{name} ({team}) | Anytime scorer {scorer_prob} | xShots {shots}"


def _unsimulated_game(fixture: dict[str, Any], *, league: str, week: int, season: int) -> dict[str, Any]:
    home_team = str(fixture.get("home_team") or "Home").strip() or "Home"
    away_team = str(fixture.get("away_team") or "Away").strip() or "Away"
    event_id = str(fixture.get("event_id") or "").strip()
    status_state = str(fixture.get("status_state") or "pre")
    date_str = str(fixture.get("date") or "")[:10]
    return {
        "gamePk": event_id or f"{league}_{date_str}_{home_team}_{away_team}".replace(" ", "_"),
        "event_id": event_id,
        "away": {
            "abbr": _abbr(away_team, league),
            "name": away_team,
            "score": fixture.get("away_score"),
            "href": _team_roster_href(away_team, league),
            "logo_url": _team_logo_url(away_team, league),
            "primary_color": _team_primary_color(away_team, league),
            "secondary_color": _team_secondary_color(away_team, league),
        },
        "home": {
            "abbr": _abbr(home_team, league),
            "name": home_team,
            "score": fixture.get("home_score"),
            "href": _team_roster_href(home_team, league),
            "logo_url": _team_logo_url(home_team, league),
            "primary_color": _team_primary_color(home_team, league),
            "secondary_color": _team_secondary_color(home_team, league),
        },
        "card_variant": "soccer_main",
        # #77. Explicit marker so the intelligence layer can exclude these
        # without pattern-matching the prose below. Confirmed in production
        # 2026-07-26: every one of these placeholders was being promoted onto
        # the Layer 2 board as a LIVE pick whose `pick`/`selection` text was
        # the "Run scripts/build_soccer_artifacts.py ..." operator instruction
        # from `items` -- with null odds/line/edge and "-" for team, player and
        # projection. This is a page-level empty state, never a bettable row.
        "is_unsimulated_placeholder": True,
        "status": _status_label(status_state, fixture.get("date")),
        "detail": date_str or league_display_name(league),
        "scheduled_start_utc": fixture.get("date"),
        "summary": f"{away_team} at {home_team} is on the schedule for Week {week} but has not been simulated yet.",
        "compact_box_line": "",
        "href": f"/soccer/{league}/game/{event_id or 'unknown'}?week={week}&season={season}",
        "href_label": "Open match card",
        "metrics": [
            {"label": "Home win", "value": "-"},
            {"label": "Draw", "value": "-"},
            {"label": "Away win", "value": "-"},
            {"label": "Total goals", "value": "-"},
            {"label": "BTTS", "value": "-"},
            {"label": "Over 2.5", "value": "-"},
        ],
        "panels": [
            {
                "eyebrow": "Not yet simulated",
                "title": f"{away_team} @ {home_team}",
                "body": f"This fixture is on the real {league_display_name(league)} schedule for {date_str}, but SoccerSim has not simulated it yet.",
                "items": [
                    f"Run scripts/build_soccer_artifacts.py --league {league} --date {date_str} to populate this match.",
                ],
            }
        ],
    }


def _live_match_state(league: str, date_str: str, event_id: str) -> dict[str, Any] | None:
    if not date_str or not event_id:
        return None
    payload = live_state_payload(league, date_str)
    games = payload.get("games") if isinstance(payload, dict) else None
    if not isinstance(games, dict):
        return None
    entry = games.get(event_id)
    return entry if isinstance(entry, dict) else None


def _market_data_for_match(league: str, date_str: str, home_team: str, away_team: str) -> dict[str, Any]:
    # game_board_contract.py's _build_period_rows/_build_box_sections already
    # know how to compare a sim projection against game["betting"] (every
    # other sport populates it from a real book line) -- soccer never set
    # this key at all, so its market/edge columns always rendered "-" even
    # though build_soccer_picks.py now computes exactly this comparison.
    # Reads the same graded picks_{date}.csv the picks pipeline writes,
    # rather than re-deriving devig/probability math here.
    #
    # Matched by team name, not event_id: build_soccer_picks.py's picks CSV
    # carries the Odds API's own event id (a different id space than ESPN's,
    # which is what the sim payload's event_id/match_id actually is), so
    # team-name matching is the only field both sources share -- same join
    # key build_soccer_picks.py itself already uses internally.
    if not date_str or not home_team or not away_team:
        return {}
    rows = [
        row
        for row in picks_rows(league, date_str)
        if str(row.get("home") or "").strip() == home_team and str(row.get("away") or "").strip() == away_team
    ]
    if not rows:
        return {}
    betting: dict[str, Any] = {}
    for row in rows:
        market = str(row.get("market") or "").strip().upper()
        side = str(row.get("side") or "").strip().lower()
        line_text = row.get("line")
        if market == "ML":
            prob = _safe_float(row.get("market_probability"))
            if prob is None:
                continue
            if side == "home":
                betting["p_home_win"] = prob
            elif side == "away":
                betting["p_away_win"] = prob
        elif market == "TOTAL" and "total" not in betting:
            line = _safe_float(line_text)
            if line is not None:
                betting["total"] = line
        elif market == "SPREAD" and side == "home":
            line = _safe_float(line_text)
            if line is None:
                continue
            current = betting.get("home_spread")
            # Multiple books quote different Asian-handicap lines; the one
            # closest to pick'em is the most representative single line to
            # show, same convention a real odds board defaults to.
            if current is None or abs(line) < abs(current):
                betting["home_spread"] = line
    return betting


def _box_score_panel(
    *,
    away_team: str,
    home_team: str,
    away_abbr: str,
    home_abbr: str,
    volume: dict[str, Any],
    live_state: dict[str, Any] | None,
) -> dict[str, Any]:
    # Same volume-stat lane either way (shots / SOT / corners); live_state
    # (poll_soccer_live_state.py's live_state_{date}.json, so-far counts from
    # ESPN's live feed) takes over from the pregame sim projection once a
    # match goes live, rather than showing both -- once the actual count is
    # known, the projection of it is no longer the useful number.
    # Eyebrow deliberately avoids "sim"/"box"/"player outcome" -- those are
    # game_board_contract.py's _build_box_sections keyword match for the Box
    # Score tab, and team-level volume isn't a box score (a box score is
    # player stat lines -- see _player_box_score_panel below, which owns that
    # tab now). This panel's items/table_groups still flow into the Game
    # tab's top-plays lane via _build_top_play_rows, same as any panel.
    if live_state is not None:
        return {
            "eyebrow": "Live match volume",
            "title": "Shots / SOT / corners / red cards -- so far",
            "body": "Actual match state from ESPN's live feed, refreshed on each live poll.",
            "table_groups": [
                {
                    "heading": "Live",
                    "rows": [
                        {
                            "name": away_abbr,
                            "detail": f"{away_team} shots / SOT / corners / red",
                            "value": f"{_fmt_num(live_state.get('away_shots_so_far'), 0)} / {_fmt_num(live_state.get('away_shots_on_target_so_far'), 0)} / {_fmt_num(live_state.get('away_corners_so_far'), 0)} / {_fmt_num(live_state.get('away_red_cards'), 0)}",
                        },
                        {
                            "name": home_abbr,
                            "detail": f"{home_team} shots / SOT / corners / red",
                            "value": f"{_fmt_num(live_state.get('home_shots_so_far'), 0)} / {_fmt_num(live_state.get('home_shots_on_target_so_far'), 0)} / {_fmt_num(live_state.get('home_corners_so_far'), 0)} / {_fmt_num(live_state.get('home_red_cards'), 0)}",
                        },
                    ],
                }
            ],
            "items": [
                f"Shots: {away_team} {_fmt_num(live_state.get('away_shots_so_far'), 0)} | {home_team} {_fmt_num(live_state.get('home_shots_so_far'), 0)}",
                f"On target: {away_team} {_fmt_num(live_state.get('away_shots_on_target_so_far'), 0)} | {home_team} {_fmt_num(live_state.get('home_shots_on_target_so_far'), 0)}",
                f"Corners: {away_team} {_fmt_num(live_state.get('away_corners_so_far'), 0)} | {home_team} {_fmt_num(live_state.get('home_corners_so_far'), 0)}",
                f"Red cards: {away_team} {_fmt_num(live_state.get('away_red_cards'), 0)} | {home_team} {_fmt_num(live_state.get('home_red_cards'), 0)}",
            ],
        }
    return {
        "eyebrow": "Projected match volume",
        "title": "Shots / SOT / corners",
        "body": "Projected volume markets for live shot props and corner totals.",
        "table_groups": [
            {
                "heading": "Projected",
                "rows": [
                    {
                        "name": away_abbr,
                        "detail": f"{away_team} shots / SOT / corners",
                        "value": f"{_fmt_num(volume.get('away_shots'), 1)} / {_fmt_num(volume.get('away_shots_on_target'), 1)} / {_fmt_num(volume.get('away_corners'), 1)}",
                    },
                    {
                        "name": home_abbr,
                        "detail": f"{home_team} shots / SOT / corners",
                        "value": f"{_fmt_num(volume.get('home_shots'), 1)} / {_fmt_num(volume.get('home_shots_on_target'), 1)} / {_fmt_num(volume.get('home_corners'), 1)}",
                    },
                ],
            }
        ],
        "items": [
            f"Shots: {away_team} {_fmt_num(volume.get('away_shots'), 1)} | {home_team} {_fmt_num(volume.get('home_shots'), 1)}",
            f"On target: {away_team} {_fmt_num(volume.get('away_shots_on_target'), 1)} | {home_team} {_fmt_num(volume.get('home_shots_on_target'), 1)}",
            f"Corners: {away_team} {_fmt_num(volume.get('away_corners'), 1)} | {home_team} {_fmt_num(volume.get('home_corners'), 1)}",
        ],
    }


def _player_box_score_panel(
    *,
    away_team: str,
    home_team: str,
    top_props: list[dict[str, Any]],
    live_state: dict[str, Any] | None,
) -> dict[str, Any]:
    # The actual box score (player stat lines), separate from the team-level
    # volume panel above. "box"/"sim" in the eyebrow is what
    # game_board_contract.py's _build_box_sections keys off of to route this
    # into the Box Score tab.
    if live_state is not None:
        live_props = live_state.get("live_player_props") if isinstance(live_state.get("live_player_props"), list) else []
        rows = [
            {
                "name": str(row.get("player_name") or "Player"),
                "detail": f"{away_team if row.get('side') == 'away' else home_team} · live",
                "value": f"{_fmt_num(row.get('shots_so_far'), 0)} sh so far → proj {_fmt_num(row.get('projected_final_shots'), 1)}",
            }
            for row in live_props[:8]
            if isinstance(row, dict)
        ]
        return {
            "eyebrow": "Live box score",
            "title": "Player stat lines",
            "body": "Shots so far and projected final shots for players who have appeared, from ESPN's live feed.",
            "table_groups": [{"heading": "Live", "rows": rows}] if rows else [],
            "items": [f"{row['name']} ({row['detail']}): {row['value']}" for row in rows] or ["No players have recorded a shot yet."],
        }
    rows = [
        {
            "name": str(row.get("player_name") or "Player"),
            "detail": f"{row.get('team') or (away_team if row.get('side') == 'away' else home_team)} · {row.get('position') or '-'}",
            "value": f"{_fmt_num(row.get('expected_shots'), 1)} xSh · {_fmt_num(row.get('expected_shots_on_target'), 1)} xSOT · {_fmt_pct(row.get('anytime_scorer_probability'))} scorer",
        }
        for row in top_props[:8]
    ]
    return {
        "eyebrow": "Sim box score",
        "title": "Player stat lines",
        "body": "Projected shots, shots on target, and anytime-scorer probability from the simulated player-props pass.",
        "table_groups": [{"heading": "Projected", "rows": rows}] if rows else [],
        "items": [f"{row['name']} ({row['detail']}): {row['value']}" for row in rows] or ["No player-prop rows were available for this match."],
    }


def _match_to_game(match: dict[str, Any], *, league: str, week: int, season: int) -> dict[str, Any]:
    matchup = match.get("matchup") if isinstance(match.get("matchup"), dict) else {}
    home_team = str(matchup.get("home_team") or "Home").strip() or "Home"
    away_team = str(matchup.get("away_team") or "Away").strip() or "Away"
    win_prob = match.get("win_probability") if isinstance(match.get("win_probability"), dict) else {}
    team_projection = match.get("team_projection") if isinstance(match.get("team_projection"), dict) else {}
    total_distribution = match.get("total_distribution") if isinstance(match.get("total_distribution"), dict) else {}
    volume = match.get("volume_projection") if isinstance(match.get("volume_projection"), dict) else {}
    periods = match.get("periods") if isinstance(match.get("periods"), dict) else {}
    top_props = match.get("top_props") if isinstance(match.get("top_props"), list) else []
    event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
    status_state = str(match.get("status_state") or "pre")
    live_state = _live_match_state(league, str(match.get("date") or "")[:10], event_id) if status_state == "in" else None

    home_score = match.get("live_home_score")
    away_score = match.get("live_away_score")
    score_text = f"{away_score}-{home_score}" if status_state in {"in", "post"} and home_score is not None else "-"

    summary = (
        f"Projected {away_team} {_fmt_num(team_projection.get('away_mean'), 1)} @ {home_team} "
        f"{_fmt_num(team_projection.get('home_mean'), 1)} (total {_fmt_num(team_projection.get('total_mean'), 1)}). "
        f"Win prob: {home_team} {_fmt_pct(win_prob.get('home'))} / Draw {_fmt_pct(win_prob.get('draw'))} / "
        f"{away_team} {_fmt_pct(win_prob.get('away'))}."
    )

    return {
        "gamePk": event_id or f"{league}_{match.get('date')}_{home_team}_{away_team}".replace(" ", "_"),
        "event_id": event_id,
        "away": {
            "abbr": _abbr(away_team, league),
            "name": away_team,
            "score": away_score,
            "href": _team_roster_href(away_team, league),
            "logo_url": _team_logo_url(away_team, league),
            "primary_color": _team_primary_color(away_team, league),
            "secondary_color": _team_secondary_color(away_team, league),
        },
        "home": {
            "abbr": _abbr(home_team, league),
            "name": home_team,
            "score": home_score,
            "href": _team_roster_href(home_team, league),
            "logo_url": _team_logo_url(home_team, league),
            "primary_color": _team_primary_color(home_team, league),
            "secondary_color": _team_secondary_color(home_team, league),
        },
        "card_variant": "soccer_main",
        "status": _status_label(status_state, match.get("kickoff")),
        "detail": score_text if score_text != "-" else league_display_name(league),
        # Raw ISO kickoff, distinct from "detail" above (which carries a
        # score/league string, not a timestamp) -- the shared game-chip and
        # home-rail scheduled-status helpers read this key to render a
        # time/date badge; without it soccer's pregame chips render no time
        # or date at all (see game_chip_scoreboard.py's _scheduled_status_token).
        "scheduled_start_utc": match.get("kickoff"),
        "summary": summary,
        "href": f"/soccer/{league}/game/{event_id or 'unknown'}?week={week}&season={season}",
        "href_label": "Open match card",
        "compact_box_line": _box_score_line(
            away_abbr=_abbr(away_team, league),
            home_abbr=_abbr(home_team, league),
            periods=periods,
            team_projection=team_projection,
        ),
        "sim": {
            "score": {"away_mean": team_projection.get("away_mean"), "home_mean": team_projection.get("home_mean")},
            "periods": periods,
        },
        "betting": _market_data_for_match(league, str(match.get("date") or "")[:10], home_team, away_team),
        "metrics": [
            {"label": "Home win", "value": _fmt_pct(win_prob.get("home"))},
            {"label": "Draw", "value": _fmt_pct(win_prob.get("draw"))},
            {"label": "Away win", "value": _fmt_pct(win_prob.get("away"))},
            {"label": "Total goals", "value": _fmt_num(team_projection.get("total_mean"), 2)},
            {"label": "BTTS", "value": _fmt_pct(total_distribution.get("both_teams_scored_probability"))},
            {"label": "Over 2.5", "value": _fmt_pct(total_distribution.get("over_2_5_probability"))},
        ],
        "panels": [
            {
                "eyebrow": "Match projection",
                "title": f"{away_team} @ {home_team}",
                "body": summary,
                "items": [
                    f"Projected score: {away_team} {_fmt_num(team_projection.get('away_mean'), 1)} - {home_team} {_fmt_num(team_projection.get('home_mean'), 1)}",
                    f"Margin: {_fmt_num(team_projection.get('margin_mean'), 2)} (home perspective)",
                    f"Simulations: {match.get('simulations') or '-'}",
                ],
            },
            _box_score_panel(
                away_team=away_team,
                home_team=home_team,
                away_abbr=_abbr(away_team, league),
                home_abbr=_abbr(home_team, league),
                volume=volume,
                live_state=live_state,
            ),
            _player_box_score_panel(
                away_team=away_team,
                home_team=home_team,
                top_props=top_props,
                live_state=live_state,
            ),
            {
                "eyebrow": "Top prop signals",
                "title": "Anytime scorer / shots leaders",
                "body": "Highest anytime-goalscorer probability players from the simulated player-props pass.",
                "items": [_prop_line(row) for row in top_props[:5]] or ["No player-prop rows were available for this match."],
            },
        ],
    }


def week_games(league: str, week: int, season: int) -> list[dict[str, Any]]:
    """The real fixture list for a week (from the schedule artifact),
    enriched with SoccerSim's simulated output where it exists -- a fixture
    on the schedule that hasn't been simulated yet still shows up, as a
    lightweight "not yet simulated" card, instead of silently disappearing.
    """
    fixtures = week_matches(league, season, week)
    if not fixtures:
        return []
    simulated_by_event_id: dict[str, dict[str, Any]] = {}
    for date_str in week_date_list(league, season, week):
        payload = recommendations_payload(league, date_str) or {}
        for match in payload.get("matches") if isinstance(payload.get("matches"), list) else []:
            event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
            if event_id:
                simulated_by_event_id[event_id] = match

    games: list[dict[str, Any]] = []
    for fixture in fixtures:
        event_id = str(fixture.get("event_id") or "").strip()
        simulated = simulated_by_event_id.get(event_id)
        if simulated is not None:
            games.append(_match_to_game(simulated, league=league, week=week, season=season))
        else:
            games.append(_unsimulated_game(fixture, league=league, week=week, season=season))
    return games


def build_cards_page_context(league: str, week: int | None = None, season: int | None = None) -> dict[str, Any]:
    league = normalize_league(league)
    resolved_season = int(season) if season else default_season(league)
    weeks = available_weeks(league, resolved_season)
    resolved_week = int(week) if week else default_week(league, resolved_season)

    games = week_games(league, resolved_week, resolved_season)
    simulated_count = sum(1 for game in games if game.get("panels", [{}])[0].get("eyebrow") == "Match projection")

    query = f"?week={resolved_week}&season={resolved_season}"
    prev_week = max([w for w in weeks if w < resolved_week], default=resolved_week)
    next_week = min([w for w in weeks if w > resolved_week], default=resolved_week)
    source_path = str(schedule_path(league, resolved_season))
    league_label = league_display_name(league)

    return apply_game_board_contract(
        {
            "date": week_label(league, resolved_season, resolved_week),
            "requested_date": query,
            "prev_date": str(prev_week),
            "next_date": str(next_week),
            "control_action": f"/soccer/{league}/cards",
            "controls_prev_href": f"/soccer/{league}/cards?week={prev_week}&season={resolved_season}",
            "controls_next_href": f"/soccer/{league}/cards?week={next_week}&season={resolved_season}",
            "control_value": str(resolved_week),
            "control_label": "Week",
            "control_type": "number",
            "control_name": "week",
            "hidden_fields": [{"name": "season", "value": str(resolved_season)}],
            # No query_suffix: switching leagues should land on that league's
            # own default week/season, not carry the current league's ?week=
            # over (e.g. MLS's week 17 landing EPL on ITS week 17, when EPL's
            # own current week is 1) -- build_cards_page_context already
            # resolves default_week()/default_season() for a bare URL.
            "extra_controls": [league_select_control(league, page_path="/cards")],
            "module_links": build_module_links(league, resolved_week, resolved_season, "Cards"),
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": game["detail"],
                }
                for game in games
            ],
            "source_path": source_path,
            "source_title": f"{league_label} SoccerSim schedule + artifacts" if games else f"{league_label} schedule unavailable",
            "empty_state": {
                "eyebrow": f"{league_label} cards",
                "title": "No scheduled matches were available for this week",
                "body": "The cards board reads the SoccerSim-generated schedule artifact for this league/season, and none was available.",
                "list_items": [
                    f"Requested week: {resolved_week} (season {resolved_season})",
                    f"Run scripts/build_soccer_schedule.py --league {league} --season {resolved_season} to populate the season schedule.",
                ],
            } if not games else None,
            "using_sample_data": False,
            "route_path": f"/soccer/{league}/cards",
            "intro_title": f"{league_label} Cards",
            "intro_body": f"{league_label} cards show the full real schedule for the selected week, with SoccerSim's simulated match and player-prop outputs layered on top where available.",
            "cards_control_links": [
                {"label": "Props", "href": f"/soccer/{league}/props{query}"},
                {"label": "Live Lens", "href": f"/soccer/{league}/live-lens{query}"},
            ],
            "header_stats": [
                {"label": "Matches this week", "value": str(len(games))},
                {"label": "Simulated", "value": str(simulated_count)},
                {"label": "Weeks available", "value": str(len(weeks) or "-")},
                {"label": "League", "value": league_label},
            ],
            "cards_stylesheet": None,
            "cards_grid_class": "cards-grid",
            "show_source_summary": True,
            "show_intro": True,
            "active_sport_name": "Soccer",
        },
        sport="soccer",
        module="cards",
        source_kind="artifact_backed",
        live_lens_integrated=True,
    )
