import pytest

from app.rate_limit import limiter


@pytest.fixture()
def enabled_limiter():
    """Opt back in (conftest disables globally) with clean counters, and
    leave clean counters behind for whoever runs next."""
    limiter.reset()
    limiter.enabled = True
    yield
    limiter.enabled = False
    limiter.reset()


@pytest.mark.asyncio
async def test_login_rate_limit_trips_at_eleven(client, enabled_limiter):
    # Garbage tokens: every attempt 401s, which is exactly the scripted-probe
    # shape the limit exists for — failures count against the bucket too.
    statuses = []
    for _ in range(11):
        response = await client.post(
            "/auth/apple", json={"identity_token": "garbage"}
        )
        statuses.append(response.status_code)

    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


@pytest.mark.asyncio
async def test_unlimited_endpoints_stay_unlimited(client, enabled_limiter):
    # Health (and by design the sync endpoints) carry no limit — a bootstrap
    # pull legitimately makes dozens of rapid requests.
    for _ in range(30):
        assert (await client.get("/health")).status_code == 200
