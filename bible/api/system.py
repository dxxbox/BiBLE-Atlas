from fastapi import APIRouter, Response

from bible.common import _get_version

router = APIRouter()

@router.get("/health", tags=["System"])
async def health_check():
    return {"status": "ok"}

@router.get("/info", tags=["System"])
async def get_info():
    version = _get_version()
    return {"version": version, "description": "BiBLE-Atlas: Agent-native context DB"}


@router.get("/api/v1/system/info", tags=["System"])
async def system_info():
    version = _get_version()
    return {
        "status": "ok",
        "result": {
            "version": version,
            "description": "BiBLE-Atlas: Agent-native context DB",
        },
    }


@router.get("/api/v1/system/status", tags=["System"])
async def system_status():
    return Response(
        status_code=200,
        content='{"status": "ok"}',
        media_type="application/json",
    )
