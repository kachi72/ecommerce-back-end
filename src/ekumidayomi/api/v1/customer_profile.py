from uuid import UUID

from fastapi import APIRouter, Response, status

from ekumidayomi.api.v1.auth import CurrentActor, Uow
from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.users import schemas as users_schemas
from ekumidayomi.users import service as users_service

router = APIRouter(prefix="/profile", tags=["customer-profile"])


@router.get("", response_model=users_schemas.ProfileView)
async def get_profile(
    actor: CurrentActor, uow: Uow, response: Response
) -> users_schemas.ProfileView:
    user = await authorize(uow, actor, Permission.PROFILE_WRITE)
    response.headers["Cache-Control"] = "no-store"
    return users_schemas.ProfileView.model_validate(user)


@router.put("", response_model=users_schemas.ProfileView)
async def put_profile(
    payload: users_schemas.ProfileInput, actor: CurrentActor, uow: Uow, response: Response
) -> users_schemas.ProfileView:
    user = await users_service.update_profile(uow, actor, payload)
    response.headers["Cache-Control"] = "no-store"
    return users_schemas.ProfileView.model_validate(user)


@router.get("/addresses", response_model=list[users_schemas.AddressView])
async def addresses(
    actor: CurrentActor, uow: Uow, response: Response
) -> list[users_schemas.AddressView]:
    rows = await users_service.list_addresses(uow, actor)
    response.headers["Cache-Control"] = "no-store"
    return [users_schemas.AddressView.model_validate(row) for row in rows]


@router.post(
    "/addresses", status_code=status.HTTP_201_CREATED, response_model=users_schemas.AddressView
)
async def create_address(
    payload: users_schemas.AddressInput, actor: CurrentActor, uow: Uow, response: Response
) -> users_schemas.AddressView:
    row = await users_service.save_address(uow, actor, payload)
    response.headers["Cache-Control"] = "no-store"
    return users_schemas.AddressView.model_validate(row)


@router.put("/addresses/{address_id}", response_model=users_schemas.AddressView)
async def replace_address(
    address_id: UUID,
    payload: users_schemas.AddressInput,
    actor: CurrentActor,
    uow: Uow,
    response: Response,
) -> users_schemas.AddressView:
    row = await users_service.save_address(uow, actor, payload, address_id=address_id)
    response.headers["Cache-Control"] = "no-store"
    return users_schemas.AddressView.model_validate(row)


@router.delete("/addresses/{address_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_address(address_id: UUID, actor: CurrentActor, uow: Uow) -> Response:
    await users_service.delete_address(uow, actor, address_id)
    return Response(
        status_code=status.HTTP_204_NO_CONTENT,
        headers={"Cache-Control": "no-store"},
    )
