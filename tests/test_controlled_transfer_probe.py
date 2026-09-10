"""The probe must record the bandwidth bucket its transfer lands IN.

A bandwidth bucket is labelled by its hour's START
(`.syndicate/findings_2026-09-10_spike_crossing_and_labelling.md`). Until
2026-09-10 the probe recorded the hour AFTER as `bucket_label` and told the
reader to wait for that label + 70 minutes, an hour later than needed. The
label now comes from the reader's `_bucket_for`, so the two scripts cannot
disagree about it again -- the second test pins that it is the SAME function,
not a copy that happens to agree today.
"""
import datetime as dt

from scripts import controlled_transfer_probe as probe
from scripts import controlled_transfer_read as reader


def test_the_probe_labels_its_hour_by_the_hours_START():
    assert probe._bucket_label(dt.datetime(2026, 9, 9, 0, 6, 27)) == "2026-09-09T00:00:00Z"
    assert probe._bucket_label(dt.datetime(2026, 9, 9, 23, 59, 59)) == "2026-09-09T23:00:00Z"


def test_the_probe_uses_the_readers_definition_not_its_own(monkeypatch):
    monkeypatch.setattr(reader, "_bucket_for", lambda when: "SENTINEL:" + when)

    assert probe._bucket_label(dt.datetime(2026, 9, 9, 0, 6, 27)) == "SENTINEL:2026-09-09T00:06:27Z"
