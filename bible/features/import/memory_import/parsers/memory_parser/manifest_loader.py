from __future__ import annotations

import json
from pathlib import Path

from .schemas import UploadedFile


def load_manifest(manifest_path: str) -> list[UploadedFile]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("manifest.files must be a non-empty list")

    out: list[UploadedFile] = []
    seen_refs: set[str] = set()
    for item in files:
        file_ref = str(item.get("file_ref", "")).strip()
        filename = str(item.get("filename", "")).strip()
        abs_path = str(item.get("abs_path", "")).strip()
        if not file_ref or not filename or not abs_path:
            raise ValueError(
                f"manifest file entry missing required field(s): "
                f"file_ref={file_ref!r}, filename={filename!r}, abs_path={abs_path!r}"
            )
        if file_ref in seen_refs:
            raise ValueError(f"duplicated file_ref in manifest: {file_ref!r}")
        seen_refs.add(file_ref)
        out.append(
            UploadedFile(
                file_ref=file_ref,
                filename=filename,
                abs_path=abs_path,
                size_bytes=int(item.get("size_bytes", 0) or 0),
                content_type=item.get("content_type"),
            )
        )
    return out