"""Guard against timezone-ambiguous "today" in slate-date code.

Syndicate's slate date is CENTRAL, always. `syndicate/features/shared/timezone.py`
exists to say so explicitly via `central_today()` / `central_today_iso()`, which
resolve through ZoneInfo("America/Chicago") and do not care what timezone the
process happens to be running in.

`date.today()` and `datetime.utcnow().date()` do NOT do that. They resolve
against the process timezone, so they silently become UTC anywhere TZ is not
applied -- and UTC crosses midnight at 19:00 CDT, five hours before the slate
does. Every evening, those calls start answering "tomorrow".

This is not hypothetical. Measured 2026-07-25/26:

- `soccer.sources.default_week` used `date_cls.today()`. Once that read
  2026-07-26, the current matchweek (17: 07-22..07-25) failed its containment
  check, execution fell through to the "first week starting on or after today"
  branch, and it returned week 18. **Live MLS games were pinned a week into the
  future while they were in progress.** Verified directly: central_today
  2026-07-25 -> week 17, 2026-07-26 -> week 18.
- The same evening the curated board kept resolving to 2026-07-26 and finding
  nothing, and hours were spent chasing writes, hosts, deferrals and
  classification before the date itself was suspected.

So this is a ratchet, not a style preference. The allowlist below records the
call sites that remain; it may shrink and must never grow. A new entry means an
evening-only, timezone-dependent bug has just been added, and those are
extremely expensive to diagnose because everything looks correct until 19:00.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Calls that resolve "now"/"today" against the PROCESS timezone rather than
# explicitly against Central.
AMBIGUOUS_PATTERNS = (
    r"(?<![\w.])date\.today\(\)",
    r"(?<![\w.])date_cls\.today\(\)",
    r"(?<![\w.])datetime\.today\(\)",
    r"utcnow\(\)\.date\(\)",
    r"utcnow\(\)\.strftime\(\s*[\"']%Y-%m-%d",
    r"Timestamp\.utcnow\(\)\.date\(\)",
)

SEARCH_ROOTS = ("syndicate", "pipeline")

# Known remaining call sites, as "<relative path>": <count>.
#
# MAY SHRINK, MUST NEVER GROW. Each is a place where an evening becomes
# tomorrow. If a change makes this test fail, fix the call site to use
# central_today()/central_today_iso() rather than adding it here.
ALLOWLIST: dict[str, int] = {
    # Recap "anchor" fallbacks, used ONLY when a sport has no artifact dates at
    # all. A one-day skew degrades an already-empty view rather than mis-dating
    # live games, so these are genuinely low-stakes -- but still worth fixing.
    "syndicate/features/nba/betting_recap.py": 1,
    "syndicate/features/nhl/betting_recap.py": 1,
    # ONNX feature builder: `date_str` is normally supplied by the caller; these
    # are the no-argument fallback and a training-cutoff normalisation.
    "syndicate/features/shared/basketball_props_onnx.py": 2,
    # Accuracy report's "until" bound -- an analysis window, not a slate date.
    "syndicate/features/mlb/live_lens_daily_accuracy.py": 1,
}


def _iter_python_files():
    for root in SEARCH_ROOTS:
        for path in (REPO_ROOT / root).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path


def _code_only(text: str) -> str:
    """Source with COMMENTS removed, string literals kept.

    Two mistakes were made building this and both are worth recording, because
    they are opposite failure modes of the same check:

    1. Scanning raw text failed on the guard's own explanatory comments -- every
       place the fix was DOCUMENTED counted as a place the bug existed. A check
       that cannot tell code from prose about code is worse than none, since the
       natural way to silence it is to delete the explanation.
    2. Fixing that by stripping comments AND strings introduced a false
       NEGATIVE: `utcnow().strftime("%Y-%m-%d")` stopped matching once the format
       string was gone, so four real call sites silently read as clean. A guard
       that under-reports is the more dangerous of the two.

    Comments removed, strings kept. Format-string patterns therefore still
    match, and prose in `#` comments does not.
    """
    import io
    import tokenize

    # Comment spans are BLANKED IN PLACE rather than the source being rebuilt
    # from tokens. Rebuilding by joining token strings destroys adjacency --
    # `date.today()` becomes `date . today ( )` -- so every pattern here stops
    # matching and the guard silently detects nothing while all its tests pass.
    # That was the third mistake in this one helper, and the only one that made
    # the check completely inert, so the in-place approach is deliberate.
    lines = text.splitlines(keepends=True)
    try:
        comments = [
            token for token in tokenize.generate_tokens(io.StringIO(text).readline)
            if token.type == tokenize.COMMENT
        ]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: fall back to raw text rather than skipping it, so a
        # syntax error cannot become a way to smuggle a call site past the guard.
        return text
    for token in comments:
        row = token.start[0] - 1
        if 0 <= row < len(lines):
            start_col, end_col = token.start[1], token.end[1]
            line = lines[row]
            lines[row] = line[:start_col] + " " * (end_col - start_col) + line[end_col:]
    return "".join(lines)


def _ambiguous_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in _iter_python_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        code = _code_only(text)
        hits = sum(len(re.findall(pattern, code)) for pattern in AMBIGUOUS_PATTERNS)
        if hits:
            counts[path.relative_to(REPO_ROOT).as_posix()] = hits
    return counts


class SlateDateTimezoneDisciplineTests(unittest.TestCase):
    def test_no_new_timezone_ambiguous_date_calls(self) -> None:
        found = _ambiguous_counts()
        new_files = sorted(set(found) - set(ALLOWLIST))
        self.assertEqual(
            new_files,
            [],
            "timezone-ambiguous 'today' introduced in:\n  "
            + "\n  ".join(f"{name} ({found[name]}x)" for name in new_files)
            + "\n\nUse central_today() / central_today_iso() from "
            "syndicate.features.shared.timezone. date.today() follows the PROCESS "
            "timezone, so it answers 'tomorrow' after 19:00 CDT -- that is how live "
            "MLS games got pinned to next week (see this module's docstring).",
        )

    def test_allowlisted_counts_do_not_grow(self) -> None:
        found = _ambiguous_counts()
        grew = {
            name: (ALLOWLIST[name], found[name])
            for name in ALLOWLIST
            if name in found and found[name] > ALLOWLIST[name]
        }
        self.assertEqual(grew, {}, f"more ambiguous date calls added to already-known files: {grew}")

    def test_allowlist_has_no_stale_entries(self) -> None:
        # Keeps the ratchet honest: a fixed file must leave the allowlist, or
        # the list stops describing reality and quietly permits regressions.
        found = _ambiguous_counts()
        stale = sorted(name for name in ALLOWLIST if name not in found)
        self.assertEqual(stale, [], f"allowlist entries no longer needed, remove them: {stale}")

    def test_soccer_week_resolution_uses_central(self) -> None:
        # The specific regression: live games pinned to next week. Guarded
        # directly as well as by the sweep, because this one had a user-visible
        # symptom and deserves a named test.
        source = (REPO_ROOT / "syndicate" / "features" / "soccer" / "sources.py").read_text(encoding="utf-8")
        default_week = source[source.index("def default_week("):]
        default_week = default_week[: default_week.index("\ndef ")]
        # Code only: the function's comment deliberately names date_cls.today()
        # to explain what went wrong, and matching prose would fail here too.
        code = _code_only(default_week)
        self.assertIn("central_today_iso", code)
        self.assertNotIn("date_cls.today", code)
