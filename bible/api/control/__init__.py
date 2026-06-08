from fastapi import APIRouter

from bible.api.control.admin_api import router as _admin_router

control_router = APIRouter()
control_router.include_router(_admin_router)

__all__ = ["control_router"]
