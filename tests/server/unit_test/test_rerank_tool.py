"""
Tests for:
  - bible.infrastructure.vector._model_utils  (get_local_model_path, download_lock_path)
  - bible.infrastructure.vector.rerank_tool   (RerankTool)

Coverage:
  1. get_local_model_path — present / absent / incomplete snapshot / custom required_metadata
  2. download_lock_path   — path structure + directory creation
  3. RerankTool.ensure_model_ready — cache hit / local load / download path / fallback
  4. RerankTool.rerank             — normal / empty / model-None fallback / error
  5. RerankTool.score              — single-pair convenience wrapper
  6. RerankTool._load_model        — sentence-transformers missing / load error
"""
from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bible.infrastructure.vector._model_utils import (
    download_lock_path,
    get_local_model_path,
    resolve_hf_cache_dir,
)
from bible.infrastructure.vector.rerank_tool import RerankTool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_snapshot(root: Path, model_slug: str, with_modules_json: bool = False) -> Path:
    """Create a minimal HF snapshot directory structure under *root*."""
    snapshot_dir = root / "hub" / f"models--{model_slug}" / "snapshots" / "abc123"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "config.json").write_text("{}")
    (snapshot_dir / "model.safetensors").write_text("weights")
    if with_modules_json:
        (snapshot_dir / "modules.json").write_text("{}")
    return snapshot_dir


def _fresh_rerank_tool(tmp_path: Path) -> RerankTool:
    """Return a RerankTool whose cache is clear (avoids cross-test contamination)."""
    RerankTool._model_cache.clear()
    return RerankTool(workspace_dir=str(tmp_path), hf_cache_dir=str(tmp_path))


# ===========================================================================
# 1. get_local_model_path
# ===========================================================================

class TestGetLocalModelPath:
    def test_returns_none_when_hub_dir_absent(self, tmp_path: Path) -> None:
        assert get_local_model_path("BAAI/bge-reranker-base", str(tmp_path)) is None

    def test_returns_none_when_no_snapshots(self, tmp_path: Path) -> None:
        snapshots = tmp_path / "hub" / "models--BAAI--bge-reranker-base" / "snapshots"
        snapshots.mkdir(parents=True)
        assert get_local_model_path("BAAI/bge-reranker-base", str(tmp_path)) is None

    def test_returns_none_when_snapshot_missing_weights(self, tmp_path: Path) -> None:
        snap = tmp_path / "hub" / "models--BAAI--bge-reranker-base" / "snapshots" / "abc"
        snap.mkdir(parents=True)
        (snap / "config.json").write_text("{}")
        # no weights file
        assert get_local_model_path("BAAI/bge-reranker-base", str(tmp_path)) is None

    def test_reranker_valid_snapshot_without_modules_json(self, tmp_path: Path) -> None:
        """Cross-encoder models don't have modules.json; required_metadata=["config.json"] should pass."""
        _make_valid_snapshot(tmp_path, "BAAI--bge-reranker-base", with_modules_json=False)
        path = get_local_model_path(
            "BAAI/bge-reranker-base",
            str(tmp_path),
            required_metadata=["config.json"],
        )
        assert path is not None
        assert "abc123" in path

    def test_embedding_model_requires_modules_json_by_default(self, tmp_path: Path) -> None:
        """Default required_metadata includes modules.json; snapshot without it is invalid."""
        _make_valid_snapshot(tmp_path, "BAAI--bge-base-zh-v1.5", with_modules_json=False)
        assert get_local_model_path("BAAI/bge-base-zh-v1.5", str(tmp_path)) is None

    def test_embedding_model_valid_when_modules_json_present(self, tmp_path: Path) -> None:
        _make_valid_snapshot(tmp_path, "BAAI--bge-base-zh-v1.5", with_modules_json=True)
        path = get_local_model_path("BAAI/bge-base-zh-v1.5", str(tmp_path))
        assert path is not None

    def test_returns_latest_snapshot_by_mtime(self, tmp_path: Path) -> None:
        """When multiple snapshots exist the most recently modified one is returned."""
        import os
        import time

        hub = tmp_path / "hub" / "models--BAAI--bge-reranker-base" / "snapshots"
        for name in ("snap_old", "snap_new"):
            d = hub / name
            d.mkdir(parents=True)
            (d / "config.json").write_text("{}")
            (d / "model.safetensors").write_text("w")

        # Explicitly assign distinct mtimes (1 second apart) so the comparison
        # is filesystem-resolution-independent.
        old_snap = hub / "snap_old"
        new_snap = hub / "snap_new"
        old_time = time.time() - 10
        new_time = time.time()
        os.utime(old_snap, (old_time, old_time))
        os.utime(new_snap, (new_time, new_time))

        path = get_local_model_path(
            "BAAI/bge-reranker-base",
            str(tmp_path),
            required_metadata=["config.json"],
        )
        assert path is not None
        assert "snap_new" in path

    def test_bare_model_name_uses_sentence_transformers_namespace(self, tmp_path: Path) -> None:
        """Names without '/' are prefixed with sentence-transformers."""
        slug = "sentence-transformers--paraphrase-multilingual-MiniLM-L12-v2"
        _make_valid_snapshot(tmp_path, slug, with_modules_json=True)
        path = get_local_model_path(
            "paraphrase-multilingual-MiniLM-L12-v2",
            str(tmp_path),
        )
        assert path is not None


# ===========================================================================
# 2. download_lock_path
# ===========================================================================

class TestDownloadLockPath:
    def test_creates_locks_directory(self, tmp_path: Path) -> None:
        path = download_lock_path("BAAI/bge-reranker-base", str(tmp_path))
        locks_dir = Path(path).parent
        assert locks_dir.exists()

    def test_path_ends_with_lock_extension(self, tmp_path: Path) -> None:
        path = download_lock_path("BAAI/bge-reranker-base", str(tmp_path))
        assert path.endswith(".lock")

    def test_slash_replaced_with_double_dash(self, tmp_path: Path) -> None:
        path = download_lock_path("BAAI/bge-reranker-base", str(tmp_path))
        assert "BAAI--bge-reranker-base" in path
        assert "/" not in Path(path).name

    def test_different_models_produce_different_paths(self, tmp_path: Path) -> None:
        p1 = download_lock_path("BAAI/bge-reranker-base", str(tmp_path))
        p2 = download_lock_path("BAAI/bge-reranker-large", str(tmp_path))
        assert p1 != p2

    def test_idempotent_when_dir_already_exists(self, tmp_path: Path) -> None:
        download_lock_path("model/a", str(tmp_path))
        path = download_lock_path("model/a", str(tmp_path))
        assert path is not None


class TestResolveHfCacheDir:
    def test_returns_absolute_path_and_creates_directory(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        path = resolve_hf_cache_dir("workspace", "relative-cache")
        assert Path(path).is_absolute()
        assert Path(path).exists()


# ===========================================================================
# 3. RerankTool.ensure_model_ready
# ===========================================================================

class TestRerankToolEnsureModelReady:
    def setup_method(self) -> None:
        RerankTool._model_cache.clear()

    def test_returns_ready_cache_on_second_call(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        sentinel = MagicMock()
        RerankTool._model_cache["mymodel"] = sentinel

        result = tool.ensure_model_ready("mymodel")

        assert result["status"] == "ready"
        assert result["source"] == "cache"

    def test_loads_from_local_when_snapshot_exists(self, tmp_path: Path) -> None:
        _make_valid_snapshot(tmp_path, "BAAI--bge-reranker-base", with_modules_json=False)
        tool = _fresh_rerank_tool(tmp_path)

        with patch.object(tool, "_load_model", return_value={"model_name": "BAAI/bge-reranker-base", "status": "ready", "source": "local"}) as mock_load:
            result = tool.ensure_model_ready("BAAI/bge-reranker-base")

        mock_load.assert_called_once()
        assert mock_load.call_args[1]["source"] == "local" or mock_load.call_args[0][2] == "local"
        assert result["source"] == "local"

    def test_downloads_when_no_local_snapshot(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)

        with patch.object(tool, "_download_from_huggingface", return_value={"model_name": "x", "status": "ready", "source": "download"}) as mock_dl:
            result = tool.ensure_model_ready("x")

        mock_dl.assert_called_once_with("x")
        assert result["source"] == "download"


# ===========================================================================
# 4. RerankTool.rerank
# ===========================================================================

class TestRerankToolRerank:
    def setup_method(self) -> None:
        RerankTool._model_cache.clear()

    def test_empty_passages_returns_empty_list(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        assert tool.rerank("query", [], "anymodel") == []

    def test_returns_zeros_when_model_is_none_fallback(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        RerankTool._model_cache["fallback-model"] = None
        scores = tool.rerank("query", ["p1", "p2"], "fallback-model")
        assert scores == [0.0, 0.0]

    def test_returns_scores_from_cross_encoder(self, tmp_path: Path) -> None:
        import numpy as np

        tool = _fresh_rerank_tool(tmp_path)
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.9, 0.3, 0.6])
        RerankTool._model_cache["ce-model"] = mock_model

        scores = tool.rerank("my query", ["p1", "p2", "p3"], "ce-model")

        assert len(scores) == 3
        assert abs(scores[0] - 0.9) < 1e-6
        assert abs(scores[1] - 0.3) < 1e-6
        mock_model.predict.assert_called_once_with(
            [["my query", "p1"], ["my query", "p2"], ["my query", "p3"]]
        )

    def test_returns_zeros_when_predict_raises(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("cuda OOM")
        RerankTool._model_cache["err-model"] = mock_model

        scores = tool.rerank("q", ["p1", "p2"], "err-model")
        assert scores == [0.0, 0.0]


# ===========================================================================
# 5. RerankTool.score
# ===========================================================================

class TestRerankToolScore:
    def setup_method(self) -> None:
        RerankTool._model_cache.clear()

    def test_returns_single_float(self, tmp_path: Path) -> None:
        import numpy as np

        tool = _fresh_rerank_tool(tmp_path)
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.75])
        RerankTool._model_cache["m"] = mock_model

        result = tool.score("q", "passage", "m")
        assert isinstance(result, float)
        assert abs(result - 0.75) < 1e-6

    def test_returns_zero_on_fallback(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        RerankTool._model_cache["fallback"] = None
        assert tool.score("q", "p", "fallback") == 0.0


# ===========================================================================
# 6. RerankTool._load_model
# ===========================================================================

class TestRerankToolLoadModel:
    def setup_method(self) -> None:
        RerankTool._model_cache.clear()

    def test_fallback_when_sentence_transformers_missing(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        with patch.dict("sys.modules", {"sentence_transformers": None}):
            result = tool._load_model("no-st-model", "no-st-model", source="local")
        assert result["status"] == "fallback"
        assert RerankTool._model_cache.get("no-st-model") is None

    def test_stores_model_in_cache_on_success(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        mock_ce = MagicMock()
        mock_module = MagicMock()
        mock_module.CrossEncoder.return_value = mock_ce

        with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
            result = tool._load_model("test-model", "test-model", source="download")

        assert result["status"] == "ready"
        assert RerankTool._model_cache["test-model"] is mock_ce
        _, kwargs = mock_module.CrossEncoder.call_args
        assert kwargs["cache_folder"] == str(tmp_path)

    def test_passes_local_files_only_when_source_is_local(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        mock_ce = MagicMock()
        mock_module = MagicMock()
        mock_module.CrossEncoder.return_value = mock_ce

        with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
            tool._load_model("local-model", "/some/path", source="local")

        _, kwargs = mock_module.CrossEncoder.call_args
        assert kwargs["cache_folder"] == str(tmp_path)
        assert kwargs["local_files_only"] is True

    def test_does_not_reload_already_cached_model(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        sentinel = MagicMock()
        RerankTool._model_cache["cached-model"] = sentinel

        mock_module = MagicMock()
        with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
            tool._load_model("cached-model", "cached-model", source="download")

        mock_module.CrossEncoder.assert_not_called()

    def test_raises_on_cross_encoder_exception(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        mock_module = MagicMock()
        mock_module.CrossEncoder.side_effect = OSError("disk full")

        with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
            with pytest.raises(OSError, match="disk full"):
                tool._load_model("fail-model", "fail-model", source="download")


# ===========================================================================
# 7. Thread safety — concurrent ensure_model_ready loads model exactly once
# ===========================================================================

class TestRerankToolThreadSafety:
    def setup_method(self) -> None:
        RerankTool._model_cache.clear()

    def test_concurrent_ensure_model_ready_loads_once(self, tmp_path: Path) -> None:
        tool = _fresh_rerank_tool(tmp_path)
        download_count = 0

        def _fake_download(model_name: str) -> dict[str, Any]:
            nonlocal download_count
            download_count += 1
            RerankTool._model_cache[model_name] = MagicMock()
            return {"model_name": model_name, "status": "ready", "source": "download"}

        with patch("bible.infrastructure.vector.rerank_tool.get_local_model_path", return_value=None):
            with patch.object(tool, "_download_from_huggingface", side_effect=_fake_download):
                threads = [
                    threading.Thread(target=tool.ensure_model_ready, args=("concurrent-model",))
                    for _ in range(5)
                ]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=10)

        assert "concurrent-model" in RerankTool._model_cache
        # The fcntl lock ensures only one download runs; the rest hit the cache re-check.
        assert download_count == 1
