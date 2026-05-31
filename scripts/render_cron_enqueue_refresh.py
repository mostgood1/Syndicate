from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request


def _coerce_base_url(explicit: str | None) -> str:
    value = str(explicit or "").strip()
    if value:
        return value.rstrip("/")
    env_base_url = str(os.environ.get("SYNDICATE_BASE_URL") or "").strip()
    if env_base_url:
        if not (env_base_url.startswith("http://") or env_base_url.startswith("https://")):
            env_base_url = f"https://{env_base_url}"
        return env_base_url.rstrip("/")
    host = str(os.environ.get("SYNDICATE_WEB_HOST") or "").strip()
    port = str(os.environ.get("SYNDICATE_WEB_PORT") or "").strip()
    if not host:
        raise ValueError("Missing SYNDICATE_BASE_URL or SYNDICATE_WEB_HOST (or pass --base-url).")
    if port:
        return f"http://{host}:{port}"
    return f"http://{host}"


def _build_payload(args: argparse.Namespace) -> dict[str, str]:
    payload = {
        "sports": args.sports,
        "phase": args.phase,
        "execution_mode": args.execution_mode,
        "regions": args.regions,
    }
    if bool(getattr(args, "skip_mirror", False)):
        payload["skip_mirror"] = True
    if bool(getattr(args, "mirror_only", False)):
        payload["mirror_only"] = True
    date_value = str(getattr(args, "date", "") or "").strip()
    if date_value:
        payload["date"] = date_value
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Render cron helper: enqueue Syndicate odds refresh through web API.")
    parser.add_argument("--base-url", default="", help="Optional explicit Syndicate base URL, e.g. https://syndicate.onrender.com. If omitted, uses SYNDICATE_BASE_URL then SYNDICATE_WEB_HOST/SYNDICATE_WEB_PORT.")
    parser.add_argument("--sports", default="all")
    parser.add_argument("--date", default="", help="Optional explicit refresh date (YYYY-MM-DD).")
    parser.add_argument("--phase", choices=("live", "pregame", "all"), default="all")
    parser.add_argument("--execution-mode", choices=("source", "ingest"), default="source")
    parser.add_argument("--regions", default="us")
    parser.add_argument("--skip-mirror", action="store_true", help="Skip mirror refresh before odds refresh.")
    parser.add_argument("--mirror-only", action="store_true", help="Only refresh mirrors and skip odds refresh.")
    parser.add_argument("--timeout-sec", type=float, default=180.0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    token = str(os.environ.get("ADMIN_TOKEN") or "").strip()
    if not token:
        raise SystemExit("Missing ADMIN_TOKEN environment variable.")

    try:
        base_url = _coerce_base_url(args.base_url)
    except ValueError as exc:
        raise SystemExit(str(exc))

    payload = _build_payload(args)
    endpoint = f"{base_url}/api/ops/odds-refresh/run?admin_token={token}"
    body = json.dumps(payload).encode("utf-8")

    if args.dry_run:
        print(json.dumps({"endpoint": endpoint, "payload": payload, "timeout_sec": args.timeout_sec}, indent=2))
        return 0

    request = urllib.request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(args.timeout_sec))) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            print(response_body)
    except urllib.error.HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
        print(error_text, file=sys.stderr)
        return int(exc.code or 1)
    except Exception as exc:
        print(f"Failed to enqueue refresh: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
