"""Provider registry. PLAN.md, Phase 1, "Provider registry".

Every identity provider the BFF can log in with is one Provider entry.
Phases 1b (GitHub), 2 (Keycloak) and 4 (your own OP) add entries here.
The auth routes must never need to change for a new provider.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException, Request

from .config import get_settings

log = logging.getLogger("bff.providers")


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

    def redirect_uri(self, bff_origin: str) -> str:
        """The callback URL registered with the provider.

        It is sent in step 2 and again in step 5, and the provider requires both to
        match the registered value character for character.
        """
        return f"{bff_origin}/auth/{self.name}/callback"


class ProviderRegistry:
    def __init__(self, providers: dict[str, Provider]):
        self._providers = providers

    def names(self) -> list[str]:
        return list(self._providers)

    def get(self, name: str) -> Provider:
        return self._providers[name]

    async def load(self, http: httpx.AsyncClient) -> None:
        for provider in self._providers.values():
            await load_discovery(provider, http)


def build_registry() -> ProviderRegistry:
    s = get_settings()
    if not s.google_client_id or not s.google_client_secret:
        log.warning("google: GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set in bff/.env")
    return ProviderRegistry(
        {
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
    )


async def load_discovery(provider: Provider, http: httpx.AsyncClient) -> None:
    """Fill the provider's endpoints from its discovery document.

    The document is public JSON at a well-known path. It is the only thing the BFF
    needs to know about an OIDC provider besides the client credentials, which is
    what makes swapping providers in Phases 2 and 4 a config change.
    """
    if not provider.oidc or provider.discovery_url is None:
        return

    response = await http.get(provider.discovery_url)
    response.raise_for_status()
    doc = response.json()

    provider.issuer = doc["issuer"]
    provider.authorization_endpoint = doc["authorization_endpoint"]
    provider.token_endpoint = doc["token_endpoint"]
    provider.jwks_uri = doc["jwks_uri"]
    provider.userinfo_endpoint = doc.get("userinfo_endpoint")

    if "S256" not in doc.get("code_challenge_methods_supported", []):
        log.warning("%s: discovery does not advertise PKCE S256", provider.name)

    log.info(
        "%s: discovery loaded. issuer=%s authorize=%s token=%s jwks=%s",
        provider.name,
        provider.issuer,
        provider.authorization_endpoint,
        provider.token_endpoint,
        provider.jwks_uri,
    )


def get_provider(provider: str, request: Request) -> Provider:
    """FastAPI dependency: resolve the {provider} path parameter to a registry entry."""
    registry: ProviderRegistry = request.app.state.registry
    try:
        return registry.get(provider)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown provider {provider!r}") from None
