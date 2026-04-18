from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()


def _not_implemented_payload(operation: str) -> dict[str, object]:
    return {
        "status": "error",
        "error": {
            "code": "NOT_IMPLEMENTED",
            "message": f"Knowledge API '{operation}' is not implemented yet on server side.",
            "details": {"operation": operation},
            "retryable": False,
        },
    }


@router.get("/api/v1/knowledge/list", tags=["Knowledge"])
async def knowledge_list() -> JSONResponse:
    return JSONResponse(status_code=501, content=_not_implemented_payload("list"))


@router.get("/api/v1/knowledge/search", tags=["Knowledge"])
async def knowledge_search(query: str | None = None) -> JSONResponse:
    payload = _not_implemented_payload("search")
    payload["error"]["details"] = {"operation": "search", "query": query}
    return JSONResponse(status_code=501, content=payload)
