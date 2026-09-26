-- Phase 0: the two tables from PLAN.md.
-- users: one row per person per identity provider, keyed on (iss, sub), never on email.
-- sessions: one row per login. The browser's cookie holds only sid.

create table users (
    id          bigserial primary key,
    iss         text not null,
    sub         text not null,
    email       text,
    name        text,
    created_at  timestamptz not null default now(),
    unique (iss, sub)
);

create table sessions (
    sid                 text primary key,
    user_id             bigint not null references users(id) on delete cascade,
    provider            text not null,
    access_token        bytea not null,   -- Fernet-encrypted
    refresh_token       bytea,            -- Fernet-encrypted; null for providers without refresh
    token_expires_at    timestamptz not null,
    session_expires_at  timestamptz not null,
    created_at          timestamptz not null default now()
);

create index sessions_user_id_idx on sessions (user_id);
create index sessions_session_expires_at_idx on sessions (session_expires_at);
