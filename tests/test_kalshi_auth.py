"""Request signing: the parts that are true regardless of what Kalshi returns."""

from __future__ import annotations

import base64

import pytest

from syndicate.features.shared import kalshi_auth


@pytest.fixture(scope="module")
def keypair():
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = private.private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()
    ).decode("ascii")
    return private, private.public_key(), pem


@pytest.fixture
def configured(monkeypatch, keypair):
    _private, _public, pem = keypair
    monkeypatch.setenv("KALSHI_API_KEY_ID", "key-id-under-test")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", pem)
    return pem


def test_no_credential_is_a_named_refusal_not_a_crash(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY", raising=False)
    assert kalshi_auth.load_credentials() == {
        "status": "unavailable",
        "reason": "no_api_key_id",
    }


def test_a_key_id_without_a_private_key_is_named_separately(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.delenv("KALSHI_PRIVATE_KEY", raising=False)
    # Half-configured must not read the same as unconfigured: one is "nobody set
    # this up", the other is "somebody set up half of it".
    assert kalshi_auth.load_credentials()["reason"] == "no_private_key"


def test_an_unreadable_key_reports_the_type_and_never_the_material(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "-----BEGIN PRIVATE KEY-----\nnope\n-----END PRIVATE KEY-----")
    result = kalshi_auth.load_credentials()
    assert result["reason"] == "unreadable_private_key"
    # The parser's message can echo key material, and this string reaches logs.
    assert "nope" not in str(result)


def test_a_pem_with_literal_backslash_n_is_accepted(monkeypatch, keypair):
    _private, _public, pem = keypair
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", pem.replace("\n", "\\n"))
    # This is how a PEM arrives from a dashboard field.
    assert kalshi_auth.load_credentials()["status"] == "ok"


def test_the_signature_verifies_against_the_public_key(configured, keypair):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    _private, public, _pem = keypair
    url = "https://external-api.kalshi.com/trade-api/v2/portfolio/balance"
    headers = kalshi_auth.auth_headers("GET", url, now=1_700_000_000.0)

    message = kalshi_auth.signing_string(
        headers["KALSHI-ACCESS-TIMESTAMP"], "GET", url
    )
    public.verify(
        base64.b64decode(headers["KALSHI-ACCESS-SIGNATURE"]),
        message.encode("utf-8"),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=hashes.SHA256.digest_size),
        hashes.SHA256(),
    )


def test_the_timestamp_is_milliseconds_not_seconds(configured):
    headers = kalshi_auth.auth_headers(
        "GET", "https://x/trade-api/v2/portfolio/balance", now=1_700_000_000.0
    )
    # Seconds would be 1700000000 and Kalshi rejects it as outside the window --
    # a 401 that looks exactly like a wrong key.
    assert headers["KALSHI-ACCESS-TIMESTAMP"] == "1700000000000"


def test_the_signed_path_is_derived_from_the_url_and_keeps_the_api_prefix():
    url = "https://external-api.kalshi.com/trade-api/v2/portfolio/positions"
    assert kalshi_auth.signed_path(url) == "/trade-api/v2/portfolio/positions"


def test_the_query_string_is_excluded_from_the_signature():
    signed = kalshi_auth.signed_path(
        "https://x/trade-api/v2/portfolio/fills?ticker=KXMLBKS-26AUG24&limit=100"
    )
    assert signed == "/trade-api/v2/portfolio/fills"
    assert "?" not in signed


def test_the_signing_string_is_timestamp_then_method_then_path():
    assert (
        kalshi_auth.signing_string("1700000000000", "post", "https://x/trade-api/v2/portfolio/orders")
        == "1700000000000POST/trade-api/v2/portfolio/orders"
    )


def test_signing_refuses_rather_than_producing_unsigned_headers(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY", raising=False)
    # An unsigned request to a trading endpoint is a 401, and a 401 on a submit
    # does not say whether the ORDER or the AUTH was rejected.
    with pytest.raises(kalshi_auth.KalshiAuthError) as excinfo:
        kalshi_auth.auth_headers("POST", "https://x/trade-api/v2/portfolio/orders")
    assert "no_api_key_id" in str(excinfo.value)


def test_two_calls_to_different_paths_do_not_share_a_signature(configured):
    a = kalshi_auth.auth_headers("GET", "https://x/trade-api/v2/portfolio/balance", now=1.0)
    b = kalshi_auth.auth_headers("GET", "https://x/trade-api/v2/portfolio/positions", now=1.0)
    assert a["KALSHI-ACCESS-SIGNATURE"] != b["KALSHI-ACCESS-SIGNATURE"]


def test_probe_auth_reports_the_missing_credential_without_calling_out(monkeypatch):
    monkeypatch.delenv("KALSHI_API_KEY_ID", raising=False)
    monkeypatch.delenv("KALSHI_PRIVATE_KEY", raising=False)

    def explode(*_a, **_k):
        raise AssertionError("probe_auth made a network call with no credential")

    monkeypatch.setattr(kalshi_auth, "signed_request", explode)
    assert kalshi_auth.probe_auth() == {
        "status": "unavailable",
        "reason": "no_api_key_id",
        "detail": None,
        # None rather than absent: a caller reading `key_shape` must not have to
        # test whether the key exists before testing what it says.
        "key_shape": None,
    }


def test_an_unreadable_key_reports_its_SHAPE_so_the_cause_is_actionable(monkeypatch):
    """`detail=ValueError` was the whole answer in production and is unusable.

    It does not distinguish a flattened PEM from a truncated one from an ssh key
    pasted by mistake — three different fixes. Length, header and line count
    separate them and none of them is key material.
    """
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv(
        "KALSHI_PRIVATE_KEY",
        "-----BEGIN PRIVATE KEY-----MIIEvQIBADANBg-----END PRIVATE KEY-----",
    )
    shape = kalshi_auth.load_credentials()["key_shape"]

    assert shape["header"] == "-----BEGIN PRIVATE KEY-----"
    assert shape["has_end_marker"] is True
    # The giveaway: a PEM with no newlines cannot be parsed by anything.
    assert shape["has_real_newlines"] is False
    assert shape["lines"] == 1


def test_the_shape_never_contains_the_key_body(monkeypatch):
    secret = "SUPERSECRETBASE64BODY"
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", f"-----BEGIN PRIVATE KEY-----{secret}-----END PRIVATE KEY-----")
    result = kalshi_auth.load_credentials()
    # The base64 body is never read, sliced or echoed.
    assert secret not in str(result)


def test_an_encrypted_key_is_named_as_such(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "-----BEGIN ENCRYPTED PRIVATE KEY-----\nx\n-----END ENCRYPTED PRIVATE KEY-----")
    shape = kalshi_auth.load_credentials()["key_shape"]
    # We load with password=None, so a passphrase-protected key can never open.
    assert shape["header"] == "-----BEGIN ENCRYPTED PRIVATE KEY-----"


def test_something_that_is_not_a_pem_says_so(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "just-some-token")
    shape = kalshi_auth.load_credentials()["key_shape"]
    # "Not a PEM at all" and "the wrong KIND of PEM" need different fixes.
    assert shape["header"] == "<unrecognized>"


def test_a_key_whose_armor_a_form_field_ate_still_loads(monkeypatch, keypair):
    """MEASURED 2026-08-23T19:36:17Z:

        chars=1616 lines=25 header=<unrecognized>
        has_end_marker=False has_real_newlines=True

    The newlines survived and the length was right for a 2048-bit key. What was
    missing was the BEGIN/END armor — some dashboard fields strip lines starting
    with `-`, and the base64 body alone is not a PEM.
    """
    _private, _public, pem = keypair
    body = "\n".join(line for line in pem.splitlines() if line and not line.startswith("-----"))

    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", body)
    result = kalshi_auth.load_credentials()
    assert result["status"] == "ok"


def test_the_repair_is_reported_never_silent(monkeypatch, keypair):
    """`armor_restored` means the repair FIRED, not merely that markers were
    absent -- a value that is not a key at all lacks markers too."""
    _private, _public, pem = keypair
    body = "\n".join(line for line in pem.splitlines() if line and not line.startswith("-----"))

    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "not base64 at all\n!!!")
    assert kalshi_auth.load_credentials()["key_shape"]["armor_restored"] is False

    monkeypatch.setenv("KALSHI_PRIVATE_KEY", body)
    # A repaired value and a correct one must never be confused, so a repaired
    # one says so even when it then loads fine.
    monkeypatch.setattr(kalshi_auth, "_pem_shape", kalshi_auth._pem_shape)
    assert kalshi_auth._pem_shape(kalshi_auth._private_key_pem())["armor_restored"] is True


def test_something_that_is_not_base64_is_left_alone(monkeypatch):
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", "hello there\nthis is not a key")
    shape = kalshi_auth.load_credentials()["key_shape"]
    # Left exactly as it was, so it fails with its OWN shape reported rather
    # than being disguised as a broken key.
    assert shape["header"] == "<unrecognized>"


def test_a_complete_pem_is_never_touched(monkeypatch, keypair):
    _private, _public, pem = keypair
    monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
    monkeypatch.setenv("KALSHI_PRIVATE_KEY", pem)
    result = kalshi_auth.load_credentials()
    assert result["status"] == "ok"
    # No repair attempted on a value that already has its armor.


def test_a_pkcs1_body_gets_pkcs1_armor_not_the_one_I_guessed_first(monkeypatch):
    """MEASURED 2026-08-23T22:49:33Z, after the first armor repair shipped:

        header='-----BEGIN PRIVATE KEY-----' has_end_marker=True
        lines=27 armor_restored=True  ->  still ValueError

    A well-formed PKCS#8 wrapper around a PKCS#1 body is structurally perfect
    and semantically wrong, which is why the repair has to be verified by
    PARSING rather than by looking right.
    """
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    for fmt in (PrivateFormat.PKCS8, PrivateFormat.TraditionalOpenSSL):
        pem = key.private_bytes(Encoding.PEM, fmt, NoEncryption()).decode("ascii")
        body = "\n".join(l for l in pem.splitlines() if l and not l.startswith("-----"))
        monkeypatch.setenv("KALSHI_API_KEY_ID", "abc")
        monkeypatch.setenv("KALSHI_PRIVATE_KEY", body)
        assert kalshi_auth.load_credentials()["status"] == "ok", fmt
