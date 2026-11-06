"""College basketball PREGAME sim, straight to the boards (lane wncaab-module, Phase 3; user 2026-11-02).

NCAAB had no pregame projection: every Layer 1 / Layer 2 game row read "no projection source wired for
ncaab". The live tier's engine, started at the opening tip, IS the pregame sim:

- `GameState()` takes exactly the pregame code path, seed for seed (`basketball_engine/resume.py`).
- The inputs are the live tier's: `ncaab/live_resim.build_engine_inputs` (team prior + player priors, both
  dated strictly before the game). Nothing is defaulted; a game without them is REFUSED by name.
- The team prior carries the league's daily PRIOR CALIBRATION (`college_basketball/prior_calibration.py`,
  2026-11-03): its stamp is in each entry's provenance and in the inputs key, so a new fit re-sims the game.
- The switches are the live tier's too. The producer runs as a child of the live-odds-worker
  (`ncaab/inplay_lane.maybe_launch_pregame_sims`), so it inherits SYNDICATE_NCAAB_HALF_SPLIT /
  EXACT_TARGET / LIVE_MECHANISMS. The P4 backtest's settled configuration cut the engine's tip total
  overshoot from +6.4 to +1.1 (regular season, `docs/ai_context/ncaab_live_tier.md`); without it the
  board would carry totals 6-10 points high. Each entry records the switches it ran under.

Artifact: `<data_root>/<league>_source/data/pregame_sim/pregame_sim_<date>.json`, one entry per slate
game keyed by ESPN event id, with score histograms per segment (`dist.segments.full|h1|h2`: `total`
and `margin`, home minus away in the SLATE's orientation, which for a neutral-site game is the odds
feed's -- `ncaab/slate.orient_neutral_site_games`). `shared/college_game_projections.py` prices board
rows off them.

COST, measured 2026-11-02 on the fleet at nice 19: ~5.5-6 s per game for 100 sims, so a 120-game slate
is ~22 CPU-minutes at 200. Each run therefore stops at its DEADLINE and writes what it has; a game is
re-simmed only when its inputs key changes (ratings / player-prior dates, switches, sims, the sim's own code --
`SIM_CODE_MODULES`). The next
launch continues where this one stopped.

WNCAAB (user 2026-11-02 "Approve the loans"): the same engine under `basketball_engine.league.WNCAAB` (four
quarters), fed by the women's tables (`build_ncaab_team_ratings.py` / `build_ncaab_player_priors.py --league
wncaab`). No men-fitted adjustment is applied to the women (half split, live mechanisms); segments are
q1..q4 plus h1 = q1+q2 and h2 = q3+q4. A game without women's ratings or priors refuses by name.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

SCHEMA = "college_pregame_sim_v1"
DEFAULT_SIMS = 200

# THE SIM'S OWN CODE IS AN INPUT (lane wncaab-module, 2026-11-06). `inputs_key` held only data and switches, so an
# engine fix never reached a game already simmed: `b9999dc1d` (the full game counts overtime) went live on the fleet
# 2026-11-05 22:36Z, and the 23:08:47Z run found all 181 of the 11-05 / 11-06 games `unchanged` -- they kept
# publishing regulation ties, 1.5-1.6% of draws. These are the modules the sim executes, from the inputs it is
# handed to the histograms it writes; a change to any of them re-sims each game once (~11 s a game at 200 sims,
# spread across runs by the deadline). A module renamed out of this list is caught by its test, not by a re-sim.
SIM_CODE_MODULES = (
    "syndicate.features.ncaab.live_resim",
    "syndicate.features.ncaab.live_team_model",
    "syndicate.features.basketball_engine.engine",
    "syndicate.features.basketball_engine.resume",
    "syndicate.features.basketball_engine.league",
    "syndicate.features.basketball_engine.league_engine",
    "syndicate.features.shared.basketball_league_rules",
    "syndicate.features.college_basketball.league",
    "syndicate.features.college_basketball.pregame_sim",
)


@lru_cache(maxsize=1)
def sim_code_fingerprint() -> str:
    """sha256 over the source of `SIM_CODE_MODULES`, read from disk. Cached for the process: the producer is a
    child launched per run, so a fast-forward reaches the next run with no restart."""
    digest = hashlib.sha256()
    for name in SIM_CODE_MODULES:
        spec = importlib.util.find_spec(name)
        origin = getattr(spec, "origin", None)
        digest.update(name.encode("utf-8") + b"\0")
        # CRLF folded: the same commit hashes alike on a Windows checkout and on the fleet.
        digest.update(Path(origin).read_bytes().replace(b"\r\n", b"\n") if origin else b"missing")
    return digest.hexdigest()[:12]


def default_sims() -> int:
    raw = str(os.environ.get("SYNDICATE_COLLEGE_PREGAME_SIMS") or "").strip()
    try:
        return max(100, int(raw)) if raw else DEFAULT_SIMS
    except ValueError:
        return DEFAULT_SIMS


def artifact_path(date_iso: str, league: str = "ncaab") -> Path:
    from syndicate.features.shared.refresh_state_store import data_root

    return Path(data_root()) / f"{league}_source" / "data" / "pregame_sim" / f"pregame_sim_{date_iso}.json"


def read_pregame_sims(date_iso: str, league: str = "ncaab") -> dict[str, Any] | None:
    path = artifact_path(date_iso, league)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _start(game: Mapping[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(game.get("start_time_utc") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def is_pregame(game: Mapping[str, Any], now: datetime) -> bool:
    live = game.get("live_state") if isinstance(game.get("live_state"), Mapping) else {}
    if live.get("in_progress") or live.get("final"):
        return False
    start = _start(game)
    return start is None or start > now


def _side(game: Mapping[str, Any], side: str, league: str) -> dict[str, Any]:
    from syndicate.features.shared.team_aliases import chip_join_key

    team = game.get(side) if isinstance(game.get(side), Mapping) else {}
    name = str(team.get("name") or "")
    return {"espn_id": str(team.get("espn_id") or ""), "abbr": team.get("abbr"), "name": name,
            "key": chip_join_key(league, name) or name.lower()}


def inputs_key(provenance: Mapping[str, Any], sims: int) -> str:
    """What makes two runs of the same game the same run. A change re-sims the game."""
    keep = {k: provenance.get(k) for k in ("ratingsAsOf", "playerPriorsAsOf", "priorSeasonFallback", "halfSplit", "mechanisms",
                                           "league", "pregameTotal", "pregameHomeMargin", "priorCalibration", "effMultBounds")}
    # The prior's own targets are in the key: a change to HOW the prior is built (2026-11-02, no second shrink on a
    # calibrated table) moves them with no change of table date, and must re-sim the game.
    keep["exactTarget"] = provenance.get("exactTarget")
    keep["sims"] = int(sims)
    keep["simCode"] = sim_code_fingerprint()
    return json.dumps(keep, sort_keys=True)


def _segments(result: Mapping[str, Any]) -> dict[str, Any]:
    segments = {"full": {"total": result["total_dist"], "margin": result["margin_dist"]}}
    for name, block in (result.get("segments") or {}).items():
        segments[name] = {"total": block["total_dist"], "margin": block["margin_dist"]}
    return segments


LEAGUES = ("ncaab", "wncaab")


def _engine_inputs(league: str, date_iso: str, game: Mapping[str, Any], home: Mapping[str, Any], away: Mapping[str, Any], priors: Any):
    from syndicate.features.ncaab import live_resim as lr

    inputs = lr.build_engine_inputs(date_iso, home["espn_id"], away["espn_id"], neutral=bool(game.get("neutral_site")),
                                    home_code=str(home.get("abbr") or ""), away_code=str(away.get("abbr") or ""), priors=priors,
                                    league=league)
    if isinstance(inputs, lr.NcaabResimRefusal):
        return None, inputs.reason, inputs.detail
    inputs["_provenance"]["exactTarget"] = lr.exact_target_enabled()
    return inputs, None, None


def run_pregame_sims(
    date_iso: str,
    league: str = "ncaab",
    *,
    sims: Optional[int] = None,
    deadline: Optional[float] = None,
    now: Optional[datetime] = None,
    clock: Callable[[], float] = time.monotonic,
    simulate: Optional[Callable[..., Any]] = None,
) -> dict[str, Any]:
    """Sim every pregame slate game of `date_iso` whose inputs changed; write after each game. Never raises
    on one game: a failure is that game's named refusal."""
    from syndicate.features.ncaab.slate import read_slate

    sims = int(sims or default_sims())
    moment = now or datetime.now(timezone.utc)
    path = artifact_path(date_iso, league)
    previous = (read_pregame_sims(date_iso, league) or {}).get("games") or {}
    games: dict[str, Any] = dict(previous)
    counts = {"pregame": 0, "simmed": 0, "unchanged": 0, "refused": 0, "not_reached": 0}
    priors = None
    if league in LEAGUES:
        from syndicate.features.ncaab import live_resim as lr

        priors = lr.load_player_priors(datetime.fromisoformat(date_iso).date(),
                                       dirs=None if league == "ncaab" else lr._processed_dirs(league))
    started = clock()

    def publish() -> None:
        _write(path, {"schema": SCHEMA, "league": league, "date": date_iso, "generated_at": _utc_now_iso(),
                      "sims": sims, "games": games})

    for game in (read_slate(date_iso, league) or {}).get("games") or []:
        event_id = str(game.get("event_id") or "")
        if not event_id or not is_pregame(game, moment):
            continue
        counts["pregame"] += 1
        if deadline is not None and clock() >= deadline:
            counts["not_reached"] += 1
            continue
        home, away = _side(game, "home", league), _side(game, "away", league)
        base = {"event_id": event_id, "start_time_utc": game.get("start_time_utc"), "neutral_site": bool(game.get("neutral_site")),
                "home": home, "away": away, "computed_at": _utc_now_iso()}
        if league not in LEAGUES:
            games[event_id] = {**base, "refused": "no_engine_inputs_for_league", "detail": league}
            counts["refused"] += 1
            continue
        try:
            from syndicate.features.basketball_engine.resume import GameState
            from syndicate.features.ncaab import live_resim as lr

            if isinstance(priors, lr.NcaabResimRefusal):
                games[event_id] = {**base, "refused": priors.reason, "detail": priors.detail}
                counts["refused"] += 1
                continue
            inputs, reason, detail = _engine_inputs(league, date_iso, game, home, away, priors)
            if inputs is None:
                games[event_id] = {**base, "refused": reason, "detail": detail}
                counts["refused"] += 1
                continue
            key = inputs_key(inputs["_provenance"], sims)
            prior = previous.get(event_id) or {}
            if prior.get("inputs_key") == key and prior.get("dist"):
                counts["unchanged"] += 1
                continue
            result = lr.resim_live_game(inputs, GameState(), sims=sims, base_seed=lr.stable_seed(event_id, 0),
                                        deadline=deadline, simulate=simulate, clock=clock, league=league)
            if isinstance(result, lr.NcaabResimRefusal):
                if result.reason == "budget_exhausted":
                    counts["not_reached"] += 1
                    continue
                games[event_id] = {**base, "refused": result.reason, "detail": result.detail}
                counts["refused"] += 1
                continue
        except Exception as exc:  # noqa: BLE001 -- one game's failure is that game's refusal
            games[event_id] = {**base, "refused": "engine_error", "detail": f"{type(exc).__name__}: {exc}"[:200]}
            counts["refused"] += 1
            continue
        games[event_id] = {
            **base,
            "inputs_key": key,
            "sims_run": result["sims_run"],
            "home_win_prob": round(float(result["home_win_prob"]), 4),
            "total_mean": round(float(result["total_mean"]), 2),
            "home_margin_mean": round(float(result["home_margin_mean"]), 2),
            "dist": {"segments": _segments(result)},
            "provenance": inputs["_provenance"],
        }
        counts["simmed"] += 1
        publish()
    if counts["refused"]:
        publish()  # a simmed game already published; a refusal is written once, at the end
    summary = {"league": league, "date": date_iso, "sims": sims, **counts,
               "published": sum(1 for g in games.values() if g.get("dist")), "elapsed_s": round(clock() - started, 1)}
    print(f"[college_pregame_sim] RUN league={league} date={date_iso} sims={sims} pregame={counts['pregame']} "
          f"simmed={counts['simmed']} unchanged={counts['unchanged']} refused={counts['refused']} "
          f"not_reached={counts['not_reached']} published={summary['published']} elapsed_s={summary['elapsed_s']} "
          f"sim_code={sim_code_fingerprint()}", flush=True)
    return summary
