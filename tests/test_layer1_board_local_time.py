"""`#354` -- kickoff times render in the viewer's zone, and the parse forces UTC.

THIS TEST EXECUTES THE JAVASCRIPT. It does not grep for it.

`#350` is the standing reason: a template that USED `projAge`/`projStale` without
declaring them passed every substring assertion in `test_projection_age.py` and
would have thrown `ReferenceError` on first paint, breaking the whole board. A
substring assertion confirms a token EXISTS and says nothing about whether it
WORKS. So the helpers are pulled out of the template and run under node against
real payload timestamps.

THE BUG THIS GUARDS
-------------------
The board carries NAIVE timestamps -- "2026-08-15T17:30:00", no trailing Z, no
offset -- and per ES2015 an offset-less date-TIME is parsed as LOCAL time. So the
obvious `new Date(g.start_time_utc)` shifts every kickoff by the viewer's offset
and produces times that look entirely plausible: that La Liga match would read
5:30pm to a Chicago viewer rather than 12:30pm. Nothing about the rendered board
would look wrong. That is precisely the failure mode that had me calling 8:20pm
Pacific games "over" earlier in this session, so it gets an executing test rather
than a hopeful one.

The MLS case is the second half of it: a kickoff at 2026-08-16T02:30Z is a
Friday-night game to everyone watching it, so the DATE bucket has to come from
the local calendar day too, not `start_time_utc.slice(0, 10)`.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess

import pytest

_TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "syndicate" / "templates" / "shared" / "layer1_board.html"

# Everything from the first time helper to the one that follows them. Sliced by
# name rather than line number so an unrelated edit above does not silently
# re-point this at the wrong block.
_START = "  function parseUtc(iso) {"
_END = "  function viewerZone()"


def _helper_source() -> str:
    html = _TEMPLATE.read_text(encoding="utf-8")
    start = html.find(_START)
    end = html.find(_END)
    assert start != -1, "parseUtc is gone from the template"
    assert end > start, "viewerZone no longer follows the time helpers -- fix the slice bounds"
    return html[start:end]


def _run_js(body: str, tz: str = "America/Chicago") -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - CI images without node
        pytest.skip("node is not available to execute the template helpers")
    env = dict(os.environ, TZ=tz)
    proc = subprocess.run(
        [node, "-e", _helper_source() + "\n" + body],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed: {proc.stderr.strip()}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_naive_timestamps_are_parsed_as_utc_not_local():
    # THE load-bearing assertion. A naive "17:30:00" must stay 17:30 UTC. Parsed
    # as local in Chicago it becomes 22:30Z and every kickoff on the board slides
    # five hours in a direction that still looks like a plausible start time.
    out = _run_js(
        'console.log(JSON.stringify({'
        '  naive: parseUtc("2026-08-15T17:30:00").getUTCHours(),'
        '  suffixed: parseUtc("2026-08-15T17:30:00Z").getUTCHours(),'
        '  spaced: parseUtc("2026-08-15 17:30:00").getUTCHours(),'
        '  offset: parseUtc("2026-08-15T13:30:00-04:00").getUTCHours()'
        '}));'
    )
    assert out["naive"] == 17, "naive timestamp was parsed as local -- every kickoff is shifted"
    assert out["suffixed"] == 17, "an already-Z timestamp must not be corrupted"
    assert out["spaced"] == 17
    assert out["offset"] == 17, "an explicit offset must be honoured, not overwritten with Z"


def test_kickoffs_render_in_the_viewers_zone():
    out = _run_js(
        'console.log(JSON.stringify({'
        '  laliga: timeLabel(parseUtc("2026-08-15T17:30:00")),'
        '  mls: timeLabel(parseUtc("2026-08-15T23:30:00")),'
        '  championship: timeLabel(parseUtc("2026-08-15T11:30:00")),'
        '  midnight: timeLabel(parseUtc("2026-08-16T05:00:00")),'
        '  noon: timeLabel(parseUtc("2026-08-15T17:00:00"))'
        '}));'
    )
    # 17:30Z is 12:30pm Central, NOT "17:30Z" as the board used to print.
    assert out["laliga"] == "12:30p"
    assert out["mls"] == "6:30p"
    assert out["championship"] == "6:30a"
    # 12-hour wrap in both directions -- 0 must render as 12, not 0.
    assert out["midnight"] == "12:00a"
    assert out["noon"] == "12:00p"


def test_a_late_kickoff_buckets_on_the_local_day():
    # 02:30Z Sunday is a Saturday-night MLS game in every US zone. Bucketing on
    # the UTC date would file it a day late and put it under the wrong header.
    out = _run_js(
        'console.log(JSON.stringify({'
        '  late: localDateKey(parseUtc("2026-08-16T02:30:00")),'
        '  utc_slice: "2026-08-16T02:30:00".slice(0, 10),'
        '  early: localDateKey(parseUtc("2026-08-15T11:30:00")),'
        '  day: dayLabel(parseUtc("2026-08-16T02:30:00"))'
        '}));'
    )
    assert out["late"] == "2026-08-15"
    assert out["late"] != out["utc_slice"], "local bucketing agrees with the UTC slice -- the test proves nothing"
    assert out["early"] == "2026-08-15"
    assert out["day"] == "Sat 8/15"


def test_bad_input_does_not_throw():
    # A card with no kickoff must render without a time, not take the board down.
    out = _run_js(
        'console.log(JSON.stringify({'
        '  none: parseUtc(null), empty: parseUtc(""), junk: parseUtc("not a date"),'
        '  label: timeLabel(null), key: localDateKey(null)'
        '}));'
    )
    assert out["none"] is None and out["empty"] is None and out["junk"] is None
    assert out["label"] == "" and out["key"] == ""


def test_the_board_no_longer_prints_a_utc_clock():
    html = _TEMPLATE.read_text(encoding="utf-8")
    assert 'slice(11, 16) + "Z"' not in html, "the UTC kickoff render is still in the template"
    assert "timeLabel(parseUtc(g.start_time_utc))" in html


def test_helpers_are_declared_before_the_render_path_uses_them():
    # The `#350` rule: assert on binding and ordering, not on text. Each of these
    # is referenced from cardHtml/groupedHtml/renderMeta, which run on first paint.
    html = _TEMPLATE.read_text(encoding="utf-8")
    for name in ("parseUtc", "timeLabel", "dayLabel", "localDateKey", "viewerZone", "groupedHtml", "leagueLabel"):
        decl = html.find("function " + name)
        assert decl != -1, f"{name} is never declared -- this is the ReferenceError"
        call = html.find(name + "(", decl + len("function " + name))
        assert call != -1, f"{name} is declared but never called -- dead helper"
