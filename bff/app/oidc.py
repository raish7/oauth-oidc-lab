"""Protocol helpers: PKCE, the pending-login cookie, ID token verification.

Phase 1 fills these in. Each docstring names the WORKFLOW.md step it implements.
"""

from .providers import Provider


def make_pkce_pair() -> tuple[str, str]:
    """Step 1. Return (code_verifier, code_challenge).

    verifier: secrets.token_urlsafe, 43 to 128 characters.
    challenge: base64url(sha256(verifier)) with no padding. RFC 7636, S256.
    """
    raise NotImplementedError("PLAN.md Phase 1: step 1")


def pack_pending(provider: str, state: str, nonce: str, code_verifier: str) -> str:
    """Step 1. Signed, timestamped value for the oauth_pending cookie.

    itsdangerous.URLSafeTimedSerializer(settings.secret_key, salt="oauth-pending").
    """
    raise NotImplementedError("PLAN.md Phase 1: step 1")


def unpack_pending(value: str) -> dict:
    """Step 4. Verify signature and age (settings.pending_login_seconds). Raise on failure."""
    raise NotImplementedError("PLAN.md Phase 1: step 4")


def verify_id_token(id_token: str, provider: Provider, expected_nonce: str) -> dict:
    """Step 6. Verify and return the claims.

    1. signature via PyJWKClient(provider.jwks_uri), algorithms=["RS256"] pinned
    2. iss == provider.issuer
    3. aud == provider.client_id
    4. exp in the future, leeway=60
    5. nonce == expected_nonce, compared with secrets.compare_digest
    """
    raise NotImplementedError("PLAN.md Phase 1: step 6")
