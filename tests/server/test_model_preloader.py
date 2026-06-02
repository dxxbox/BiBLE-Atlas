"""
向量模型预加载器测试

覆盖范围：
1. _resolve_preload_model_ref  —— 字符串 / 字典 / 对象 / 无效输入四种分支
2. _get_model_list             —— VectorModelEntry 列表 / 空列表 / 缺少属性 / 混合类型
3. preload_all_models          —— 全成功 / 部分失败 / 全失败 / 空列表
4. preload_all_models_async    —— 后台线程启动并完成
5. 集成：从 YAML 加载配置后预加载路径端到端
"""

from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call

import pytest

from bible.config.configure import BibleAtlasConfig, VectorConfig, VectorModelEntry
from bible.infrastructure.vector.model_preloader import VectorModelPreloader


# ---------------------------------------------------------------------------
# Helpers / factories
# ---------------------------------------------------------------------------

def _make_preloader(models: list[Any] | None = None, *, preload_on_startup: bool = True) -> tuple[VectorModelPreloader, MagicMock]:
    """Return a (preloader, mock_vector_tool) pair backed by a minimal config."""
    vector_cfg = VectorConfig(
        preload_on_startup=preload_on_startup,
        available_models=models if models is not None else [],
    )
    config = SimpleNamespace(vector=vector_cfg)
    mock_tool = MagicMock()
    mock_tool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
    return VectorModelPreloader(config=config, vector_tool=mock_tool), mock_tool


def _make_entry(id_: str = "bge-large", name: str = "BAAI/bge-large-zh-v1.5") -> VectorModelEntry:
    return VectorModelEntry(id=id_, name=name, dims=1024, params="326M")


# ---------------------------------------------------------------------------
# 1. _resolve_preload_model_ref
# ---------------------------------------------------------------------------

class TestResolvePreloadModelRef:
    def test_plain_string_returns_itself(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref("BAAI/bge-large-zh-v1.5") == "BAAI/bge-large-zh-v1.5"

    def test_dict_with_name_returns_name(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref({"id": "bge-large", "name": "BAAI/bge-large-zh-v1.5"}) == "BAAI/bge-large-zh-v1.5"

    def test_object_with_name_attr_returns_name(self) -> None:
        entry = _make_entry()
        assert VectorModelPreloader._resolve_preload_model_ref(entry) == "BAAI/bge-large-zh-v1.5"

    def test_dict_missing_name_returns_none(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref({"id": "bge-large"}) is None

    def test_dict_with_empty_name_returns_none(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref({"name": ""}) is None

    def test_dict_with_none_name_returns_none(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref({"name": None}) is None

    def test_object_without_name_attr_returns_none(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref(SimpleNamespace(id="bge-large")) is None

    def test_object_with_empty_name_attr_returns_none(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref(SimpleNamespace(name="")) is None

    def test_integer_returns_none(self) -> None:
        assert VectorModelPreloader._resolve_preload_model_ref(42) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. _get_model_list
# ---------------------------------------------------------------------------

class TestGetModelList:
    def test_returns_hf_names_from_vector_model_entries(self) -> None:
        entries = [
            _make_entry("mini", "paraphrase-multilingual-MiniLM-L12-v2"),
            _make_entry("bge-large", "BAAI/bge-large-zh-v1.5"),
        ]
        preloader, _ = _make_preloader(entries)
        assert preloader._get_model_list() == [
            "paraphrase-multilingual-MiniLM-L12-v2",
            "BAAI/bge-large-zh-v1.5",
        ]

    def test_empty_available_models_returns_empty_list(self) -> None:
        preloader, _ = _make_preloader([])
        assert preloader._get_model_list() == []

    def test_no_vector_attr_on_config_returns_empty_list(self) -> None:
        config = SimpleNamespace()  # no .vector
        preloader = VectorModelPreloader(config=config, vector_tool=MagicMock())
        assert preloader._get_model_list() == []

    def test_vector_available_models_is_none_returns_empty_list(self) -> None:
        config = SimpleNamespace(vector=SimpleNamespace(available_models=None))
        preloader = VectorModelPreloader(config=config, vector_tool=MagicMock())
        assert preloader._get_model_list() == []

    def test_legacy_string_list_returned_unchanged(self) -> None:
        """Backwards-compat: available_models may be a plain list of strings."""
        config = SimpleNamespace(
            vector=SimpleNamespace(available_models=["BAAI/bge-m3", "BAAI/bge-large-zh-v1.5"])
        )
        preloader = VectorModelPreloader(config=config, vector_tool=MagicMock())
        assert preloader._get_model_list() == ["BAAI/bge-m3", "BAAI/bge-large-zh-v1.5"]

    def test_mixed_list_skips_invalid_items(self) -> None:
        """Items without a resolvable name are silently dropped."""
        config = SimpleNamespace(
            vector=SimpleNamespace(available_models=[
                {"id": "bge-large", "name": "BAAI/bge-large-zh-v1.5"},
                {"id": "broken"},           # missing name → skipped
                "paraphrase-multilingual-MiniLM-L12-v2",
                {"name": ""},               # empty name → skipped
            ])
        )
        preloader = VectorModelPreloader(config=config, vector_tool=MagicMock())
        assert preloader._get_model_list() == [
            "BAAI/bge-large-zh-v1.5",
            "paraphrase-multilingual-MiniLM-L12-v2",
        ]

    def test_all_six_models_from_full_yaml_config(self) -> None:
        """Matches the six entries defined in bible-atlas.yaml."""
        entries = [
            _make_entry("mini", "paraphrase-multilingual-MiniLM-L12-v2"),
            _make_entry("mpnet", "paraphrase-multilingual-mpnet-base-v2"),
            _make_entry("bge-base", "BAAI/bge-base-zh-v1.5"),
            _make_entry("bge-large", "BAAI/bge-large-zh-v1.5"),
            _make_entry("bge-m3", "BAAI/bge-m3"),
            _make_entry("e5-large", "intfloat/multilingual-e5-large"),
        ]
        preloader, _ = _make_preloader(entries)
        names = preloader._get_model_list()
        assert len(names) == 6
        assert "BAAI/bge-large-zh-v1.5" in names
        assert "BAAI/bge-m3" in names


# ---------------------------------------------------------------------------
# 3. preload_all_models
# ---------------------------------------------------------------------------

class TestPreloadAllModels:
    def test_no_models_returns_zero_success_empty_failed(self) -> None:
        preloader, mock_tool = _make_preloader([])
        count, failed = preloader.preload_all_models()
        assert count == 0
        assert failed == []
        mock_tool.ensure_model_ready.assert_not_called()

    def test_all_succeed_returns_correct_count(self) -> None:
        entries = [_make_entry("mini", "mini-model"), _make_entry("bge-large", "bge-large-model")]
        preloader, mock_tool = _make_preloader(entries)
        mock_tool.ensure_model_ready.return_value = {"status": "ready", "source": "cache"}

        count, failed = preloader.preload_all_models()

        assert count == 2
        assert failed == []
        mock_tool.ensure_model_ready.assert_has_calls([call("mini-model"), call("bge-large-model")])

    def test_all_fail_returns_zero_success_with_error_messages(self) -> None:
        entries = [_make_entry("a", "model-a"), _make_entry("b", "model-b")]
        preloader, mock_tool = _make_preloader(entries)
        mock_tool.ensure_model_ready.side_effect = RuntimeError("network error")

        count, failed = preloader.preload_all_models()

        assert count == 0
        assert len(failed) == 2
        assert failed[0] == ("model-a", "network error")
        assert failed[1] == ("model-b", "network error")

    def test_partial_failure_counts_correctly(self) -> None:
        entries = [
            _make_entry("ok", "model-ok"),
            _make_entry("bad", "model-bad"),
            _make_entry("ok2", "model-ok2"),
        ]
        preloader, mock_tool = _make_preloader(entries)

        def _side_effect(name: str):
            if name == "model-bad":
                raise ValueError("bad model")
            return {"status": "ready", "source": "local"}

        mock_tool.ensure_model_ready.side_effect = _side_effect

        count, failed = preloader.preload_all_models()

        assert count == 2
        assert len(failed) == 1
        assert failed[0][0] == "model-bad"
        assert "bad model" in failed[0][1]

    def test_failed_list_preserves_error_message_as_string(self) -> None:
        preloader, mock_tool = _make_preloader([_make_entry("x", "model-x")])
        mock_tool.ensure_model_ready.side_effect = OSError("disk full")

        _, failed = preloader.preload_all_models()

        assert failed[0][1] == "disk full"

    def test_each_model_called_exactly_once(self) -> None:
        entries = [_make_entry("a", "m-a"), _make_entry("b", "m-b"), _make_entry("c", "m-c")]
        preloader, mock_tool = _make_preloader(entries)

        preloader.preload_all_models()

        assert mock_tool.ensure_model_ready.call_count == 3

    def test_source_info_from_ensure_model_ready_is_logged(self) -> None:
        """Checks the 'source' key is consumed without raising KeyError."""
        preloader, mock_tool = _make_preloader([_make_entry("m", "model-m")])
        mock_tool.ensure_model_ready.return_value = {"status": "ready", "source": "download"}

        count, failed = preloader.preload_all_models()

        assert count == 1
        assert failed == []

    def test_missing_source_key_does_not_raise(self) -> None:
        """ensure_model_ready returns dict without 'source' → fallback to '?'."""
        preloader, mock_tool = _make_preloader([_make_entry("m", "model-m")])
        mock_tool.ensure_model_ready.return_value = {"status": "ready"}

        count, failed = preloader.preload_all_models()

        assert count == 1
        assert failed == []


# ---------------------------------------------------------------------------
# 4. preload_all_models_async
# ---------------------------------------------------------------------------

class TestPreloadAllModelsAsync:
    def test_returns_daemon_thread(self) -> None:
        preloader, _ = _make_preloader([])
        thread = preloader.preload_all_models_async()
        assert isinstance(thread, threading.Thread)
        assert thread.daemon is True

    def test_thread_has_expected_name(self) -> None:
        preloader, _ = _make_preloader([])
        thread = preloader.preload_all_models_async()
        assert thread.name == "VectorModelPreloader"

    def test_async_thread_completes_and_calls_ensure_model_ready(self) -> None:
        entries = [_make_entry("m1", "model-1"), _make_entry("m2", "model-2")]
        preloader, mock_tool = _make_preloader(entries)

        thread = preloader.preload_all_models_async()
        thread.join(timeout=5)

        assert not thread.is_alive(), "preload thread should finish within 5 s"
        assert mock_tool.ensure_model_ready.call_count == 2

    def test_async_thread_does_not_propagate_exception(self) -> None:
        """Background errors must be swallowed so the HTTP server keeps running."""
        preloader, mock_tool = _make_preloader([_make_entry("bad", "model-bad")])
        mock_tool.ensure_model_ready.side_effect = RuntimeError("boom")

        thread = preloader.preload_all_models_async()
        thread.join(timeout=5)

        assert not thread.is_alive()


# ---------------------------------------------------------------------------
# 5. Integration: load from YAML → preloader resolves correct HF names
# ---------------------------------------------------------------------------

_VECTOR_YAML = """\
vector:
  preload_on_startup: true
  batch_size: 16
  available_models:
    - id: 'bge-large'
      name: 'BAAI/bge-large-zh-v1.5'
      description: '中文优化，高精度'
      params: '326M'
      dims: 1024
      languages: ['中文', '英文']
    - id: 'bge-m3'
      name: 'BAAI/bge-m3'
      description: '多语言，支持长文本'
      params: '568M'
      dims: 1024
      languages: ['100+ 语言']
"""


class TestIntegrationYamlToPreloader:
    def test_yaml_config_preloader_extracts_hf_names(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(_VECTOR_YAML, encoding="utf-8")

        from bible.config.configure import load_bible_atlas_config_from_file
        config = load_bible_atlas_config_from_file(cfg_file)

        assert config.vector.preload_on_startup is True
        assert config.vector.batch_size == 16

        mock_tool = MagicMock()
        mock_tool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
        preloader = VectorModelPreloader(config=config, vector_tool=mock_tool)

        names = preloader._get_model_list()
        assert names == ["BAAI/bge-large-zh-v1.5", "BAAI/bge-m3"]

    def test_yaml_config_preload_all_models_calls_ensure_with_hf_names(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(_VECTOR_YAML, encoding="utf-8")

        from bible.config.configure import load_bible_atlas_config_from_file
        config = load_bible_atlas_config_from_file(cfg_file)

        mock_tool = MagicMock()
        mock_tool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
        preloader = VectorModelPreloader(config=config, vector_tool=mock_tool)

        count, failed = preloader.preload_all_models()

        assert count == 2
        assert failed == []
        mock_tool.ensure_model_ready.assert_any_call("BAAI/bge-large-zh-v1.5")
        mock_tool.ensure_model_ready.assert_any_call("BAAI/bge-m3")

    def test_preload_on_startup_false_does_not_disable_manual_call(self, tmp_path: Path) -> None:
        """preload_on_startup 只控制 main.py 触发，手动调用 preload_all_models 仍可运行。"""
        yaml_text = _VECTOR_YAML.replace("preload_on_startup: true", "preload_on_startup: false")
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(yaml_text, encoding="utf-8")

        from bible.config.configure import load_bible_atlas_config_from_file
        config = load_bible_atlas_config_from_file(cfg_file)
        assert config.vector.preload_on_startup is False

        mock_tool = MagicMock()
        mock_tool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
        preloader = VectorModelPreloader(config=config, vector_tool=mock_tool)

        count, failed = preloader.preload_all_models()
        assert count == 2

    def test_no_vector_section_in_yaml_defaults_to_empty_preload(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("atlas_url: https://example.com\n", encoding="utf-8")

        from bible.config.configure import load_bible_atlas_config_from_file
        config = load_bible_atlas_config_from_file(cfg_file)

        assert config.vector.available_models == []
        assert config.vector.preload_on_startup is False

        preloader = VectorModelPreloader(config=config, vector_tool=MagicMock())
        count, failed = preloader.preload_all_models()
        assert count == 0
        assert failed == []


# ---------------------------------------------------------------------------
# Rerank model preloading — _get_rerank_model_list + combined preload_all_models
# ---------------------------------------------------------------------------

_RERANK_YAML = """\
rerank:
  preload_on_startup: true
  available_models:
    - id: 'bge-reranker-base'
      name: 'BAAI/bge-reranker-base'
      description: '中英文轻量 reranker'
      params: '278M'
    - id: 'bge-reranker-large'
      name: 'BAAI/bge-reranker-large'
      params: '560M'
"""


def _make_rerank_preloader(
    rerank_models: list[Any] | None = None,
    vector_models: list[Any] | None = None,
) -> tuple[VectorModelPreloader, MagicMock, MagicMock]:
    """Return (preloader, mock_vector_tool, mock_rerank_tool)."""
    from types import SimpleNamespace
    vector_cfg = VectorConfig(available_models=vector_models or [])
    from bible.config.configure import RerankConfig
    rerank_raw = rerank_models if rerank_models is not None else []
    rerank_cfg = RerankConfig(available_models=rerank_raw)
    config = SimpleNamespace(vector=vector_cfg, rerank=rerank_cfg)
    mock_vtool = MagicMock()
    mock_vtool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
    mock_rtool = MagicMock()
    mock_rtool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
    preloader = VectorModelPreloader(
        config=config,
        vector_tool=mock_vtool,
        rerank_tool=mock_rtool,
    )
    return preloader, mock_vtool, mock_rtool


class TestGetRerankModelList:
    def test_returns_hf_names_from_rerank_model_entries(self) -> None:
        from bible.config.configure import RerankModelEntry
        entries = [
            RerankModelEntry(id="base", name="BAAI/bge-reranker-base"),
            RerankModelEntry(id="large", name="BAAI/bge-reranker-large"),
        ]
        preloader, _, _ = _make_rerank_preloader(rerank_models=entries)
        assert preloader._get_rerank_model_list() == [
            "BAAI/bge-reranker-base",
            "BAAI/bge-reranker-large",
        ]

    def test_empty_available_models_returns_empty_list(self) -> None:
        preloader, _, _ = _make_rerank_preloader(rerank_models=[])
        assert preloader._get_rerank_model_list() == []

    def test_no_rerank_attr_on_config_returns_empty_list(self) -> None:
        from types import SimpleNamespace
        config = SimpleNamespace(vector=VectorConfig())  # no .rerank
        preloader = VectorModelPreloader(config=config, rerank_tool=MagicMock())
        assert preloader._get_rerank_model_list() == []

    def test_rerank_available_models_is_none_returns_empty_list(self) -> None:
        from types import SimpleNamespace
        config = SimpleNamespace(
            vector=VectorConfig(),
            rerank=SimpleNamespace(available_models=None),
        )
        preloader = VectorModelPreloader(config=config, rerank_tool=MagicMock())
        assert preloader._get_rerank_model_list() == []


class TestPreloadAllModelsWithRerank:
    def test_rerank_models_are_preloaded_via_rerank_tool(self) -> None:
        from bible.config.configure import RerankModelEntry
        entries = [
            RerankModelEntry(id="base", name="BAAI/bge-reranker-base"),
            RerankModelEntry(id="large", name="BAAI/bge-reranker-large"),
        ]
        preloader, _, mock_rtool = _make_rerank_preloader(rerank_models=entries)
        count, failed = preloader.preload_all_models()
        assert count == 2  # 0 vector + 2 rerank
        assert failed == []
        mock_rtool.ensure_model_ready.assert_any_call("BAAI/bge-reranker-base")
        mock_rtool.ensure_model_ready.assert_any_call("BAAI/bge-reranker-large")

    def test_vector_tool_not_called_when_no_vector_models(self) -> None:
        from bible.config.configure import RerankModelEntry
        preloader, mock_vtool, _ = _make_rerank_preloader(
            rerank_models=[RerankModelEntry(id="r", name="model/r")],
            vector_models=[],
        )
        preloader.preload_all_models()
        mock_vtool.ensure_model_ready.assert_not_called()

    def test_rerank_tool_not_called_when_no_rerank_models(self) -> None:
        preloader, _, mock_rtool = _make_rerank_preloader(
            rerank_models=[],
            vector_models=[_make_entry("m", "some-model")],
        )
        preloader.preload_all_models()
        mock_rtool.ensure_model_ready.assert_not_called()

    def test_combined_vector_and_rerank_counts_aggregated(self) -> None:
        from bible.config.configure import RerankModelEntry
        preloader, _, _ = _make_rerank_preloader(
            vector_models=[_make_entry("v1", "vec-model-1"), _make_entry("v2", "vec-model-2")],
            rerank_models=[RerankModelEntry(id="r1", name="rerank-model-1")],
        )
        count, failed = preloader.preload_all_models()
        assert count == 3  # 2 vector + 1 rerank
        assert failed == []

    def test_rerank_failure_counted_independently_of_vector(self) -> None:
        from bible.config.configure import RerankModelEntry
        from types import SimpleNamespace
        from bible.config.configure import RerankConfig

        vector_cfg = VectorConfig(available_models=[_make_entry("v", "vec-ok")])
        rerank_cfg = RerankConfig(available_models=[RerankModelEntry(id="r", name="rerank-fail")])
        config = SimpleNamespace(vector=vector_cfg, rerank=rerank_cfg)

        mock_vtool = MagicMock()
        mock_vtool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
        mock_rtool = MagicMock()
        mock_rtool.ensure_model_ready.side_effect = RuntimeError("load error")

        preloader = VectorModelPreloader(config=config, vector_tool=mock_vtool, rerank_tool=mock_rtool)
        count, failed = preloader.preload_all_models()

        assert count == 1          # vector succeeded
        assert len(failed) == 1    # rerank failed
        assert failed[0][0] == "rerank-fail"

    def test_no_tools_provided_returns_zero_and_empty(self) -> None:
        from types import SimpleNamespace
        config = SimpleNamespace(
            vector=VectorConfig(available_models=[_make_entry("v", "vec")]),
            rerank=SimpleNamespace(available_models=[]),
        )
        preloader = VectorModelPreloader(config=config)  # no tools
        count, failed = preloader.preload_all_models()
        assert count == 0
        assert failed == []

    def test_yaml_config_rerank_preload_end_to_end(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(_RERANK_YAML, encoding="utf-8")

        from bible.config.configure import load_bible_atlas_config_from_file
        config = load_bible_atlas_config_from_file(cfg_file)

        assert config.rerank.preload_on_startup is True
        assert len(config.rerank.available_models) == 2

        mock_rtool = MagicMock()
        mock_rtool.ensure_model_ready.return_value = {"status": "ready", "source": "local"}
        preloader = VectorModelPreloader(config=config, rerank_tool=mock_rtool)

        count, failed = preloader.preload_all_models()
        assert count == 2
        assert failed == []
        mock_rtool.ensure_model_ready.assert_any_call("BAAI/bge-reranker-base")
        mock_rtool.ensure_model_ready.assert_any_call("BAAI/bge-reranker-large")
