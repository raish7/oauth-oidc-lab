# OAuth 2.0 / OIDC lab: how the workflow actually works

Companion to `architecture.svg`. Read this first; the diagram will make sense afterwards.
Every numbered step below matches a numbered arrow in the diagram.

![architecture](architecture.svg)

---

## 0. How to read the diagram

- **Boxes** are processes. Each one runs on its own port so you can watch them talk to each other.
- **Arrows** are HTTP requests. The number is the order in which they happen.
- **Dashed arrows** are 302 redirects. The browser is being told "go there next".
- **Orange arrows** carry tokens. Notice they all stay on the right side.
- **The dashed vertical line** is the trust boundary. Left of it, the user (or anyone with their laptop) can read everything. Right of it are your servers. The entire design has one rule: **tokens never cross that line.**

---

## 1. The cast

| Box in the diagram | What it really is | Port | Its one job |
|---|---|---|---|
| Browser | Your React / Next.js app | 3000 | Show the UI. Knows nothing about tokens. |
| FastAPI BFF | Your Python backend. BFF = backend-for-frontend. In OAuth terms it is the **client**; OIDC calls it the **relying party**. | 8000 | Do the entire OAuth dance on the browser's behalf and keep every secret. |
| Identity Provider | Whoever checks the user's password. OAuth calls it the **authorization server**; OIDC calls it the **OpenID Provider**. | Google/GitHub (internet), Keycloak 8080, your own 8002 | Log the user in, ask for consent, hand out tokens, publish the keys needed to verify them. |
| Postgres | Your database | 5434 | Remember who each user is and hold their tokens server-side. |
| FastAPI Resource Server | A second Python API that owns the protected data | 8001 | Accept a bearer token, verify it, return data. |

---

## 2. The whole thing in one paragraph

The old way: the user types their Google password into your app and your app stores it. Bad.

The OAuth way: your app sends the browser to Google. Google checks the password, asks the user "let this app see your profile?", and sends the browser back with a one-time **code**. Your backend swaps that code for **tokens** in a direct server-to-server call. Now your backend can act for the user, and the browser never saw a password or a token.

Everything below is that paragraph in slow motion.

---

## 3. A user signs in (arrows 1 to 8)

Setup: the user is on `http://localhost:3000` and clicks **Sign in with Google**.

### Step 1. Browser → BFF: `GET /auth/login`

The sign-in button is a plain link to `http://localhost:8000/auth/login`, not a `fetch()`. OAuth works by redirecting the whole browser window, and JavaScript fetches cannot follow a redirect to another site's login page.

The BFF does four things before answering:

1. Generates `state`: a random string. Used for CSRF protection in step 4.
2. Generates `nonce`: a random string. Must come back inside the ID token in step 6.
3. Generates `code_verifier` (random, 43 to 128 characters) and derives `code_challenge = base64url(sha256(code_verifier))`. This pair is PKCE.
4. Saves `state`, `nonce` and `code_verifier` somewhere it can find them again: a short-lived signed cookie, or a `pending_logins` table row.

Then it responds `302 Location: <the provider's authorize URL>`.

### Step 2. Browser → Provider: `GET /authorize`

The browser follows the redirect. The URL it lands on:

```
https://accounts.google.com/o/oauth2/v2/auth
  ?response_type=code
  &client_id=1234.apps.googleusercontent.com
  &redirect_uri=http://localhost:8000/auth/callback
  &scope=openid email profile
  &state=af0ifjsldkj
  &nonce=n-0S6_WzA2Mj
  &code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM
  &code_challenge_method=S256
```

Two things to notice:

- `redirect_uri` points at your **backend** on port 8000, not at the React app. You registered exactly this URL in Google Cloud Console, and Google refuses any other.
- `scope=openid` is what turns plain OAuth into OIDC. It says "I also want an ID token".

### Step 3. The user logs in and consents (on the provider's pages)

- The provider shows **its own** login page. Your app is not involved. That is the point.
- The provider shows a consent screen: "photo-lab wants to see your email and profile".
- The user clicks Allow.
- The provider mints an **authorization code**: random, single-use, expires within minutes, tied to this `client_id`, `redirect_uri` and `code_challenge`.
- The provider responds:

```
302 Location: http://localhost:8000/auth/callback?code=4/0AX4XfWh...&state=af0ifjsldkj
```

### Step 4. Browser → BFF: `GET /auth/callback?code=...&state=...`

The browser follows that redirect and lands back on your backend. This is the only moment the browser carries something security-relevant, the code. Step 5 shows why the code alone is useless.

The BFF:

1. Loads the pending login it saved in step 1.
2. Checks that `state` in the URL equals the saved one. If not, respond 400 and stop.

That check is the CSRF defence. Without it, an attacker could start a login with *their* account, take the callback URL, and trick your browser into finishing it, so you end up logged into the attacker's account and unknowingly save your data there.

### Step 5. BFF → Provider: `POST /token` (server to server)

The browser is not involved. Python calls the provider directly with httpx:

```
POST https://oauth2.googleapis.com/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=4/0AX4XfWh...
&redirect_uri=http://localhost:8000/auth/callback
&client_id=1234.apps.googleusercontent.com
&client_secret=GOCSPX-...
&code_verifier=dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk
```

The provider checks that the code exists and is unused, that `client_secret` matches, and that `sha256(code_verifier)` equals the `code_challenge` from step 2. If all pass:

```json
{
  "access_token": "ya29.a0AfH6SMB...",
  "expires_in": 3599,
  "refresh_token": "1//0gE4nZ...",
  "id_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6...",
  "token_type": "Bearer",
  "scope": "openid email profile"
}
```

**Why the code-then-token two-step?** The code travelled through the browser: address bar, history, proxy logs. The tokens travel only over this backend call. Stealing the code does not help an attacker, because the exchange also needs the `client_secret` and the `code_verifier`, and only the BFF has those.

### Step 6. The BFF verifies the ID token

`id_token` is a JWT: three base64url parts, `header.payload.signature`. The decoded payload:

```json
{
  "iss": "https://accounts.google.com",
  "sub": "110169484474386276334",
  "aud": "1234.apps.googleusercontent.com",
  "exp": 1758297600,
  "iat": 1758294000,
  "nonce": "n-0S6_WzA2Mj",
  "email": "user@example.com",
  "email_verified": true,
  "name": "Example User"
}
```

The BFF must check, in this order:

1. **Signature.** Fetch `https://accounts.google.com/.well-known/openid-configuration`, read `jwks_uri`, fetch the keys, verify the RS256 signature. PyJWT's `PyJWKClient` does the fetching and caching.
2. **`iss`** equals the provider you expected.
3. **`aud`** equals your `client_id`. This stops a token issued to some other app from logging someone in here.
4. **`exp`** is in the future.
5. **`nonce`** equals the one saved in step 1.

Skip any of these and the login is forgeable. The one people forget is `aud`.

### Step 7. BFF → Postgres

- Upsert the user: `INSERT ... ON CONFLICT (iss, sub) DO UPDATE`. Key on `sub`, never on email. Emails change and can be reassigned; `sub` is stable.
- Insert a session row: `sid` (32 random bytes), `user_id`, `access_token`, `refresh_token`, `expires_at = now + expires_in`.

### Step 8. BFF → Browser: `Set-Cookie` and 302 back to the app

```
HTTP/1.1 302 Found
Location: http://localhost:3000/
Set-Cookie: sid=7c9e6679f4...; HttpOnly; SameSite=Lax; Path=/
```

- `HttpOnly`: JavaScript cannot read it, so an XSS bug cannot steal it.
- `SameSite=Lax`: requests started from other sites do not carry it.
- Add `Secure` in production.
- The cookie value is a random ID that points at a database row. It is not a token. If it leaks, delete the row and it is dead.

Login is done. The ledger at this moment:

| Who | Holds |
|---|---|
| Browser | `sid` cookie |
| BFF / Postgres | `access_token`, `refresh_token`, user record |
| Provider | the password, the consent record |

---

## 4. The user uses the app (arrows 9a to 9c)

### Step 9a. Browser → BFF: `fetch('/api/photos', { credentials: 'include' })`

- React calls the backend. `credentials: 'include'` tells the browser to attach the `sid` cookie even though the origins differ.
- CORS: FastAPI must answer with `Access-Control-Allow-Origin: http://localhost:3000` (the exact origin) and `Access-Control-Allow-Credentials: true`. Browsers reject a `*` origin when credentials are included.
- The BFF reads `sid`, loads the session row, and now knows the user and has their `access_token`.

### Step 9b. BFF → Resource Server: `Authorization: Bearer <access_token>`

```
GET http://localhost:8001/photos
Authorization: Bearer eyJhbGciOiJSUzI1NiIs...
```

Orange in the diagram: a token in flight, server to server.

### Step 9c. The Resource Server verifies the token

Same checklist as step 6, applied to the access token: fetch the provider's JWKS (cached), verify the signature, check `iss` and `exp`, check that `aud` (or `azp`) names this API, and check that `scope` contains what this endpoint needs. Then return the data.

The resource server never sees the cookie and has no sessions. Every request stands alone on its token.

In phase 1 with Google, the resource server *is* Google's own API and step 9c happens inside Google. Phase 3 is where you write your own.

---

## 5. When the access token expires

Access tokens last about an hour. Before every 9b the BFF checks `expires_at`. If it has passed:

```
POST https://oauth2.googleapis.com/token
grant_type=refresh_token
&refresh_token=1//0gE4nZ...
&client_id=...
&client_secret=...
```

The provider returns a fresh `access_token`, sometimes a new `refresh_token` too (store it, the old one may be revoked). Update the session row. The user notices nothing. This is why access tokens can be short-lived without annoying anyone.

---

## 6. Logout

`POST /auth/logout`: delete the session row and clear the cookie. Optionally also:

- call the provider's `revocation_endpoint` with the refresh token, so it cannot be used again;
- redirect the browser to the provider's `end_session_endpoint`, so the user is logged out of the provider as well (OIDC RP-Initiated Logout).

---

## 7. How the picture changes by phase

### Phase 1: Browser + BFF + Postgres, against Google and GitHub

Everything in sections 3 to 6. Two providers on purpose:

- **Google** speaks OIDC. You get an `id_token` in step 5 and verify it in step 6.
- **GitHub** speaks plain OAuth 2.0. There is no `id_token`. After step 5 you have only an `access_token`, so you must call `GET https://api.github.com/user` with it to learn who the user is. Notice what you lost: no signature to verify, no `aud` to check, no `nonce`. That gap is exactly what OIDC was invented to close.

### Phase 2: Keycloak in Docker on port 8080

One config value changes: the discovery URL becomes
`http://localhost:8080/realms/lab/.well-known/openid-configuration`.
Nothing else in the BFF changes. Now you can see the provider's side: create clients, scopes and users, watch the consent screen, rotate refresh tokens, call the introspection endpoint, run a client-credentials flow for a machine client.

### Phase 3: Resource Server on port 8001

The BFF starts doing 9b. The resource server implements 9c against Keycloak's JWKS. FastAPI's `HTTPBearer` security scheme gives Swagger UI an Authorize button, and `OAuth2AuthorizationCodeBearer` lets Swagger run the real code flow against Keycloak from the docs page.

### Phase 4: Your own OpenID Provider on port 8002

Again only the discovery URL changes. Your OP must serve five endpoints:

| Endpoint | Job |
|---|---|
| `/.well-known/openid-configuration` | JSON listing the other four URLs and what you support |
| `/authorize` | Login form and consent page (Jinja2), issues the code |
| `/token` | Swaps code for tokens, signs the ID token with RS256 |
| `/jwks` | Publishes your RSA public key |
| `/userinfo` | Returns profile claims for a bearer token |

If both your phase 1 BFF and Authlib's client can log in through it with no special-casing, you have implemented OIDC.

---

## 8. Glossary

| Term | Meaning |
|---|---|
| `client_id` / `client_secret` | Your app's username and password at the provider. The secret lives only in the BFF. |
| `redirect_uri` | Where the provider sends the browser after login. Registered in advance, must match exactly. |
| `scope` | What you are asking for. `openid` means "give me an ID token". `email profile` adds those claims. |
| `state` | Random per login. Sent out in step 2, checked in step 4. Anti-CSRF. |
| `nonce` | Random per login. Sent in step 2, must appear inside the ID token in step 6. Anti-replay. |
| `code_verifier` / `code_challenge` | The PKCE pair. Challenge goes out in step 2, verifier in step 5. Proves the same client that started the login is finishing it. |
| authorization code | One-time ticket from step 3, exchanged in step 5. Useless without the secret and verifier. |
| `access_token` | The pass for APIs. "Bearer" means whoever holds it can use it. Short-lived. |
| `refresh_token` | Long-lived. Only ever sent to the provider's token endpoint to get new access tokens. |
| `id_token` | Signed JWT saying who logged in. For the BFF only. Never send it to an API. |
| `iss` / `sub` / `aud` / `exp` | Issuer, subject (the user's stable ID), audience (your `client_id`), expiry. The four claims you always check. |
| JWKS | The provider's public keys, published at `jwks_uri`. Used to verify signatures. |
| `sid` | Your session cookie value. A random ID pointing at a `sessions` row. Not a token. |
| BFF | Backend-for-frontend. The pattern where the backend does OAuth and the browser only gets a cookie. |

---

## 9. The same flow as a sequence diagram

If the box diagram is hard to follow, this is the identical story top to bottom. The numbers in the message text are the arrow numbers from `architecture.svg`. GitHub renders this block; VS Code does too with a Mermaid extension.

```mermaid
sequenceDiagram
    participant B as Browser (:3000)
    participant F as FastAPI BFF (:8000)
    participant P as Identity Provider
    participant D as Postgres (:5434)
    participant R as Resource Server (:8001)

    B->>F: 1. GET /auth/login (full navigation)
    F-->>B: 302 to provider /authorize with state, nonce, code_challenge
    B->>P: 2. GET /authorize
    P->>B: login page, then consent screen
    B->>P: 3. user submits password and clicks Allow
    P-->>B: 302 to /auth/callback?code&state
    B->>F: 4. GET /auth/callback?code&state
    F->>F: check state matches the saved one
    F->>P: 5. POST /token (code, client_secret, code_verifier)
    P-->>F: access_token, refresh_token, id_token
    F->>P: 6. GET discovery + jwks (cached)
    F->>F: verify id_token signature, iss, aud, exp, nonce
    F->>D: 7. upsert user by sub, insert session with tokens
    F-->>B: 8. Set-Cookie sid (HttpOnly) and 302 to the app
    Note over B,F: Login done. Browser holds a cookie, not a token.
    B->>F: 9a. fetch /api/photos with credentials include
    F->>D: load session by sid
    F->>R: 9b. GET /photos with Authorization Bearer access_token
    R->>P: 9c. GET jwks (cached)
    R->>R: verify access_token signature, iss, aud, exp, scope
    R-->>F: 200 data
    F-->>B: 200 data
```

---

## 10. Watch it happen

Open DevTools, go to the Network tab, tick **Preserve log**, then click Sign in. You will see this chain:

1. `localhost:8000/auth/login` → 302
2. `accounts.google.com/o/oauth2/v2/auth?...` → 200 (login and consent pages, a few POSTs)
3. `localhost:8000/auth/callback?code=...&state=...` → 302
4. `localhost:3000/` → 200

Look at every URL and every response body the browser received. No token appears anywhere. That is the whole point of the design.
