"""Stable errors for user and identity workflows, with subclass-owned HTTP contracts."""

from http import HTTPStatus

from ekumidayomi.core.errors import (
    AuthenticationError,
    ConflictError,
    DependencyUnavailableError,
    ForbiddenError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)


class InvalidEmailError(ValidationError):
    """Enter a valid email address."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "invalid_email"
    message = "Enter a valid email address."


class AuthenticationRequiredError(AuthenticationError):
    """Authentication is required."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "authentication_required"
    message = "Authentication is required."


class InvalidPasswordLengthError(ValidationError):
    """Use a password of 15 to 128 characters."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "invalid_password"
    message = "Use a password of 15 to 128 characters."


class InvalidChallengeError(AuthenticationError):
    """Verification could not be completed."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "invalid_challenge"
    message = "Verification could not be completed."


class EmailVerificationUnavailableError(DependencyUnavailableError):
    """Email verification is unavailable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "email_unavailable"
    message = "Email verification is unavailable."


class CommonPasswordError(ValidationError):
    """Choose a less common password or a longer unique passphrase."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "unsafe_password"
    message = "Choose a less common password or a longer unique passphrase."


class BreachedPasswordError(ValidationError):
    """Choose a password that has not appeared in known data breaches."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "unsafe_password"
    message = "Choose a password that has not appeared in known data breaches."


class InvalidPasswordEncodingError(ValidationError):
    """Use valid Unicode characters."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "invalid_password"
    message = "Use valid Unicode characters."


class PasswordCheckUnavailableError(DependencyUnavailableError):
    """Password safety checking is temporarily unavailable. Please try again."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "password_check_unavailable"
    message = "Password safety checking is temporarily unavailable. Please try again."


class UntrustedOriginError(ForbiddenError):
    """This request origin is not allowed."""

    status_code = HTTPStatus.FORBIDDEN
    code = "untrusted_origin"
    message = "This request origin is not allowed."


class InvalidCredentialsError(AuthenticationError):
    """Sign-in could not be completed."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "invalid_credentials"
    message = "Sign-in could not be completed."


class IdentityRateLimitExceededError(RateLimitError):
    """Too many attempts. Please try again later."""

    status_code = HTTPStatus.TOO_MANY_REQUESTS
    code = "rate_limit_exceeded"
    message = "Too many attempts. Please try again later."

    def __init__(self, *, retry_after: int) -> None:
        if isinstance(retry_after, bool) or not isinstance(retry_after, int):
            raise TypeError("retry_after must be an integer")
        if retry_after < 1:
            raise ValueError("retry_after must be positive")
        self.retry_after = retry_after
        super().__init__(details={"retry_after": retry_after})

    @property
    def headers(self) -> dict[str, str]:
        """Expose only the validated retry delay as an HTTP response header."""
        return {"Retry-After": str(self.retry_after)}


class IdentityUnavailableError(DependencyUnavailableError):
    """Authentication is temporarily unavailable."""

    status_code = HTTPStatus.SERVICE_UNAVAILABLE
    code = "identity_unavailable"
    message = "Authentication is temporarily unavailable."


class AuthenticationRequestTooLargeError(ValidationError):
    """Authentication request is too large."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "request_too_large"
    message = "Authentication request is too large."


class PermissionDeniedError(ForbiddenError):
    """This operation is not permitted."""

    status_code = HTTPStatus.FORBIDDEN
    code = "permission_denied"
    message = "This operation is not permitted."


class ReauthenticationRequiredError(AuthenticationError):
    """Please authenticate again."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "reauthentication_required"
    message = "Please authenticate again."


class UserNotFoundError(NotFoundError):
    """User not found."""

    status_code = HTTPStatus.NOT_FOUND
    code = "user_not_found"
    message = "User not found."


class UnverifiedAdminError(ConflictError):
    """Verify this account before assigning administration."""

    status_code = HTTPStatus.CONFLICT
    code = "unverified_admin"
    message = "Verify this account before assigning administration."


class LastActiveAdminError(ConflictError):
    """The final active administrator must remain."""

    status_code = HTTPStatus.CONFLICT
    code = "last_active_admin"
    message = "The final active administrator must remain."


class BootstrapConflictError(ConflictError):
    """Use the authenticated administration workflow."""

    status_code = HTTPStatus.CONFLICT
    code = "bootstrap_conflict"
    message = "Use the authenticated administration workflow."


class BootstrapCompleteError(ConflictError):
    """Initial administration already exists."""

    status_code = HTTPStatus.CONFLICT
    code = "bootstrap_complete"
    message = "Initial administration already exists."


class AddressNotFoundError(NotFoundError):
    """Address not found."""

    status_code = HTTPStatus.NOT_FOUND
    code = "address_not_found"
    message = "Address not found."


class AddressLimitReachedError(ConflictError):
    """The saved address limit has been reached."""

    status_code = HTTPStatus.CONFLICT
    code = "address_limit"
    message = "The saved address limit has been reached."


class InvalidAuditFiltersError(ValidationError):
    """Audit filters are invalid."""

    status_code = HTTPStatus.UNPROCESSABLE_ENTITY
    code = "invalid_audit_filters"
    message = "Audit filters are invalid."


class ExternalLoginFailedError(AuthenticationError):
    """External sign-in could not be completed."""

    status_code = HTTPStatus.UNAUTHORIZED
    code = "external_login_failed"
    message = "External sign-in could not be completed."


class FinalLoginMethodError(ConflictError):
    """The final login method cannot be removed."""

    status_code = HTTPStatus.CONFLICT
    code = "final_login_method"
    message = "The final login method cannot be removed."


class ProviderAlreadyLinkedError(ConflictError):
    """This provider is already linked."""

    status_code = HTTPStatus.CONFLICT
    code = "provider_already_linked"
    message = "This provider is already linked."
