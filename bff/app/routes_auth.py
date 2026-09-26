"""/auth routes. WORKFLOW.md steps 1, 4 to 8, plus /me and /logout.

Routes are parameterised on {provider} from day one so Phases 1b, 2 and 4
add providers in providers.py without touching this file.
"""

import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from .config import Settings, get_settings
from .oidc import (
    PENDING_COOKIE,
    IdTokenError,
    PendingLoginError,
    TokenExchangeError,
    exchange_code,
    identity_from_tokens,
    make_pkce_pair,
    pack_pending,
    unpack_pending,
)
from .providers import Provider, get_provider

log = logging.getLogger("bff.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _not_yet(task: str) -> HTTPException:
    return HTTPException(status_code=501, detail=f"Not implemented yet: PLAN.md Phase 1, {task}")


def _fail(status: int, detail: str) -> JSONResponse:
    """Error response that also clears the pending cookie, so a failed attempt
    cannot be retried against the same state/nonce/verifier."""
    response = JSONResponse(status_code=status, content={"detail": detail})
    response.delete_cookie(PENDING_COOKIE, path="/auth")
    return response


@router.get("/{provider}/login")
async def login(
    prov: Provider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
):
    """Step 1: generate state, nonce and PKCE, remember them, send the browser to the provider."""
    state = secrets.token_urlsafe(32)  # anti-CSRF, checked in step 4
    nonce = secrets.token_urlsafe(32)  # anti-replay, must come back inside the id_token in step 6
    code_verifier, code_challenge = make_pkce_pair()

    params = {
        "response_type": "code",
        "client_id": prov.client_id,
        "redirect_uri": prov.redirect_uri(settings.bff_origin),
        "scope": " ".join(prov.scopes),
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        **prov.extra_authorize_params,
    }
    if prov.oidc:
        params["nonce"] = nonce

    response = RedirectResponse(f"{prov.authorization_endpoint}?{urlencode(params)}", status_code=302)
    response.set_cookie(
        PENDING_COOKIE,
        pack_pending(prov.name, state, nonce, code_verifier),
        max_age=settings.pending_login_seconds,
        httponly=True,
        # Lax, not Strict: the provider's redirect back to /auth/.../callback is a
        # cross-site navigation, and a Strict cookie is not sent on it.
        samesite="lax",
        path="/auth",
        secure=settings.bff_origin.startswith("https://"),
    )
    return response


@router.get("/{provider}/callback")
async def callback(
    request: Request,
    prov: Provider = Depends(get_provider),
    settings: Settings = Depends(get_settings),
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
):
    """Steps 4 to 6: is this our login, swap the code for tokens, verify who the user is."""

    # Step 4a: does this browser have a login in progress at all?
    try:
        pending = unpack_pending(request.cookies.get(PENDING_COOKIE))
    except PendingLoginError as exc:
        return _fail(400, str(exc))
    if pending["provider"] != prov.name:
        return _fail(400, "pending login is for a different provider")

    # Step 4b: the CSRF check. The state in the URL must be the one this browser was
    # given in step 1. An attacker's callback URL carries the attacker's state.
    if state is None or not secrets.compare_digest(pending["state"].encode(), state.encode()):
        return _fail(400, "state mismatch: this callback does not belong to a login this browser started")

    # The provider may have said no: user cancelled, client misconfigured, scope refused.
    if error:
        return _fail(400, f"provider returned {error}: {error_description or ''}".strip())
    if not code:
        return _fail(400, "callback has no code")

    # Step 5: code -> tokens, server to server.
    try:
        tokens = await exchange_code(
            request.app.state.http,
            prov,
            code=code,
            code_verifier=pending["code_verifier"],
            redirect_uri=prov.redirect_uri(settings.bff_origin),
        )
    except TokenExchangeError as exc:
        return _fail(502, f"token exchange failed: {exc}")
    # Keys only. Never log token values.
    log.info(
        "%s: token response keys=%s expires_in=%s scope=%s",
        prov.name, sorted(tokens), tokens.get("expires_in"), tokens.get("scope"),
    )

    # Step 6: verify the id_token and learn who this is.
    try:
        identity = await identity_from_tokens(prov, tokens, pending["nonce"])
    except IdTokenError as exc:
        return _fail(401, str(exc))

    # Steps 7 and 8 (store user + session, set sid cookie, redirect to the app) come next.
    # Until then, show what was verified. This response goes away in the next stage.
    response = JSONResponse(
        {
            "verified": True,
            "provider": prov.name,
            "iss": identity.iss,
            "sub": identity.sub,
            "email": identity.email,
            "email_verified": identity.email_verified,
            "name": identity.name,
            "token_response_keys": sorted(tokens),
            "expires_in": tokens.get("expires_in"),
            "note": "temporary: next stage stores a session and redirects to the app",
        }
    )
    response.delete_cookie(PENDING_COOKIE, path="/auth")
    return response


@router.get("/me")
async def me():
    """Return the logged-in user from the session cookie."""
    raise _not_yet("sessions")


@router.post("/logout")
async def logout():
    """Delete the session row and clear the cookie."""
    raise _not_yet("sessions")
