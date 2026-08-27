"""NCAAF player props, from the captured OddsAPI CSV to the board contract.

WHAT THIS IS, AND WHAT IT DELIBERATELY IS NOT.

This is a MARKET INVENTORY, not a recommendation engine. NCAAF has no prop
model -- `syndicate/features/ncaaf/player_stats.py` exists but nothing has
been fitted or graded on it, and NFL's own prop model was measured at -7.35%
ROI over 64,007 graded bets, so inventing an NCAAF one by analogy would be
inventing a losing one. Every row here carries a line, a price and the book
that offered it. No edge, no tier, no pick. If a `pick` field ever appears in
this file it must be because something was BACKTESTED first.

WHY THE ROWS GO WHERE THEY GO.
`game_board_contract._build_prop_rows` reads `game["prop_recommendations"]` as
`{"away": [...], "home": [...]}` and derives each row's heading from the LIST
IT IS IN, not from anything on the row. So a misattributed player renders under
the wrong team's heading with no way for the reader to tell. That is why
`_side_for_player` drops what it cannot resolve rather than guessing a side.

THE ATTRIBUTION PROBLEM, measured.
OddsAPI's per-event prop payload carries NO team on a player outcome -- the
`team` column is blank on every captured row. Side has to come from the roster
snapshot joined through the team registry. Measured on the real 2026 wk1
openers, 2026-08-26: **68 of 68 distinct players resolved to exactly one
side, 0 misses, 0 ambiguous**.

**CORRECTED 2026-08-27.** An earlier version of this note said the roster
snapshot was stuck on season 2025 because the 2026 build "produced Publishable
rows: 0". That was a misreading of a STALE REPORT dated 2026-08-01. Re-run
against live CFBD: **15,496 rows across 138 teams, 0 validation issues**. The
2026 roster, coach-continuity (138) and transfer (3,305) snapshots are now
built and committed, and `_team_context` populates **102 of 102 team slots**
on the served board. The builder was never broken; the report simply predated
CFBD publishing 2026 rosters and was never regenerated.

The roster file is season-ACCUMULATING (`_merge_season_aware_rows` keeps prior
seasons), so it now holds 44,395 rows across 2025 and 2026. That is why
`_team_ids_by_player` prefers the requested season: without the preference a
transfer looks like a player on two teams, and this module drops ambiguity
rather than guessing a side -- which would silently delete transfers from the
panel, the population most likely to be quoted in week 1.
`build_game_props` still returns its own drop counts so erosion is visible as a
number rather than as a quietly shrinking panel.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from syndicate.features.ncaaf.sources import ncaaf_player_props_path
from syndicate.features.ncaaf.sources import roster_snapshot_path
from syndicate.features.ncaaf.sources import team_registry_snapshot_path
from syndicate.features.shared.book_shortlist import is_bettable

#: Rows the board shows per game. `_build_prop_rows` caps at 8 across both
#: sides, so anything above this is built and then discarded by the contract.
MAX_ROWS_PER_SIDE = 4

_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")


def _norm(value: Any) -> str:
    """Normalise a team or player name for joining.

    ACCENTS ARE FOLDED, NOT STRIPPED, and that is the whole point of the
    `unicodedata` line. Measured on the 2026 week 1 slate: the team registry
    stores `San José State`, the board sends `San Jose State`, and OddsAPI
    sends `San José State Spartans`. Deleting the accented character as
    non-alphanumeric turns the registry form into `san jos state` while the
    board form stays `san jose state` -- they stop matching, and San José
    State's entire props panel disappears with no error anywhere. Decomposing
    to `e` + combining acute and dropping the mark maps all three to
    `san jose state`.
    """
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.strip().lower().replace("&", " and ")
    text = _NON_ALNUM_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def _checkout_processed_path(*parts: str) -> Path:
    """The REPO CHECKOUT copy, which is what `cards.py` reads.

    `cards.py::_processed_artifact_path` resolves these four snapshots from
    `parents[3]/data/ncaaf_source/...` -- the checkout -- while
    `sources.*_snapshot_path()` resolves them from
    `SYNDICATE_NCAAF_SOURCE_ROOT`, the mounted disk. On Render those are
    DIFFERENT FILES with different vintages: the checkout is replaced by every
    web deploy, but the boot sync onto the mounted disk is SEED-ONLY, so a disk
    copy that already exists is never overwritten.

    That split is why this is tried as a fallback. If props attribution read
    only the mounted disk it could resolve players against a roster years older
    than the one the card beside it is displaying, and the symptom would be a
    thinning props panel with no error anywhere.
    """
    return Path(__file__).resolve().parents[3] / "data" / "ncaaf_source" / "source_artifacts" / "data" / "processed" / Path(*parts)


def _read_snapshot(primary: Path, *checkout_parts: str) -> list[dict[str, str]]:
    """Mounted-disk copy first, then the checkout copy, then empty."""
    rows = _read_csv(primary)
    if rows:
        return rows
    return _read_csv(_checkout_processed_path(*checkout_parts))


def _team_registry_rows() -> list[dict[str, str]]:
    """The team registry, under EITHER of the two names it ships under.

    `sources.team_registry_snapshot_path()` points at
    `ncaaf_team_registry_snapshot.csv` while `cards.py` reads
    `ncaaf_team_registry.csv`. Both exist in the tree, byte-identical in size,
    and the production hot-artifact inventory lists both. Reading only one
    means the side attribution silently resolves NOTHING if a deploy ever
    carries only the other -- and an empty registry produces an empty props
    panel, not an error. Cost of tolerating both: one extra `exists()`.
    """
    for candidate in (
        team_registry_snapshot_path(),
        team_registry_snapshot_path().with_name("ncaaf_team_registry.csv"),
        _checkout_processed_path("team_registry", "ncaaf_team_registry_snapshot.csv"),
        _checkout_processed_path("team_registry", "ncaaf_team_registry.csv"),
    ):
        rows = _read_csv(candidate)
        if rows:
            return rows
    return []


@lru_cache(maxsize=1)
def _team_id_by_name() -> dict[str, str]:
    """Every name form -> team_id, for EXACT normalised lookup.

    EXACT, NOT PREFIX, and this is the second design here -- the first used a
    prefix rule and it was wrong in the one way that matters.

    The two naming conventions in play are the CFBD schedule's school-only
    form ("North Carolina") and OddsAPI's school-plus-mascot form ("North
    Carolina Tar Heels"). A prefix rule joins those correctly and ALSO joins
    "North Carolina" to "North Carolina State", because that is the identical
    string shape. Both teams are on the 2026 week 1 slate, so the failure is
    not hypothetical: NC State players would render under North Carolina's
    heading with nothing on the card to reveal it.

    The registry already carries `mascot_name`, so OddsAPI's form can be
    RECONSTRUCTED (`school_name + " " + mascot_name`) and matched exactly
    rather than guessed at. Where a name still misses, `_resolve_team_id`
    falls back to the LONGEST matching school-name prefix, which resolves
    "north carolina state ..." to NC State before UNC can claim it.
    """
    index: dict[str, str] = {}
    for row in _team_registry_rows():
        team_id = str(row.get("team_id") or "").strip()
        if not team_id:
            continue
        school = _norm(row.get("school_name"))
        mascot = _norm(row.get("mascot_name"))
        forms = {
            school,
            _norm(row.get("canonical_team_name")),
            _norm(row.get("display_name")),
            _norm(row.get("abbreviation")),
        }
        if school and mascot:
            forms.add(f"{school} {mascot}")
        for form in forms:
            if form:
                index.setdefault(form, team_id)
    return index


@lru_cache(maxsize=1)
def _school_names_by_id() -> tuple[tuple[str, str], ...]:
    """(normalised school name, team_id), LONGEST FIRST.

    Longest-first is the whole point: it makes the prefix fallback resolve
    "north carolina state wolfpack" to NC State before North Carolina can
    claim it.
    """
    pairs: set[tuple[str, str]] = set()
    for row in _team_registry_rows():
        team_id = str(row.get("team_id") or "").strip()
        school = _norm(row.get("school_name"))
        if team_id and school:
            pairs.add((school, team_id))
    return tuple(sorted(pairs, key=lambda pair: (-len(pair[0]), pair[0])))


def _resolve_team_id(name: str) -> str | None:
    """A team name in EITHER convention -> team_id, or None."""
    normalized = _norm(name)
    if not normalized:
        return None
    exact = _team_id_by_name().get(normalized)
    if exact:
        return exact
    for school, team_id in _school_names_by_id():
        if normalized == school or normalized.startswith(school + " "):
            return team_id
    return None


@lru_cache(maxsize=8)
def _team_ids_by_player(season: int) -> dict[str, frozenset[str]]:
    """player -> the team ids they are rostered on, CURRENT SEASON PREFERRED.

    The roster snapshot is season-accumulating: `_merge_season_aware_rows`
    keeps every prior season in the same file, so after the 2026 build it
    holds 44,395 rows across 2025 AND 2026. Indexing all of them without
    preference makes a transfer look like a player on two teams, and this
    module drops ambiguity rather than guessing a side -- so a naive index
    would silently delete transfers from the props panel, which is precisely
    the population most likely to be quoted in week 1.

    So: if a player has any row for the requested season, ONLY those rows
    count. Players with no current-season row fall back to whatever seasons
    exist, which keeps a late-arriving roster from blanking the panel.
    """
    current: dict[str, set[str]] = defaultdict(set)
    fallback: dict[str, set[str]] = defaultdict(set)
    for row in _read_snapshot(roster_snapshot_path(), "roster", "ncaaf_roster_snapshot.csv"):
        player = _norm(row.get("player_name"))
        team_id = str(row.get("team_id") or "").strip()
        if not player or not team_id:
            continue
        if str(row.get("season") or "").strip() == str(int(season)):
            current[player].add(team_id)
        else:
            fallback[player].add(team_id)
    merged = {player: frozenset(ids) for player, ids in current.items()}
    for player, ids in fallback.items():
        merged.setdefault(player, frozenset(ids))
    return merged


def _side_for_player(player: str, *, home: str, away: str, season: int) -> str | None:
    """"home", "away", or None when the roster cannot place this player.

    None on BOTH no-match and ambiguous-match. An ambiguous player (on the
    roster of both teams, which happens with a common name) is exactly the
    case where a guess renders under the wrong heading, so it is dropped for
    the same reason a miss is.
    """
    team_ids = _team_ids_by_player(int(season)).get(_norm(player))
    if not team_ids:
        return None
    # Compare TEAM IDS, never names. Name comparison is what put an NC State
    # player on a North Carolina card in the first version of this function.
    home_id, away_id = _resolve_team_id(home), _resolve_team_id(away)
    sides: set[str] = set()
    if home_id and home_id in team_ids:
        sides.add("home")
    if away_id and away_id in team_ids:
        sides.add("away")
    if len(sides) == 1:
        return sides.pop()
    return None


def _american(value: Any) -> int | None:
    text = str(value or "").strip().replace("+", "")
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


def _better(left: int | None, right: int | None) -> int | None:
    """The more favourable American price for the bettor.

    Not `max`: -105 beats -120 and +180 beats +150, but a naive max over the
    raw integers is correct for both only because negative prices compare the
    same way. Stated explicitly because it looks like it needs a sign split
    and does not.
    """
    if left is None:
        return right
    if right is None:
        return left
    return left if left > right else right


def _format_line(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return f"{number:g}"


def _format_price(price: int | None) -> str:
    if price is None:
        return ""
    return f"+{price}" if price > 0 else str(price)


def load_prop_rows(season: int, week: int) -> list[dict[str, str]]:
    """Raw captured rows for one (season, week), or [] when nothing captured."""
    return _read_csv(ncaaf_player_props_path(season, week))


def _selection_key(row: dict[str, str]) -> tuple[str, str, str]:
    return (str(row.get("player") or "").strip(), str(row.get("market") or "").strip(), _format_line(row.get("line")))


def build_game_props(
    rows: Iterable[dict[str, str]],
    *,
    home_team: str,
    away_team: str,
    season: int = 0,
    bettable_only: bool = True,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    """One game's captured rows -> the contract's away/home prop lists.

    Returns `(prop_recommendations, diagnostics)`. Diagnostics carry the
    dropped counts so the caller can log erosion rather than serve a quietly
    shrinking panel -- see this module's docstring.

    Books are collapsed to a BEST PRICE per selection, with the book that
    offered it named on the row. That is the whole reason the capture keeps
    every bookmaker: measured on the real wk1 openers, 74 of 130 selections
    were quoted by more than one book, best-minus-worst averaging 93.8
    American points.
    """
    by_selection: dict[tuple[str, str, str], dict[str, Any]] = {}
    dropped_unbettable = 0
    for row in rows:
        book = str(row.get("book") or "").strip()
        if bettable_only and not is_bettable(book):
            dropped_unbettable += 1
            continue
        key = _selection_key(row)
        if not key[0] or not key[1]:
            continue
        over = _american(row.get("over_price"))
        under = _american(row.get("under_price"))
        record = by_selection.get(key)
        if record is None:
            record = {
                "player": key[0],
                "market": key[1],
                "line": key[2],
                "over_price": None,
                "under_price": None,
                "over_book": "",
                "under_book": "",
                "books": set(),
            }
            by_selection[key] = record
        if over is not None:
            if _better(record["over_price"], over) == over and over != record["over_price"]:
                record["over_book"] = book
            record["over_price"] = _better(record["over_price"], over)
        if under is not None:
            if _better(record["under_price"], under) == under and under != record["under_price"]:
                record["under_book"] = book
            record["under_price"] = _better(record["under_price"], under)
        record["books"].add(book)

    sides: dict[str, list[dict[str, Any]]] = {"away": [], "home": []}
    dropped_unattributed: set[str] = set()
    for record in by_selection.values():
        side = _side_for_player(record["player"], home=home_team, away=away_team, season=season)
        if side is None:
            dropped_unattributed.add(record["player"])
            continue
        line = record["line"]
        market = record["market"]
        over_text = _format_price(record["over_price"])
        under_text = _format_price(record["under_price"])
        if line:
            pick = f"Over {line} {market}".strip()
            detail = f"{market} {line} - over {over_text}" + (f" / under {under_text}" if under_text else "")
        else:
            pick = market
            detail = f"{market} {over_text}".strip()
        book_count = len([book for book in record["books"] if book])

        # THE ONLY MODELLED MARKET, and the restriction is the finding.
        # Backtested out-of-sample on 2025 (weeks 5-16, fitted on weeks < w):
        # Anytime TD beats both the player's own mean (Brier 0.18168 vs
        # 0.21919) and the league base rate (0.19400). Every continuous market
        # LOSES to the player's own mean, so none of them is projected --
        # a projection worse than "his average" is worse than a blank column,
        # because it looks like knowledge.
        #
        # `projected` is a PROBABILITY here, not a stat line. `pick_gate.py`
        # suppresses NCAAF picks default-DENY and states that it "does NOT stop
        # projections being generated, published, or displayed" -- so a
        # probability may be shown, and an edge, tier, stake or recommendation
        # may not, until its LIFT_CONDITION is met on real graded bets.
        projection = None
        implied = None
        if market == "Anytime TD":
            from syndicate.features.ncaaf import prop_model

            projection = prop_model.anytime_td_probability(record["player"], int(season or 0))
            implied = prop_model.american_to_probability(record["over_price"])

        sides[side].append(
            {
                "player": record["player"],
                "market": market,
                "line": line or None,
                "market_line": line or None,
                "price": over_text or under_text,
                # WHAT THE CARD ACTUALLY RENDERS, and it is not obvious from
                # here. `_build_prop_rows` maps `detail <- display_pick` and
                # `value <- tier or line or price`. So the book count has to
                # ride on `display_pick` and the PRICE has to be `tier`, or the
                # card shows a player and a market with no number on it -- which
                # is what the first version of this file did.
                #
                # `tier` is a misnomer inherited from the sports that have a
                # model. There is no NCAAF prop model, so the most
                # decision-relevant thing available is the best price.
                "display_pick": f"{pick} - {book_count} book" + ("s" if book_count != 1 else ""),
                "tier": over_text or under_text or None,
                "selection": "over" if over_text else "under",
                "book": record["over_book"] or record["under_book"],
                "detail": detail,
                "book_count": book_count,
                # Contract mapping: `_build_prop_rows` reads `projected` via
                # `_first_present(projected, projection, model_mean)`. A row
                # with no model leaves it absent rather than 0.0 -- zero is a
                # probability and would render as one.
                "projected": (projection or {}).get("probability"),
                "model_prior_games": (projection or {}).get("prior_games"),
                # Implied, NOT fair: a one-sided anytime-TD price carries the
                # book's margin and has no opposing side quoted to de-vig
                # against, so every comparison here is model-vs-price-with-vig.
                "market_implied": implied,
            }
        )

    for side in sides:
        # Most-quoted first: book count is the only liquidity signal available
        # without a model, and a selection three books agree on is a better
        # thing to surface than a lone outlier price.
        sides[side].sort(key=lambda item: (-int(item.get("book_count") or 0), str(item.get("player") or "")))
        del sides[side][MAX_ROWS_PER_SIDE:]

    diagnostics = {
        "selections": len(by_selection),
        "dropped_unbettable_rows": dropped_unbettable,
        "dropped_unattributed_players": len(dropped_unattributed),
        "away": len(sides["away"]),
        "home": len(sides["home"]),
    }
    return sides, diagnostics


@lru_cache(maxsize=4)
def _rows_by_game(season: int, week: int) -> dict[tuple[str, str], tuple[dict[str, str], ...]]:
    index: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in load_prop_rows(season, week):
        key = (_norm(row.get("home_team")), _norm(row.get("away_team")))
        if key[0] and key[1]:
            index[key].append(row)
    return {key: tuple(value) for key, value in index.items()}


def _team_matches(board_name: str, captured_name: str) -> bool:
    """Do a board team name and an OddsAPI team name refer to one team?

    THEY ARE NOT THE SAME STRINGS AND THAT IS THE NORMAL CASE -- CFBD gives
    "TCU", OddsAPI gives "TCU Horned Frogs". A straight equality join matched
    0 of 6 openers, measured.

    Resolved through the registry to TEAM IDS rather than compared as strings.
    A bare string prefix rule also joins "North Carolina" to "North Carolina
    State", and both are on the 2026 week 1 slate.
    """
    board, captured = _norm(board_name), _norm(captured_name)
    if not board or not captured:
        return False
    if board == captured:
        return True
    board_id, captured_id = _resolve_team_id(board), _resolve_team_id(captured)
    return bool(board_id and captured_id and board_id == captured_id)


def _find_captured_game(
    index: dict[tuple[str, str], tuple[dict[str, str], ...]], *, home_team: str, away_team: str
) -> tuple[dict[str, str], ...] | None:
    """The captured rows for this matchup, or None.

    Requires a UNIQUE match on both sides. Two candidates means the name
    matching is not discriminating enough for this pair, and attaching the
    wrong game's props to a card is worse than attaching none.
    """
    exact = index.get((_norm(home_team), _norm(away_team)))
    if exact:
        return exact
    matches = [
        rows
        for (captured_home, captured_away), rows in index.items()
        if _team_matches(home_team, captured_home) and _team_matches(away_team, captured_away)
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def prop_recommendations_for_game(*, season: int, week: int, home_team: str, away_team: str) -> dict[str, list[dict[str, Any]]]:
    """The contract block for one game, or `{}` when nothing was captured.

    `{}` rather than `{"away": [], "home": []}` on purpose: the contract's
    `_build_prop_rows` falls through to a panel scrape when
    `prop_recommendations` is empty, and an empty-but-present dict and an
    absent one behave identically there -- but an absent one reads correctly
    to a human debugging the payload as "nothing captured", instead of
    "captured and everything was filtered".
    """
    rows = _find_captured_game(_rows_by_game(int(season), int(week)), home_team=home_team, away_team=away_team)
    if not rows:
        return {}
    sides, _diagnostics = build_game_props(rows, home_team=home_team, away_team=away_team, season=int(season))
    if not sides["away"] and not sides["home"]:
        return {}
    return sides


def reset_caches() -> None:
    """Drop the memoised snapshots -- for tests, and after a fresh capture."""
    _team_id_by_name.cache_clear()
    _school_names_by_id.cache_clear()
    _team_ids_by_player.cache_clear()
    _rows_by_game.cache_clear()
