from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from bible.common.logger import get_logger
from bible.infrastructure.vector.vector_tool import VectorTool

if TYPE_CHECKING:
    from bible.infrastructure.vector.rerank_tool import RerankTool

logger = get_logger(__name__)


class VectorModelPreloader:
    """Preloads configured vector and/or rerank models at application startup.

    Mirrors the async-thread pattern from the legacy ``model_preloader.py``:
    ``preload_all_models_async()`` spawns a daemon thread so the HTTP server
    starts immediately while model loading proceeds in the background.

    Both ``vector_tool`` and ``rerank_tool`` are optional; pass whichever tools
    correspond to the models you want to preload.  ``preload_all_models()`` is a
    no-op when neither tool is provided.
    """

    def __init__(
        self,
        config: Any,
        vector_tool: VectorTool | None = None,
        rerank_tool: "RerankTool | None" = None,
    ) -> None:
        self._config = config
        self._vector_tool = vector_tool
        self._rerank_tool = rerank_tool

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def preload_all_models_async(self) -> threading.Thread:
        """Start background model preloading and return the daemon thread."""
        logger.info("Starting background model preload thread…")
        thread = threading.Thread(
            target=self._preload_background,
            daemon=True,
            name="VectorModelPreloader",
        )
        thread.start()
        logger.info(
            "Model preload thread started. "
            "Models will be ready once loading completes."
        )
        return thread

    def preload_all_models(self) -> tuple[int, list[tuple[str, str]]]:
        """Synchronously preload all configured vector and rerank models.

        Returns ``(success_count, failed_list)`` where each failed entry is
        ``(model_name, error_message)``.  Counts across both model types are
        aggregated into a single result.
        """
        total_success = 0
        total_failed: list[tuple[str, str]] = []

        if self._vector_tool is not None:
            s, f = self._preload_group(
                label="vector",
                models=self._get_model_list(),
                tool=self._vector_tool,
            )
            total_success += s
            total_failed.extend(f)

        if self._rerank_tool is not None:
            s, f = self._preload_group(
                label="rerank",
                models=self._get_rerank_model_list(),
                tool=self._rerank_tool,
            )
            total_success += s
            total_failed.extend(f)

        if self._vector_tool is None and self._rerank_tool is None:
            logger.info("No model tools configured for preloading.")

        return total_success, total_failed

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _preload_background(self) -> None:
        try:
            self.preload_all_models()
        except Exception:
            logger.exception("Background model preload raised an unexpected error.")

    def _preload_group(
        self,
        label: str,
        models: list[str],
        tool: Any,
    ) -> tuple[int, list[tuple[str, str]]]:
        """Load a list of models using *tool.ensure_model_ready*."""
        if not models:
            logger.info("No %s models configured for preloading.", label)
            return 0, []

        logger.info("=" * 60)
        logger.info("Preloading %d %s model(s)…", len(models), label)
        logger.info("=" * 60)

        success_count = 0
        failed: list[tuple[str, str]] = []

        for idx, model_name in enumerate(models, 1):
            logger.info("[%d/%d] Loading %s model: %s", idx, len(models), label, model_name)
            try:
                info = tool.ensure_model_ready(model_name)
                logger.info(
                    "  ✓ %s model '%s' ready (source=%s).",
                    label,
                    model_name,
                    info.get("source", "?"),
                )
                success_count += 1
            except Exception as exc:
                logger.error("  ✗ Failed to load %s model '%s': %s", label, model_name, exc)
                failed.append((model_name, str(exc)))

        logger.info("=" * 60)
        logger.info(
            "%s model preload complete: %d/%d succeeded.",
            label.capitalize(),
            success_count,
            len(models),
        )
        if failed:
            for name, err in failed:
                logger.warning("  Failed: %s — %s", name, err)
        logger.info("=" * 60)

        return success_count, failed

    def _get_model_list(self) -> list[str]:
        """Return HuggingFace ids for vector models from ``config.vector.available_models``.

        Accepts a list of strings (legacy) or objects/dicts with a ``name`` field.
        """
        try:
            raw = self._config.vector.available_models or []
        except AttributeError:
            return []
        return [r for item in raw if (r := self._resolve_preload_model_ref(item))]

    def _get_rerank_model_list(self) -> list[str]:
        """Return HuggingFace ids for rerank models from ``config.rerank.available_models``."""
        try:
            raw = self._config.rerank.available_models or []
        except AttributeError:
            return []
        return [r for item in raw if (r := self._resolve_preload_model_ref(item))]

    @staticmethod
    def _resolve_preload_model_ref(item: Any) -> str | None:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            name = item.get("name")
            return name if isinstance(name, str) and name else None
        name = getattr(item, "name", None)
        return name if isinstance(name, str) and name else None
