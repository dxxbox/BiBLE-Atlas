from __future__ import annotations

import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bible.common.errors import DomainError, ErrorCode
from bible.features.upload.memory_upload.parsers.memory_parser.file_classifier import (
    split_meta_and_attachments,
)
from bible.features.upload.memory_upload.parsers.memory_parser.meta_parser import parse_meta
from bible.features.upload.memory_upload.parsers.memory_parser.schemas import UploadedFile
from bible.features.upload.parser_runtime.ast_guard import ASTGuard


@dataclass(slots=True)
class UploadFileRef:
    filename: str
    path: str
    content_type: str | None = None
    size: int = 0


def run_upload_preflight(
    *,
    domain: str,
    files: list[UploadFileRef],
    parser_script_path: str | None = None,
    parser_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_common(files, parser_script_path, parser_context)
    if domain == "MEMORY":
        return _validate_memory(files)
    if domain == "KNOWLEDGE_BASE":
        return _validate_knowledge_base(files)
    if domain == "SKILL":
        return _validate_skill(files)
    raise DomainError(ErrorCode.INVALID_ARGUMENT, f"unsupported import domain: {domain}")


def _validate_common(
    files: list[UploadFileRef],
    parser_script_path: str | None,
    parser_context: dict[str, Any] | None,
) -> None:
    if not files:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "files[] is required")
    if len(files) > 2000:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "too many files")
    if parser_context is not None and not isinstance(parser_context, dict):
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "parser_context must be a JSON object")
    if parser_script_path:
        if not parser_script_path.endswith(".py"):
            raise DomainError(ErrorCode.INVALID_ARGUMENT, "parser_script must be a .py file")
        ASTGuard().validate(parser_script_path)


def _validate_memory(files: list[UploadFileRef]) -> dict[str, Any]:
    uploaded = [
        UploadedFile(
            file_ref=f"f_{idx:03d}",
            filename=file.filename,
            abs_path=file.path,
            size_bytes=file.size,
            content_type=file.content_type,
        )
        for idx, file in enumerate(files, start=1)
    ]
    meta, attachments = split_meta_and_attachments(uploaded)
    parsed = parse_meta(meta.abs_path)
    return {
        "memory_id": parsed.memory_id,
        "attachments": len(attachments),
    }


def _validate_knowledge_base(files: list[UploadFileRef]) -> dict[str, Any]:
    for file in files:
        if not Path(file.path).exists():
            raise DomainError(ErrorCode.INVALID_ARGUMENT, f"uploaded file not found: {file.filename}")
    return {"files": len(files)}


def _validate_skill(files: list[UploadFileRef]) -> dict[str, Any]:
    skill_file = files[0]
    try:
        with zipfile.ZipFile(skill_file.path) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        raise DomainError(
            ErrorCode.INVALID_ARGUMENT,
            f"skill package is not a valid zip file: {exc}",
        ) from exc

    top_level_dirs = {name.split("/")[0] for name in names if "/" in name}
    if not top_level_dirs:
        raise DomainError(
            ErrorCode.INVALID_ARGUMENT,
            "skill package must contain a top-level directory containing SKILL.md; "
            "found only root-level files",
        )
    if len(top_level_dirs) > 1:
        raise DomainError(
            ErrorCode.INVALID_ARGUMENT,
            f"skill package must contain exactly one top-level directory, "
            f"got {sorted(top_level_dirs)!r}",
        )

    skill_name = next(iter(top_level_dirs))
    if f"{skill_name}/SKILL.md" not in names:
        raise DomainError(
            ErrorCode.INVALID_ARGUMENT,
            f"skill package '{skill_file.filename}' must contain SKILL.md inside "
            f"'{skill_name}/', but it was not found",
        )

    return {"skill_package": skill_file.filename}

