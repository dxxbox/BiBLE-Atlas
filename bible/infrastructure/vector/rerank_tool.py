from __future__ import annotations

import fcntl
import os
import threading
from typing import Any

from bible.common.logger import get_logger
from bible.infrastructure.vector._model_utils import download_lock_path, get_local_model_path

logger = get_logger(__name__)

class RerankTool:
    # Shared model cache – keyed by model_name.
    _model_cache: dict[str, Any] = {}
    _cache_lock = threading.Lock()
    # Limit concurrent predict calls to avoid resource contention.
    _predict_semaphore = threading.Semaphore(3)

    def __init__(self, workspace_dir: str, hf_cache_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir
        # HF cache dir: explicit arg > env var > workspace_dir/hf_cache
        self._hf_cache_dir = (
            hf_cache_dir
            or os.environ.get("HF_HOME")
            or os.path.join(workspace_dir, "hf_cache")
        )

    def _get_cached_model(self, model_name: str) -> Any:
        if model_name not in RerankTool._model_cache:
            self.ensure_model_ready(model_name)
        return RerankTool._model_cache.get(model_name)

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
                    load_kwargs: dict[str, Any] = {}
                    if source == "local":
                        # Prevent AutoModel from making network requests when
                        # loading from a local snapshot.
                        load_kwargs["automodel_args"] = {"local_files_only": True}
                    model = CrossEncoder(load_path, **load_kwargs)
                    logger.info(
                        "Rerank model '%s' loaded (source=%s).", model_name, source
                    )
                    RerankTool._model_cache[model_name] = model
                except Exception as exc:
                    logger.error("Failed to load rerank model '%s': %s", model_name, exc)
                    raise

        return {"model_name": model_name, "status": "ready", "source": source}

    def _download_from_huggingface(self, model_name: str) -> dict[str, Any]:
        """Download via sentence-transformers CrossEncoder (sets HF_HOME first)."""
        os.environ.setdefault("HF_HOME", self._hf_cache_dir)
        return self._load_model(model_name, model_name, source="download")

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

    def ensure_model_ready(self, model_name: str) -> dict[str, Any]:
        with RerankTool._cache_lock:
            if model_name in RerankTool._model_cache:
                logger.info("Rerank model '%s' already in cache.", model_name)
                return {"model_name": model_name, "status": "ready", "source": "cache"}

        lock_file = download_lock_path(model_name, self._hf_cache_dir)
        with open(lock_file, "w") as _lf:
            fcntl.flock(_lf, fcntl.LOCK_EX)
            try:
                with RerankTool._cache_lock:
                    if model_name in RerankTool._model_cache:
                        return {"model_name": model_name, "status": "ready", "source": "cache"}

                local_path = get_local_model_path(model_name, self._hf_cache_dir, required_metadata=["config.json"])

                if local_path:
                    logger.info("Loading rerank Model: '%s' from local path: %s", model_name, local_path)
                    return self._load_model(model_name, local_path, source="local")
                logger.info("Rerank Model '%s' not found locally, downloading...", model_name)
                return self._download_from_huggingface(model_name)
            finally:
                fcntl.flock(_lf, fcntl.LOCK_UN)