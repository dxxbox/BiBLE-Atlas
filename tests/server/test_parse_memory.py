"""
Tests for parse_memory.py and the memory_parser/ package.

Covers (aligns with design doc §8):
1. manifest_loader — valid, missing fields, duplicate file_ref
2. file_classifier — valid, no meta.json, multiple meta.json
3. meta_parser — valid, missing required fields, length limits, bad ISO8601
4. chunk_builder — correct fields, abstract+overview not split, file_refs wired
5. storage_plan_builder — all attachments in plan, meta.json excluded
6. orchestrator — end-to-end parse_manifest (no subprocess)
7. parse_memory.py CLI — subprocess integration (SandboxRunner-style invocation)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers: path to parsers directory
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Could not locate project root (no pyproject.toml) starting from {start}")

_PARSERS_DIR = _find_project_root(Path(__file__)) / "bible" / "features" / "import" / "memory_import" / "parsers"
_PARSE_MEMORY_PY = _PARSERS_DIR / "parse_memory.py"

# Add parsers dir to sys.path so memory_parser is importable in-process
if str(_PARSERS_DIR) not in sys.path:
    sys.path.insert(0, str(_PARSERS_DIR))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _write_manifest(tmp_path: Path, files: list[dict[str, Any]]) -> Path:
    manifest = {
        "task_id": "test-task",
        "kb_index": "kb_test",
        "tag": "memory",
        "files": files,
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest), encoding="utf-8")
    return p


def _write_meta(tmp_path: Path, data: dict[str, Any] | None = None) -> Path:
    defaults: dict[str, Any] = {
        "memory_id": "mem_test_001",
        "title": "Test Memory",
        "abstract": "Short summary of the test memory.",
        "overview": "Detailed overview of the test memory.",
        "created_at": "2026-05-22T10:00:00+00:00",
        "updated_at": "2026-05-22T12:00:00+00:00",
        "task_ids": ["TASK-001"],
        "feature_tags": ["testing"],
        "domain_tags": ["unit-test"],
        "component_tags": ["parser"],
        "source_client": "test_client",
        "language": "en",
    }
    if data:
        defaults.update(data)
    p = tmp_path / "meta.json"
    p.write_text(json.dumps(defaults), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# 1. manifest_loader
# ---------------------------------------------------------------------------

class TestManifestLoader:
    def test_valid_manifest_returns_uploaded_files(self, tmp_path):
        from memory_parser.manifest_loader import load_manifest  # type: ignore[import]
        meta = _write_meta(tmp_path)
        attach = tmp_path / "attach.txt"
        attach.write_bytes(b"content")
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
            {"file_ref": "f_002", "filename": "attach.txt", "abs_path": str(attach), "size_bytes": 7},
        ])
        files = load_manifest(str(m))
        assert len(files) == 2
        assert files[0].file_ref == "f_001"
        assert files[1].filename == "attach.txt"

    def test_empty_files_list_raises(self, tmp_path):
        from memory_parser.manifest_loader import load_manifest  # type: ignore[import]
        m = _write_manifest(tmp_path, [])
        with pytest.raises(ValueError, match="non-empty"):
            load_manifest(str(m))

    def test_missing_file_ref_raises(self, tmp_path):
        from memory_parser.manifest_loader import load_manifest  # type: ignore[import]
        m = _write_manifest(tmp_path, [{"filename": "meta.json", "abs_path": "/tmp/x"}])
        with pytest.raises(ValueError, match="missing required field"):
            load_manifest(str(m))

    def test_duplicate_file_ref_raises(self, tmp_path):
        from memory_parser.manifest_loader import load_manifest  # type: ignore[import]
        m = _write_manifest(tmp_path, [
            {"file_ref": "dup", "filename": "meta.json", "abs_path": "/tmp/a"},
            {"file_ref": "dup", "filename": "other.txt", "abs_path": "/tmp/b"},
        ])
        with pytest.raises(ValueError, match="duplicated file_ref"):
            load_manifest(str(m))


# ---------------------------------------------------------------------------
# 2. file_classifier
# ---------------------------------------------------------------------------

class TestFileClassifier:
    def _make_file(self, ref, name, path="/tmp/x"):
        from memory_parser.schemas import UploadedFile  # type: ignore[import]
        return UploadedFile(file_ref=ref, filename=name, abs_path=path, size_bytes=0)

    def test_splits_meta_and_attachments(self):
        from memory_parser.file_classifier import split_meta_and_attachments  # type: ignore[import]
        files = [
            self._make_file("f1", "meta.json"),
            self._make_file("f2", "attach.txt"),
            self._make_file("f3", "img.png"),
        ]
        meta, attachments = split_meta_and_attachments(files)
        assert meta.file_ref == "f1"
        assert len(attachments) == 2

    def test_no_meta_json_raises(self):
        from memory_parser.file_classifier import split_meta_and_attachments  # type: ignore[import]
        files = [self._make_file("f1", "attach.txt")]
        with pytest.raises(ValueError, match="meta.json"):
            split_meta_and_attachments(files)

    def test_multiple_meta_json_raises(self):
        from memory_parser.file_classifier import split_meta_and_attachments  # type: ignore[import]
        files = [
            self._make_file("f1", "meta.json"),
            self._make_file("f2", "Meta.json"),
        ]
        # meta.json check is case-insensitive, so both match
        with pytest.raises(ValueError, match="meta.json"):
            split_meta_and_attachments(files)

    def test_only_meta_no_attachments(self):
        from memory_parser.file_classifier import split_meta_and_attachments  # type: ignore[import]
        files = [self._make_file("f1", "meta.json")]
        meta, attachments = split_meta_and_attachments(files)
        assert meta.file_ref == "f1"
        assert attachments == []


# ---------------------------------------------------------------------------
# 3. meta_parser
# ---------------------------------------------------------------------------

class TestMetaParser:
    def test_valid_meta_parses_correctly(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        meta_path = _write_meta(tmp_path)
        meta = parse_meta(str(meta_path))
        assert meta.memory_id == "mem_test_001"
        assert meta.title == "Test Memory"
        assert meta.abstract == "Short summary of the test memory."
        assert meta.language == "en"
        assert "TASK-001" in meta.task_ids

    def test_missing_memory_id_raises(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"memory_id": ""})
        with pytest.raises(ValueError, match="memory_id"):
            parse_meta(str(p))

    def test_missing_title_raises(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"title": ""})
        with pytest.raises(ValueError, match="title"):
            parse_meta(str(p))

    def test_missing_abstract_raises(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"abstract": ""})
        with pytest.raises(ValueError, match="abstract"):
            parse_meta(str(p))

    def test_title_too_long_raises(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"title": "x" * 201})
        with pytest.raises(ValueError, match="title"):
            parse_meta(str(p))

    def test_abstract_too_long_raises(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"abstract": "a" * 501})
        with pytest.raises(ValueError, match="abstract"):
            parse_meta(str(p))

    def test_bad_iso8601_created_at_raises(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"created_at": "not-a-date"})
        with pytest.raises(ValueError, match="ISO 8601"):
            parse_meta(str(p))

    def test_missing_optional_overview_defaults_to_empty(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"overview": None})
        meta = parse_meta(str(p))
        assert meta.overview == ""

    def test_missing_language_defaults_to_zh(self, tmp_path):
        from memory_parser.meta_parser import parse_meta  # type: ignore[import]
        p = _write_meta(tmp_path, {"language": None})
        meta = parse_meta(str(p))
        assert meta.language == "zh"


# ---------------------------------------------------------------------------
# 4. chunk_builder
# ---------------------------------------------------------------------------

class TestChunkBuilder:
    def _make_meta(self):
        from memory_parser.schemas import MemoryMeta  # type: ignore[import]
        return MemoryMeta(
            memory_id="mem_001",
            title="Title",
            abstract="Abstract text.",
            overview="Overview text.",
            created_at="2026-05-22T10:00:00+00:00",
            updated_at=None,
            task_ids=["T1"],
            feature_tags=["f1"],
            domain_tags=["d1"],
            component_tags=[],
            source_client="client",
            language="zh",
        )

    def _make_attachment(self, ref: str, name: str):
        from memory_parser.schemas import UploadedFile  # type: ignore[import]
        return UploadedFile(file_ref=ref, filename=name, abs_path="/tmp/" + name, size_bytes=0)

    def test_builds_exactly_one_chunk(self):
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        chunks = build_single_memory_chunk(self._make_meta(), [])
        assert len(chunks) == 1

    def test_chunk_contains_required_fields(self):
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        chunk = build_single_memory_chunk(self._make_meta(), [])[0]
        for field in ("doc_id", "memory_id", "title", "content", "abstract", "overview", "metadata"):
            assert field in chunk, f"missing field: {field}"

    def test_content_is_abstract_plus_overview(self):
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        chunk = build_single_memory_chunk(self._make_meta(), [])[0]
        assert "Abstract text." in chunk["content"]
        assert "Overview text." in chunk["content"]

    def test_abstract_and_overview_stored_whole(self):
        """No truncation — full text must survive."""
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        chunk = build_single_memory_chunk(self._make_meta(), [])[0]
        assert chunk["abstract"] == "Abstract text."
        assert chunk["overview"] == "Overview text."

    def test_related_file_refs_populated_from_attachments(self):
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        attachments = [self._make_attachment("ref_a", "a.pdf"), self._make_attachment("ref_b", "b.png")]
        chunk = build_single_memory_chunk(self._make_meta(), attachments)[0]
        assert chunk["metadata"]["related_file_refs"] == ["ref_a", "ref_b"]

    def test_related_storage_paths_initially_empty(self):
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        chunk = build_single_memory_chunk(self._make_meta(), [])[0]
        assert chunk["metadata"]["related_storage_paths"] == []

    def test_no_attachments_gives_empty_refs(self):
        from memory_parser.chunk_builder import build_single_memory_chunk  # type: ignore[import]
        chunk = build_single_memory_chunk(self._make_meta(), [])[0]
        assert chunk["metadata"]["related_file_refs"] == []


# ---------------------------------------------------------------------------
# 5. storage_plan_builder
# ---------------------------------------------------------------------------

class TestStoragePlanBuilder:
    def _make_attachment(self, ref: str, name: str, path: str = "/tmp/f"):
        from memory_parser.schemas import UploadedFile  # type: ignore[import]
        return UploadedFile(file_ref=ref, filename=name, abs_path=path, size_bytes=100)

    def test_empty_attachments_returns_empty_files_list(self):
        from memory_parser.storage_plan_builder import build_local_storage_plan  # type: ignore[import]
        plan = build_local_storage_plan([])
        assert plan["files"] == []

    def test_attachments_appear_in_plan(self):
        from memory_parser.storage_plan_builder import build_local_storage_plan  # type: ignore[import]
        attachments = [self._make_attachment("r1", "a.pdf", "/tmp/a.pdf")]
        plan = build_local_storage_plan(attachments)
        assert len(plan["files"]) == 1
        entry = plan["files"][0]
        assert entry["file_ref"] == "r1"
        assert entry["filename"] == "a.pdf"
        assert entry["source_path"] == "/tmp/a.pdf"
        assert entry["must_store_local"] is True
        assert entry["storage_role"] == "memory_attachment"

    def test_meta_json_not_in_plan(self):
        """file_classifier separates meta.json; storage plan must contain only attachments."""
        from memory_parser.storage_plan_builder import build_local_storage_plan  # type: ignore[import]
        attachments = [self._make_attachment("r2", "message.json")]
        plan = build_local_storage_plan(attachments)
        filenames = [e["filename"] for e in plan["files"]]
        assert "meta.json" not in filenames


# ---------------------------------------------------------------------------
# 6. orchestrator — end-to-end (in-process)
# ---------------------------------------------------------------------------

class TestOrchestrator:
    def test_full_parse_returns_chunks_profile_plan(self, tmp_path):
        from memory_parser.orchestrator import parse_manifest  # type: ignore[import]
        meta = _write_meta(tmp_path)
        attach = tmp_path / "attach.txt"
        attach.write_bytes(b"attachment content")
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": meta.stat().st_size},
            {"file_ref": "f_002", "filename": "attach.txt", "abs_path": str(attach), "size_bytes": 18},
        ])
        result = parse_manifest(str(m), {})
        assert "chunks" in result
        assert "search_profile" in result
        assert "local_file_storage_plan" in result

    def test_one_chunk_per_meta(self, tmp_path):
        from memory_parser.orchestrator import parse_manifest  # type: ignore[import]
        meta = _write_meta(tmp_path)
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
        ])
        result = parse_manifest(str(m), {})
        assert len(result["chunks"]) == 1

    def test_attachment_in_storage_plan(self, tmp_path):
        from memory_parser.orchestrator import parse_manifest  # type: ignore[import]
        meta = _write_meta(tmp_path)
        attach = tmp_path / "msg.json"
        attach.write_bytes(b"{}")
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
            {"file_ref": "f_002", "filename": "msg.json", "abs_path": str(attach), "size_bytes": 2},
        ])
        result = parse_manifest(str(m), {})
        plan_refs = [e["file_ref"] for e in result["local_file_storage_plan"]["files"]]
        assert "f_002" in plan_refs
        assert "f_001" not in plan_refs  # meta.json is not an attachment

    def test_chunk_has_related_file_refs_from_attachments(self, tmp_path):
        from memory_parser.orchestrator import parse_manifest  # type: ignore[import]
        meta = _write_meta(tmp_path)
        attach = tmp_path / "data.bin"
        attach.write_bytes(b"x" * 100)
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
            {"file_ref": "f_002", "filename": "data.bin", "abs_path": str(attach), "size_bytes": 100},
        ])
        result = parse_manifest(str(m), {})
        chunk_refs = result["chunks"][0]["metadata"]["related_file_refs"]
        assert "f_002" in chunk_refs

    def test_no_meta_json_raises(self, tmp_path):
        from memory_parser.orchestrator import parse_manifest  # type: ignore[import]
        attach = tmp_path / "only.txt"
        attach.write_bytes(b"no meta")
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "only.txt", "abs_path": str(attach), "size_bytes": 7},
        ])
        with pytest.raises(ValueError, match="meta.json"):
            parse_manifest(str(m), {})


# ---------------------------------------------------------------------------
# 7. parse_memory.py CLI — subprocess integration
# ---------------------------------------------------------------------------

class TestParseMemoryCLI:
    """Tests that invoke parse_memory.py as a subprocess (mirrors SandboxRunner behavior)."""

    def _run(self, manifest_path: str, context: dict | None = None) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(_PARSE_MEMORY_PY), "--manifest", manifest_path]
        if context:
            cmd += ["--context", json.dumps(context)]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_cli_succeeds_with_valid_manifest(self, tmp_path):
        meta = _write_meta(tmp_path)
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
        ])
        proc = self._run(str(m))
        assert proc.returncode == 0, proc.stderr

    def test_cli_outputs_valid_json(self, tmp_path):
        meta = _write_meta(tmp_path)
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
        ])
        proc = self._run(str(m))
        result = json.loads(proc.stdout)
        assert "chunks" in result
        assert "search_profile" in result
        assert "local_file_storage_plan" in result

    def test_cli_chunk_contains_memory_id(self, tmp_path):
        meta = _write_meta(tmp_path)
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
        ])
        proc = self._run(str(m))
        result = json.loads(proc.stdout)
        assert result["chunks"][0]["memory_id"] == "mem_test_001"

    def test_cli_fails_on_missing_meta_json(self, tmp_path):
        attach = tmp_path / "nope.txt"
        attach.write_bytes(b"x")
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "nope.txt", "abs_path": str(attach), "size_bytes": 1},
        ])
        proc = self._run(str(m))
        assert proc.returncode != 0
        assert proc.stderr != ""

    def test_cli_attachment_in_storage_plan(self, tmp_path):
        meta = _write_meta(tmp_path)
        attach = tmp_path / "msg.txt"
        attach.write_bytes(b"hello")
        m = _write_manifest(tmp_path, [
            {"file_ref": "f_001", "filename": "meta.json", "abs_path": str(meta), "size_bytes": 10},
            {"file_ref": "f_002", "filename": "msg.txt", "abs_path": str(attach), "size_bytes": 5},
        ])
        proc = self._run(str(m))
        assert proc.returncode == 0
        result = json.loads(proc.stdout)
        plan_refs = [e["file_ref"] for e in result["local_file_storage_plan"]["files"]]
        assert "f_002" in plan_refs
        assert "f_001" not in plan_refs
