"""Contracts for named identity errors, independent of future auth services."""

from collections.abc import Callable
from typing import Any

import pytest
from starlette.requests import Request

from ekumidayomi.api.errors import handle_application_error
from ekumidayomi.core.errors import (
    ApplicationError,
    AuthenticationError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    JsonValue,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from ekumidayomi.users.errors import (
    AddressLimitReachedError,
    AddressNotFoundError,
    AuthenticationRequestTooLargeError,
    AuthenticationRequiredError,
    BootstrapCompleteError,
    BootstrapConflictError,
    BreachedPasswordError,
    CommonPasswordError,
    EmailVerificationUnavailableError,
    ExternalLoginFailedError,
    FinalLoginMethodError,
    IdentityRateLimitExceededError,
    IdentityUnavailableError,
    InvalidAuditFiltersError,
    InvalidChallengeError,
    InvalidCredentialsError,
    InvalidEmailError,
    InvalidPasswordEncodingError,
    InvalidPasswordLengthError,
    LastActiveAdminError,
    PasswordCheckUnavailableError,
    PermissionDeniedError,
    ProviderAlreadyLinkedError,
    ReauthenticationRequiredError,
    UntrustedOriginError,
    UnverifiedAdminError,
    UserNotFoundError,
)

type ErrorCase = tuple[
    Callable[[], ApplicationError],
    type[ApplicationError],
    int,
    str,
    str,
    dict[str, JsonValue],
]

CASES: list[ErrorCase] = [
    (
        InvalidEmailError,
        ValidationError,
        422,
        "invalid_email",
        "Enter a valid email address.",
        {},
    ),
    (
        AuthenticationRequiredError,
        AuthenticationError,
        401,
        "authentication_required",
        "Authentication is required.",
        {},
    ),
    (
        InvalidPasswordLengthError,
        ValidationError,
        422,
        "invalid_password",
        "Use a password of 15 to 128 characters.",
        {},
    ),
    (
        InvalidChallengeError,
        AuthenticationError,
        401,
        "invalid_challenge",
        "Verification could not be completed.",
        {},
    ),
    (
        EmailVerificationUnavailableError,
        DependencyUnavailableError,
        503,
        "email_unavailable",
        "Email verification is unavailable.",
        {},
    ),
    (
        CommonPasswordError,
        ValidationError,
        422,
        "unsafe_password",
        "Choose a less common password or a longer unique passphrase.",
        {},
    ),
    (
        BreachedPasswordError,
        ValidationError,
        422,
        "unsafe_password",
        "Choose a password that has not appeared in known data breaches.",
        {},
    ),
    (
        InvalidPasswordEncodingError,
        ValidationError,
        422,
        "invalid_password",
        "Use valid Unicode characters.",
        {},
    ),
    (
        PasswordCheckUnavailableError,
        DependencyUnavailableError,
        503,
        "password_check_unavailable",
        "Password safety checking is temporarily unavailable. Please try again.",
        {},
    ),
    (
        UntrustedOriginError,
        ForbiddenError,
        403,
        "untrusted_origin",
        "This request origin is not allowed.",
        {},
    ),
    (
        InvalidCredentialsError,
        AuthenticationError,
        401,
        "invalid_credentials",
        "Sign-in could not be completed.",
        {},
    ),
    (
        lambda: IdentityRateLimitExceededError(retry_after=7),
        RateLimitError,
        429,
        "rate_limit_exceeded",
        "Too many attempts. Please try again later.",
        {"retry_after": 7},
    ),
    (
        IdentityUnavailableError,
        DependencyUnavailableError,
        503,
        "identity_unavailable",
        "Authentication is temporarily unavailable.",
        {},
    ),
    (
        AuthenticationRequestTooLargeError,
        ValidationError,
        422,
        "request_too_large",
        "Authentication request is too large.",
        {},
    ),
    (
        PermissionDeniedError,
        ForbiddenError,
        403,
        "permission_denied",
        "This operation is not permitted.",
        {},
    ),
    (
        ReauthenticationRequiredError,
        AuthenticationError,
        401,
        "reauthentication_required",
        "Please authenticate again.",
        {},
    ),
    (
        UserNotFoundError,
        NotFoundError,
        404,
        "user_not_found",
        "User not found.",
        {},
    ),
    (
        UnverifiedAdminError,
        ConflictError,
        409,
        "unverified_admin",
        "Verify this account before assigning administration.",
        {},
    ),
    (
        LastActiveAdminError,
        ConflictError,
        409,
        "last_active_admin",
        "The final active administrator must remain.",
        {},
    ),
    (
        BootstrapConflictError,
        ConflictError,
        409,
        "bootstrap_conflict",
        "Use the authenticated administration workflow.",
        {},
    ),
    (
        BootstrapCompleteError,
        ConflictError,
        409,
        "bootstrap_complete",
        "Initial administration already exists.",
        {},
    ),
    (
        AddressNotFoundError,
        NotFoundError,
        404,
        "address_not_found",
        "Address not found.",
        {},
    ),
    (
        AddressLimitReachedError,
        ConflictError,
        409,
        "address_limit",
        "The saved address limit has been reached.",
        {},
    ),
    (
        InvalidAuditFiltersError,
        ValidationError,
        422,
        "invalid_audit_filters",
        "Audit filters are invalid.",
        {},
    ),
    (
        ExternalLoginFailedError,
        AuthenticationError,
        401,
        "external_login_failed",
        "External sign-in could not be completed.",
        {},
    ),
    (
        FinalLoginMethodError,
        ConflictError,
        409,
        "final_login_method",
        "The final login method cannot be removed.",
        {},
    ),
    (
        ProviderAlreadyLinkedError,
        ConflictError,
        409,
        "provider_already_linked",
        "This provider is already linked.",
        {},
    ),
]


@pytest.mark.parametrize("factory, category, status, code, message, details", CASES)
async def test_named_error_and_http_contract(
    factory: Callable[[], ApplicationError],
    category: type[ApplicationError],
    status: int,
    code: str,
    message: str,
    details: dict[str, JsonValue],
) -> None:
    import json

    first, second = factory(), factory()
    assert isinstance(first, category)
    assert first.status_code == status
    assert first.code == code and first.message == message
    assert str(first) == message and first.details == details
    first.details["diagnostic"] = "safe-test-marker"
    assert "diagnostic" not in second.details

    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "state": {"request_id": "identity-error-test"},
        }
    )
    response = await handle_application_error(request, second)
    assert response.status_code == status
    assert json.loads(bytes(response.body)) == {
        "error": {
            "code": code,
            "message": message,
            "details": details,
            "request_id": "identity-error-test",
        }
    }


@pytest.mark.parametrize(
    "error_type",
    [
        AddressLimitReachedError,
        AddressNotFoundError,
        AuthenticationRequestTooLargeError,
        AuthenticationRequiredError,
        BootstrapCompleteError,
        BootstrapConflictError,
        BreachedPasswordError,
        CommonPasswordError,
        EmailVerificationUnavailableError,
        ExternalLoginFailedError,
        FinalLoginMethodError,
        IdentityRateLimitExceededError,
        IdentityUnavailableError,
        InvalidAuditFiltersError,
        InvalidChallengeError,
        InvalidCredentialsError,
        InvalidEmailError,
        InvalidPasswordEncodingError,
        InvalidPasswordLengthError,
        LastActiveAdminError,
        PasswordCheckUnavailableError,
        PermissionDeniedError,
        ProviderAlreadyLinkedError,
        ReauthenticationRequiredError,
        UntrustedOriginError,
        UnverifiedAdminError,
        UserNotFoundError,
    ],
)
@pytest.mark.parametrize(
    "override",
    [{"code": "replacement"}, {"message": "replacement"}, {"status_code": 500}],
)
def test_callers_cannot_override_named_error_contract(
    error_type: type[ApplicationError], override: dict[str, Any]
) -> None:
    with pytest.raises(TypeError):
        error_type(**override)


@pytest.mark.parametrize("retry_after", [True, "7", 1.5, None])
def test_retry_context_rejects_wrong_types(retry_after: Any) -> None:
    with pytest.raises(TypeError, match="integer"):
        IdentityRateLimitExceededError(retry_after=retry_after)


@pytest.mark.parametrize("retry_after", [0, -1])
def test_retry_context_rejects_non_positive_values(retry_after: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        IdentityRateLimitExceededError(retry_after=retry_after)


def test_named_errors_declare_metadata_without_boilerplate_constructors() -> None:
    from ekumidayomi.users import errors

    declared = [
        value
        for value in vars(errors).values()
        if isinstance(value, type)
        and issubclass(value, ApplicationError)
        and value.__module__ == errors.__name__
    ]
    assert len(declared) == 27
    for error_type in declared:
        assert {"status_code", "code", "message"} <= error_type.__dict__.keys()
        if error_type is not IdentityRateLimitExceededError:
            assert "__init__" not in error_type.__dict__


def test_rate_limit_headers_are_fresh() -> None:
    error = IdentityRateLimitExceededError(retry_after=7)
    assert error.headers == {"Retry-After": "7"}
    error.headers["Retry-After"] = "999"
    assert error.headers == {"Retry-After": "7"}
