"""/auth routes. WORKFLOW.md steps 1, 4 to 8, plus /me and /logout.

Routes are parameterised on {provider} from day one so Phases 1b, 2 and 4
add providers in providers.py without touching this file.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/auth", tags=["auth"])


def _not_yet(task: str) -> HTTPException:
    return HTTPException(status_code=501, detail=f"Not implemented yet: PLAN.md Phase 1, {task}")


@router.get("/{provider}/login")
async def login(provider: str):
    """Step 1: generate state, nonce, PKCE; set oauth_pending cookie; 302 to the provider."""
    raise _not_yet("step 1")


@router.get("/{provider}/callback")
async def callback(provider: str):
    """Steps 4 to 8: check state, exchange code, verify id_token, upsert user, create session."""
    raise _not_yet("steps 4 to 8")


@router.get("/me")
async def me():
    """Return the logged-in user from the session cookie."""
    raise _not_yet("sessions")


@router.post("/logout")
async def logout():
    """Delete the session row and clear the cookie."""
    raise _not_yet("sessions")
