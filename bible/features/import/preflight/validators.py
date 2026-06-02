from __future__ import annotations

import importlib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bible.common.errors import DomainError, ErrorCode

ASTGuard = importlib.import_module("bible.features.import.parser_runtime.ast_guard").ASTGuard


@dataclass(slots=True)
class ImportFileRef:
    filename: str
    path: str
    content_type: str | None = None
    size: int = 0


def run_import_preflight(
    *,
    domain: str,
    files: list[ImportFileRef],
    parser_script_path: str | None = None,
    parser_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_common(files, parser_script_path, parser_context)
    if domain == "MEMORY":
        return _validate_memory(files)
    if domain == "SKILL":
        return _validate_skill(files)
    if domain == "KNOWLEDGE_BASE":
        return _validate_knowledge_base(files)
    raise DomainError(ErrorCode.INVALID_ARGUMENT, f"unsupported import domain: {domain}")


def _validate_common(
    files: list[ImportFileRef],
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


def _validate_memory(files: list[ImportFileRef]) -> dict[str, Any]:
    parser_pkg = "bible.features.import.memory_import.parsers.memory_parser"
    split_meta_and_attachments = importlib.import_module(
        f"{parser_pkg}.file_classifier"
    ).split_meta_and_attachments
    parse_meta = importlib.import_module(f"{parser_pkg}.meta_parser").parse_meta
    UploadedFile = importlib.import_module(f"{parser_pkg}.schemas").UploadedFile

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


def _validate_skill(files: list[ImportFileRef]) -> dict[str, Any]:
    skill_files = [file for file in files if file.filename.lower().endswith(".skill")]
    if len(skill_files) != 1:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "skill import must contain exactly one .skill file")
    skill_file = skill_files[0]
    try:
        with zipfile.ZipFile(skill_file.path) as zf:
            entries = [info for info in zf.infolist() if info.filename.strip("/")]
    except zipfile.BadZipFile as exc:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, ".skill file must be a valid zip package") from exc
    top_dirs: set[str] = set()
    has_manifest = False
    for info in entries:
        if info.is_dir():
            continue
        raw_name = info.filename
        if raw_name.startswith("/"):
            raise DomainError(ErrorCode.INVALID_ARGUMENT, ".skill package contains unsafe paths")
        name = raw_name.rstrip("/")
        normalized = Path(name)
        parts = normalized.parts
        if normalized.is_absolute() or ".." in parts:
            raise DomainError(ErrorCode.INVALID_ARGUMENT, ".skill package contains unsafe paths")
        if len(parts) < 2:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                ".skill package files must live under a single top-level directory",
            )
        top_dirs.add(parts[0])
        if len(parts) == 2 and parts[1] == "SKILLS.md":
            has_manifest = True
    if len(top_dirs) != 1:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, ".skill package must contain exactly one top-level directory")
    if not has_manifest:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, ".skill package must contain <skill-name>/SKILLS.md")
    return {"skill_package": skill_file.filename}


def _validate_knowledge_base(files: list[ImportFileRef]) -> dict[str, Any]:
    for file in files:
        if not Path(file.path).exists():
            raise DomainError(ErrorCode.INVALID_ARGUMENT, f"uploaded file not found: {file.filename}")
    return {"files": len(files)}

