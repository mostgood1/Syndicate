# -*- coding: utf-8 -*-
"""Live remaining corners from the PRE-KICKOFF estimate and the clock, instead of the possession sim.

WHY. Measured offline on 320 held-out current-season matches at 30/45/60/75 minutes (H29, lane
`soccer-live-model-study`, `.syndicate/log/2026-09-17.md` ~13:55 CT): `project_live_match`'s remaining
corners carry a MAE of 1.951 and over-predict by +0.46, while the pregame estimator total spread over the
share of the match still to play carries 1.876 and +0.07 (paired -0.0742 [-0.1235, -0.0235]). The same
registration FALSIFIED the arm that also updates on the corners observed so far: it added nothing
(+0.0028), so this module deliberately does NOT read the running corner rate -- only the pregame number
and the clock.

This is the live-side echo of the pregame finding (H26): the possession sim's corners are near
zero-information, so `features/corners_estimator.py` replaced them before kickoff. The sim's own values
are KEPT beside the published ones here too, under `sim_*`, so a forward grade can score both arms from
the same artifact.

S(t) IS FIT ON TRAIN ONLY (matches before 2026-08-22, 133 of them), as the mean per-match share of a
match's corners still to come at each five-minute mark. It is a table plus linear interpolation rather
than a curve: a fitted `(1 - t/90)^0.83` had an RMSE of 0.020 against these points and was worst exactly
where the number matters least (85'), so the table is simpler and closer.

NOT GRADED ON PRODUCTION YET. H32 (registration in the same log) grades it forward against the kept `sim_`
values on live matches. Until then this is a measured offline improvement, not a verified live one.
"""
from __future__ import annotations

import dataclasses
import json
import os
from typing import Any, Mapping

LIVE_CORNERS_BASIS = "prekickoff_pace_v1"
PREGAME_BASIS = "team_rates_pressure_v1"
_ENV_FLAG = "SYNDICATE_SOCCER_LIVE_CORNERS_ESTIMATOR"
_HALF_SECONDS = 45.0 * 60.0

# (match minute, share of the match's corners still to come). TRAIN fit, 133 matches; see the module
# docstring. 0 and 90+ are the endpoints the table is clamped to.
SHARE_TABLE: tuple[tuple[float, float], ...] = (
    (0.0, 1.000), (5.0, 0.958), (10.0, 0.910), (15.0, 0.867), (20.0, 0.818), (25.0, 0.780),
    (30.0, 0.742), (35.0, 0.686), (40.0, 0.638), (45.0, 0.539), (50.0, 0.489), (55.0, 0.425),
    (60.0, 0.373), (65.0, 0.323), (70.0, 0.281), (75.0, 0.232), (80.0, 0.182), (85.0, 0.130),
    (90.0, 0.004),
)


def live_corners_enabled() -> bool:
    """Default ON, as the pregame estimator ships. `off`, `0`, `false` or `no` disables it."""
    raw = str(os.environ.get(_ENV_FLAG) or "").strip().lower()
    return raw not in {"off", "0", "false", "no"}


def elapsed_seconds(live_state: Mapping[str, Any]) -> float:
    """Match seconds played, from the live state's own half and remaining clock."""
    half = int(live_state.get("half") or 1)
    remaining = float(live_state.get("clock_remaining") or 0.0)
    return max(0.0, (half - 1) * _HALF_SECONDS + (_HALF_SECONDS - remaining))


def share_remaining(seconds: float) -> float:
    """S(t) by linear interpolation between the fitted points, clamped to [0, 1]."""
    minute = max(0.0, float(seconds)) / 60.0
    if minute <= SHARE_TABLE[0][0]:
        return SHARE_TABLE[0][1]
    if minute >= SHARE_TABLE[-1][0]:
        return SHARE_TABLE[-1][1]
    for (m0, s0), (m1, s1) in zip(SHARE_TABLE, SHARE_TABLE[1:]):
        if minute <= m1:
            span = m1 - m0
            return s0 + (s1 - s0) * ((minute - m0) / span if span else 0.0)
    return SHARE_TABLE[-1][1]


def pregame_corners_from_payload(payload: Mapping[str, Any], match_id: str) -> tuple[float, float] | None:
    """The match's pregame estimator corners from a recommendations or pre-kickoff freeze payload.

    Returns None unless the entry names the pregame estimator (`corners_basis`): a possession-sim number
    is exactly what this module exists to stop publishing, so falling back to it would be silent.
    """
    entries: list[Mapping[str, Any]] = []
    matches = payload.get("matches")
    if isinstance(matches, dict):                      # pre-kickoff freeze: {match_id: {match: {...}}}
        entry = matches.get(str(match_id))
        if isinstance(entry, Mapping):
            inner = entry.get("match")
            entries.append(inner if isinstance(inner, Mapping) else entry)
    elif isinstance(matches, list):                    # recommendations artifact
        entries = [m for m in matches if isinstance(m, Mapping) and str(m.get("match_id")) == str(match_id)]
    for match in entries:
        volume = match.get("volume_projection") or {}
        if str(volume.get("corners_basis") or "") != PREGAME_BASIS:
            continue
        home, away = volume.get("home_corners"), volume.get("away_corners")
        if home is None or away is None:
            continue
        try:
            return float(home), float(away)
        except (TypeError, ValueError):
            return None
    return None


def load_pregame_payload(data_root: Any, league: str, iso_date: str) -> dict[str, Any]:
    """The league-date's pregame numbers, preferring the PRE-KICKOFF FREEZE over the live artifact.

    The freeze holds the last build made before each kickoff; `recommendations_<date>.json` is rewritten as
    matches go pre -> in -> post, so after kickoff it no longer carries a pregame number for that match.
    This keeps the caller's patch to one line and the read off the request path (the poller is a worker).
    Returns {} rather than raising: a live tick must never fail on a missing artifact.
    """
    from pathlib import Path

    directory = Path(data_root) / str(league) / "api" / "recommendations"
    candidates = sorted(directory.glob(f"recommendations_prekickoff_{iso_date}.*.json"))
    candidates.append(directory / f"recommendations_{iso_date}.json")
    merged: dict[str, Any] = {}
    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- missing or half-written: the next candidate answers
            continue
        if not isinstance(payload, dict):
            continue
        if not merged:
            merged = payload
            continue
        # More than one service froze this date: merge their entries, keeping the later `frozen_at`.
        existing, incoming = merged.get("matches"), payload.get("matches")
        if isinstance(existing, dict) and isinstance(incoming, dict):
            for match_id, entry in incoming.items():
                held = existing.get(match_id)
                if not isinstance(held, Mapping) or str(entry.get("frozen_at") or "") > str(held.get("frozen_at") or ""):
                    existing[match_id] = entry
    return merged


def apply_live_corners(projection: Any, live_state: Mapping[str, Any],
                       pregame: tuple[float, float] | None) -> tuple[Any, dict[str, Any]]:
    """`(projection, audit)`: the projection's corners replaced by `so far + pregame total x S(t)`, with the
    sim's own values kept on the returned copy.

    `LiveMatchProjection` is frozen, so this returns a REPLACED projection rather than mutating one -- the
    caller must use the returned object. An audit `state` other than `applied` means the projection came
    back untouched, and says why, so a refusal in production is never silent.
    """
    audit: dict[str, Any] = {"basis": LIVE_CORNERS_BASIS}
    if not live_corners_enabled():
        audit["state"] = "disabled"
        return projection, audit
    if pregame is None:
        audit["state"] = "no_pregame_estimate"
        return projection, audit
    pregame_home, pregame_away = pregame
    total_pregame = pregame_home + pregame_away
    if total_pregame <= 0:
        audit["state"] = "pregame_total_not_positive"
        return projection, audit

    home_so_far = float(int(live_state.get("home_corners_so_far") or 0))
    away_so_far = float(int(live_state.get("away_corners_so_far") or 0))
    seconds = elapsed_seconds(live_state)
    share = share_remaining(seconds)
    remaining = total_pregame * share
    home_split = pregame_home / total_pregame            # the pregame split; the study graded the TOTAL only

    home_corners = round(home_so_far + remaining * home_split, 4)
    away_corners = round(away_so_far + remaining * (1.0 - home_split), 4)
    updated = dataclasses.replace(
        projection,
        projected_home_corners=home_corners,
        projected_away_corners=away_corners,
        projected_total_corners=round(home_corners + away_corners, 4),
        sim_projected_home_corners=projection.projected_home_corners,
        sim_projected_away_corners=projection.projected_away_corners,
        sim_projected_total_corners=projection.projected_total_corners,
        corners_basis=LIVE_CORNERS_BASIS,
    )
    audit.update({
        "state": "applied",
        "elapsed_seconds": round(seconds, 1),
        "share_remaining": round(share, 4),
        "pregame_total": round(total_pregame, 4),
        "remaining": round(remaining, 4),
        "so_far": home_so_far + away_so_far,
        "sim_total": updated.sim_projected_total_corners,
        "published_total": updated.projected_total_corners,
    })
    return updated, audit
