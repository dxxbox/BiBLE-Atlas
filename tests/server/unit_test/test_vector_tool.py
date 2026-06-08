from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from bible.infrastructure.vector.vector_tool import VectorTool


class TestVectorToolCacheDir:
    def setup_method(self) -> None:
        VectorTool._model_cache.clear()

    def test_cache_dir_is_absolute_and_created(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        tool = VectorTool(workspace_dir="workspace", hf_cache_dir="relative-cache")

        assert Path(tool._hf_cache_dir).is_absolute()
        assert Path(tool._hf_cache_dir).exists()

    def test_download_load_passes_cache_folder(self, tmp_path: Path) -> None:
        tool = VectorTool(workspace_dir=str(tmp_path), hf_cache_dir=str(tmp_path))
        fake_model = MagicMock()
        fake_model.get_embedding_dimension.return_value = 384
        mock_module = MagicMock()
        mock_module.SentenceTransformer.return_value = fake_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
            result = tool._load_model("test-model", "test-model", source="download")

        assert result["status"] == "ready"
        _, kwargs = mock_module.SentenceTransformer.call_args
        assert kwargs["cache_folder"] == str(tmp_path)
        assert "local_files_only" not in kwargs

    def test_local_load_passes_cache_folder_and_local_files_only(self, tmp_path: Path) -> None:
        tool = VectorTool(workspace_dir=str(tmp_path), hf_cache_dir=str(tmp_path))
        fake_model = MagicMock()
        fake_model.get_embedding_dimension.return_value = 384
        mock_module = MagicMock()
        mock_module.SentenceTransformer.return_value = fake_model

        with patch.dict("sys.modules", {"sentence_transformers": mock_module}):
            result = tool._load_model("local-model", "/some/path", source="local")

        assert result["status"] == "ready"
        _, kwargs = mock_module.SentenceTransformer.call_args
        assert kwargs["cache_folder"] == str(tmp_path)
        assert kwargs["local_files_only"] is True
