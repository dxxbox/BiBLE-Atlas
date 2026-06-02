from __future__ import annotations

import json
from typing import Any

from fastapi import UploadFile

SEARCH_TYPES = {"keyword", "title", "text", "vector", "hybrid"}


class ValidationFailure(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 400, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details


def validate_fixed_tag(domain: str, tag: str) -> None:
    expected = {"SKILL": "skill", "MEMORY": "memory"}.get(domain)
    if expected and tag != expected:
        raise ValidationFailure("TAG_INVALID", f"tag must be '{expected}', got '{tag}'")


def validate_search(domain: str, body: dict[str, Any]) -> None:
    query = body.get("query")
    tag = body.get("tag")
    if not isinstance(query, str) or not query.strip():
        raise ValidationFailure("INVALID_ARGUMENT", "query is required", details={"field": "query"})
    if not isinstance(tag, str) or not tag.strip():
        raise ValidationFailure("INVALID_ARGUMENT", "tag is required", details={"field": "tag"})
    validate_fixed_tag(domain, tag)
    search_type = body.get("search_type")
    if search_type is not None and search_type not in SEARCH_TYPES:
        raise ValidationFailure(
            "INVALID_ARGUMENT",
            "search_type is invalid",
            details={"field": "search_type", "allowed": sorted(SEARCH_TYPES)},
        )
    top_k = body.get("top_k")
    if top_k is not None and (not isinstance(top_k, int) or top_k <= 0):
        raise ValidationFailure("INVALID_ARGUMENT", "top_k must be a positive integer", details={"field": "top_k"})


def validate_import_fields(
    *,
    domain: str,
    files: list[UploadFile],
    kb_index: str,
    tag: str,
    parser_context: str | None,
) -> dict[str, Any] | None:
    if not files:
        raise ValidationFailure("INVALID_ARGUMENT", "files[] is required", details={"field": "files"})
    if not kb_index or not kb_index.strip():
        raise ValidationFailure("INVALID_ARGUMENT", "kb_index is required", details={"field": "kb_index"})
    if not tag or not tag.strip():
        raise ValidationFailure("INVALID_ARGUMENT", "tag is required", details={"field": "tag"})
    validate_fixed_tag(domain, tag)
    if not parser_context:
        return None
    try:
        parsed = json.loads(parser_context)
    except json.JSONDecodeError as exc:
        raise ValidationFailure(
            "INVALID_ARGUMENT",
            "parser_context must be valid JSON",
            details={"field": "parser_context"},
        ) from exc
    if not isinstance(parsed, dict):
        raise ValidationFailure(
            "INVALID_ARGUMENT",
            "parser_context must be a JSON object",
            details={"field": "parser_context"},
        )
    return parsed


def validate_download(domain: str, body: dict[str, Any], *, batch: bool) -> None:
    tag = body.get("tag")
    if not isinstance(tag, str) or not tag.strip():
        raise ValidationFailure("INVALID_ARGUMENT", "tag is required", details={"field": "tag"})
    validate_fixed_tag(domain, tag)
    if batch:
        storage_paths = body.get("storage_paths")
        if not isinstance(storage_paths, list) or not storage_paths or not all(isinstance(v, str) and v.strip() for v in storage_paths):
            raise ValidationFailure(
                "INVALID_ARGUMENT",
                "storage_paths must be a non-empty string array",
                details={"field": "storage_paths"},
            )
    else:
        storage_path = body.get("storage_path")
        if not isinstance(storage_path, str) or not storage_path.strip():
            raise ValidationFailure("INVALID_ARGUMENT", "storage_path is required", details={"field": "storage_path"})

