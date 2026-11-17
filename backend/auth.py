"""Authentication helpers: password hashing + JWT (HS256), stdlib only.

No extra dependencies needed: passwords use PBKDF2-HMAC-SHA256 and tokens
are real signed JWTs (header.payload.signature) verified with HMAC.
Change SUPERVISORMATCH_SECRET in production / before deployment.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

SECRET = os.environ.get("SUPERVISORMATCH_SECRET", "dev-secret-change-me")
TOKEN_TTL_SECONDS = 24 * 3600


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000
    ).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    try:
        salt, digest = stored.split("$")
    except (ValueError, AttributeError):
        return False
    check = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000
    ).hex()
    return hmac.compare_digest(digest, check)


def _b64(data: bytes):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def create_token(user_id, role):
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64(
        json.dumps(
            {"sub": user_id, "role": role, "exp": int(time.time()) + TOKEN_TTL_SECONDS}
        ).encode()
    )
    signature = _b64(
        hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    )
    return f"{header}.{payload}.{signature}"


def decode_token(token):
    try:
        header, payload, signature = token.split(".")
        expected = _b64(
            hmac.new(SECRET.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(expected, signature):
            return None
        data = json.loads(
            base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        )
        if data["exp"] < time.time():
            return None
        return data
    except Exception:
        return None
