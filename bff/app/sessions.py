"""Session cookie to user. WORKFLOW.md steps 7, 8 and 9a.

Phase 1 fills these in.
"""

from fastapi import HTTPException, Request

SESSION_COOKIE = "sid"


async def current_user(request: Request) -> dict:
    """Step 9a. Read the sid cookie, load session joined to user, 401 if missing or expired."""
    raise HTTPException(status_code=501, detail="Not implemented yet: PLAN.md Phase 1, sessions")


async def get_access_token(session: dict) -> str:
    """Section 5 of WORKFLOW.md. Refresh with the refresh_token if token_expires_at has passed."""
    raise NotImplementedError("PLAN.md Phase 1: refresh")
