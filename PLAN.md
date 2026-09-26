# OAuth 2.0 / OIDC lab: implementation plan

Companion to `architecture.svg` and `WORKFLOW.md`. Step numbers below refer to the arrows in the diagram.

Rules for the whole lab:

- No auth libraries in the BFF. `httpx` for HTTP, `PyJWT` for signature checks, the standard library for randomness and hashing. Authlib is allowed only as a reference client to compare against.
- Each box in the diagram is its own process on its own port. No shortcuts through shared memory.
- Every phase ends with a "done when" list. Do not start the next phase until it passes.
- Every phase has "break it" exercises. They are not optional. Each one turns a security rule into something you have seen fail.

Rough effort: P0 half a day, P1 one weekend, P1b one evening, P2 two evenings, P3 two evenings, P4 two weekends.

---

## Phase 0: Scaffold

### Repo layout

```
oauth-oidc-lab/
  architecture.svg
  WORKFLOW.md
  PLAN.md
  docker-compose.yml         # keycloak (P2); postgres if you don't reuse :5433
  bff/                       # FastAPI :8000  (P1)
    app/
      main.py                # app factory, CORS, routers
      config.py              # pydantic-settings, reads .env
      providers.py           # provider registry: discovery, endpoints, client creds
      oidc.py                # verify_id_token, PKCE helpers, pending-login cookie
      routes_auth.py         # /auth/{provider}/login, /callback, /me, /logout
      routes_api.py          # /api/* that use the stored access token
      sessions.py            # current_user dependency, refresh-if-expired
      db.py                  # engine, models: users, sessions
    tests/
    .env.example
    pyproject.toml
  frontend/                  # Next.js :3000  (P1)
  resource-server/           # FastAPI :8001  (P3)
  provider/                  # FastAPI :8002  (P4)
```

### Tasks

- [ ] `git init` in this folder. Commit the three docs first.
- [ ] Python 3.12 venv per service. Dependencies for the BFF: `fastapi`, `uvicorn[standard]`, `httpx`, `pyjwt[crypto]`, `itsdangerous`, `pydantic-settings`, `sqlalchemy`, `psycopg[binary]`, `cryptography`, `pytest`, `pytest-asyncio`.
- [ ] Database: create `oauth_lab` on your existing Postgres on port 5433, or add a postgres service to compose on another port. Two tables to start:
  ```sql
  CREATE TABLE users (
    id          bigserial PRIMARY KEY,
    iss         text NOT NULL,
    sub         text NOT NULL,
    email       text,
    name        text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (iss, sub)
  );
  CREATE TABLE sessions (
    sid            text PRIMARY KEY,
    user_id        bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider       text NOT NULL,
    access_token   bytea NOT NULL,      -- encrypted
    refresh_token  bytea,               -- encrypted
    token_expires_at   timestamptz NOT NULL,
    session_expires_at timestamptz NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now()
  );
  ```
- [ ] Next.js app on port 3000. App Router is fine, but treat it as a client-side app: no server actions, no route handlers for auth.
- [ ] Google Cloud Console: create an OAuth 2.0 client of type Web application. Authorized redirect URI: `http://localhost:8000/auth/google/callback`. Configure the consent screen as External, Testing, and add your own Google account as a test user.
- [ ] `.env` with `SECRET_KEY`, `TOKEN_ENC_KEY` (Fernet key), `DATABASE_URL`, `FRONTEND_ORIGIN=http://localhost:3000`, and the Google client id and secret. Commit `.env.example`, never `.env`.

### Done when

- [ ] `GET http://localhost:8000/health` returns 200, `http://localhost:3000` renders, both tables exist.

---

## Phase 1: Hand-rolled client against Google

Implements arrows 1 to 9a of the diagram against one OIDC provider. GitHub comes in Phase 1b, once this works.

### Tasks

**Provider registry**

- [ ] At startup, fetch Google's discovery document from `https://accounts.google.com/.well-known/openid-configuration` and keep `issuer`, `authorization_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint`.
- [ ] Make the registry data-driven from the start, and keep the routes parameterized as `/auth/{provider}/...` even with one provider. Phases 1b, 2 and 4 add providers without touching the flow.
- [ ] Put the "who is this user" logic behind one function per provider, `identity_from_tokens(provider, token_response) -> (iss, sub, email, name)`. For Google it verifies the `id_token`. GitHub will later implement it by calling `/user`. The callback route calls this function and never knows the difference.

**Step 1: `GET /auth/{provider}/login`**

- [ ] Generate `state`, `nonce` and `code_verifier` with `secrets.token_urlsafe`. Derive `code_challenge` as base64url of the SHA-256 of the verifier, no padding.
- [ ] Pack the three values plus the provider name into a signed cookie with `itsdangerous.URLSafeTimedSerializer`. Cookie: `oauth_pending`, `HttpOnly`, `SameSite=Lax`, `Path=/auth`, `Max-Age=600`.
- [ ] Redirect to the authorize URL with `response_type=code`, `client_id`, `redirect_uri`, `scope`, `state`, `nonce`, `code_challenge`, `code_challenge_method=S256`. For Google add `access_type=offline` and `prompt=consent`, otherwise you will not get a refresh token.
- [ ] Scope: `openid email profile`.

**Step 4 and 5: `GET /auth/{provider}/callback`**

- [ ] If the provider redirected with `error=...`, render or return that error and stop.
- [ ] Load and verify the `oauth_pending` cookie. Reject with 400 if missing, expired or badly signed.
- [ ] Compare `state` with `secrets.compare_digest`. Mismatch is 400.
- [ ] POST the token endpoint with `grant_type=authorization_code`, `code`, `redirect_uri`, `client_id`, `client_secret`, `code_verifier`.
- [ ] Delete the `oauth_pending` cookie in the response regardless of outcome.

**Step 6: `verify_id_token`**

- [ ] One `PyJWKClient` per provider, built from `jwks_uri`, with caching on.
- [ ] `jwt.decode` with `algorithms=["RS256"]`, `audience=client_id`, `issuer=issuer`, `leeway=60`, and `options={"require": ["exp", "iat", "sub", "nonce"]}`.
- [ ] Compare `nonce` with the pending cookie value using `compare_digest`.

**Step 7 and 8: persist and set the session**

- [ ] Upsert `users` on `(iss, sub)`.
- [ ] Encrypt both tokens with Fernet before insert. Generate `sid` with `secrets.token_urlsafe(32)`.
- [ ] `session_expires_at` = now + 30 days. `token_expires_at` = now + `expires_in`.
- [ ] Set cookie `sid`, `HttpOnly`, `SameSite=Lax`, `Path=/`, `Max-Age` matching the session. Redirect to `FRONTEND_ORIGIN`.

**Sessions and API**

- [ ] `current_user` dependency: read `sid`, load session joined to user, 401 if missing or past `session_expires_at`.
- [ ] `GET /auth/me` returns id, email, name, provider.
- [ ] `POST /auth/logout` deletes the session row and clears the cookie.
- [ ] `get_access_token(session)`: if `token_expires_at` has passed, POST the token endpoint with `grant_type=refresh_token`, store the new token and the new refresh token if one was returned, then return it.
- [ ] `GET /api/profile`: call Google's userinfo endpoint with the access token and return the JSON. This proves the stored access token works.
- [ ] `CORSMiddleware` with `allow_origins=[FRONTEND_ORIGIN]`, `allow_credentials=True`, and explicit methods and headers.

**Frontend**

- [ ] Home page with one anchor, `Sign in with Google`, a plain `<a href="http://localhost:8000/auth/google/login">`. Render it from a list of providers so the next one is a single entry.
- [ ] On load, `fetch('/auth/me', { credentials: 'include' })`. If 200 show the profile, a `Call API` button that fetches `/api/profile`, and a `Logout` button. If 401 show the sign-in links.
- [ ] Put the BFF base URL in one env variable. No token handling anywhere in the frontend.

**Tests**

- [ ] Unit tests for `verify_id_token` using an RSA key pair generated in the test. Sign tokens yourself and assert rejection for: wrong key, wrong `aud`, wrong `iss`, expired, missing `nonce`, wrong `nonce`, `alg=none`, `alg=HS256` signed with the public key as the secret.
- [ ] Unit test for the PKCE derivation against the RFC 7636 appendix B test vector.
- [ ] Route test for the callback with a mismatched `state` returning 400.

### Done when

- [ ] Login with Google lands you on the frontend showing your name.
- [ ] DevTools Network with Preserve log shows the redirect chain and no token in any URL, header or body the browser received.
- [ ] Set `token_expires_at` in the past by hand and call `/api/profile`. It succeeds and the row now has a new token.
- [ ] Logout, then `/auth/me` returns 401 and the session row is gone.
- [ ] All unit tests pass.

### Break it

- [ ] Comment out the `state` comparison. Start a login in a private window, copy the callback URL before it completes, open it in your normal window. You are now logged in as the private window's account. Put the check back.
- [ ] Change `SameSite=Lax` to `Strict` on `oauth_pending`. Every login now fails with "no pending login". Understand why, then revert.
- [ ] Remove `access_type=offline` from the Google authorize URL. Log in. Note that `refresh_token` is missing from the token response.
- [ ] Optional: build a second Next.js page that does the whole flow in the browser as a public client with PKCE and holds the tokens in React state. Look at where the tokens are visible. Do not merge it into the main app.

---

## Phase 1b: Add GitHub

GitHub speaks plain OAuth 2.0 with no OIDC layer. Adding it after Google shows exactly what OIDC gave you, and proves the registry can take a non-OIDC provider with one small branch. One evening.

### Tasks

- [ ] GitHub: Settings, Developer settings, OAuth Apps, New. Callback URL `http://localhost:8000/auth/github/callback`. Add the client id and secret to `.env`.
- [ ] Registry entry with `oidc=False` and three hard-coded URLs: authorize `https://github.com/login/oauth/authorize`, token `https://github.com/login/oauth/access_token`, user `https://api.github.com/user`. No discovery document, no `jwks_uri`.
- [ ] Scope `read:user user:email`.
- [ ] Token request: send `Accept: application/json`, or GitHub answers in form encoding.
- [ ] `identity_from_tokens` for GitHub: call `GET /user` for `id`, `name` and `login`, then `GET /user/emails` for the primary verified email. `sub` is the numeric `id` as a string. `iss` is `https://github.com`.
- [ ] GitHub OAuth app tokens do not expire and there is no refresh token. Set `token_expires_at` far in the future and make the refresh path a no-op when the provider has no refresh support.
- [ ] Second sign-in link on the frontend, from the provider list.

### Done when

- [ ] Login with GitHub works through the same routes as Google.
- [ ] The diff for this phase touches the registry, the GitHub identity function, config and the frontend list. Nothing in the login route, the callback route or the session code.

### Reflect

- [ ] Write down, in three sentences, what you could verify for Google in step 6 that you could not verify for GitHub. That is the OAuth-versus-OIDC answer for an interview.

---

## Phase 2: Keycloak as the provider

Swaps the provider box in the diagram. The BFF must not change except for config.

### Tasks

- [ ] `docker-compose.yml` with `quay.io/keycloak/keycloak` running `start-dev` on port 8080, bootstrap admin user and password from env.
- [ ] In the admin console create realm `lab`. Create client `bff`: client authentication on, standard flow on, PKCE method `S256` under Advanced, valid redirect URI `http://localhost:8000/auth/keycloak/callback`, web origins `http://localhost:3000`. Copy the client secret.
- [ ] Create a user with a password, and a second user for later exercises.
- [ ] Add provider `keycloak` to the BFF registry with only: discovery URL `http://localhost:8080/realms/lab/.well-known/openid-configuration`, client id, client secret. Add a third sign-in link on the frontend.
- [ ] Log in. If anything in `routes_auth.py` or `oidc.py` had to change, that is a bug in Phase 1. Fix the abstraction, not the symptom.

### Explore the provider side

- [ ] Turn on `Consent required` on the client. Log in again and see the consent screen. Read the discovery document and the JWKS URL in the browser.
- [ ] Add a client scope with a custom mapper that puts a claim like `department` into the ID token. Watch it appear in the decoded token.
- [ ] Realm settings, Tokens: set access token lifespan to 1 minute. Watch your refresh path fire on the next `/api/profile` call.
- [ ] Turn on `Revoke Refresh Token` with max reuse 0. Refresh once, then try the old refresh token again with curl. It is rejected.
- [ ] Call the introspection endpoint with curl and a live access token, then with a revoked one.
- [ ] Create client `worker` with service accounts on. Write a 20-line script that gets a token with `grant_type=client_credentials` and decodes it. No user involved: this is machine-to-machine OAuth.

### Done when

- [ ] Keycloak login works through the same code path as Google.
- [ ] You can explain from memory what each of these did: consent required, PKCE S256, refresh token revocation, an audience or claim mapper, service accounts.

### Break it

- [ ] Create a second client `evil` in the same realm, log in through it with a throwaway script, and take its `id_token`. Add a temporary `POST /auth/token-login` to the BFF that accepts an `id_token` in the body and runs `verify_id_token` on it. The `aud` check rejects the evil token. Remove the `aud` check and it logs you in. Delete the endpoint afterwards.
- [ ] Rotate the realm's signing key in Keycloak. Your next login still works because `PyJWKClient` refetched on the unknown `kid`.

---

## Phase 3: Your own resource server

Adds the bottom-right box and arrows 9b and 9c.

### Tasks

**Keycloak**

- [ ] Create client scopes `photos:read` and `photos:write`. Attach both to client `bff` as optional scopes.
- [ ] Create a client scope `photos-api-audience` with an Audience mapper whose included custom audience is `photos-api`, and attach it to `bff` as a default scope. Without this the access token's `aud` is `account` and the resource server must reject it.
- [ ] BFF: request `scope=openid profile email photos:read photos:write` for the keycloak provider.

**Resource server on 8001**

- [ ] New FastAPI app. Config: discovery URL, expected audience `photos-api`.
- [ ] `require_token` dependency using `HTTPBearer`, a `PyJWKClient` on the provider's `jwks_uri`, and `jwt.decode` with `algorithms=["RS256"]`, `audience="photos-api"`, `issuer`. Return the claims.
- [ ] `require_scope("photos:read")` dependency factory that reads the space-separated `scope` claim and returns 403 if the scope is absent.
- [ ] `GET /photos` needs `photos:read`. `POST /photos` needs `photos:write`. Data can be an in-memory list keyed on `sub`.
- [ ] Swagger: `OAuth2AuthorizationCodeBearer` pointing at Keycloak's authorize and token URLs, plus `swagger_ui_init_oauth` with a public client `swagger` that has PKCE on and redirect URI `http://localhost:8001/docs/oauth2-redirect`. Run the flow from `/docs`.
- [ ] No cookies, no sessions, no CORS needed. Only the BFF calls this service.

**BFF**

- [ ] `GET /api/photos` and `POST /api/photos`: load session, `get_access_token` with refresh, call the resource server with `Authorization: Bearer`, return its response and status code.
- [ ] Frontend: a Photos section with a list and an add form, all through the BFF.

**Tests**

- [ ] Unit tests for `require_token` and `require_scope` with self-signed tokens: wrong audience 401, expired 401, missing scope 403, valid 200.

### Done when

- [ ] Browser to BFF to resource server to data works end to end.
- [ ] A curl with no token gets 401, with a Google access token gets 401 (wrong issuer), with a Keycloak token that lacks `photos:write` gets 403 on POST.
- [ ] The Swagger Authorize button completes the flow against Keycloak.

### Break it

- [ ] Remove the audience mapper in Keycloak. Every call now fails with invalid audience. Understand that this is the resource server protecting itself, then restore it.
- [ ] Send the `id_token` instead of the access token as the bearer. It is rejected because its `aud` is the BFF's client id, not `photos-api`. This is why the two tokens are never interchangeable.

---

## Phase 4: Your own OpenID Provider

Replaces the provider box with code you wrote. The BFF and the resource server change only by config.

### Storage

- [ ] Same Postgres, separate schema or database. Tables:
  - `op_users`: id, username, password_hash (argon2 via `argon2-cffi`), email, name.
  - `op_clients`: client_id, client_secret_hash, redirect_uris (text[]), allowed_scopes (text[]), is_public.
  - `op_auth_codes`: code_hash, client_id, user_id, redirect_uri, scope, nonce, code_challenge, expires_at, used_at.
  - `op_refresh_tokens`: token_hash, client_id, user_id, scope, expires_at, revoked_at.
  - `op_consents`: user_id, client_id, scopes, granted_at.
  - `op_login_sessions`: sid, user_id, auth_time, expires_at. The provider's own login cookie, separate from the BFF's.

### Keys

- [ ] Generate an RSA 2048 key pair once with `cryptography`, store the PEM outside git, load at startup. `kid` = SHA-256 thumbprint of the public key, base64url.
- [ ] Sign every JWT with RS256 and put `kid` in the header.

### Endpoints

- [ ] `GET /.well-known/openid-configuration`: `issuer`, the five endpoint URLs, `jwks_uri`, `response_types_supported: ["code"]`, `grant_types_supported`, `code_challenge_methods_supported: ["S256"]`, `id_token_signing_alg_values_supported: ["RS256"]`, `scopes_supported`, `token_endpoint_auth_methods_supported`.
- [ ] `GET /jwks.json`: `{"keys": [ {kty, use, kid, alg, n, e} ]}`. `jwt.algorithms.RSAAlgorithm.to_jwk` produces the JSON for you.
- [ ] `GET /authorize`:
  - Validate `client_id` exists. Validate `redirect_uri` is an exact string match against the registered list. If either fails, render an error page. Never redirect to an unregistered URI.
  - All other errors redirect back with `error=` and `error_description=` and the original `state`.
  - Require `response_type=code`, `scope` containing `openid`, `code_challenge` with `code_challenge_method=S256`. Public clients must send PKCE; confidential clients should.
  - If no provider login session: render the Jinja2 login form with the full authorize request carried in a signed hidden field or a short-lived cookie. `POST /login` verifies the password and creates the login session, then resumes the authorize request.
  - If consent for these scopes is not on record: render the consent page listing the scopes. `POST /consent` records it. Both forms carry a CSRF token.
  - Mint a code: 32 random bytes, store its SHA-256 with everything the token endpoint will need, 60-second expiry. Redirect to `redirect_uri` with `code` and `state`.
- [ ] `POST /token`:
  - Authenticate the client: HTTP Basic or `client_secret` in the body. Public clients authenticate by PKCE only.
  - `authorization_code`: look up by code hash. Reject if unknown, expired, already used, wrong client, or `redirect_uri` differs. Verify `sha256(code_verifier)` equals the stored challenge. Mark used. If a used code is presented again, revoke every token issued from it, as RFC 6749 requires.
  - Issue: `access_token` as a JWT with `iss`, `sub`, `aud` (the resource server id from the requested scopes), `scope`, `exp` 15 minutes, `client_id`. `id_token` with `iss`, `sub`, `aud` = client_id, `exp`, `iat`, `auth_time`, `nonce`, plus `email` and `name` if those scopes were granted. `refresh_token` as an opaque random string stored hashed.
  - `refresh_token`: validate, rotate (revoke old, issue new), issue a new access token.
  - `client_credentials`: confidential clients only, no user, `sub` = client_id.
- [ ] `GET /userinfo`: bearer access token, return claims allowed by its scope.
- [ ] `POST /revoke` per RFC 7009 and `POST /introspect` per RFC 7662. Both authenticate the client.
- [ ] `GET /logout` as `end_session_endpoint`: clear the provider login session, redirect to `post_logout_redirect_uri` if it is registered.

### Wire it in

- [ ] Register client `bff` and client `photos-api` in `op_clients` with a seed script. Add provider `local` to the BFF registry with discovery URL `http://localhost:8002/.well-known/openid-configuration`.
- [ ] Point the resource server's config at the same discovery URL. Arrows 9b and 9c now run entirely on your code.
- [ ] Use `http://localhost:8002` as the issuer, not `127.0.0.1`. The string in `iss` must match the discovery URL's origin exactly.

### Tests

- [ ] Route tests for `/authorize` error handling: bad `redirect_uri` renders an error and does not redirect; missing PKCE redirects with `invalid_request`.
- [ ] Token endpoint: code reuse returns `invalid_grant` and revokes; wrong verifier returns `invalid_grant`; wrong client secret returns `invalid_client`.
- [ ] Once this provider exists, run the Phase 1 BFF tests against it instead of self-signed tokens. Your own provider is now your test fixture.

### Final exam

- [ ] Your BFF logs in through your provider with no code change.
- [ ] Authlib's Starlette client, configured with only the discovery URL, client id and secret, logs in through your provider. If it does, your provider speaks standard OIDC.
- [ ] Stretch: run the OpenID Foundation conformance suite in Docker against your provider and see how many basic profile tests pass.

### Break it

- [ ] Send a code twice. Second call fails and the first call's tokens stop working at the resource server (you will need a token denylist or short expiry to demonstrate).
- [ ] Register `http://localhost:8000/auth/local/callback` and request `http://localhost:8000/auth/local/callback/../evil`. Exact matching rejects it.
- [ ] Hand-craft a token with `alg: none` and a token signed with a different key but your `kid`. Your resource server rejects both.

---

## Phase 5 (optional): take it somewhere real

- [ ] Add OIDC login to the multi-tenant tracker with Keycloak as the provider. Map a Keycloak group or a custom `tenant_id` claim to the tenant used by the row-level security policies.
- [ ] Production checklist: both origins under one parent domain or a Next.js rewrite proxy, `Secure` on every cookie, HTTPS everywhere, client secrets and the Fernet key from a secret manager, key rotation for your provider with two keys live in the JWKS during the overlap.

---

## Reading list, in the order they become relevant

- RFC 6749, OAuth 2.0 core: sections 4.1 (authorization code) and 10 (security).
- RFC 7636, PKCE. Short.
- OpenID Connect Core 1.0: sections 2 (ID token), 3.1 (code flow), 3.1.3.7 (ID token validation, your step 6).
- RFC 9700, OAuth 2.0 Security Best Current Practice. Explains every "why" in this plan.
- OAuth 2.1 draft. What the consolidated spec looks like with implicit and password grants removed.
- RFC 7517 (JWK), RFC 7519 (JWT), RFC 7009 (revocation), RFC 7662 (introspection), for Phase 4.
