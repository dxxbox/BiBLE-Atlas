from __future__ import annotations

import os
from typing import Any

from bible.common.errors import DomainError, ErrorCode
from bible.common.logger import get_logger
from ..parser_runtime.ast_guard import ASTGuard
from ..parser_runtime.sandbox_runner import SandboxRunner
from .storage.store_memory import StoreMemory
from ..types import MemoryImportPayload, ParseResult

logger = get_logger(__name__)

class MemoryImportService:
    def __init__(
        self,
        store_memory: StoreMemory,
        ast_guard: ASTGuard,
        sandbox_runner: SandboxRunner,
        parsers_dir: str,
        config: Any = None,
    ) -> None:
        self._store_memory = store_memory
        self._ast_guard = ast_guard
        self._sandbox_runner = sandbox_runner
        self._parsers_dir = parsers_dir
        self._config = config
        pass

    def validate_parse_result_schema(self, result: dict[str, Any]) -> None:
        if not isinstance(result.get("chunks"), list):
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Parse result missing required field 'chunks' (must be a list)",
                details={"code": "PARSE_RESULT_SCHEMA_INVALID"},
            )
        if not isinstance(result.get("search_profile"), dict):
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Parse result missing required field 'search_profile' (must be a dict)",
                details={"code": "PARSE_RESULT_SCHEMA_INVALID"},
            )
        local_plan = result.get("local_file_storage_plan")
        if local_plan is not None and not isinstance(local_plan, dict):
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Parse result field 'local_file_storage_plan' must be a dict or null",
                details={"code": "PARSE_RESULT_SCHEMA_INVALID"},
            )

    def merge_chunks_and_check_profile_consistency(
        self, all_results: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if not all_results:
            return {"chunks": [], "search_profile": {}}

        merged_chunks: list[dict] = []
        reference_profile: dict[str, Any] | None = None

        for result in all_results:
            merged_chunks.extend(result.get("chunks", []))
            profile = result.get("search_profile", {})
            if reference_profile is None:
                reference_profile = profile
            else:
                ref_type = reference_profile.get("type")
                cur_type = profile.get("type")
                if ref_type and cur_type and ref_type != cur_type:
                    logger.warning(
                        "Inconsistent search_profile types across results: %s vs %s",
                        ref_type,
                        cur_type,
                    )

        return {"chunks": merged_chunks, "search_profile": reference_profile or {}}
    
    def cleanup_staged_workspace(
        self,
        task_id: str,
        keep_failed: bool = False,
        session_upload_dir: str | None = None,
    ) -> None:
        self._store_memory.cleanup_task_workspace(task_id, keep_failed=keep_failed)
        if session_upload_dir and not keep_failed:
            import shutil as _shutil
            try:
                _shutil.rmtree(session_upload_dir, ignore_errors=True)
                logger.debug("[task=%s] Removed session upload dir: %s", task_id, session_upload_dir)
            except Exception:
                pass

    def _select_parser_script(self, payload: MemoryImportPayload, task_id: str) -> str:
        if payload.parser_script_path is not None:
            # The API layer already saved the script to the session upload dir;
            # use the path directly — no second write needed.
            return payload.parser_script_path

        if payload.parser_context and "script_content" in payload.parser_context:
            # Script passed inline via parser_context["script_content"].
            # Save it to the session upload dir so the sandbox can reference it by path.
            script_content: str = payload.parser_context["script_content"]
            base_dir = payload.session_upload_dir or os.path.join(self._store_memory._import_work_root, task_id)
            os.makedirs(base_dir, exist_ok=True)
            script_path = os.path.join(base_dir, "parse_from_context.py")
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(script_content)
            logger.debug("[task=%s] Saved inline script to %s", task_id, script_path)
            return script_path

        candidate_memory = os.path.join(self._parsers_dir, "parse_memory.py")
        if os.path.exists(candidate_memory):
            return candidate_memory

        candidate_default = os.path.join(self._parsers_dir, "parse_default.py")
        if os.path.exists(candidate_default):
            return candidate_default

        raise DomainError(
            ErrorCode.NOT_FOUND,
            "No parser script found; upload a parser script, embed it in parser_context.script_content, or pre-register parse_memory.py",
            details={"code": "PARSER_SCRIPT_NOT_FOUND"},
        )

    def execute_task(
        self,
        task_id: str,
        payload: MemoryImportPayload,
        files: list[Any],
    ) -> dict[str, Any]:
        keep_failed = False
        if self._config is not None:
            keep_failed = (
                self._config.import_memory.keep_failed_workspace
                if hasattr(self._config, "import_memory")
                else False
            )

        logger.info(
            "[task=%s] Starting memory import: kb_index=%s files=%d vector_model=%s",
            task_id, payload.kb_index, len(files), payload.vector_model or "default",
        )

        failed = False
        try:
            # 1. Script selection
            script_path = self._select_parser_script(payload, task_id)
            logger.debug("[task=%s] Using parser script: %s", task_id, script_path)

            # 2. AST validation — for any user-supplied script (file upload or inline);
            # pre-registered parsers in parsers_dir are trusted.
            _user_supplied = (
                payload.parser_script_path is not None
                or (payload.parser_context and "script_content" in payload.parser_context)
            )
            if _user_supplied:
                logger.debug("[task=%s] Running AST validation on user-supplied script", task_id)
                self._ast_guard.validate(script_path)
                logger.debug("[task=%s] AST validation passed", task_id)

            # 3. Build staged-files list from pre-saved upload paths (no copy).
            logger.debug("[task=%s] Building staged list for %d uploaded file(s)", task_id, len(files))
            staged_files = self._store_memory.build_staged_files_from_paths(files)
            logger.debug("[task=%s] Staged list ready: %d file(s)", task_id, len(staged_files))

            # 4. Build manifest — written into the same session upload dir as the files
            manifest_path = self._store_memory.build_parse_manifest(
                staged_files, task_id, payload.kb_index, payload.tag,
                work_dir=payload.session_upload_dir,
            )
            logger.debug("[task=%s] Manifest written: %s", task_id, manifest_path)

            # 5. Run parser in sandbox
            # Strip script_content from context — the script shouldn't see its own source.
            sandbox_context = payload.parser_context
            if sandbox_context and "script_content" in sandbox_context:
                sandbox_context = {k: v for k, v in sandbox_context.items() if k != "script_content"}
            logger.info("[task=%s] Launching parser sandbox", task_id)
            raw_result = self._sandbox_runner.run_parse(
                script_path, manifest_path, sandbox_context
            )
            logger.info(
                "[task=%s] Parser finished: chunks=%d has_file_plan=%s",
                task_id,
                len(raw_result.get("chunks", [])),
                raw_result.get("local_file_storage_plan") is not None,
            )

            # 6. Validate parse result schema
            self.validate_parse_result_schema(raw_result)
            logger.debug("[task=%s] Parse result schema valid", task_id)

            # 7. Merge chunks / check profile consistency
            self.merge_chunks_and_check_profile_consistency([raw_result])

            parse_result = ParseResult(
                chunks=raw_result["chunks"],
                search_profile=raw_result["search_profile"],
                local_file_storage_plan=raw_result.get("local_file_storage_plan"),
            )

            # 8. Determine parser script source info
            import hashlib
            parser_script_source = os.path.basename(script_path)
            with open(script_path, "rb") as f:
                parser_script_sha256 = hashlib.sha256(f.read()).hexdigest()
            logger.debug(
                "[task=%s] Parser script: %s sha256=%s",
                task_id, parser_script_source, parser_script_sha256[:12],
            )

            # 9. Store everything
            logger.info("[task=%s] Storing %d chunk(s) to kb_index=%s", task_id, len(parse_result.chunks), payload.kb_index)
            result = self._store_memory.store(
                kb_index=payload.kb_index,
                parse_result=parse_result,
                vector_model=payload.vector_model,
                parser_script_source=parser_script_source,
                parser_script_sha256=parser_script_sha256,
                task_id=task_id,
            )
            logger.info(
                "[task=%s] Import complete: chunks_indexed=%s files_stored=%s",
                task_id,
                result.get("chunks_indexed"),
                result.get("files_stored"),
            )
            return result
        except DomainError as exc:
            failed = True
            logger.warning("[task=%s] Import failed (domain error): %s", task_id, exc)
            raise
        except Exception as exc:
            failed = True
            # Let Celery's soft-timeout signal propagate so dispatch_task.py can
            # update the task status correctly instead of wrapping it as a
            # generic INTERNAL error.
            try:
                from celery.exceptions import SoftTimeLimitExceeded
                if isinstance(exc, SoftTimeLimitExceeded):
                    raise
            except ImportError:
                pass
            logger.exception("[task=%s] Import failed (unexpected error)", task_id)
            raise DomainError(ErrorCode.INTERNAL, str(exc)) from exc
        finally:
            self.cleanup_staged_workspace(
                task_id,
                keep_failed=failed and keep_failed,
                session_upload_dir=payload.session_upload_dir,
            )
