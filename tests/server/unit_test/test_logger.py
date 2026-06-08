from __future__ import annotations

import logging

from bible.common.logger import _create_log_handler


def test_file_logger_recreates_deleted_log_file(tmp_path) -> None:
    log_path = tmp_path / "bible-atlas.log"
    handler = _create_log_handler(str(log_path), config=None)
    logger = logging.getLogger("tests.server.test_logger.recreate")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)

    try:
        logger.info("first message")
        handler.flush()
        assert log_path.exists()
        assert "first message" in log_path.read_text(encoding="utf-8")

        log_path.unlink()
        logger.info("second message")
        handler.flush()

        assert log_path.exists()
        assert "second message" in log_path.read_text(encoding="utf-8")
    finally:
        logger.handlers.clear()
        handler.close()
