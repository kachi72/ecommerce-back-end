"""Version 1 Router."""

from fastapi import APIRouter, Depends

from ekumidayomi.api.v1.admin import router as admin_router
from ekumidayomi.api.v1.auth import router as auth_router
from ekumidayomi.api.v1.customer_profile import router as customer_profile_router
from ekumidayomi.api.v1.registration import router as registration_router
from ekumidayomi.auth.rate_dependencies import identify_rate_limit
from ekumidayomi.users.rate_dependencies import profile_rate_limit

router = APIRouter()
router.include_router(registration_router, dependencies=[Depends(identify_rate_limit)])
router.include_router(auth_router, dependencies=[Depends(identify_rate_limit)])
router.include_router(customer_profile_router, dependencies=[Depends(profile_rate_limit)])
router.include_router(admin_router)


@router.get("/", include_in_schema=False)
async def api_root() -> dict[str, str]:
    """Identify the active versioned API without advertising a domain endpoint."""

    return {"name": "Ẹkúmidáyọ̀mí API", "version": "v1"}
