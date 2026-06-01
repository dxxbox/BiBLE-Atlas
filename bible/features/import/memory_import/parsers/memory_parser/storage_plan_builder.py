from __future__ import annotations

from .schemas import UploadedFile


def build_local_storage_plan(attachments: list[UploadedFile]) -> dict:
    """Return a local_file_storage_plan listing every attachment to persist."""
    return {
        "files": [
            {
                "file_ref": f.file_ref,
                "filename": f.filename,
                # source_path is the staged abs_path; store_memory reads this field.
                "source_path": f.abs_path,
                "size_bytes": f.size_bytes,
                "content_type": f.content_type,
                "must_store_local": True,
                "storage_role": "memory_attachment",
            }
            for f in attachments
        ]
    }