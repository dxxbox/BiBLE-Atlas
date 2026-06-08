from __future__ import annotations

from typing import Any

from bible.common.errors import DomainError, ErrorCode
from .memory_upload.memory_upload_service import MemoryUploadService
from .skill_upload.skill_upload_service import SkillImportService
from .types import MemoryUploadPayload, SkillImportPayload


class UploadTaskExecutor:
    def __init__(
        self,
        memory_upload_service: MemoryUploadService,
        skill_import_service: SkillImportService | None = None,
    ) -> None:
        self._memory_upload_service = memory_upload_service
        self._skill_import_service = skill_import_service

    def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task_type == "import.memory":
            memory_payload = MemoryUploadPayload(
                kb_index=payload["kb_index"],
                tag=payload.get("tag", "memory"),
                vector_model=payload.get("vector_model"),
                parser_context=payload.get("parser_context"),
                parser_script_path=payload.get("parser_script_path"),
                parser_script_filename=payload.get("parser_script_filename"),
                session_upload_dir=payload.get("_session_upload_dir"),
            )
            files: list[Any] = payload.get("_files", [])
            return self._memory_upload_service.execute_task(task_id, memory_payload, files)
        elif task_type == "import.skill":
            if self._skill_import_service is None:
                raise DomainError(
                    ErrorCode.NOT_IMPLEMENTED,
                    "Skill import service is not initialized",
                )
            skill_payload = SkillImportPayload(
                kb_index=payload["kb_index"],
                tag=payload.get("tag", "skill"),
                vector_model=payload.get("vector_model"),
                parser_context=payload.get("parser_context"),
                parser_script_path=payload.get("parser_script_path"),
                parser_script_filename=payload.get("parser_script_filename"),
                session_upload_dir=payload.get("_session_upload_dir"),
            )
            files = payload.get("_files", [])
            return self._skill_import_service.execute_task(task_id, skill_payload, files)
        else:
            raise DomainError(
                ErrorCode.NOT_IMPLEMENTED,
                f"Unknown task type: {task_type}",
            )
