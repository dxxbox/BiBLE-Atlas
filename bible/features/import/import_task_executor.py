from __future__ import annotations

from typing import Any

from bible.common.errors import DomainError, ErrorCode
from .memory_import.memory_import_service import MemoryImportService
from .types import MemoryImportPayload


class ImportTaskExecutor:
    def __init__(self, memory_import_service: MemoryImportService) -> None:
        self._memory_import_service = memory_import_service

    def execute(self, task_id: str, task_type: str, payload: dict[str, Any]) -> dict[str, Any]:
        if task_type == "import.memory":
            memory_payload = MemoryImportPayload(
                kb_index=payload["kb_index"],
                tag=payload.get("tag", "memory"),
                vector_model=payload.get("vector_model"),
                parser_context=payload.get("parser_context"),
                parser_script_path=payload.get("parser_script_path"),
                parser_script_filename=payload.get("parser_script_filename"),
                session_upload_dir=payload.get("_session_upload_dir"),
            )
            files: list[Any] = payload.get("_files", [])
            return self._memory_import_service.execute_task(task_id, memory_payload, files)
        else:
            raise DomainError(
                ErrorCode.NOT_IMPLEMENTED,
                f"Unknown task type: {task_type}",
            )
