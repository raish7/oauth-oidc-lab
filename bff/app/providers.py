"""Provider registry. PLAN.md, Phase 1, "Provider registry".

Every identity provider the BFF can log in with is one Provider entry.
Phases 1b (GitHub), 2 (Keycloak) and 4 (your own OP) add entries here.
The auth routes must never need to change for a new provider.
"""

from dataclasses import dataclass, field

from .config import get_settings


@dataclass
class Provider:
    name: str
    client_id: str
    client_secret: str
    scopes: list[str]
    # False for plain-OAuth providers such as GitHub (Phase 1b): no id_token, no discovery.
    oidc: bool = True

    # OIDC providers: filled from the discovery document by load_discovery().
    # Non-OIDC providers: hard-coded in build_registry().
    discovery_url: str | None = None
    issuer: str | None = None
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_uri: str | None = None
    userinfo_endpoint: str | None = None

    # Provider-specific query parameters added to the authorize URL.
    extra_authorize_params: dict[str, str] = field(default_factory=dict)


def build_registry() -> dict[str, Provider]:
    s = get_settings()
    return {
        "google": Provider(
            name="google",
            client_id=s.google_client_id,
            client_secret=s.google_client_secret,
            scopes=["openid", "email", "profile"],
            discovery_url="https://accounts.google.com/.well-known/openid-configuration",
            # Without these Google returns no refresh_token. PLAN.md, Phase 1, step 1.
            extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        ),
    }


async def load_discovery(provider: Provider) -> None:
    """Phase 1: GET provider.discovery_url with httpx and fill issuer, the endpoints and jwks_uri."""
    raise NotImplementedError("PLAN.md Phase 1: provider registry, discovery")
