from __future__ import annotations

import importlib

# ---------------------------------------------------------------------------
# Proxy re-exports for feature-level entry points.
# Import-specific symbols still route through `bible.features.import` because
# "import" is a Python keyword and cannot be used in a plain from-import.
# ---------------------------------------------------------------------------

_EXPORT_MAP: dict[str, tuple[str, str]] = {
    # Async task infrastructure
    "build_task_container": ("bible.features.async_task.container", "build_task_container"),
    "get_task_service": ("bible.features.async_task.container", "get_task_service"),
    "get_task_repository": ("bible.features.async_task.container", "get_task_repository"),
    "get_task_dispatcher": ("bible.features.async_task.container", "get_task_dispatcher"),
    "shutdown_task_container": ("bible.features.async_task.container", "shutdown_task_container"),
    "AsyncTaskDispatcher": ("bible.features.async_task.dispatcher", "AsyncTaskDispatcher"),
    # Import feature container
    "build_import_container": ("bible.features.import.container", "build_import_container"),
    # types
    "MemoryImportPayload": ("bible.features.import.types", "MemoryImportPayload"),
    "ParseResult": ("bible.features.import.types", "ParseResult"),
    "FileStoreResult": ("bible.features.import.types", "FileStoreResult"),
    # executor
    "ImportTaskExecutor": ("bible.features.import.import_task_executor", "ImportTaskExecutor"),
    # service
    "MemoryImportService": (
        "bible.features.import.memory_import.memory_import_service",
        "MemoryImportService",
    ),
    # storage
    "StoreMemory": (
        "bible.features.import.memory_import.storage.store_memory",
        "StoreMemory",
    ),
    # parser runtime
    "ASTGuard": ("bible.features.import.parser_runtime.ast_guard", "ASTGuard"),
    "SandboxRunner": ("bible.features.import.parser_runtime.sandbox_runner", "SandboxRunner"),
}


def __getattr__(name: str):  # noqa: ANN001, ANN202
    if name in _EXPORT_MAP:
        mod_path, attr = _EXPORT_MAP[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'bible.features' has no attribute {name!r}")
