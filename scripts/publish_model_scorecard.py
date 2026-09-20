"""The `model-scorecard` Render cron: grade the priced population, publish the scorecard and overlay.

Lane `model-scorecard-cron` `[2026-09-17]`. Daily. On Mondays (Central) it also runs the
weekly backtests (`scripts/run_weekly_backtests.py`) and publishes their report.

    py -3 scripts/publish_model_scorecard.py                       # grade + write locally, publish nothing
    py -3 scripts/publish_model_scorecard.py --publish --verify    # what the cron runs
    py -3 scripts/publish_model_scorecard.py --weekly on           # force the weekly backtests

WHAT A RUN DOES, IN ORDER
1. Reads its own previous STATE, scorecard and overlay back from web. A state read that
   FAILS (anything but a clean 404) stops the run: starting from an empty state and
   publishing it would erase a month of graded history and read as a quiet first run.
2. Fetches the recorder parts (`opportunity_population_ledger`) for the board dates that can
   still change -- today, yesterday, and any date in the window not yet complete. One read at
   a time through `/api/ops/artifacts/stream` (see `WebReader`), never `export`.
3. Grades every game whose kickoff date has passed with `bucket_search.grade_population`,
   MLB props through `MlbPropGrader`, and everything else through `population_outcomes`.
4. Builds the scorecard (7d / 28d) and the validated-bucket overlay, writes them under the
   data root, publishes, and reads the scorecard back.

REFUSALS, NOT SILENT ZEROS
- No ADMIN_TOKEN: exit 2.
- Every board-date fetch failed: exit 3 -- nothing is published, because an overlay built on
  nothing would replace a real one with an empty table.
- The state read failed: exit 4.
- A publish failed: exit 5. The read-back does not match: exit 6.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from syndicate.features.shared import model_scorecard as msc  # noqa: E402

# Sports with recorder parts to read.
#
# THE OFF-SEASON EXCLUSION IS A COST DECISION AND IT STAYS -- every board date would spend one
# not-found read per out-of-season sport. What changed 2026-09-20 (lane `daily-accuracy-suite`)
# is that it is no longer a hand-maintained list whose note said "add them back when their
# seasons open" and relied on somebody remembering. `SEASON_WINDOWS` decides it per run date,
# so NBA turns itself on in late October and off again in late June.
#
# The windows are deliberately COARSE. The question they answer is "should anyone expect rows
# for this sport today", not "is there a game tonight" -- a sport inside its window with no
# slate simply reads zero, which is cheap and honest. Being WRONG in the generous direction
# costs one not-found read; being wrong in the mean direction silently drops a sport from the
# accuracy job for a month, which is the failure this replaces.
#
# NCAAB is inside a window here and still will not grade: it is not in the ESPN settler's
# HANDLED_SPORTS because no NCAAB team registry exists. That is deliberate and visible --
# the scorecard will carry the sport with zero graded rows rather than omit it silently.
SEASON_WINDOWS = {
    "mlb": ((3, 20), (11, 5)),
    "nba": ((10, 1), (6, 25)),
    "ncaab": ((11, 1), (4, 10)),
    "ncaaf": ((8, 20), (1, 20)),
    "nfl": ((9, 1), (2, 15)),
    "nhl": ((9, 15), (6, 30)),
    "soccer": ((7, 15), (6, 5)),
    "wnba": ((5, 1), (10, 20)),
}
ALL_SPORTS = tuple(sorted(SEASON_WINDOWS))


def in_season(sport: str, today: date) -> bool:
    """Whether `sport` is inside its (coarse) season window on `today`.

    Windows wrap the new year where the end month/day is before the start's -- NFL runs
    September to mid-February, so a January date is IN season and a May date is not.
    """
    window = SEASON_WINDOWS.get(str(sport or "").strip().lower())
    if window is None:
        return True  # unknown sport: never silently drop it
    (start_month, start_day), (end_month, end_day) = window
    start, end, now = (start_month, start_day), (end_month, end_day), (today.month, today.day)
    return start <= now or now <= end if end < start else start <= now <= end


def sports_in_season(today: date) -> tuple[str, ...]:
    return tuple(sport for sport in ALL_SPORTS if in_season(sport, today))


DEFAULT_SPORTS = ("mlb", "nfl", "ncaaf", "soccer", "wnba", "nhl")
EXPORT_PAUSE_SECONDS = 2.0
TOOL = "publish_model_scorecard"


class FetchError(RuntimeError):
    """A read that did not come back as content or a clean not-found."""


def log(message: str) -> None:
    print(f"[model_scorecard] {message}", flush=True)


def data_root() -> Path:
    root = str(os.environ.get("SYNDICATE_DATA_ROOT") or "").strip()
    return Path(root).expanduser().resolve() if root else (REPO_ROOT / "data")


def base_url() -> str:
    for key in ("SYNDICATE_WEB_PUBLISH_URL", "SYNDICATE_BASE_URL", "BASE_URL"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value.rstrip("/")
    return "https://syndicate-an21.onrender.com"


def admin_token() -> str:
    value = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if value:
        return value
    env = REPO_ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("ADMIN_TOKEN"):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class WebReader:
    """Sequential, paced, retried reads of web's disk.

    THROUGH `/api/ops/artifacts/stream`, NOT `/export`. The first production run (2026-09-17
    15:26-15:33Z) read recorder parts through `export`: 58 calls took 290 s, one board date took
    2 m 19 s, and web answered the scoreboard with 502 right after -- the run graded nothing
    (`chips_unavailable` 61). `stream` is a `send_file` from disk with the same admin gate and
    allowlist (the weekly runner measured a 19.1 MB file in 0.9 s), so it is the one to lean on.
    """

    def __init__(self, base: str, token: str, *, attempts: int = 3, pause: float = EXPORT_PAUSE_SECONDS,
                 opener: Any = None) -> None:
        self.base, self.token, self.attempts, self.pause = base, token, attempts, pause
        self.opener = opener or urllib.request.urlopen
        self.calls = 0
        self.seconds = 0.0

    def text(self, relative: str) -> str | None:
        """File content as text, None for a clean not-found, FetchError for anything else."""
        blob = self.bytes(relative)
        return None if blob is None else blob.decode("utf-8")

    def bytes(self, relative: str) -> bytes | None:
        """File content as bytes, None for a clean not-found, FetchError for anything else."""
        url = f"{self.base}/api/ops/artifacts/stream?path={urllib.parse.quote(relative, safe='')}"
        last: Exception | None = None
        for attempt in range(self.attempts):
            if self.calls:
                time.sleep(self.pause)
            self.calls += 1
            started = time.monotonic()
            try:
                request = urllib.request.Request(url, headers={"X-Admin-Token": self.token})
                with self.opener(request, timeout=240) as response:
                    body = response.read()
                self.seconds += time.monotonic() - started
                return body
            except urllib.error.HTTPError as exc:
                self.seconds += time.monotonic() - started
                if exc.code in (403, 404):
                    return None
                last = exc
            except Exception as exc:  # network, timeout, undecodable body
                self.seconds += time.monotonic() - started
                last = exc
            time.sleep(min(30.0, 10.0 * (attempt + 1)))
        raise FetchError(f"{relative}: {type(last).__name__}: {last}")

    def json(self, relative: str) -> Any:
        text = self.text(relative)
        return None if text is None else json.loads(text)


def fetch_board_date(reader: WebReader, bs: Any, day: str, sports: list[str]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    records: list[dict[str, Any]] = []
    parts: dict[str, int] = {}
    for sport in sports:
        for part in range(bs.MAX_PARTS):
            relative = f"reports/intelligence/{bs.POPULATION_SUBDIR}/{day}__{sport}__part{part:03d}.jsonl"
            text = reader.text(relative)
            if text is None:
                break
            records.extend(bs.parse_records_text(text))
            parts[sport] = part + 1
    return records, parts


def fetch_chips_with_retry(bs: Any, day: str, *, attempts: int = 4) -> list[Any]:
    """The public scoreboard, retried: a 502 from a busy web is transient, a missing scoreboard is not."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            return bs.SCORECARD.fetch_chips(base_url(), day, None)
        except Exception as exc:
            last = exc
            log(f"CHIPS_RETRY {day} attempt={attempt + 1} {type(exc).__name__}: {exc}")
            time.sleep(min(60.0, 15.0 * (attempt + 1)))
    raise last if last is not None else RuntimeError("unreachable")


def grader_signature(bs: Any, settler: Any) -> tuple[str, dict[str, str], dict[str, Any]]:
    """(core signature, per-sport versions, report block).

    The CORE is the code every sport grades through; a change there resets all history. Each
    sport's version is its settler's declared version -- plus, for MLB, a hash of the prop grader
    that only MLB uses -- so changing or adding one sport's settler resets only that sport.
    """
    from syndicate.features.mlb import prop_outcomes

    def digest(objects: tuple[Any, ...]) -> str:
        return hashlib.sha256("\n".join(inspect.getsource(obj) for obj in objects).encode("utf-8")).hexdigest()[:12]

    core = digest((bs.grade_population, bs.settle_from_score, bs.scorecard_record, bs.SCORECARD.grade,
                   bs.SCORECARD.match_chip))
    sport_versions = dict(settler.sport_versions)
    sport_versions["mlb"] = (f"{sport_versions.get('mlb', 'unavailable:mlb')}+props:"
                             f"{digest((prop_outcomes.MlbPropGrader.settle, prop_outcomes.MlbPropGrader.final_score))}")
    signature = json.dumps({"scorecard": msc.SCORECARD_VERSION, "core_code": core}, sort_keys=True)
    grader = {"scorecard": msc.SCORECARD_VERSION, "core_code": core, "sport_versions": sport_versions,
              "settlers": settler.versions, "settlers_unavailable": sorted(settler.unavailable)}
    return signature, sport_versions, grader


def write(relative: str, content: str | bytes) -> Path:
    path = data_root() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def publish(relative: str, token: str) -> bool:
    from syndicate.features.shared import artifact_publisher as ap

    return bool(ap._publish_streamed(  # noqa: SLF001
        data_root() / relative, relative_path=relative, url=base_url() + "/api/ops/artifacts/publish",
        token=token, timeout_seconds=300, publisher=ap.publisher_identity_for_tool(TOOL)))


def weekly_due(mode: str, today: str) -> bool:
    if mode == "on":
        return True
    if mode == "off":
        return False
    return datetime.fromisoformat(today).weekday() == 0


def run_weekly(today: str, token: str, *, publish_outputs: bool) -> dict[str, Any]:
    runner = REPO_ROOT / "scripts" / "run_weekly_backtests.py"
    if not runner.is_file():
        return {"status": "skipped", "reason": "runner_absent"}
    out_dir = Path(tempfile.mkdtemp(prefix="weekly_backtests_"))
    env = dict(os.environ, ADMIN_TOKEN=token)
    started = time.monotonic()
    proc = subprocess.run([sys.executable, str(runner), "--out-dir", str(out_dir)], cwd=REPO_ROOT, env=env,
                          capture_output=True, text=True)
    for line in (proc.stdout or "").splitlines()[-15:]:
        log("weekly | " + line[:240])
    result: dict[str, Any] = {"exit_code": proc.returncode, "seconds": round(time.monotonic() - started, 1),
                              "published": []}
    for produced in sorted(out_dir.glob("weekly_backtests_*")):
        # No ISO date in the published name (the workers' `*<date>*` pulls), whichever date the runner stamped.
        stamp = re.sub(r"(\d{4})-(\d{2})-(\d{2})", r"\1\2\3", produced.name)
        relative = f"{msc.REPORT_DIR}/weekly/{stamp}"
        write(relative, produced.read_text(encoding="utf-8"))
        if publish_outputs and publish(relative, token):
            result["published"].append(relative)
    result["status"] = "ok" if proc.returncode == 0 else "failed"
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--sports", default="auto",
                        help="comma-separated, or 'auto' (default): every sport inside its "
                             "SEASON_WINDOWS entry on the run date. 'all' reads every sport regardless.")
    parser.add_argument("--max-board-dates", type=int, default=10)
    parser.add_argument("--resamples", type=int, default=None)
    parser.add_argument("--weekly", choices=("auto", "on", "off"), default="auto")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    token = admin_token()
    if not token:
        log("REFUSING: no ADMIN_TOKEN -- every read would 401 and the scorecard would grade nothing.")
        return 2
    bs = msc.load_bucket_search()
    today = msc.central_today(now, bs.SCORECARD.central_date)
    if args.sports.strip().lower() == "auto":
        sports = list(sports_in_season(date.fromisoformat(today)))
        log(f"SPORTS_IN_SEASON date={today} sports={','.join(sports)} "
            f"off_season={','.join(s for s in ALL_SPORTS if s not in sports) or 'none'}")
    elif args.sports.strip().lower() == "all":
        sports = list(ALL_SPORTS)
    else:
        sports = [s.strip().lower() for s in args.sports.split(",") if s.strip()]
    reader = WebReader(base_url(), token)
    cache = Path(tempfile.mkdtemp(prefix="model_scorecard_cache_"))
    log(f"START today_central={today} base={base_url()} data_root={data_root()} sports={','.join(sports)}")

    from syndicate.features.mlb.prop_outcomes import MlbPropGrader
    from syndicate.features.shared.population_outcomes import build_extra_settler

    mlb = MlbPropGrader(cache_dir=cache / "statsapi")
    settler = build_extra_settler(cache_dir=cache / "settlers", fetch_export=reader.text)
    signature, sport_versions, grader = grader_signature(bs, settler)
    log(f"GRADER {json.dumps(grader, sort_keys=True)}")

    try:
        saved_state = msc.decode_state(reader.bytes(msc.STATE_PATH))
        previous = reader.json(msc.LATEST_PATH)
    except FetchError as exc:
        log(f"REFUSING: could not read the saved state ({exc}). Publishing a fresh state would erase history.")
        return 4
    state, reset = msc.load_state(saved_state, signature, now=now, sport_versions=sport_versions)
    log(f"STATE loaded={'yes' if saved_state is not None else 'no (first run)'} reset={reset} "
        f"games={len(state['games'])} pending={len(state['pending'])}")

    fetched_ok = 0
    merge_counts: dict[str, Any] = {}
    for day in msc.board_dates_to_fetch(state, today, limit=args.max_board_dates):
        try:
            records, parts = fetch_board_date(reader, bs, day, sports)
        except FetchError as exc:
            log(f"FETCH_FAILED board_date={day} {exc}")
            continue
        fetched_ok += 1
        merge_counts[day] = {"parts": parts, **msc.merge_board_date(
            state, day, records, today=today, central_date=bs.SCORECARD.central_date,
            fetched_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))}
        log(f"BOARD_DATE {day} parts={parts} {merge_counts[day]}")
    if fetched_ok == 0:
        log("REFUSING: every board-date fetch failed; publishing would replace the overlay with an empty table.")
        return 3

    grade = functools.partial(bs.grade_population, prop_settler=mlb.settle, score_source=mlb.final_score,
                              extra_settler=settler)
    grading = msc.grade_pending(state, today=today, grade=grade,
                                chips_for=functools.partial(fetch_chips_with_retry, bs),
                                central_date=bs.SCORECARD.central_date)
    msc.prune(state, today)
    log(f"GRADED {grading} settlers={settler.report()}")

    run_info = {"board_dates": merge_counts, "grading": grading, "settlers": settler.report(),
                "exports": {"calls": reader.calls, "seconds": round(reader.seconds, 1)}, "reset": reset}
    scorecard, overlay = msc.build_scorecard(state, bs=bs, today=today, now=now, grader=grader, run=run_info,
                                             previous=previous, resamples=args.resamples)
    try:
        previous_overlay = reader.json(msc.OVERLAY_PATH)
    except FetchError:
        previous_overlay = None
    scorecard["overlay"]["diff"] = msc.overlay_diff(previous_overlay, overlay)

    weekly = None
    if weekly_due(args.weekly, today):
        weekly = run_weekly(today, token, publish_outputs=args.publish)
        scorecard["weekly_backtests"] = weekly

    outputs = {
        msc.STATE_PATH: msc.encode_state(state),
        msc.OVERLAY_PATH: json.dumps(overlay, indent=1, sort_keys=True),
        msc.scorecard_path(today): json.dumps(scorecard, indent=1, sort_keys=True, default=str),
        msc.markdown_path(today): msc.markdown(scorecard),
        msc.LATEST_PATH: json.dumps(scorecard, indent=1, sort_keys=True, default=str),
    }
    for relative, content in outputs.items():
        path = write(relative, content)
        log(f"WROTE {relative} bytes={path.stat().st_size}")
    for label, window in scorecard["windows"].items():
        log(f"WINDOW {label} {json.dumps(window['coverage']['by_sport'])} cells={len(window['cells'])} "
            f"changes={len(window['verdict_changes'])}")
    log(f"OVERLAY buckets={len(overlay['buckets'])} validated={overlay['buckets_validated']} "
        f"diff={json.dumps(scorecard['overlay']['diff'])}")

    if not args.publish:
        log("NOT PUBLISHED (--publish not given)")
        return 0
    failed = [relative for relative in outputs if not publish(relative, token)]
    if failed:
        log(f"PUBLISH_FAILED {failed}")
        return 5
    log(f"PUBLISHED {len(outputs)} files")
    if args.verify:
        try:
            echoed = reader.json(msc.LATEST_PATH)
        except FetchError as exc:
            echoed, error = None, str(exc)
        else:
            error = None
        if not isinstance(echoed, dict) or echoed.get("generated_at") != scorecard["generated_at"]:
            log(f"VERIFY_FAILED latest generated_at={None if not isinstance(echoed, dict) else echoed.get('generated_at')} "
                f"expected={scorecard['generated_at']} error={error}")
            return 6
        log(f"VERIFIED latest generated_at={echoed['generated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
