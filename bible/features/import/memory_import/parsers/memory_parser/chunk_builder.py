from __future__ import annotations
from .schemas import MemoryMeta, UploadedFile

def build_single_memory_chunk(
    meta: MemoryMeta,
    attachments: list[UploadedFile],
) -> list[dict]:
    """Build exactly one semantic chunk from a MemoryMeta.

    abstract and overview are stored whole — no splitting allowed.
    """
    content = "\n".join(filter(None, [meta.abstract, meta.overview])).strip()

    return [
        {
            "doc_id": meta.memory_id,
            "memory_id": meta.memory_id,
            "title": meta.title,
            "content": content,
            "abstract": meta.abstract,
            "overview": meta.overview,
            "task_ids": meta.task_ids,
            "feature_tags": meta.feature_tags,
            "domain_tags": meta.domain_tags,
            "component_tags": meta.component_tags,
            "attributes": {
                "tag": "memory",
                "source_client": meta.source_client or "",
                "language": meta.language or "zh",
            },
            "metadata": {
                "source_file": "meta.json",
                "created_at": meta.created_at,
                "updated_at": meta.updated_at,
                # Refs used by store_memory to back-fill storage paths after local save.
                "related_file_refs": [f.file_ref for f in attachments],
                "related_storage_paths": [],
            },
        }
    ]

