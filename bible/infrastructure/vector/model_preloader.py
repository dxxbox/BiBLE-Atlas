from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Any

from bible.common.logger import get_logger
from bible.infrastructure.vector.vector_tool import VectorTool

if TYPE_CHECKING:
    from bible.infrastructure.vector.rerank_tool import RerankTool

logger = get_logger(__name__)