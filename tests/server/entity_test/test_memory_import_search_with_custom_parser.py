from __future__ import annotations

import os
from pathlib import Path
import time

import httpx

from _helpers import (
    BackendLogAssertions,
    get_memory_database_state,
    response_json,
    unique_id,
    wait_for_import_task,
)


def _custom_memory_parser_path() -> Path:
    from bible.config.configure import (
        _clear_bible_atlas_config_cache,
        get_bible_atlas_config,
    )

    _clear_bible_atlas_config_cache()
    config = get_bible_atlas_config()
    return Path(config.import_memory.custom_parsers_dir) / "parse_memory.py"


CUSTOM_MEMORY_PARSER = r"""from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_context(raw_context: str | None) -> dict:
    if not raw_context:
        return {}
    return json.loads(raw_context)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--context", default=None)
    args = parser.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    context = _load_context(args.context)
    input_file = manifest["files"][0]
    input_payload = json.loads(Path(input_file["abs_path"]).read_text(encoding="utf-8"))
    parser_script_path = Path(__file__)

    memory_id = context.get("memory_id") or input_payload["memory_id"]
    title = input_payload.get("title") or f"Custom Parser Memory {memory_id}"
    abstract = input_payload["abstract"]
    overview = input_payload.get("overview", "")
    chunk = {
        "doc_id": memory_id,
        "memory_id": memory_id,
        "title": title,
        "content": f"{abstract}\n{overview}",
        "abstract": abstract,
        "overview": overview,
        "task_ids": [],
        "feature_tags": ["custom-parser"],
        "domain_tags": ["entity-test"],
        "component_tags": ["memory-import"],
        "metadata": {
            "source_file": input_file["filename"],
            "related_file_refs": [],
            "related_storage_paths": [],
            "parser_script_path": str(parser_script_path),
            "parser_script_exists": parser_script_path.exists(),
        },
    }

    search_profile = {
        "tag": "memory",
        "search_type_profile": {
            "keyword": {
                "enabled": True,
                "term_fields": [
                    {"field": "memory_id.keyword", "weight": 5.0},
                    {"field": "feature_tags.keyword", "weight": 1.5},
                ],
            },
            "title": {
                "enabled": True,
                "match_fields": [{"field": "title", "weight": 3.0}],
            },
            "text": {
                "enabled": True,
                "multi_match_type": "most_fields",
                "fields": [
                    {"field": "title", "weight": 3.0},
                    {"field": "abstract", "weight": 3.0},
                    {"field": "overview", "weight": 2.5},
                    {"field": "content", "weight": 2.0},
                ],
            },
            "vector": {
                "enabled": True,
                "vector_field": "content_vector",
                "source_template": "{title}\n{abstract}\n{overview}",
                "num_candidates": 100,
            },
            "hybrid": {
                "enabled": True,
                "default_vector_weight": 0.65,
            },
        },
        "response_fields": [
            "doc_id",
            "memory_id",
            "title",
            "abstract",
            "overview",
            "feature_tags",
            "metadata.parser_script_exists",
            "score",
        ],
    }

    print(json.dumps({
        "chunks": [chunk],
        "search_profile": search_profile,
        "local_file_storage_plan": None,
    }))


if __name__ == "__main__":
    main()
"""


def _assert_memory_search_finds_custom_import(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
    *,
    kb_index: str,
    memory_id: str,
) -> None:
    timeout = float(os.environ.get("BIBLE_SEARCH_VISIBILITY_TIMEOUT", "15"))
    deadline = time.monotonic() + timeout
    last_payload = None

    while time.monotonic() < deadline:
        response = client.post(
            "/api/search/memory",
            json={
                "query": memory_id,
                "tag": "memory",
                "kb_index": kb_index,
                "search_type": "keyword",
                "top_k": 5,
            },
        )

        assert response.status_code == 200
        payload = response_json(response)
        last_payload = payload
        assert payload["success"] is True
        assert payload["domain"] == "MEMORY"
        assert payload["kb_index"] == kb_index
        assert payload["tag"] == "memory"
        matches = [
            item for item in payload["results"]["memory"]
            if item["memory_id"] == memory_id
        ]
        if matches:
            assert matches[0]["title"] == f"Custom Parser Memory {memory_id}"
            assert matches[0]["parser_script_exists"] is True
            backend_log.expect(f"MEMORY search started tag=memory kb_index={kb_index}")
            backend_log.expect(
                f"OpenSearch binding lookup by index hit domain=MEMORY kb_index={kb_index}"
            )
            backend_log.expect(
                f"MEMORY search completed kb_index={kb_index} content_index=memory_{kb_index}"
            )
            backend_log.expect("HTTP request completed method=POST path=/api/search/memory")
            return
        time.sleep(1)

    raise AssertionError(
        f"memory_id {memory_id!r} was not searchable in kb_index {kb_index!r} "
        f"within {timeout}s; last_payload={last_payload!r}"
    )


def test_import_memory_with_uploaded_custom_parser_is_searchable(
    client: httpx.Client,
    backend_log: BackendLogAssertions,
) -> None:
    kb_index = unique_id("kb_import_search_custom_parser")
    memory_id = unique_id("mem_import_search_custom_parser")
    parser_filename = "custom_memory_parser.py"

    response = client.post(
        "/api/import/memory",
        data={
            "kb_index": kb_index,
            "tag": "memory",
            "parser_context": f'{{"memory_id": "{memory_id}"}}',
        },
        files=[
            (
                "files",
                (
                    "custom-memory.json",
                    b'{"abstract":"Imported by uploaded custom parser.",'
                    b'"overview":"Entity test verifies parser upload, storage, and search."}',
                    "application/json",
                ),
            ),
            (
                "parser_script",
                (parser_filename, CUSTOM_MEMORY_PARSER.encode("utf-8"), "text/x-python"),
            ),
        ],
    )

    assert response.status_code == 202
    task_id = response_json(response)["task_id"]
    task = wait_for_import_task(client, task_id)
    assert task["status"] == "completed", task
    assert task["result"]["chunks_indexed"] >= 1

    db_state = get_memory_database_state(kb_index, memory_id)
    assert db_state.binding["parser_script_source"] == "parse_memory.py"
    assert db_state.binding["parser_script_sha256"]
    assert db_state.document["memory_id"] == memory_id
    assert db_state.document["title"] == f"Custom Parser Memory {memory_id}"
    assert db_state.document["abstract"] == "Imported by uploaded custom parser."
    assert db_state.document["metadata"]["source_file"] == "custom-memory.json"
    assert db_state.document["metadata"]["parser_script_exists"] is True
    assert db_state.document["metadata"]["parser_script_path"].endswith(parser_filename)
    persisted_parser = _custom_memory_parser_path()
    assert persisted_parser.is_file()
    assert persisted_parser.read_text(encoding="utf-8") == CUSTOM_MEMORY_PARSER

    backend_log.expect(f"POST /api/import/memory received: kb_index={kb_index} tag=memory")
    backend_log.expect(f"Starting memory import: kb_index={kb_index}")
    backend_log.expect("Parser finished: chunks=1")
    backend_log.expect("Import complete: chunks_indexed=")
    backend_log.expect("HTTP request completed method=POST path=/api/import/memory")
    _assert_memory_search_finds_custom_import(
        client,
        backend_log,
        kb_index=kb_index,
        memory_id=memory_id,
    )
