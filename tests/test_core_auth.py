from dagi_core.auth import create_session_token, hash_password, verify_password, verify_session_token


def test_password_hash_verifies_only_the_matching_password():
    encoded = hash_password("test-password", salt=bytes.fromhex("00112233445566778899aabbccddeeff"), iterations=1000)

    assert encoded.startswith("pbkdf2_sha256$1000$")
    assert verify_password("test-password", encoded)
    assert not verify_password("wrong-password", encoded)


def test_session_token_expires_and_rejects_tampering():
    token = create_session_token("admin", secret=b"test-session-secret", now=1000, nonce=b"nonce")

    assert verify_session_token(token, "admin", b"test-session-secret", now=1001, ttl=60)
    assert not verify_session_token(token, "admin", b"test-session-secret", now=1061, ttl=60)
    assert not verify_session_token(token + "x", "admin", b"test-session-secret", now=1001, ttl=60)
    assert not verify_session_token(token, "other", b"test-session-secret", now=1001, ttl=60)
