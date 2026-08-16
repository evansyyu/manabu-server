from pydantic import BaseModel


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str

class AvatarUpload(BaseModel):
    # Client ms-epoch write clock — the LWW arbiter (see the avatar routes).
    updated_at: int
    content_type: str
    data_base64: str


class AvatarDelete(BaseModel):
    # The removal's own write time, compared against the stored image's under
    # the same last-writer-wins rule an upload uses.
    updated_at: int


class AvatarState(BaseModel):
    # Whether this write won. False means the server holds something newer;
    # the winning updated_at is returned either way so the loser can fetch.
    accepted: bool
    updated_at: int | None


class AvatarImage(BaseModel):
    updated_at: int
    content_type: str
    data_base64: str


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