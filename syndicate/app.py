"""
Context: Syndicate Simulation System
See: docs/ai_context/architecture.md

Role:
- Creates the Flask app, registers blueprints, and starts background loops.

Constraints:
- State-driven execution
- Avoid redundant computation
"""

from __future__ import annotations

import os
import tempfile
import threading
from typing import Callable

from flask import Flask
from flask.json.provider import DefaultJSONProvider
from syndicate.features.shared import memory_observability
from syndicate.blueprints.ask_the_syndicate import ask_the_syndicate_bp
from syndicate.blueprints.home import home_bp
from syndicate.blueprints.intelligence import intelligence_bp
from syndicate.blueprints.ops import ops_bp
from syndicate.blueprints.nfl import nfl_bp
from syndicate.blueprints.nhl import nhl_bp
from syndicate.blueprints.ncaab import ncaab_bp
from syndicate.blueprints.ncaaf import ncaaf_bp
from syndicate.blueprints.nba import nba_bp
from syndicate.blueprints.mlb import mlb_bp
from syndicate.blueprints.opportunity_board import opportunity_board_bp
from syndicate.blueprints.soccer import soccer_bp
from syndicate.blueprints.sports import sports_bp
from syndicate.blueprints.wnba import wnba_bp
from syndicate.features.shared.json_safety import json_safe_value
from syndicate.features.shared.live_refresh_loop import start_live_refresh_background_loop
from pipeline.intelligence_state import start_intelligence_state_background_loop


class _NaNSafeJSONProvider(DefaultJSONProvider):
    """Sanitizes NaN/Infinity/-Infinity out of every jsonify() response.

    Root cause: syndicate/features/shared/json_safety.py's docstring.
    A per-call-site sanitizer (syndicate/blueprints/intelligence.py's
    _json_safe_value, added 2026-07-31) closed this for one blueprint's
    response paths, then the same bug recurred 2026-08-04 in a second,
    unrelated blueprint that had never been wired through it. Applying it
    here instead -- at the app's own JSON provider -- covers every
    jsonify() call across every current and future blueprint by
    construction, not by remembering to wire each new response path
    through a shared helper.
    """

    def dumps(self, obj: object, **kwargs: object) -> str:
        return super().dumps(json_safe_value(obj), **kwargs)


def _env_bool(name: str, *, default: bool = False) -> bool:
    raw = str(os.environ.get(name) or "").strip().lower()
    if not raw:
        return bool(default)
    return raw in {"1", "true", "yes", "on"}


# Last-resort backstop only. With the lock container-local AND pid-checked, this
# fires just for PID reuse inside one long-lived container -- not for the
# cross-boot case, which cannot happen any more.
_BOOTSTRAP_LOCK_MAX_AGE_SECONDS = 1800


def _pid_is_running(pid: int) -> bool:
    """Whether `pid` is a live process IN THIS CONTAINER.

    This is only a valid signal because the lock it backs is container-local
    (see `_bootstrap_lock_path`). `deploys.md` 2026-08-19 records a PID being
    used as a CROSS-SESSION liveness check and being wrong for exactly the
    reason that does not apply here: PID namespaces restart with the container,
    so a PID recorded by another container names a different process or none at
    all. Same call, sound here, unsound there -- the difference is entirely
    where the lock lives.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by another user
    except OSError:
        # Unknown. Treat as ALIVE: refusing to take a lock costs one skipped
        # sync, while stealing a live one runs two syncs at once. The age
        # backstop still breaks a lock that reads "alive" forever.
        return True
    return True


def _bootstrap_lock_path() -> str:
    """CONTAINER-LOCAL on purpose. This is the whole 2026-08-20 fix.

    The lock lived at `<SYNDICATE_DATA_ROOT>/.bootstrap_sync.lock` -- on the
    Render PERSISTENT DISK -- while what it guards ("only one gunicorn worker
    per BOOT runs the sync") is scoped to a single container. **A lock stored
    somewhere that outlives its own scope can poison a boot it was never meant
    to see**, and that is not a hypothetical:

    Measured 2026-08-20. Web's boot sync started 22:36:47Z and was killed 63s
    in when a `/healthz` timeout took the instance (`server_failed`, 22:37:52.78Z).
    gunicorn shut down GRACEFULLY, so the daemon thread was never joined and the
    `finally` that removes the lock never ran. The replacement instance booted
    at 22:38:05Z, found that lock 78 seconds old, and **skipped its sync
    entirely** -- for 30 minutes, on the age check alone. Web took 8 deploys
    that day, so the sync may routinely never complete. That is the likeliest
    reason 1,114 of 8,016 hot artifacts were stale mirror copies rather than
    all ~33k (`#494`).

    In a temp dir the file dies with the container, so a new boot always starts
    clean -- and the PID written inside it now refers to THIS container's PID
    namespace, which is what turns `_pid_is_running` into a real check instead
    of a guess.

    (`fcntl.flock` would be stronger still -- the kernel drops it when the
    holder dies, with no pid and no clock. Not used because it is POSIX-only,
    which would leave production running a branch the Windows test suite can
    never execute. The failure mode here was a lock outliving its holder; the
    fix removes the place it could outlive them.)
    """
    return os.path.join(tempfile.gettempdir(), "syndicate_bootstrap_sync.lock")


def _bootstrap_render_data(bootstrap_main: Callable[[], int] | None = None) -> None:
    if not _env_bool("SYNDICATE_BOOTSTRAP_ON_START", default=False):
        return
    if bootstrap_main is None:
        try:
            from scripts.bootstrap_data_root import main as bootstrap_main  # type: ignore
        except Exception:
            return
    if _is_render_web_dyno():
        # 2026-07-05: running bootstrap synchronously during app creation
        # blocked startup long enough for Render's proxy to 502, so it was
        # skipped here outright. But with the GHA daily-update retired this
        # is the only path that lands committed repo data (sim summaries,
        # boxscore histories, BvP caches) on the web service's own disk
        # after a deploy -- so run it in a background thread instead: the
        # app binds immediately and the disk backfills within minutes.
        # WEB_CONCURRENCY > 1 means several gunicorn worker *processes* each
        # build the app independently at boot (no --preload), so a plain
        # check-then-write lock would race: both could pass the exists()
        # check before either writes the file. O_CREAT|O_EXCL is atomic --
        # the OS guarantees only one process wins the open() call.
        def _run_bootstrap() -> None:
            import time

            # 2026-07-20: observed the container at ~100% of its 2GB ceiling
            # (sub-1MB headroom, memory_observability.py's pre-existing
            # instrumentation) immediately after this sync finished, while
            # real post-deploy traffic hit WNBA's already-memory-tight card
            # payload builder. Root cause is that builder's own memory use,
            # not this sync -- but the two land in the same narrow
            # post-deploy window, so give the initial traffic surge and
            # health checks time to settle before adding this sync's disk
            # I/O (and resulting page-cache pressure) on top of it.
            time.sleep(20)

            data_root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip() or "data"
            lock_path = _bootstrap_lock_path()

            def _take_lock() -> bool:
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                except FileExistsError:
                    return False
                except OSError as exc:
                    print(
                        f"[bootstrap] LOCK_UNAVAILABLE path={lock_path} "
                        f"{type(exc).__name__}: {exc}",
                        flush=True,
                    )
                    return False
                try:
                    os.write(fd, str(os.getpid()).encode("utf-8"))
                finally:
                    os.close(fd)
                return True

            def _lock_holder() -> tuple[int, float]:
                try:
                    with open(lock_path, encoding="utf-8") as handle:
                        holder = int((handle.read() or "").strip() or 0)
                except (OSError, ValueError):
                    holder = 0
                try:
                    age = max(0.0, time.time() - os.path.getmtime(lock_path))
                except OSError:
                    age = 0.0
                return holder, age

            # Every branch below PRINTS. `logger.info` does not reach Render's
            # log collector, and a silent skip is what made the 2026-08-20
            # incident invisible: the boot that dropped its sync looked exactly
            # like a boot that had nothing to do.
            if not _take_lock():
                holder, age = _lock_holder()
                alive = _pid_is_running(holder)
                if alive and age < _BOOTSTRAP_LOCK_MAX_AGE_SECONDS:
                    print(
                        f"[bootstrap] SKIP a live sibling holds the lock "
                        f"pid={holder} age={age:.0f}s",
                        flush=True,
                    )
                    return
                print(
                    f"[bootstrap] RECLAIM stale lock pid={holder} alive={alive} "
                    f"age={age:.0f}s -- its holder is gone, so this boot syncs",
                    flush=True,
                )
                try:
                    os.remove(lock_path)
                except OSError:
                    pass
                if not _take_lock():
                    print("[bootstrap] SKIP another worker won the reclaim race", flush=True)
                    return

            print(f"[bootstrap] LOCK pid={os.getpid()} path={lock_path}", flush=True)
            try:
                # Unrelated to the lock, kept from the original: a cold dyno may
                # not have the mounted root yet.
                os.makedirs(data_root, exist_ok=True)
                bootstrap_main()
            except Exception as exc:
                print(f"[bootstrap] FAILED {type(exc).__name__}: {exc}", flush=True)
            finally:
                try:
                    os.remove(lock_path)
                except OSError:
                    pass

        threading.Thread(target=_run_bootstrap, name="render-bootstrap-sync", daemon=True).start()
        return
    try:
        bootstrap_main()
    except Exception:
        return


def _is_render_web_dyno() -> bool:
    return bool(
        str(os.environ.get("RENDER") or "").strip().lower() in {"1", "true", "yes", "on"}
        or str(os.environ.get("RENDER_EXTERNAL_URL") or "").strip()
        or str(os.environ.get("RENDER_SERVICE_ID") or "").strip()
    )


def create_app() -> Flask:
    _bootstrap_render_data()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.json = _NaNSafeJSONProvider(app)

    if not app.config.get("SYNDICATE_SPORTS"):
        app.config["SYNDICATE_SPORTS"] = [
            {
                "slug": "mlb",
                "name": "MLB",
                "status": "Phase-1 complete",
                "phase": "Reference module",
                "summary": "Phase-1 complete reference module for the shared Syndicate board contract with cards, game detail, live lens, a daily archive, season betting-card surfaces, and stabilized shared rank-board API transport across the main ranked MLB views.",
                "primary_href": "/mlb",
                "primary_label": "Open MLB hub",
                "surfaces": ["cards", "game", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep MLB stable as the reference module, and only extract shared board helpers where multiple migrated sports now prove the abstraction without weakening artifact-backed browser parity.",
                "runtime_contract": {
                    "dependency_tier": "owned_local",
                    "ownership_goal": "full_local",
                    "source_of_truth": "Syndicate-owned artifacts and refresh workflows",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "nba",
                "name": "NBA",
                "status": "Active migration",
                "phase": "Artifact-backed cards + picks + live-lens + betting-card lanes",
                "summary": "NBA now has artifact-backed cards, picks, live-lens, market-accuracy, recap/features payloads, season betting-card flows, a real hub, and a stored-date daily archive under the MLB-shaped public contract, with mirrored live snapshot families covering same-day live fallback lanes.",
                "primary_href": "/nba",
                "primary_label": "Open NBA cards",
                "surfaces": ["cards", "game", "picks", "props", "live-lens", "accuracy", "recap", "features", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NBA stable on the protected artifact-backed contract, and only deepen postgame or historical lanes where mirrored stored-date artifacts already exist.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Local processed artifacts plus mirrored live snapshot families",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "nhl",
                "name": "NHL",
                "status": "Active migration",
                "phase": "Artifact-backed cards + picks + recap + props lanes",
                "summary": "NHL now has artifact-backed cards and game drill-in surfaces in Syndicate, plus ranked picks, a season betting-card lane, native live-lens and market-accuracy pages, local betting and props reconciliation lanes, a props-lines surface, a real hub, and a stored-date daily archive built from mirrored daily artifacts.",
                "primary_href": "/nhl",
                "primary_label": "Open NHL cards",
                "surfaces": ["cards", "game", "live-lens", "accuracy", "recap", "props reconciliation", "props lines", "picks", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NHL stable on the protected artifact-backed contract, and only deepen settled-history lanes where mirrored daily artifacts can support native views.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Mirrored daily artifacts with public schedule augmentation",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "nfl",
                "name": "NFL",
                "status": "Near completion candidate",
                "phase": "Cards + game + grouped picks + betting card",
                "summary": "NFL now has snapshot-backed cards and game drill-ins in Syndicate, alongside grouped weekly picks, a read-only live-lens monitor, a weekly daily archive, source-style picks payload aliases, and a season betting-card companion built from the same stored snapshot lane.",
                "primary_href": "/nfl",
                "primary_label": "Open NFL cards",
                "surfaces": ["cards", "game", "picks", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NFL stable as the next module-family completion candidate, now that weekly snapshots back cards, live lens, archive, and betting-card lanes under the same artifact-backed contract.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Weekly stored snapshots mirrored into Syndicate",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "wnba",
                "name": "WNBA",
                "status": "Active migration",
                "phase": "Artifact-backed shared board + picks + props + live audit lanes",
                "summary": "WNBA now exposes shared cards, picks, props, game detail, a real hub, a first season betting-card lane, MLB-style live-lens routes, a stored-date daily archive lane, and native local accuracy/audit payloads in Syndicate.",
                "primary_href": "/wnba",
                "primary_label": "Open WNBA cards",
                "surfaces": ["cards", "game", "picks", "props", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep WNBA stable on the protected artifact-backed contract, and only deepen historical coverage where repeated stored dates already exist in the mirrored processed lane.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Shared stored-date artifacts plus native local live audit payloads",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "ncaaf",
                "name": "NCAAF",
                "status": "Active migration",
                "phase": "Artifact-backed weekly cards + picks + betting-card lanes",
                "summary": "NCAAF now has artifact-backed weekly cards, game drill-ins, picks, a read-only live-lens monitor, a weekly daily archive, and a season betting-card companion in Syndicate, built from stored recommendation summaries while the live source feed is offseason-empty.",
                "primary_href": "/ncaaf",
                "primary_label": "Open NCAAF cards",
                "surfaces": ["cards", "game", "picks", "live-lens", "daily archive", "season betting-card", "hub"],
                "next_step": "Keep NCAAF stable on the protected artifact-backed weekly contract until the live source workflow repopulates, then decide whether live-lens or archive wrappers need richer native views.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Syndicate-local weekly snapshots",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "ncaab",
                "name": "NCAAB",
                "status": "Active migration",
                "phase": "Mirror-first cards + game + live-lens + historical lanes",
                "summary": "NCAAB now runs cards, game detail, live lens, season review, the historical betting-card companion, and the daily archive from mirrored artifacts inside Syndicate.",
                "primary_href": "/ncaab",
                "primary_label": "Open NCAAB cards",
                "surfaces": ["cards", "game", "live-lens", "daily archive", "season review", "season betting-card", "hub"],
                "next_step": "Keep NCAAB stable as the mirror-first college basketball reference module, and only deepen historical or live wrappers where mirrored artifacts already justify the surface.",
                "runtime_contract": {
                    "dependency_tier": "artifact_backed",
                    "ownership_goal": "mirror_first",
                    "source_of_truth": "Local mirrored NCAAB artifacts refreshed from the source app",
                    "fallback_surfaces": [],
                },
            },
            {
                "slug": "soccer",
                "name": "Soccer",
                "status": "Active migration",
                "phase": "SoccerSim-backed cards + game + props + live lens + daily archive across leagues",
                "summary": "Soccer runs its own possession-based Monte Carlo engine (SoccerSim) across multiple leagues, with artifact-backed cards, a game drill-in, player-prop boards (anytime scorer / shots / shots on target), graded picks (build_soccer_picks.py, consumed by cards/props and the Layer 2 board), a resumed-match live lens covering live corners, live shots/SOT, live goals/BTTS/team totals, and scoring-in-a-window probabilities, and a stored-date daily archive. The scheduled refresh autoruns are live (SYNDICATE_ENABLE_SOCCER_PREGAME_REFRESH_AUTORUN / _WEEKLY_REFRESH_AUTORUN). No settlement/accuracy pipeline exists yet, so market-accuracy and reconciliation lanes are not published for soccer.",
                "primary_href": "/soccer/epl/cards",
                "primary_label": "Open Soccer cards",
                "surfaces": ["cards", "game", "props", "live-lens", "daily archive", "hub"],
                "next_step": "Build a soccer actuals writer (game results + prop reconciliation in prediction_reconciliation.py's expected format) so soccer picks can settle and market-accuracy can follow the same pattern as the other sports.",
                "runtime_contract": {
                    "dependency_tier": "owned_local",
                    "ownership_goal": "full_local",
                    "source_of_truth": "SoccerSim-generated artifacts from ESPN + Understat/ASA/football-data.co.uk ingestion",
                    "fallback_surfaces": [],
                },
            },
        ]
    if not app.config.get("SYNDICATE_ACTIVE_SPORTS"):
        app.config["SYNDICATE_ACTIVE_SPORTS"] = ["mlb", "wnba"]

    @app.context_processor
    def inject_syndicate_sports() -> dict[str, object]:
        return {"syndicate_sports": app.config.get("SYNDICATE_SPORTS", [])}

    # EVERY TIME A PERSON READS IS CENTRAL [USER DECISION 2026-08-25].
    #
    # Registered as a FILTER rather than converted per template, because the
    # failure was a template doing its own arithmetic: the live portfolio
    # rendered `submitted_at[11:19]`, a raw slice of the stored UTC string, so
    # a 6:15 PM Central order displayed as `23:15:05` -- unlabelled, five hours
    # wrong, in the column a person uses to reconcile against the venue.
    #
    # Storage stays UTC on purpose. Venue payloads are UTC, `fetched_at` ages
    # are computed against `time.time()`, and ISO strings are compared lexically
    # throughout; rewriting stored stamps into a zone with a DST discontinuity
    # would break all of that, and twice a year would break it silently. UTC on
    # the wire and on disk, Central at the edge.
    from syndicate.features.shared.timezone import central_clock, central_clock_from_epoch

    app.jinja_env.filters["central"] = central_clock
    app.jinja_env.filters["central_epoch"] = central_clock_from_epoch

    app.register_blueprint(home_bp)
    app.register_blueprint(intelligence_bp)
    app.register_blueprint(opportunity_board_bp)
    app.register_blueprint(ask_the_syndicate_bp)
    app.register_blueprint(ops_bp)
    app.register_blueprint(mlb_bp)
    app.register_blueprint(nba_bp)
    app.register_blueprint(nhl_bp)
    app.register_blueprint(nfl_bp)
    app.register_blueprint(wnba_bp)
    app.register_blueprint(ncaaf_bp)
    app.register_blueprint(ncaab_bp)
    app.register_blueprint(soccer_bp)
    app.register_blueprint(sports_bp)

    
    @app.route("/")
    def root():
        return "OK", 200

    def _start_background_loops() -> None:
        render_web_dyno = _is_render_web_dyno()
        if render_web_dyno and not _env_bool("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", default=False):
            return
        if app.extensions.get("syndicate_background_loops_started"):
            return
        if app.extensions.get("syndicate_background_loops_bootstrap_started"):
            return
        app.extensions["syndicate_background_loops_bootstrap_started"] = True

        def _bootstrap_background_loops() -> None:
            try:
                if app.extensions.get("syndicate_background_loops_started"):
                    return
                start_intelligence_state_background_loop(app)
                if not render_web_dyno:
                    start_live_refresh_background_loop()
                app.extensions["syndicate_background_loops_started"] = True
            finally:
                app.extensions.pop("syndicate_background_loops_bootstrap_started", None)

        threading.Thread(
            target=_bootstrap_background_loops,
            name="syndicate-background-loop-bootstrap",
            daemon=True,
        ).start()

    # `#632`. PER-REQUEST ANON ATTRIBUTION, DEFAULT OFF.
    #
    # Web's anonymous memory climbs to 89% of a 2GB limit and never falls except
    # at a restart, and the cheap per-route explanation is already dead: the
    # correlation collapsed from +0.499 to +0.139 once one outlier window was
    # dropped. This is the instrument that can answer it, and it is registered
    # UNCONDITIONALLY but does nothing until `SYNDICATE_REQUEST_MEMORY_PROFILE`
    # is set -- `note_request_start` checks the key before it touches the cgroup.
    #
    # Registering it unconditionally is deliberate: a hook added only when the
    # key is set at IMPORT time cannot be switched on by an env change alone,
    # and someone would set the key, see nothing, and conclude the leak had
    # stopped. `#241` is why the WORK is gated rather than the registration.
    @app.before_request
    def _note_request_memory_start() -> None:
        from flask import g, request

        try:
            # The ROUTE is passed at ENTRY because this layer is the only one
            # that knows it in time. `note_request_end` learns the rule at
            # teardown, which is too late to decide whether to take a BEFORE
            # reading -- and a per-request bucket delta needs both halves.
            # Same RULE, not raw path, for the same reason as at teardown.
            rule = getattr(request.url_rule, "rule", None) or "<unmatched>"
            g._syndicate_memory_token = memory_observability.note_request_start(rule)
        except Exception:
            g._syndicate_memory_token = None

    @app.teardown_request
    def _note_request_memory_end(_exc: BaseException | None = None) -> None:
        from flask import g, request

        token = getattr(g, "_syndicate_memory_token", None)
        try:
            # The RULE, not the raw path: `/mlb/api/cards?date=` must not become
            # one route per date, or the table is a histogram of traffic and
            # attributes nothing.
            rule = getattr(request.url_rule, "rule", None) or "<unmatched>"
            memory_observability.note_request_end(token, rule)
        except Exception:
            pass

    if _is_render_web_dyno():
        if _env_bool("SYNDICATE_ENABLE_INTELLIGENCE_STATE_BACKGROUND_LOOP", default=False):
            _start_background_loops()
    else:
        try:
            app.before_serving(_start_background_loops)
        except AttributeError:
            app.before_request(_start_background_loops)

    return app


app = create_app()