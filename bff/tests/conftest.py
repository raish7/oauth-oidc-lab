import os

import pytest
from fastapi.testclient import TestClient

# Real environment variables beat .env, so these defaults keep the tests
# independent of whatever is in your local .env.
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("TOKEN_ENC_KEY", "test-not-a-real-fernet-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://lab:lab@localhost:5434/oauth_lab")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")
os.environ.setdefault("BFF_ORIGIN", "http://localhost:8000")

# A provider with fixed endpoints, so tests never fetch a real discovery document.
FAKE_ISSUER = "https://idp.test"


@pytest.fixture
def registry():
    from app.providers import Provider, ProviderRegistry

    return ProviderRegistry(
        {
            "google": Provider(
                name="google",
                client_id="test-client-id",
                client_secret="test-client-secret",
                scopes=["openid", "email", "profile"],
                issuer=FAKE_ISSUER,
                authorization_endpoint=f"{FAKE_ISSUER}/authorize",
                token_endpoint=f"{FAKE_ISSUER}/token",
                jwks_uri=f"{FAKE_ISSUER}/jwks",
                userinfo_endpoint=f"{FAKE_ISSUER}/userinfo",
                extra_authorize_params={"access_type": "offline", "prompt": "consent"},
            )
        }
    )


@pytest.fixture
def fastapi_app(registry):
    from app.main import create_app

    application = create_app()
    application.state.registry = registry  # lifespan sees this and skips discovery
    return application


@pytest.fixture
def client(fastapi_app) -> TestClient:
    # `with` runs the lifespan, which creates the shared httpx client.
    with TestClient(fastapi_app) as test_client:
        yield test_client
