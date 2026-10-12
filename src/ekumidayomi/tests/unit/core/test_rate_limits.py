import pytest

from ekumidayomi.core.rate_limits import private_identifier, rate_limit_key


def test_private_rate_limit_identity_and_key_hide_source_value() -> None:
    source = "customer-id-that-must-not-appear"
    identifier = private_identifier(source, "test-secret")
    key = rate_limit_key(
        namespace="test",
        scope="users",
        operation="profile-update",
        identity=source,
        secret="test-secret",
    )

    assert len(identifier) == 64
    assert source not in identifier
    assert source not in key
    assert key == f"ekumidayomi:test:users:v1:limit:profile-update:{identifier}"


@pytest.mark.parametrize(
    "limit,window_seconds",
    [(0, 60), (True, 60), (1, 0), (1, True)],
)
async def test_sliding_window_rejects_invalid_configuration(
    limit: int, window_seconds: int
) -> None:
    from unittest.mock import AsyncMock

    from ekumidayomi.core.rate_limits import sliding_window_retry_after

    with pytest.raises(ValueError):
        await sliding_window_retry_after(
            AsyncMock(),
            key="test-key",
            limit=limit,
            window_seconds=window_seconds,
        )
