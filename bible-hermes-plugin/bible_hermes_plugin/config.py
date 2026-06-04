"""BiBLE Hermes Plugin — configuration resolution.

Reads from environment variables (BIBLE_ATLAS_BASE_URL, BIBLE_ATLAS_TOKEN, …)
and from a Hermes config.yaml section:

    bible:
      base_url: "http://localhost:8080"
      token: "..."
      recall_top_k: 8
      # … all fields below

Environment variables take precedence over config.yaml values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import os
import re
from typing import Any

# ── data class ───────────────────────────────────────────────────────────────

@dataclass
class BibleHermesConfig:
    base_url: str
    token: str | None = None
    timeout_ms: int = 30_000
    context_engine_id: str = "bible-hermes-plugin"
    default_kb_index: str = "kb_memory_main"
    source_client: str = "hermes"
    enable_memory_recall: bool = True
    enable_skill_recall: bool = False
    enable_knowledge_recall: bool = False
    knowledge_tags: list[str] = field(default_factory=list)
    recall_top_k: int = 8
    recall_min_score: float = 0.35
    injection_token_budget: int = 1_200
    capture_enabled: bool = True
    capture_commit_threshold_turns: int = 8
    capture_commit_threshold_chars: int = 16_000
    force_injection: bool = False
    force_capture: bool = False
    bypass_session_patterns: list[str] = field(default_factory=list)
    compiled_bypass_patterns: list[re.Pattern[str]] = field(default_factory=list, repr=False)


class BibleConfigError(ValueError):
    code = "BIBLE_CONFIG_INVALID"


# ── resolver ────────────────────────────────────────────────────────────────

def resolve_config(hermes_cfg: Any = None) -> BibleHermesConfig:
    """Build a BibleHermesConfig from env vars + optional Hermes config dict.

    Environment variables take precedence. hermes_cfg may be a dict-like
    object from Hermes's config.yaml, typically the ``bible`` section.
    """
    section = _extract_section(hermes_cfg)

    base_url = (
        os.environ.get("BIBLE_ATLAS_BASE_URL", "").strip()
        or _str(section, "base_url", required=False)
        or ""
    )
    if not base_url:
        raise BibleConfigError(
            "BIBLE_ATLAS_BASE_URL is required (set the environment variable or "
            "add bible.base_url to config.yaml)."
        )
    base_url = base_url.rstrip("/")

    token = (
        os.environ.get("BIBLE_ATLAS_TOKEN", "").strip() or None
        or _str(section, "token", required=False)
        or None
    )

    cfg = BibleHermesConfig(
        base_url=base_url,
        token=token,
        timeout_ms=_int(section, "timeout_ms", 1_000, None, 30_000),
        context_engine_id=_str(section, "context_engine_id") or "bible-hermes-plugin",
        default_kb_index=_str(section, "default_kb_index") or "kb_memory_main",
        source_client=_str(section, "source_client") or "hermes",
        enable_memory_recall=_bool(section, "enable_memory_recall", True),
        enable_skill_recall=_bool(section, "enable_skill_recall", False),
        enable_knowledge_recall=_bool(section, "enable_knowledge_recall", False),
        knowledge_tags=_str_list(section, "knowledge_tags"),
        recall_top_k=_int(section, "recall_top_k", 1, 50, 8),
        recall_min_score=_float(section, "recall_min_score", 0.0, 1.0, 0.35),
        injection_token_budget=_int(section, "injection_token_budget", 128, None, 1_200),
        capture_enabled=_bool(section, "capture_enabled", True),
        capture_commit_threshold_turns=_int(section, "capture_commit_threshold_turns", 1, None, 8),
        capture_commit_threshold_chars=_int(section, "capture_commit_threshold_chars", 1_000, None, 16_000),
        force_injection=_bool(section, "force_injection", False),
        force_capture=_bool(section, "force_capture", False),
        bypass_session_patterns=_str_list(section, "bypass_session_patterns"),
    )
    cfg.compiled_bypass_patterns = _compile_bypass_patterns(cfg.bypass_session_patterns)
    return cfg


# ── helpers ──────────────────────────────────────────────────────────────────

def _extract_section(hermes_cfg: Any) -> dict:
    """Pull the 'bible' sub-section from the Hermes config object."""
    if not hermes_cfg:
        return {}
    if isinstance(hermes_cfg, dict):
        return hermes_cfg.get("bible", {}) or {}
    # Hermes may pass a config proxy; try attribute access too
    try:
        section = getattr(hermes_cfg, "bible", None)
        if isinstance(section, dict):
            return section
    except Exception:
        pass
    return {}


def _compile_bypass_patterns(patterns: list[str]) -> list[re.Pattern]:
    compiled: list[re.Pattern] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern))
        except re.error as exc:
            raise BibleConfigError(
                f'Invalid bypass_session_patterns regex "{pattern}": {exc}'
            ) from exc
    return compiled


def _str(section: dict, key: str, required: bool = False) -> str | None:
    value = section.get(key)
    if value is None:
        if required:
            raise BibleConfigError(f"{key} is required.")
        return None
    if not isinstance(value, str) or not value.strip():
        raise BibleConfigError(f"{key} must be a non-empty string.")
    return value.strip()


def _bool(section: dict, key: str, fallback: bool) -> bool:
    value = section.get(key)
    if value is None:
        return fallback
    if not isinstance(value, bool):
        raise BibleConfigError(f"{key} must be a boolean.")
    return value


def _int(section: dict, key: str, min_val: int, max_val: int | None, fallback: int) -> int:
    value = section.get(key)
    if value is None:
        return fallback
    if not isinstance(value, int) or isinstance(value, bool):
        raise BibleConfigError(f"{key} must be an integer.")
    if value < min_val:
        raise BibleConfigError(f"{key} must be >= {min_val}.")
    if max_val is not None and value > max_val:
        raise BibleConfigError(f"{key} must be <= {max_val}.")
    return value


def _float(section: dict, key: str, min_val: float, max_val: float, fallback: float) -> float:
    value = section.get(key)
    if value is None:
        return fallback
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise BibleConfigError(f"{key} must be a number.")
    if value < min_val or value > max_val:
        raise BibleConfigError(f"{key} must be between {min_val} and {max_val}.")
    return float(value)


def _str_list(section: dict, key: str) -> list[str]:
    value = section.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise BibleConfigError(f"{key} must be a list of strings.")
    return [item.strip() for item in value if item.strip()]
