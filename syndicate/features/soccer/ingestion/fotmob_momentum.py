"""FotMob's own per-minute momentum series, normalised to the card's shape.

THIS REPLACES THE ESPN-COMMENTARY PROXY AS THE PRODUCTION SIGNAL, per the
2026-08-22 deep dive (`docs/ai_context/todo.md` #518): FotMob's series carries
real, calibrated, direction-predictive signal (dAUC +0.071 on "next team to
score", holdout, 5,552 matches); the ESPN event-weighted proxy in
`features/momentum.py` was swept across every half-life and carries none. That
proxy is NOT reused as a fallback here -- showing a confident-looking chart
built on a disproven signal is worse than showing nothing, and the card
already treats `supported: False` as "hide the panel", not "hide and lie".

THE 0-100 SCALE, and why the card's strength bands use it directly. FotMob's
series is bounded (empirically ~-100..100), unlike the ESPN proxy's unbounded
weighted sum. The deep dive measured goal-rate lift BY BAND on this exact
scale: <40 no lift (0.93-0.99x), 60-80 = 1.19x, 80+ = 1.23x. `_momentum_chart`
in `cards.py` must read `current` on THIS scale, not the old ESPN-proxy scale
its label thresholds were tuned to informally.
"""

from __future__ import annotations

from typing import Any

from syndicate.features.soccer.ingestion.fotmob_match_id import resolve_fotmob_match_id
from syndicate.features.soccer.ingestion.fotmob_shots import _get


def _fetch_momentum_series(match_id: int, _fetch: Any = None) -> list[dict[str, float]]:
    """[{t: seconds, value: signed float}] from FotMob's matchDetails payload.

    Mirrors the normalisation in `fotmob_shots.shots_for_match` exactly (same
    `content.momentum.main.data` path, same minute->seconds conversion) so the
    two never drift into reading the series two different ways.
    """
    fetch = _fetch or _get
    payload = fetch(f"https://www.fotmob.com/api/data/matchDetails?matchId={match_id}")
    content = payload.get("content") or {}
    main = ((content.get("momentum") or {}).get("main") or {}) if isinstance(content.get("momentum"), dict) else {}
    out: list[dict[str, float]] = []
    for point in (main.get("data") or []):
        if not isinstance(point, dict):
            continue
        try:
            out.append({"t": float(point["minute"]) * 60.0, "value": float(point["value"])})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def fotmob_momentum_block(
    *, league: str, home_team: str, away_team: str, iso_date: str,
    as_of_seconds: float | None,
    _resolve: Any = None, _fetch: Any = None,
) -> dict[str, Any]:
    """Same return shape as the retired ESPN `_momentum_block`:
    {supported, current, series, events, as_of_seconds} on success, or
    {supported: False, reason} when the match cannot be resolved or fetched.

    NEVER FATAL. A join miss or a transient FotMob failure is a stated reason,
    not an exception raised into the poll loop -- one match's momentum must
    never take down a whole league's live tick.
    """
    try:
        resolve = _resolve or resolve_fotmob_match_id
        match_id = resolve(league=league, home_team=home_team, away_team=away_team, iso_date=iso_date)
        if match_id is None:
            return {"supported": False, "reason": "fotmob match id unresolved",
                    "current": None, "series": []}
        series_raw = _fetch_momentum_series(match_id, _fetch=_fetch)
        if not series_raw:
            return {"supported": False, "reason": "fotmob momentum series empty",
                    "current": None, "series": []}
        clock = float(as_of_seconds) if as_of_seconds is not None else float(series_raw[-1]["t"])
        usable = [p for p in series_raw if p["t"] <= clock]
        if not usable:
            return {"supported": True, "reason": "no fotmob momentum samples yet",
                    "current": 0.0, "series": []}
        return {
            "supported": True,
            "current": float(usable[-1]["value"]),
            "events": len(usable),
            "as_of_seconds": clock,
            "series": [{"t": int(p["t"]), "v": p["value"]} for p in usable],
            "source": "fotmob",
            "fotmob_match_id": match_id,
        }
    except Exception as exc:  # pragma: no cover - defensive, never fatal
        return {"supported": False, "reason": f"{type(exc).__name__}: {exc}",
                "current": None, "series": []}


__all__ = ["fotmob_momentum_block"]
