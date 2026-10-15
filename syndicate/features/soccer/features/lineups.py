"""Wire ESPN's confirmed-lineup data into the live props pipeline.

The Phase 7 backtest (``scripts/backtest_soccer_starter_awareness.py``)
proved real confirmed lineups measurably improve prop allocation accuracy
over season-only usage rates. This module is the live-pipeline hookup:
before a fixture kicks off, ESPN's confirmed lineup exists for some window
(typically the last ~hour before kickoff); before that, or if a fixture
can't be matched, it falls back to season-only allocation automatically --
no lineup source is required for the pipeline to run, it's a strict
improvement when one is available.

Usage: call ``attach_confirmed_starters`` on a fixtures list before
``build_soccer_simulation_input`` (the same opt-in-preprocessing pattern
``market_anchoring.anchor_ratings_to_market`` uses). Fixtures where no
confirmed lineup was found come back unchanged.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from syndicate.features.soccer.features.team_names import match_team_name
from syndicate.features.soccer.ingestion.espn_lineups import extract_match_player_rows
from syndicate.features.soccer.ingestion.espn_lineups import fetch_events
from syndicate.features.soccer.ingestion.espn_lineups import fetch_match_summary
from syndicate.features.soccer.sim_engine.soccersim.player_props import player_row_key

_DEFAULT_MIN_STARTERS = 7


def _norm_player_name(name: str) -> str:
    """Accent-folded, lower-cased player name for squad, roster and starter matching.

    LETTERS THAT DO NOT DECOMPOSE ARE FOLDED FIRST (lane `soccer-squad-name-fold`,
    2026-10-05). NFKD strips combining accents but leaves `ø æ œ ł đ ß` intact, so
    the stats file's `Aron Dønnum` never equalled the ESPN roster's `Aron Donnum`,
    the departed-player roster rescue (`build_soccer_artifacts._drop_departed_players`)
    missed him, and he was dropped from every ligue_1 squad. Uses the board's own
    table (`prop_projections._LIGATURE_FOLD`) so the two normalisers cannot drift.

    HTML ENTITIES ARE DECODED FIRST (lane soccer-starter-name-match, 2026-10-14): a
    stats row reads `Ngal&#039;ayel Mukau` where ESPN has `Ngal'ayel Mukau`.
    """
    import html

    from syndicate.features.shared.prop_projections import _LIGATURE_FOLD

    text = unicodedata.normalize("NFKD", html.unescape(str(name or "")).translate(_LIGATURE_FOLD))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(text.lower().replace(".", " ").replace("-", " ").split())


def resolve_starter_ids(
    player_rows: list[dict[str, Any]],
    starter_names: set[str],
    starter_espn_ids: dict[str, str] | None = None,
) -> set[str]:
    return _resolve_starters(player_rows, starter_names, starter_espn_ids)[0]


def _resolve_starters(
    player_rows: list[dict[str, Any]],
    starter_names: set[str],
    starter_espn_ids: dict[str, str] | None = None,
) -> tuple[set[str], set[str]]:
    """Map normalized ESPN starter names onto the identity keys
    ``build_usage_profiles`` actually uses (player_id when present, else a
    name-based key) -- so a ``starters`` set built from this function lines
    up with the rows passed into it, regardless of which ingestion source
    (Understat, ASA, ...) those rows came from."""
    resolved: set[str] = set()
    matched_names: set[str] = set()
    # BY ESPN ID FIRST (lane soccer-starter-name-match, 2026-10-14). Where the
    # season rows are ESPN-sourced (championship, eredivisie, belgian_pro_league,
    # primeira_liga) a row's `player_id` IS the ESPN athlete id, and the id pins the
    # player whatever either side calls them: the deduped row keeps the season with
    # the most minutes, so it reads "Jonathan Buatu" while ESPN's starter is "Buatu".
    # `starter_espn_ids` maps ESPN id -> normalized starter name.
    for index, row in enumerate(player_rows):
        espn_name = (starter_espn_ids or {}).get(str(row.get("player_id") or ""))
        if espn_name is not None:
            resolved.add(player_row_key(row, index, "_"))
            matched_names.add(espn_name)
    for index, row in enumerate(player_rows):
        name = _norm_player_name(row.get("player_name"))
        if name in starter_names and player_row_key(row, index, "_") not in resolved:
            resolved.add(player_row_key(row, index, "_"))
            matched_names.add(name)
    # NAME-FORM FALLBACK (lane soccer-starter-name-match, 2026-10-13). ESPN's
    # starter and the season row can name one player two ways -- "Eren Dinkci" /
    # "Eren Sami Dinkci", "Jeong Woo-yeong" / "Woo-Yeong Jeong". Tried only for a
    # starter no row matched exactly, against rows no starter claimed, in order of
    # strength; a step that finds two rows refuses rather than guesses.
    free = [(index, row) for index, row in enumerate(player_rows)
            if player_row_key(row, index, "_") not in resolved]
    for name in sorted(starter_names - matched_names):
        want = name.split()
        if not want:
            continue
        for step in _NAME_FORM_STEPS:
            hits = [(index, row) for index, row in free if step(want, _norm_player_name(row.get("player_name")).split())]
            if len(hits) == 1:
                resolved.add(player_row_key(hits[0][1], hits[0][0], "_"))
                free.remove(hits[0])
                matched_names.add(name)
                break
            if hits:
                break
    # SINGLE-NAME ROWS (lane soccer-single-name-starters, 2026-10-15). Understat
    # lists some players by one name -- "Gabriel" for ESPN's "Gabriel Magalhaes",
    # "Alisson" for "Alisson Becker", "Thiago" for "Igor Thiago" (12 confirmed
    # starters on 10-09..10-12). The REVERSE of the rejected one-word step, so it
    # must be unique BOTH ways: exactly one free single-name row carries the word,
    # and exactly one still-unresolved multi-word starter contains it. Two Arsenal
    # Gabriels starting, or two "Gabriel" rows, refuse.
    singles = [(index, row) for index, row in free
               if len(_norm_player_name(row.get("player_name")).split()) == 1]
    left = [name for name in sorted(starter_names - matched_names) if len(name.split()) >= 2]
    for index, row in singles:
        word = _norm_player_name(row.get("player_name"))
        if len(word) < 3:
            continue
        owners = [name for name in left if word in name.split()]
        rivals = [other for _, other in singles if _norm_player_name(other.get("player_name")) == word]
        if len(owners) == 1 and len(rivals) == 1:
            resolved.add(player_row_key(row, index, "_"))
            matched_names.add(owners[0])
            left.remove(owners[0])
    return resolved, matched_names


def _nested(want: list[str], have: list[str]) -> bool:
    small, large = (have, want) if len(have) <= len(want) else (want, have)
    return len(small) >= 2 and set(small) <= set(large) and want != have


def _short_first_name(want: list[str], have: list[str]) -> bool:
    """Same surname, first names sharing 3+ leading letters: a short or legal first
    name ("Matty" / "Matthew" Cash, "Dayot" / "Dayotchanculle" Upamecano, "Santi" /
    "Santiago"). Measured 2026-10-14: 34 confirmed starters on 10-09..10-12."""
    if len(want) < 2 or len(have) < 2 or want[-1] != have[-1] or want == have:
        return False
    a, b = want[0], have[0]
    n = 0
    while n < min(len(a), len(b)) and a[n] == b[n]:
        n += 1
    return n >= 3


# Strongest first. Word order; first and last name; two or more nested words; same
# surname with a short/legal first name. NO ONE-WORD STEP: it matched FC Dallas'
# starting goalkeeper "Daniel" to the squad's attacking midfielder "Daniel Job"
# (both in the same ESPN box, 10-10) -- a one-word name carries too little to pin
# a player. NO SURNAME-ONLY STEP: siblings and common surnames (the Kalulus).
_NAME_FORM_STEPS = (
    lambda want, have: sorted(want) == sorted(have),
    lambda want, have: len(want) > 1 and len(have) > 1 and (want[0], want[-1]) == (have[0], have[-1]),
    _nested,
    _short_first_name,
)


def find_event_for_fixture(
    events: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
) -> dict[str, Any] | None:
    """Match a fixture's team names against a pre-fetched ESPN event list."""
    team_pairs = [(event.get("home_team"), event.get("away_team")) for event in events]
    home_names = [pair[0] for pair in team_pairs if pair[0]]
    matched_home = match_team_name(home_team, home_names)
    if matched_home is None:
        return None
    for event in events:
        if event.get("home_team") != matched_home:
            continue
        if match_team_name(away_team, [event.get("away_team")] if event.get("away_team") else []) is not None:
            return event
    return None


def _move_starters_from_other_clubs(
    league: str,
    unmatched: set[str],
    espn_ids: dict[str, str],
    team_label: str,
    side_rows: list[dict[str, Any]],
    other_club_rows: list[dict[str, Any]],
) -> set[str]:
    """Confirmed starters this club's rows do not hold, found under ANOTHER club in
    the same league, and RE-FILED under the club that started them (lane
    soccer-starter-club-move, 2026-10-15).

    A within-league move the stats source has not caught up with: Matias Galarza
    starts for Inter Miami, but the row still says Atlanta, so the sim gave Atlanta
    his share and Inter Miami nobody. 9 confirmed starters on 10-09..10-12, mostly MLS.

    STRICT: a multi-word starter name only, matched by ESPN id, else exact name, else
    a name-form step; exactly ONE row in the whole pool or nothing moves. The row
    object is shared with the league's `player_rows`, so setting its `team` moves
    the player for the sim (`adapters._players_for_side` keys on it) -- out of the
    old squad and into the new one.
    """
    by_id = {str(espn_id): name for espn_id, name in (espn_ids or {}).items()}
    moved: set[str] = set()
    for name in sorted(unmatched):
        if len(name.split()) < 2:
            continue
        want_ids = {i for i, n in by_id.items() if n == name}
        hits = [row for row in other_club_rows if str(row.get("player_id") or "") in want_ids]
        if not hits:
            hits = [row for row in other_club_rows if _norm_player_name(row.get("player_name")) == name]
        if not hits:
            for step in _NAME_FORM_STEPS:
                hits = [row for row in other_club_rows
                        if step(name.split(), _norm_player_name(row.get("player_name")).split())]
                if hits:
                    break
        if len(hits) != 1:
            continue
        row = hits[0]
        if "," in str(row.get("team") or ""):
            # A comma-joined label ("Everton,Manchester City") is already filed under
            # each club it names (`build_soccer_artifacts._attach_confirmed_starters`),
            # so finding it HERE means it names neither club in this fixture -- not a
            # move this pass can make with confidence.
            continue
        print(f"[lineups] SOCCER_STARTER_CLUB_MOVED league={league} player={row.get('player_name')!r} "
              f"from={row.get('team')!r} to={team_label!r}", flush=True)
        row["team"] = team_label
        other_club_rows.remove(row)
        side_rows.append(row)
        moved.add(player_row_key(row, len(side_rows) - 1, "_"))
    return moved


def fetch_confirmed_starter_ids(
    league: str,
    *,
    home_team: str,
    away_team: str,
    home_player_rows: list[dict[str, Any]],
    away_player_rows: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
    date_windows: list[str] | None = None,
    min_starters: int = _DEFAULT_MIN_STARTERS,
    other_club_rows: list[dict[str, Any]] | None = None,
    home_team_label: str | None = None,
    away_team_label: str | None = None,
) -> tuple[set[str], set[str]] | None:
    """Confirmed starter id sets for one fixture, or ``None`` if no matching
    event was found or its lineup isn't posted yet (fewer than
    ``min_starters`` flagged on either side -- ESPN's pre-kickoff roster
    exists ahead of the real lineup announcement with nobody flagged as a
    starter, so this threshold is what actually distinguishes "posted" from
    "not yet")."""
    if events is None:
        windows = date_windows or []
        if not windows:
            return None
        events = fetch_events(league, date_windows=windows, statuses={"pre", "in"})
    event = find_event_for_fixture(events, home_team=home_team, away_team=away_team)
    if event is None:
        return None

    summary = fetch_match_summary(league, event["event_id"])
    rows = extract_match_player_rows(summary, event_id=event["event_id"])
    if not rows:
        return None

    home_names = {_norm_player_name(row["player_name"]) for row in rows if row["side"] == "home" and row["starter"]}
    away_names = {_norm_player_name(row["player_name"]) for row in rows if row["side"] == "away" and row["starter"]}
    if len(home_names) < min_starters or len(away_names) < min_starters:
        return None

    starter_ids = {
        side: {str(row["player_id"]): _norm_player_name(row["player_name"])
               for row in rows if row["side"] == side and row["starter"] and row.get("player_id")}
        for side in ("home", "away")
    }
    home_ids, home_matched = _resolve_starters(home_player_rows, home_names, starter_ids["home"])
    away_ids, away_matched = _resolve_starters(away_player_rows, away_names, starter_ids["away"])
    if other_club_rows:
        for side, names, matched, ids, label, side_rows in (
            ("home", home_names, home_matched, home_ids, home_team_label or home_team, home_player_rows),
            ("away", away_names, away_matched, away_ids, away_team_label or away_team, away_player_rows),
        ):
            ids |= _move_starters_from_other_clubs(
                league, names - matched, starter_ids[side], label, side_rows, other_club_rows)
    # PER SIDE, NOT PER FIXTURE. This used to `return None` when EITHER side
    # resolved fewer than `min_starters`, which discards a side whose lineup
    # matched perfectly well because the OTHER side did not.
    #
    # MEASURED against the real ESPN feed, 2026-08-21 18:11Z, today's slate:
    #   Marseille v Strasbourg      home 10  away  7   -> was kept
    #   Standard Liege v RAAL       home  9  away  5   -> was DISCARDED WHOLE
    #   Arsenal v Coventry          home  8  away  0   -> was DISCARDED WHOLE
    # Standard's nine confirmed starters and Arsenal's eight were thrown away
    # for the other club's name-matching gap. The two sides are allocated
    # independently downstream (`adapters.py` keys `side_starters` by
    # home/away), so a per-side decision is coherent rather than a partial
    # application of something that needs both halves.
    #
    # The EVIDENCE BAR PER SIDE IS UNCHANGED: a side still needs
    # `min_starters` resolved names or it contributes nothing and falls back
    # to season-only allocation. This widens WHICH sides qualify, not how
    # little evidence qualifies one.
    home_ok = len(home_ids) >= min_starters
    away_ok = len(away_ids) >= min_starters
    if not home_ok and not away_ok:
        # Lineup was posted but too few names matched our season-data
        # roster on either side to trust anything (name-matching gap,
        # mid-season signing not yet in the per-90 source, etc.).
        return None
    return (home_ids if home_ok else set()), (away_ids if away_ok else set())


def attach_confirmed_starters(
    fixtures: list[dict[str, Any]],
    *,
    league: str,
    player_rows_by_team: dict[str, list[dict[str, Any]]],
    date_windows: list[str],
    min_starters: int = _DEFAULT_MIN_STARTERS,
) -> list[dict[str, Any]]:
    """Return a copy of ``fixtures`` with ``home_starter_ids`` /
    ``away_starter_ids`` populated wherever ESPN has a confirmed lineup.
    Fixtures without a match, or without a posted lineup yet, come back
    unchanged -- the caller's existing season-only allocation still applies.
    Fetches the league's event list once and reuses it across all fixtures.
    """
    events = fetch_events(league, date_windows=date_windows, statuses={"pre", "in"})
    # EVERY CLUB A COMMA-JOINED LABEL NAMES (lane soccer-starter-club-move,
    # 2026-10-15). The caller keys rows by the whole `team` string, so a row filed
    # "Everton,Manchester City" sat under a key no fixture matches and its player
    # could never be matched as a confirmed starter -- while the sim itself binds
    # such a row to whichever part is playing (`loaders._bind_player_team`).
    # Measured 10-09..10-12: 53 such rows in five leagues (31 are ligue_1's
    # "Paris Saint Germain,Rennes", an upstream label fault). Re-keyed here so the
    # starter step reads the same clubs the sim does.
    expanded: dict[str, list[dict[str, Any]]] = {}
    for key, rows in player_rows_by_team.items():
        for part in dict.fromkeys(p.strip() for p in str(key).split(",")):
            if part:
                expanded.setdefault(part, []).extend(rows)
    player_rows_by_team = expanded
    team_names = list(player_rows_by_team)
    updated: list[dict[str, Any]] = []
    for fixture in fixtures:
        new_fixture = dict(fixture)
        home_team = str(fixture.get("home_team") or "")
        away_team = str(fixture.get("away_team") or "")
        home_key = match_team_name(home_team, team_names)
        away_key = match_team_name(away_team, team_names)
        if home_key is None or away_key is None:
            updated.append(new_fixture)
            continue
        others = [row for team, rows in player_rows_by_team.items() if team not in (home_key, away_key)
                  for row in rows]
        pool = list(others)
        result = fetch_confirmed_starter_ids(
            league,
            home_team=home_team,
            away_team=away_team,
            home_player_rows=player_rows_by_team[home_key],
            away_player_rows=player_rows_by_team[away_key],
            events=events,
            min_starters=min_starters,
            other_club_rows=pool,
            home_team_label=home_key,
            away_team_label=away_key,
        )
        # A moved row left its old club: drop it from that club's list too, so a later
        # fixture of the old club cannot claim it again.
        for row in others:
            if row not in pool:
                for team, rows in player_rows_by_team.items():
                    if team not in (home_key, away_key) and row in rows:
                        rows.remove(row)
        if result is not None:
            home_ids, away_ids = result
            # An EMPTY side means "not confirmed", and must stay absent rather
            # than be written as an empty tuple: `()` and "no key" both read as
            # falsy to the consumer, but a caller counting confirmed fixtures
            # (`build_soccer_artifacts._attach_confirmed_starters`) tests the
            # HOME key specifically, so writing `()` there would make an
            # away-only confirmation look like a home confirmation of nobody.
            if home_ids:
                new_fixture["home_starter_ids"] = tuple(home_ids)
            if away_ids:
                new_fixture["away_starter_ids"] = tuple(away_ids)
        updated.append(new_fixture)
    return updated


__all__ = [
    "attach_confirmed_starters",
    "fetch_confirmed_starter_ids",
    "find_event_for_fixture",
    "resolve_starter_ids",
]
