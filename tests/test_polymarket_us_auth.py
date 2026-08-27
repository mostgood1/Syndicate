"""Ed25519 signing for `api.polymarket.us`.

Nothing here has run against the venue — the sandbox proxy denies CONNECT to
every venue host. But the signature itself is verifiable offline against the
public key, which is more than could be said for Kalshi's before its first live
run, and worth doing: a signature that is merely well-formed and does not
verify produces a 401 with no other symptom.
"""

from __future__ import annotations

import base64
import re

import pytest
from cryptography.hazmat.primitives.asymmetric import ed25519

from syndicate.features.shared import polymarket_us_auth as mod
from syndicate.features.shared.polymarket_us_auth import (
    PolymarketUSAuthError,
    auth_headers,
    credentials_present,
    load_credentials,
    sign,
    signed_path,
    signing_string,
)

_SEED = bytes(range(32))
_KEY = ed25519.Ed25519PrivateKey.from_private_bytes(_SEED)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("POLYMARKET_US_API_KEY_ID", raising=False)
    monkeypatch.delenv("POLYMARKET_US_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("POLYMARKET_US_API_BASE", raising=False)
    yield


def _arm(monkeypatch, private_key=None):
    monkeypatch.setenv("POLYMARKET_US_API_KEY_ID", "11111111-2222-3333-4444-555555555555")
    monkeypatch.setenv(
        "POLYMARKET_US_PRIVATE_KEY",
        private_key if private_key is not None else base64.b64encode(_SEED).decode(),
    )


# --------------------------------------------------------------------------
# THE SIGNATURE MUST ACTUALLY VERIFY
# --------------------------------------------------------------------------


def test_the_signature_verifies_against_the_public_key():
    """A signature that is merely well-formed base64 and does not verify is a
    401 with no other symptom. This is the one thing about this file that can
    be proven without reaching the venue, so it is proven."""
    message = signing_string("1756060800000", "GET", "https://api.polymarket.us/v1/markets")
    signature = base64.b64decode(sign(_KEY, message))
    # Raises InvalidSignature if wrong; no assertion needed beyond not raising.
    _KEY.public_key().verify(signature, message.encode("utf-8"))
    assert len(signature) == 64


def test_a_different_message_does_not_verify():
    """Guards against a signature computed over something other than the
    string that is sent -- e.g. a path that differs from the request's."""
    from cryptography.exceptions import InvalidSignature

    signature = base64.b64decode(sign(_KEY, "1756060800000GET/v1/markets"))
    with pytest.raises(InvalidSignature):
        _KEY.public_key().verify(signature, b"1756060800000GET/v1/orders")


# --------------------------------------------------------------------------
# The signing string, verbatim from the documentation
# --------------------------------------------------------------------------


def test_the_signing_string_is_timestamp_method_path_with_no_separator():
    """`timestamp + method + path`. No delimiter, uppercase method — both are
    the kind of detail that produces a 401 and nothing else."""
    assert signing_string("1700", "get", "https://api.polymarket.us/v1/orders") == "1700GET/v1/orders"


def test_the_signed_path_keeps_the_v1_prefix():
    assert signed_path("https://api.polymarket.us/v1/markets") == "/v1/markets"


def test_the_query_string_is_excluded_from_the_signature():
    """Documented as "timestamp + method + path". If that is wrong the symptom
    is a 401 on every GET carrying a filter and none that do not — which is
    why it is a named constant rather than an inline decision."""
    assert signed_path("https://api.polymarket.us/v1/markets?active=true&limit=1") == "/v1/markets"


def test_the_timestamp_is_milliseconds():
    """Documented as milliseconds, and the window is ±30s. Sending seconds
    would put every request ~55 years out of tolerance."""
    headers = auth_headers("GET", "https://api.polymarket.us/v1/markets",
                           credentials={"key_id": "k", "private_key": _KEY},
                           now=1756060800.5)
    assert headers["X-PM-Timestamp"] == "1756060800500"


def test_the_documented_headers_are_the_ones_sent():
    headers = auth_headers("GET", "https://api.polymarket.us/v1/markets",
                           credentials={"key_id": "key-1", "private_key": _KEY})
    assert headers["X-PM-Access-Key"] == "key-1"
    assert re.fullmatch(r"[A-Za-z0-9+/]+=*", headers["X-PM-Signature"])
    assert headers["X-PM-Timestamp"].isdigit()


def test_the_headers_sign_the_url_that_is_sent():
    """Built from the SAME url the request uses — the whole reason
    `signed_request` is one function rather than a header helper plus a
    caller's urlopen."""
    url = "https://api.polymarket.us/v1/orders"
    headers = auth_headers("POST", url, credentials={"key_id": "k", "private_key": _KEY})
    expected = signing_string(headers["X-PM-Timestamp"], "POST", url)
    _KEY.public_key().verify(base64.b64decode(headers["X-PM-Signature"]), expected.encode())


# --------------------------------------------------------------------------
# Credentials: absent, malformed, and mangled-by-a-text-box
# --------------------------------------------------------------------------


def test_both_halves_or_neither(monkeypatch):
    """A key id with no private key is not a partial credential — it is an
    unsigned request waiting to be refused at the venue."""
    assert credentials_present() is False
    monkeypatch.setenv("POLYMARKET_US_API_KEY_ID", "k")
    assert credentials_present() is False
    monkeypatch.setenv("POLYMARKET_US_PRIVATE_KEY", base64.b64encode(_SEED).decode())
    assert credentials_present() is True


def test_an_absent_key_id_is_named():
    with pytest.raises(PolymarketUSAuthError, match="api_key_id_absent"):
        load_credentials()


def test_whitespace_and_padding_do_not_break_the_key(monkeypatch):
    """A dashboard field is a text box: it strips newlines, sometimes adds
    them. A credential that fails to load because of whitespace is
    indistinguishable from one that is simply wrong."""
    encoded = base64.b64encode(_SEED).decode()
    for variant in (f"  {encoded}  ", f"{encoded}\n", encoded.rstrip("=")):
        _arm(monkeypatch, variant)
        assert load_credentials()["private_key"].private_bytes_raw() == _SEED


def test_a_hex_key_is_accepted(monkeypatch):
    """Tried BEFORE base64: a 64-char hex string is also valid base64url
    characters, so decoding it as base64 first yields 48 wrong bytes rather
    than failing — a key that loads and never verifies."""
    _arm(monkeypatch, _SEED.hex())
    assert load_credentials()["private_key"].private_bytes_raw() == _SEED


def test_a_base64url_key_is_accepted(monkeypatch):
    _arm(monkeypatch, base64.urlsafe_b64encode(_SEED).decode())
    assert load_credentials()["private_key"].private_bytes_raw() == _SEED


def test_an_unreadable_key_reports_SHAPE_and_never_the_value(monkeypatch):
    """The failure says what shape was seen, because that is what tells
    someone whether they pasted the wrong field. It must not echo the secret."""
    secret = "not-a-key-at-all!!!"
    _arm(monkeypatch, secret)
    with pytest.raises(PolymarketUSAuthError) as excinfo:
        load_credentials()
    message = str(excinfo.value)
    assert "private_key_unreadable" in message
    assert "chars=" in message
    assert secret not in message


def test_a_wrong_length_key_is_refused(monkeypatch):
    _arm(monkeypatch, base64.b64encode(b"too-short").decode())
    with pytest.raises(PolymarketUSAuthError, match="private_key_unreadable"):
        load_credentials()


# --------------------------------------------------------------------------
# The probe: absence and failure must never share a line
# --------------------------------------------------------------------------


def test_the_probe_names_absent_credentials_rather_than_failing():
    """Distinct from a credential that exists and fails — they need completely
    different responses."""
    result = mod.probe_auth()
    assert result["ok"] is False
    assert result["reason"] == "credentials_absent"


def test_the_probe_reports_the_shape_rather_than_parsing_it(monkeypatch):
    """The choice that caught Kalshi's ten wrong field names and its 100x
    price error before either reached an order."""
    _arm(monkeypatch)
    monkeypatch.setattr(
        mod, "signed_request",
        lambda *a, **k: {"markets": [{"slug": "s", "bestBid": "0.54"}], "next": None},
    )
    result = mod.probe_auth()
    assert result["ok"] is True
    assert result["payload_keys"] == ["markets", "next"]
    assert result["row_keys"] == ["bestBid", "slug"]


def test_the_probe_reports_a_failure_by_name(monkeypatch):
    _arm(monkeypatch)

    def boom(*_a, **_k):
        raise PolymarketUSAuthError("http_401: ... clock skew ...")

    monkeypatch.setattr(mod, "signed_request", boom)
    result = mod.probe_auth()
    assert result["ok"] is False
    assert "http_401" in result["reason"]


def test_this_module_cannot_reach_the_global_polymarket_exchange():
    """`polymarket_client` talks to the on-chain venue: different host,
    different auth, different MONEY. An account funded on one is not funded on
    the other, so a fallback between them is not a degraded answer — it is an
    order on an exchange the user did not choose."""
    import ast
    import inspect

    # BEHAVIOUR, NOT PROSE, AND NO SIDE EFFECTS. Two earlier versions of this
    # test were wrong in instructive ways: the first grepped the source for the
    # global hosts and failed on its own docstring, which EXPLAINS the
    # distinction; the second popped `polymarket_client` from `sys.modules` to
    # prove it was not imported, which invalidated another test file's
    # monkeypatch and made an unrelated test hit the real network.
    #
    # Parsing the IMPORT STATEMENTS asserts the real property and touches
    # nothing.
    assert mod.BASE_URL == "https://api.polymarket.us"

    imported: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(mod))):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert not any("polymarket_client" in name for name in imported), imported

    # And every path it signs is rooted at the US host.
    for url in (f"{mod.BASE_URL}/v1/markets", f"{mod.BASE_URL}/v1/orders?limit=1"):
        assert mod.signed_path(url).startswith("/v1")
