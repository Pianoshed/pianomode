import base64
import time

from app.core import crypto, totp

# RFC 6238 appendix B: the shared secret is the ASCII string "12345678901234567890", HMAC-SHA1,
# and the standard prints 8-digit codes. Our codes are 6 digits, the last six of those.
RFC_SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
RFC_VECTORS = {
    59: "94287082",
    1111111109: "07081804",
    1111111111: "14050471",
    1234567890: "89005924",
    2000000000: "69279037",
    20000000000: "65353130",
}


def test_matches_the_rfc_6238_test_vectors() -> None:
    for t, eight in RFC_VECTORS.items():
        assert totp._code(RFC_SECRET, totp.step_at(t)) == eight[-6:], t


def test_accepts_the_current_and_neighbouring_steps_but_not_far_ones() -> None:
    now = 1_700_000_000.0
    step = totp.step_at(now)
    for s in (step - 1, step, step + 1):
        assert totp.verify(RFC_SECRET, totp._code(RFC_SECRET, s), now) == s
    for s in (step - 2, step + 2):
        assert totp.verify(RFC_SECRET, totp._code(RFC_SECRET, s), now) is None


def test_a_code_cannot_be_used_twice() -> None:
    now = 1_700_000_000.0
    code = totp._code(RFC_SECRET, totp.step_at(now))
    used = totp.verify(RFC_SECRET, code, now)
    assert used is not None
    assert totp.verify(RFC_SECRET, code, now, last_step=used) is None
    # ...but the next step's code still works
    assert (
        totp.verify(RFC_SECRET, totp._code(RFC_SECRET, used + 1), now, last_step=used) == used + 1
    )


def test_malformed_codes_are_rejected() -> None:
    for bad in ("", "12345", "1234567", "abcdef", "12 34 5"):
        assert totp.verify(RFC_SECRET, bad, 1_700_000_000.0) is None
    now = 1_700_000_000.0
    spaced = totp._code(RFC_SECRET, totp.step_at(now))
    assert (
        totp.verify(RFC_SECRET, f"{spaced[:3]} {spaced[3:]}", now) is not None
    )  # apps show "123 456"


def test_secrets_and_uri() -> None:
    s = totp.new_secret()
    assert len(s) == 32 and s == s.upper() and totp.new_secret() != s
    assert totp.verify(s, totp._code(s, totp.step_at(time.time())), time.time()) is not None
    uri = totp.otpauth_uri(s, "a@b.com", "Keystudy")
    assert uri.startswith("otpauth://totp/Keystudy:a%40b.com?secret=") and "issuer=Keystudy" in uri


def test_recovery_codes_look_like_codes_and_differ() -> None:
    codes = {totp.recovery_code() for _ in range(50)}
    assert len(codes) == 50 and all(len(c) == 11 and c[5] == "-" for c in codes)


def test_stored_secrets_are_encrypted_and_round_trip() -> None:
    token = crypto.encrypt("JBSWY3DPEHPK3PXP")
    assert "JBSWY3DP" not in token and crypto.decrypt(token) == "JBSWY3DPEHPK3PXP"
    assert crypto.decrypt("not a token") is None
