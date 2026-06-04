"""Tests for config resolution and validation."""

from __future__ import annotations

import os
import re

import pytest

from bible_hermes_plugin.config import (
    BibleConfigError,
    BibleHermesConfig,
    resolve_config,
)


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("BIBLE_ATLAS_BASE_URL", raising=False)
    monkeypatch.delenv("BIBLE_ATLAS_TOKEN", raising=False)


def cfg(extra: dict | None = None) -> dict:
    base = {"bible": {"base_url": "http://localhost:9999"}}
    if extra:
        base["bible"].update(extra)
    return base


# ── resolve_config: happy path ────────────────────────────────────────────────

def test_resolve_from_env(monkeypatch):
    monkeypatch.setenv("BIBLE_ATLAS_BASE_URL", "http://env-server:8080/")
    c = resolve_config()
    assert c.base_url == "http://env-server:8080"  # trailing slash stripped
    assert c.token is None


def test_resolve_from_yaml():
    c = resolve_config(cfg())
    assert c.base_url == "http://localhost:9999"


def test_env_takes_precedence_over_yaml(monkeypatch):
    monkeypatch.setenv("BIBLE_ATLAS_BASE_URL", "http://from-env")
    c = resolve_config(cfg({"base_url": "http://from-yaml"}))
    assert c.base_url == "http://from-env"


def test_token_from_env(monkeypatch):
    monkeypatch.setenv("BIBLE_ATLAS_BASE_URL", "http://x")
    monkeypatch.setenv("BIBLE_ATLAS_TOKEN", "secret")
    c = resolve_config()
    assert c.token == "secret"


def test_token_from_yaml():
    c = resolve_config(cfg({"token": "yaml-tok"}))
    assert c.token == "yaml-tok"


def test_defaults():
    c = resolve_config(cfg())
    assert c.timeout_ms == 30_000
    assert c.context_engine_id == "bible-hermes-plugin"
    assert c.default_kb_index == "kb_memory_main"
    assert c.source_client == "hermes"
    assert c.enable_memory_recall is True
    assert c.enable_skill_recall is False
    assert c.enable_knowledge_recall is False
    assert c.recall_top_k == 8
    assert c.recall_min_score == pytest.approx(0.35)
    assert c.injection_token_budget == 1_200
    assert c.capture_enabled is True
    assert c.capture_commit_threshold_turns == 8
    assert c.capture_commit_threshold_chars == 16_000
    assert c.bypass_session_patterns == []
    assert c.compiled_bypass_patterns == []


def test_yaml_overrides():
    c = resolve_config(cfg({
        "recall_top_k": 12,
        "recall_min_score": 0.5,
        "enable_skill_recall": True,
        "knowledge_tags": ["arch", "ops"],
        "bypass_session_patterns": [r"^test-"],
    }))
    assert c.recall_top_k == 12
    assert c.recall_min_score == pytest.approx(0.5)
    assert c.enable_skill_recall is True
    assert c.knowledge_tags == ["arch", "ops"]
    assert len(c.compiled_bypass_patterns) == 1


def test_bypass_patterns_compiled():
    c = resolve_config(cfg({"bypass_session_patterns": [r"scratch-\d+", r"test"]}))
    assert len(c.compiled_bypass_patterns) == 2
    assert all(isinstance(p, re.Pattern) for p in c.compiled_bypass_patterns)


# ── resolve_config: error cases ───────────────────────────────────────────────

def test_missing_base_url_raises():
    with pytest.raises(BibleConfigError, match="BIBLE_ATLAS_BASE_URL is required"):
        resolve_config()


def test_invalid_recall_top_k_type():
    with pytest.raises(BibleConfigError, match="recall_top_k must be an integer"):
        resolve_config(cfg({"recall_top_k": "eight"}))


def test_recall_top_k_out_of_range():
    with pytest.raises(BibleConfigError, match="must be <= 50"):
        resolve_config(cfg({"recall_top_k": 99}))


def test_recall_min_score_out_of_range():
    with pytest.raises(BibleConfigError, match="must be between"):
        resolve_config(cfg({"recall_min_score": 1.5}))


def test_invalid_bool():
    with pytest.raises(BibleConfigError, match="must be a boolean"):
        resolve_config(cfg({"capture_enabled": "yes"}))


def test_invalid_bypass_pattern():
    with pytest.raises(BibleConfigError, match="Invalid bypass_session_patterns regex"):
        resolve_config(cfg({"bypass_session_patterns": [r"[invalid"]}))


def test_knowledge_tags_not_list():
    with pytest.raises(BibleConfigError, match="must be a list of strings"):
        resolve_config(cfg({"knowledge_tags": "arch"}))


def test_nested_bible_section():
    c = resolve_config({"bible": {"base_url": "http://nested"}})
    assert c.base_url == "http://nested"


def test_flat_dict_ignored():
    with pytest.raises(BibleConfigError):
        resolve_config({"base_url": "http://flat"})  # missing 'bible' key
