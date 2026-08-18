"""As-of team form for football: metrics computed STRICTLY BEFORE a given game.

WHY THIS EXISTS. `build_nflverse_game_metrics` computes its EPA / success-rate /
pass-rate fields from **the game being predicted** — `_match_game_rows`
(`nflverse_ingestion.py:151`) filters play-by-play to rows where
`home_team == home AND away_team == away` for that season and week, i.e. one
game's plays. Measured 2026-08-18 over 285 games of 2023: the correlation
between that EPA differential and the final margin is **r = 0.988**. Those
fields restate the outcome. Feeding them to a model is leakage, and it is
invisible to every other check this repo has — a leaked field is 100% populated
by construction and looks maximally healthy to an input checklist.

This module is the legitimate replacement. Every metric here is aggregated over
games with `week < target_week` in the same season, or over the prior season
when there is no in-season history yet.

THE GUARANTEE, AND IT IS ENFORCED NOT PROMISED. `team_form_asof` never sees a
row from the target week or later, because the filter is applied when the rows
are read, not when they are aggregated. `assert_no_leakage()` re-derives the
correlation against realised margins and raises if it exceeds a prior-form
ceiling, so a future refactor that reintroduces same-game rows fails loudly
instead of silently producing a spectacular backtest.

WEEK 1 HAS NO IN-SEASON HISTORY, and pretending otherwise is its own bug. The
fallback is the PRIOR season's full-season form, which is the same device
`generate_smartsim2_nfl_preseason_projections.py` already uses for ratings
(`rating_source` reads `..._prior_season_fallback`). Where even that is absent
the team is reported as unfed rather than defaulted to a league average — a
neutral default is exactly the silent no-op `model_engine_standard.md` §4.2
warns about, and callers must be able to tell "average team" from "no data".
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[4]
DEFAULT_PBP_DIR = REPO / "data/nfl_source/tracking/nflverse/pbp"

# A prior-form feature must not restate the outcome. Season-to-date team
# strength genuinely predicts a single NFL game at roughly r = 0.3-0.5; in-game
# EPA measured 0.988. Anything above this ceiling means same-game rows have
# leaked back in.
LEAKAGE_CEILING_R = 0.65

# Below this many prior plays a team's form is noise dressed as a number.
# Reported as unfed rather than emitted, so a caller cannot mistake a
# two-game sample for a season of evidence.
MIN_PLAYS_FOR_FORM = 100


def _f(value: Any) -> float | None:
    if value in (None, "", "NA"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class TeamForm:
    """One team's form as of a point in time. `plays` is the denominator.

    Every field is Optional on purpose: `None` means "not enough prior data",
    which is a different statement from 0.0 and must stay distinguishable.
    """

    team: str
    plays: int = 0
    games: int = 0
    source: str = "none"
    offensive_epa: float | None = None
    success_rate: float | None = None
    pass_rate: float | None = None
    pass_rate_over_expectation: float | None = None
    explosive_play_rate: float | None = None
    red_zone_efficiency: float | None = None
    defensive_epa: float | None = None
    success_rate_allowed: float | None = None
    pace_seconds_per_play: float | None = None

    @property
    def is_fed(self) -> bool:
        return self.plays >= MIN_PLAYS_FOR_FORM and self.offensive_epa is not None


def _pbp_path(season: int, pbp_dir: Path | None = None) -> Path:
    return (pbp_dir or DEFAULT_PBP_DIR) / ("pbp_%d.csv" % season)


# Only these columns are read. Projecting at parse time is what makes a
# multi-week backtest affordable: the full pbp row carries ~380 columns, and
# keeping whole rows for four seasons is gigabytes. This is thirteen.
_NEEDED = (
    "game_id", "season", "week", "posteam", "defteam", "epa", "success",
    "pass", "yards_gained", "yardline_100", "touchdown", "play_type", "pass_oe",
)

# season -> projected rows, parsed once. Keyed by resolved path so a caller
# pointing at a fixture directory cannot collide with the real mirror.
_ROW_CACHE: dict[str, list[dict[str, Any]]] = {}


def _all_rows(season: int, pbp_dir: Path | None = None) -> list[dict[str, Any]]:
    """Every projected row for a season, parsed at most once per process.

    ADDED AFTER A MEASURED FAILURE, not speculatively. The first version
    re-read the 100 MB CSV on every `team_form_asof` call. A 40-game
    reachability run spans ~13 distinct weeks and each week also probes the
    prior season, so it performed ~26 full-file parses: 142 s of CPU across 32
    minutes of wall clock, about 7% utilisation and entirely I/O bound. Over the
    full 1,139-game experiment that pattern would have read the file hundreds of
    times.
    """
    path = _pbp_path(season, pbp_dir)
    key = str(path.resolve()) if path.exists() else str(path)
    cached = _ROW_CACHE.get(key)
    if cached is not None:
        return cached
    rows: list[dict[str, Any]] = []
    if path.is_file():
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
            for row in csv.DictReader(fh):
                rows.append({c: row.get(c) for c in _NEEDED})
    _ROW_CACHE[key] = rows
    return rows


def _read_rows(season: int, *, before_week: int | None, pbp_dir: Path | None = None) -> Iterable[dict[str, Any]]:
    """Rows for `season`, hard-filtered to `week < before_week`.

    THE FILTER STILL LIVES HERE, at the point rows enter the pipeline, and that
    is deliberate. Aggregating first and filtering later is how same-game rows
    creep back in during a refactor. Caching changed WHERE THE BYTES COME FROM,
    never which rows are eligible: the cache holds the whole season and the week
    filter is applied on every read out of it, so a target-week row still never
    reaches the aggregator. `test_target_week_rows_are_never_read` covers this
    path unchanged.
    """
    rows = _all_rows(season, pbp_dir)
    if before_week is None:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        wk = _f(row.get("week"))
        if wk is None or int(wk) >= int(before_week):
            continue
        out.append(row)
    return out


def _aggregate(rows: Iterable[dict[str, Any]], source: str) -> dict[str, TeamForm]:
    off: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    dfn: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    games: dict[str, set[str]] = defaultdict(set)
    rz_att: dict[str, int] = defaultdict(int)
    rz_td: dict[str, int] = defaultdict(int)

    for row in rows:
        pos = str(row.get("posteam") or "").strip().upper()
        def_ = str(row.get("defteam") or "").strip().upper()
        epa = _f(row.get("epa"))
        if not pos or epa is None:
            continue
        gid = str(row.get("game_id") or "")
        if gid:
            games[pos].add(gid)

        off[pos]["epa"].append(epa)
        succ = _f(row.get("success"))
        if succ is not None:
            off[pos]["success"].append(succ)
        is_pass = _f(row.get("pass"))
        if is_pass is not None:
            off[pos]["pass"].append(is_pass)
        poe = _f(row.get("pass_oe"))
        if poe is not None:
            off[pos]["pass_oe"].append(poe)
        yards = _f(row.get("yards_gained"))
        if yards is not None:
            # Explosive: the conventional 20+ pass / 10+ rush split, not a
            # single threshold — a 12-yard run and a 12-yard completion are not
            # the same event.
            thresh = 20.0 if (is_pass or 0.0) >= 1.0 else 10.0
            off[pos]["explosive"].append(1.0 if yards >= thresh else 0.0)

        y100 = _f(row.get("yardline_100"))
        if y100 is not None and y100 <= 20.0 and str(row.get("play_type") or "") in ("pass", "run"):
            rz_att[pos] += 1
            if (_f(row.get("touchdown")) or 0.0) >= 1.0:
                rz_td[pos] += 1

        if def_:
            dfn[def_]["epa"].append(epa)
            if succ is not None:
                dfn[def_]["success"].append(succ)

    def mean(xs: list[float]) -> float | None:
        return (sum(xs) / len(xs)) if xs else None

    teams = set(off) | set(dfn)
    out: dict[str, TeamForm] = {}
    for team in sorted(teams):
        o, d = off.get(team, {}), dfn.get(team, {})
        plays = len(o.get("epa", []))
        out[team] = TeamForm(
            team=team,
            plays=plays,
            games=len(games.get(team, set())),
            source=source,
            offensive_epa=mean(o.get("epa", [])),
            success_rate=mean(o.get("success", [])),
            pass_rate=mean(o.get("pass", [])),
            # pass_oe is already a percentage-over-expected in nflverse; /100
            # to match the 0-1 scale the engine's other rate terms use.
            pass_rate_over_expectation=(lambda v: v / 100.0 if v is not None else None)(mean(o.get("pass_oe", []))),
            explosive_play_rate=mean(o.get("explosive", [])),
            red_zone_efficiency=(rz_td[team] / rz_att[team]) if rz_att.get(team) else None,
            defensive_epa=mean(d.get("epa", [])),
            success_rate_allowed=mean(d.get("success", [])),
            pace_seconds_per_play=None,  # see build_payload: needs drive timing, not per-play
        )
    return out


def team_form_asof(
    season: int,
    week: int,
    *,
    pbp_dir: Path | None = None,
    allow_prior_season: bool = True,
) -> dict[str, TeamForm]:
    """Form for every team as of BEFORE `week` of `season`.

    Falls back to the prior season's FULL form when in-season history is too
    thin (week 1, and early weeks where a team has < MIN_PLAYS_FOR_FORM). The
    fallback is per-team, not whole-index: by week 3 some teams have enough
    in-season history and some do not, and forcing one choice on all of them
    would either discard real data or over-trust two games of it.
    """
    current = _aggregate(_read_rows(season, before_week=week, pbp_dir=pbp_dir),
                         source="season_%d_through_wk%d" % (season, week - 1))
    if not allow_prior_season:
        return current

    thin = [t for t, f in current.items() if not f.is_fed]
    if not thin and current:
        return current

    prior = _aggregate(_read_rows(season - 1, before_week=None, pbp_dir=pbp_dir),
                       source="season_%d_full_prior_fallback" % (season - 1))
    merged = dict(current)
    for team, form in prior.items():
        if team not in merged or not merged[team].is_fed:
            merged[team] = form
    return merged


def build_payload(
    home_team: str,
    away_team: str,
    *,
    season: int,
    week: int,
    forms: dict[str, TeamForm] | None = None,
    pbp_dir: Path | None = None,
) -> dict[str, Any]:
    """A `feature_generation_payload` for smartsim2, from PRIOR form only.

    Keys are the ones `drive_priors._extract_block` / `_first_float` actually
    read, taken from that module's own call sites — not invented here. A term
    whose form is missing is OMITTED rather than zero-filled, so the engine's
    existing neutral default applies and an unfed input stays distinguishable
    from a genuinely average one.
    """
    forms = forms if forms is not None else team_form_asof(season, week, pbp_dir=pbp_dir)
    h = forms.get(str(home_team).upper())
    a = forms.get(str(away_team).upper())
    if h is None or a is None or not h.is_fed or not a.is_fed:
        return {}

    def put(d: dict[str, Any], key: str, value: float | None) -> None:
        if value is not None:
            d[key] = value

    offensive: dict[str, Any] = {}
    put(offensive, "offensive_epa", h.offensive_epa)
    put(offensive, "home_offensive_epa", h.offensive_epa)
    put(offensive, "away_offensive_epa", a.offensive_epa)
    put(offensive, "success_rate", h.success_rate)
    put(offensive, "home_success_rate", h.success_rate)
    put(offensive, "away_success_rate", a.success_rate)
    put(offensive, "red_zone_efficiency", h.red_zone_efficiency)
    put(offensive, "explosive_play_rate", h.explosive_play_rate)
    put(offensive, "pass_rate_over_expectation", h.pass_rate_over_expectation)
    put(offensive, "home_pass_rate", h.pass_rate)
    put(offensive, "away_pass_rate", a.pass_rate)

    defensive: dict[str, Any] = {}
    put(defensive, "defensive_epa", h.defensive_epa)
    put(defensive, "home_defensive_epa", h.defensive_epa)
    put(defensive, "away_defensive_epa", a.defensive_epa)
    put(defensive, "success_rate_allowed", h.success_rate_allowed)
    put(defensive, "home_success_rate_allowed", h.success_rate_allowed)
    put(defensive, "away_success_rate_allowed", a.success_rate_allowed)

    advanced: dict[str, Any] = {}
    put(advanced, "home_offensive_epa", h.offensive_epa)
    put(advanced, "away_offensive_epa", a.offensive_epa)
    put(advanced, "home_defensive_epa", h.defensive_epa)
    put(advanced, "away_defensive_epa", a.defensive_epa)
    # `def_pressure_avg` is deliberately ABSENT: nflverse pbp carries `sack` but
    # not a pressure rate, and deriving "pressure" from sacks alone would be a
    # different statistic wearing the same name. Left unfed and documented.

    payload: dict[str, Any] = {
        "offensive_metrics": offensive,
        "defensive_metrics": defensive,
        "advanced_metrics": advanced,
        "asof": {
            "season": season,
            "before_week": week,
            "home_source": h.source,
            "away_source": a.source,
            "home_plays": h.plays,
            "away_plays": a.plays,
        },
    }
    return payload


def assert_no_leakage(
    season: int,
    *,
    pbp_dir: Path | None = None,
    ceiling: float = LEAKAGE_CEILING_R,
) -> float:
    """Re-derive the leakage correlation and raise if it clears `ceiling`.

    This is the check that would have caught the original defect, so it lives in
    the module rather than in a test that a refactor might not run. Returns the
    measured r so a caller can report it rather than merely trusting a pass.
    """
    import statistics

    path = _pbp_path(season, pbp_dir)
    if not path.is_file():
        raise FileNotFoundError(path)

    finals: dict[str, tuple[str, str, float, float, int]] = {}
    with path.open("r", encoding="utf-8", errors="ignore", newline="") as fh:
        for row in csv.DictReader(fh):
            gid = row.get("game_id")
            hs, aws, wk = _f(row.get("home_score")), _f(row.get("away_score")), _f(row.get("week"))
            if gid and hs is not None and aws is not None and wk is not None:
                finals[gid] = (str(row.get("home_team") or "").upper(),
                               str(row.get("away_team") or "").upper(), hs, aws, int(wk))

    by_week: dict[int, dict[str, TeamForm]] = {}
    xs: list[float] = []
    ys: list[float] = []
    for home, away, hs, aws, wk in finals.values():
        if wk < 2:
            continue  # week 1 has no in-season prior form; excluded by design
        if wk not in by_week:
            by_week[wk] = team_form_asof(season, wk, pbp_dir=pbp_dir, allow_prior_season=False)
        forms = by_week[wk]
        h, a = forms.get(home), forms.get(away)
        if not h or not a or not h.is_fed or not a.is_fed:
            continue
        xs.append((h.offensive_epa or 0.0) - (a.offensive_epa or 0.0))
        ys.append(hs - aws)

    if len(xs) < 30:
        raise RuntimeError("only %d comparable games — too few to certify" % len(xs))

    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / len(xs)
    r = cov / (statistics.pstdev(xs) * statistics.pstdev(ys))
    if abs(r) > ceiling:
        raise AssertionError(
            "LEAKAGE: as-of EPA differential correlates r=%.3f with the final margin "
            "over %d games (ceiling %.2f). Same-game rows are reaching the aggregator."
            % (r, len(xs), ceiling)
        )
    return r
