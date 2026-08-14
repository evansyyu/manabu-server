from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str

class ProviderLoginRequest(BaseModel):
    identity_token: str
    # Apple only: the one-time authorizationCode from the native sheet. When
    # revocation is configured server-side, it is exchanged for the Apple
    # refresh token that account deletion later revokes. Optional and ignored
    # for Google.
    authorization_code: str | None = None
    # Apple only: the raw nonce whose sha256 the client passed to the native
    # sheet — the token's `nonce` claim must match its hash (see oidc.py).
    nonce: str | None = None