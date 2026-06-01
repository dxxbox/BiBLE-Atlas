from __future__ import annotations

import importlib

_EXPORT_MAP: dict[str, tuple[str, str]] = {

    "build_task_container": ("bible.features.async_task.container", "build_task_container"),
    "get_task_service": ("bible.features.async_task.container", "get_task_service"),
    "get_task_repository": ("bible.features.async_task.container", "get_task_repository"),
    "get_task_dispatcher": ("bible.features.async_task.container", "get_task_dispatcher"),
    "shutdown_task_container": ("bible.features.async_task.container", "shutdown_task_container"),
    "AsyncTaskDispatcher": ("bible.features.async_task.dispatcher", "AsyncTaskDispatcher"),

    "build_import_container": ("bible.features.import.container", "build_import_container"),

    "MemoryImportPayload": ("bible.features.import.types", "MemoryImportPayload"),
    "ParseResult": ("bible.features.import.types", "ParseResult"),
    "FileStoreResult": ("bible.features.import.types", "FileStoreResult"),

    "ImportTaskExecutor": ("bible.features.import.import_task_executor", "ImportTaskExecutor"),

    "MemoryImportService": (
        "bible.features.import.memory_import.memory_import_service",
        "MemoryImportService",
    ),

    "StoreMemory": (
        "bible.features.import.memory_import.storage.store_memory",
        "StoreMemory",
    ),

    "ASTGuard": ("bible.features.import.parser_runtime.ast_guard", "ASTGuard"),
    "SandboxRunner": ("bible.features.import.parser_runtime.sandbox_runner", "SandboxRunner"),
}

def __getattr__(name: str):
    if name in _EXPORT_MAP:
        mod_path, attr = _EXPORT_MAP[name]
        mod = importlib.import_module(mod_path)
        return getattr(mod, attr)
    raise AttributeError(f"module 'bible.features' has no attribute {name!r}")
