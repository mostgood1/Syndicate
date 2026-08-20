from __future__ import annotations

from datetime import datetime
from datetime import timezone
from typing import Any

from syndicate.features.shared.timezone import CENTRAL_TIMEZONE
from syndicate.features.shared.timezone import central_today_iso
from syndicate.features.soccer.sources import available_weeks
from syndicate.features.soccer.sources import build_module_links
from syndicate.features.soccer.sources import default_season
from syndicate.features.soccer.sources import default_week
from syndicate.features.soccer.sources import LEAGUE_DISPLAY_NAMES
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
from syndicate.features.soccer.props import _normalize_player_name
from syndicate.features.soccer.props import _prop_picks_by_player


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


_ABBR_MISSES_LOGGED: set[tuple[str, str]] = set()


def _abbr(team: str, league: str) -> str:
    """The club's directory tri-code, or a readable label that is NOT one.

    The old fallback built an all-caps initialism from the club name, which is
    indistinguishable from a directory-sourced tri-code -- and soccer tri-codes
    already collide across leagues, which `game_chip_scoreboard._side_name`
    documents ("`STL` is both Standard Liege and St. Louis CITY SC"). Measured
    2026-08-11: `_abbr('Leeds', 'mls')` returned `LEE`, and `LEE` appears in
    exactly one file in the repo -- `epl_team_branding.csv`, as Leeds United.
    Nothing downstream could tell an invented `LEE` from the real one, and
    `abbr` is the chip join's documented last-resort key.

    So a directory miss now yields a Title-Case short name. It cannot be
    mistaken for a tri-code by a reader or by a join, and the miss is logged
    once per club so the branding-CSV gap is findable rather than papered over.
    `_team_key_variants` (`#355`) removed the common cause of a miss -- accent
    and club-prefix spellings -- leaving this path for clubs genuinely absent
    from the league's branding snapshot.
    """
    directory_team = team_by_name(league, team)
    if directory_team and str(directory_team.get("abbreviation") or "").strip():
        return str(directory_team["abbreviation"]).strip().upper()
    tokens = [token for token in str(team or "").replace("&", " ").split() if token]
    if not tokens:
        return "TBD"
    key = (str(league or ""), " ".join(tokens))
    if key not in _ABBR_MISSES_LOGGED:
        _ABBR_MISSES_LOGGED.add(key)
        print(f"[soccer_cards] TEAM_NOT_IN_BRANDING league={league} team={' '.join(tokens)}", flush=True)
    longest = max(tokens, key=len)
    return longest[:8].title()


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


# A match cannot have started before its own kickoff. Tolerance is generous on
# purpose: the cost of the two errors is NOT symmetric. Suppressing a genuinely
# live match for a few minutes costs a stale badge; trusting a bogus `post`
# costs a settled-looking card and a withheld edge on a game nobody has played.
# 30 minutes covers listed-kickoff drift and clock skew and is still three
# orders of magnitude short of the five-day error this was built for.
_KICKOFF_GRACE_SECONDS = 1800.0


def _effective_status_state(status_state: str, kickoff: Any) -> str:
    """`status_state`, refused where the kickoff cannot support it.

    THE DEFECT, measured on production 2026-08-17 19:3xZ: the chip for
    `eredivisie EXC @ NEC` read `state: "final"`, token `FINAL`, score 0-0 --
    on a fixture kicking off `2026-08-22T18:00:00Z`, FIVE DAYS LATER. Traced
    end to end: `/soccer/eredivisie/api/cards` served that game with
    `live_state: {"final": true}` while all seven sibling fixtures in the same
    league and week read `false`, so this is one corrupt `status_state: "post"`
    in the schedule artifact, not a rendering bug. The git mirror of the same
    event (`401875636`, generated 2026-07-20) still reads `"pre"`.

    NOTHING ANYWHERE CHECKED THIS. `_live_state_block` and `_status_label` both
    trusted `status_state` outright, and every downstream reader trusts them:
    `_game_flags` sets the chip's state from `live_state`, and `live_edge_policy`
    keys on it to decide whether to withhold an edge. A `post` that arrives five
    days early therefore presents an unplayed match as settled.

    Deliberately a REFUSAL, never an inference. This only ever downgrades a
    started/finished claim to `pre`; it cannot promote anything, so it cannot
    reintroduce the "stuck at pregame" failure `_live_state_block` was built to
    fix. An unparseable or absent kickoff leaves the source's own state alone --
    with no clock to check against there is no contradiction to act on, and
    inventing one would be the permissive-on-unknown mistake in reverse.
    """
    state = str(status_state or "pre").strip().lower()
    if state not in {"in", "post"}:
        return state
    kickoff_dt = _parse_kickoff(kickoff)
    if kickoff_dt is None:
        return state
    now = datetime.now(timezone.utc)
    if (kickoff_dt - now).total_seconds() <= _KICKOFF_GRACE_SECONDS:
        return state
    # Counted where it happens, in the same commit as the rule: a filter that
    # trims silently is indistinguishable from a source that got it right.
    print(
        f"[soccer_cards] IMPOSSIBLE_STATUS_STATE_REFUSED state={state} "
        f"kickoff={kickoff_dt.isoformat()} now={now.isoformat()}",
        flush=True,
    )
    return "pre"


def _parse_kickoff(value: Any) -> datetime | None:
    # Naive stamps are read as CENTRAL, matching _format_kickoff_display above.
    # Not a detail: if the guard and the badge disagreed about what a naive
    # kickoff means, a card could read "Final" beside a time that says it has
    # not started, which is the exact contradiction this is here to remove.
    text = str(value or "").strip()
    if not text or "T" not in text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CENTRAL_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _status_label(status_state: str, kickoff: str | None) -> str:
    state = _effective_status_state(status_state, kickoff)
    if state == "post":
        return "Final"
    if state == "in":
        return "Live"
    return _format_kickoff_display(kickoff)


def _live_state_block(status_state: str, kickoff: Any = None) -> dict[str, Any]:
    """The STRUCTURED liveness signal, which soccer knew and never published.

    THE DEFECT THIS FIXES, measured on production 2026-08-16 18:03Z: the soccer
    board reported `live: 0` while **14 matches were past kickoff and 12 carried
    a real score**, and 45 rows served a bettable edge on a game in play or
    already over -- including a `totals 2.5` on GRO @ ADO, which finished 4-1
    almost eight hours earlier. `live_edge_policy` keys on `game.state`, and
    `pregame` is its PERMISSIVE branch, so a match stuck there never has its
    edge withheld.

    WHY IT WAS STUCK. Both readers of liveness want a structured signal and
    soccer published none:

        game_board_contract._infer_live_state  -> sets `shared_is_live`
        game_chip_scoreboard._game_flags       -> sets the chip's `state`

    Both read `status`/`live_state` as DICTS. Soccer's `status` is a display
    STRING (`"Sat, Aug 15 - 7:30 PM CT"`), and `live_state`, `gameState` and
    `status_badge` were all absent. Dumped from the real provider on
    2026-08-16: `_game_flags` returned `(False, False)` for all 90 soccer
    chips while MLB returned 9 live of 15. With no structured signal both
    readers fall back to a token search over `detail`/`summary` prose -- and
    `_infer_live_state`'s `final_tokens` contains **"scheduled"**, so soccer's
    own placeholder wording actively forced a not-live verdict.

    `status_state` was RIGHT THERE the whole time. `_match_to_game` already
    branches on it to decide whether to fetch live stats. It simply never put
    it on the game dict in a shape anything downstream could read.

    Deliberately sport-local: emitting this dict fixes both readers with no
    change to any shared eight-sport predicate. Widening `_game_flags` to infer
    liveness from kickoff+score was the alternative and is strictly more
    dangerous -- a wrong `live` costs exactly as much as a wrong `pregame`, and
    it would have moved MLB, WNBA, NFL and NCAAF to chase a soccer bug.

    NO TEXT STATUS IS EMITTED HERE ON PURPOSE. `_game_flags` folds
    `live_state.get("status")` into a substring haystack; putting a display
    string in it would reintroduce exactly the prose-matching this replaces.
    The booleans are read first by both consumers, so they are all that is
    needed and all that is offered.

    `kickoff` is optional so the one caller that has no timestamp to offer keeps
    working unchanged; see `_effective_status_state` for what it buys when
    present. It defaults to None rather than being required because a missing
    kickoff and a future one are different facts and only the second is a
    contradiction.
    """
    state = _effective_status_state(status_state, kickoff)
    return {
        # `final` wins over `in_progress` in both readers anyway, but stating
        # both explicitly keeps this readable as a state machine rather than as
        # two independent flags that could contradict each other.
        "in_progress": state == "in",
        "final": state == "post",
    }


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


def _prop_line(row: dict[str, Any], pick: dict[str, Any] | None = None) -> str:
    name = str(row.get("player_name") or "Player").strip()
    team = str(row.get("team") or "").strip()
    scorer_prob = _fmt_pct(row.get("anytime_scorer_probability"))
    shots = _fmt_num(row.get("expected_shots"), 1)
    base = f"{name} ({team}) | Anytime scorer {scorer_prob} | xShots {shots}"
    if not pick:
        return base
    # The price and edge were ALREADY being computed -- by
    # `build_soccer_picks.py::build_prop_picks`, and rendered on
    # `/soccer/<league>/props` as "Odds +150 | Model probability 25.4% |
    # Edge -14.6%". The CARD showed only the simulated probability, so the
    # one number that says whether a prop is worth betting was one page away
    # from the prop itself. Same join key, same source rows.
    odds = _fmt_odds(pick.get("price"))
    edge = _safe_float(pick.get("edge"))
    parts = [base]
    if odds:
        parts.append(f"Odds {odds}")
    if edge is not None:
        parts.append(f"Edge {edge * 100.0:+.1f}%")
    return " | ".join(parts)


def _prop_rows_with_market(top_props: list, prop_picks: dict) -> list:
    """Prop rows joined to their captured market price, newest-first by edge.

    Rows are returned WITHOUT `is_synthesized`, which matters: the shared
    contract's `_build_prop_status_rows` drops every synthesized row, so
    soccer's props-status table rendered empty on every card. A row carrying
    its own price and edge has something of its own to say, which is exactly
    the bar that filter documents.
    """
    candidates = []
    for row in top_props:
        if not isinstance(row, dict):
            continue
        pick = prop_picks.get(_normalize_player_name(row.get("player_name")))
        candidates.append((row, pick))
    # If NOTHING in this match has a captured price, saying so once beats
    # saying it on every row. Measured 2026-08-20 after the first cut of this
    # function: "No market price captured" rendered 10 times on one card --
    # a per-row note that is really a per-match fact, which is the same
    # wasted-space shape as the matchup string repeated across four tiles.
    # When SOME rows are priced the marker earns its place, because then it
    # discriminates between rows instead of restating the section.
    any_priced = any(pick and _safe_float(pick.get("price")) is not None for _, pick in candidates)
    rows = []
    for row, pick in candidates:
        model_p = _safe_float(row.get("anytime_scorer_probability"))
        edge = _safe_float((pick or {}).get("edge"))
        odds = _fmt_odds((pick or {}).get("price"))
        detail_parts = []
        if odds:
            detail_parts.append(f"Odds {odds}")
        if edge is not None:
            detail_parts.append(f"Edge {edge * 100.0:+.1f}%")
        if not detail_parts and any_priced:
            detail_parts.append("No price")
        rows.append(
            {
                "heading": "Anytime goalscorer" if any_priced else "Anytime goalscorer (model only)",
                "name": f"{str(row.get('player_name') or 'Player').strip()} ({row.get('team') or '-'})",
                "value": _fmt_pct(model_p),
                "detail": " | ".join(detail_parts),
                "_edge": edge if edge is not None else float("-inf"),
            }
        )
    rows.sort(key=lambda item: item["_edge"], reverse=True)
    for row in rows:
        row.pop("_edge", None)
    return rows


def _result_text(away_team: str, home_team: str, away_score: Any, home_score: Any) -> str | None:
    away_goals = _safe_float(away_score)
    home_goals = _safe_float(home_score)
    if away_goals is None or home_goals is None:
        return None
    return f"{away_team} {away_goals:.0f} - {home_team} {home_goals:.0f}"


def _placeholder_summary(*, away_team, home_team, week, status_state, away_score, home_score) -> str:
    if status_state == "post":
        result = _result_text(away_team, home_team, away_score, home_score)
        if result:
            return f"Final: {result}. This match was not simulated, so there is no model comparison for it."
        return f"{away_team} at {home_team} has finished. No final score was published for it."
    if status_state == "in":
        result = _result_text(away_team, home_team, away_score, home_score)
        if result:
            return f"In progress: {result}. This match was not simulated, so there is no live model line for it."
    return f"{away_team} at {home_team} is on the schedule for Week {week} but has not been simulated yet."


def _placeholder_panels(*, away_team, home_team, league, date_str, status_state, away_score, home_score) -> list:
    """What to show for a match with no sim output.

    Three genuinely different cases were collapsed into one before: a FINISHED
    match, a LIVE match, and a fixture nobody has simulated. Only the third
    wants the operator instruction, and printing it on the other two put a
    build command where a reader was looking for a result.
    """
    result = _result_text(away_team, home_team, away_score, home_score)
    if status_state == "post" and result:
        return [
            {
                "eyebrow": "Final result",
                "title": f"{away_team} @ {home_team}",
                "body": "The match as played. No simulation was run for this fixture, so no model comparison is available.",
                "items": [f"Final score: {result}"],
                "table_groups": [
                    {
                        "heading": "Final",
                        "rows": [
                            {"name": _abbr(away_team, league), "detail": away_team, "value": _fmt_num(_safe_float(away_score), 0)},
                            {"name": _abbr(home_team, league), "detail": home_team, "value": _fmt_num(_safe_float(home_score), 0)},
                        ],
                    }
                ],
            }
        ]
    if status_state == "in" and result:
        return [
            {
                "eyebrow": "Live score",
                "title": f"{away_team} @ {home_team}",
                "body": "The score as it stands. No simulation was run for this fixture, so no live model line is available.",
                "items": [f"Current score: {result}"],
            }
        ]
    return [
        {
            "eyebrow": "Not yet simulated",
            "title": f"{away_team} @ {home_team}",
            "body": f"This fixture is on the real {league_display_name(league)} schedule for {date_str}, but SoccerSim has not simulated it yet.",
            "items": [
                f"Run scripts/build_soccer_artifacts.py --league {league} --date {date_str} to populate this match.",
            ],
        }
    ]


def _unsimulated_game(fixture: dict[str, Any], *, league: str, week: int, season: int) -> dict[str, Any]:
    home_team = str(fixture.get("home_team") or "Home").strip() or "Home"
    away_team = str(fixture.get("away_team") or "Away").strip() or "Away"
    event_id = str(fixture.get("event_id") or "").strip()
    status_state = _effective_status_state(fixture.get("status_state") or "pre", fixture.get("date"))
    date_str = str(fixture.get("date") or "")[:10]
    return {
        "gamePk": event_id or f"{league}_{date_str}_{home_team}_{away_team}".replace(" ", "_"),
        "event_id": event_id,
        "league": league,
        "league_display": league_display_name(league),
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
        "market_tiles": _market_tiles(
            away_abbr=_abbr(away_team, league),
            home_abbr=_abbr(home_team, league),
            win_prob={},
            total_distribution={},
            team_projection={},
            betting={},
            top_props=[],
            live_state_block=_live_state_block(status_state, fixture.get("date")),
            away_score=fixture.get("away_score"),
            home_score=fixture.get("home_score"),
        ),
        # THE PLACEHOLDER NEEDS THIS TOO, and it is the more dangerous of the
        # two producers to leave out. Its `summary` ends "...has not been
        # simulated yet" and its panel body says "on the real schedule for
        # <date>" -- prose that `_infer_live_state` scans, where `final_tokens`
        # contains "scheduled". So an unsimulated fixture that has actually
        # kicked off was being pinned not-live by its own placeholder wording.
        # An unsimulated match is still a real match that can start and finish.
        "live_state": _live_state_block(status_state, fixture.get("date")),
        "detail": date_str or league_display_name(league),
        "scheduled_start_utc": fixture.get("date"),
        "summary": _placeholder_summary(
            away_team=away_team,
            home_team=home_team,
            week=week,
            status_state=status_state,
            away_score=fixture.get("away_score"),
            home_score=fixture.get("home_score"),
        ),
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
        "panels": _placeholder_panels(
            away_team=away_team,
            home_team=home_team,
            league=league,
            date_str=date_str,
            status_state=status_state,
            away_score=fixture.get("away_score"),
            home_score=fixture.get("home_score"),
        ),
    }


def _real_live_score(live_state: dict[str, Any] | None, side: str) -> Any:
    """A live score ONLY when the live poller actually reported one.

    Deliberately does NOT fall back to the recommendations artifact's
    `live_{side}_score`: those are the constant "0" placeholder described at
    the call site. A missing score must read as missing, never as nil-nil.
    """
    if not isinstance(live_state, dict):
        return None
    for key in (f"{side}_score", f"{side}_goals", side):
        value = live_state.get(key)
        if isinstance(value, dict):
            value = value.get("score", value.get("goals"))
        if value is None or isinstance(value, bool):
            continue
        text = str(value).strip()
        if text and text.lstrip("-").isdigit():
            # An int, not the artifact's stringly-typed "0": the caller puts
            # this straight into `away.score`/`home.score`, and the template
            # guards on `is not none`, so a real 0 must stay a real 0.
            return int(text)
    return None


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
    #
    # #150 follow-up. This originally only captured p_home_win/p_away_win/
    # total/home_spread -- enough for game_board_contract.py's own sim-vs-
    # line display, but not enough for home.py's cross-sport
    # _game_bet_candidates_from_game, which reads this same dict to build
    # the board's "game" candidates. That function needs real price/edge
    # (home_ml/away_ml/*_ev) to show anything but blank odds, and gates
    # Spread-candidate creation on home_puck_line/away_puck_line specifically
    # (not home_spread, which this function set instead) -- so soccer's real,
    # already-graded picks never produced a single Spread candidate on the
    # cross-sport opportunities board even once the game itself was hydrated.
    # Adds those fields from the same picks rows, without changing the
    # existing p_home_win/p_away_win/total/home_spread keys anything else
    # already reads.
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
        price = _safe_float(row.get("price"))
        ev = _safe_float(row.get("ev"))
        prob = _safe_float(row.get("market_probability"))
        if market == "ML":
            if side == "home":
                if prob is not None:
                    betting["p_home_win"] = prob
                if price is not None:
                    betting["home_ml"] = price
                if ev is not None:
                    betting["home_ml_ev"] = ev
            elif side == "away":
                if prob is not None:
                    betting["p_away_win"] = prob
                if price is not None:
                    betting["away_ml"] = price
                if ev is not None:
                    betting["away_ml_ev"] = ev
        elif market == "TOTAL":
            line = _safe_float(line_text)
            if line is not None and "total" not in betting:
                betting["total"] = line
            if side == "over":
                if price is not None:
                    betting.setdefault("odds", price)
                if prob is not None:
                    betting["p_total_over"] = prob
                if ev is not None:
                    betting["over_ev"] = ev
            elif side == "under":
                if prob is not None:
                    betting["p_total_under"] = prob
                if ev is not None:
                    betting["under_ev"] = ev
        elif market == "SPREAD":
            line = _safe_float(line_text)
            if line is None:
                continue
            # Multiple books quote different Asian-handicap lines; the one
            # closest to pick'em is the most representative single line to
            # show, same convention a real odds board defaults to.
            if side == "home":
                current = betting.get("home_spread")
                if current is None or abs(line) < abs(current):
                    betting["home_spread"] = line
                    betting["home_puck_line"] = line
                if prob is not None:
                    betting["p_home_cover"] = prob
                if ev is not None:
                    betting["home_spread_ev"] = ev
            elif side == "away":
                current = betting.get("away_puck_line")
                if current is None or abs(line) < abs(current):
                    betting["away_puck_line"] = line
                if prob is not None:
                    betting["p_away_cover"] = prob
                if ev is not None:
                    betting["away_spread_ev"] = ev
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


def _fmt_odds(price):
    number = _safe_float(price)
    if number is None:
        return ""
    return f"+{number:.0f}" if number > 0 else f"{number:.0f}"


def _fmt_line(value):
    number = _safe_float(value)
    if number is None:
        return ""
    return f"+{number:g}" if number > 0 else f"{number:g}"


def _edge_points(model_prob: Any, market_prob: Any) -> float | None:
    """Model probability minus the market's devigged implied probability.

    Deliberately NOT the picks pipeline's `ev` column, even though
    `_market_data_for_match` already carries it. `build_soccer_picks.py:131`
    computes `ev = model_prob * decimal - 1`, where its `model_prob` comes from
    the picks run -- a DIFFERENT vintage than the sim payload this card
    renders. Measured 2026-08-20 on COV@ARS: the card's own sim says away win
    7.0%, while `away_ml_ev` of 0.575 at +1400 implies about 10.5%. Printing
    the card's probability beside that EV would put two models' numbers under
    one heading and invite the reader to treat them as one calculation. Both
    fields stay on `betting` for anything that wants the pipeline's number;
    the TILE compares like with like.
    """
    model = _safe_float(model_prob)
    market = _safe_float(market_prob)
    if model is None or market is None:
        return None
    return (model - market) * 100.0


def _fmt_edge(points: float | None) -> str:
    if points is None:
        return "-"
    return f"{points:+.1f} pts"


def _top_play_rows(
    *,
    away_abbr: str,
    home_abbr: str,
    away_team: str,
    home_team: str,
    team_projection: dict,
    betting: dict,
    win_prob: dict,
    volume: dict,
) -> list:
    """Structured top-play rows: `name` is the thing, `value` is its number.

    The generic `_build_top_play_rows` scrapes display panels, and on soccer it
    emitted `{"name": "Projected score", "value": "Coventry City @ Arsenal",
    "detail": "Coventry City 0.8 - Arsenal 2.7"}` -- the matchup in the value
    column, the actual number demoted to detail, and the same matchup string
    repeated as every row's `heading`. Measured 2026-08-20: three of the six
    rows had the matchup as their value.
    """
    rows = []
    away_mean = _safe_float(team_projection.get("away_mean"))
    home_mean = _safe_float(team_projection.get("home_mean"))
    if away_mean is not None and home_mean is not None:
        rows.append(
            {
                "heading": "Projection",
                "name": "Projected score",
                "value": f"{away_abbr} {away_mean:.1f} - {home_abbr} {home_mean:.1f}",
                "detail": f"{away_team} at {home_team}",
            }
        )
    margin = _safe_float(team_projection.get("margin_mean"))
    if margin is not None:
        rows.append(
            {
                "heading": "Projection",
                "name": "Projected margin",
                "value": _fmt_num(margin, 2),
                "detail": "Home perspective",
            }
        )
    total_mean = _safe_float(team_projection.get("total_mean"))
    if total_mean is not None:
        line = _safe_float(betting.get("total"))
        rows.append(
            {
                "heading": "Total goals",
                "name": "Model total",
                "value": _fmt_num(total_mean, 2),
                "detail": f"Market line {line:g}" if line is not None else "No market total captured",
            }
        )
    for side, abbr, team, ml_key, prob_key in (
        ("home", home_abbr, home_team, "home_ml", "p_home_win"),
        ("away", away_abbr, away_team, "away_ml", "p_away_win"),
    ):
        model_p = _safe_float(win_prob.get(side))
        market_p = _safe_float(betting.get(prob_key))
        price = betting.get(ml_key)
        if model_p is None:
            continue
        if market_p is not None:
            detail = f"Market {_fmt_pct(market_p)} | Edge {_fmt_edge(_edge_points(model_p, market_p))}"
        else:
            detail = "No market price captured"
        odds = _fmt_odds(price)
        rows.append(
            {
                "heading": "Moneyline",
                "name": f"{abbr} win{f' ({odds})' if odds else ''}",
                "value": _fmt_pct(model_p),
                "detail": detail,
            }
        )
    draw_p = _safe_float(win_prob.get("draw"))
    if draw_p is not None:
        rows.append({"heading": "Moneyline", "name": "Draw", "value": _fmt_pct(draw_p), "detail": "Three-way market"})
    for side, abbr, team in (("away", away_abbr, away_team), ("home", home_abbr, home_team)):
        shots = _safe_float(volume.get(f"{side}_shots"))
        sot = _safe_float(volume.get(f"{side}_shots_on_target"))
        corners = _safe_float(volume.get(f"{side}_corners"))
        if shots is None and sot is None and corners is None:
            continue
        rows.append(
            {
                "heading": "Projected volume",
                "name": f"{abbr} shots / SOT / corners",
                "value": f"{_fmt_num(shots, 1)} / {_fmt_num(sot, 1)} / {_fmt_num(corners, 1)}",
                "detail": team,
            }
        )
    return rows


def _market_tiles(
    *,
    away_abbr: str,
    home_abbr: str,
    win_prob: dict,
    total_distribution: dict,
    team_projection: dict,
    betting: dict,
    top_props: list,
    live_state_block: dict,
    prop_picks: dict | None = None,
    away_score: Any,
    home_score: Any,
) -> list:
    """Four BET tiles, mirroring `mlb/cards.py::_market_tiles`.

    Replaces the generic fallback in `game_board_contract.py` (`metrics[:4]`),
    which rendered a bare probability per tile with the matchup string as all
    four sub-labels -- four tiles carrying one fact and three repetitions of
    the card's own title. Measured 2026-08-20 on production: soccer's payload
    already held `home_ml -590`, `away_ml +1400`, `total 2.5`, `spread -1.5`
    and both sides' devigged market probabilities, and not one reached a tile.
    That fallback also truncated `metrics` to 4, silently dropping BTTS and
    Over 2.5.

    Every tile states its own provenance in the sub-line, because soccer's
    market coverage is genuinely uneven -- MLS carried `betting = {}` on the
    same sweep EPL carried a full book. A tile with no market says so, rather
    than showing a model number under a market-shaped heading.
    """
    final = bool(live_state_block.get("final"))
    in_progress = bool(live_state_block.get("in_progress"))

    def tile(label, title, sub):
        return {"label": label, "title": title, "sub": sub}

    if final:
        # A finished match has a result, not a projection. The old path sent
        # these through the unsimulated placeholder and rendered "-" in all
        # four tiles -- 25 of 31 MLS cards on the 2026-08-20 board.
        away_goals = _safe_float(away_score)
        home_goals = _safe_float(home_score)
        if away_goals is not None and home_goals is not None:
            if home_goals > away_goals:
                result = f"{home_abbr} win"
            elif away_goals > home_goals:
                result = f"{away_abbr} win"
            else:
                result = "Draw"
            return [
                tile("Final", f"{away_abbr} {away_goals:.0f} - {home_abbr} {home_goals:.0f}", result),
                tile("Total goals", f"{away_goals + home_goals:.0f}", "Actual"),
                tile("Result", result, "Full time"),
                tile("Status", "Final", "Match complete"),
            ]

    model_home = _safe_float(win_prob.get("home"))
    model_draw = _safe_float(win_prob.get("draw"))
    model_away = _safe_float(win_prob.get("away"))

    # --- Tile 1: the 1X2 side the model likes most, versus the market ---
    sides = [
        (home_abbr, model_home, _safe_float(betting.get("p_home_win")), betting.get("home_ml")),
        (away_abbr, model_away, _safe_float(betting.get("p_away_win")), betting.get("away_ml")),
    ]
    priced = [row for row in sides if row[1] is not None and row[2] is not None]
    if priced:
        abbr, model_p, market_p, price = max(priced, key=lambda row: (row[1] or 0.0) - (row[2] or 0.0))
        ml_title = " ".join(part for part in (f"{abbr} ML", _fmt_odds(price)) if part)
        ml_sub = f"Model {_fmt_pct(model_p)} | Market {_fmt_pct(market_p)} | Edge {_fmt_edge(_edge_points(model_p, market_p))}"
        ml_label = "Best 1X2 edge"
    elif model_home is not None:
        best_abbr, best_p = home_abbr, model_home
        if model_away is not None and model_away > best_p:
            best_abbr, best_p = away_abbr, model_away
        if model_draw is not None and model_draw > best_p:
            best_abbr, best_p = "Draw", model_draw
        ml_title = f"{best_abbr} {_fmt_pct(best_p)}"
        ml_sub = "Model only -- no market price captured"
        ml_label = "1X2 lean"
    else:
        ml_title = "No 1X2 read"
        ml_sub = "Not simulated"
        ml_label = "1X2"

    # --- Tile 2: total goals ---
    total_line = _safe_float(betting.get("total"))
    over_price = betting.get("odds")
    model_total = _safe_float(team_projection.get("total_mean"))
    model_over_25 = _safe_float(total_distribution.get("over_2_5_probability"))
    if total_line is not None:
        selection = "OVER" if (model_total is not None and model_total > total_line) else "UNDER"
        market_p = _safe_float(betting.get("p_total_over" if selection == "OVER" else "p_total_under"))
        total_title = " ".join(part for part in (selection, f"{total_line:g}", _fmt_odds(over_price)) if part)
        if model_total is not None and market_p is not None:
            total_sub = f"Model {_fmt_num(model_total, 2)} | Line {total_line:g} | Market {_fmt_pct(market_p)}"
        elif model_total is not None:
            total_sub = f"Model {_fmt_num(model_total, 2)} | Line {total_line:g}"
        else:
            total_sub = f"Line {total_line:g}"
        total_label = "Total goals"
    elif model_total is not None:
        total_title = _fmt_num(model_total, 2)
        total_sub = f"Over 2.5 {_fmt_pct(model_over_25)} model" if model_over_25 is not None else "Model only -- no market total"
        total_label = "Projected total"
    else:
        total_title = "No total"
        total_sub = "Not simulated"
        total_label = "Total goals"

    # --- Tile 3: the handicap. NO model cover probability is published, so
    # this shows the projected MARGIN against the line rather than inventing a
    # cover number. Lane F's rule: an absent probability renders as absent.
    home_line = _safe_float(betting.get("home_spread"))
    margin = _safe_float(team_projection.get("margin_mean"))
    if home_line is not None:
        favourite = home_abbr if home_line < 0 else away_abbr
        shown_line = home_line if home_line < 0 else -home_line
        spread_title = f"{favourite} {_fmt_line(shown_line)}"
        if margin is not None:
            cushion = margin + home_line
            spread_sub = f"Proj margin {_fmt_num(margin, 2)} | vs line {_fmt_num(cushion, 2)}"
        else:
            spread_sub = "No projected margin"
        spread_label = "Handicap"
    elif margin is not None:
        spread_title = f"{_fmt_num(margin, 2)} margin"
        spread_sub = "Model only -- no handicap captured"
        spread_label = "Projected margin"
    else:
        spread_title = "No handicap"
        spread_sub = "Not simulated"
        spread_label = "Handicap"

    # --- Tile 4: the leading player prop ---
    picks = prop_picks or {}
    priced = [
        (row, picks.get(_normalize_player_name(row.get("player_name"))))
        for row in top_props
        if isinstance(row, dict)
    ]
    with_edge = [(row, pick) for row, pick in priced if pick and _safe_float(pick.get("edge")) is not None]
    if with_edge:
        # The best EDGE, not the highest probability: a 40% scorer at a price
        # that implies 50% is not the play on the card, and showing it as the
        # headline prop is how a model number gets read as a recommendation.
        lead, pick = max(with_edge, key=lambda item: _safe_float(item[1].get("edge")) or 0.0)
        edge = _safe_float(pick.get("edge")) or 0.0
        odds = _fmt_odds(pick.get("price"))
        prop_title = " ".join(
            part for part in (f"{str(lead.get('player_name') or 'Player').strip()} anytime", odds) if part
        )
        prop_sub = f"Model {_fmt_pct(lead.get('anytime_scorer_probability'))} | Edge {edge * 100.0:+.1f}%"
        prop_label = "Best prop edge"
    elif priced:
        lead = priced[0][0]
        prop_title = f"{str(lead.get('player_name') or 'Player').strip()} anytime"
        prop_sub = f"Model {_fmt_pct(lead.get('anytime_scorer_probability'))} | {_fmt_num(lead.get('expected_shots'), 1)} xSh"
        prop_label = "Top prop"
    else:
        prop_title = "No prop rows"
        prop_sub = "Player props not simulated"
        prop_label = "Top prop"

    if in_progress:
        ml_label = f"LIVE {ml_label}"

    return [
        tile(ml_label, ml_title, ml_sub),
        tile(total_label, total_title, total_sub),
        tile(spread_label, spread_title, spread_sub),
        tile(prop_label, prop_title, prop_sub),
    ]


def _squad_box_sections(
    *,
    squad_props: list,
    prop_picks: dict,
    away_team: str,
    home_team: str,
    away_abbr: str,
    home_abbr: str,
    live_state: dict | None,
) -> list:
    """One stat table per side, every player the sim published.

    THE DATA WAS ALREADY THERE AND ON THE WRONG SIDE OF A TRUNCATION.
    `cards.py` read `match["top_props"]`, which the artifact builder caps at
    EIGHT. The full roster lives at the payload's TOP level as
    `player_props` -- 28 players for COV@ARS on 2026-08-21, each with 13
    fields including the `_if_playing` variants and `expected_minutes_share`.
    `/soccer/<league>/props` has been reading that key all along; the card
    never did. Measured 2026-08-20: MLB's box tab carries 566 leaf values
    (full batting and pitching lines, real and simulated) against soccer's
    30.

    Columns mirror what MLB's box actually shows -- identity, then a row of
    numbers -- rather than the name/detail/value list, which could only ever
    surface three of thirteen fields.

    `Odds`/`Edge` come from the same `build_soccer_picks` join the props page
    and the prop tiles use, so a player's edge reads identically wherever it
    appears on the card.
    """
    if not squad_props:
        return []
    columns = ["Player", "Pos", "Min%", "xSh", "xSOT", "Scorer%", "Odds", "Edge"]
    sections = []
    for side, team_name, abbr in (("away", away_team, away_abbr), ("home", home_team, home_abbr)):
        rows = [row for row in squad_props if isinstance(row, dict) and str(row.get("side") or "") == side]
        if not rows:
            # Stated, not hidden. Soccer's player coverage is genuinely
            # one-sided for some fixtures -- all 28 rows for COV@ARS are
            # Arsenal players, none Coventry. An empty column that says
            # nothing is indistinguishable from a rendering bug.
            sections.append(
                {
                    "title": f"{abbr} squad projections",
                    "body": f"No player projections were published for {team_name} in this match.",
                    "rows": [],
                }
            )
            continue
        rows.sort(key=lambda row: _safe_float(row.get("anytime_scorer_probability")) or 0.0, reverse=True)
        table_rows = []
        for row in rows:
            pick = prop_picks.get(_normalize_player_name(row.get("player_name"))) or {}
            edge = _safe_float(pick.get("edge"))
            table_rows.append(
                [
                    str(row.get("player_name") or "Player").strip(),
                    str(row.get("position") or "-").strip() or "-",
                    _fmt_pct(row.get("expected_minutes_share")),
                    _fmt_num(row.get("expected_shots"), 2),
                    _fmt_num(row.get("expected_shots_on_target"), 2),
                    _fmt_pct(row.get("anytime_scorer_probability")),
                    _fmt_odds(pick.get("price")) or "-",
                    f"{edge * 100.0:+.1f}%" if edge is not None else "-",
                ]
            )
        sections.append(
            {
                "title": f"{abbr} squad projections",
                "body": (
                    f"{len(table_rows)} {team_name} players. Expected minutes share, shots, shots on "
                    "target and anytime-scorer probability from the sim, against the captured price."
                ),
                "columns": columns,
                "table_rows": table_rows,
                "rows": [],
            }
        )
    return sections


def _scoreline_section(scoreline_probabilities: Any, *, away_abbr: str, home_abbr: str) -> dict | None:
    """The most likely exact scorelines.

    `scoreline_probabilities` is published on every simulated match (25
    entries for COV@ARS) and was read by NOTHING on the card. For a sport
    whose correct-score market is a headline market, that is the single
    highest-signal artifact field going unused.

    The keys are `"home-away"` -- confirmed against the payload, where the
    3.24-total Arsenal-favourite match peaks at "3-0" 14.0% and "2-0" 12.7%,
    which is a home-heavy distribution as it must be. Rendered
    away-first to match the card's `AWAY @ HOME` header, so the same match
    never reads in two orders on one card.
    """
    if not isinstance(scoreline_probabilities, dict) or not scoreline_probabilities:
        return None
    ranked = sorted(
        ((str(k), _safe_float(v)) for k, v in scoreline_probabilities.items()),
        key=lambda item: item[1] or 0.0,
        reverse=True,
    )
    table_rows = []
    for key, prob in ranked[:10]:
        if prob is None or "-" not in key:
            continue
        home_goals, _, away_goals = key.partition("-")
        table_rows.append(
            [
                f"{away_abbr} {away_goals.strip()} - {home_abbr} {home_goals.strip()}",
                _fmt_pct(prob),
            ]
        )
    if not table_rows:
        return None
    covered = sum(prob or 0.0 for _, prob in ranked[:10])
    return {
        "kicker": "Correct score",
        "title": "Most likely scorelines",
        "body": f"Top {len(table_rows)} exact scores from the sim, {_fmt_pct(covered)} of all simulated outcomes.",
        "columns": ["Scoreline", "Prob"],
        "table_rows": table_rows,
        "rows": [],
    }


def _match_to_game(
    match: dict[str, Any],
    *,
    league: str,
    week: int,
    season: int,
    squad_props: list | None = None,
) -> dict[str, Any]:
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
    # Resolved ONCE and used for every state-dependent branch below. The live
    # fetch, the score line and the badge previously each re-read the raw
    # `status_state`, so a guard applied to one of them would have left the
    # others still presenting a match its own kickoff says has not started.
    effective_state = _effective_status_state(status_state, match.get("kickoff"))
    live_state = _live_match_state(league, str(match.get("date") or "")[:10], event_id) if effective_state == "in" else None

    betting = _market_data_for_match(league, str(match.get("date") or "")[:10], home_team, away_team)
    prop_picks = _prop_picks_by_player(league, week, season)
    # `live_home_score` / `live_away_score` ARE NOT A SCORE. Measured across
    # every git-tracked recommendations artifact, 2026-08-20: both fields are
    # the string "0" on 12 of 12 sampled matches INCLUDING `status_state ==
    # "pre"` -- fixtures that had not kicked off. The artifact builder writes
    # a placeholder, not a reading, and nine consecutive 0-0 results across a
    # league's completed slate is not a plausible set of soccer scores.
    #
    # Publishing them as `away.score`/`home.score` put a FABRICATED 0-0 on any
    # live match -- the exact failure Lane F removed from seven other sites in
    # `game_board_contract.py`. Soccer has no trustworthy per-match live score
    # in the card payload today, so it publishes NONE and the card renders its
    # empty state. A real score belongs here when the live poller supplies one
    # (`_live_match_state` reads `live_state_payload`, which is where it would
    # arrive); until then absence is the honest value.
    home_score = _real_live_score(live_state, "home")
    away_score = _real_live_score(live_state, "away")

    summary = (
        f"Projected {away_team} {_fmt_num(team_projection.get('away_mean'), 1)} @ {home_team} "
        f"{_fmt_num(team_projection.get('home_mean'), 1)} (total {_fmt_num(team_projection.get('total_mean'), 1)}). "
        f"Win prob: {home_team} {_fmt_pct(win_prob.get('home'))} / Draw {_fmt_pct(win_prob.get('draw'))} / "
        f"{away_team} {_fmt_pct(win_prob.get('away'))}."
    )

    return {
        "gamePk": event_id or f"{league}_{match.get('date')}_{home_team}_{away_team}".replace(" ", "_"),
        "event_id": event_id,
        "league": league,
        "league_display": league_display_name(league),
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
        # `effective_state`, not `status_state`: already guarded above, so these
        # two re-derive nothing and the refusal is logged once per match rather
        # than once per reader.
        "status": _status_label(effective_state, match.get("kickoff")),
        # Structured liveness alongside the display string above. See
        # `_live_state_block`: `status` is prose and every downstream reader
        # wants a dict, which is why soccer sat at 100% `pregame`.
        "live_state": _live_state_block(effective_state, match.get("kickoff")),
        # `detail` is the card's "Slate context" slot and every non-live
        # state puts the competition name in it. It used to be overwritten
        # with the score for live/final matches, which both lost the league
        # label and captioned the score with "Slate context". The head now
        # renders `away.score`/`home.score` directly, so this stays constant
        # across states -- one field, one meaning.
        "detail": league_display_name(league),
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
            # The same three-way split the tiles below render. Published here
            # so game_board_contract's probability bar reads the SIM rather
            # than falling through to betting.p_home_win, which is the
            # market's implied number -- the UI audit measured the card
            # showing both, ~250px apart, both labelled "home win"
            # (HOME WIN 77.3% in the tiles vs Home win 81.1% in the bar).
            # Carrying the draw is what stops the bar renormalising a
            # three-way market into a two-way one.
            "win_probability": {
                "home": win_prob.get("home"),
                "draw": win_prob.get("draw"),
                "away": win_prob.get("away"),
            },
        },
        "betting": betting,
        "market_tiles": _market_tiles(
            away_abbr=_abbr(away_team, league),
            home_abbr=_abbr(home_team, league),
            win_prob=win_prob,
            total_distribution=total_distribution,
            team_projection=team_projection,
            betting=betting,
            top_props=top_props,
            prop_picks=prop_picks,
            live_state_block=_live_state_block(effective_state, match.get("kickoff")),
            away_score=away_score,
            home_score=home_score,
        ),
        # Supplied rather than left to `_build_top_play_rows`, whose generic
        # panel-scrape produced rows whose `value` was the MATCHUP STRING and
        # whose real content sat in `name`/`detail` -- so the card rendered
        # "Coventry City @ Arsenal" three times down the value column.
        # `game_board_contract` preserves a non-empty incoming list.
        "shared_headline_section": _scoreline_section(
            match.get("scoreline_probabilities"),
            away_abbr=_abbr(away_team, league),
            home_abbr=_abbr(home_team, league),
        ),
        "shared_box_sections": [
            section
            for section in (
                _squad_box_sections(
                    squad_props=squad_props or [],
                    prop_picks=prop_picks,
                    away_team=away_team,
                    home_team=home_team,
                    away_abbr=_abbr(away_team, league),
                    home_abbr=_abbr(home_team, league),
                    live_state=live_state,
                )
            )
            if section
        ],
        "shared_prop_rows": _prop_rows_with_market(squad_props or top_props, prop_picks),
        "shared_top_play_rows": _top_play_rows(
            away_abbr=_abbr(away_team, league),
            home_abbr=_abbr(home_team, league),
            away_team=away_team,
            home_team=home_team,
            team_projection=team_projection,
            betting=betting,
            win_prob=win_prob,
            volume=volume,
        ),
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
                "body": "Anytime-goalscorer probability against the captured market price, best edge first.",
                "items": [
                    _prop_line(row, prop_picks.get(_normalize_player_name(row.get("player_name"))))
                    for row in top_props[:5]
                ] or ["No player-prop rows were available for this match."],
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
    # `player_props` is a TOP-LEVEL key, not a per-match one, and it carries
    # the full squad where `match["top_props"]` is capped at eight by the
    # artifact builder. Indexed by match_id here so the card can show what
    # `/soccer/<league>/props` has always shown.
    squad_by_match: dict[str, list[dict[str, Any]]] = {}
    for date_str in week_date_list(league, season, week):
        payload = recommendations_payload(league, date_str) or {}
        for match in payload.get("matches") if isinstance(payload.get("matches"), list) else []:
            event_id = str(match.get("event_id") or match.get("match_id") or "").strip()
            if event_id:
                simulated_by_event_id[event_id] = match
        for row in payload.get("player_props") if isinstance(payload.get("player_props"), list) else []:
            if not isinstance(row, dict):
                continue
            match_id = str(row.get("match_id") or "").strip()
            if match_id:
                squad_by_match.setdefault(match_id, []).append(row)

    games: list[dict[str, Any]] = []
    for fixture in fixtures:
        event_id = str(fixture.get("event_id") or "").strip()
        simulated = simulated_by_event_id.get(event_id)
        if simulated is not None:
            match_id = str(simulated.get("match_id") or simulated.get("event_id") or "").strip()
            games.append(
                _match_to_game(
                    simulated,
                    league=league,
                    week=week,
                    season=season,
                    squad_props=squad_by_match.get(match_id) or squad_by_match.get(event_id) or [],
                )
            )
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


# ---------------------------------------------------------------------------
# Cross-league, DATE-scoped board (`soccer-board-mlb-parity`, 2026-08-20).
#
# Every other sport's card board is keyed by DATE. Soccer's was keyed by
# (league, matchweek), and each league runs its own matchweek calendar, so the
# ten leagues resolved to ten different date windows. Measured on production
# 2026-08-20, the "current" week per league covered: EPL Aug 21 only, MLS
# Aug 16-22, Bundesliga Aug 28 only, Serie A Aug 22-28, Belgian Aug 15-21.
# `/soccer` redirected to EPL, so the landing page showed 1 match -- kicking
# off the FOLLOWING day -- out of 92 across the ten leagues, with no surface
# anywhere that answered "what is on today".
#
# This does not replace the per-league week board; that view is the right one
# for planning a matchweek. It adds the view MLB has had all along.
# ---------------------------------------------------------------------------


def _central_slate_date(kickoff: Any) -> str | None:
    """The CENTRAL calendar date a kickoff belongs to.

    Was `str(scheduled_start_utc)[:10]`, and that was wrong in production for
    most of an evening slate. Reported by the user 2026-08-20 and confirmed:
    the board for 2026-08-20 carried EIGHT MLS matches that were played on
    2026-08-19 Central. Their UTC kickoffs are 00:00Z-02:30Z on the 20th --
    a 7:00-9:30 PM Central start on the 19th -- so a UTC date slice files a
    whole evening of North American football onto the following day, and the
    cards arrive already Final.

    `CLAUDE.md` documents this exact trap for NCAAF ("28 of 157 real 2026
    kickoffs were previously filed under their UTC day... the platform's
    display timezone is Central everywhere; `central_today_iso()` is the
    slate clock"), and this function was written against UTC anyway. It is
    also why the fix is a CENTRAL conversion rather than a fixed offset:
    the offset changes with DST and the slate clock does not.

    Reuses `_parse_kickoff`, which already owns the naive-stamp convention
    for this file, rather than adding a second parse that could disagree
    with the status badge about what a kickoff means.
    """
    parsed = _parse_kickoff(kickoff)
    if parsed is None:
        return None
    return parsed.astimezone(CENTRAL_TIMEZONE).date().isoformat()


def _kickoff_sort_key(game: dict[str, Any]) -> tuple:
    """Kickoff order, with live matches first and finals last.

    A soccer date board spans time zones far more than a domestic-sport one --
    a European kickoff and an MLS kickoff on the same date are ~8 hours apart
    -- so plain chronological order buries whatever is actually happening now.
    """
    live_state = game.get("live_state") if isinstance(game.get("live_state"), dict) else {}
    if live_state.get("in_progress"):
        bucket = 0
    elif live_state.get("final"):
        bucket = 2
    else:
        bucket = 1
    return (bucket, str(game.get("scheduled_start_utc") or "~"), str(game.get("gamePk") or ""))


def date_games(date_str: str) -> list[dict[str, Any]]:
    """Every league's matches on one calendar date.

    Resolves each league's own matchweek for the date via `default_week(...,
    reference_date=)` -- the same primitive the per-league board already uses,
    rather than a second week-resolution rule that could disagree with it.
    """
    games: list[dict[str, Any]] = []
    for league in LEAGUE_DISPLAY_NAMES:
        try:
            season = default_season(league)
            week = default_week(league, season, reference_date=date_str)
            for game in week_games(league, week, season):
                if _central_slate_date(game.get("scheduled_start_utc")) != date_str:
                    continue
                games.append(game)
        except Exception as exc:  # noqa: BLE001
            # One league's missing/!malformed schedule artifact must not blank
            # the whole board -- that is the failure shape `learnings.md`
            # records for `poll_active_leagues_for_tick`, where a per-league
            # exception was swallowed into a dict nothing could read. Printed,
            # not swallowed: `print(..., flush=True)` is the only thing that
            # reaches Render's collector (`logger.info` does not).
            print(f"[soccer_date_board] LEAGUE_FAILED league={league} date={date_str} err={exc}", flush=True)
    return sorted(games, key=_kickoff_sort_key)


def build_date_cards_page_context(date_str: str) -> dict[str, Any]:
    from datetime import date as _date
    from datetime import timedelta as _timedelta

    selected = str(date_str or "")[:10]
    try:
        anchor = _date.fromisoformat(selected)
    except ValueError:
        anchor = _date.fromisoformat(central_today_iso())
        selected = anchor.isoformat()
    prev_date = (anchor - _timedelta(days=1)).isoformat()
    next_date = (anchor + _timedelta(days=1)).isoformat()

    games = date_games(selected)
    leagues_present = sorted({str(game.get("league_display") or "") for game in games if game.get("league_display")})
    live_count = sum(
        1 for game in games if isinstance(game.get("live_state"), dict) and game["live_state"].get("in_progress")
    )
    final_count = sum(
        1 for game in games if isinstance(game.get("live_state"), dict) and game["live_state"].get("final")
    )
    simulated_count = sum(1 for game in games if not game.get("is_unsimulated_placeholder"))

    return apply_game_board_contract(
        {
            "date": selected,
            "requested_date": selected,
            "prev_date": prev_date,
            "next_date": next_date,
            "control_action": "/soccer/cards",
            "controls_prev_href": f"/soccer/cards?date={prev_date}",
            "controls_next_href": f"/soccer/cards?date={next_date}",
            "control_value": selected,
            "control_label": "Date",
            "control_type": "date",
            "control_name": "date",
            "hidden_fields": [],
            "module_links": [
                {"label": "All leagues", "href": f"/soccer/cards?date={selected}", "active": True},
                {"label": "Betting board", "href": "/soccer/market-board", "active": False},
                {"label": "Hub", "href": "/soccer/hub", "active": False},
            ],
            "games": games,
            "scoreboard_items": [
                {
                    "target_id": f"game-{game['gamePk']}",
                    "label": f"{game['away']['abbr']} @ {game['home']['abbr']}",
                    "status": str(game.get("league_display") or game.get("detail") or ""),
                }
                for game in games
            ],
            "source_path": "data/soccer_source/<league>/api/schedule + recommendations",
            "source_title": "SoccerSim schedules + artifacts, all leagues",
            "empty_state": {
                "eyebrow": "Soccer cards",
                "title": f"No matches are scheduled on {selected} in any tracked league",
                "body": "This board reads every league's stored SoccerSim schedule and shows the fixtures whose kickoff falls on the selected date.",
                "list_items": [
                    f"Leagues checked: {len(LEAGUE_DISPLAY_NAMES)}",
                    "Use the date control to move to a date with fixtures, or open the Hub for each league's own matchweek.",
                ],
            } if not games else None,
            "using_sample_data": False,
            "route_path": "/soccer/cards",
            "intro_title": "Soccer Cards",
            "intro_body": (
                "Every tracked league's matches for the selected date, in kickoff order with live matches first. "
                "Each league's own matchweek is resolved for this date, so a card appears here on the day it is played."
            ),
            "cards_control_links": [
                {"label": "Betting board", "href": "/soccer/market-board"},
                {"label": "Hub", "href": "/soccer/hub"},
            ],
            "header_stats": [
                {"label": "Matches", "value": str(len(games))},
                {"label": "Live", "value": str(live_count)},
                {"label": "Final", "value": str(final_count)},
                {"label": "Simulated", "value": f"{simulated_count}/{len(games)}" if games else "-"},
                {"label": "Leagues", "value": str(len(leagues_present) or "-")},
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
