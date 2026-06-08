from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
from datetime import datetime, timezone
from typing import Any

from bible.common.logger import get_logger
from bible.infrastructure.database.factory import DatabaseFactory
from bible.infrastructure.database.types import IndexBinding
from bible.infrastructure.file_system.factory import FileSystemFactory
from bible.infrastructure.vector.vector_tool import VectorTool

logger = get_logger(__name__)

_DOMAIN = "SKILL"


def _sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class StoreSkill:
    def __init__(self, workspace_dir: str, config: Any = None) -> None:
        self._workspace_dir = workspace_dir
        self._config = config
        self._vector_tool: VectorTool | None = None

        if config is None:
            from bible.config.configure import get_bible_atlas_config
            config = get_bible_atlas_config()

        self._import_work_root = (
            config.import_skill.import_work_dir
            if hasattr(config, "import_skill") and config.import_skill.import_work_dir
            else os.path.join(workspace_dir, "skill_import_work")
        )
        os.makedirs(self._import_work_root, exist_ok=True)

        # Use a skill-specific file root so SKILL files land under workspace/skill/files/
        # rather than the shared file_system gateway (which has no single root_dir any more).
        skill_files_dir = (
            config.import_skill.files_dir
            if hasattr(config, "import_skill") and getattr(config.import_skill, "files_dir", None)
            else os.path.join(workspace_dir, "files")
        )
        self._fs_gateway = self._build_fs_gateway(config, skill_files_dir)
        self._db_factory = DatabaseFactory(config)
        self._hf_cache_dir: str | None = (
            config.vector.hf_cache_dir if hasattr(config, "vector") else None
        )

        if self._config is not None:
            self._vector_tool = VectorTool(
                workspace_dir=workspace_dir,
                hf_cache_dir=self._hf_cache_dir,
            )

    # -------------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------------

    def stage_upload_files(self, files: list[Any], task_id: str) -> list[dict[str, Any]]:
        staged_dir = os.path.join(self._import_work_root, task_id, "staged")
        os.makedirs(staged_dir, exist_ok=True)

        results: list[dict[str, Any]] = []
        for idx, file_obj in enumerate(files):
            filename, content = self._read_file_obj(file_obj, idx)
            dest_path = os.path.join(staged_dir, filename)
            with open(dest_path, "wb") as f:
                f.write(content)

            content_type = getattr(file_obj, "content_type", "application/octet-stream") or "application/octet-stream"
            results.append(
                {
                    "file_ref": f"file_{idx}",
                    "filename": filename,
                    "abs_path": dest_path,
                    "size_bytes": len(content),
                    "content_type": content_type,
                }
            )
        return results

    def stage_parser_script(
        self,
        content: bytes,
        original_filename: str | None,
        task_id: str,
    ) -> str:
        safe_name = self._sanitize_script_filename(original_filename)
        script_dir = os.path.join(self._import_work_root, task_id, "parser")
        os.makedirs(script_dir, exist_ok=True)
        dest = os.path.join(script_dir, safe_name)
        with open(dest, "wb") as f:
            f.write(content)
        logger.debug("Staged uploaded parser script → %s", dest)
        return dest

    @staticmethod
    def _sanitize_script_filename(name: str | None) -> str:
        if not name:
            return "parse_upload.py"
        basename = os.path.basename(name)
        safe = re.sub(r"[^\w\-.]", "_", basename)
        if not safe:
            return "parse_upload.py"
        if not safe.endswith(".py"):
            safe += ".py"
        return safe

    def build_staged_files_from_paths(self, file_refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for idx, ref in enumerate(file_refs):
            filename = ref.get("filename") or f"file_{idx}"
            abs_path = ref.get("path", "")
            content_type = ref.get("content_type", "application/octet-stream")
            try:
                size_bytes = os.path.getsize(abs_path) if abs_path else 0
            except OSError:
                size_bytes = 0
            results.append(
                {
                    "file_ref": f"file_{idx}",
                    "filename": filename,
                    "abs_path": abs_path,
                    "size_bytes": size_bytes,
                    "content_type": content_type,
                }
            )
        return results

    def build_parse_manifest(
        self,
        staged_files: list[dict[str, Any]],
        task_id: str,
        kb_index: str,
        tag: str,
        work_dir: str | None = None,
    ) -> str:
        manifest = {
            "task_id": task_id,
            "kb_index": kb_index,
            "tag": tag,
            "files": staged_files,
        }
        target_dir = work_dir if work_dir else os.path.join(self._import_work_root, task_id)
        os.makedirs(target_dir, exist_ok=True)
        manifest_path = os.path.join(target_dir, "skill_request_manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        return manifest_path

    def store(
        self,
        kb_index: str,
        parse_result: Any,
        vector_model: str | None,
        parser_script_source: str,
        parser_script_sha256: str,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        chunks: list[dict[str, Any]] = list(parse_result.chunks)
        search_profile: dict[str, Any] = dict(parse_result.search_profile)
        local_file_storage_plan = parse_result.local_file_storage_plan

        logger.debug("Saving files by plan: kb_index=%s task_id=%s", kb_index, task_id)
        ref_to_store_result = self._save_files_by_plan(kb_index, _DOMAIN, local_file_storage_plan, task_id=task_id)
        if ref_to_store_result:
            logger.info("Stored %d file(s) for kb_index=%s", len(ref_to_store_result), kb_index)

        chunks = self._hydrate_chunks_with_storage_paths(chunks, ref_to_store_result)

        logger.debug("Upserting binding for kb_index=%s vector_model=%s", kb_index, vector_model)
        binding = self._get_or_create_binding(
            kb_index=kb_index,
            tag=_DOMAIN.lower(),
            parser_script_source=parser_script_source,
            parser_script_sha256=parser_script_sha256,
            vector_model=vector_model,
            search_profile=search_profile,
        )
        logger.debug("Binding ready: binding_id=%s", binding.kb_index)

        logger.info("Vectorizing %d chunk(s): kb_index=%s model=%s", len(chunks), kb_index, vector_model or "default")
        chunks = self._vectorize_if_needed(chunks, vector_model, search_profile)

        logger.info("Writing %d chunk(s) to index: kb_index=%s", len(chunks), kb_index)
        store_result = self._store_parsed_content(kb_index, chunks)
        logger.info(
            "Index write complete: kb_index=%s indexed=%s",
            kb_index, store_result.success_count,
        )

        return {
            "kb_index": kb_index,
            "binding_id": binding.kb_index,
            "chunks_indexed": store_result.success_count,
            "files_stored": len(ref_to_store_result),
            "database_write_status": "ok",
            "file_write_status": "ok",
        }

    def cleanup_task_workspace(self, task_id: str, keep_failed: bool = False) -> None:
        if keep_failed:
            logger.debug("Keeping failed workspace for task %s", task_id)
            return
        task_dir = os.path.join(self._import_work_root, task_id)
        if os.path.isdir(task_dir):
            shutil.rmtree(task_dir, ignore_errors=True)
            logger.debug("Cleaned up workspace for task %s", task_id)

    def sweep_expired_task_workspaces(self, ttl_hours: int = 24, limit: int = 1000) -> int:
        cutoff = time.time() - ttl_hours * 3600
        deleted = 0
        if not os.path.isdir(self._import_work_root):
            return 0
        for entry in os.scandir(self._import_work_root):
            if deleted >= limit:
                break
            if entry.is_dir():
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if mtime < cutoff:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    deleted += 1
        return deleted

    # -------------------------------------------------------------------------
    # Private helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _build_fs_gateway(config: Any, root_dir: str) -> Any:
        """Build a LocalFileSystemGateway (or backend-appropriate gateway) for SKILL files."""
        backend = (
            config.file_system.backend.lower()
            if hasattr(config, "file_system") and config.file_system
            else "local"
        )
        if backend == "local":
            from bible.infrastructure.file_system.local import LocalFileSystemGateway
            fs_cfg = config.file_system.local if hasattr(config, "file_system") else None
            return LocalFileSystemGateway(
                root_dir=root_dir,
                hash_algo=fs_cfg.hash_algo if fs_cfg else "sha256",
                chunk_size=fs_cfg.chunk_size if fs_cfg else 1024 * 1024,
                use_atomic_rename=fs_cfg.use_atomic_rename if fs_cfg else True,
            )
        # For minio/s3 fall back to the shared factory so config is honoured.
        factory = FileSystemFactory(config)
        return factory.get_gateway()

    def _read_file_obj(self, file_obj: Any, idx: int) -> tuple[str, bytes]:
        if isinstance(file_obj, dict):
            filename = file_obj.get("filename") or f"file_{idx}"
            content: bytes = file_obj.get("content", b"")
            return filename, content

        filename = getattr(file_obj, "filename", None) or f"file_{idx}"

        if isinstance(file_obj, (bytes, bytearray)):
            return filename, bytes(file_obj)

        if hasattr(file_obj, "content"):
            return filename, file_obj.content

        if hasattr(file_obj, "file"):
            file_obj.file.seek(0)
            return filename, file_obj.file.read()

        raise ValueError(f"Cannot read file object at index {idx}: {type(file_obj)}")

    def _save_files_by_plan(
        self,
        kb_index: str,
        tag: str,
        local_file_storage_plan: dict[str, Any] | None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        ref_to_result: dict[str, Any] = {}
        if not local_file_storage_plan:
            return ref_to_result

        gateway = self._fs_gateway
        plan_files: list[dict] = local_file_storage_plan.get("files", [])
        task_id = local_file_storage_plan.get("task_id") or task_id

        for file_entry in plan_files:
            file_ref: str = file_entry.get("file_ref", "")
            src_path: str = file_entry.get("abs_path") or file_entry.get("source_path", "")
            filename: str = file_entry.get("filename", os.path.basename(src_path))

            if not src_path or not os.path.exists(src_path):
                logger.warning("Skipping missing file %s (ref=%s)", src_path, file_ref)
                continue

            with open(src_path, "rb") as file_stream:
                store_result = gateway.store(
                    file_stream=file_stream,
                    domain=None,
                    kb_index=None,
                    filename=filename,
                    task_id=task_id,
                )
            ref_to_result[file_ref] = {
                "filename": store_result.filename,
                "storage_path": store_result.storage_path,
                "file_hash": store_result.file_hash,
                "size_bytes": store_result.size_bytes,
            }

        return ref_to_result

    def _hydrate_chunks_with_storage_paths(
        self,
        chunks: list[dict[str, Any]],
        ref_to_store_result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not ref_to_store_result:
            return chunks

        hydrated: list[dict[str, Any]] = []
        for chunk in chunks:
            c = dict(chunk)
            metadata = dict(c.get("metadata") or {})
            file_refs: list[str] = metadata.get("related_file_refs") or []
            if file_refs:
                storage_paths = [
                    ref_to_store_result[ref]["storage_path"]
                    for ref in file_refs
                    if ref in ref_to_store_result
                ]
                metadata["related_storage_paths"] = storage_paths
                c["metadata"] = metadata
            hydrated.append(c)
        return hydrated

    def _get_or_create_binding(
        self,
        kb_index: str,
        tag: str,
        parser_script_source: str,
        parser_script_sha256: str,
        vector_model: str | None,
        search_profile: dict[str, Any],
    ) -> IndexBinding:
        writer = self._db_factory.get_writer(_DOMAIN)
        existing = writer.get_binding_by_domain_index(_DOMAIN, kb_index)

        if existing is not None:
            # For skill re-imports any parameter change (vector_model, parser, search_profile)
            # is intentional — the user is explicitly overwriting with new settings.
            # Update all changed fields in-place so the binding stays consistent with the index.
            new_profile_json = json.dumps(search_profile, ensure_ascii=False, sort_keys=True)
            new_profile_sha256 = hashlib.sha256(new_profile_json.encode()).hexdigest()
            patch: dict[str, Any] = {}
            if existing.vector_model != vector_model:
                patch["vector_model"] = vector_model
            if existing.parser_script_source != parser_script_source:
                patch["parser_script_source"] = parser_script_source
            if existing.parser_script_sha256 != parser_script_sha256:
                patch["parser_script_sha256"] = parser_script_sha256
            if existing.search_profile_sha256 != new_profile_sha256:
                patch["search_profile_json"] = new_profile_json
                patch["search_profile_sha256"] = new_profile_sha256
            if patch:
                logger.info(
                    "Binding for kb_index=%s has changed; updating fields: %s",
                    kb_index, list(patch.keys()),
                )
                writer.update_binding(_DOMAIN, kb_index, patch)
            return IndexBinding(
                domain_type=existing.domain_type,
                kb_index=existing.kb_index,
                tag=existing.tag,
                parser_script_source=parser_script_source,
                parser_script_sha256=parser_script_sha256,
                vector_model=vector_model,
                search_profile_json=new_profile_json,
                search_profile_sha256=new_profile_sha256,
                is_active=existing.is_active,
                created_at=existing.created_at,
            )

        now = datetime.now(timezone.utc).isoformat()
        search_profile_json = json.dumps(search_profile, ensure_ascii=False, sort_keys=True)
        search_profile_sha256 = hashlib.sha256(search_profile_json.encode()).hexdigest()
        binding_doc: dict[str, Any] = {
            "domain_type": _DOMAIN,
            "kb_index": kb_index,
            "tag": tag,
            "parser_script_source": parser_script_source,
            "parser_script_sha256": parser_script_sha256,
            "vector_model": vector_model,
            "search_profile_json": search_profile_json,
            "search_profile_sha256": search_profile_sha256,
            "created_at": now,
        }
        writer.create_index_binding(binding_doc)
        return IndexBinding(
            domain_type=_DOMAIN,
            kb_index=kb_index,
            tag=tag,
            parser_script_source=parser_script_source,
            parser_script_sha256=parser_script_sha256,
            vector_model=vector_model,
            search_profile_json=search_profile_json,
            search_profile_sha256=search_profile_sha256,
            created_at=now,
        )

    def _vectorize_if_needed(
        self,
        chunks: list[dict[str, Any]],
        vector_model: str | None,
        search_profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not vector_model:
            return chunks
        if self._vector_tool is None:
            self._vector_tool = VectorTool(
                workspace_dir=self._workspace_dir,
                hf_cache_dir=self._hf_cache_dir,
            )
        source_template: str | None = search_profile.get("source_template")
        try:
            return self._vector_tool.embed_chunks(chunks, vector_model, source_template)
        except Exception as exc:
            from bible.common.errors import DomainError, ErrorCode
            raise DomainError(
                ErrorCode.INTERNAL,
                f"Vectorization failed: {exc}",
                details={"code": "VECTOR_MODEL_PREPARE_FAILED"},
            )

    def _store_parsed_content(
        self,
        kb_index: str,
        chunks: list[dict[str, Any]],
    ) -> Any:
        writer = self._db_factory.get_writer(_DOMAIN)
        return writer.bulk_upsert_content_docs(kb_index, chunks)

    def assert_binding_consistency(
        self,
        existing_binding: IndexBinding,
        parser_script_sha256: str,
        vector_model: str | None,
        search_profile_sha256: str,
    ) -> None:
        """Raise INDEX_BINDING_CONFLICT if the new import is incompatible with the existing binding."""
        from bible.common.errors import DomainError, ErrorCode

        conflicts: list[str] = []
        if existing_binding.parser_script_sha256 != parser_script_sha256:
            conflicts.append(
                f"parser_script_sha256 changed: {existing_binding.parser_script_sha256[:12]!r} → {parser_script_sha256[:12]!r}"
            )
        if existing_binding.vector_model != vector_model:
            conflicts.append(
                f"vector_model changed: {existing_binding.vector_model!r} → {vector_model!r}"
            )
        if existing_binding.search_profile_sha256 != search_profile_sha256:
            conflicts.append(
                f"search_profile_sha256 changed: {existing_binding.search_profile_sha256[:12]!r} → {search_profile_sha256[:12]!r}"
            )

        if conflicts:
            raise DomainError(
                ErrorCode.CONFLICT,
                "Binding conflict detected for kb_index {!r}: {}".format(
                    existing_binding.kb_index, "; ".join(conflicts)
                ),
                details={"code": "INDEX_BINDING_CONFLICT", "conflicts": conflicts},
            )

