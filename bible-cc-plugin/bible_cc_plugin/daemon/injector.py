"""Context injection — queries BiBLE Atlas and returns formatted context string."""

from __future__ import annotations

import logging

from ..config import BibleCCConfig
from ..client import BibleAtlasClient
from ..recall import run_recall_pipeline
from .buffer import Buffer

logger = logging.getLogger(__name__)


class ContextInjector:
    def __init__(self, config: BibleCCConfig, client: BibleAtlasClient, buffer: Buffer) -> None:
        self.config = config
        self.client = client
        self.buffer = buffer
        self._manual_saves: set[str] = set()

    def notify_manual_save(self, session_id: str) -> None:
        self._manual_saves.add(session_id)

    def inject(self, session_id: str, user_message: str) -> str:
        if not self.config.enable_memory_recall and not self.config.enable_knowledge_recall:
            return ""

        recall_config = self.config
        if self.config.force_injection:
            from copy import copy
            recall_config = copy(self.config)
            recall_config.enable_memory_recall = True
            recall_config.enable_knowledge_recall = True

        turns = self.buffer.get_turns(session_id, limit=12)
        history = [
            {"role": t["role"], "content": t["content"]}
            for t in turns[:-1] if t["role"] == "user"
        ]

        try:
            rendered, warnings = run_recall_pipeline(
                user_message=user_message,
                conversation_history=history,
                config=recall_config,
                client=self.client,
            )
            for w in warnings:
                logger.debug("recall warning: %s", w)
            return rendered
        except Exception as exc:
            logger.warning("inject failed (non-fatal): %s", exc)
            return ""
