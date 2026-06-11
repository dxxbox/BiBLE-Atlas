from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock

ROOT_DIR = Path(__file__).resolve().parents[2]
MODEL_PULLER = ROOT_DIR / "tools" / "model_puller" / "main.py"


def load_model_puller() -> ModuleType:
    spec = importlib.util.spec_from_file_location("model_puller_main", MODEL_PULLER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_config(path: Path) -> None:
    path.write_text(
        """
workspace:
  root: ./workspace
vector:
  preload_on_startup: true
  hf_cache_dir: ./workspace/hf_cache
  available_models:
    - id: mini
      name: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
    - id: bge-large
      name: BAAI/bge-large-zh-v1.5
rerank:
  preload_on_startup: true
  hf_cache_dir: ./workspace/hf_cache
  available_models:
    - id: bge-reranker-base
      name: BAAI/bge-reranker-base
""",
        encoding="utf-8",
    )


def install_fake_sentence_transformers(monkeypatch, sentence_transformer, cross_encoder) -> None:
    fake_module = SimpleNamespace(
        SentenceTransformer=sentence_transformer,
        CrossEncoder=cross_encoder,
    )
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)


def test_model_puller_has_no_bible_imports() -> None:
    source = MODEL_PULLER.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.append(node.module)

    assert not any(name == "bible" or name.startswith("bible.") for name in imported_modules)


def test_load_config_extracts_models_and_resolves_paths_against_repo_root(tmp_path: Path) -> None:
    module = load_model_puller()
    config_path = tmp_path / "bible-atlas.yaml"
    write_config(config_path)

    config = module.load_config(config_path=config_path, repo_root=ROOT_DIR)

    assert config.vector_cache_dir == ROOT_DIR / "workspace" / "hf_cache"
    assert config.rerank_cache_dir == ROOT_DIR / "workspace" / "hf_cache"
    assert [model.id for model in config.vector_models] == ["mini", "bge-large"]
    assert [model.name for model in config.vector_models] == [
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        "BAAI/bge-large-zh-v1.5",
    ]
    assert [model.id for model in config.rerank_models] == ["bge-reranker-base"]


def test_load_config_expands_environment_variables(tmp_path: Path, monkeypatch) -> None:
    module = load_model_puller()
    config_path = tmp_path / "bible-atlas.yaml"
    monkeypatch.setenv("BIBLE_TEST_HF_CACHE", "custom-cache")
    config_path.write_text(
        """
workspace:
  root: ./workspace
vector:
  hf_cache_dir: ${BIBLE_TEST_HF_CACHE}
  available_models:
    - id: mini
      name: sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
""",
        encoding="utf-8",
    )

    config = module.load_config(config_path=config_path, repo_root=ROOT_DIR)

    assert config.vector_cache_dir == ROOT_DIR / "custom-cache"


def test_select_models_filters_by_type_and_model_id_or_name(tmp_path: Path) -> None:
    module = load_model_puller()
    config_path = tmp_path / "bible-atlas.yaml"
    write_config(config_path)
    config = module.load_config(config_path=config_path, repo_root=ROOT_DIR)

    vector_only = module.select_models(config, model_type="vector", model_filter=None)
    rerank_by_id = module.select_models(config, model_type="all", model_filter="bge-reranker-base")
    vector_by_name = module.select_models(config, model_type="all", model_filter="BAAI/bge-large-zh-v1.5")

    assert [item.model.id for item in vector_only] == ["mini", "bge-large"]
    assert [item.model.name for item in rerank_by_id] == ["BAAI/bge-reranker-base"]
    assert [item.model.id for item in vector_by_name] == ["bge-large"]


def test_dry_run_does_not_import_sentence_transformers(tmp_path: Path, monkeypatch) -> None:
    module = load_model_puller()
    config_path = tmp_path / "bible-atlas.yaml"
    write_config(config_path)
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

    exit_code = module.main([
        "pull",
        "--config",
        str(config_path),
        "--repo-root",
        str(ROOT_DIR),
        "--dry-run",
    ])

    assert exit_code == 0
    assert "sentence_transformers" not in sys.modules


def test_pull_dispatches_vector_and_rerank_models_to_sentence_transformers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    module = load_model_puller()
    config_path = tmp_path / "bible-atlas.yaml"
    write_config(config_path)
    sentence_transformer = MagicMock()
    cross_encoder = MagicMock()
    install_fake_sentence_transformers(monkeypatch, sentence_transformer, cross_encoder)

    exit_code = module.main([
        "pull",
        "--config",
        str(config_path),
        "--repo-root",
        str(ROOT_DIR),
    ])

    assert exit_code == 0
    sentence_transformer.assert_any_call(
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        cache_folder=str(ROOT_DIR / "workspace" / "hf_cache"),
    )
    sentence_transformer.assert_any_call(
        "BAAI/bge-large-zh-v1.5",
        cache_folder=str(ROOT_DIR / "workspace" / "hf_cache"),
    )
    cross_encoder.assert_called_once_with(
        "BAAI/bge-reranker-base",
        cache_folder=str(ROOT_DIR / "workspace" / "hf_cache"),
    )
