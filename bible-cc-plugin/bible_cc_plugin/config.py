"""BiBLE CC Plugin — configuration resolution.

Reads from ~/.bible-cc/config.yaml with env var overrides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BibleCCConfig:
    # BiBLE Atlas connection
    base_url: str
    token: str | None = None
    timeout_ms: int = 30_000
    default_kb_index: str = "kb_memory_main"
    source_client: str = "claude-code"

    # Daemon
    daemon_port: int = 9777
    db_path: str = "~/.bible-cc/daemon.db"

    # Context recall
    enable_memory_recall: bool = True
    enable_knowledge_recall: bool = False
    knowledge_tags: list[str] = field(default_factory=list)
    recall_top_k: int = 8
    recall_min_score: float = 0.35
    injection_token_budget: int = 1200
    force_injection: bool = False

    # Session capture
    capture_enabled: bool = True
    capture_mode: str = "key_moments"
    commit_threshold_turns: int = 8
    commit_threshold_chars: int = 16_000
    tool_result_max_chars: int = 250

    # Moment detection
    detection_model: str = "claude-sonnet-4-5"
    detection_max_tokens: int = 512
    detection_temperature: float = 0.0

    # Bypass
    bypass_session_patterns: list[str] = field(default_factory=list)
    compiled_bypass_patterns: list[re.Pattern[str]] = field(default_factory=list, repr=False)


class BibleConfigError(ValueError):
    pass


def resolve_config() -> BibleCCConfig:
    file_cfg = _load_yaml_config()
    return _build_config(file_cfg)


def _config_path() -> Path:
    return Path(os.environ.get("BIBLE_CC_CONFIG_PATH", Path.home() / ".bible-cc" / "config.yaml"))


def _load_yaml_config() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _build_config(file_cfg: dict) -> BibleCCConfig:
    bible = file_cfg.get("bible", {}) if isinstance(file_cfg.get("bible"), dict) else {}
    daemon = file_cfg.get("daemon", {}) if isinstance(file_cfg.get("daemon"), dict) else {}
    recall = file_cfg.get("recall", {}) if isinstance(file_cfg.get("recall"), dict) else {}
    capture = file_cfg.get("capture", {}) if isinstance(file_cfg.get("capture"), dict) else {}
    detection = file_cfg.get("detection", {}) if isinstance(file_cfg.get("detection"), dict) else {}
    bypass = file_cfg.get("bypass", {}) if isinstance(file_cfg.get("bypass"), dict) else {}

    base_url = os.environ.get("BIBLE_ATLAS_BASE_URL") or bible.get("base_url", "")
    if not base_url:
        raise BibleConfigError(
            "BIBLE_ATLAS_BASE_URL is required. Run 'bible-cc setup' or set the env var."
        )

    cfg = BibleCCConfig(
        base_url=base_url.rstrip("/"),
        token=os.environ.get("BIBLE_ATLAS_TOKEN") or bible.get("token"),
        timeout_ms=_int(bible, "timeout_ms", 1000, None, 30_000),
        default_kb_index=bible.get("default_kb_index", "kb_memory_main"),
        source_client=bible.get("source_client", "claude-code"),
        daemon_port=_int(daemon, "port", 1024, 65535, 9777),
        db_path=daemon.get("db_path", "~/.bible-cc/daemon.db"),
        enable_memory_recall=_bool(recall, "enable_memory", True),
        enable_knowledge_recall=_bool(recall, "enable_knowledge", False),
        knowledge_tags=_str_list(recall, "knowledge_tags"),
        recall_top_k=_int(recall, "top_k", 1, 50, 8),
        recall_min_score=_float(recall, "min_score", 0.0, 1.0, 0.35),
        injection_token_budget=_int(recall, "injection_token_budget", 128, None, 1200),
        force_injection=_bool(recall, "force_injection", False),
        capture_enabled=_bool(capture, "enabled", True),
        capture_mode=capture.get("mode", "key_moments"),
        commit_threshold_turns=_int(capture, "commit_threshold_turns", 1, None, 8),
        commit_threshold_chars=_int(capture, "commit_threshold_chars", 1000, None, 16_000),
        tool_result_max_chars=_int(capture, "tool_result_max_chars", 50, 2000, 250),
        detection_model=detection.get("model", "claude-sonnet-4-5"),
        detection_max_tokens=_int(detection, "max_tokens", 64, 4096, 512),
        detection_temperature=_float(detection, "temperature", 0.0, 2.0, 0.0),
        bypass_session_patterns=_str_list(bypass, "session_patterns"),
    )
    cfg.compiled_bypass_patterns = _compile_patterns(cfg.bypass_session_patterns)
    return cfg


def _bool(section: dict, key: str, fallback: bool) -> bool:
    val = section.get(key)
    return fallback if val is None else bool(val)


def _int(section: dict, key: str, lo: int, hi: int | None, fallback: int) -> int:
    val = section.get(key)
    if val is None:
        return fallback
    if not isinstance(val, int) or isinstance(val, bool):
        return fallback
    if val < lo:
        return fallback
    if hi is not None and val > hi:
        return fallback
    return val


def _float(section: dict, key: str, lo: float, hi: float, fallback: float) -> float:
    val = section.get(key)
    if val is None:
        return fallback
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        return fallback
    if val < lo or val > hi:
        return fallback
    return float(val)


def _str_list(section: dict, key: str) -> list[str]:
    val = section.get(key)
    if not isinstance(val, list):
        return []
    return [str(item).strip() for item in val if isinstance(item, str) and item.strip()]


def _compile_patterns(patterns: list[str]) -> list[re.Pattern]:
    compiled: list[re.Pattern] = []
    for p in patterns:
        try:
            compiled.append(re.compile(p))
        except re.error:
            pass
    return compiled
