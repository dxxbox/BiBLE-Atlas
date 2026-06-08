"""SKILL Search API — POST /api/search/skill.

PUML responsibilities (skill_search_flow, steps 48-69):
  1. Parse JSON body.
  2. Read search.default_top_k / search.max_top_k from config.
  3. validate_request(): query non-empty, search_type in allowed,
     1 <= top_k <= max_top_k, 0 <= vector_weight <= 1.
  4. Validate tag == "skill" (case-sensitive) → TAG_INVALID.
  5. Delegate to SkillSearchService.search().
  6. Map Service-layer exceptions to HTTP status codes (via search errors module).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from bible.api.deps import get_skill_search_service, get_search_cfg
from bible.config.configure import SearchConfig
from bible.features.search.errors import raise_search_http_exception
from bible.features.search.skill_search.skill_search_service import SkillSearchService

logger = logging.getLogger(__name__)

router = APIRouter()

_REQUIRED_TAG = "skill"


# ── Request model ──────────────────────────────────────────────────────────────


class SkillSearchRequest(BaseModel):
    """Request body for POST /api/search/skill."""

    query: str = Field(..., description="Query text (required, non-empty).")
    tag: str = Field(..., description="Skill tag (required); must be 'skill'.")
    kb_index: str | None = Field(
        default=None,
        description=(
            "Optional exact knowledge-base index binding to search. "
            "When provided, binding is looked up by domain+kb_index; "
            "otherwise by domain+tag."
        ),
    )
    search_type: str | None = Field(
        default=None,
        description="keyword | title | text | vector | hybrid",
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        description="Maximum hits to return.",
    )
    vector_model: str | None = Field(
        default=None,
        description="Embedding model name; must match the binding's model.",
    )
    vector_weight: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="kNN weight for hybrid search (0 ≤ w ≤ 1).",
    )

    @field_validator("query")
    @classmethod
    def query_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("'query' must not be empty.")
        return v

    @field_validator("tag")
    @classmethod
    def tag_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("'tag' must not be empty.")
        return v

    @field_validator("kb_index")
    @classmethod
    def kb_index_non_empty(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("'kb_index' must not be empty when provided.")
        return v


# ── Route ──────────────────────────────────────────────────────────────────────


@router.post(
    "/api/search/skill",
    tags=["Search"],
    summary="SKILL search",
    status_code=200,
)
async def search_skill(
    body: SkillSearchRequest,
    search_cfg: SearchConfig = Depends(get_search_cfg),
    svc: SkillSearchService = Depends(get_skill_search_service),
) -> JSONResponse:
    """Execute a SKILL search and return ranked results."""

    # ── validate_request() — business rules beyond Pydantic constraints ───
    _validate_search_type(body.search_type, search_cfg)
    _validate_top_k(body.top_k, search_cfg)
    _validate_tag(body.tag)

    # ── Call service, map exceptions via shared error contract ────────────
    try:
        result = svc.search(
            query=body.query,
            tag=body.tag,
            search_type=body.search_type,
            top_k=body.top_k,
            vector_model=body.vector_model,
            vector_weight=body.vector_weight,
            kb_index=body.kb_index,
        )
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        logger.debug("Search exception caught: %s: %s", type(exc).__name__, exc)
        raise_search_http_exception(exc)   # raises HTTPException or re-raises

    return JSONResponse(status_code=200, content=result)


# ── Validation helpers ─────────────────────────────────────────────────────────


def _validate_search_type(search_type: str | None, cfg: SearchConfig) -> None:
    if search_type is None:
        return
    if search_type not in cfg.allowed_search_types:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SEARCH_TYPE_INVALID",
                "message": (
                    f"search_type '{search_type}' is not allowed. "
                    f"Allowed values: {cfg.allowed_search_types}"
                ),
            },
        )


def _validate_top_k(top_k: int | None, cfg: SearchConfig) -> None:
    if top_k is None:
        return
    if top_k > cfg.max_top_k:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ARGUMENT",
                "message": f"top_k={top_k} exceeds max_top_k={cfg.max_top_k}.",
            },
        )


def _validate_tag(tag: str) -> None:
    """Enforce that tag == 'skill' (case-sensitive)."""
    if tag != _REQUIRED_TAG:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TAG_INVALID",
                "message": (
                    f"tag '{tag}' is invalid for this endpoint. "
                    f"Expected '{_REQUIRED_TAG}' (case-sensitive)."
                ),
            },
        )
