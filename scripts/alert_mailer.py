"""Email delivery for the local fleet's alerts and daily digest (lane `execution-alerts`).

    python3 scripts/alert_mailer.py status           # is email configured? what is queued?
    python3 scripts/alert_mailer.py test             # queue + send one test email now
    python3 scripts/alert_mailer.py flush            # send whatever is queued

WHY EMAIL. Live money runs unattended on this machine, and the watchdog's only
channel was a Windows toast, which reaches nobody away from the desk. The user
chose Gmail email on 2026-10-19 (after removing an ntfy push on 10-14).

CONFIG lives in `<home>/alerts.env` (KEY=VALUE, chmod 600), written BY THE
USER, never by a session, and kept out of `local_production.env` so the SMTP
password never enters a role's environment:

    SYNDICATE_ALERT_SMTP_USER=you@gmail.com
    SYNDICATE_ALERT_SMTP_PASSWORD=<16-character Gmail app password>
    SYNDICATE_ALERT_EMAIL_TO=you@gmail.com        # optional, default = SMTP user
    SYNDICATE_ALERT_SMTP_HOST=smtp.gmail.com      # optional
    SYNDICATE_ALERT_SMTP_PORT=587                 # optional (STARTTLS)

No file, or no password -> email is OFF and `status` says so. Nothing here ever
prints or logs the password, or any substring of it.

DELIVERY. Messages go into an OUTBOX (`<home>/run/alert_outbox.json`) and each
flush sends what is queued, so an SMTP outage delays an alert, it does not drop
it. Rate limit and coalescing, so a flapping check cannot flood the inbox:
  * one flush sends at most ONE email per kind (`alert`, `digest`): everything
    queued of that kind is joined into it;
  * at most MAX_SENDS_PER_HOUR emails per rolling hour; the rest wait;
  * a message older than MAX_QUEUED_SECONDS is dropped (logged) -- a day-old
    alert is history, and the digest carries it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import smtplib
import socket
import sys
import uuid
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import local_production as lp  # noqa: E402

CONFIG_NAME = "alerts.env"
OUTBOX_NAME = "alert_outbox.json"
LOG_NAME = "alert_mailer.log"
MAX_SENDS_PER_HOUR = 6
MAX_QUEUED_SECONDS = 24 * 3600
MAX_OUTBOX = 200
SMTP_TIMEOUT_SECONDS = 20
SUBJECT_PREFIX = "[Syndicate]"


def config_path(home: Path) -> Path:
    return home / CONFIG_NAME


def load_config(home: Path) -> dict[str, Any]:
    """The SMTP settings, plus `enabled` and a `reason` when it is not.

    `password` is returned for the sender only; `describe` is what may be shown.
    """
    path = config_path(home)
    raw = lp.parse_env_file(path) if path.is_file() else {}
    user = str(raw.get("SYNDICATE_ALERT_SMTP_USER") or "").strip()
    password = str(raw.get("SYNDICATE_ALERT_SMTP_PASSWORD") or "").replace(" ", "").strip()
    to = str(raw.get("SYNDICATE_ALERT_EMAIL_TO") or user).strip()
    host = str(raw.get("SYNDICATE_ALERT_SMTP_HOST") or "smtp.gmail.com").strip()
    try:
        port = int(raw.get("SYNDICATE_ALERT_SMTP_PORT") or 587)
    except ValueError:
        port = 587
    if not path.is_file():
        reason = f"no {path}"
    elif not user or not password:
        reason = f"{path} lacks SYNDICATE_ALERT_SMTP_USER or SYNDICATE_ALERT_SMTP_PASSWORD"
    elif "@" not in to:
        reason = "no recipient (SYNDICATE_ALERT_EMAIL_TO)"
    else:
        reason = ""
    return {"enabled": not reason, "reason": reason, "user": user, "password": password,
            "to": to, "host": host, "port": port, "path": str(path)}


def describe(config: dict[str, Any]) -> dict[str, Any]:
    """Config safe to print: no password, not even its length."""
    return {"enabled": config["enabled"], "reason": config["reason"], "to": config["to"],
            "from": config["user"], "host": config["host"], "port": config["port"],
            "password_set": bool(config.get("password"))}


def smtp_send(config: dict[str, Any], subject: str, body: str) -> None:
    message = EmailMessage()
    message["From"] = config["user"]
    message["To"] = config["to"]
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(config["host"], config["port"], timeout=SMTP_TIMEOUT_SECONDS) as client:
        client.starttls()
        client.login(config["user"], config["password"])
        client.send_message(message)


# --------------------------------------------------------------------------
# outbox (pure functions over a dict, so the tests need no disk or network)
# --------------------------------------------------------------------------


def enqueue(outbox: dict[str, Any], *, kind: str, subject: str, body: str, now: dt.datetime) -> dict[str, Any]:
    queue = list(outbox.get("queue") or [])
    queue.append({"id": uuid.uuid4().hex[:12], "kind": kind, "subject": subject, "body": body,
                  "queued_at": now.isoformat()})
    dropped = max(0, len(queue) - MAX_OUTBOX)
    out = dict(outbox)
    out["queue"] = queue[dropped:]
    if dropped:
        out["dropped_overflow"] = int(out.get("dropped_overflow") or 0) + dropped
    return out


def _compose(kind: str, items: list[dict[str, Any]]) -> tuple[str, str]:
    if len(items) == 1:
        return f"{SUBJECT_PREFIX} {items[0]['subject']}", items[0]["body"]
    subject = f"{SUBJECT_PREFIX} {len(items)} {kind}s: " + " / ".join(i["subject"] for i in items[:3])
    if len(items) > 3:
        subject += " / ..."
    parts = []
    for item in items:
        parts.append(f"=== {item['subject']}  (queued {item['queued_at']})\n{item['body']}")
    return subject[:240], "\n\n".join(parts)


def flush(outbox: dict[str, Any], config: dict[str, Any], now: dt.datetime,
          sender: Callable[[dict[str, Any], str, str], None] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """(new outbox, summary). Sends at most one email per kind, within the hourly cap."""
    sender = sender or smtp_send  # looked up at call time, so a drill can swap the transport
    out = dict(outbox)
    sent_at = [s for s in (out.get("sent_at") or []) if (now - dt.datetime.fromisoformat(s)).total_seconds() < 3600]
    queue, expired = [], []
    for item in out.get("queue") or []:
        age = (now - dt.datetime.fromisoformat(item["queued_at"])).total_seconds()
        (expired if age > MAX_QUEUED_SECONDS else queue).append(item)
    summary: dict[str, Any] = {"sent": [], "failed": [], "expired": len(expired), "held": 0,
                               "enabled": config["enabled"], "reason": config["reason"]}
    if config["enabled"]:
        for kind in sorted({i["kind"] for i in queue}, key=lambda k: (k != "alert", k)):
            if len(sent_at) >= MAX_SENDS_PER_HOUR:
                summary["held"] = len(queue)
                break
            items = [i for i in queue if i["kind"] == kind]
            subject, body = _compose(kind, items)
            try:
                sender(config, subject, body)
            except (smtplib.SMTPException, OSError, socket.timeout) as exc:
                # The exception text can echo the server's reply, never our password; keep it short anyway.
                summary["failed"].append({"kind": kind, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
                continue
            sent_at.append(now.isoformat())
            ids = {i["id"] for i in items}
            queue = [i for i in queue if i["id"] not in ids]
            summary["sent"].append({"kind": kind, "subject": subject, "items": len(items)})
    out["queue"] = queue
    out["sent_at"] = sent_at
    if summary["sent"]:
        out["last_sent_at"] = now.isoformat()
    if summary["failed"]:
        out["last_error"] = {"at": now.isoformat(), **summary["failed"][-1]}
    summary["queued"] = len(queue)
    return out, summary


# --------------------------------------------------------------------------
# disk
# --------------------------------------------------------------------------


def outbox_path(settings: lp.Settings) -> Path:
    return settings.run_dir / OUTBOX_NAME


def load_outbox(settings: lp.Settings) -> dict[str, Any]:
    try:
        payload = json.loads(outbox_path(settings).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def save_outbox(settings: lp.Settings, outbox: dict[str, Any]) -> None:
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    path = outbox_path(settings)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(outbox, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def log_line(settings: lp.Settings, now: dt.datetime, text: str) -> None:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    with (settings.logs_dir / LOG_NAME).open("a", encoding="utf-8") as handle:
        handle.write(f"{now.isoformat()} {text}\n")


def deliver(settings: lp.Settings, messages: list[dict[str, str]], now: dt.datetime,
            sender: Callable[[dict[str, Any], str, str], None] | None = None) -> dict[str, Any]:
    """Queue `messages` ({kind, subject, body}) and flush. The one entry point callers use."""
    outbox = load_outbox(settings)
    for message in messages:
        outbox = enqueue(outbox, kind=message["kind"], subject=message["subject"], body=message["body"], now=now)
    config = load_config(settings.home)
    outbox, summary = flush(outbox, config, now, sender=sender)
    save_outbox(settings, outbox)
    for item in summary["sent"]:
        log_line(settings, now, f"EMAIL_SENT kind={item['kind']} items={item['items']} subject={item['subject']!r}")
    for item in summary["failed"]:
        log_line(settings, now, f"EMAIL_FAILED kind={item['kind']} {item['error']}")
    if summary["expired"]:
        log_line(settings, now, f"EMAIL_EXPIRED n={summary['expired']}")
    if messages and not config["enabled"]:
        log_line(settings, now, f"EMAIL_OFF queued={summary['queued']} reason={config['reason']}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("status", "test", "flush"))
    parser.add_argument("--home", help="local production home (default: as local_production.py)")
    args = parser.parse_args(argv)
    home = Path(args.home).expanduser().resolve() if args.home else lp.default_home()
    settings = lp.Settings(home=home)
    now = dt.datetime.now(dt.timezone.utc)
    if args.command == "status":
        outbox = load_outbox(settings)
        print(json.dumps({"config": describe(load_config(home)), "queued": len(outbox.get("queue") or []),
                          "last_sent_at": outbox.get("last_sent_at"), "last_error": outbox.get("last_error")}, indent=2))
        return 0
    messages = []
    if args.command == "test":
        messages.append({"kind": "alert", "subject": "test email from the fleet watchdog",
                         "body": f"If you can read this, Syndicate alerts reach you.\nSent {now.isoformat()} "
                                 f"from {socket.gethostname()}."})
    summary = deliver(settings, messages, now)
    print(json.dumps(summary, indent=2))
    return 0 if not summary["failed"] and summary["enabled"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
