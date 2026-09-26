"""Step 1: /auth/{provider}/login."""

from urllib.parse import parse_qs, urlsplit

from app.oidc import PENDING_COOKIE, pkce_challenge, unpack_pending


def test_pkce_challenge_matches_rfc7636_appendix_b():
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert pkce_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_login_redirects_to_the_provider_with_pkce_state_and_nonce(client):
    response = client.get("/auth/google/login", follow_redirects=False)
    assert response.status_code == 302

    location = urlsplit(response.headers["location"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == "https://idp.test/authorize"

    q = {key: values[0] for key, values in parse_qs(location.query).items()}
    assert q["response_type"] == "code"
    assert q["client_id"] == "test-client-id"
    assert q["redirect_uri"] == "http://localhost:8000/auth/google/callback"
    assert q["scope"] == "openid email profile"
    assert q["code_challenge_method"] == "S256"
    assert q["access_type"] == "offline"
    assert q["prompt"] == "consent"
    assert len(q["state"]) >= 32
    assert len(q["nonce"]) >= 32

    # The pending cookie must let the callback reproduce exactly what was sent.
    pending = unpack_pending(response.cookies[PENDING_COOKIE])
    assert pending["provider"] == "google"
    assert pending["state"] == q["state"]
    assert pending["nonce"] == q["nonce"]
    assert pkce_challenge(pending["code_verifier"]) == q["code_challenge"]

    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "path=/auth" in set_cookie
    assert "samesite=lax" in set_cookie


def test_every_login_gets_fresh_state_and_nonce(client):
    first = client.get("/auth/google/login", follow_redirects=False)
    second = client.get("/auth/google/login", follow_redirects=False)
    q1 = parse_qs(urlsplit(first.headers["location"]).query)
    q2 = parse_qs(urlsplit(second.headers["location"]).query)
    assert q1["state"] != q2["state"]
    assert q1["nonce"] != q2["nonce"]
    assert q1["code_challenge"] != q2["code_challenge"]


def test_unknown_provider_is_404(client):
    response = client.get("/auth/nope/login", follow_redirects=False)
    assert response.status_code == 404


def test_tampered_pending_cookie_is_rejected(client):
    from app.oidc import PendingLoginError
    import pytest

    response = client.get("/auth/google/login", follow_redirects=False)
    good = response.cookies[PENDING_COOKIE]
    with pytest.raises(PendingLoginError):
        unpack_pending(good[:-2] + "xx")
    with pytest.raises(PendingLoginError):
        unpack_pending(None)
