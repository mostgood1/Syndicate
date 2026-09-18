"""Soccer player-prop evidence.

SOURCES (all allowlisted in `artifact_publisher.HOT_ARTIFACT_PATTERNS`, all read
on production web 2026-09-17):

    <league>/api/recommendations/recommendations_<date>.json
            matches[]: win_probability, team_projection, total_distribution,
            volume_projection (team shots / SOT / corners), periods,
            scoreline_probabilities, adapter_metadata.{home,away}_rating_detail
            (xG for/against, goals for/against, PPDA), squad_audit;
            player_props[]: expected_* means (+ `_if_playing`),
            expected_minutes_share, {shots,shots_on_target,assists}_over_probabilities,
            anytime_scorer_probability (+ `_if_playing`), goal_or_assist_probability
    <league>/api/live_state/live_state_<date>.json
            match_box[event].players.{home,away}.players[]: appeared, starter,
            minutes, goals, assists, shots, shots_on_target (player boxes exist
            since 2026-09-09; team stats and goals before that)
    <league>/players/players_<season>.csv
            per-player season rates (understat or ESPN)

THE MATCH IS FOUND THE WAY THE BOARD FINDS IT. `load_soccer_projections` +
`SoccerProjectionIndex.match_for`, over `preferred_artifact_roots(...,
local_dir_name="soccer_source")` and `resolve_window_dates("soccer", date,
"slate")` -- the loader, join, roots and window `attach_soccer_projections` and
Ask's `_soccer_match_evidence` use -- so the evidence and the row's price cannot
describe two different fixtures.

THE PLAYER IS FOUND THE WAY THE BOARD FINDS HIM, and his box line THE WAY
SETTLEMENT FINDS IT. Inside the sim's roster for that one match: exact
`_norm_name`, else a UNIQUE token subset (the rule
`attach_soccer_projections._lookup_player` states; it is a closure there, so it
is restated in `lookup_player` below). Inside a live_state box:
`population_outcomes_soccer.find_player`, `is_final`, `qualifying_goals` and
`deciding_scorer` are CALLED, so a hit rate here and a graded result there use
one matching rule, one own-goal rule and one DNP rule.

THE LADDERS DO NOT ALL MEAN THE SAME THING, and this is the single most
misreadable number on a soccer prop. Measured over the production
`serie_a/recommendations_2026-09-19.json` (230 rows) and
`eredivisie/recommendations_2026-09-18.json` (46 rows):

    shots_over_probabilities["0.5"]            closer to 1-exp(-expected_shots_if_playing)
                                               than to 1-exp(-expected_shots) in 207/212 and
                                               34/43 rows (every exception a mixture/zero row)
    shots_on_target_over_probabilities["0.5"]  same, 210/212 and 38/43
    assists_over_probabilities["0.5"]          == 1-exp(-expected_assists) within 1e-4 on
                                               212/212 and 43/43 rows: UNCONDITIONAL
    anytime_scorer_probability                 == 1-exp(-expected_goals): UNCONDITIONAL

which is what `player_props.project_player_props` wrote then: shots and shots
on target a start/sub mixture "P(over | appears)"; assists and the anytime field
Poisson on the unconditional mean. Since `#673` (2026-09-18, H33) the ASSISTS
ladder is the mixture too, and every probability field is stamped in
`ladder_conditioning`; the anytime field stays unconditional by user decision.
`ladder_basis` reads the stamp, and for a file built before it the exact test in
`soccer_projections.ladder_conditioning`, so this and the board cannot disagree. So a bench player (Nils Eggens, minutes share 0.059) reads
"P(over 0.5 shots) 88%" -- IF HE PLAYS. Every probability row below says which
it is, beside the minutes share, and `ladder_basis` checks it per row rather
than per market, because artifacts built before `b33ef901` (2026-09-15) carry an
unconditional shots ladder under the same key.

NOTHING HERE COMPUTES A PROJECTION. Ladders are read at the board's line
(exact match only, as the board prices them); totals-by-goals and team shares
are arithmetic over published numbers.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from syndicate.features.shared.prop_evidence import common as C
from syndicate.features.shared.prop_evidence.contract import (
    ABSENT_NO_ARTIFACT,
    ABSENT_NO_MATCH,
    ABSENT_NO_PRODUCER,
    ABSENT_NO_SAMPLE,
    ABSENT_NOT_APPLICABLE,
    Layer,
    LayerEvidence,
    PropEvidence,
    PropSubject,
    absent,
    chart,
    table,
)
from syndicate.features.shared.prop_evidence.track_record import build_track_record

logger = logging.getLogger(__name__)

LOCAL_DIR = "soccer_source"
FORM_LOOKBACK_DAYS = 45
MAX_LIVE_STATE_FILES = 30
SMALL_SAMPLE = 3
STALE_FORM_DAYS = 14
# Tolerance for "this ladder IS Poisson on the unconditional mean": both the
# probability and the mean are published rounded to 4 dp, and d/dm (1-e^-m) <= 1.
_POISSON_TOLERANCE = 0.00015
PLAYER_BOXES_SINCE = "2026-09-09"


@dataclass(frozen=True)
class MarketSpec:
    label: str
    box_stat: str | None
    ladder: str | None
    mean: str | None
    mean_if_playing: str | None
    kind: str  # count | anytime | first | last


MARKETS: dict[str, MarketSpec] = {
    "player_shots": MarketSpec("Shots", "shots", "shots_over_probabilities", "expected_shots",
                               "expected_shots_if_playing", "count"),
    "player_shots_on_target": MarketSpec("Shots on target", "shots_on_target", "shots_on_target_over_probabilities",
                                         "expected_shots_on_target", "expected_shots_on_target_if_playing", "count"),
    "player_assists": MarketSpec("Assists", "assists", "assists_over_probabilities", "expected_assists",
                                 "expected_assists_if_playing", "count"),
    "player_goal_scorer_anytime": MarketSpec("Goals", "goals", None, "expected_goals", None, "anytime"),
    "player_first_goal_scorer": MarketSpec("Goals", "goals", None, "expected_goals", None, "first"),
    "player_last_goal_scorer": MarketSpec("Goals", "goals", None, "expected_goals", None, "last"),
}

# Board markets the soccer platform captures odds for but has no model or box stat for.
NO_MODEL_MARKETS: dict[str, str] = {
    "player_to_receive_card": "the soccer sim publishes no card model, and live_state boxes carry team card counts only",
    "player_to_receive_red_card": "the soccer sim publishes no card model, and live_state boxes carry team card counts only",
}

# Measured caveats from the ledger. Stated, never corrected for here. All were
# measured on artifacts built BEFORE the 2026-09-15 conditional-ladder deploy.
LEDGER_SOURCE = (".syndicate/state_soccer.md [soccer-season-market-audit] and "
                 ".syndicate/findings_2026-09-15_soccer_season_market_audit.md, measured 2026-09-15")
_SHOTS_CAVEAT = ("Season audit (07-22..09-14): betting shots overs on the model's raw edge returned "
                 "-31.9% [-46.1%, -15.1%] held out.")
_SOT_CAVEAT = ("Season audit (07-22..09-14): shots-on-target overs on raw model edge +28.6% "
               "[-25.9%, +89.8%] on 47 bets -- no measurable edge.")
_SCORER_CAVEAT = ("Season audit (07-22..09-14): the top decile of anytime-scorer probabilities was 1.39x "
                  "the realised rate. Fix #3 (2026-09-16) addressed the zero deciles; the top decile is "
                  "not recorded as re-measured.")
LEDGER_CAVEATS: dict[str, str] = {
    "player_shots": _SHOTS_CAVEAT,
    "player_shots_on_target": _SOT_CAVEAT,
    "player_goal_scorer_anytime": _SCORER_CAVEAT,
    "player_first_goal_scorer": _SCORER_CAVEAT,
    "player_last_goal_scorer": _SCORER_CAVEAT,
}


# ---------------------------------------------------------------------------
# Resolution: roots, window, fixture, player
# ---------------------------------------------------------------------------


@dataclass
class Resolved:
    roots: list[Path] = field(default_factory=list)
    window: list[str] = field(default_factory=list)
    index: Any = None
    match: dict[str, Any] | None = None
    match_reason: str = ""
    league: str = ""
    match_id: str = ""
    match_date: str = ""
    entry: dict[str, Any] | None = None
    player_reason: str = ""
    player_join: str = ""
    side: str = ""
    team: str = ""
    opponent: str = ""
    # From the ONE file holding this match. `index.generated_at_by_league` holds
    # the league's OLDEST file in the window (`#673`), not this match's build.
    generated_at: str = ""

    def generated_at_for(self) -> str:
        if self.generated_at:
            return self.generated_at
        by_league = getattr(self.index, "generated_at_by_league", None) or {}
        return str(by_league.get(self.league) or "")


def artifact_roots() -> list[Path]:
    from syndicate.features.shared import soccer_projections
    from syndicate.features.shared.source_roots import preferred_artifact_roots

    return list(preferred_artifact_roots(
        soccer_projections.__file__, env_var="SYNDICATE_SOCCER_SOURCE_ROOT", local_dir_name=LOCAL_DIR,
    ))


def slate_window(selected_date: str) -> list[str]:
    from syndicate.features.shared.layer1_board import resolve_window_dates

    try:
        return list(resolve_window_dates("soccer", selected_date, window="slate"))
    except Exception:
        return [selected_date]


def load_index(roots: list[Path], selected_date: str, window: list[str]):
    from syndicate.features.shared import soccer_projections

    return soccer_projections.load_soccer_projections(roots, selected_date, window_dates=window)


def lookup_player(pool: Mapping[str, Any], board_name: Any) -> tuple[Any, str]:
    """`(entry, state)` -- the rule `attach_soccer_projections._lookup_player` applies.

    Exact `_norm_name` first; else a UNIQUE token-subset match inside this one
    match's roster, with a one-token side at least four characters. Ambiguity
    returns nothing. Restated rather than imported because the board's copy is a
    closure inside `attach_soccer_projections`.
    """
    key = C.name_key(board_name)
    if not key or not pool:
        return None, "empty"
    hit = pool.get(key)
    if hit is not None:
        return hit, "exact"
    tokens = set(key.split())
    candidates: list[Any] = []
    for pool_key, pool_value in pool.items():
        pool_tokens = set(str(pool_key or "").split())
        if not pool_tokens:
            continue
        shorter, longer = (pool_tokens, tokens) if len(pool_tokens) <= len(tokens) else (tokens, pool_tokens)
        if not shorter <= longer:
            continue
        if len(shorter) == 1 and len(next(iter(shorter))) < 4:
            continue
        candidates.append(pool_value)
    if len(candidates) == 1:
        return candidates[0], "alias"
    if len(candidates) > 1:
        return None, "ambiguous"
    return None, "miss"


def resolve(subject: PropSubject) -> Resolved:
    out = Resolved()
    selected = subject.selected_date or subject.commence_time[:10]
    out.roots = artifact_roots()
    out.window = slate_window(selected)
    out.index = load_index(out.roots, selected, out.window)
    window_text = f"{out.window[0]}..{out.window[-1]}" if out.window else selected
    if not getattr(out.index, "source_paths", None):
        out.match_reason = f"{ABSENT_NO_ARTIFACT}:no soccer recommendations_<date>.json in slate window {window_text}"
        return out
    row = {"event_id": subject.event_id, "home_team": subject.home_team, "away_team": subject.away_team}
    match = out.index.match_for(row)
    if not isinstance(match, dict):
        from syndicate.features.shared.soccer_projections import _norm_team

        key = (_norm_team(subject.home_team), _norm_team(subject.away_team))
        why = "ambiguous (two fixtures share these clubs in the window)" if key in out.index.ambiguous_team_keys else "not in the sim"
        out.match_reason = (f"{ABSENT_NO_MATCH}:fixture {subject.away_team} @ {subject.home_team} {why}; "
                            f"read {len(out.index.source_paths)} recommendations files for {window_text}")
        return out
    out.match = match
    out.league = str(match.get("league") or "")
    out.match_id = str(match.get("match_id") or "").strip()
    out.match_date = str(match.get("date") or match.get("kickoff") or "")[:10]
    pool = out.index.players_by_match.get(out.match_id) or {}
    entry, state = lookup_player(pool, subject.player_name)
    out.player_join = state
    if not isinstance(entry, dict):
        out.player_reason = (f"{ABSENT_NO_MATCH}:{subject.player_name} not in the sim's player list for match "
                             f"{out.match_id} ({len(pool)} listed; join {state})")
        return out
    out.entry = entry
    out.side = str(entry.get("side") or "").strip().lower()
    matchup = match.get("matchup") or {}
    other = "away" if out.side == "home" else "home"
    # The FIXTURE's spelling (ESPN), the same feed live_state writes -- not the
    # player file's club name, which is understat's spelling in understat leagues.
    out.team = str(matchup.get(f"{out.side}_team") or entry.get("team") or "")
    out.opponent = str(matchup.get(f"{other}_team") or "")
    return out


def recommendations_meta(ctx: Resolved) -> tuple[dict[str, Any], Path | None]:
    """Top-level anchor / substrate / generated_at of the ONE file that holds this match."""
    if ctx.match is None:
        return {}, None
    wanted = f"recommendations_{ctx.match_date}.json"
    for raw in getattr(ctx.index, "source_paths", []) or []:
        path = Path(raw)
        try:
            league_dir = path.parents[2].name
        except IndexError:
            league_dir = ""
        if path.name != wanted or (ctx.league and league_dir != ctx.league):
            continue
        try:
            payload = C.load_json(path)
        except Exception:
            logger.exception("prop_evidence soccer: unreadable %s", path)
            return {}, path
        if not isinstance(payload, dict):
            return {}, path
        return {key: payload.get(key) for key in ("generated_at", "simulations", "anchor", "player_substrate")}, path
    return {}, None


# ---------------------------------------------------------------------------
# Ladders
# ---------------------------------------------------------------------------


def ladder_points(entry: Mapping[str, Any], field_name: str | None) -> list[tuple[float, float]]:
    ladder = entry.get(field_name) if field_name else None
    points: list[tuple[float, float]] = []
    for key, value in (ladder or {}).items() if isinstance(ladder, Mapping) else []:
        line, prob = C.to_float(key), C.to_float(value)
        if line is not None and prob is not None and 0.0 <= prob <= 1.0:
            points.append((line, prob))
    points.sort()
    return points


def ladder_basis(entry: Mapping[str, Any], spec: MarketSpec) -> str:
    """Which quantity THIS row's ladder is: `if_playing`, `unconditional`, `zero` or `none`.

    The BOARD's rule, not a second copy of it: `soccer_projections.ladder_conditioning`
    reads the producer's `ladder_conditioning` stamp, and for a file built before
    the stamp the exact test (a ladder equal to Poisson on the unconditional mean
    at 0.5 IS that; any other value is the start/sub mixture).
    """
    from syndicate.features.shared import soccer_projections

    if not spec.ladder:
        return "none"
    state = soccer_projections.ladder_conditioning(entry, spec.ladder)
    return {soccer_projections.CONDITIONAL_ON_APPEARING: "if_playing",
            soccer_projections.UNCONDITIONAL: "unconditional", "zero": "zero"}.get(state, "none")


def board_prices_ladder(market: str, basis: str) -> bool:
    """Whether the board prices a ladder of this basis for this market (`#673`)."""
    from syndicate.features.shared import soccer_projections

    family = soccer_projections._FAMILY_CONDITIONING.get(market)
    wanted = {soccer_projections.CONDITIONAL_ON_APPEARING: "if_playing",
              soccer_projections.UNCONDITIONAL: "unconditional"}.get(family or "")
    return basis == "zero" or basis == wanted


_BASIS_TEXT = {
    "if_playing": "IF HE PLAYS (start/sub mixture; books void on a DNP)",
    "unconditional": "UNCONDITIONAL (includes the chance he does not play)",
    "zero": "zero mean: the sim gives him no volume",
    "unverified": "basis not verifiable from the artifact",
    "none": "no ladder published",
}


# ---------------------------------------------------------------------------
# live_state boxes
# ---------------------------------------------------------------------------


def live_state_files(roots: list[Path], league: str, before_date: str) -> list[tuple[str, Path]]:
    """Newest-first dated live_state files for ONE league, strictly before the match date.

    First root wins per date. At most `MAX_LIVE_STATE_FILES`, within `FORM_LOOKBACK_DAYS`.
    """
    if not league or not before_date:
        return []
    try:
        floor = (datetime.fromisoformat(before_date) - timedelta(days=FORM_LOOKBACK_DAYS)).date().isoformat()
    except ValueError:
        return []
    by_date: dict[str, Path] = {}
    for root in roots:
        folder = Path(root) / league / "api" / "live_state"
        try:
            candidates = list(folder.glob("live_state_????-??-??.json"))
        except OSError:
            continue
        for path in candidates:
            iso = path.stem[len("live_state_"):]
            if iso >= before_date or iso < floor:
                continue
            by_date.setdefault(iso, path)
    return [(iso, by_date[iso]) for iso in sorted(by_date, reverse=True)[:MAX_LIVE_STATE_FILES]]


@dataclass
class BoxScan:
    files: int = 0
    files_with_player_box: int = 0
    newest_file: str = ""
    oldest_file: str = ""
    appearances: list[dict[str, Any]] = field(default_factory=list)
    unused: list[dict[str, Any]] = field(default_factory=list)
    not_in_roster: list[dict[str, Any]] = field(default_factory=list)
    team_box_without_players: list[str] = field(default_factory=list)
    ambiguous: int = 0
    team_matches: list[dict[str, Any]] = field(default_factory=list)
    opponent_matches: list[dict[str, Any]] = field(default_factory=list)


def _stat_int(stats: Mapping[str, Any], key: str) -> float | None:
    return C.to_float(str((stats or {}).get(key) or "").replace("%", "") or None)


def _team_view(box: Mapping[str, Any], side: str, iso: str) -> dict[str, Any]:
    other = "away" if side == "home" else "home"
    teams = box.get("teams") or {}
    own = (teams.get(side) or {}).get("stats") or {}
    opp = (teams.get(other) or {}).get("stats") or {}
    return {
        "date": iso,
        "event_id": str(box.get("event_id") or ""),
        "venue": side,
        "opponent": str(box.get(f"{other}_team") or ""),
        "shots_for": _stat_int(own, "Shots"),
        "sot_for": _stat_int(own, "On target"),
        "goals_for": C.to_float(box.get(f"score_{side}")),
        "shots_against": _stat_int(opp, "Shots"),
        "sot_against": _stat_int(opp, "On target"),
        "goals_against": C.to_float(box.get(f"score_{other}")),
    }


def _box_side_of(box: Mapping[str, Any], team: str) -> str | None:
    from syndicate.features.shared.team_aliases import teams_match

    if not team:
        return None
    hits = [side for side in ("home", "away") if teams_match("soccer", box.get(f"{side}_team"), team)]
    return hits[0] if len(hits) == 1 else None


def scan_boxes(files: list[tuple[str, Path]], ctx: Resolved, subject: PropSubject) -> BoxScan:
    from syndicate.features.shared import population_outcomes_soccer as grader

    scan = BoxScan()
    entry = ctx.entry or {}
    names = [subject.player_name]
    if entry.get("player_name") and not C.names_match(entry.get("player_name"), subject.player_name):
        names.append(str(entry.get("player_name")))
    for iso, path in files:
        try:
            payload = C.load_json(path)
        except Exception:
            logger.exception("prop_evidence soccer: unreadable %s", path)
            continue
        scan.files += 1
        scan.newest_file = scan.newest_file or iso
        scan.oldest_file = iso
        boxes = payload.get("match_box") if isinstance(payload, dict) else None
        if not isinstance(boxes, dict):
            continue
        if any(isinstance(b, dict) and b.get("players") for b in boxes.values()):
            scan.files_with_player_box += 1
        for box in boxes.values():
            if not isinstance(box, dict) or not grader.is_final(box):
                continue
            opp_side = _box_side_of(box, ctx.opponent)
            if opp_side:
                scan.opponent_matches.append(_team_view(box, opp_side, iso))
            side = _box_side_of(box, ctx.team)
            if not side:
                continue
            view = _team_view(box, side, iso)
            scan.team_matches.append(view)
            if not entry:
                continue
            if not box.get("players"):
                scan.team_box_without_players.append(iso)
                continue
            player, why = None, None
            for name in names:
                player, why = grader.find_player(box, name)
                if player is not None or why == grader.REASON_PLAYER_AMBIGUOUS:
                    break
            if player is None:
                if why == grader.REASON_PLAYER_AMBIGUOUS:
                    scan.ambiguous += 1
                else:
                    scan.not_in_roster.append(view)
                continue
            own_roster = ((box.get("players") or {}).get(side) or {}).get("players") or []
            if not any(candidate is player for candidate in own_roster):
                # A namesake on the other club, not him.
                scan.not_in_roster.append(view)
                continue
            if not player.get("appeared"):
                scan.unused.append(view)
                continue
            game = dict(view)
            game.update({
                "minutes": C.to_float(player.get("minutes")),
                "starter": bool(player.get("starter")),
                "goals": C.to_float(player.get("goals")),
                "assists": C.to_float(player.get("assists")),
                "shots": C.to_float(player.get("shots")),
                "shots_on_target": C.to_float(player.get("shots_on_target")),
            })
            goals, _ = grader.qualifying_goals(box)
            for which in ("first", "last"):
                if goals is None:
                    game[f"{which}_goal"] = None
                elif not goals:
                    game[f"{which}_goal"] = 0.0
                else:
                    scorer, _ = grader.deciding_scorer(goals, which)
                    game[f"{which}_goal"] = None if scorer is None else float(scorer == C.name_key(player.get("player_name")))
            scan.appearances.append(game)
    return scan


# ---------------------------------------------------------------------------
# Season rates
# ---------------------------------------------------------------------------


def _is_espn(row: Mapping[str, Any]) -> bool:
    return str(row.get("source") or "").strip().lower().startswith("espn")


def season_rates(roots: list[Path], league: str, entry: Mapping[str, Any], match_date: str) -> list[tuple[str, dict[str, str], Path]]:
    """The player's row in the two newest `players_<season>.csv` not after the match year."""
    if not league or not entry:
        return []
    try:
        year = int(match_date[:4])
    except ValueError:
        return []
    by_season: dict[str, Path] = {}
    for root in roots:
        folder = Path(root) / league / "players"
        try:
            candidates = list(folder.glob("players_????.csv"))
        except OSError:
            continue
        for path in candidates:
            season = path.stem[len("players_"):]
            if season.isdigit() and int(season) <= year:
                by_season.setdefault(season, path)
    player_id = str(entry.get("player_id") or "").strip()
    out: list[tuple[str, dict[str, str], Path]] = []
    for season in sorted(by_season, reverse=True)[:2]:
        path = by_season[season]
        by_id: dict[str, str] | None = None
        by_name: list[dict[str, str]] = []
        try:
            for row in C.iter_csv(path):
                if player_id and str(row.get("player_id") or "").strip() == player_id:
                    by_id = row
                    break
                if C.names_match(row.get("player_name"), entry.get("player_name")):
                    by_name.append(row)
        except Exception:
            logger.exception("prop_evidence soccer: unreadable %s", path)
            continue
        row = by_id or (by_name[0] if len(by_name) == 1 else None)
        if row is not None:
            out.append((season, dict(row), path))
    return out


# ---------------------------------------------------------------------------
# Layers
# ---------------------------------------------------------------------------


def _pct_or_floor(prob: float | None) -> str:
    if prob is None:
        return "—"
    if prob == 0.0:
        return "0.0% (rounds to zero at 4 dp; not a certainty)"
    return C.fmt_pct(prob)


def _board_projection_row(subject: PropSubject) -> list[Any] | None:
    projection = subject.projection or {}
    board_prob = C.to_float(projection.get("model_prob_over"))
    market_prob = C.to_float(projection.get("market_fair_prob_over"))
    projected = C.to_float(projection.get("projected"))
    if board_prob is None and market_prob is None and projected is None:
        return None
    basis = str(projection.get("basis") or "").strip()
    if board_prob is not None or market_prob is not None:
        value = f"{C.fmt_pct(board_prob)} vs {C.fmt_pct(market_prob)}"
    else:
        value = f"projected {C.fmt_num(projected, 2)}"
    return ["Board model P vs market fair", value + (f" (basis {basis})" if basis else "")]


def _minutes_row(entry: Mapping[str, Any]) -> list[Any]:
    share = C.to_float(entry.get("expected_minutes_share"))
    return ["Expected minutes share (sim)", C.fmt_pct(share) if share is not None else "—"]


def _player_sim(subject: PropSubject, ctx: Resolved, spec: MarketSpec | None) -> LayerEvidence:
    if subject.market_key in NO_MODEL_MARKETS:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NO_PRODUCER}:{NO_MODEL_MARKETS[subject.market_key]}")
    if spec is None:
        return absent(Layer.PLAYER_SIM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no soccer sim field")
    if ctx.match is None:
        return absent(Layer.PLAYER_SIM, ctx.match_reason)
    if ctx.entry is None:
        return absent(Layer.PLAYER_SIM, ctx.player_reason)
    entry = ctx.entry
    rows: list[list[Any]] = []
    charts: list[dict[str, Any]] = []
    facts: dict[str, Any] = {"match_id": ctx.match_id, "league": ctx.league, "player_join": ctx.player_join,
                             "expected_minutes_share": C.to_float(entry.get("expected_minutes_share"))}
    rows.append(_minutes_row(entry))

    if spec.kind == "count":
        basis = ladder_basis(entry, spec)
        points = ladder_points(entry, spec.ladder)
        prob = None
        if subject.line is not None:
            prob = next((p for line, p in points if line == subject.line), None)
        basis_text = _BASIS_TEXT[basis]
        label_line = C.fmt_line(subject.line)
        if subject.line is None:
            rows.append([f"Sim P(over) — {spec.label.lower()}", "board row carries no line"])
        elif prob is None:
            priced = ", ".join(C.fmt_line(line) for line, _ in points) or "none"
            rows.append([f"Sim P(over {label_line} {spec.label.lower()})",
                         f"not priced at {label_line} (ladder lines: {priced}); no nearest-line substitute"])
        else:
            rows.append([f"Sim P(over {label_line} {spec.label.lower()}) — {basis_text}", _pct_or_floor(prob)])
            if subject.side == "under":
                rows.append([f"Sim P(under {label_line}) — same basis", _pct_or_floor(1.0 - prob)])
        mean = C.to_float(entry.get(spec.mean))
        mean_playing = C.to_float(entry.get(spec.mean_if_playing))
        rows.append([f"Expected {spec.label.lower()}: if he plays / unconditional",
                     f"{C.fmt_num(mean_playing, 2)} / {C.fmt_num(mean, 2)}"])
        if points:
            rows.append(["How the ladder is priced", "Poisson on the match sim's team volume x his share "
                                                     "(a start/sub mixture when conditional), not simulation draws"])
        if basis != "none" and not board_prices_ladder(subject.market, basis):
            rows.append(["Board", "does NOT price this row from the ladder above: it answers a different question "
                                  "from the one the board prices for this market (books void on a DNP, `#673`); "
                                  "a rebuild of this match's artifact replaces it"])
        facts.update({"stat": spec.box_stat, "prob_over": prob, "ladder_basis": basis, "ladder": dict(points),
                      "mean": mean, "mean_if_playing": mean_playing})
        if points:
            marker = {"x": f"{subject.line:g}", "label": f"Board line {label_line}"} if prob is not None else None
            charts.append(chart(
                f"P(over line) {spec.label.lower()}, {basis_text.split(' (')[0].lower()} — {subject.player_name}",
                "Line", "% probability",
                [{"x": f"{line:g}", "y": round(100.0 * p, 2)} for line, p in points],
                Layer.PLAYER_SIM, marker=marker,
            ))
    else:
        anytime = C.to_float(entry.get("anytime_scorer_probability"))
        anytime_playing = C.to_float(entry.get("anytime_scorer_probability_if_playing"))
        expected_goals = C.to_float(entry.get("expected_goals"))
        basis = "unconditional" if (anytime is not None and expected_goals is not None
                                    and abs(anytime - (1.0 - math.exp(-expected_goals))) <= _POISSON_TOLERANCE) else "unverified"
        rows.append([f"Sim P(scores) — {_BASIS_TEXT[basis]}; the board prices this field", _pct_or_floor(anytime)])
        rows.append(["Sim P(scores) — IF HE PLAYS (start/sub mixture)", _pct_or_floor(anytime_playing)])
        rows.append(["Expected goals (unconditional)", C.fmt_num(expected_goals, 3)])
        rows.append(["Sim P(2+ goals) / P(goal or assist), unconditional",
                     f"{_pct_or_floor(C.to_float(entry.get('two_or_more_scorer_probability')))} / "
                     f"{_pct_or_floor(C.to_float(entry.get('goal_or_assist_probability')))}"])
        facts.update({"stat": "goals", "prob_yes": anytime, "prob_yes_if_playing": anytime_playing,
                      "expected_goals": expected_goals, "probability_basis": basis})
        if spec.kind in ("first", "last"):
            projection = subject.projection or {}
            race = C.to_float(projection.get("model_prob_over"))
            rows.append([f"Board P({spec.kind} goalscorer) — Poisson scorer race, computed at board build",
                         _pct_or_floor(race) if race is not None else "not on this row (the artifact publishes no race)"])
            if projection.get("attributable_share") is not None:
                rows.append(["Share of match goal rate the listed players cover", C.fmt_pct(projection.get("attributable_share"))])
            if projection.get("assumption"):
                rows.append(["Assumption", str(projection.get("assumption"))])
            facts["race_prob"] = race

    board_row = _board_projection_row(subject)
    if board_row and spec.kind not in ("first", "last"):
        rows.append(board_row)
    caveat = LEDGER_CAVEATS.get(subject.market_key)
    if caveat:
        rows.append(["Measured caveat (ledger)", caveat])
        facts["caveats"] = [{"text": caveat, "source": LEDGER_SOURCE}]
    generated = ctx.generated_at_for()
    title = (f"Player sim — {subject.player_name} {subject.market} {C.fmt_line(subject.line) if subject.line is not None else ''}"
             f" ({ctx.team} vs {ctx.opponent}, {ctx.match_date})").replace("  ", " ")
    return LayerEvidence(Layer.PLAYER_SIM, tables=[table(title, ["Measure", "Value"], rows, Layer.PLAYER_SIM)],
                         charts=charts, facts=facts, source="soccer:recommendations.player_props",
                         as_of=generated or ctx.match_date)


def _form_line_side(subject: PropSubject, spec: MarketSpec) -> tuple[float | None, str]:
    if spec.kind in ("anytime", "first", "last"):
        return 0.5, "under" if subject.side == "no" else "over"
    return subject.line, "under" if subject.side == "under" else "over"


def _form_value(game: Mapping[str, Any], spec: MarketSpec) -> float | None:
    if spec.kind in ("first", "last"):
        return C.to_float(game.get(f"{spec.kind}_goal"))
    return C.to_float(game.get(spec.box_stat or ""))


def _vs_text(view: Mapping[str, Any]) -> str:
    return f"{view.get('date')} {'v' if view.get('venue') == 'home' else '@'} {view.get('opponent')}"


def _recent_form(subject: PropSubject, ctx: Resolved, spec: MarketSpec | None, files: list[tuple[str, Path]],
                 scan: BoxScan | None) -> LayerEvidence:
    if subject.market_key in NO_MODEL_MARKETS:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_PRODUCER}:{NO_MODEL_MARKETS[subject.market_key]}")
    if spec is None:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NOT_APPLICABLE}:market {subject.market} has no box stat")
    if ctx.match is None:
        return absent(Layer.RECENT_FORM, ctx.match_reason)
    if ctx.entry is None:
        return absent(Layer.RECENT_FORM, ctx.player_reason)
    if not files or scan is None:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_ARTIFACT}:no {ctx.league} live_state_<date>.json in the "
                                         f"{FORM_LOOKBACK_DAYS} days before {ctx.match_date}")
    if scan.files_with_player_box == 0:
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_SAMPLE}:{scan.files} {ctx.league} live_state files "
                                         f"{scan.oldest_file}..{scan.newest_file}, none with a player box "
                                         f"(player boxes published since {PLAYER_BOXES_SINCE})")
    if not scan.appearances:
        span = f"{ctx.league} live_state {scan.oldest_file}..{scan.newest_file}"
        if not scan.team_matches:
            return absent(Layer.RECENT_FORM, f"{ABSENT_NO_SAMPLE}:no final {ctx.team} match in {span}")
        if scan.ambiguous and not (scan.unused or scan.not_in_roster):
            return absent(Layer.RECENT_FORM, f"{ABSENT_NO_MATCH}:{subject.player_name} matched several players "
                                             f"in {scan.ambiguous} {ctx.team} box(es) in {span}")
        detail = (f"{len(scan.unused)} unused-sub, {len(scan.not_in_roster)} not in box roster, "
                  f"{len(scan.team_box_without_players)} box(es) without players, {scan.ambiguous} ambiguous, "
                  f"over {len(scan.team_matches)} final {ctx.team} matches")
        return absent(Layer.RECENT_FORM, f"{ABSENT_NO_SAMPLE}:{subject.player_name} has no appearance in {span} ({detail})")
    games = scan.appearances[:C.LAST_N_GAMES]
    line, side = _form_line_side(subject, spec)
    values = [_form_value(g, spec) for g in games]
    rate = C.hit_rate(values, line, side)
    is_scorer = spec.kind in ("anytime", "first", "last")
    stat_label = {"first": "Scored first", "last": "Scored last"}.get(spec.kind, spec.label)
    columns = ["Date", "Opp", "Min", "Start", stat_label]
    rows: list[list[Any]] = []
    for game, value in zip(games, values):
        cell = ("yes" if value else "no") if spec.kind in ("first", "last") and value is not None else C.fmt_num(value, 0)
        rows.append([game["date"], f"{'v' if game['venue'] == 'home' else '@'} {game['opponent']}",
                     C.fmt_num(game.get("minutes"), 0), "yes" if game.get("starter") else "no", cell])
    clean = [v for v in values if v is not None]
    minutes = [g.get("minutes") for g in games if g.get("minutes") is not None]
    rows.append([f"L{len(games)} avg", "", C.fmt_num(sum(minutes) / len(minutes), 0) if minutes else "—", "",
                 C.fmt_num(sum(clean) / len(clean), 2) if clean else "—"])
    if rate:
        if is_scorer:
            verb = {"anytime": "scored", "first": "scored the first goal", "last": "scored the last goal"}[spec.kind]
            text = f"{verb} in {rate['over']} of {rate['games']} appearances"
        else:
            text = C.hit_rate_text(rate)
        rows.append([f"Hit rate vs board {C.fmt_line(subject.line) if not is_scorer else subject.side or 'yes'}", "", "", "", text])
    if scan.unused:
        rows.append(["Listed but did not play (void, not a miss)", ", ".join(_vs_text(v) for v in scan.unused[:6]), "", "", ""])
    if scan.not_in_roster:
        rows.append([f"{ctx.team} played, he was not in the box roster", ", ".join(_vs_text(v) for v in scan.not_in_roster[:6]), "", "", ""])
    if len(games) < SMALL_SAMPLE:
        rows.append([f"SMALL SAMPLE: {len(games)} appearance{'s' if len(games) != 1 else ''} with a player box "
                     f"(live_state {scan.oldest_file}..{scan.newest_file}; boxes published since {PLAYER_BOXES_SINCE})", "", "", "", ""])
    stale_days = _days_between(games[0]["date"], ctx.match_date)
    if stale_days is not None and stale_days > STALE_FORM_DAYS:
        rows.append([f"STALE: newest appearance is {stale_days} days before this match", "", "", "", ""])
    charts: list[dict[str, Any]] = []
    series = [{"date": g["date"], "value": v} for g, v in zip(games, values)]
    chart_obj = C.form_chart(series, stat_key="value", stat_label=stat_label, player=subject.player_name,
                             line=None if is_scorer else subject.line)
    if chart_obj:
        charts.append(chart_obj)
    return LayerEvidence(
        Layer.RECENT_FORM,
        tables=[table(f"Recent matches — {subject.player_name} ({ctx.league} live_state box, through {games[0]['date']})",
                      columns, rows, Layer.RECENT_FORM)],
        charts=charts,
        facts={"games": len(games), "values": values, "hit_rate": rate, "newest_game": games[0]["date"],
               "small_sample": len(games) < SMALL_SAMPLE, "stale_days": stale_days,
               "unused_dates": [v["date"] for v in scan.unused], "not_in_roster_dates": [v["date"] for v in scan.not_in_roster],
               "ambiguous_boxes": scan.ambiguous, "files_read": scan.files,
               "files_with_player_box": scan.files_with_player_box, "window": [scan.oldest_file, scan.newest_file]},
        source="soccer:live_state.match_box",
        as_of=games[0]["date"],
    )


def _days_between(earlier: str, later: str) -> int | None:
    try:
        return (datetime.fromisoformat(later[:10]) - datetime.fromisoformat(earlier[:10])).days
    except ValueError:
        return None


def _avg(values: list[float | None]) -> float | None:
    clean = [v for v in values if v is not None]
    return sum(clean) / len(clean) if clean else None


def goals_stand_in_for_xg(detail: Mapping[str, Any]) -> bool:
    """Whether a team rating's `xg_*_per_match` is really GOALS.

    `loaders.team_rows_from_match_history` (the football-data path) writes
    `xg_for = goals` and deliberately emits no `goals_for_per_match`, while it
    does emit `shots_per_match` / `shots_allowed_per_match`. The understat path
    emits `goals_for_per_match` beside real xG. So: shot volume without a
    separate goals field is the stand-in's signature.
    """
    if not isinstance(detail, Mapping) or not detail:
        return False
    has_shots = detail.get("shots_per_match") is not None or detail.get("shots_allowed_per_match") is not None
    return has_shots and detail.get("goals_for_per_match") is None


def _ppda_text(value: Any) -> str:
    number = C.to_float(value)
    if number is None:
        return "—"
    if number == 0.0:
        # `compute_team_ratings` writes 0.0 when a league's history has no PPDA
        # (loaders.py `"ppda": ... else 0.0`); the sim's own reader drops it.
        return "not measured (0.0 sentinel)"
    return C.fmt_num(number, 1)


def _matchup(subject: PropSubject, ctx: Resolved, scan: BoxScan | None) -> LayerEvidence:
    if ctx.match is None:
        return absent(Layer.MATCHUP, ctx.match_reason)
    if ctx.entry is None:
        return absent(Layer.MATCHUP, f"{ABSENT_NO_MATCH}:opponent unknown without the player's sim row ({ctx.player_reason})")
    match = ctx.match
    other = "away" if ctx.side == "home" else "home"
    meta = match.get("adapter_metadata") or {}
    own = meta.get(f"{ctx.side}_rating_detail") or {}
    opp = meta.get(f"{other}_rating_detail") or {}
    volume = match.get("volume_projection") or {}
    team_proj = match.get("team_projection") or {}
    stand_in = goals_stand_in_for_xg(own) or goals_stand_in_for_xg(opp)
    xg_label = "Goals (xG stand-in) for / match" if stand_in else "xG for / match"
    xga_label = "Goals (xG stand-in) against / match" if stand_in else "xG against / match"
    rows = [
        [xg_label, C.fmt_num(own.get("xg_for_per_match"), 2), C.fmt_num(opp.get("xg_for_per_match"), 2)],
        [xga_label, C.fmt_num(own.get("xg_against_per_match"), 2), C.fmt_num(opp.get("xg_against_per_match"), 2)],
        ["Goals for / against per match", f"{C.fmt_num(own.get('goals_for_per_match'), 2)} / {C.fmt_num(own.get('goals_against_per_match'), 2)}",
         f"{C.fmt_num(opp.get('goals_for_per_match'), 2)} / {C.fmt_num(opp.get('goals_against_per_match'), 2)}"],
        ["Shots / shots allowed per match", f"{C.fmt_num(own.get('shots_per_match'), 1)} / {C.fmt_num(own.get('shots_allowed_per_match'), 1)}",
         f"{C.fmt_num(opp.get('shots_per_match'), 1)} / {C.fmt_num(opp.get('shots_allowed_per_match'), 1)}"],
        ["Clean-sheet rate", C.fmt_pct(own.get("clean_sheet_rate")), C.fmt_pct(opp.get("clean_sheet_rate"))],
        ["Attack / defence rating", f"{C.fmt_num(own.get('attack_rating'), 3)} / {C.fmt_num(own.get('defense_rating'), 3)}",
         f"{C.fmt_num(opp.get('attack_rating'), 3)} / {C.fmt_num(opp.get('defense_rating'), 3)}"],
        ["PPDA (lower = more pressing)", _ppda_text(own.get("ppda")), _ppda_text(opp.get("ppda"))],
        ["Matches rated", C.fmt_num(own.get("matches"), 0), C.fmt_num(opp.get("matches"), 0)],
        ["Sim projected shots (this match)", C.fmt_num(volume.get(f"{ctx.side}_shots"), 1), C.fmt_num(volume.get(f"{other}_shots"), 1)],
        ["Sim projected shots on target", C.fmt_num(volume.get(f"{ctx.side}_shots_on_target"), 1),
         C.fmt_num(volume.get(f"{other}_shots_on_target"), 1)],
        ["Sim projected goals", C.fmt_num(team_proj.get(f"{ctx.side}_mean"), 2), C.fmt_num(team_proj.get(f"{other}_mean"), 2)],
    ]
    for label, key in (("Rating matched to team data", f"{ctx.side}_rating_matched"),):
        own_flag, opp_flag = meta.get(key), meta.get(f"{other}_rating_matched")
        if own_flag is not None or opp_flag is not None:
            rows.append([label, "yes" if own_flag else "no", "yes" if opp_flag else "no"])
    tables = [table(f"Matchup — {ctx.team} vs {ctx.opponent} (team ratings the sim used, and its volume)",
                    ["Measure", ctx.team, ctx.opponent], [r for r in rows if any(c != "—" and c != "— / —" for c in r[1:])],
                    Layer.MATCHUP)]
    facts: dict[str, Any] = {"opponent": ctx.opponent, "team": ctx.team, "side": ctx.side,
                             "opponent_rating": opp, "team_rating": own, "xg_is_goals_stand_in": stand_in,
                             "projected_volume": {k: volume.get(k) for k in (f"{ctx.side}_shots", f"{other}_shots",
                                                                             f"{ctx.side}_shots_on_target", f"{other}_shots_on_target")}}
    recent = (scan.opponent_matches if scan else [])[:C.LAST_N_GAMES]
    if recent:
        opp_rows = [[_vs_text(v), C.fmt_num(v.get("shots_against"), 0), C.fmt_num(v.get("sot_against"), 0),
                     C.fmt_num(v.get("goals_against"), 0)] for v in recent]
        conceded = {"shots": _avg([v.get("shots_against") for v in recent]), "sot": _avg([v.get("sot_against") for v in recent]),
                    "goals": _avg([v.get("goals_against") for v in recent])}
        opp_rows.append([f"Avg conceded, last {len(recent)}", C.fmt_num(conceded["shots"], 1), C.fmt_num(conceded["sot"], 1),
                         C.fmt_num(conceded["goals"], 2)])
        tables.append(table(f"{ctx.opponent} recent matches — what they conceded (live_state team stats)",
                            ["Match", "Shots conceded", "SOT conceded", "Goals conceded"], opp_rows, Layer.MATCHUP))
        facts["opponent_recent_conceded"] = {"matches": len(recent), **conceded}
    vs = [g for g in (scan.appearances if scan else []) if C.names_match(g.get("opponent"), ctx.opponent)]
    if vs:
        facts["vs_opponent_appearances"] = len(vs)
    return LayerEvidence(Layer.MATCHUP, tables=tables, facts=facts, source="soccer:recommendations.adapter_metadata+live_state",
                         as_of=ctx.match_date)


_RATE_SPECS: tuple[tuple[str, str, str, str, int, bool], ...] = (
    # (understat label, espn label, understat key, espn key, digits, percent)
    ("Minutes", "Minutes", "minutes", "minutes_played", 0, False),
    ("Games", "Appearances", "games", "appearances", 0, False),
    ("", "Starts", "", "starts", 0, False),
    ("Shots per 90", "Shots per 90", "shots_per90", "shots_per90", 2, False),
    ("xG per 90", "Goals per 90 (ESPN: `xg_per90` holds GOALS, no xG exists)", "xg_per90", "xg_per90", 2, False),
    ("xA per 90", "Assists per 90 (ESPN: `xa_per90` holds ASSISTS, no xA exists)", "xa_per90", "xa_per90", 2, False),
    ("Goals per 90", "", "goals_per90", "", 2, False),
    ("Assists per 90", "", "assists_per90", "", 2, False),
    ("Key passes per 90", "", "key_passes_per90", "", 2, False),
    ("", "Shot-on-target rate", "", "shot_on_target_rate", 1, True),
    ("Expected minutes share (season file)", "Expected minutes share (season file)", "expected_minutes_share",
     "expected_minutes_share", 1, True),
    ("Weight on this season's own rate", "", "rate_own_weight", "", 1, True),
)


def _advanced(subject: PropSubject, ctx: Resolved, spec: MarketSpec | None, rates, meta: Mapping[str, Any]) -> LayerEvidence:
    if ctx.match is None:
        return absent(Layer.ADVANCED, ctx.match_reason)
    if ctx.entry is None:
        return absent(Layer.ADVANCED, ctx.player_reason)
    entry = ctx.entry
    tables: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}
    if rates:
        espn_flags = {season: _is_espn(row) for season, row, _ in rates}
        columns = ["Measure"] + [f"{season} ({'ESPN box scores' if espn_flags[season] else row.get('source') or 'understat'})"
                                 for season, row, _ in rates]
        rows: list[list[Any]] = []
        for u_label, e_label, u_key, e_key, digits, percent in _RATE_SPECS:
            labels = {e_label if espn_flags[s] else u_label for s, _, _ in rates} - {""}
            if not labels:
                continue
            cells = []
            for season, row, _ in rates:
                key = e_key if espn_flags[season] else u_key
                value = C.to_float(row.get(key)) if key else None
                cells.append((C.fmt_pct(value) if percent else C.fmt_num(value, digits)) if value is not None else "—")
            if all(cell == "—" for cell in cells):
                continue
            rows.append([" | ".join(sorted(labels)), *cells])
        tables.append(table(f"Season rates — {subject.player_name} ({ctx.league} players_<season>.csv)", columns, rows, Layer.ADVANCED))
        facts["season_rates"] = {
            season: {"source": row.get("source"), "xg_column_meaning": "goals_per90" if espn_flags[season] else "xg_per90",
                     "xa_column_meaning": "assists_per90" if espn_flags[season] else "xa_per90",
                     "minutes": C.to_float(row.get("minutes_played" if espn_flags[season] else "minutes")),
                     "shots_per90": C.to_float(row.get("shots_per90")), "xg_per90": C.to_float(row.get("xg_per90"))}
            for season, row, _ in rates
        }
    else:
        facts["season_rates"] = f"{ABSENT_NO_ARTIFACT}:no players_<season>.csv row for {subject.player_name} in {ctx.league}"

    volume = ctx.match.get("volume_projection") or {}
    role_rows = [["Position (sim)", str(entry.get("position") or "—")], _minutes_row(entry)]
    team_shots = C.to_float(volume.get(f"{ctx.side}_shots"))
    shots = C.to_float(entry.get("expected_shots"))
    if team_shots and shots is not None:
        share = shots / team_shots
        role_rows.append([f"Share of {ctx.team} sim shots (unconditional)", C.fmt_pct(share)])
        facts["team_shot_share"] = share
    for label, key in (("Expected shots if he plays", "expected_shots_if_playing"),
                       ("Expected shots on target if he plays", "expected_shots_on_target_if_playing"),
                       ("Expected assists if he plays (minutes rescale)", "expected_assists_if_playing"),
                       ("Expected goals (unconditional)", "expected_goals")):
        value = C.to_float(entry.get(key))
        if value is not None:
            role_rows.append([label, C.fmt_num(value, 3)])
    substrate = meta.get("player_substrate") if isinstance(meta.get("player_substrate"), dict) else {}
    shrink = substrate.get("espn_goal_shrink") if isinstance(substrate.get("espn_goal_shrink"), dict) else {}
    if shrink.get("state") == "applied":
        role_rows.append(["ESPN goal rates the sim used", f"shrunk at load (stabiliser {C.fmt_num(shrink.get('stabilizer'), 0)} min), "
                                                          "so they differ from the raw per-90 column above"])
        facts["espn_goal_shrink"] = shrink.get("state")
    tables.append(table(f"Role in this sim — {subject.player_name} ({ctx.match_date})", ["Measure", "Value"], role_rows, Layer.ADVANCED))
    facts["expected_minutes_share"] = C.to_float(entry.get("expected_minutes_share"))
    as_of = C.mtime_iso(rates[0][2]) if rates else ctx.match_date
    return LayerEvidence(Layer.ADVANCED, tables=tables, facts=facts, source="soccer:players_<season>.csv+player_props", as_of=as_of)


def _game_sim(subject: PropSubject, ctx: Resolved, meta: Mapping[str, Any]) -> LayerEvidence:
    if ctx.match is None:
        return absent(Layer.GAME_SIM, ctx.match_reason)
    match = ctx.match
    matchup = match.get("matchup") or {}
    home, away = str(matchup.get("home_team") or subject.home_team), str(matchup.get("away_team") or subject.away_team)
    win = match.get("win_probability") or {}
    team = match.get("team_projection") or {}
    volume = match.get("volume_projection") or {}
    goals = match.get("total_distribution") or {}
    periods = match.get("periods") or {}
    if not win and not team:
        return absent(Layer.GAME_SIM, f"{ABSENT_NO_MATCH}:match {ctx.match_id} carries no win probability or team projection")
    h1, h2 = periods.get("h1") or {}, periods.get("h2") or {}
    rows = [
        ["Win probability", C.fmt_pct(win.get("away")), C.fmt_pct(win.get("home"))],
        ["Expected goals", C.fmt_num(team.get("away_mean"), 2), C.fmt_num(team.get("home_mean"), 2)],
        ["Expected goals 1st / 2nd half", f"{C.fmt_num(h1.get('away_mean'), 2)} / {C.fmt_num(h2.get('away_mean'), 2)}",
         f"{C.fmt_num(h1.get('home_mean'), 2)} / {C.fmt_num(h2.get('home_mean'), 2)}"],
        ["Shots", C.fmt_num(volume.get("away_shots"), 1), C.fmt_num(volume.get("home_shots"), 1)],
        ["Shots on target", C.fmt_num(volume.get("away_shots_on_target"), 1), C.fmt_num(volume.get("home_shots_on_target"), 1)],
        ["Corners", C.fmt_num(volume.get("away_corners"), 1), C.fmt_num(volume.get("home_corners"), 1)],
    ]
    total_mean = goals.get("mean") if goals.get("mean") is not None else team.get("total_mean")
    outlook = [
        ["Draw probability", C.fmt_pct(win.get("draw"))],
        ["Total goals (mean)", C.fmt_num(total_mean, 2)],
        ["Over 2.5 goals", C.fmt_pct(goals.get("over_2_5_probability"))],
        ["Both teams to score", C.fmt_pct(goals.get("both_teams_scored_probability"))],
        [f"{home} margin (mean)", C.fmt_num(team.get("margin_mean"), 2)],
    ]
    sims = match.get("simulations") or meta.get("simulations")
    tables = [
        table(f"Match sim — {away} @ {home} ({ctx.match_date}, {sims or '?'} sims)", ["Metric", away, home],
              [r for r in rows if any(c not in ("—", "— / —") for c in r[1:])], Layer.GAME_SIM),
        table(f"Match sim goals — {away} @ {home}", ["Metric", "Value"], [r for r in outlook if r[1] != "—"], Layer.GAME_SIM),
    ]
    by_total: dict[int, float] = {}
    for score, probability in (match.get("scoreline_probabilities") or {}).items():
        parts = str(score).replace(":", "-").split("-")
        weight = C.to_float(probability)
        try:
            total = int(parts[0]) + int(parts[1])
        except (IndexError, ValueError):
            continue
        if weight is not None:
            by_total[total] = by_total.get(total, 0.0) + weight
    charts: list[dict[str, Any]] = []
    if by_total:
        charts.append(chart(f"Simulated total goals — {away} @ {home}", "Total goals", "% probability",
                            [{"x": str(k), "y": round(100.0 * by_total[k], 2)} for k in sorted(by_total)], Layer.GAME_SIM))
    generated = ctx.generated_at_for()
    return LayerEvidence(Layer.GAME_SIM, tables=tables, charts=charts,
                         facts={"match_id": ctx.match_id, "league": ctx.league, "win_probability": dict(win),
                                "team_projection": dict(team), "total_distribution": dict(goals), "simulations": sims},
                         source="soccer:recommendations.matches", as_of=generated or ctx.match_date)


def _hours_before(generated_at: Any, kickoff: Any) -> float | None:
    try:
        made = datetime.fromisoformat(str(generated_at).replace("Z", "+00:00"))
        start = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
    except ValueError:
        return None
    if made.tzinfo is None:
        made = made.replace(tzinfo=timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return round((start - made).total_seconds() / 3600.0, 1)


def _environment(subject: PropSubject, ctx: Resolved, meta: Mapping[str, Any], scan: BoxScan | None) -> LayerEvidence:
    if ctx.match is None:
        return absent(Layer.ENVIRONMENT, ctx.match_reason)
    match = ctx.match
    rows: list[list[Any]] = []
    facts: dict[str, Any] = {"lineups_injuries": f"{ABSENT_NO_PRODUCER}:no soccer producer publishes confirmed lineups or injuries"}
    if ctx.entry is not None:
        rows.append(["Venue", f"{'Home' if ctx.side == 'home' else 'Away'} ({ctx.team} {'hosts' if ctx.side == 'home' else 'visits'} {ctx.opponent})"])
        facts["side"] = ctx.side
    kickoff = match.get("kickoff")
    rows.append(["Kickoff (UTC) / status at build", f"{kickoff or '—'} / {match.get('status_state') or '—'}"])
    generated = ctx.generated_at_for()
    if generated:
        lead = _hours_before(generated, kickoff)
        rows.append(["Sim generated", f"{str(generated)[:16]}Z" + (f" ({lead:g} h before kickoff)" if lead is not None else "")])
        facts["generated_at"] = generated
        facts["hours_before_kickoff"] = lead
    anchor = meta.get("anchor") if isinstance(meta.get("anchor"), dict) else {}
    if anchor:
        state = str(anchor.get("state") or "—")
        rows.append(["Market anchor", f"{state} (weight {C.fmt_num(anchor.get('weight'), 2)})"
                                      + (" — the sim is not blended toward market prices" if state == "disabled" else "")])
        facts["market_anchor"] = {"state": state, "weight": anchor.get("weight")}
    substrate = meta.get("player_substrate") if isinstance(meta.get("player_substrate"), dict) else {}
    if substrate:
        rows.append(["Player data the sim read", f"{', '.join(substrate.get('files') or []) or '—'}; newest season max minutes "
                                                  f"{C.fmt_num(substrate.get('latest_max_minutes'), 0)}"])
        facts["player_substrate"] = {k: substrate.get(k) for k in ("files", "latest_max_minutes", "clubs_ready", "clubs_seen")}
    audit = (match.get("squad_audit") or {}).get(ctx.side) if ctx.side else None
    if isinstance(audit, dict):
        rows.append([f"Sim squad audit ({ctx.team})", f"{audit.get('listed')} listed: {audit.get('current')} this season, "
                                                      f"{audit.get('prior_only')} prior-season only"])
        facts["squad_audit"] = dict(audit)
    if scan is not None and ctx.entry is not None and scan.team_matches:
        last = scan.team_matches[0]
        if any(g["date"] == last["date"] and g["event_id"] == last["event_id"] for g in scan.appearances):
            game = next(g for g in scan.appearances if g["event_id"] == last["event_id"])
            status = f"appeared, {'started' if game.get('starter') else 'off the bench'}, {C.fmt_num(game.get('minutes'), 0)} min"
        elif any(v["event_id"] == last["event_id"] for v in scan.unused):
            status = "in the squad, did not play"
        elif any(v["event_id"] == last["event_id"] for v in scan.not_in_roster):
            status = "not in the box roster (not in the squad, or a spelling miss)"
        elif last["date"] in scan.team_box_without_players:
            status = "unknown (that box carries no players)"
        else:
            status = "unknown"
        rows.append([f"Availability, last boxed {ctx.team} match ({_vs_text(last)})", status])
        facts["last_team_match_status"] = status
    rows.append(["Confirmed lineups / injuries", "not published — no soccer producer writes them"])
    return LayerEvidence(Layer.ENVIRONMENT,
                         tables=[table(f"Match environment — {subject.player_name} ({ctx.match_date})", ["Factor", "Value"], rows, Layer.ENVIRONMENT)],
                         facts=facts, source="soccer:recommendations+live_state", as_of=generated or ctx.match_date)


def build(subject: PropSubject) -> PropEvidence:
    evidence = PropEvidence(subject=subject, provider="soccer")
    spec = MARKETS.get(subject.market_key)
    ctx = resolve(subject)
    meta, _ = recommendations_meta(ctx)
    ctx.generated_at = str(meta.get("generated_at") or "")
    files = live_state_files(ctx.roots, ctx.league, ctx.match_date) if ctx.match is not None else []
    scan = scan_boxes(files, ctx, subject) if files else None
    rates = season_rates(ctx.roots, ctx.league, ctx.entry or {}, ctx.match_date) if ctx.entry is not None else []

    evidence.set(_player_sim(subject, ctx, spec))
    evidence.set(_recent_form(subject, ctx, spec, files, scan))
    evidence.set(_matchup(subject, ctx, scan))
    evidence.set(_advanced(subject, ctx, spec, rates, meta))
    evidence.set(_game_sim(subject, ctx, meta))
    evidence.set(_environment(subject, ctx, meta, scan))
    evidence.set(build_track_record(subject))
    return evidence
