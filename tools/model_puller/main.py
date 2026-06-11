from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, NamedTuple, Sequence

import yaml


class ModelRef(NamedTuple):
    id: str
    name: str


class PullerConfig(NamedTuple):
    repo_root: Path
    vector_cache_dir: Path
    rerank_cache_dir: Path
    vector_models: list[ModelRef]
    rerank_models: list[ModelRef]


class SelectedModel(NamedTuple):
    kind: str
    model: ModelRef
    cache_dir: Path


def default_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(repo_root: Path, raw_path: str | None, default_path: str) -> Path:
    path = Path(raw_path or default_path).expanduser()
    if path.is_absolute():
        return path
    return repo_root / path


def model_refs(raw_models: Any) -> list[ModelRef]:
    if not isinstance(raw_models, list):
        return []

    refs: list[ModelRef] = []
    for item in raw_models:
        if isinstance(item, str) and item:
            refs.append(ModelRef(id=item, name=item))
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                model_id = item.get("id")
                refs.append(ModelRef(id=model_id if isinstance(model_id, str) and model_id else name, name=name))
    return refs


def load_config(config_path: Path, repo_root: Path | None = None) -> PullerConfig:
    repo_root = (repo_root or default_repo_root()).resolve()
    with config_path.open("r", encoding="utf-8") as fh:
        raw_text = os.path.expandvars(fh.read())
        raw = yaml.safe_load(raw_text) or {}
    if not isinstance(raw, dict):
        raw = {}

    workspace = raw.get("workspace") if isinstance(raw.get("workspace"), dict) else {}
    workspace_root = workspace.get("root") if isinstance(workspace, dict) else None
    default_cache = str(Path(workspace_root or "./workspace") / "hf_cache")

    vector = raw.get("vector") if isinstance(raw.get("vector"), dict) else {}
    rerank = raw.get("rerank") if isinstance(raw.get("rerank"), dict) else {}

    return PullerConfig(
        repo_root=repo_root,
        vector_cache_dir=resolve_repo_path(repo_root, vector.get("hf_cache_dir"), default_cache),
        rerank_cache_dir=resolve_repo_path(repo_root, rerank.get("hf_cache_dir"), default_cache),
        vector_models=model_refs(vector.get("available_models")),
        rerank_models=model_refs(rerank.get("available_models")),
    )


def select_models(
    config: PullerConfig,
    model_type: str,
    model_filter: str | None,
) -> list[SelectedModel]:
    selected: list[SelectedModel] = []
    if model_type in ("vector", "all"):
        selected.extend(
            SelectedModel(kind="vector", model=model, cache_dir=config.vector_cache_dir)
            for model in config.vector_models
        )
    if model_type in ("rerank", "all"):
        selected.extend(
            SelectedModel(kind="rerank", model=model, cache_dir=config.rerank_cache_dir)
            for model in config.rerank_models
        )

    if model_filter:
        selected = [
            item for item in selected
            if item.model.id == model_filter or item.model.name == model_filter
        ]
    return selected


def describe_models(models: Sequence[SelectedModel]) -> None:
    if not models:
        print("No models selected.")
        return

    for item in models:
        print(f"{item.kind}\t{item.model.id}\t{item.model.name}\t{item.cache_dir}")


def pull_models(models: Sequence[SelectedModel], dry_run: bool = False) -> int:
    describe_models(models)
    if dry_run or not models:
        return 0

    from sentence_transformers import CrossEncoder, SentenceTransformer

    failed: list[tuple[SelectedModel, str]] = []
    for item in models:
        item.cache_dir.mkdir(parents=True, exist_ok=True)
        os.environ["HF_HOME"] = str(item.cache_dir)
        os.environ["HUGGINGFACE_HUB_CACHE"] = str(item.cache_dir / "hub")
        try:
            if item.kind == "vector":
                SentenceTransformer(item.model.name, cache_folder=str(item.cache_dir))
            else:
                CrossEncoder(item.model.name, cache_folder=str(item.cache_dir))
            print(f"Pulled {item.kind} model: {item.model.name}")
        except Exception as exc:
            failed.append((item, str(exc)))
            print(f"Failed {item.kind} model {item.model.name}: {exc}")

    return 1 if failed else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Standalone BiBLE Atlas model puller")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("pull", "list"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", default="bible-atlas.yaml")
        subparser.add_argument("--repo-root", default=str(default_repo_root()))
        subparser.add_argument("--type", choices=["vector", "rerank", "all"], default="all")
        subparser.add_argument("--model", default=None)
        if command == "pull":
            subparser.add_argument("--dry-run", action="store_true")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(config_path=Path(args.config), repo_root=Path(args.repo_root))
    selected = select_models(config, model_type=args.type, model_filter=args.model)
    if args.command == "list":
        describe_models(selected)
        return 0
    return pull_models(selected, dry_run=args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
