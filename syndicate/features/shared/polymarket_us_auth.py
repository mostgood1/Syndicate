"""Ed25519 request signing for Polymarket US (`api.polymarket.us`).

--------------------------------------------------------------------------
THIS IS A DIFFERENT EXCHANGE FROM `polymarket_client.py`
--------------------------------------------------------------------------

That module talks to `gamma-api.polymarket.com` and `clob.polymarket.com` --
the GLOBAL, on-chain Polymarket: EIP-712 order structs, an Ethereum wallet,
USDC on Polygon, ERC-1155 token ids.

This one talks to `api.polymarket.us` -- the US venue. Different host,
different auth, different order contract, and **different money**. An account
funded on one is not funded on the other.

The two are kept in separate modules, named unmistakably, because a fallback
between them is not a degraded answer -- it is an order placed on an exchange
where the user has no balance, or worse, has a balance they did not intend to
spend. Nothing here imports that module and nothing there imports this one.

--------------------------------------------------------------------------
WHY THIS IS FAR SIMPLER THAN THE GLOBAL VENUE
--------------------------------------------------------------------------

The global CLOB needs an Ethereum private key to sign EIP-712 order structs,
which would mean a new dependency (`eth-account`/`web3`) and a credential that
DRAINS THE WALLET if leaked, not merely one that can trade.

`api.polymarket.us` uses Ed25519 over a string -- the same shape as Kalshi's
RSA-PSS, and `cryptography` (already a dependency) supports it directly. The
credential is an API key that can trade and nothing more. That is a materially
smaller blast radius and it is worth stating plainly, because "Polymarket
orders need a wallet key" was true of the other module and is NOT true here.

--------------------------------------------------------------------------
EVERY ASSUMPTION IN ONE PLACE, BECAUSE ALL OF THEM ARE UNVERIFIED
--------------------------------------------------------------------------

No call in this file has run. The proxy in the build sandbox denies CONNECT to
every venue host, exactly as it did for Kalshi -- whose first live run
corrected ten field names and a 100x price error. Kalshi's order route then
cost an `http_410` because a path was inferred rather than read.

So the documented facts are constants, not scattered literals:

    signing string   timestamp + method + path      (documented, verbatim)
    timestamp        Unix MILLISECONDS, ±30s of server time
    signature        base64 of the raw Ed25519 signature
    headers          X-PM-Access-Key / X-PM-Timestamp / X-PM-Signature

`probe_auth()` reports the SHAPE that came back rather than parsing it, which
is what caught Kalshi's errors before they reached an order.

--------------------------------------------------------------------------
CREDENTIALS
--------------------------------------------------------------------------

`POLYMARKET_US_API_KEY_ID` and `POLYMARKET_US_PRIVATE_KEY`, from the Render
dashboard -- never `render.yaml`, which is in git AND fires `blueprint_sync`
against all three services (`#284`). Nothing in this module logs key material:
failures report an exception TYPE and a structural shape, never a value.
"""

from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

__all__ = [
    "PolymarketUSAuthError",
    "load_credentials",
    "signing_string",
    "sign",
    "auth_headers",
    "signed_request",
    "probe_auth",
    "credentials_present",
]


class PolymarketUSAuthError(RuntimeError):
    """Raised only where continuing would send an unsigned or misdirected call."""


# THE DOCUMENTED CONTRACT, in one object. Each line is a thing a first live run
# can falsify, and none of them is repeated anywhere else in the codebase.
BASE_URL = "https://api.polymarket.us"
_API_PREFIX = "/v1"
_TIMESTAMP_UNIT_MS = True            # "Unix timestamp in milliseconds".
_SIGNED_PATH_INCLUDES_PREFIX = True  # i.e. "/v1/orders", not "/orders".
_SIGNED_PATH_INCLUDES_QUERY = False  # Documented as "timestamp + method + path".
_HEADER_KEY = "X-PM-Access-Key"
_HEADER_TIMESTAMP = "X-PM-Timestamp"
_HEADER_SIGNATURE = "X-PM-Signature"
# "Must be within 30 seconds of server time." Recorded so a clock-skew failure
# is diagnosable rather than mysterious -- the single most common cause of a
# 401 on a signed API, and the one the caller can actually check.
CLOCK_SKEW_TOLERANCE_SECONDS = 30

_BASE64_LINE = re.compile(r"^[A-Za-z0-9+/=_-]+$")


def _env(name: str) -> str:
    return str(os.environ.get(name) or "").strip()


def credentials_present() -> bool:
    """Both halves, or neither. A key id with no private key is not a partial
    credential -- it is an unsigned request waiting to be refused at the venue,
    and it should be refused here instead."""
    return bool(_env("POLYMARKET_US_API_KEY_ID") and _env("POLYMARKET_US_PRIVATE_KEY"))


def _decode_private_key(raw: str):
    """A 32-byte Ed25519 seed, however the dashboard mangled it.

    Accepts base64 and base64url, with or without padding, and hex. A dashboard
    field is a text box: it strips newlines, sometimes adds them, and a
    credential that fails to load because of whitespace is indistinguishable
    from one that is wrong. So the tolerant path is here, ONCE, and every
    caller gets the same behaviour.

    NEVER logs the value. The failure says what SHAPE was seen, because that is
    what tells someone whether they pasted the wrong field.
    """
    from cryptography.hazmat.primitives.asymmetric import ed25519

    text = "".join(str(raw or "").split())
    if not text:
        raise PolymarketUSAuthError("private_key_absent")

    seed: bytes | None = None
    # Hex first: a 64-char hex string is also valid base64url characters, so
    # trying base64 first would decode it to 48 wrong bytes rather than fail.
    if len(text) == 64 and re.fullmatch(r"[0-9a-fA-F]{64}", text):
        seed = bytes.fromhex(text)
    elif _BASE64_LINE.match(text):
        padded = text + "=" * (-len(text) % 4)
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                candidate = decoder(padded)
            except Exception:
                continue
            if len(candidate) in (32, 64):
                seed = candidate[:32]
                break

    if seed is None or len(seed) != 32:
        raise PolymarketUSAuthError(
            f"private_key_unreadable: chars={len(text)} looks_hex={bool(re.fullmatch(r'[0-9a-fA-F]+', text))}"
        )
    try:
        return ed25519.Ed25519PrivateKey.from_private_bytes(seed)
    except Exception as exc:
        raise PolymarketUSAuthError(f"private_key_rejected: {type(exc).__name__}") from exc


def load_credentials() -> dict[str, Any]:
    """`{key_id, private_key}` or a raised, NAMED failure."""
    key_id = _env("POLYMARKET_US_API_KEY_ID")
    if not key_id:
        raise PolymarketUSAuthError("api_key_id_absent")
    return {"key_id": key_id, "private_key": _decode_private_key(_env("POLYMARKET_US_PRIVATE_KEY"))}


def _timestamp_ms(now: float | None = None) -> str:
    seconds = time.time() if now is None else now
    return str(int(seconds * 1000)) if _TIMESTAMP_UNIT_MS else str(int(seconds))


def signed_path(url: str) -> str:
    """The path exactly as the signature must cover it.

    Query EXCLUDED per the documented "timestamp + method + path". If that
    turns out to be wrong the symptom is a 401 on every GET that carries a
    filter and none that do not -- which is why the flag is a named constant
    rather than an inline decision.
    """
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path or "/"
    if not _SIGNED_PATH_INCLUDES_PREFIX and path.startswith(_API_PREFIX):
        path = path[len(_API_PREFIX):] or "/"
    if _SIGNED_PATH_INCLUDES_QUERY and parsed.query:
        path = f"{path}?{parsed.query}"
    return path


def signing_string(timestamp: str, method: str, url: str) -> str:
    """`timestamp + method + path`, concatenated with no separator.

    Verbatim from the documentation. The METHOD IS UPPERCASE and the
    concatenation has no delimiter -- both are the kind of detail that produces
    a 401 with no other symptom, so they live here rather than at three call
    sites.
    """
    return f"{timestamp}{str(method).upper()}{signed_path(url)}"


def sign(private_key: Any, message: str) -> str:
    """Base64 of the raw 64-byte Ed25519 signature."""
    return base64.b64encode(private_key.sign(message.encode("utf-8"))).decode("ascii")


def auth_headers(
    method: str, url: str, *, credentials: dict[str, Any] | None = None,
    now: float | None = None,
) -> dict[str, str]:
    creds = credentials or load_credentials()
    timestamp = _timestamp_ms(now)
    return {
        _HEADER_KEY: str(creds["key_id"]),
        _HEADER_TIMESTAMP: timestamp,
        _HEADER_SIGNATURE: sign(creds["private_key"], signing_string(timestamp, method, url)),
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
    """One signed call. Returns the decoded object, or raises.

    Headers are built from the SAME `url` that is sent -- the whole reason this
    is one function rather than a header helper plus a caller's urlopen. A
    signature over a path that differs from the request's is a 401 nobody can
    see the cause of.
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
        # A 401 gets the hint rather than a guess. Clock skew is the most
        # common cause and the least obvious, and this venue documents a ±30s
        # window explicitly -- so it is worth naming rather than rediscovering.
        hint = (
            f" (check container clock skew against the documented"
            f" ±{CLOCK_SKEW_TOLERANCE_SECONDS}s window, the key id, and that the key is live)"
            if exc.code == 401 else ""
        )
        raise PolymarketUSAuthError(f"http_{exc.code}: {url}{hint}: {detail}") from exc
    except Exception as exc:
        raise PolymarketUSAuthError(f"{type(exc).__name__}: {exc}") from exc
    if not isinstance(decoded, dict):
        raise PolymarketUSAuthError(f"payload_not_an_object: {type(decoded).__name__}")
    return decoded


def probe_auth() -> dict[str, Any]:
    """Does the credential work, and what does a signed read look like?

    Reports the SHAPE that came back rather than parsing it -- the choice that
    caught Kalshi's ten wrong field names and its 100x price error before
    either could reach an order.

    READ-ONLY BY CONSTRUCTION. It asks for markets. There is no argument that
    turns this into a write, and it cannot reach the order module.
    """
    if not credentials_present():
        # Absence, named. Distinct from a credential that exists and fails --
        # they need completely different responses and must never share a line.
        return {"ok": False, "reason": "credentials_absent", "base_url": BASE_URL}
    url = f"{BASE_URL}{_API_PREFIX}/markets?active=true&limit=1"
    try:
        payload = signed_request("GET", url)
    except PolymarketUSAuthError as exc:
        return {"ok": False, "reason": str(exc), "base_url": BASE_URL}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "base_url": BASE_URL}

    rows = payload.get("markets") if isinstance(payload.get("markets"), list) else None
    sample = rows[0] if rows else None
    return {
        "ok": True,
        "base_url": BASE_URL,
        "payload_keys": sorted(payload.keys()),
        "count": len(rows) if rows is not None else None,
        # Keys only. A market row carries no credential, but reporting the
        # SHAPE is the point -- the values would just be noise here.
        "row_keys": sorted(sample.keys()) if isinstance(sample, dict) else None,
    }
