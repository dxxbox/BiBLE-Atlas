from __future__ import annotations

from typing import Any

from bible.test_mode.fixture_store import FixtureStore
from bible.test_mode.schemas import RequestContext, RouteFixture


class FixtureConflictError(ValueError):
    pass


class FixtureResolver:
    def __init__(self, store: FixtureStore) -> None:
        self.store = store

    def resolve(self, context: RequestContext) -> RouteFixture | None:
        for routes in self.store.route_stores:
            matched = self._match_store(routes, context)
            if matched is not None:
                return matched
        return None

    def _match_store(
        self,
        routes: list[RouteFixture],
        context: RequestContext,
    ) -> RouteFixture | None:
        candidates = [
            route
            for route in routes
            if route.method == context.method
            and route.path == context.path
            and route.domain == context.domain
            and _selector_matches(route.selector, context)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda route: len(route.selector), reverse=True)
        best = candidates[0]
        tied = [route for route in candidates if len(route.selector) == len(best.selector)]
        if len(tied) > 1 and self.store.strict:
            ids = ", ".join(route.id or f"{route.method} {route.path}" for route in tied)
            raise FixtureConflictError(f"multiple fixture routes matched equally: {ids}")
        return best


def _selector_matches(selector: dict[str, Any], context: RequestContext) -> bool:
    flat = _flatten_context(context)
    for key, expected in selector.items():
        if key not in flat:
            return False
        if not _values_equal(flat[key], expected, key):
            return False
    return True


def _flatten_context(context: RequestContext) -> dict[str, Any]:
    flat: dict[str, Any] = {
        "method": context.method,
        "path": context.path,
        "domain": context.domain,
    }
    flat.update(context.params)
    flat.update(context.path_params)
    flat.update(context.body)
    fields = context.multipart.get("fields") or {}
    flat.update(fields)
    file_names = context.multipart.get("file_names")
    if file_names is not None:
        flat["file_names"] = sorted(file_names)
    return flat


def _values_equal(actual: Any, expected: Any, key: str) -> bool:
    if key == "file_names" and isinstance(actual, list) and isinstance(expected, list):
        return sorted(actual) == sorted(expected)
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return float(actual) == float(expected)
    return actual == expected

