"""Rate limiting for the auth surface (slowapi over `limits`).

Auth endpoints are the ones an attacker can hammer without an account —
credential stuffing has no purchase here (there are no passwords), but token
brute-forcing, spam account creation, and refresh-token guessing are all
bounded by these limits. Sync endpoints are deliberately unlimited: they
require a valid access token, a bootstrap pull legitimately makes dozens of
rapid requests, and per-user abuse is better handled at the account level
than the IP level.

## Keying by client IP behind Railway's proxy

Requests arrive from Railway's edge, so the TCP peer address is the proxy,
not the user — naive `request.client.host` keying would put every user in
one shared bucket, and the first person to hit a limit would lock everyone
out. Uvicorn is therefore started with ``--proxy-headers
--forwarded-allow-ips="*"`` (see the Dockerfile), which rewrites
``request.client`` from ``X-Forwarded-For`` before the app sees it.
Trusting that header from anywhere is safe *in this deployment* because
Railway's edge overwrites what clients send; running the container anywhere
that exposes it directly to the internet would let clients spoof their IP
per request, and the allow-list would need tightening.

In-memory storage: correct for a single instance, resets on deploy — both
fine at this scale. Scaling to multiple instances means pointing `limits`
at a shared Redis, a one-line storage_uri change.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

# Sign-in: a human does this a handful of times, ever. The ceiling exists
# for scripted account creation and identity-token replay probing.
LOGIN_LIMIT = "10/minute"

# Refresh: routine (every ~15 min per device), and several devices can share
# a NAT'd IP — generous, but a guessing loop still dies fast.
REFRESH_LIMIT = "30/minute"

# Deletion is once-per-account destructive; nobody legitimate does it in a loop.
ACCOUNT_DELETE_LIMIT = "5/minute"
