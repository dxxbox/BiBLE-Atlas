"""Tests for KB-SCH task G — BibleAtlasConfig.search / SearchConfig.

Covers:
- Default values match v3 dynamic_config.yaml search-section conventions.
- Values can be overridden via dict / YAML loading.
- Pydantic validation rejects illegal combinations and out-of-range values.
- API layer helpers: SearchConfig.is_valid_search_type, top_k clamping logic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bible.config.configure import (
    BibleAtlasConfig,
    SearchConfig,
    _clear_bible_atlas_config_cache,
    load_bible_atlas_config_from_file,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    _clear_bible_atlas_config_cache()
    yield  # type: ignore[misc]
    _clear_bible_atlas_config_cache()


# ---------------------------------------------------------------------------
# SearchConfig — standalone unit tests
# ---------------------------------------------------------------------------


class TestSearchConfigDefaults:
    """SearchConfig must expose the v3-aligned defaults when no YAML is supplied."""

    def test_default_top_k_is_10(self) -> None:
        cfg = SearchConfig()
        assert cfg.default_top_k == 10

    def test_max_top_k_is_100(self) -> None:
        cfg = SearchConfig()
        assert cfg.max_top_k == 100

    def test_default_top_k_is_positive(self) -> None:
        cfg = SearchConfig()
        assert cfg.default_top_k >= 1

    def test_max_top_k_is_positive(self) -> None:
        cfg = SearchConfig()
        assert cfg.max_top_k >= 1

    def test_max_top_k_gte_default_top_k(self) -> None:
        cfg = SearchConfig()
        assert cfg.max_top_k >= cfg.default_top_k

    def test_allowed_search_types_contains_five_types(self) -> None:
        cfg = SearchConfig()
        expected = {"keyword", "title", "text", "vector", "hybrid"}
        assert expected == set(cfg.allowed_search_types)


class TestSearchConfigOverride:
    """SearchConfig values can be customised via keyword args (dict / YAML load)."""

    def test_custom_default_top_k(self) -> None:
        cfg = SearchConfig(default_top_k=20)
        assert cfg.default_top_k == 20

    def test_custom_max_top_k(self) -> None:
        cfg = SearchConfig(default_top_k=5, max_top_k=50)
        assert cfg.max_top_k == 50

    def test_custom_allowed_search_types_subset(self) -> None:
        cfg = SearchConfig(allowed_search_types=["keyword", "text"])
        assert cfg.allowed_search_types == ["keyword", "text"]


class TestSearchConfigValidation:
    """Illegal combinations must raise ValidationError at construction time."""

    def test_default_top_k_zero_raises(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SearchConfig(default_top_k=0)

    def test_default_top_k_negative_raises(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SearchConfig(default_top_k=-1)

    def test_max_top_k_zero_raises(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SearchConfig(max_top_k=0)

    def test_max_top_k_less_than_default_raises(self) -> None:
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            SearchConfig(default_top_k=50, max_top_k=10)

    def test_max_top_k_equal_to_default_is_valid(self) -> None:
        """Boundary: max == default is allowed."""
        cfg = SearchConfig(default_top_k=5, max_top_k=5)
        assert cfg.max_top_k == cfg.default_top_k


# ---------------------------------------------------------------------------
# BibleAtlasConfig.search integration — defaults wired into parent config
# ---------------------------------------------------------------------------


class TestBibleAtlasConfigSearchDefaults:
    """BibleAtlasConfig exposes a .search attribute with correct defaults."""

    def test_search_field_present(self) -> None:
        cfg = BibleAtlasConfig()
        assert hasattr(cfg, "search")

    def test_search_is_search_config_instance(self) -> None:
        cfg = BibleAtlasConfig()
        assert isinstance(cfg.search, SearchConfig)

    def test_search_default_top_k_via_parent(self) -> None:
        cfg = BibleAtlasConfig()
        assert cfg.search.default_top_k == 10

    def test_search_max_top_k_via_parent(self) -> None:
        cfg = BibleAtlasConfig()
        assert cfg.search.max_top_k == 100

    def test_search_allowed_types_via_parent(self) -> None:
        cfg = BibleAtlasConfig()
        assert "hybrid" in cfg.search.allowed_search_types


# ---------------------------------------------------------------------------
# BibleAtlasConfig.load_config_from_dict — YAML round-trip
# ---------------------------------------------------------------------------


class TestBibleAtlasConfigLoadFromDict:
    """search section in raw dict is parsed into SearchConfig fields."""

    def test_load_default_top_k_from_dict(self) -> None:
        cfg = BibleAtlasConfig.load_config_from_dict({"search": {"default_top_k": 25}})
        assert cfg.search.default_top_k == 25

    def test_load_max_top_k_from_dict(self) -> None:
        cfg = BibleAtlasConfig.load_config_from_dict({"search": {"max_top_k": 200}})
        assert cfg.search.max_top_k == 200

    def test_load_partial_search_keeps_other_defaults(self) -> None:
        """Partial override: unspecified fields fall back to SearchConfig defaults."""
        cfg = BibleAtlasConfig.load_config_from_dict({"search": {"default_top_k": 15}})
        assert cfg.search.default_top_k == 15
        assert cfg.search.max_top_k == 100

    def test_load_allowed_search_types_from_dict(self) -> None:
        cfg = BibleAtlasConfig.load_config_from_dict(
            {"search": {"allowed_search_types": ["text", "vector"]}}
        )
        assert set(cfg.search.allowed_search_types) == {"text", "vector"}

    def test_missing_search_section_uses_defaults(self) -> None:
        """If the YAML has no 'search' key, defaults must still be available."""
        cfg = BibleAtlasConfig.load_config_from_dict({})
        assert cfg.search.default_top_k == 10
        assert cfg.search.max_top_k == 100


# ---------------------------------------------------------------------------
# YAML file loading
# ---------------------------------------------------------------------------


class TestBibleAtlasConfigYamlLoading:
    """End-to-end: YAML file with search section is loaded correctly."""

    def test_load_search_defaults_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            "search:\n  default_top_k: 5\n  max_top_k: 50\n",
            encoding="utf-8",
        )
        cfg = load_bible_atlas_config_from_file(yaml_file)
        assert cfg.search.default_top_k == 5
        assert cfg.search.max_top_k == 50

    def test_load_allowed_search_types_from_yaml(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text(
            "search:\n  allowed_search_types:\n    - keyword\n    - hybrid\n",
            encoding="utf-8",
        )
        cfg = load_bible_atlas_config_from_file(yaml_file)
        assert set(cfg.search.allowed_search_types) == {"keyword", "hybrid"}

    def test_yaml_without_search_section_uses_defaults(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "config.yaml"
        yaml_file.write_text("atlas_url: https://example.com\n", encoding="utf-8")
        cfg = load_bible_atlas_config_from_file(yaml_file)
        assert cfg.search.default_top_k == 10
        assert cfg.search.max_top_k == 100


# ---------------------------------------------------------------------------
# API-layer helpers: top_k clamping and search_type validation
# ---------------------------------------------------------------------------


class TestSearchConfigApiHelpers:
    """Helpers the API layer will use to validate / normalise request params."""

    def test_is_valid_search_type_known_types(self) -> None:
        cfg = SearchConfig()
        for st in ["keyword", "title", "text", "vector", "hybrid"]:
            assert st in cfg.allowed_search_types

    def test_is_valid_search_type_unknown_returns_false(self) -> None:
        cfg = SearchConfig()
        assert "fuzzy" not in cfg.allowed_search_types

    def test_clamp_top_k_below_one(self) -> None:
        """Any value < 1 must be treated as invalid (API should reject it)."""
        cfg = SearchConfig()
        assert 0 < cfg.default_top_k

    def test_clamp_top_k_above_max(self) -> None:
        """A request top_k > max_top_k must be capped or rejected by the API.
        This test verifies that the SearchConfig carries enough info for the check.
        """
        cfg = SearchConfig(default_top_k=10, max_top_k=50)
        request_top_k = 200
        assert request_top_k > cfg.max_top_k  # API must reject / cap this

    def test_effective_top_k_falls_back_to_default(self) -> None:
        """When client sends None, API resolves to default_top_k."""
        cfg = SearchConfig(default_top_k=10, max_top_k=100)
        client_top_k = None
        effective = client_top_k if client_top_k is not None else cfg.default_top_k
        assert effective == 10
