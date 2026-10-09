"""Real PostgreSQL credential/challenge constraints, using isolated-schema fixtures."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ekumidayomi.auth.challenge_model import ChallengePurpose, EmailChallenge, PasswordCredential
from ekumidayomi.auth.passwords import hash_password, verify_password
from ekumidayomi.users.model import User


def make_challenge(
    *,
    email: str = "customer@example.com",
    purpose: str = ChallengePurpose.REGISTRATION.value,
    attempts: int = 0,
) -> EmailChallenge:
    now = datetime.now(UTC)
    return EmailChallenge(
        email=email,
        purpose=purpose,
        key_version="v1",
        code_hash="a" * 64,
        attempts=attempts,
        created_at=now,
        expires_at=now + timedelta(minutes=10),
    )


async def test_credential_hash_and_timestamps_round_trip(database_session: AsyncSession) -> None:
    user = User(email="customer@example.com")
    database_session.add(user)
    await database_session.flush()
    value = "quiet meadows beyond the river"
    encoded = await hash_password(value)
    credential = PasswordCredential(user_id=user.id, password_hash=encoded)
    database_session.add(credential)
    await database_session.flush()
    user_id = user.id
    await database_session.commit()
    database_session.expunge_all()
    restored = await database_session.get(PasswordCredential, user_id)
    assert restored is not None and restored.password_hash == encoded
    assert restored.created_at.utcoffset() is not None
    assert restored.updated_at.utcoffset() is not None
    assert await verify_password(restored.password_hash, value)


async def test_credential_requires_existing_user(database_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError) as caught:
        async with database_session.begin_nested():
            database_session.add(PasswordCredential(user_id=uuid4(), password_hash="test-hash"))
            await database_session.flush()
    assert "fk_password_credentials_user_id_users" in str(caught.value.orig)


async def test_only_one_credential_per_user(database_session: AsyncSession) -> None:
    user = User(email="customer@example.com")
    database_session.add(user)
    await database_session.flush()
    values = {"user_id": user.id, "password_hash": "test-hash"}
    await database_session.execute(sa.insert(PasswordCredential).values(**values))
    with pytest.raises(IntegrityError) as caught:
        async with database_session.begin_nested():
            await database_session.execute(sa.insert(PasswordCredential).values(**values))
    assert "pk_password_credentials" in str(caught.value.orig)


async def test_user_deletion_cascades_only_its_credential(database_session: AsyncSession) -> None:
    users = [User(email="first@example.com"), User(email="second@example.com")]
    database_session.add_all(users)
    await database_session.flush()
    ids = [user.id for user in users]
    database_session.add_all(
        PasswordCredential(user_id=user_id, password_hash="test-hash") for user_id in ids
    )
    await database_session.commit()
    await database_session.execute(sa.delete(User).where(User.id == ids[0]))
    await database_session.commit()
    database_session.expunge_all()
    assert await database_session.get(PasswordCredential, ids[0]) is None
    assert await database_session.get(PasswordCredential, ids[1]) is not None


async def test_challenge_round_trip_defaults_and_consumption(
    database_session: AsyncSession,
) -> None:
    challenge = make_challenge()
    # Omit attempts entirely to exercise the mapped default, not the helper's value.
    del challenge.attempts
    database_session.add(challenge)
    await database_session.flush()
    assert isinstance(challenge.id, UUID)
    assert challenge.attempts == 0 and challenge.consumed_at is None
    challenge_id = challenge.id
    created_at, expires_at = challenge.created_at, challenge.expires_at
    await database_session.commit()
    database_session.expunge_all()
    restored = await database_session.get(EmailChallenge, challenge_id)
    assert restored is not None
    assert restored.email == "customer@example.com"
    assert type(restored.purpose) is str
    assert restored.purpose == ChallengePurpose.REGISTRATION.value
    assert restored.key_version == "v1" and restored.code_hash == "a" * 64
    assert restored.created_at == created_at and restored.expires_at == expires_at
    assert restored.expires_at.utcoffset() is not None
    consumed_at = datetime.now(UTC)
    restored.consumed_at = consumed_at
    restored.attempts = 2
    await database_session.commit()
    database_session.expunge_all()
    consumed = await database_session.get(EmailChallenge, challenge_id)
    assert consumed is not None
    assert consumed.consumed_at == consumed_at and consumed.attempts == 2


async def test_email_and_purpose_pair_is_unique(database_session: AsyncSession) -> None:
    database_session.add(make_challenge())
    await database_session.flush()
    with pytest.raises(IntegrityError) as caught:
        async with database_session.begin_nested():
            database_session.add(make_challenge())
            await database_session.flush()
    assert "uq_email_challenges_email_purpose" in str(caught.value.orig)


async def test_different_email_or_purpose_can_coexist(database_session: AsyncSession) -> None:
    database_session.add_all(
        [
            make_challenge(),
            make_challenge(purpose=ChallengePurpose.PASSWORD_RESET.value),
            make_challenge(email="another@example.com"),
        ]
    )
    await database_session.flush()
    count = await database_session.scalar(sa.select(sa.func.count()).select_from(EmailChallenge))
    assert count == 3


async def test_database_does_not_enforce_purpose_options(database_session: AsyncSession) -> None:
    # Application handlers validate supported purposes; the DB stores plain strings.
    challenge = make_challenge(purpose="future_workflow")
    database_session.add(challenge)
    await database_session.flush()
    challenge_id = challenge.id
    await database_session.commit()
    database_session.expunge_all()
    restored = await database_session.get(EmailChallenge, challenge_id)
    assert restored is not None and restored.purpose == "future_workflow"


async def test_negative_attempts_are_rejected(database_session: AsyncSession) -> None:
    with pytest.raises(IntegrityError) as caught:
        async with database_session.begin_nested():
            database_session.add(make_challenge(attempts=-1))
            await database_session.flush()
    assert "ck_email_challenges_attempts_non_negative" in str(caught.value.orig)
