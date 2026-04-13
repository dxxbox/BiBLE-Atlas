import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from bible.common.consts import (
    CONFIG_PATH_ENV_VAR,
    DEFAULT_CONFIG_PATH_JSON,
    DEFAULT_CONFIG_PATH_YAML,
)


def resolve_existing_path(file_path: Path | str) -> Optional[Path]:
    candidate_path = Path(os.path.expandvars(os.path.expanduser(file_path))).resolve(strict=False)
    if not candidate_path.exists():
        return None
    return candidate_path


def resolve_config_path(explicit_path: Path | str | None = None) -> Optional[Path]:
    """Resolve the configuration file path using the following precedence:
    1. Explicitly provided path
    2. Environment variable
    3. Default paths
    """
    if explicit_path is not None:
        return resolve_existing_path(explicit_path)

    env_path = os.getenv(CONFIG_PATH_ENV_VAR)
    if env_path is not None:
        return resolve_existing_path(env_path)

    for default_path in (DEFAULT_CONFIG_PATH_JSON, DEFAULT_CONFIG_PATH_YAML):
        resolved_path = resolve_existing_path(default_path)
        if resolved_path is not None:
            return resolved_path

    return None


def load_raw_config_from_file(file_path: Path | str) -> Dict[str, Any]:
    """Load raw configuration data from a JSON or YAML file."""
    config_path = Path(file_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")

    with open(config_path, "r", encoding="utf-8") as file:
        raw = file.read()

    raw = os.path.expandvars(raw)
    if config_path.suffix in {".yaml", ".yml"}:
        config_data = yaml.safe_load(raw)
    else:
        config_data = json.loads(raw)

    return {} if config_data is None else config_data
