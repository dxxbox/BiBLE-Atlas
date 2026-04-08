import logging
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Optional, Tuple

def _load_log_config() -> Tuple[str, str, str, Optional[Any]]:
    config = None
    try:
        from bible.common.configure import get_bible_atlas_config

        config = get_bible_atlas_config()
        log_level_str = config.log.level.upper()
        log_format = config.log.format
        log_output = config.log.output

        if log_output == "file":
            workspace_path = Path(config.storage.workspace_dir).resolve()
            log_dir = workspace_path / "log"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_output = str(log_dir / "bible-atlas.log")
    except Exception:
        log_level_str = "INFO"
        log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        log_output = "stdout"

    return log_level_str, log_format, log_output, config

def _create_log_handler(log_output: str, config: Optional[Any]) -> logging.Handler:
    # Prevent creating a file literally named "file"
    if log_output == "file":
        log_output = "stdout"

    if log_output == "stdout":
        return logging.StreamHandler(sys.stdout)
    elif log_output == "stderr":
        return logging.StreamHandler(sys.stderr)
    else:
        if config is not None:
            try:
                log_rotation = config.log.rotation
                if log_rotation:
                    log_rotation_days = config.log.rotation_days
                    log_rotation_interval = config.log.rotation_interval

                    if log_rotation_interval == "midnight":
                        when = "midnight"
                        interval = 1
                    else:
                        when = log_rotation_interval
                        interval = 1

                    return TimedRotatingFileHandler(
                        log_output,
                        when=when,
                        interval=interval,
                        backupCount=log_rotation_days,
                        encoding="utf-8",
                    )
                else:
                    return logging.FileHandler(log_output, encoding="utf-8")
            except Exception:
                return logging.FileHandler(log_output, encoding="utf-8")
        else:
            return logging.FileHandler(log_output, encoding="utf-8")

def get_logger(
    name: str = "bible-atlas",
    format_string: Optional[str] = None,
) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:
        log_level_str, log_format, log_output, config = _load_log_config()
        level = getattr(logging, log_level_str, logging.INFO)
        handler = _create_log_handler(log_output, config)

        if format_string is None:
            format_string = log_format
        formatter = logging.Formatter(format_string)
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.propagate = False
        logger.setLevel(level)

    return logger


# Default logger instance
default_logger = get_logger()