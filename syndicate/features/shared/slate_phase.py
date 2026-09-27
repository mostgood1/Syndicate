"""Per-sport SLATE PHASE: pregame -> starting_soon -> live.

WHY THIS EXISTS (lane `slate-starting-soon-phase`, 2026-09-27). The refresh loop
had exactly two modes, and the switch between them was GLOBAL: `effective_phase`
flips to "live" the moment ANY tracked sport has a game in play
(`live_refresh_loop._run_live_refresh_tick`). Nothing represented the window
that matters most for a bettor -- the last few hours before a sport's first
start, when injury news lands and lines move on it.

The fixture-aware tier ladder (`_FIXTURE_TIER_SECONDS`) does name that window
("< 3h: the T-75/T-10 ramp owns it"), but the hand-off went nowhere for five of
eight sports: T-75/T-10 providers exist only for mlb/wnba/soccer
(`_T_WINDOW_COMMENCE_PROVIDERS`), so `_fixture_aware_interval_seconds` returned
None and the caller fell back to the flat 2h baseline -- i.e. NFL, NCAAF, NBA,
NHL and NCAAB swept LESS often inside T-3h than the ladder intended. Reading
that motivated this: 2026-09-27 ~10:45 CT, NFL 75 minutes before its 12:00
kickoffs with stale odds, and NFL injuries on a fixed 6h timer.

WHAT THIS MODULE IS. Pure decisions plus small caches -- no subprocess, no
launch. The refresh loop and the refresh worker ask it:

  * which phase a sport is in (`current_phase`, `classify`);
  * how often a starting-soon sport must sweep (`apply_starting_soon_interval`),
    which can only ever SHORTEN an interval, never lengthen one -- so this
    composes safely with every existing override;
  * when a sport's injury/news poll is due (`starting_soon_poll_interval`);
  * whether an injury file changed (`injury_file_changed`).

DEFAULT OFF (`SYNDICATE_SLATE_STARTING_SOON_ENABLED`), the house convention for
cadence changes. OBSERVATION HAS ITS OWN FLAG (`SYNDICATE_SLATE_PHASE_OBSERVE`,
also default off): it computes and prints the phase (`SLATE_PHASE`) and changes
no cadence, so the transitions can be read on production before anything acts
on them. It is a separate flag because observing costs subprocesses -- caught by
the tick tests, which began spawning real schedule fetches when it was ungated.
"""

from __future__ import annotations

import hashlib
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

PHASE_PREGAME = "pregame"
PHASE_STARTING_SOON = "starting_soon"
PHASE_LIVE = "live"

#: T-3h. The user's stated window is "2-3 hours before games start", and 3h is
#: also the existing tier ladder's imminent boundary, so the two agree on what
#: "imminent" means rather than drifting apart.
DEFAULT_STARTING_SOON_WINDOW_SECONDS = 3 * 3600

#: Sweep at least this often while starting soon. 30 min, not less: a combined
#: pregame sweep was measured at up to ~1h per pass (2026-09-19), and
#: `launch_refresh_run` refuses a second run while one is active, so an interval
#: much shorter than a pass buys contention, not captures. NFL game lines have
#: their own 150 s lane on live-odds-worker; this cadence is what carries PROPS.
DEFAULT_STARTING_SOON_SWEEP_INTERVAL_SECONDS = 30 * 60

#: Relaunch cooldown for a starting-soon sport (the normal one is 1800 s). Still
#: a storm guard -- a sport cannot relaunch faster than this -- but short enough
#: that a T-10 closing sweep is not held off by a sweep 20 minutes earlier.
DEFAULT_STARTING_SOON_RELAUNCH_COOLDOWN_SECONDS = 10 * 60

#: Injury / news polls while starting soon. NFL inactives are published ~90 min
#: before kickoff; a 6h timer can miss them entirely.
DEFAULT_STARTING_SOON_POLL_INTERVAL_SECONDS = 15 * 60

#: Minimum gap between two T-window-forced sweeps of one sport. A 60-game NCAAB
#: Saturday with staggered tips would otherwise force a sweep on nearly every
#: tick; a sweep this recent already covers any window that comes due.
DEFAULT_T_WINDOW_MIN_GAP_SECONDS = 5 * 60

#: A start time already passed but the sport's liveness checker has not flipped
#: yet (ESPN lag, a delayed first pitch). Keep it starting_soon for this long so
#: cadence does not fall back to pregame exactly at kickoff -- the moment the
#: 2026-09-20 reading measured rows going live on a 1,279 s-old pregame quote.
KICKOFF_GRACE_SECONDS = 60 * 60

_LIVE_CACHE_TTL_SECONDS = 90.0


def _env(env: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if env is None else env


def _env_int(name: str, default: int, env: Mapping[str, str] | None = None) -> int:
    raw = str(_env(env).get(name) or "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _sport_env_int(base: str, sport: str, default: int, env: Mapping[str, str] | None = None) -> int:
    """`<BASE>_<SPORT>` wins over `<BASE>`, which wins over the default."""
    sport_key = f"{base}_{str(sport or '').strip().upper()}"
    if str(_env(env).get(sport_key) or "").strip():
        return _env_int(sport_key, default, env)
    return _env_int(base, default, env)


def starting_soon_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Absent means OFF."""
    raw = str(_env(env).get("SYNDICATE_SLATE_STARTING_SOON_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def observe_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Compute and print the phase every tick WITHOUT acting on it.

    Its own flag, and absent means OFF, because observing is not free: the phase
    reads the schedule adapter (subprocess fetches on a cache miss) and the ESPN
    liveness checkers (subprocesses). With both flags absent the tick does exactly
    what it did before this module existed. `SYNDICATE_SLATE_STARTING_SOON_ENABLED`
    implies observing.
    """
    raw = str(_env(env).get("SYNDICATE_SLATE_PHASE_OBSERVE") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"} or starting_soon_enabled(env)


def starting_soon_window_seconds(sport: str, env: Mapping[str, str] | None = None) -> int:
    return _sport_env_int("SYNDICATE_SLATE_STARTING_SOON_WINDOW_SECONDS", sport, DEFAULT_STARTING_SOON_WINDOW_SECONDS, env)


def starting_soon_sweep_interval_seconds(sport: str, env: Mapping[str, str] | None = None) -> int:
    return _sport_env_int(
        "SYNDICATE_SLATE_STARTING_SOON_SWEEP_INTERVAL_SECONDS", sport, DEFAULT_STARTING_SOON_SWEEP_INTERVAL_SECONDS, env
    )


def starting_soon_relaunch_cooldown_seconds(env: Mapping[str, str] | None = None) -> int:
    return _env_int(
        "SYNDICATE_SLATE_STARTING_SOON_RELAUNCH_COOLDOWN_SECONDS", DEFAULT_STARTING_SOON_RELAUNCH_COOLDOWN_SECONDS, env
    )


def t_window_min_gap_seconds(env: Mapping[str, str] | None = None) -> int:
    return _env_int("SYNDICATE_T_WINDOW_MIN_GAP_SECONDS", DEFAULT_T_WINDOW_MIN_GAP_SECONDS, env)


@dataclass(frozen=True)
class SlatePhase:
    sport: str
    phase: str
    #: Seconds until the sport's next start; negative inside the kickoff grace;
    #: None when no fixture was found.
    seconds_to_next: float | None
    reason: str

    def as_meta(self) -> dict[str, Any]:
        out = asdict(self)
        if self.seconds_to_next is not None:
            out["seconds_to_next"] = int(self.seconds_to_next)
        return out


def classify(
    sport: str,
    *,
    now_epoch: float,
    next_fixture_epoch: float | None,
    is_live: bool | None,
    env: Mapping[str, str] | None = None,
) -> SlatePhase:
    """The phase for one sport, from two readings the caller already has.

    `is_live=None` means liveness could not be read. It is NOT treated as live:
    a sport shown "live" while it is not would suppress nothing here, but it
    would mislabel the ops view, and the cadence code already fails open on an
    unreadable checker by sweeping.
    """
    sport = str(sport or "").strip().lower()
    if is_live:
        seconds = None if next_fixture_epoch is None else float(next_fixture_epoch) - float(now_epoch)
        return SlatePhase(sport, PHASE_LIVE, seconds, "game_in_progress")
    if next_fixture_epoch is None:
        return SlatePhase(sport, PHASE_PREGAME, None, "no_fixture_found")
    seconds_out = float(next_fixture_epoch) - float(now_epoch)
    window = starting_soon_window_seconds(sport, env)
    if seconds_out <= 0:
        if -seconds_out <= KICKOFF_GRACE_SECONDS:
            return SlatePhase(sport, PHASE_STARTING_SOON, seconds_out, "start_passed_not_yet_live")
        return SlatePhase(sport, PHASE_PREGAME, seconds_out, "start_passed_stale_fixture")
    if seconds_out <= window:
        return SlatePhase(sport, PHASE_STARTING_SOON, seconds_out, f"within_{int(window)}s")
    return SlatePhase(sport, PHASE_PREGAME, seconds_out, f"beyond_{int(window)}s")


# ---------------------------------------------------------------------------
# Resolution against the live refresh loop's own readings.
#
# The two inputs come from `live_refresh_loop` -- `_next_fixture_epoch` (the
# fixture clock the tier ladder already uses, 15-min cache, covers 7 of 8
# sports through `fetch_schedule_for_date`) and `_LIVE_STATUS_CHECKERS`. Reusing
# them is the point: a third spelling of "when does this sport start" is how
# the cadence code drifted in the first place. Imported lazily because
# live_refresh_loop imports this module.
# ---------------------------------------------------------------------------

_LIVE_CACHE: dict[tuple[str, str], tuple[float, bool | None]] = {}
_LIVE_CACHE_LOCK = threading.Lock()
_LAST_PRINTED: dict[str, str] = {}


def _cached_is_live(sport: str, date_str: str, checker: Callable[[str], bool] | None, now_epoch: float) -> bool | None:
    """The ESPN checkers are subprocesses with a 12 s timeout; cache per sport."""
    if checker is None:
        return None
    key = (sport, date_str)
    with _LIVE_CACHE_LOCK:
        cached = _LIVE_CACHE.get(key)
        if cached is not None and (now_epoch - cached[0]) < _LIVE_CACHE_TTL_SECONDS:
            return cached[1]
    try:
        value: bool | None = bool(checker(date_str))
    except Exception:
        value = None
    with _LIVE_CACHE_LOCK:
        if len(_LIVE_CACHE) > 32:
            _LIVE_CACHE.clear()
        _LIVE_CACHE[key] = (now_epoch, value)
    return value


def _default_readers() -> tuple[Callable[..., float | None], Mapping[str, Callable[[str], bool]]]:
    from syndicate.features.shared import live_refresh_loop as loop

    return loop._next_fixture_epoch, loop._LIVE_STATUS_CHECKERS


def current_phase(
    sport: str,
    *,
    now_epoch: float | None = None,
    date_str: str | None = None,
    next_fixture: Callable[..., float | None] | None = None,
    live_checkers: Mapping[str, Callable[[str], bool]] | None = None,
    env: Mapping[str, str] | None = None,
    need_live: bool = True,
) -> SlatePhase:
    """Resolve one sport's phase. Never raises: an error reads as pregame, named.

    `need_live=False` is for callers that only ask "is this sport starting
    soon?" (the cadence gates). The liveness checkers are ESPN subprocesses, so
    those callers skip them unless a start sits inside the window -- the only
    case where live vs starting_soon changes their answer. An off-season or
    far-off sport then costs no subprocess, and its phase reads `pregame`
    (possibly while live, which such a caller does not act on).
    """
    sport = str(sport or "").strip().lower()
    now = float(now_epoch if now_epoch is not None else time.time())
    try:
        if next_fixture is None or live_checkers is None:
            default_next, default_checkers = _default_readers()
            next_fixture = next_fixture or default_next
            live_checkers = default_checkers if live_checkers is None else live_checkers
        if date_str is None:
            from syndicate.features.shared.timezone import central_today_iso

            date_str = central_today_iso()
        next_epoch = next_fixture(sport, now_epoch=now)
        if not need_live and (
            next_epoch is None or float(next_epoch) - now > starting_soon_window_seconds(sport, env)
        ):
            return classify(sport, now_epoch=now, next_fixture_epoch=next_epoch, is_live=None, env=env)
        is_live = _cached_is_live(sport, date_str, live_checkers.get(sport), now)
        return classify(sport, now_epoch=now, next_fixture_epoch=next_epoch, is_live=is_live, env=env)
    except Exception as exc:  # noqa: BLE001
        return SlatePhase(sport, PHASE_PREGAME, None, f"unresolved:{type(exc).__name__}")


def resolve_phases(sports: Iterable[str], **kwargs: Any) -> dict[str, SlatePhase]:
    out: dict[str, SlatePhase] = {}
    for sport in sports:
        key = str(sport or "").strip().lower()
        if key and key not in out:
            out[key] = current_phase(key, **kwargs)
    return out


def is_starting_soon(sport: str, **kwargs: Any) -> bool:
    """True only when the feature is ON and the sport is in the window."""
    env = kwargs.get("env")
    if not starting_soon_enabled(env):
        return False
    return current_phase(sport, **kwargs).phase == PHASE_STARTING_SOON


def print_transitions(phases: Mapping[str, SlatePhase], *, prefix: str = "[slate_phase]") -> list[str]:
    """One `SLATE_PHASE` line per sport whose phase CHANGED since the last call.

    Printed (not `logger.info`, which never reaches Render's collector) and only
    on change, so the log carries the transitions themselves -- the reading this
    lane is verified on -- without a line per sport per tick.
    """
    lines: list[str] = []
    enabled = starting_soon_enabled()
    for sport, phase in sorted(phases.items()):
        if _LAST_PRINTED.get(sport) == phase.phase:
            continue
        previous = _LAST_PRINTED.get(sport, "unknown")
        _LAST_PRINTED[sport] = phase.phase
        seconds = "none" if phase.seconds_to_next is None else str(int(phase.seconds_to_next))
        line = (
            f"{prefix} SLATE_PHASE sport={sport} from={previous} to={phase.phase} "
            f"seconds_to_next={seconds} reason={phase.reason} acting={'yes' if enabled else 'no_flag_off'}"
        )
        print(line, flush=True)
        lines.append(line)
    return lines


# ---------------------------------------------------------------------------
# Cadence decisions.
# ---------------------------------------------------------------------------


def apply_starting_soon_interval(
    sport: str,
    base_interval: int,
    phase: SlatePhase | None,
    env: Mapping[str, str] | None = None,
) -> tuple[int, str | None]:
    """(interval, reason-if-changed). Can only SHORTEN, never lengthen.

    `base_interval <= 0` means "sweep every tick" to the cadence filter and is
    returned untouched -- starting soon must never slow a sport down, whatever
    an operator set explicitly.
    """
    if not starting_soon_enabled(env) or phase is None or phase.phase != PHASE_STARTING_SOON:
        return base_interval, None
    target = starting_soon_sweep_interval_seconds(sport, env)
    if base_interval <= 0 or target <= 0 or base_interval <= target:
        return base_interval, None
    return target, f"starting_soon:{phase.reason}"


def starting_soon_poll_interval(
    sport: str,
    base_interval: int,
    *,
    env_key: str,
    default: int = DEFAULT_STARTING_SOON_POLL_INTERVAL_SECONDS,
    phase: SlatePhase | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    """An injury/news poll interval, shortened while the sport starts soon.

    `phase=None` resolves it here, so a worker autorun needs one call and no
    knowledge of the fixture clock.
    """
    if not starting_soon_enabled(env):
        return base_interval
    resolved = phase if phase is not None else current_phase(sport, env=env)
    if resolved.phase != PHASE_STARTING_SOON:
        return base_interval
    fast = _env_int(env_key, default, env)
    if fast <= 0:
        return base_interval
    return min(base_interval, fast)


def t_window_force_allowed(
    last_sweep_epoch: float | None,
    *,
    now_epoch: float,
    env: Mapping[str, str] | None = None,
) -> bool:
    """False when a sweep of this sport ran within the min gap; that sweep covers
    the window, so the caller credits the marker without forcing another."""
    gap = t_window_min_gap_seconds(env)
    if gap <= 0 or not last_sweep_epoch or last_sweep_epoch <= 0:
        return True
    return (float(now_epoch) - float(last_sweep_epoch)) >= gap


def schedule_commence_times(
    sport: str,
    date_str: str,
    *,
    fetch: Callable[[str, str], list[Any]] | None = None,
) -> list[tuple[str, float]]:
    """T-window commence times from the shared schedule adapter.

    For the sports without a dedicated provider (nfl, ncaaf, nba, nhl, ncaab).
    `fetch_schedule_for_date` is the adapter the fixture clock already trusts, so
    the T-window and the phase agree on when a game starts. Fails open to `[]`.
    """
    if fetch is None:
        from syndicate.features.shared.schedule_adapter import fetch_schedule_for_date as fetch
    try:
        events = fetch(sport, date_str) or []
    except Exception:
        return []
    out: list[tuple[str, float]] = []
    for event in events:
        try:
            epoch = event.start_time_epoch()
            event_id = str(getattr(event, "event_id", "") or "").strip()
        except Exception:
            continue
        if epoch is not None and event_id:
            out.append((event_id, float(epoch)))
    return sorted(out, key=lambda item: item[1])


# ---------------------------------------------------------------------------
# Injury-file change detection.
# ---------------------------------------------------------------------------


def file_fingerprint(path: Path | str) -> str | None:
    """sha256 of the file's bytes, or None when it cannot be read."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def injury_file_changed(
    sport: str,
    path: Path | str,
    *,
    read_state: Callable[[Path], Any],
    write_state: Callable[[Path, Any], Any],
    state_path: Path,
    date_str: str,
) -> bool:
    """True when the injury file's content changed since the last check TODAY.

    First sight of a date (or of the file) records a baseline and returns False
    -- a day rollover is not injury news, the same rule `_should_force_sim_rerun`
    applies so the board does not tag every sport "news-driven" once a day. An
    unreadable file returns False and leaves the baseline alone.
    """
    current = file_fingerprint(path)
    if current is None:
        return False
    try:
        state = read_state(state_path)
    except Exception:
        state = None
    state = state if isinstance(state, dict) else {}
    same_day = str(state.get("date") or "") == date_str
    previous = state.get(sport) if same_day else None
    if previous == current and same_day:
        return False
    try:
        merged = dict(state) if same_day else {}
        merged.update({"date": date_str, sport: current})
        write_state(state_path, merged)
    except Exception as exc:  # noqa: BLE001 -- a lost baseline costs one extra sweep
        print(f"[slate_phase] INJURY_FINGERPRINT_WRITE_FAILED sport={sport} {type(exc).__name__}: {exc}", flush=True)
    return previous is not None and previous != current
