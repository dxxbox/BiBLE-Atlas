from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .schemas import MemoryMeta

def _str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"expected list, got {type(value).__name__}")
    return [str(v).strip() for v in value if str(v).strip()]


def _opt(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

def _validate_required(data: dict[str, Any]) -> None:
    for field in ("memory_id", "title", "abstract"):
        if not str(data.get(field, "")).strip():
            raise ValueError(f"meta.json missing required field: {field!r}")


def _validate_lengths(data: dict[str, Any]) -> None:
    limits = {"title": 200, "abstract": 500, "overview": 2000}
    for field, limit in limits.items():
        value = str(data.get(field, ""))
        if len(value) > limit:
            raise ValueError(f"meta.json field {field!r} exceeds max length {limit}")


def _validate_iso8601(data: dict[str, Any], key: str, required: bool) -> None:
    value = _opt(data.get(key))
    if not value:
        if required:
            raise ValueError(f"meta.json field {key!r} is required")
        return
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"meta.json field {key!r} must be ISO 8601 format") from exc

def parse_meta(path: str) -> MemoryMeta:
    data: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_required(data)
    _validate_lengths(data)
    _validate_iso8601(data, "created_at", required=False)
    _validate_iso8601(data, "updated_at", required=False)

    return MemoryMeta(
        memory_id=str(data["memory_id"]).strip(),
        title=str(data["title"]).strip(),
        abstract=str(data["abstract"]).strip(),
        overview=str(data.get("overview", "") or "").strip(),
        created_at=_opt(data.get("created_at")),
        updated_at=_opt(data.get("updated_at")),
        task_ids=_str_list(data.get("task_ids")),
        feature_tags=_str_list(data.get("feature_tags")),
        domain_tags=_str_list(data.get("domain_tags")),
        component_tags=_str_list(data.get("component_tags")),
        source_client=_opt(data.get("source_client")),
        language=_opt(data.get("language")) or "zh",
    )

