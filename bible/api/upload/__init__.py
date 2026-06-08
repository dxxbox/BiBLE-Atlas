from fastapi import APIRouter

from .memory_upload_api import router as _memory_router
from .skill_upload_api import router as _skill_router

upload_router = APIRouter()
upload_router.include_router(_memory_router)
upload_router.include_router(_skill_router)

__all__ = ["upload_router"]
