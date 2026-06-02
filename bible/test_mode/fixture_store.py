from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from bible.test_mode.schemas import ArtifactFixture, FixtureDocument, RouteFixture, TaskFixture


class FixtureLoadError(ValueError):
    pass


class FixtureStore:
    def __init__(
        self,
        *,
        builtin: FixtureDocument,
        external: FixtureDocument | None = None,
        strict: bool = True,
    ) -> None:
        self.builtin = builtin
        self.external = external
        self.strict = strict
        self.merged = _merge_builtin_and_external(builtin, external, strict=strict)
        if strict:
            self._validate_route_conflicts(self.merged.routes, "merged")

    @classmethod
    def load(
        cls,
        *,
        fixture_path: str | None = None,
        strict: bool = True,
    ) -> "FixtureStore":
        builtin = _load_fixture(_builtin_fixture_path())
        external = _load_external_fixtures(Path(fixture_path), strict=strict) if fixture_path else None
        return cls(builtin=builtin, external=external, strict=strict)

    @property
    def route_stores(self) -> list[list[RouteFixture]]:
        return [self.merged.routes]

    @property
    def tasks(self) -> list[TaskFixture]:
        return self.merged.tasks

    @property
    def artifacts(self) -> list[ArtifactFixture]:
        return self.merged.artifacts

    def _validate_route_conflicts(self, routes: list[RouteFixture], store_name: str) -> None:
        seen: dict[tuple[str, str, str | None, str], RouteFixture] = {}
        for route in routes:
            key = (
                route.method,
                route.path,
                route.domain,
                json.dumps(route.selector, sort_keys=True, ensure_ascii=False),
            )
            if key in seen:
                raise FixtureLoadError(
                    f"duplicate route fixture in {store_name}: {route.method} {route.path}"
                )
            seen[key] = route


def _builtin_fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "builtin.json"


def _load_external_fixtures(path: Path, *, strict: bool) -> FixtureDocument:
    paths = _external_fixture_paths(path)
    if not paths:
        raise FixtureLoadError(f"fixture directory has no JSON files: {path}")
    documents = [_load_fixture(fixture_path, base_dir=fixture_path.parent) for fixture_path in paths]
    return _merge_external_documents(documents, paths, strict=strict)


def _external_fixture_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(child for child in path.iterdir() if child.is_file() and child.suffix == ".json")
    raise FixtureLoadError(f"fixture path does not exist: {path}")


def _load_fixture(path: Path, *, base_dir: Path | None = None) -> FixtureDocument:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        document = FixtureDocument.model_validate(raw)
        if base_dir is not None:
            document = _resolve_artifact_paths(document, base_dir)
        return document
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as exc:
        raise FixtureLoadError(f"invalid fixture {path}: {exc}") from exc


def _resolve_artifact_paths(document: FixtureDocument, base_dir: Path) -> FixtureDocument:
    artifacts: list[ArtifactFixture] = []
    for artifact in document.artifacts:
        file_path = artifact.file_path
        if file_path and not Path(file_path).is_absolute():
            artifact = artifact.model_copy(update={"file_path": str((base_dir / file_path).resolve())})
        artifacts.append(artifact)
    return document.model_copy(update={"artifacts": artifacts})


def _merge_external_documents(
    documents: list[FixtureDocument],
    paths: list[Path],
    *,
    strict: bool,
) -> FixtureDocument:
    routes: list[RouteFixture] = []
    tasks: list[TaskFixture] = []
    artifacts: list[ArtifactFixture] = []
    route_id_index: dict[str, int] = {}
    route_key_index: dict[tuple[str, str, str | None, str], int] = {}
    task_index: dict[str, int] = {}
    artifact_index: dict[str, int] = {}

    for document, path in zip(documents, paths, strict=True):
        for route in document.routes:
            _merge_route(
                routes,
                route,
                route_id_index,
                route_key_index,
                strict=strict,
                source=f"external fixture {path}",
            )
        for task in document.tasks:
            _merge_by_key(
                tasks,
                task,
                task.task_id,
                task_index,
                strict=strict,
                source=f"external fixture {path}",
                item_name="task_id",
            )
        for artifact in document.artifacts:
            _merge_by_key(
                artifacts,
                artifact,
                artifact.artifact_id,
                artifact_index,
                strict=strict,
                source=f"external fixture {path}",
                item_name="artifact_id",
            )

    return FixtureDocument(version=1, routes=routes, tasks=tasks, artifacts=artifacts)


def _merge_builtin_and_external(
    builtin: FixtureDocument,
    external: FixtureDocument | None,
    *,
    strict: bool,
) -> FixtureDocument:
    routes = list(builtin.routes)
    tasks = list(builtin.tasks)
    artifacts = list(builtin.artifacts)
    route_id_index: dict[str, int] = {}
    route_key_index: dict[tuple[str, str, str | None, str], int] = {}
    task_index = {task.task_id: index for index, task in enumerate(tasks)}
    artifact_index = {artifact.artifact_id: index for index, artifact in enumerate(artifacts)}

    for index, route in enumerate(routes):
        _index_route(route, index, route_id_index, route_key_index)

    if external is not None:
        for route in external.routes:
            _merge_route(
                routes,
                route,
                route_id_index,
                route_key_index,
                strict=False,
                source="external fixture",
            )
        for task in external.tasks:
            _merge_by_key(tasks, task, task.task_id, task_index, strict=False, source="external fixture", item_name="task_id")
        for artifact in external.artifacts:
            _merge_by_key(
                artifacts,
                artifact,
                artifact.artifact_id,
                artifact_index,
                strict=False,
                source="external fixture",
                item_name="artifact_id",
            )

    return FixtureDocument(version=1, routes=routes, tasks=tasks, artifacts=artifacts)


def _route_key(route: RouteFixture) -> tuple[str, str, str | None, str]:
    return (
        route.method,
        route.path,
        route.domain,
        json.dumps(route.selector, sort_keys=True, ensure_ascii=False),
    )


def _index_route(
    route: RouteFixture,
    index: int,
    route_id_index: dict[str, int],
    route_key_index: dict[tuple[str, str, str | None, str], int],
) -> None:
    if route.id:
        route_id_index[route.id] = index
    route_key_index[_route_key(route)] = index


def _merge_route(
    routes: list[RouteFixture],
    route: RouteFixture,
    route_id_index: dict[str, int],
    route_key_index: dict[tuple[str, str, str | None, str], int],
    *,
    strict: bool,
    source: str,
) -> None:
    route_key = _route_key(route)
    existing_index = route_id_index.get(route.id) if route.id else None
    if existing_index is None:
        existing_index = route_key_index.get(route_key)
    if existing_index is not None:
        if strict:
            route_identity = route.id or f"{route.method} {route.path}"
            raise FixtureLoadError(f"duplicate route fixture in {source}: {route_identity}")
        old_route = routes[existing_index]
        if old_route.id:
            route_id_index.pop(old_route.id, None)
        route_key_index.pop(_route_key(old_route), None)
        routes[existing_index] = route
        _index_route(route, existing_index, route_id_index, route_key_index)
        return
    routes.append(route)
    _index_route(route, len(routes) - 1, route_id_index, route_key_index)


def _merge_by_key(
    items: list,
    item,
    key: str,
    index: dict[str, int],
    *,
    strict: bool,
    source: str,
    item_name: str,
) -> None:
    if key in index:
        if strict:
            raise FixtureLoadError(f"duplicate {item_name} in {source}: {key}")
        items[index[key]] = item
        return
    index[key] = len(items)
    items.append(item)

