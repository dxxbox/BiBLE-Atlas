from __future__ import annotations

from .schemas import UploadedFile


def split_meta_and_attachments(
    files: list[UploadedFile],
) -> tuple[UploadedFile, list[UploadedFile]]:
    """Return (meta_file, attachments).

    Exactly one file must be named ``meta.json`` (case-insensitive).
    All other files are treated as attachments.
    """
    metas = [f for f in files if f.filename.lower() == "meta.json"]
    if len(metas) == 0:
        raise ValueError("memory upload must contain exactly one meta.json (none found)")
    if len(metas) > 1:
        raise ValueError(
            f"memory upload must contain exactly one meta.json ({len(metas)} found)"
        )
    meta = metas[0]
    attachments = [f for f in files if f.file_ref != meta.file_ref]
    return meta, attachments