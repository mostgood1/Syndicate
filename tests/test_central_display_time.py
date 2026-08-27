"""Every time a person reads is CENTRAL [USER DECISION 2026-08-25].

The live portfolio rendered `submitted_at[11:19]` -- a raw slice of the stored
UTC string -- so an order placed at 6:15 PM Central appeared as `23:15:05`.
Unlabelled, unconverted, five hours wrong, and sitting in the column a person
uses to reconcile against the venue's own screen.
"""

from __future__ import annotations


def test_a_stored_utc_stamp_renders_as_the_central_clock():
    """The exact row from the 2026-08-25 ledger."""
    from syndicate.features.shared.timezone import central_clock

    assert central_clock("2026-08-25T23:15:05Z") == "18:15:05"
    assert central_clock("2026-08-25T23:15:05Z", with_date=True) == "2026-08-25 18:15:05"


def test_the_central_DATE_can_differ_from_the_utc_date():
    """The half of this that is not cosmetic. A 7pm Central first pitch is
    already the NEXT UTC day, so a page showing the UTC date puts an evening
    game on tomorrow's slate -- the same failure `central_date_from_iso`
    documents for WNBA card filtering."""
    from syndicate.features.shared.timezone import central_clock

    assert central_clock("2026-08-26T00:15:05Z", with_date=True) == "2026-08-25 19:15:05"


def test_a_naive_stamp_is_read_as_utc_not_as_local():
    """Everything in this repo that writes a naive stamp uses
    `datetime.now(timezone.utc)` or `time.time()`. Reading one as local would
    shift it by five hours in the WRONG direction, which is worse than the bug
    being fixed because it would look plausible."""
    from syndicate.features.shared.timezone import central_clock

    assert central_clock("2026-08-25T23:15:05") == "18:15:05"


def test_an_unreadable_stamp_renders_BLANK_rather_than_a_guess():
    """`str(None)[11:19]` is how the old slice failed -- silently, into
    something that looked like a time. A blank cell is honest."""
    from syndicate.features.shared.timezone import central_clock

    for value in (None, "", "nonsense", "2026-13-45T99:99:99Z", 12345):
        assert central_clock(value) == "", value


def test_an_epoch_stamp_converts_too():
    """`fetched_at` is stored as a float epoch, not an ISO string."""
    from syndicate.features.shared.timezone import (
        central_clock_from_epoch,
        central_datetime_from_epoch,
    )

    epoch = 1787698739.09
    assert central_clock_from_epoch(epoch) == central_datetime_from_epoch(epoch).strftime("%H:%M:%S")
    assert central_clock_from_epoch("nonsense") == ""


def test_the_filters_are_registered_on_the_app():
    """Registered once, centrally, rather than converted per template. The bug
    was a template doing its own time arithmetic; a filter is what stops the
    next one from doing that too."""
    from syndicate.app import app

    assert "central" in app.jinja_env.filters
    assert "central_epoch" in app.jinja_env.filters
    rendered = app.jinja_env.from_string("{{ x|central }}").render(x="2026-08-25T23:15:05Z")
    assert rendered == "18:15:05"


def test_no_user_facing_template_slices_a_raw_timestamp():
    """THE SHAPE OF THE BUG, pinned so it cannot come back by hand.

    `{{ o.get('submitted_at')[11:19] }}` renders whatever zone the string was
    stored in and labels it nothing. Any template needing a clock must go
    through the filter.
    """
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "syndicate" / "templates"
    # A slice starting at 11 is the ISO time-of-day; that is the tell.
    slicer = re.compile(r"\[11:\d+\]")
    offenders = []
    for path in sorted(root.glob("*.html")):
        for number, line in enumerate(path.read_text(errors="ignore").splitlines(), start=1):
            if line.lstrip().startswith("{#"):
                continue
            if slicer.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()[:80]}")
    assert not offenders, "use the |central filter:\n  " + "\n  ".join(offenders)
