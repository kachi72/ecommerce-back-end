import pytest
from pydantic import ValidationError as PydanticValidationError

from ekumidayomi.users.schemas import AddressInput, ProfileInput


def test_profile_preserves_yoruba_and_forbids_privilege_fields() -> None:
    assert ProfileInput(display_name="Ẹkúmidáyọ̀mí").display_name == "Ẹkúmidáyọ̀mí"
    with pytest.raises(PydanticValidationError):
        ProfileInput.model_validate({"display_name": "Customer", "role": "admin"})


def test_country_code_is_bounded_ascii() -> None:
    data = dict(
        kind="shipping",
        recipient="Customer",
        line1="1 Main Street",
        city="Lagos",
        region="Lagos",
        country_code="NG",
    )
    assert AddressInput.model_validate(data).country_code == "NG"
    with pytest.raises(PydanticValidationError):
        AddressInput.model_validate(data | {"country_code": "Nigeria"})
