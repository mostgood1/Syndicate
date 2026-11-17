"""The live-betting change register: what restarts the scale-up gate's 800-event clock (todo #815).

    python scripts/betting_change.py clock            # where the clock starts, and which change set it
    python scripts/betting_change.py candidates       # deploys.md entries since coverage that nothing classifies
    python scripts/betting_change.py add --kind yes --loaded-at 2026-11-17T00:04:38Z \
        --what "NCAAB per-line total calibration" --deploy "2026-11-17 00:04:20Z" --lane ncaab-total-overprojection
    python scripts/betting_change.py add --kind yes --pending live-odds-worker --what "..." --deploy "..." --lane ...
    python scripts/betting_change.py resolve BC-015 --loaded-at 2026-11-17T06:01:00Z
    python scripts/betting_change.py add --kind no --deploy "2026-11-17 00:20:21Z" --what "log line only" --lane ...

The user decided on 2026-11-16 that "Any betting change" restarts the scale-up gate's count of independent events
(findings_2026-11-16_live_book_edge_readout.md, § "Scale-up gate"). A betting change is any fleet load (code or env)
that changes which live bets are placed, how they are sized, or how they are held or exited. Display-only,
ledger-only and shadow-only changes are not.

- **The register** is `.syndicate/betting_changes.md`: one table row per classified deploy. `yes` rows restart the
  clock at their LOAD time (when the running role picked the change up, not the ff). A `yes` whose load has not
  happened yet is `pending:<roles>`. While any `yes` is pending, the clock starts NOW: the count is 0 until someone
  records the load. That fails closed: an unknown load time must not let pre-change bets count.
- **Coverage.** Every deploys.md entry that loads something, from the register's `Classified from:` instant on,
  needs a row (`yes` or `no`) or a `betting change: yes|no` line in its own body. `candidates` lists the ones that
  have neither. The deploy-like filter is a heuristic over the heading; it is a reminder list, not a classifier.
- **Read by** `scripts/live_book_edge_readout.py`, which measures the gate over bets SUBMITTED after the clock start.

Writes only `.syndicate/betting_changes.md`, and only for `add` / `resolve`.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
REGISTER_PATH = ROOT / ".syndicate" / "betting_changes.md"
DEPLOYS_PATH = ROOT / ".syndicate" / "deploys.md"

KIND_YES = "yes"
KIND_NO = "no"
PENDING_PREFIX = "pending:"
TABLE_HEADER = "| id | kind | loaded_at (UTC) | what changed | deploys.md entry | lane |"
TABLE_RULE = "|---|---|---|---|---|---|"

_ID_RE = re.compile(r"^BC-(\d{3,})$")
_COVERAGE_RE = re.compile(r"^Classified from:\s*`?([0-9T:\-. Z]+?)`?\s*$", re.MULTILINE)
_HEADING_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}(?::\d{2})?)(?:\.\d+)?Z(.*)$", re.MULTILINE)
_DEPLOY_LIKE = re.compile(r"\bff\b|FLEET|DEPLOY|\bTERM\b|LOADED|\bLOAD\b|\benv\b|restart|recycle|down/up", re.IGNORECASE)
_NO_DEPLOY = re.compile(r"no deploy|not a deploy", re.IGNORECASE)
_LOAD_WORDS = re.compile(r"LOADED|recycle", re.IGNORECASE)
_BODY_TAG = re.compile(r"betting change:\s*(yes|no)\b", re.IGNORECASE)


@dataclass(frozen=True)
class Change:
    id: str
    kind: str  # yes | no
    loaded_at: str  # ISO-8601 UTC "YYYY-MM-DDTHH:MM:SSZ", or "pending:<roles>"
    what: str
    deploy: str  # the deploys.md heading's instant, normalised; "" when there is no entry
    lane: str

    @property
    def pending(self) -> bool:
        return self.loaded_at.startswith(PENDING_PREFIX)


@dataclass(frozen=True)
class ClockStart:
    start: str  # ISO-8601 UTC; bets SUBMITTED at or after it count
    change: Change
    pending: bool  # True: a yes has not loaded yet, so the clock starts at `now`


def normalize_ts(value: str) -> str:
    """'2026-11-17 00:04:20Z', '2026-11-17T00:04Z', '2026-11-17T00:04:20.467Z' -> '2026-11-17T00:04:20Z'."""
    text = str(value or "").strip()
    match = re.match(r"^(\d{4}-\d{2}-\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.\d+)?(?:Z|\+00:00)$", text)
    if not match:
        raise ValueError(f"not a UTC timestamp: {value!r} (want YYYY-MM-DDTHH:MM[:SS]Z)")
    day, hh, mm, ss = match.groups()
    stamp = f"{day}T{hh}:{mm}:{ss or '00'}Z"
    datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ")  # rejects 25:00 and the like
    return stamp


def parse_utc(value: str | None) -> datetime | None:
    """Any ISO-8601 UTC instant (fractions up to nanoseconds) -> an aware datetime; None if it does not parse."""
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    match = re.match(r"^(.*?\d{2}:\d{2}:\d{2})(\.\d+)?(\+00:00)$", text)
    if match:
        head, frac, tail = match.groups()
        text = head + ((frac or "")[:7]) + tail
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _cell(text: str) -> str:
    return " ".join(str(text or "").replace("|", "/").split())


def parse_register(text: str) -> tuple[list[Change], str | None]:
    """The register's rows and its `Classified from:` instant."""
    changes: list[Change] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("| BC-"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) != 6:
            raise ValueError(f"register row needs 6 cells, got {len(cells)}: {line!r}")
        cid, kind, loaded_at, what, deploy, lane = cells
        if not _ID_RE.match(cid):
            raise ValueError(f"bad id {cid!r}")
        if kind not in (KIND_YES, KIND_NO):
            raise ValueError(f"{cid}: kind must be yes or no, got {kind!r}")
        if not loaded_at.startswith(PENDING_PREFIX):
            loaded_at = normalize_ts(loaded_at)
        changes.append(Change(cid, kind, loaded_at, what, normalize_ts(deploy) if deploy else "", lane))
    ids = [c.id for c in changes]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate ids in the register")
    match = _COVERAGE_RE.search(text)
    return changes, normalize_ts(match.group(1)) if match else None


def clock_start(changes: Iterable[Change], now: datetime | None = None) -> ClockStart | None:
    """The instant the count restarts from: the latest LOADED yes, or `now` while any yes is pending."""
    yes = [c for c in changes if c.kind == KIND_YES]
    if not yes:
        return None
    pending = [c for c in yes if c.pending]
    if pending:
        moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return ClockStart(moment.strftime("%Y-%m-%dT%H:%M:%SZ"), pending[-1], True)
    latest = max(yes, key=lambda c: (c.loaded_at, c.id))  # a tie goes to the later row
    return ClockStart(latest.loaded_at, latest, False)


def deploy_headings(deploys_text: str) -> list[tuple[str, str]]:
    """(normalised instant, heading text) for every dated `## ` heading, in file order."""
    return [(normalize_ts(f"{d} {t}Z"), f"{d} {t}Z{rest}") for d, t, rest in _HEADING_RE.findall(deploys_text)]


def _bodies(deploys_text: str) -> dict[str, str]:
    """Heading instant -> the entry's body (up to the next `## `). Two entries on one instant are concatenated."""
    out: dict[str, str] = {}
    matches = list(_HEADING_RE.finditer(deploys_text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(deploys_text)
        key = normalize_ts(f"{m.group(1)} {m.group(2)}Z")
        out[key] = out.get(key, "") + deploys_text[m.start():end]
    return out


def is_deploy_like(heading: str) -> bool:
    if not _DEPLOY_LIKE.search(heading):
        return False
    return not (_NO_DEPLOY.search(heading) and not _LOAD_WORDS.search(heading))


def candidates(changes: Sequence[Change], deploys_text: str, since: str) -> list[dict[str, str]]:
    """Deploy-like entries at or after `since` that no register row and no `betting change:` line classifies.

    A body tagged `betting change: yes` with no register row is listed too: it restarts the clock, so it needs
    its load time in the register.
    """
    referenced = {c.deploy for c in changes if c.deploy}
    bodies = _bodies(deploys_text)
    out = []
    seen: set[str] = set()
    for instant, heading in deploy_headings(deploys_text):
        if instant < since or instant in referenced or instant in seen or not is_deploy_like(heading):
            continue
        seen.add(instant)
        tag = _BODY_TAG.search(bodies.get(instant, ""))
        if tag and tag.group(1).lower() == KIND_NO:
            continue
        out.append({
            "deploy": instant,
            "heading": heading[:200],
            "why": "tagged yes in deploys.md but no register row (needs its load time)" if tag else "unclassified",
        })
    return out


def next_id(changes: Sequence[Change]) -> str:
    numbers = [int(_ID_RE.match(c.id).group(1)) for c in changes]
    return f"BC-{(max(numbers) + 1) if numbers else 1:03d}"


def format_row(change: Change) -> str:
    return (
        f"| {change.id} | {change.kind} | {change.loaded_at} | {_cell(change.what)} | {change.deploy} | "
        f"{_cell(change.lane)} |"
    )


def append_row(text: str, change: Change) -> str:
    """The register text with `change` added as the table's last row."""
    lines = text.splitlines()
    last = max((i for i, ln in enumerate(lines) if ln.strip().startswith("| BC-")), default=None)
    if last is None:
        try:
            last = lines.index(TABLE_RULE)
        except ValueError as exc:
            raise ValueError("the register has no table header") from exc
    lines.insert(last + 1, format_row(change))
    return "\n".join(lines) + "\n"


def replace_row(text: str, change: Change) -> str:
    lines = text.splitlines()
    hits = [i for i, ln in enumerate(lines) if ln.strip().startswith(f"| {change.id} |")]
    if len(hits) != 1:
        raise ValueError(f"{change.id}: expected exactly one row, found {len(hits)}")
    lines[hits[0]] = format_row(change)
    return "\n".join(lines) + "\n"


def _cst(stamp: str) -> str:
    moment = parse_utc(stamp)
    if moment is None:
        return stamp
    from zoneinfo import ZoneInfo

    local = moment.astimezone(ZoneInfo("America/Chicago"))
    return local.strftime("%Y-%m-%d %I:%M %p %Z").replace(" 0", " ")


def describe_clock(clock: ClockStart | None) -> str:
    if clock is None:
        return "CLOCK: no betting change in the register"
    c = clock.change
    if clock.pending:
        return (
            f"CLOCK: count is 0 -- {c.id} ({c.what}) is PENDING its load on {c.loaded_at[len(PENDING_PREFIX):]}. "
            f"Record the load with `betting_change.py resolve {c.id} --loaded-at <UTC>`."
        )
    return f"CLOCK: starts {clock.start} ({_cst(clock.start)}) at {c.id}: {c.what}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--register", default=str(REGISTER_PATH))
    parser.add_argument("--deploys", default=str(DEPLOYS_PATH))
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("clock", help="where the gate's clock starts")
    sub.add_parser("list", help="every row")
    sub.add_parser("candidates", help="deploys.md entries since coverage that nothing classifies")
    add = sub.add_parser("add", help="classify one deploys.md entry")
    add.add_argument("--kind", choices=(KIND_YES, KIND_NO), required=True)
    when = add.add_mutually_exclusive_group()
    when.add_argument("--loaded-at", help="UTC instant the running role picked the change up")
    when.add_argument("--pending", metavar="ROLES", help="not loaded yet; loads at these roles' next restart")
    add.add_argument("--what", required=True)
    add.add_argument("--deploy", default="", help="the deploys.md heading's instant, e.g. '2026-11-17 00:04:20Z'")
    add.add_argument("--lane", default="")
    res = sub.add_parser("resolve", help="record the load time of a pending row")
    res.add_argument("id")
    res.add_argument("--loaded-at", required=True)
    args = parser.parse_args(argv)

    register = Path(args.register)
    text = register.read_text(encoding="utf-8")
    changes, coverage = parse_register(text)

    if args.cmd == "clock":
        print(describe_clock(clock_start(changes)))
        return 0
    if args.cmd == "list":
        for c in changes:
            print(format_row(c))
        return 0
    if args.cmd == "candidates":
        if coverage is None:
            print("the register declares no `Classified from:` instant", file=sys.stderr)
            return 2
        found = candidates(changes, Path(args.deploys).read_text(encoding="utf-8"), coverage)
        for row in found:
            print(f"{row['deploy']}  {row['why']}: {row['heading']}")
        print(f"{len(found)} unclassified deploy entr{'y' if len(found) == 1 else 'ies'} since {coverage}")
        return 1 if found else 0
    if args.cmd == "add":
        if args.kind == KIND_YES and not (args.loaded_at or args.pending):
            parser.error("a yes needs --loaded-at or --pending")
        if args.pending:
            loaded_at = PENDING_PREFIX + _cell(args.pending).replace(" ", "")
        elif args.loaded_at or args.deploy:
            loaded_at = normalize_ts(args.loaded_at or args.deploy)
        else:
            parser.error("a no needs --deploy (or --loaded-at)")
        deploy = normalize_ts(args.deploy) if args.deploy else ""
        if deploy and deploy in {c.deploy for c in changes}:
            parser.error(f"deploys.md entry {deploy} is already classified")
        change = Change(next_id(changes), args.kind, loaded_at, _cell(args.what), deploy, _cell(args.lane))
        register.write_text(append_row(text, change), encoding="utf-8")
        print(format_row(change))
        print(describe_clock(clock_start([*changes, change])))
        return 0
    if args.cmd == "resolve":
        match = [c for c in changes if c.id == args.id]
        if not match or not match[0].pending:
            parser.error(f"{args.id} is not a pending row")
        old = match[0]
        new = Change(old.id, old.kind, normalize_ts(args.loaded_at), old.what, old.deploy, old.lane)
        register.write_text(replace_row(text, new), encoding="utf-8")
        print(format_row(new))
        print(describe_clock(clock_start([new if c.id == new.id else c for c in changes])))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
