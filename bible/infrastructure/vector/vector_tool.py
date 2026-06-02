from __future__ import annotations
import fcntl
import os
import threading
from typing import Any
from bible.common.logger import get_logger
from bible.infrastructure.vector._model_utils import download_lock_path, get_local_model_path

logger = get_logger(__name__)

# Fallback embedding dimension when sentence-transformers is unavailable. 
_FALLBACK_DIM = 384

def _get_embedding_dimension (model:Any) -> int:
    """Return the embedding dimension of a SentenceTransformer model.

    ``get_embedding_dimension`` is the current API (sentence-transformers ≥ 3.x);
    ``get_sentence_embedding_dimension`` is the legacy name kept for backward
    compatibility with older installations.
    """
    try:
        return model.get_embedding_dimension()
    except AttributeError:
        pass
    try:
        return model.get_sentence_embedding_dimension()
    except Exception:
        return _FALLBACK_DIM

class VectorTool:

    _model_cache: dict[str, Any] = {}
    _cache_lock = threading.Lock()
    _encode_semaphore = threading.Semaphore(3)

    def __init__(self, workspace_dir: str, hf_cache_dir: str | None = None) -> None:
        self._workspace_dir = workspace_dir
        # HF cache dir: explicit arg > env var > workspace_dir/hf_cache
        self._hf_cache_dir = (
            hf_cache_dir
            or os.environ.get("HF_HOME")
            or os.path.join(workspace_dir, "hf_cache")
        )

    def ensure_model_ready(self, model_name: str) -> dict[str, Any]:
        """Load model from local cache; download if absent. Returns status dict.

        A cross-process exclusive file lock (fcntl LOCK_EX) ensures that only
        one process ever downloads a given model.  The second process blocks on
        the lock; once it is released it re-checks the local HF cache and loads
        the already-downloaded snapshot instead of triggering a second download.
        """
        # Fast path: model already loaded in this process's memory.
        with VectorTool._cache_lock:
            if model_name in VectorTool._model_cache:
                logger.info("Model '%s' already in cache.", model_name)
                return {"model_name": model_name, "status": "ready", "source": "cache"}

        # Cross-process exclusive lock – prevents parallel downloads across the
        # FastAPI server process and the Celery worker process.
        lock_path = self._download_lock_path(model_name)
        with open(lock_path, "w") as _lf:
            fcntl.flock(_lf, fcntl.LOCK_EX)
            try:
                # Re-check after acquiring lock: another process may have just
                # finished downloading while we were waiting.
                with VectorTool._cache_lock:
                    if model_name in VectorTool._model_cache:
                        return {"model_name": model_name, "status": "ready", "source": "cache"}
                local_path = get_local_model_path(model_name, self._hf_cache_dir)
                if local_path:
                    logger.info(
                        "Loading model '%s' from local path: %s", model_name, local_path
                    )
                    return self._load_model(model_name, local_path, source="local")
                logger.info("Model '%s' not found locally, downloading…", model_name)
                return self.download_from_huggingface(model_name)
            finally:
                fcntl.flock(_lf, fcntl.LOCK_UN)

    def _download_lock_path(self, model_name: str) -> str:
        """Return the path to the per-model cross-process download lock file."""
        return download_lock_path(model_name, self._hf_cache_dir)

    def download_from_huggingface(self, model_name: str) -> dict[str, Any]:
        """Download model via sentence-transformers (sets HF_HOME beforehand)."""
        os.environ.setdefault("HF_HOME", self._hf_cache_dir)
        return self._load_model(model_name, model_name, source="download")
    
    def embed_chunks(
        self,
        chunks: list[dict[str, Any]],
        model_name: str,
        source_template: str | None = None,
    ) -> list[dict[str, Any]]:
        """Add ``content_vector`` to each chunk. Uses source_template when set."""
        model = self._get_cached_model(model_name)

        result: list[dict[str, Any]] = []
        for chunk in chunks:
            text = self._extract_text(chunk, source_template)
            vector = self._encode(model, text, model_name)
            enriched = dict(chunk)
            enriched["content_vector"] = vector
            result.append(enriched)
        return result

    def embed_query(self, query: str, model_name: str) -> list[float]:
        """Encode a single query string into a dense vector.

        Ensures the model is loaded before encoding.  Returns a zero-vector
        when sentence-transformers is unavailable (same fallback as
        :meth:`embed_chunks`).
        """
        model = self._get_cached_model(model_name)
        return self._encode(model, query, model_name)

    def get_dims(self, model_name: str) -> int:
        """Return the embedding dimension for a loaded model."""
        model = self._get_cached_model(model_name)
        if model is None:
            return _FALLBACK_DIM
        return _get_embedding_dimension(model)
    
    def _get_cached_model(self, model_name: str) -> Any:
        if model_name not in VectorTool._model_cache:
            self.ensure_model_ready(model_name)
        return VectorTool._model_cache.get(model_name)

    def _load_model(self, model_name: str, load_path: str, source: str) -> dict[str, Any]:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import]
        except ImportError:
            logger.warning(
                "sentence-transformers not installed; model '%s' will use zero-vectors.",
                model_name,
            )
            with VectorTool._cache_lock:
                VectorTool._model_cache[model_name] = None
            return {"model_name": model_name, "status": "fallback", "source": source}

        with VectorTool._cache_lock:
            if model_name not in VectorTool._model_cache:
                try:
                    # local_files_only=True prevents sentence-transformers ≥ 5.x
                    # from calling AutoProcessor.from_pretrained() with a network
                    # request when loading from a local snapshot path.
                    load_kwargs: dict[str, Any] = {}
                    if source == "local":
                        load_kwargs["local_files_only"] = True
                    model = SentenceTransformer(load_path, **load_kwargs)
                    actual_dims = _get_embedding_dimension(model)
                    logger.info(
                        "Model '%s' loaded (dims=%d, source=%s).", model_name, actual_dims, source
                    )
                    VectorTool._model_cache[model_name] = model
                except Exception as exc:
                    logger.error("Failed to load model '%s': %s", model_name, exc)
                    raise

        return {"model_name": model_name, "status": "ready", "source": source}
    
    def _encode(self, model: Any, text: str, model_name: str) -> list[float]:
        if model is None:
            # sentence-transformers not installed – return zero-vector
            return [0.0] * _FALLBACK_DIM

        if not text or not text.strip():
            return [0.0] * _get_embedding_dimension(model)

        try:
            with VectorTool._encode_semaphore:
                vector: list[float] = model.encode(text).tolist()
            return vector
        except Exception as exc:
            logger.error("Encoding failed for model '%s': %s", model_name, exc)
            return [0.0] * _get_embedding_dimension(model)
        
    @staticmethod
    def _extract_text(chunk: dict[str, Any], source_template: str | None) -> str:
        if source_template:
            try:
                return source_template.format(**chunk)
            except (KeyError, ValueError):
                pass
        # Fallback: use common text fields
        for field in ("text", "content", "body", "title"):
            val = chunk.get(field)
            if val and isinstance(val, str):
                return val
        return str(chunk)