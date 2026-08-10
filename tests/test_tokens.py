import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.auth.tokens import ALGORITHM, decode_access_token, create_access_token
from app.config import settings


def test_roundtrip():
    user_id = uuid.uuid4()
    assert decode_access_token(create_access_token(user_id)) == user_id


def test_rejects_expired():
    past = datetime.now(UTC) - timedelta(hours=1)
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": int(past.timestamp())},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


def test_rejects_wrong_secret():
    token = jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": 9999999999},
        "not-the-real-secret",
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token)