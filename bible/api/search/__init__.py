from fastapi import APIRouter

from .knowledge_base_search_api import router as _kb_search_router
from .memory_search_api import router as _memory_search_router

search_router = APIRouter()
search_router.include_router(_kb_search_router)
search_router.include_router(_memory_search_router)
router = search_router

__all__ = ["router", "search_router"]
