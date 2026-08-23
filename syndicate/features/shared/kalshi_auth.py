"""Signed requests to Kalshi -- the prerequisite for placing an order.

Everything Syndicate reads from Kalshi today is public and unauthenticated.
Placing an order is not: Kalshi authenticates with an API key ID plus an
RSA-PSS signature over each individual request, so there is no "log in once"
step and no bearer token to hold. Every call is signed or it is rejected.

--------------------------------------------------------------------------
THIS MODULE CAN CREATE POSITIONS. IT DEFAULTS TO BEING UNABLE TO.
--------------------------------------------------------------------------

The read-only client can be wrong and cost us a bad number. This one can be
wrong and cost money. So the safety is structural rather than procedural:

- **No credential, no client.** `load_credentials()` returns a NAMED refusal --
  `no_api_key_id`, `no_private_key`, `unreadable_private_key`, `no_cryptography`
  -- never a half-configured object. A signer that exists but cannot sign would
  fail at the submit call, which is the worst possible place to discover it.
- **The signature and the URL are produced TOGETHER** by `signed_request`, and
  the path is derived from the URL rather than passed alongside it. The classic
  failure of this scheme is signing one path and sending another: the server
  returns a bare 401 and every plausible cause -- clock skew, wrong key, wrong
  host -- looks identical from the outside.
- **Nothing here places an order.** This module signs and sends; the decision to
  send anything that creates a position lives behind `kalshi_execution`'s caps
  and kill switch. Separated so that reading account state can never be one
  typo'd argument away from writing to it.

--------------------------------------------------------------------------
UNVERIFIED, AND SHAPED AROUND THAT -- AGAIN
--------------------------------------------------------------------------

The agent proxy 403s CONNECT to every Kalshi host, so this was written without
calling the API, exactly like `kalshi_client` was. That module's first live run
corrected 10 of 17 field names and a 100x price error, so the assumptions here
are again in ONE place (`_TIMESTAMP_UNIT`, `_SIGNED_PATH_INCLUDES_PREFIX`,
`_HEADER_*`) and `probe_auth()` reports what came back instead of parsing it.

The parts that do NOT depend on the endpoint -- that a signature verifies
against its public key, that the signed string is built from the path actually
requested, that a query string is excluded -- are unit-tested against a
generated keypair and are true regardless of what Kalshi returns.

--------------------------------------------------------------------------
CREDENTIALS
--------------------------------------------------------------------------

`KALSHI_API_KEY_ID` and `KALSHI_PRIVATE_KEY` (the PEM, newlines allowed as
literal `\\n`) belong in the Render dashboard. Not in `render.yaml` -- that
would put a private key in git AND fire `blueprint_sync` (`#284`). Not in chat.

The key ID pasted into a session transcript on 2026-08-23 should be treated as
disclosed and rotated before this module is ever pointed at a funded account.
"""

from __future__ import annotations

import base64
import json
import re
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

__all__ = [
    "load_credentials",
    "signing_string",
    "sign",
    "auth_headers",
    "signed_request",
    "probe_auth",
    "KalshiAuthError",
]

# ASSUMPTIONS, in one place so a live run can correct them the way it corrected
# `_MARKET_FIELDS`.
_TIMESTAMP_UNIT_MS = True          # Kalshi documents milliseconds, not seconds.
_SIGNED_PATH_INCLUDES_PREFIX = True  # i.e. "/trade-api/v2/portfolio/balance".
_SIGNED_PATH_INCLUDES_QUERY = False  # The query string is excluded.
_HEADER_KEY = "KALSHI-ACCESS-KEY"
_HEADER_SIGNATURE = "KALSHI-ACCESS-SIGNATURE"
_HEADER_TIMESTAMP = "KALSHI-ACCESS-TIMESTAMP"


class KalshiAuthError(RuntimeError):
    """A signed call that cannot be trusted. Never swallowed into a falsy result."""


_BASE64_LINE = re.compile(r"^[A-Za-z0-9+/=]+$")


def _private_key_pem() -> str:
    raw = os.environ.get("KALSHI_PRIVATE_KEY") or ""
    # A PEM pasted into a dashboard field arrives with literal backslash-n. Both
    # forms are accepted; neither is logged.
    text = raw.replace("\\n", "\n").strip()
    return _restore_pem_armor(text)


def _restore_pem_armor(text: str) -> str:
    """Put the BEGIN/END lines back when a form field has eaten them.

    MEASURED 2026-08-23T19:36:17Z: `chars=1616 lines=25 header=<unrecognized>
    has_end_marker=False has_real_newlines=True`. The newlines survived and the
    length is right for a 2048-bit key; what was missing was the armor. Some
    dashboard fields strip lines beginning with `-`, and the base64 body alone
    is not a PEM.

    ONLY when every line is valid base64 and no marker is present anywhere. A
    value that is something else entirely is left exactly as it was, so it still
    fails with its own shape reported rather than being disguised as a broken
    key. `restored` is reported by `_pem_shape`, so this is never silent.
    """
    if not text or "-----" in text:
        return text
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2 or not all(_BASE64_LINE.match(line) for line in lines):
        return text
    body = "\n".join(lines)
    # BOTH ARMORS ARE TRIED, and which one worked is reported.
    #
    # MEASURED 2026-08-23T22:49:33Z: the PKCS#8 armor restored cleanly --
    # `header='-----BEGIN PRIVATE KEY-----' has_end_marker=True lines=27` -- and
    # STILL raised ValueError. A well-formed PKCS#8 wrapper around a PKCS#1 body
    # is exactly that: structurally perfect, semantically wrong. So the caller
    # gets the armor that actually parses rather than the one I guessed first.
    for label in ("PRIVATE KEY", "RSA PRIVATE KEY"):
        candidate = f"-----BEGIN {label}-----\n{body}\n-----END {label}-----"
        if _parses(candidate):
            return candidate
    # Neither parsed. Return the PKCS#8 form so the failure is reported against
    # a definite shape rather than against the bare body.
    return f"-----BEGIN PRIVATE KEY-----\n{body}\n-----END PRIVATE KEY-----"


def _parses(pem: str) -> bool:
    """Does this text load as a private key? No exception escapes."""
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key

        load_pem_private_key(pem.encode("utf-8"), password=None)
        return True
    except BaseException:  # noqa: BLE001 -- a broken install raises PanicException
        return False


# PEM headers we can name without revealing anything. The BODY is never touched.
_PEM_HEADERS = (
    "-----BEGIN PRIVATE KEY-----",            # PKCS#8, unencrypted -- what we want
    "-----BEGIN RSA PRIVATE KEY-----",        # PKCS#1, also fine
    "-----BEGIN ENCRYPTED PRIVATE KEY-----",  # passphrase-protected -- we cannot open it
    "-----BEGIN OPENSSH PRIVATE KEY-----",    # ssh-keygen output, NOT a PEM key pair
)


def _pem_shape(pem: str) -> dict[str, Any]:
    """Structural facts about the configured value. NEVER any of its content.

    Length, header and line count are enough to tell a flattened PEM from a
    truncated one from an ssh key pasted by mistake, and none of them is
    material. The base64 body is never read, sliced or echoed.
    """
    text = str(pem or "")
    header = next((h for h in _PEM_HEADERS if text.startswith(h)), None)
    return {
        "chars": len(text),
        "lines": text.count("\n") + 1 if text else 0,
        # Named header, or a bounded description of what it starts with instead
        # -- "not a PEM at all" and "the wrong KIND of PEM" need different fixes.
        "header": header or ("<unrecognized>" if text else "<empty>"),
        "has_end_marker": "-----END" in text,
        # A dashboard field often flattens newlines. If BOTH are false the value
        # is one long line and no parser will read it.
        "has_real_newlines": "\n" in text,
        "had_escaped_newlines": "\\n" in (os.environ.get("KALSHI_PRIVATE_KEY") or ""),
        # True when the armor was rebuilt by `_restore_pem_armor` rather than
        # supplied. Compares the REPAIRED value against the raw one, so it means
        # "the repair fired", not merely "the input had no markers" -- a value
        # that is not a key at all lacks markers too and was left untouched.
        "armor_restored": "-----" in text
        and "-----" not in (os.environ.get("KALSHI_PRIVATE_KEY") or "").replace("\\n", "\n"),
    }


def load_credentials() -> dict[str, Any]:
    """The signer, or a NAMED reason there isn't one.

    Returns `{"status": "ok", "key_id": ..., "private_key": <object>}` or
    `{"status": "unavailable", "reason": ...}`. Never raises, never returns a
    partially configured signer: "configured but unable to sign" would surface
    at the submit call, which is the one place a surprise is unaffordable.
    """
    key_id = (os.environ.get("KALSHI_API_KEY_ID") or "").strip()
    if not key_id:
        return {"status": "unavailable", "reason": "no_api_key_id"}

    pem = _private_key_pem()
    if not pem:
        return {"status": "unavailable", "reason": "no_private_key"}

    try:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
    except BaseException:  # noqa: BLE001 -- see below, this is deliberate
        # `cryptography` is a declared dependency, but an import failure here
        # must read as "cannot sign" rather than taking down the worker that
        # imports this module for its read-only side.
        #
        # BaseException, NOT Exception, and MEASURED rather than defensive: a
        # broken install (`cryptography` present, `_cffi_backend` missing --
        # exactly what this container had on 2026-08-23) raises pyo3's
        # `PanicException`, which inherits from BaseException. `except
        # Exception` let it straight through and the process died on an import.
        return {"status": "unavailable", "reason": "no_cryptography"}

    try:
        private_key = load_pem_private_key(pem.encode("utf-8"), password=None)
    except Exception as exc:
        # The EXCEPTION TYPE only -- the message from a key parser can echo key
        # material, and this string reaches logs.
        #
        # But a bare type name is not actionable: `ValueError` was the whole
        # answer on 2026-08-23T19:28:53Z and it does not distinguish a flattened
        # PEM from a truncated one from the wrong format entirely. So the SHAPE
        # of the value is reported alongside it -- length, which header it
        # carries, how many lines it has. None of that is key material and all
        # of it separates the causes. Same choice `probe()` made for the market
        # schema, which is what caught the 100x price error.
        return {
            "status": "unavailable",
            "reason": "unreadable_private_key",
            "detail": type(exc).__name__,
            "key_shape": _pem_shape(pem),
        }

    return {"status": "ok", "key_id": key_id, "private_key": private_key}


def _timestamp_ms(now: float | None = None) -> str:
    seconds = time.time() if now is None else now
    return str(int(seconds * 1000)) if _TIMESTAMP_UNIT_MS else str(int(seconds))


def signed_path(url: str) -> str:
    """The path portion of `url`, as it must appear in the signed string.

    DERIVED FROM THE URL, never passed beside it. Signing one path and sending
    another produces a bare 401 in which clock skew, a wrong key and a wrong
    host are indistinguishable -- so the two cannot be allowed to disagree.
    """
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or "/"
    if _SIGNED_PATH_INCLUDES_QUERY and parsed.query:
        return f"{path}?{parsed.query}"
    return path


def signing_string(timestamp: str, method: str, url: str) -> str:
    """`timestamp + METHOD + path`, concatenated with no separators."""
    return f"{timestamp}{method.upper()}{signed_path(url)}"


def sign(private_key: Any, message: str) -> str:
    """RSA-PSS over SHA-256, MGF1-SHA256, salt length = digest length."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=hashes.SHA256.digest_size,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("ascii")


def auth_headers(
    method: str, url: str, *, credentials: dict[str, Any] | None = None, now: float | None = None
) -> dict[str, str]:
    """Headers for one signed call. Raises rather than returning unsigned ones.

    An unsigned request to a trading endpoint is a 401, and a 401 on a submit is
    ambiguous in the most expensive way -- it does not tell you whether the order
    was rejected or the auth was. Refusing here keeps that ambiguity out.
    """
    creds = credentials or load_credentials()
    if creds.get("status") != "ok":
        raise KalshiAuthError(f"cannot_sign: {creds.get('reason')}")

    timestamp = _timestamp_ms(now)
    signature = sign(creds["private_key"], signing_string(timestamp, method, url))
    return {
        _HEADER_KEY: str(creds["key_id"]),
        _HEADER_SIGNATURE: signature,
        _HEADER_TIMESTAMP: timestamp,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "syndicate/1.0",
    }


def signed_request(
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
    credentials: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> dict[str, Any]:
    """One signed call. Returns the decoded object, or raises `KalshiAuthError`.

    The headers are built from the SAME `url` that is sent -- the whole reason
    this is one function rather than a header helper plus a caller's urlopen.
    """
    headers = auth_headers(method, url, credentials=credentials)
    payload = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=payload, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8")[:400]
        except Exception:
            detail = "<unreadable>"
        # 401 gets a hint rather than a guess. Clock skew is the most common
        # cause and the least obvious one, and it is the only one the caller can
        # check without Kalshi's help.
        hint = " (check container clock skew, key id, and that the key is live)" if exc.code == 401 else ""
        raise KalshiAuthError(f"http_{exc.code}: {url}{hint}: {detail}") from exc
    except Exception as exc:
        raise KalshiAuthError(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(decoded, dict):
        raise KalshiAuthError(f"payload_not_an_object: {type(decoded).__name__}")
    return decoded


def _base_url() -> str:
    from syndicate.features.shared.kalshi_client import _BASE_URLS

    override = (os.environ.get("KALSHI_API_BASE") or "").strip()
    return override or _BASE_URLS[0]


def probe_auth() -> dict[str, Any]:
    """Does the credential work, and what does an authenticated read look like?

    Reports the SHAPE that came back rather than parsing it -- the same choice
    `kalshi_client.probe()` made, which is what caught the 100x price error and
    the ten wrong field names before either could ship.

    Read-only by construction: it asks for the balance. There is no argument
    that turns this into a write.
    """
    creds = load_credentials()
    if creds.get("status") != "ok":
        return {
            "status": "unavailable",
            "reason": creds.get("reason"),
            "detail": creds.get("detail"),
            "key_shape": creds.get("key_shape"),
        }

    url = f"{_base_url()}/portfolio/balance"
    try:
        payload = signed_request("GET", url, credentials=creds)
    except KalshiAuthError as exc:
        return {"status": "error", "reason": str(exc), "url": url}
    return {
        "status": "ok",
        "url": url,
        # Keys, not values: a balance is not a secret but there is no reason for
        # it to be in a log line whose job is to confirm the signature worked.
        "keys": sorted(payload.keys()),
        "balance_present": "balance" in payload,
    }
