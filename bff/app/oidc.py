"""Protocol helpers: PKCE, the pending-login cookie, token exchange, ID token verification.

Each function names the WORKFLOW.md step it implements.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass

import httpx
import jwt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from jwt import PyJWKClient
from starlette.concurrency import run_in_threadpool

from .config import get_settings
from .providers import Provider

log = logging.getLogger("bff.oidc")

# Set in step 1, read in step 4, deleted right after. Scoped to /auth so it is only
# ever sent to the login and callback routes.
PENDING_COOKIE = "oauth_pending"


class PendingLoginError(Exception):
    """The oauth_pending cookie is missing, expired or has a bad signature."""


class TokenExchangeError(Exception):
    """The provider refused to swap the code for tokens, or answered with nonsense."""


class IdTokenError(Exception):
    """The id_token failed one of the five checks in step 6."""


# --- PKCE (RFC 7636) --------------------------------------------------------------


def pkce_challenge(code_verifier: str) -> str:
    """S256: base64url(sha256(verifier)) with the padding stripped."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def make_pkce_pair() -> tuple[str, str]:
    """Step 1. Return (code_verifier, code_challenge).

    The challenge goes out in the authorize URL (step 2). The verifier stays in the
    pending cookie and is revealed only at the token exchange (step 5). The provider
    hashes what it gets in step 5 and compares with what it saw in step 2.
    """
    code_verifier = secrets.token_urlsafe(64)  # 86 characters, inside the 43..128 the RFC allows
    return code_verifier, pkce_challenge(code_verifier)


# --- Pending-login cookie ---------------------------------------------------------


def _serializer() -> URLSafeTimedSerializer:
    # Signed, not encrypted: the browser can read the values but cannot change them.
    # None of them is secret on its own; what matters is that they cannot be forged.
    return URLSafeTimedSerializer(get_settings().secret_key, salt="oauth-pending")


def pack_pending(provider: str, state: str, nonce: str, code_verifier: str) -> str:
    """Step 1. Everything the callback needs to recognise this login attempt."""
    return _serializer().dumps(
        {"provider": provider, "state": state, "nonce": nonce, "code_verifier": code_verifier}
    )


def unpack_pending(value: str | None) -> dict:
    """Step 4. Verify signature and age, return the dict from pack_pending."""
    if not value:
        raise PendingLoginError("no pending login; start again from /auth/{provider}/login")
    try:
        return _serializer().loads(value, max_age=get_settings().pending_login_seconds)
    except SignatureExpired as exc:
        raise PendingLoginError("pending login expired; start again") from exc
    except BadSignature as exc:
        raise PendingLoginError("pending login cookie is invalid") from exc


# --- Token exchange (step 5) -----------------------------------------------------


async def exchange_code(
    http: httpx.AsyncClient,
    provider: Provider,
    *,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict:
    """Step 5. Server to server: the browser never sees this request or its response.

    The provider checks that the code is real and unused, that client_secret matches,
    and that sha256(code_verifier) equals the code_challenge it saw in step 2.
    """
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,  # must equal the one sent in step 2, exactly
        "client_id": provider.client_id,
        "client_secret": provider.client_secret,
        "code_verifier": code_verifier,
    }
    # Accept: application/json is for GitHub (Phase 1b), which otherwise answers form-encoded.
    response = await http.post(
        provider.token_endpoint, data=form, headers={"Accept": "application/json"}
    )

    if response.status_code != 200:
        # RFC 6749 section 5.2: errors are JSON with "error" and optional "error_description".
        try:
            body = response.json()
        except ValueError:
            body = {"error": f"http {response.status_code}", "error_description": response.text[:200]}
        raise TokenExchangeError(f"{body.get('error')}: {body.get('error_description', '')}".strip())

    tokens = response.json()
    if "access_token" not in tokens:
        raise TokenExchangeError("token response has no access_token")
    return tokens


# --- ID token (step 6) -----------------------------------------------------------

_jwks_clients: dict[str, PyJWKClient] = {}


def jwks_client_for(provider: Provider) -> PyJWKClient:
    """One cached JWKS client per provider. It refetches when it meets an unknown kid,
    which is how key rotation just works."""
    assert provider.jwks_uri, f"{provider.name}: no jwks_uri (discovery not loaded?)"
    if provider.jwks_uri not in _jwks_clients:
        _jwks_clients[provider.jwks_uri] = PyJWKClient(provider.jwks_uri, cache_keys=True)
    return _jwks_clients[provider.jwks_uri]


def verify_id_token_with_key(id_token: str, key, provider: Provider, expected_nonce: str) -> dict:
    """Step 6, the five checks, given the public key that should have signed the token.

    1. signature, with the algorithm pinned to RS256 by us, never read from the token
    2. iss == provider.issuer
    3. aud == provider.client_id
    4. exp in the future, with a minute of leeway for clock drift
    5. nonce == what we saved in step 1
    """
    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=provider.client_id,
            issuer=provider.issuer,
            leeway=60,
            options={"require": ["exp", "iat", "sub", "nonce"]},
        )
    except jwt.PyJWTError as exc:
        raise IdTokenError(f"id_token rejected: {exc}") from exc

    if not secrets.compare_digest(str(claims["nonce"]).encode(), expected_nonce.encode()):
        raise IdTokenError("id_token rejected: nonce mismatch")
    return claims


def verify_id_token(id_token: str, provider: Provider, expected_nonce: str) -> dict:
    """Step 6. Resolve the signing key from the provider's JWKS, then run the five checks."""
    try:
        signing_key = jwks_client_for(provider).get_signing_key_from_jwt(id_token)
    except jwt.PyJWTError as exc:
        raise IdTokenError(f"could not resolve signing key: {exc}") from exc
    return verify_id_token_with_key(id_token, signing_key.key, provider, expected_nonce)


# --- Who is this user? -----------------------------------------------------------


@dataclass
class Identity:
    iss: str
    sub: str
    email: str | None
    name: str | None
    email_verified: bool


async def identity_from_tokens(provider: Provider, tokens: dict, expected_nonce: str) -> Identity:
    """Turn a token response into a verified identity.

    OIDC providers: verify the id_token (step 6). That is the whole point of OIDC.
    Plain OAuth providers (GitHub, Phase 1b): call their user endpoint instead, and
    accept that nothing about the answer is signed or audience-bound.
    """
    if provider.oidc:
        id_token = tokens.get("id_token")
        if not id_token:
            raise IdTokenError("provider returned no id_token; was 'openid' in the scope?")
        # PyJWKClient fetches over blocking urllib, so keep it off the event loop.
        claims = await run_in_threadpool(verify_id_token, id_token, provider, expected_nonce)
        return Identity(
            iss=claims["iss"],
            sub=str(claims["sub"]),
            email=claims.get("email"),
            name=claims.get("name"),
            email_verified=bool(claims.get("email_verified", False)),
        )

    raise NotImplementedError(f"{provider.name}: non-OIDC identity lookup arrives in Phase 1b")
