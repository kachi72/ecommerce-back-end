"""Version 1 Router."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/", include_in_schema=False)
async def api_root() -> dict[str, str]:
    """Identify the active versioned API without advertising a domain endpoint."""

    return {"name": "Ẹkúmidáyọ̀mí API", "version": "v1"}
