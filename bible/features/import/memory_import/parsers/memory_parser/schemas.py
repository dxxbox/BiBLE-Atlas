from __future__ import annotations
from dataclasses import dataclass, field

@dataclass (slots=True)
class UploadedFile:
    file_ref: str
    filename: str
    abs_path: str
    size_bytes: int
    content_type: str | None = None

@dataclass(slots=True)
class MemoryMeta:
    memory_id: str
    title: str
    abstract: str
    overview: str
    created_at: str | None
    updated_at: str | None
    task_ids: list[str] = field(default_factory=list)
    feature_tags: list[str] = field(default_factory=list)
    domain_tags: list[str] = field(default_factory=list)
    component_tags: list[str] = field(default_factory=list)
    source_client: str | None = None
    language: str | None = None