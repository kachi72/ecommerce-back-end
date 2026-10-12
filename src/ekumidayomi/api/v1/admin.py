"""Admin only endpoints."""

from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Request, Response, status

from ekumidayomi.api import schemas as api_schemas
from ekumidayomi.api.v1.auth import CurrentActor, Sessions, Uow
from ekumidayomi.audit import schemas as audit_schemas
from ekumidayomi.audit import service as audit_service
from ekumidayomi.audit.model import ActorKind, AuditOutcome
from ekumidayomi.auth.permissions import Permission, authorize
from ekumidayomi.core.types import Page as DomainPage
from ekumidayomi.core.types import PageRequest
from ekumidayomi.users import schemas as users_schemas
from ekumidayomi.users.admin_repository import list_users
from ekumidayomi.users.administration import change_access
from ekumidayomi.users.errors import InvalidAuditFiltersError
from ekumidayomi.users.model import Role

router = APIRouter(prefix="/admin", tags=["administration"])


@router.get("/users", response_model=api_schemas.Page[users_schemas.UserView])
async def users(
    actor: CurrentActor,
    uow: Uow,
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    role: Role | None = None,
    is_active: bool | None = None,
    email: Annotated[str | None, Query(max_length=320)] = None,
) -> api_schemas.Page[users_schemas.UserView]:
    result = await list_users(
        uow,
        actor,
        page=PageRequest(page=page, page_size=page_size),
        role=role,
        is_active=is_active,
        email=email,
    )
    response.headers["Cache-Control"] = "no-store"
    return api_schemas.Page[users_schemas.UserView].from_domain(
        DomainPage(
            items=tuple(users_schemas.UserView.model_validate(row) for row in result.items),
            total_items=result.total_items,
            page=result.page,
            page_size=result.page_size,
        )
    )


@router.patch("/users/{user_id}/access", status_code=status.HTTP_204_NO_CONTENT)
async def access(
    user_id: UUID,
    payload: users_schemas.AccessInput,
    actor: CurrentActor,
    uow: Uow,
    sessions: Sessions,
    request: Request,
) -> Response:
    await change_access(
        uow,
        sessions,
        actor=actor,
        target_id=user_id,
        role=payload.role,
        is_active=payload.is_active,
        correlation_id=getattr(request.state, "request_id", str(uuid4())),
    )
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@router.get("/audits", response_model=api_schemas.Page[audit_schemas.AuditView])
async def audits(
    actor: CurrentActor,
    uow: Uow,
    response: Response,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    action: Annotated[str | None, Query(max_length=100)] = None,
    actor_kind: ActorKind | None = None,
    actor_id: UUID | None = None,
    target_type: Annotated[str | None, Query(max_length=100)] = None,
    target_id: UUID | None = None,
    outcome: AuditOutcome | None = None,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
) -> api_schemas.Page[audit_schemas.AuditView]:
    await authorize(uow, actor, Permission.AUDIT_READ)
    try:
        filters = audit_service.AuditFilters(
            action=action,
            actor_kind=actor_kind,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            outcome=outcome,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        )
    except (ValueError, TypeError):
        raise InvalidAuditFiltersError() from None
    result = await audit_service.query_records(
        uow,
        filters=filters,
        page_request=PageRequest(page=page, page_size=page_size),
    )
    response.headers["Cache-Control"] = "no-store"
    return api_schemas.Page[audit_schemas.AuditView].from_domain(
        DomainPage(
            items=tuple(audit_schemas.AuditView.model_validate(row) for row in result.items),
            total_items=result.total_items,
            page=result.page,
            page_size=result.page_size,
        )
    )
