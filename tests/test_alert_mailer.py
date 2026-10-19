"""scripts/alert_mailer.py -- config, outbox, coalescing, rate limit, failure keeps the message."""

from __future__ import annotations

import datetime as dt
import smtplib

from scripts import alert_mailer as am

NOW = dt.datetime(2026, 10, 19, 22, 0, tzinfo=dt.timezone.utc)
CONFIG = {"enabled": True, "reason": "", "user": "a@gmail.com", "password": "abcdabcdabcdabcd",
          "to": "a@gmail.com", "host": "smtp.gmail.com", "port": 587, "path": "/x"}


class Recorder:
    def __init__(self, fail: bool = False):
        self.sent: list[tuple[str, str]] = []
        self.fail = fail

    def __call__(self, config, subject, body):
        if self.fail:
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.sent.append((subject, body))


def _queue(*items):
    box: dict = {}
    for kind, subject in items:
        box = am.enqueue(box, kind=kind, subject=subject, body=f"body of {subject}", now=NOW)
    return box


def test_config_off_without_file_or_password(tmp_path):
    assert am.load_config(tmp_path)["enabled"] is False
    (tmp_path / am.CONFIG_NAME).write_text("SYNDICATE_ALERT_SMTP_USER=a@gmail.com\n", encoding="utf-8")
    cfg = am.load_config(tmp_path)
    assert cfg["enabled"] is False and "PASSWORD" in cfg["reason"]
    (tmp_path / am.CONFIG_NAME).write_text(
        "SYNDICATE_ALERT_SMTP_USER=a@gmail.com\nSYNDICATE_ALERT_SMTP_PASSWORD='abcd efgh ijkl mnop'\n", encoding="utf-8")
    cfg = am.load_config(tmp_path)
    assert cfg["enabled"] is True and cfg["to"] == "a@gmail.com" and cfg["password"] == "abcdefghijklmnop"


def test_describe_never_carries_the_password():
    shown = am.describe(CONFIG)
    assert "abcd" not in repr(shown) and shown["password_set"] is True


def test_one_email_per_kind_coalesces_everything_queued():
    box = _queue(("alert", "kill switch"), ("alert", "heartbeat"), ("digest", "daily digest"))
    rec = Recorder()
    box, summary = am.flush(box, CONFIG, NOW, sender=rec)
    assert len(rec.sent) == 2
    alert_subject, alert_body = rec.sent[0]          # alerts go first
    assert "2 alerts" in alert_subject and "kill switch" in alert_body and "heartbeat" in alert_body
    assert box["queue"] == [] and summary["queued"] == 0


def test_hourly_cap_holds_messages_for_later():
    box = _queue(("alert", "x"))
    box["sent_at"] = [(NOW - dt.timedelta(minutes=m)).isoformat() for m in range(am.MAX_SENDS_PER_HOUR)]
    rec = Recorder()
    box, summary = am.flush(box, CONFIG, NOW, sender=rec)
    assert rec.sent == [] and summary["held"] == 1 and len(box["queue"]) == 1
    # an hour later the cap has rolled off and it goes
    box, summary = am.flush(box, CONFIG, NOW + dt.timedelta(minutes=61), sender=rec)
    assert len(rec.sent) == 1 and box["queue"] == []


def test_a_failed_send_keeps_the_message_and_records_the_error():
    box = _queue(("alert", "x"))
    box, summary = am.flush(box, CONFIG, NOW, sender=Recorder(fail=True))
    assert len(box["queue"]) == 1 and summary["failed"] and "abcd" not in repr(summary)
    assert box["last_error"]["kind"] == "alert"


def test_disabled_config_queues_without_sending():
    rec = Recorder()
    box, summary = am.flush(_queue(("alert", "x")), {**CONFIG, "enabled": False, "reason": "no file"}, NOW, sender=rec)
    assert rec.sent == [] and len(box["queue"]) == 1


def test_day_old_messages_expire():
    box = am.enqueue({}, kind="alert", subject="old", body="b", now=NOW - dt.timedelta(hours=25))
    rec = Recorder()
    box, summary = am.flush(box, CONFIG, NOW, sender=rec)
    assert rec.sent == [] and summary["expired"] == 1 and box["queue"] == []


def test_deliver_round_trips_through_disk(tmp_path):
    settings = am.lp.Settings(home=tmp_path)
    (tmp_path / am.CONFIG_NAME).write_text(
        "SYNDICATE_ALERT_SMTP_USER=a@gmail.com\nSYNDICATE_ALERT_SMTP_PASSWORD=abcdabcdabcdabcd\n", encoding="utf-8")
    rec = Recorder()
    summary = am.deliver(settings, [{"kind": "alert", "subject": "s", "body": "b"}], NOW, sender=rec)
    assert summary["sent"] and len(rec.sent) == 1
    log = (settings.logs_dir / am.LOG_NAME).read_text(encoding="utf-8")
    assert "EMAIL_SENT" in log and "abcd" not in log
