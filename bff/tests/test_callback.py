"""Steps 4 to 6: /auth/{provider}/callback and ID token verification.

The ID token tests sign tokens with a throwaway RSA key generated here, so every
rejection below is exercised for real, not mocked.
"""

import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.oidc import PENDING_COOKIE, IdTokenError, pkce_challenge, verify_id_token_with_key

FAKE_ISSUER = "https://idp.test"  # same as conftest's registry fixture
CLIENT_ID = "test-client-id"
NONCE = "n-0S6_WzA2Mj"


# --- fixtures -------------------------------------------------------------------


@pytest.fixture(scope="module")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def private_pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def public_pem(key) -> bytes:
    return key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def good_claims(**overrides) -> dict:
    now = int(time.time())
    claims = {
        "iss": FAKE_ISSUER,
        "sub": "110169484474386276334",
        "aud": CLIENT_ID,
        "exp": now + 3600,
        "iat": now,
        "nonce": NONCE,
        "email": "user@example.com",
        "email_verified": True,
        "name": "Example User",
    }
    claims.update(overrides)
    return {k: v for k, v in claims.items() if v is not None}


def sign(key, claims: dict) -> str:
    return jwt.encode(claims, private_pem(key), algorithm="RS256", headers={"kid": "test-kid"})


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


# --- verify_id_token_with_key: the five checks ------------------------------------


def test_valid_token_passes(rsa_key, registry):
    provider = registry.get("google")
    claims = verify_id_token_with_key(sign(rsa_key, good_claims()), rsa_key.public_key(), provider, NONCE)
    assert claims["sub"] == "110169484474386276334"
    assert claims["email"] == "user@example.com"


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"aud": "some-other-app"}, "wrong audience: token issued to another client"),
        ({"iss": "https://evil.test"}, "wrong issuer"),
        ({"exp": int(time.time()) - 600}, "expired"),
        ({"nonce": "different"}, "nonce mismatch: replayed from another login"),
        ({"nonce": None}, "nonce missing"),
        ({"sub": None}, "sub missing"),
    ],
)
def test_claim_checks(rsa_key, registry, overrides, reason):
    provider = registry.get("google")
    token = sign(rsa_key, good_claims(**overrides))
    with pytest.raises(IdTokenError):
        verify_id_token_with_key(token, rsa_key.public_key(), provider, NONCE)


def test_expiry_leeway_tolerates_small_clock_drift(rsa_key, registry):
    provider = registry.get("google")
    token = sign(rsa_key, good_claims(exp=int(time.time()) - 30))  # 30s stale, inside 60s leeway
    verify_id_token_with_key(token, rsa_key.public_key(), provider, NONCE)


def test_token_signed_by_a_different_key_is_rejected(rsa_key, other_rsa_key, registry):
    provider = registry.get("google")
    token = sign(other_rsa_key, good_claims())
    with pytest.raises(IdTokenError, match="Signature"):
        verify_id_token_with_key(token, rsa_key.public_key(), provider, NONCE)


def test_alg_none_is_rejected(rsa_key, registry):
    """A token that claims 'no signature needed'. Accepting it would make every claim forgeable."""
    provider = registry.get("google")
    header = b64url(json.dumps({"alg": "none", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(good_claims()).encode())
    with pytest.raises(IdTokenError):
        verify_id_token_with_key(f"{header}.{payload}.", rsa_key.public_key(), provider, NONCE)


def test_hs256_signed_with_the_public_key_is_rejected(rsa_key, registry):
    """The algorithm confusion attack: sign with HMAC using the *public* key as the secret.
    A verifier that trusts the token's alg header would validate it. Pinning RS256 stops it."""
    provider = registry.get("google")
    header = b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64url(json.dumps(good_claims()).encode())
    signing_input = f"{header}.{payload}".encode()
    mac = hmac.new(public_pem(rsa_key), signing_input, hashlib.sha256).digest()
    with pytest.raises(IdTokenError):
        verify_id_token_with_key(f"{header}.{payload}.{b64url(mac)}", rsa_key.public_key(), provider, NONCE)


# --- the callback route -----------------------------------------------------------


def test_callback_without_a_pending_login_is_rejected(client):
    response = client.get("/auth/google/callback?code=x&state=y")
    assert response.status_code == 400
    assert "no pending login" in response.json()["detail"]


def test_callback_with_wrong_state_is_rejected(client):
    """The CSRF case: a callback URL that carries someone else's state."""
    client.get("/auth/google/login", follow_redirects=False)  # sets the pending cookie
    response = client.get("/auth/google/callback?code=x&state=attackers-state")
    assert response.status_code == 400
    assert "state mismatch" in response.json()["detail"]


def test_callback_relays_a_provider_error(client):
    login = client.get("/auth/google/login", follow_redirects=False)
    state = parse_qs(urlsplit(login.headers["location"]).query)["state"][0]
    response = client.get(f"/auth/google/callback?error=access_denied&state={state}")
    assert response.status_code == 400
    assert "access_denied" in response.json()["detail"]


class FakeJwks:
    """Stands in for PyJWKClient: returns the test public key for any token."""

    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, token):
        class Signing:
            key = self._key

        return Signing()


def test_callback_end_to_end(fastapi_app, rsa_key, monkeypatch):
    """Login, then a callback whose code exchange is answered by a fake token endpoint."""
    seen = {}  # what the fake token endpoint received, for assertions afterwards
    ctx = {}   # state / nonce / code_challenge captured from the login redirect

    def token_endpoint(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == f"{FAKE_ISSUER}/token"
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        seen.update(form)
        if form.get("code") != "test-code":
            return httpx.Response(400, json={"error": "invalid_grant", "error_description": "bad code"})
        return httpx.Response(
            200,
            json={
                "access_token": "ya29.test-access",
                "refresh_token": "1//test-refresh",
                "id_token": sign(rsa_key, good_claims(nonce=ctx["nonce"])),
                "expires_in": 3599,
                "token_type": "Bearer",
                "scope": "openid email profile",
            },
        )

    fastapi_app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(token_endpoint))
    monkeypatch.setattr("app.oidc.jwks_client_for", lambda provider: FakeJwks(rsa_key.public_key()))

    with TestClient(fastapi_app) as client:
        login = client.get("/auth/google/login", follow_redirects=False)
        q = {k: v[0] for k, v in parse_qs(urlsplit(login.headers["location"]).query).items()}
        ctx.update(state=q["state"], nonce=q["nonce"], code_challenge=q["code_challenge"])

        response = client.get(f"/auth/google/callback?code=test-code&state={q['state']}")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verified"] is True
        assert body["sub"] == "110169484474386276334"
        assert body["email"] == "user@example.com"
        assert body["token_response_keys"] == ["access_token", "expires_in", "id_token", "refresh_token", "scope", "token_type"]

        # Step 5 sent exactly what the walkthrough says, and PKCE closed the loop.
        assert seen["grant_type"] == "authorization_code"
        assert seen["redirect_uri"] == "http://localhost:8000/auth/google/callback"
        assert seen["client_id"] == CLIENT_ID
        assert seen["client_secret"] == "test-client-secret"
        assert pkce_challenge(seen["code_verifier"]) == ctx["code_challenge"]

        # The pending cookie is single-use: gone after the callback.
        assert client.cookies.get(PENDING_COOKIE) is None
