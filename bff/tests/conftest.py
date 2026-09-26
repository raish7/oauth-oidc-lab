import os

import pytest
from fastapi.testclient import TestClient

# Real environment variables beat .env, so these defaults keep the tests
# independent of whatever is in your local .env.
os.environ.setdefault("SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("TOKEN_ENC_KEY", "test-not-a-real-fernet-key")
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://lab:lab@localhost:5434/oauth_lab")
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:3000")


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)
