"""Command handlers for top-level command groups."""

from __future__ import annotations

import hashlib
import json
import os
import time
from argparse import Namespace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from bible_cli.client.sync_http import SyncHTTPClient
from bible_cli.exceptions import BibleCLIError, CommandNotImplementedError, InvalidArgumentError
from bible_cli.utils.config import ClientConfig

MEMORY_CACHE_FILENAME = ".bible-memory-cache.json"
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
TASK_POLL_INTERVAL = 3.0   # seconds
TASK_POLL_MAX_WAIT = 300.0  # seconds


class _BaseCommands:
    group_name: str
    client_config: ClientConfig
    client: SyncHTTPClient

    def __init__(self) -> None:
        self.client_config = ClientConfig.from_env()
        self.client = SyncHTTPClient(config=self.client_config.as_client_dict())

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class HealthCommands(_BaseCommands):
    group_name = "health"

    def execute(self, args: Namespace) -> int:
        try:
            print(json.dumps(self.client.health(), ensure_ascii=True))
            return 0
        finally:
            self.client.close()


class SystemCommands(_BaseCommands):
    group_name = "system"

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        try:
            if action == "status":
                print(json.dumps(self.client.status(), ensure_ascii=True))
                return 0
            if action == "info":
                print(json.dumps(self.client.info(), ensure_ascii=True))
                return 0
        finally:
            self.client.close()
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class KnowledgeCommands(_BaseCommands):
    group_name = "knowledge"

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        try:
            if action == "list":
                print(json.dumps(self.client.knowledge_list(), ensure_ascii=True))
                return 0
            if action == "search":
                query = getattr(args, "query", None)
                print(json.dumps(self.client.knowledge_search(query=query), ensure_ascii=True))
                return 0
        finally:
            self.client.close()
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())


class MemoryCommands(_BaseCommands):
    group_name = "memory"

    def execute(self, args: Namespace) -> int:
        action = getattr(args, "action", None) or "default"
        try:
            if action == "upload":
                return self._cmd_upload(args)
            if action == "upload-all":
                return self._cmd_upload_all(args)
            if action == "build-meta":
                return self._cmd_build_meta(args)
            if action == "status":
                return self._cmd_status(args)
            if action == "search":
                return self._cmd_search(args)
        finally:
            self.client.close()
        raise CommandNotImplementedError(f"{self.group_name} {action}".strip())

    # ------------------------------------------------------------------
    # upload
    # ------------------------------------------------------------------

    def _cmd_upload(self, args: Namespace) -> int:
        session_dir: Path = args.session_dir.resolve()
        kb_index = self._resolve_kb_index(getattr(args, "kb_index", None))
        skip_if_exists: bool = getattr(args, "skip_if_exists", True)
        vector_model: str | None = getattr(args, "vector_model", None)
        task_ids: list[str] = getattr(args, "task_ids", [])
        feature_tags: list[str] = getattr(args, "feature_tags", [])
        title_override: str | None = getattr(args, "title", None)
        abstract_override: str | None = getattr(args, "abstract", None)
        wait: bool = getattr(args, "wait", False)

        return self._upload_one(
            session_dir=session_dir,
            kb_index=kb_index,
            skip_if_exists=skip_if_exists,
            vector_model=vector_model,
            task_ids=task_ids,
            feature_tags=feature_tags,
            title_override=title_override,
            abstract_override=abstract_override,
            wait=wait,
        )

    # ------------------------------------------------------------------
    # upload-all
    # ------------------------------------------------------------------

    def _cmd_upload_all(self, args: Namespace) -> int:
        base_dir: Path = args.base_dir.resolve()
        kb_index = self._resolve_kb_index(getattr(args, "kb_index", None))
        skip_if_exists: bool = getattr(args, "skip_if_exists", True)
        vector_model: str | None = getattr(args, "vector_model", None)
        wait: bool = getattr(args, "wait", False)

        if not base_dir.is_dir():
            raise InvalidArgumentError(f"base_dir does not exist: {base_dir}")

        session_dirs = sorted(
            d for d in base_dir.iterdir()
            if d.is_dir() and (d / "message.json").exists()
        )
        if not session_dirs:
            print(f"[WARN] No session directories found under {base_dir}")
            return 0

        errors = 0
        for sd in session_dirs:
            rc = self._upload_one(
                session_dir=sd,
                kb_index=kb_index,
                skip_if_exists=skip_if_exists,
                vector_model=vector_model,
                task_ids=[],
                feature_tags=[],
                wait=wait,
            )
            if rc != 0:
                errors += 1

        print(f"[DONE] upload-all: {len(session_dirs)} dirs, {errors} errors.")
        return 0 if errors == 0 else 1

    # ------------------------------------------------------------------
    # build-meta
    # ------------------------------------------------------------------

    def _cmd_build_meta(self, args: Namespace) -> int:
        session_dir: Path = args.session_dir.resolve()
        force: bool = getattr(args, "force", False)
        title_override: str | None = getattr(args, "title", None)
        abstract_override: str | None = getattr(args, "abstract", None)
        task_ids: list[str] = getattr(args, "task_ids", [])
        feature_tags: list[str] = getattr(args, "feature_tags", [])

        meta_path = session_dir / "meta.json"
        if meta_path.exists() and not force:
            print(f"[SKIP] meta.json already exists: {meta_path}  (use --force to overwrite)")
            return 0

        message_path = session_dir / "message.json"
        if not message_path.exists():
            raise InvalidArgumentError(f"message.json not found in {session_dir}")

        meta = _build_meta_from_message_json(
            message_path,
            task_ids=task_ids,
            feature_tags=feature_tags,
            title_override=title_override,
            abstract_override=abstract_override,
        )
        _save_json(meta_path, meta)
        print(f"[OK] meta.json written: {meta_path}")
        print(f"     memory_id = {meta['memory_id']}")
        print(f"     title     = {meta['title']}")
        return 0

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _cmd_status(self, args: Namespace) -> int:
        target: str = args.target
        task_id = self._resolve_task_id(target)
        result = self.client.memory_task_status(task_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # ------------------------------------------------------------------
    # search
    # ------------------------------------------------------------------

    def _cmd_search(self, args: Namespace) -> int:
        kb_index = self._resolve_kb_index(getattr(args, "kb_index", None))
        query: str = args.query
        search_type: str = getattr(args, "search_type", "hybrid")
        top_k: int = getattr(args, "top_k", 10)
        tag: str | None = getattr(args, "tag", None)

        result = self.client.memory_search(
            kb_index=kb_index,
            query=query,
            search_type=search_type,
            top_k=top_k,
            tag=tag,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _upload_one(
        self,
        *,
        session_dir: Path,
        kb_index: str,
        skip_if_exists: bool,
        vector_model: str | None,
        task_ids: list[str],
        feature_tags: list[str],
        title_override: str | None = None,
        abstract_override: str | None = None,
        wait: bool,
    ) -> int:
        message_path = session_dir / "message.json"
        meta_path = session_dir / "meta.json"

        # 1. Ensure meta.json exists (build from message.json if missing)
        if not meta_path.exists():
            if not message_path.exists():
                print(f"[SKIP] {session_dir.name}: neither meta.json nor message.json found.")
                return 1
            meta = _build_meta_from_message_json(
                message_path,
                task_ids=task_ids,
                feature_tags=feature_tags,
                title_override=title_override,
                abstract_override=abstract_override,
            )
            _save_json(meta_path, meta)
        else:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if task_ids or feature_tags:
                meta["task_ids"] = list({*meta.get("task_ids", []), *task_ids})
                meta["feature_tags"] = list({*meta.get("feature_tags", []), *feature_tags})
                _save_json(meta_path, meta)

        # 2. Validate required fields
        missing = [f for f in ("memory_id", "title", "abstract") if not meta.get(f)]
        if missing:
            raise InvalidArgumentError(
                f"meta.json missing required fields: {missing}",
                details={"session_dir": str(session_dir)},
            )

        # 3. File size guard
        if meta_path.stat().st_size > MAX_FILE_SIZE_BYTES:
            print(f"[SKIP] {session_dir.name}: meta.json exceeds 20 MB limit.")
            return 1

        # 4. Idempotency check using meta_hash + kb_index
        meta_hash = _sha256_file(meta_path)
        if skip_if_exists:
            cached = _load_cache(session_dir)
            if (
                cached
                and cached.get("meta_hash") == meta_hash
                and cached.get("kb_index") == kb_index
                and cached.get("upload_status") == "completed"
            ):
                print(f"[SKIP] {meta['memory_id']}: already uploaded with same meta content.")
                return 0

        # 5. Upload
        payload = self.client.memory_import(
            meta_path=meta_path,
            kb_index=kb_index,
            message_path=message_path if message_path.exists() else None,
            vector_model=vector_model,
        )

        task_id: str = payload.get("task_id") or ""
        status: str = payload.get("status", "unknown")
        print(f"[OK] {meta['memory_id']}: status={status} task_id={task_id}")

        # 6. Write v4 cache
        _save_cache(session_dir, {
            "memory_id": meta["memory_id"],
            "kb_index": kb_index,
            "meta_hash": meta_hash,
            "task_id": task_id,
            "upload_status": "pending" if status in ("accepted", "pending") else status,
            "uploaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "server_url": self.client_config.base_url,
        })

        # 7. Optionally poll task to completion
        if wait and task_id:
            final = self._poll_task(task_id)
            final_status = final.get("status", "unknown")
            current_cache = _load_cache(session_dir) or {}
            _save_cache(session_dir, {**current_cache, "upload_status": final_status})
            print(f"[DONE] {meta['memory_id']}: final_status={final_status}")
            if final_status in ("failure", "failed", "FAILED"):
                return 1

        return 0

    def _poll_task(self, task_id: str) -> dict[str, Any]:
        """Synchronous task polling loop."""
        deadline = time.monotonic() + TASK_POLL_MAX_WAIT
        while time.monotonic() < deadline:
            result = self.client.memory_task_status(task_id)
            status = (result.get("status") or "").lower()
            if status in ("success", "succeeded", "failure", "failed", "error"):
                return result
            time.sleep(TASK_POLL_INTERVAL)
        return {"status": "timeout", "task_id": task_id}

    @staticmethod
    def _resolve_kb_index(cli_value: str | None) -> str:
        value = (
            cli_value
            or os.environ.get("BIBLE_MEMORY_KB_INDEX")
            or ""
        )
        if not value:
            raise InvalidArgumentError(
                "kb_index is required. Provide --kb-index or set BIBLE_MEMORY_KB_INDEX env var."
            )
        return value

    @staticmethod
    def _resolve_task_id(target: str) -> str:
        """Resolve a task_id from a bare ID or a session directory path."""
        p = Path(target)
        if p.is_dir():
            cached = _load_cache(p)
            if not cached or not cached.get("task_id"):
                raise InvalidArgumentError(
                    f"No task_id found in cache for session dir: {p}. "
                    "Run 'bible memory upload' first."
                )
            return cached["task_id"]
        return target


class SkillsCommands(_BaseCommands):
    group_name = "skills"


# ---------------------------------------------------------------------------
# Shared meta.json helpers (used only by CLI handlers; standalone script has
# its own copies to remain dependency-free)
# ---------------------------------------------------------------------------

def _build_meta_from_message_json(
    message_path: Path,
    *,
    task_ids: list[str] | None = None,
    feature_tags: list[str] | None = None,
    title_override: str | None = None,
    abstract_override: str | None = None,
) -> dict[str, Any]:
    """Construct a v4 meta.json dict from message.json content."""
    data: dict[str, Any] = json.loads(message_path.read_text(encoding="utf-8"))

    session_id = (
        str(data.get("session_id") or "").strip()
        or str((data.get("sourceClient") or {}).get("sessionId") or "").strip()
        or str(data.get("requestId") or "").strip()
        or ""
    )
    if session_id:
        memory_id = f"mem_{session_id}"
    else:
        memory_id = f"mem_{_sha256_str(str(message_path))[:16]}"

    first_user_text = ""
    for req in data.get("requests", []):
        text = str((req.get("message") or {}).get("text") or "").strip()
        if text:
            first_user_text = text
            break

    title = title_override or first_user_text[:100].strip() or f"Session {date.today()}"
    abstract = abstract_override or first_user_text[:300].strip() or title

    src = data.get("sourceClient") or {}
    source_client = str(src.get("kind") or "unknown")

    created_at = _extract_timestamp(data)

    return {
        "memory_id": memory_id,
        "title": title,
        "abstract": abstract,
        "overview": "",
        "created_at": created_at,
        "task_ids": list(task_ids or []),
        "feature_tags": list(feature_tags or []),
        "domain_tags": [],
        "component_tags": [],
        "source_client": source_client,
        "language": "zh",
    }


def _extract_timestamp(data: dict[str, Any]) -> str:
    src = data.get("sourceClient") or {}
    for key in ("exportedAt", "createdAt"):
        ts = str(src.get(key) or "").strip()
        if ts:
            return ts
    for req in data.get("requests", []):
        ts = str(req.get("timestamp") or req.get("created_at") or "").strip()
        if ts:
            return ts
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _load_cache(session_dir: Path) -> dict[str, Any] | None:
    p = session_dir / MEMORY_CACHE_FILENAME
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save_cache(session_dir: Path, entry: dict[str, Any]) -> None:
    p = session_dir / MEMORY_CACHE_FILENAME
    try:
        p.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
