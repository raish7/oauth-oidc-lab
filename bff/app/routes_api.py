"""/api routes: things the BFF does on the user's behalf with the stored access token.

WORKFLOW.md step 9a in, 9b out.
"""

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["api"])


@router.get("/profile")
async def profile():
    """Call the provider's userinfo endpoint with the session's access token."""
    raise HTTPException(status_code=501, detail="Not implemented yet: PLAN.md Phase 1, /api/profile")
