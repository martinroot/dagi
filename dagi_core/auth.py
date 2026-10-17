"""Password hashing and signed browser-session tokens for the web sandbox."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import time

_HASH_NAME = "pbkdf2_sha256"
_DEFAULT_ITERATIONS = 600_000


def hash_password(password: str, *, salt: bytes | None = None, iterations: int = _DEFAULT_ITERATIONS) -> str:
    if not password or iterations < 1_000:
        raise ValueError("password must be non-empty and PBKDF2 iterations at least 1000")
    salt = os.urandom(16) if salt is None else salt
    if len(salt) < 16:
        raise ValueError("password salt must be at least 16 bytes")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_HASH_NAME}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        name, raw_iterations, raw_salt, raw_digest = encoded.split("$", 3)
        iterations = int(raw_iterations)
        salt = bytes.fromhex(raw_salt)
        expected = bytes.fromhex(raw_digest)
        if name != _HASH_NAME or not 1_000 <= iterations <= 2_000_000 or len(salt) < 16:
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_session_token(
    username: str,
    secret: bytes,
    *,
    now: int | None = None,
    nonce: bytes | None = None,
) -> str:
    issued_at = int(time.time() if now is None else now)
    payload = b"\0".join((username.encode("utf-8"), str(issued_at).encode("ascii"), _b64(nonce or os.urandom(24)).encode("ascii")))
    encoded = _b64(payload)
    signature = hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64(signature)}"


def verify_session_token(
    token: str,
    username: str,
    secret: bytes,
    *,
    now: int | None = None,
    ttl: int = 43_200,
) -> bool:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = _b64(hmac.new(secret, encoded.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return False
        token_user, raw_issued_at, nonce = _unb64(encoded).split(b"\0", 2)
        issued_at = int(raw_issued_at)
        current_time = int(time.time() if now is None else now)
        return (
            token_user.decode("utf-8") == username
            and bool(nonce)
            and issued_at <= current_time + 30
            and current_time - issued_at < ttl
        )
    except (ValueError, UnicodeDecodeError, TypeError):
        return False
