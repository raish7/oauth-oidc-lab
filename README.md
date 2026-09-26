# OAuth 2.0 / OIDC lab

A hands-on lab for learning OAuth 2.0 and OpenID Connect by building every part of the system:
a hand-rolled OAuth client (FastAPI, backend-for-frontend pattern), a React/Next.js frontend,
and later a resource server and a self-written OpenID Provider.

| Read this | For |
|---|---|
| `architecture.svg` | The picture: five boxes, numbered arrows, the trust boundary |
| `WORKFLOW.md` | What happens on each arrow, with real requests and responses |
| `PLAN.md` | Phased task list with "done when" and "break it" exercises |

## Layout

```
bff/               FastAPI, the OAuth client        :8000   Phase 1
frontend/          Next.js, pure client-side app    :3000   Phase 1
resource-server/   FastAPI, protected API           :8001   Phase 3
provider/          FastAPI, your own OpenID Provider :8002  Phase 4
docker-compose.yml Postgres :5434, Keycloak :8080 (profile "keycloak", Phase 2)
```

## Run (Phase 0 state)

Postgres:

```
docker compose up -d postgres
```

BFF:

```
cd bff
cp .env.example .env        # then fill in GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET
uv sync
uv run python -m app.migrate
uv run uvicorn app.main:app --reload --port 8000
```

Check `http://localhost:8000/health` and `http://localhost:8000/health/db`.

Frontend:

```
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open `http://localhost:3000`. The page calls the BFF's health endpoint with credentials on,
which proves the CORS configuration before any auth code exists.

Tests:

```
cd bff
uv run pytest
```

## Google OAuth client (one-time setup, free, no billing account needed)

Use a personal Google account rather than a Workspace (work) account, so no organisation
policy gets in the way.

1. Google Cloud Console, create or pick a project. Skip any free-trial or billing prompt.
2. Open Google Auth Platform (older menus call it APIs & Services, OAuth consent screen).
   Under Branding set the app name. Under Audience choose External, keep it in Testing,
   and add your own Google account as a test user.
3. Under Clients create an OAuth client of type Web application.
4. Authorized redirect URI: `http://localhost:8000/auth/google/callback`. Nothing on port 3000.
5. Copy the client ID and secret into `bff/.env`.

While the app is in Testing, Google expires refresh tokens after 7 days. Expect to sign in
again about once a week. Publishing to Production removes that limit and needs no review
for the `openid email profile` scopes.
