# manabu-server

Backend for **Manabu**, an offline-first Japanese learning app for iOS. It handles sign-in and syncs each user's study data (spaced-repetition cards, review logs, study sets, favorites, settings) across devices.

The app works fully offline against a local SQLite database. This server's job is to let multiple devices converge on the same state without ever losing a review.

## Tech stack

- **Python 3.14**, **FastAPI**, **Uvicorn**
- **PostgreSQL 16** via **SQLAlchemy 2 (async)** + **asyncpg**
- **Alembic** for schema migrations
- **PyJWT** for access tokens and Apple/Google OIDC verification
- **slowapi** for per-IP rate limiting
- **pydantic-settings** for configuration
- **uv** for dependency management, **Docker** for deployment (Railway)
- **pytest** + **pytest-asyncio**, **ruff**, **mypy**

## Features

**Authentication**
- Sign in with Apple and Google: identity tokens verified against each provider's public JWKS, with nonce binding to block replay
- Short-lived JWT access tokens (15 min) and rotating, revocable refresh tokens (30 days)
- Account deletion that also revokes the user's Apple token (App Store guideline 5.1.1(v))
- Rate limits on every auth route (e.g. 10 sign-ins/min per IP)

**Offline-first sync** ([protocol spec](docs/SYNC_PROTOCOL.md))
- The client owns content, the server owns ordering. Every accepted row gets a per-user, monotonically increasing `server_seq` from a row-locked counter, and devices pull "everything after the last seq I saw." Client clocks are never used for ordering.
- Merge strategy per table: last-writer-wins for mutable rows, set union for append-only logs and per-device rollups, monotonic tombstones for deletes (pruned after 90 days)
- Push and pull are idempotent, so retries after a dropped connection are safe
- Cursor-paged `/sync/pull`

**Diagnostics**
- Crash-report intake that works signed-out, with rate limiting, batch caps, field truncation and dedupe on the client's report id

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/auth/{provider}` | Sign in with `apple` or `google` |
| `POST` | `/auth/refresh` | Rotate a refresh token |
| `POST` | `/auth/logout` | Revoke the current refresh token |
| `GET` | `/auth/me` | Current user |
| `GET` `PUT` `DELETE` | `/auth/avatar` | Profile picture |
| `DELETE` | `/auth/account` | Delete the account and revoke Apple tokens |
| `POST` | `/sync/push` | Upload local changes |
| `GET` | `/sync/pull` | Download changes after a cursor |
| `POST` | `/diagnostics/crash` | Submit queued crash reports |
| `GET` | `/health`, `/health/db` | Liveness and database checks |

## Running locally

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
docker volume create manabu-pgdata
docker compose up -d db

uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Create a `.env` in the repo root:

```
DATABASE_URL=postgresql+asyncpg://manabu:dev@localhost:5432/manabu
JWT_SECRET=<a long random string>
APPLE_BUNDLE_ID=<your bundle id>
GOOGLE_CLIENT_IDS=<comma-separated client ids>
DEV_LOGIN_ENABLED=true   # enables /auth/dev-login for local testing only
```

Apple token revocation additionally needs `APPLE_TEAM_ID`, `APPLE_KEY_ID` and `APPLE_PRIVATE_KEY` (the `.p8` contents).

## Tests

```bash
uv run pytest
```

Tests run against the local Postgres. Each test runs inside a transaction that is rolled back afterwards, so tests stay isolated without truncating tables.

## Project layout

```
app/
  auth/           sign-in, OIDC verification, tokens, account deletion
  sync/           push, pull, merge rules, sequence allocator, tombstone pruning
  diagnostics.py  crash-report intake
  models.py       SQLAlchemy models
  rate_limit.py   per-route limits
alembic/          migrations
docs/             sync protocol design
tests/
```
