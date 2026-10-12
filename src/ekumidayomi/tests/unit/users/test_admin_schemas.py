import pytest
from pydantic import ValidationError as PydanticValidationError

from ekumidayomi.audit.schemas import AuditView
from ekumidayomi.users.schemas import AccessInput, UserView


def test_admin_views_do_not_expose_authentication_material() -> None:
    assert set(UserView.model_fields).isdisjoint(
        {"password_hash", "secret_hash", "code_hash", "subject", "phone"}
    )
    assert "metadata" not in AuditView.model_fields
    with pytest.raises(PydanticValidationError):
        AccessInput.model_validate({})
    with pytest.raises(PydanticValidationError):
        AccessInput.model_validate({"role": "superuser"})
