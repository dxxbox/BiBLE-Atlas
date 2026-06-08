"""Rerank tool backed by sentence-transformers CrossEncoder.

Design mirrors :class:`VectorTool`:
- Thread-safe in-process model cache (class-level dict + lock).
- Cross-process exclusive download lock (``fcntl.LOCK_EX``) prevents multiple
  processes from downloading the same model simultaneously.
- Graceful fallback (scores of 0.0) when sentence-transformers is unavailable,
  so the rest of the search pipeline can operate in lightweight environments.

Shared utilities (``get_local_model_path``, ``download_lock_path``) live in
:mod:`bible.infrastructure.vector._model_utils` and are reused by both tools.
"""
from __future__ import annotations

import fcntl
import os
import threading
from typing import Any

from bible.common.logger import get_logger
from bible.infrastructure.vector._model_utils import (
    download_lock_path,
    get_local_model_path,
    resolve_hf_cache_dir,
)

logger = get_logger(__name__)


class RerankTool:
    """Thread-safe rerank tool backed by sentence-transformers CrossEncoder.

    Falls back to zero scores when sentence-transformers is not installed so
    that search pipelines can be exercised without the heavy ML dependency.

    Cross-encoder / reranker models are plain Transformers checkpoints and do
    **not** contain ``modules.json``; the local-cache check therefore only
    requires ``config.json`` + a weights file.
    """

    # Shared model cache – keyed by model_name.
    _model_cache: dict[str, Any] = {}
    _cache_lock = threading.Lock()
    # Limit concurrent predict calls to avoid resource contention.
    _predict_semaphore = threading.Semaphore(3)

    def __init__(self, workspace_dir: str, hf_cache_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir
        # HF cache dir: explicit arg > env var > workspace_dir/hf_cache
        self._hf_cache_dir = resolve_hf_cache_dir(workspace_dir, hf_cache_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_model_ready(self, model_name: str) -> dict[str, Any]:
        """Load reranker from local cache; download if absent. Returns status dict.

        Uses the same cross-process exclusive lock pattern as :class:`VectorTool`
        so only one process downloads a model even when the server and Celery
        worker start simultaneously.
        """
        # Fast path: model already in this process's memory.
        with RerankTool._cache_lock:
            if model_name in RerankTool._model_cache:
                logger.info("Rerank model '%s' already in cache.", model_name)
                return {"model_name": model_name, "status": "ready", "source": "cache"}

        lock_file = download_lock_path(model_name, self._hf_cache_dir)
        with open(lock_file, "w") as _lf:
            fcntl.flock(_lf, fcntl.LOCK_EX)
            try:
                # Re-check after acquiring the lock.
                with RerankTool._cache_lock:
                    if model_name in RerankTool._model_cache:
                        return {"model_name": model_name, "status": "ready", "source": "cache"}

                # Cross-encoder models only need config.json (no modules.json).
                local_path = get_local_model_path(
                    model_name,
                    self._hf_cache_dir,
                    required_metadata=["config.json"],
                )
                if local_path:
                    logger.info(
                        "Loading rerank model '%s' from local path: %s", model_name, local_path
                    )
                    return self._load_model(model_name, local_path, source="local")
                logger.info(
                    "Rerank model '%s' not found locally under %s, downloading…",
                    model_name,
                    self._hf_cache_dir,
                )
                return self._download_from_huggingface(model_name)
            finally:
                fcntl.flock(_lf, fcntl.LOCK_UN)

    def rerank(
        self,
        query: str,
        passages: list[str],
        model_name: str,
    ) -> list[float]:
        """Score each passage against *query*; higher score = more relevant.

        Returns a list of floats aligned with *passages*.  Returns zeros when
        the model is unavailable (sentence-transformers not installed).
        """
        if not passages:
            return []
        model = self._get_cached_model(model_name)
        if model is None:
            return [0.0] * len(passages)

        pairs = [[query, p] for p in passages]
        try:
            with RerankTool._predict_semaphore:
                scores: list[float] = model.predict(pairs).tolist()
            return scores
        except Exception as exc:
            logger.error("Rerank scoring failed for model '%s': %s", model_name, exc)
            return [0.0] * len(passages)

    def score(self, query: str, passage: str, model_name: str) -> float:
        """Convenience wrapper to score a single (query, passage) pair."""
        scores = self.rerank(query, [passage], model_name)
        return scores[0] if scores else 0.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _download_from_huggingface(self, model_name: str) -> dict[str, Any]:
        """Download via sentence-transformers CrossEncoder using configured cache."""
        os.environ.setdefault("HF_HOME", self._hf_cache_dir)
        os.environ.setdefault(
            "HUGGINGFACE_HUB_CACHE",
            os.path.join(self._hf_cache_dir, "hub"),
        )
        result = self._load_model(model_name, model_name, source="download")
        local_path = get_local_model_path(
            model_name,
            self._hf_cache_dir,
            required_metadata=["config.json"],
        )
        logger.info(
            "Rerank model '%s' download/load complete; cache_dir=%s local_path=%s",
            model_name,
            self._hf_cache_dir,
            local_path or "<not found>",
        )
        return result

    def _load_model(self, model_name: str, load_path: str, source: str) -> dict[str, Any]:
        try:
            from sentence_transformers import CrossEncoder  # type: ignore[import]
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; rerank model '%s' will use zero scores.",
                model_name,
            )
            with RerankTool._cache_lock:
                RerankTool._model_cache[model_name] = None
            return {"model_name": model_name, "status": "fallback", "source": source}

        with RerankTool._cache_lock:
            if model_name not in RerankTool._model_cache:
                try:
                    load_kwargs: dict[str, Any] = {"cache_folder": self._hf_cache_dir}
                    if source == "local":
                        # Prevent network requests when loading from a local snapshot.
                        load_kwargs["local_files_only"] = True
                    model = CrossEncoder(load_path, **load_kwargs)
                    logger.info(
                        "Rerank model '%s' loaded (source=%s).", model_name, source
                    )
                    RerankTool._model_cache[model_name] = model
                except Exception as exc:
                    logger.error("Failed to load rerank model '%s': %s", model_name, exc)
                    raise

        return {"model_name": model_name, "status": "ready", "source": source}

    def _get_cached_model(self, model_name: str) -> Any:
        if model_name not in RerankTool._model_cache:
            self.ensure_model_ready(model_name)
        return RerankTool._model_cache.get(model_name)
