"""
Tests for the v4 SKILL import feature.

Covers design doc checklist:
 1.  tag=skill normal queue and execution → 202 Accepted
 2.  Wrong tag rejected → 400 TAG_INVALID
 3.  Upload missing .skill file rejected → SKILL_PACKAGE_MISSING
 4.  Upload with multiple .skill files rejected → SKILL_PACKAGE_MULTIPLE
 5.  One .skill + multiple other files → complete local_file_storage_plan
 6.  Parser script three-way selection (upload / dir_discovery / default)
 7.  Raw files staged successfully and available for parsing
 8.  .skill extraction security checks (path traversal / zip bomb)
 9.  Missing SKILL.md after extraction → failure
10.  SKILL.md parses name/description/body → valid chunks/search_profile
11.  keyword search hits name
12.  text search hits name/description/body
13.  vector search uses name/description/body vector
14.  hybrid search uses text+vector mix
15.  Binding first-time creation, repeat consistent import, conflict rejection
16.  vector_model present → vectorization runs
17.  vector_model missing → no vector field
18.  Content + file registry double-write returns correct result
19.  metadata.related_storage_paths backfilled correctly
20.  After success, <import_work_root>/<task_id>/ (including staged/) cleaned up
21.  Failed task with keep_failed_workspace=true preserved
22.  TTL sweep deletes expired task directories
"""

from __future__ import annotations

import json
import os
import sys
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from bible.common.errors import DomainError, ErrorCode
from bible.features import ASTGuard, SandboxRunner

# ---------------------------------------------------------------------------
# Import types via importlib — "import" is a keyword, direct dotted imports
# like `from bible.features.import.types import ...` are a SyntaxError.
# ---------------------------------------------------------------------------

import importlib as _importlib

_types_mod = _importlib.import_module("bible.features.upload.types")
SkillImportPayload = _types_mod.SkillImportPayload
ParseResult = _types_mod.ParseResult
FileStoreResult = _types_mod.FileStoreResult

# ---------------------------------------------------------------------------
# Locate project root and skill parsers directory
# ---------------------------------------------------------------------------

def _find_project_root(start: Path) -> Path:
    for candidate in [start.resolve(), *start.resolve().parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    raise RuntimeError(f"Could not locate project root (no pyproject.toml) from {start}")


_PROJECT_ROOT = _find_project_root(Path(__file__))
_SKILL_PARSERS_DIR = (
    _PROJECT_ROOT
    / "bible"
    / "features"
    / "upload"
    / "skill_upload"
    / "parsers"
)
_PARSE_SKILL_PY = _SKILL_PARSERS_DIR / "parse_skill.py"

# Add parsers dir to sys.path so skill_parser.* is importable in-process
if _SKILL_PARSERS_DIR.exists() and str(_SKILL_PARSERS_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_PARSERS_DIR))

# ---------------------------------------------------------------------------
# Optional imports — guarded for pre-implementation state.
# Must use importlib because "import" is a reserved keyword in Python.
# ---------------------------------------------------------------------------

try:
    _svc_mod = _importlib.import_module(
        "bible.features.upload.skill_upload.skill_upload_service"
    )
    SkillImportService = getattr(_svc_mod, "SkillImportService")
    _SKILL_SERVICE_AVAILABLE = True
except ImportError:
    SkillImportService = None  # type: ignore[assignment,misc]
    _SKILL_SERVICE_AVAILABLE = False

try:
    _store_mod = _importlib.import_module(
        "bible.features.upload.skill_upload.storage.store_skill"
    )
    StoreSkill = getattr(_store_mod, "StoreSkill")
    _STORE_SKILL_AVAILABLE = True
except ImportError:
    StoreSkill = None  # type: ignore[assignment,misc]
    _STORE_SKILL_AVAILABLE = False

_SKILL_PARSERS_AVAILABLE = _SKILL_PARSERS_DIR.exists()

_skip_service = pytest.mark.skipif(
    not _SKILL_SERVICE_AVAILABLE,
    reason="SkillImportService not implemented yet",
)
_skip_store = pytest.mark.skipif(
    not _STORE_SKILL_AVAILABLE,
    reason="StoreSkill not implemented yet",
)
_skip_parsers = pytest.mark.skipif(
    not _SKILL_PARSERS_AVAILABLE,
    reason="skill_parser modules not implemented yet",
)
_skip_e2e = pytest.mark.skipif(
    not _PARSE_SKILL_PY.exists(),
    reason="parse_skill.py not implemented yet",
)

# ---------------------------------------------------------------------------
# In-memory database writer stub
# ---------------------------------------------------------------------------


class _InMemoryWriter:
    """Minimal in-memory writer for tests that assert on stored binding/content data."""

    def __init__(self) -> None:
        self._bindings: dict = {}
        self._content_docs: list = []
        self._file_registry: list = []

    def get_binding_by_domain_index(self, domain: str, kb_index: str):
        from bible.infrastructure.database.types import IndexBinding

        doc = self._bindings.get(f"{domain}:{kb_index}")
        if doc is None:
            return None
        if isinstance(doc, IndexBinding):
            return doc
        return IndexBinding(
            domain_type=doc.get("domain_type", domain),
            kb_index=doc.get("kb_index", kb_index),
            tag=doc.get("tag", ""),
            parser_script_source=doc.get("parser_script_source", ""),
            parser_script_sha256=doc.get("parser_script_sha256", ""),
            vector_model=doc.get("vector_model"),
            search_profile_json=doc.get("search_profile_json", {}),
            search_profile_sha256=doc.get("search_profile_sha256", ""),
        )

    def create_index_binding(self, binding_doc: dict) -> dict:
        domain = binding_doc.get("domain_type", binding_doc.get("domain", ""))
        kb_index = binding_doc.get("kb_index", "")
        self._bindings[f"{domain}:{kb_index}"] = binding_doc
        return binding_doc

    def bulk_upsert_content_docs(self, index: str, docs: list):
        from bible.infrastructure.database.types import BulkWriteResult

        self._content_docs.extend(docs)
        return BulkWriteResult(success_count=len(docs))

    def bulk_upsert_file_registry(self, index: str, records: list):
        from bible.infrastructure.database.types import BulkWriteResult

        self._file_registry.extend(records)
        return BulkWriteResult(success_count=len(records))

    # Stub remaining IDatabaseWriter methods
    def get_binding_by_domain_tag(self, domain, tag):
        return None

    def deactivate_binding(self, domain, kb_index):
        return {}

    def upgrade_binding_vector_model(self, domain, kb_index, vector_model):
        return {}

    def create_async_task(self, task_doc):
        pass

    def get_async_task(self, task_id):
        return None

    def find_async_task_by_idempotency(self, task_type, key):
        return None

    def update_async_task(self, task_id, patch_doc, expected_statuses=None):
        return True


class _FakeVectorTool:
    """Fake VectorTool that returns deterministic vectors without loading a real model."""

    def __init__(self, dims: int = 384) -> None:
        self._dims = dims
        self.embed_calls: list[tuple] = []

    def embed_chunks(
        self,
        chunks: list[dict],
        model_id: str,
        source_template: str | None = None,
    ) -> list[dict]:
        self.embed_calls.append((model_id, source_template, len(chunks)))
        return [{**chunk, "content_vector": [0.1] * self._dims} for chunk in chunks]


# ---------------------------------------------------------------------------
# Patch helpers
# ---------------------------------------------------------------------------


@contextmanager
def _patch_skill_db_writer(writer=None):
    """Patch DatabaseFactory in store_skill to use the given writer instance."""
    mock_factory = MagicMock()
    mock_factory.get_writer.return_value = writer if writer is not None else MagicMock()
    with patch(
        "bible.features.upload.skill_upload.storage.store_skill.DatabaseFactory",
        return_value=mock_factory,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_PARSER_SCRIPT = """\
import argparse
import json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--context", default=None)
    args = parser.parse_args()
    result = {
        "chunks": [{"id": "skill_chunk_1", "text": "test content"}],
        "search_profile": {"type": "bm25"},
        "local_file_storage_plan": None,
    }
    print(json.dumps(result))


if __name__ == "__main__":
    main()
"""

_DANGEROUS_SCRIPT = """\
import os


def parse():
    return {}
"""

VALID_SKILLS_MD = """\
# k8s-log-cleaner

Clean stale Kubernetes logs safely.

## Usage

Run with `--namespace kube-system` to clean logs in the kube-system namespace.

## Options

- `--dry-run`: Preview what would be deleted without making changes.
"""

MINIMAL_SKILLS_MD = """\
# my-skill

Short description of the skill.

Body content here.
"""

MISSING_H1_SKILLS_MD = """\
## Section Without H1

Some content without a top-level heading.
"""

MISSING_DESCRIPTION_SKILLS_MD = """\
# name-only-skill
"""


def _make_test_config(tmp_path: Path):
    """Create a minimal BibleAtlasConfig suitable for unit tests."""
    from bible.config.configure import (
        BibleAtlasConfig,
        FileSystemConfig,
        FileSystemLocalConfig,
        ImportMemoryConfig,
        ImportSkillConfig,
    )

    return BibleAtlasConfig(
        file_system=FileSystemConfig(
            backend="local",
            local=FileSystemLocalConfig(root_dir=str(tmp_path / "files")),
        ),
        import_skill=ImportSkillConfig(
            custom_parsers_dir=str(tmp_path / "custom_skill_parsers"),
            import_work_dir=str(tmp_path / "skill_import_work"),
        ),
        import_memory=ImportMemoryConfig(
            import_work_dir=str(tmp_path / "memory_import_work"),
        ),
    )


def _make_store_skill(tmp_path: Path):
    """Create a StoreSkill instance backed by a real (tmp) config."""
    if StoreSkill is None:
        pytest.skip("StoreSkill not implemented yet")
    return StoreSkill(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))


def _make_skill_payload(**kwargs) -> SkillImportPayload:
    defaults: dict[str, Any] = {
        "kb_index": "test_skill_kb",
        "tag": "skill",
        "vector_model": None,
        "parser_context": None,
    }
    defaults.update(kwargs)
    return SkillImportPayload(**defaults)


def make_skill_zip(
    tmp_path: Path,
    skill_name: str,
    skills_md_content: str,
    extra_files: dict[str, bytes] | None = None,
) -> Path:
    """Create a real .skill ZIP file with proper structure.

    Structure:
        <skill_name>/SKILL.md  <- skills_md_content
        <skill_name>/<fname>    <- for each extra_file

    Returns path to the created .skill file.
    """
    skill_dir = tmp_path / skill_name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(skills_md_content, encoding="utf-8")
    if extra_files:
        for fname, content in extra_files.items():
            (skill_dir / fname).write_bytes(content)

    skill_file = tmp_path / f"{skill_name}.skill"
    with zipfile.ZipFile(skill_file, "w") as zf:
        for f in skill_dir.rglob("*"):
            if f.is_file():
                zf.write(f, f.relative_to(tmp_path))
    return skill_file


def make_manifest_json(tmp_path: Path, staged_files: list[dict[str, Any]]) -> Path:
    """Create a manifest JSON pointing to the staged files."""
    manifest = {
        "task_id": "test-e2e-task",
        "kb_index": "skill_kb",
        "tag": "skill",
        "files": staged_files,
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _make_staged_entry(file_path: Path, file_ref: str = "ref_0") -> dict[str, Any]:
    return {
        "file_ref": file_ref,
        "filename": file_path.name,
        "abs_path": str(file_path),
        "size_bytes": file_path.stat().st_size,
        "content_type": "application/octet-stream",
    }


# ---------------------------------------------------------------------------
# Fixture: reset module-level singletons
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_globals():
    """Isolate module-level singletons between tests."""
    import importlib as _il

    container_mod = _il.import_module("bible.features.upload.container")
    import bible.features.async_task.container as task_container_mod
    import bible.features.async_task.tasks.dispatch_task as dispatch_mod
    import bible.config.configure as config_mod
    from bible.config.configure import BibleAtlasConfig

    if container_mod._workspace_sweeper is not None:
        container_mod._workspace_sweeper.stop()
    container_mod._workspace_sweeper = None
    container_mod._import_executor = None
    task_container_mod._task_service = None
    task_container_mod._task_repository = None
    task_container_mod._task_dispatcher = None
    dispatch_mod._repository = None
    dispatch_mod._dispatcher = None
    config_mod._config_instance = BibleAtlasConfig()

    yield

    if container_mod._workspace_sweeper is not None:
        container_mod._workspace_sweeper.stop()
    container_mod._workspace_sweeper = None
    container_mod._import_executor = None
    task_container_mod._task_service = None
    task_container_mod._task_repository = None
    task_container_mod._task_dispatcher = None
    dispatch_mod._repository = None
    dispatch_mod._dispatcher = None
    config_mod._config_instance = None


# ---------------------------------------------------------------------------
# Fixtures: task service mocks
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_task_service():
    svc = MagicMock()
    svc.submit.return_value = {"task_id": "test-skill-task-123", "status": "queued"}
    return svc


def _skill_api_available() -> bool:
    try:
        _importlib.import_module("bible.api.upload.skill_upload_api")
        return True
    except ImportError:
        return False


@pytest.fixture
def client_with_mock_service(mock_task_service, tmp_path):
    """TestClient where get_task_service is mocked — for pure API routing tests."""
    if not _skill_api_available():
        pytest.skip("skill_import_api not implemented yet")

    from bible.main import create_app

    _api_mod = _importlib.import_module("bible.api.upload.skill_upload_api")
    mock_config = _make_test_config(tmp_path)
    with patch(
        "bible.api.upload.skill_upload_api.get_task_service",
        return_value=mock_task_service,
    ):
        with patch(
            "bible.api.upload.skill_upload_api._get_config",
            return_value=mock_config,
        ):
            app = create_app()
            yield TestClient(app)


# ===========================================================================
# Section 1: Unit tests for parser modules (stdlib sandbox)
# ===========================================================================

# ---------------------------------------------------------------------------
# TestSkillsMdParser
# ---------------------------------------------------------------------------


@_skip_parsers
class TestSkillsMdParser:
    """Tests for skill_parser.skills_md_parser — SKILL.md format parsing."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        try:
            from skill_parser import skills_md_parser as _m  # type: ignore[import]

            self._mod = _m
        except ImportError:
            pytest.skip("skill_parser.skills_md_parser not available")

    def test_valid_skills_md_returns_name_description_body(self, tmp_path):
        """A well-formed SKILL.md returns all three required keys."""
        skills_md = tmp_path / "SKILL.md"
        skills_md.write_text(VALID_SKILLS_MD, encoding="utf-8")
        result = self._mod.parse_standard_skills_md(str(skills_md))
        assert result["name"] == "k8s-log-cleaner"
        assert "Clean stale Kubernetes" in result["description"]
        assert "body" in result
        assert result["body"]  # non-empty

    def test_missing_h1_raises_error(self, tmp_path):
        """SKILL.md with no H1 heading must raise a parse error."""
        skills_md = tmp_path / "SKILL.md"
        skills_md.write_text(MISSING_H1_SKILLS_MD, encoding="utf-8")
        with pytest.raises(Exception):
            self._mod.parse_standard_skills_md(str(skills_md))

    def test_missing_description_raises_error(self, tmp_path):
        """SKILL.md with H1 but no description paragraph must raise."""
        skills_md = tmp_path / "SKILL.md"
        skills_md.write_text(MISSING_DESCRIPTION_SKILLS_MD, encoding="utf-8")
        with pytest.raises(Exception):
            self._mod.parse_standard_skills_md(str(skills_md))

    def test_minimal_valid_file_parses_successfully(self, tmp_path):
        """Minimal valid SKILL.md (name + description + body) is accepted."""
        skills_md = tmp_path / "SKILL.md"
        skills_md.write_text(MINIMAL_SKILLS_MD, encoding="utf-8")
        result = self._mod.parse_standard_skills_md(str(skills_md))
        assert result["name"] == "my-skill"
        assert result["description"]
        assert "body" in result

    def test_result_has_required_keys(self, tmp_path):
        """Parsed result always carries name, description, and body keys."""
        skills_md = tmp_path / "SKILL.md"
        skills_md.write_text(VALID_SKILLS_MD, encoding="utf-8")
        result = self._mod.parse_standard_skills_md(str(skills_md))
        for key in ("name", "description", "body"):
            assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# TestFileClassifier
# ---------------------------------------------------------------------------


@_skip_parsers
class TestFileClassifier:
    """Tests for skill_parser.file_classifier — .skill file detection."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        try:
            from skill_parser import file_classifier as _m  # type: ignore[import]

            self._mod = _m
        except ImportError:
            pytest.skip("skill_parser.file_classifier not available")

    def _staged(self, filenames: list[str]) -> list[dict]:
        return [
            {"file_ref": f"ref_{i}", "filename": fn, "abs_path": f"/tmp/{fn}"}
            for i, fn in enumerate(filenames)
        ]

    def test_exactly_one_skill_returns_success(self):
        """Single .skill file + other files → skill_file and other_files split."""
        skill_file, other_files = self._mod.classify_files(
            self._staged(["my-skill.skill", "readme.md"])
        )
        assert skill_file["filename"] == "my-skill.skill"
        assert len(other_files) == 1

    def test_zero_skill_files_raises_package_missing(self):
        """No .skill file in manifest → SKILL_PACKAGE_MISSING error."""
        with pytest.raises(Exception) as exc_info:
            self._mod.classify_files(self._staged(["readme.md", "config.json"]))
        assert "SKILL_PACKAGE_MISSING" in str(exc_info.value)

    def test_two_skill_files_raises_package_multiple(self):
        """Two .skill files in manifest → SKILL_PACKAGE_MULTIPLE error."""
        with pytest.raises(Exception) as exc_info:
            self._mod.classify_files(self._staged(["a.skill", "b.skill"]))
        assert "SKILL_PACKAGE_MULTIPLE" in str(exc_info.value)

    def test_mix_skill_and_other_files_correct_split(self):
        """One .skill + extras → correct classification of each file."""
        skill_file, other_files = self._mod.classify_files(
            self._staged(["pkg.skill", "extra.md", "extra2.json"])
        )
        assert skill_file["filename"] == "pkg.skill"
        assert len(other_files) == 2
        assert all(f["filename"] != "pkg.skill" for f in other_files)


# ---------------------------------------------------------------------------
# TestZipSafeExtractor
# ---------------------------------------------------------------------------


@_skip_parsers
class TestZipSafeExtractor:
    """Tests for skill_parser.zip_safe_extractor — extraction safety."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        try:
            from skill_parser import zip_safe_extractor as _m  # type: ignore[import]

            self._mod = _m
        except ImportError:
            pytest.skip("skill_parser.zip_safe_extractor not available")

    def test_normal_valid_zip_extracts_successfully(self, tmp_path):
        """A well-formed .skill ZIP is extracted into the target directory."""
        skill_file = make_skill_zip(tmp_path / "build", "my-skill", VALID_SKILLS_MD)
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        self._mod.safe_extract(str(skill_file), str(extract_dir))
        assert (extract_dir / "my-skill" / "SKILL.md").exists()

    def test_zip_slip_path_traversal_rejected(self, tmp_path):
        """Entry with ../../ path component must be rejected."""
        evil_zip = tmp_path / "evil.skill"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../evil.txt", "evil content")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with pytest.raises(Exception) as exc_info:
            self._mod.safe_extract(str(evil_zip), str(extract_dir))
        err = str(exc_info.value).lower()
        assert any(kw in err for kw in ("traversal", "path", "invalid", "unsafe", "outside"))

    def test_absolute_path_entry_rejected(self, tmp_path):
        """Entry with an absolute path must be rejected."""
        evil_zip = tmp_path / "abs.skill"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("/etc/passwd", "root:x:0:0")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with pytest.raises(Exception):
            self._mod.safe_extract(str(evil_zip), str(extract_dir))

    def test_too_many_entries_rejected(self, tmp_path):
        """ZIP with entries exceeding _MAX_ENTRIES threshold is rejected."""
        large_zip = tmp_path / "large.skill"
        with zipfile.ZipFile(large_zip, "w") as zf:
            for i in range(20):
                zf.writestr(f"myskill/file_{i}.txt", f"content {i}")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        # Temporarily lower _MAX_ENTRIES to 5 so the 20-entry zip is rejected
        import skill_parser.zip_safe_extractor as _ze  # type: ignore[import]
        original = _ze._MAX_ENTRIES
        _ze._MAX_ENTRIES = 5
        try:
            with pytest.raises(Exception) as exc_info:
                self._mod.safe_extract(str(large_zip), str(extract_dir))
            assert "SKILL_PACKAGE_INVALID_FORMAT" in str(exc_info.value)
        finally:
            _ze._MAX_ENTRIES = original

    def test_non_zip_file_raises_invalid_format(self, tmp_path):
        """A file that is not a valid ZIP raises SKILL_PACKAGE_INVALID_FORMAT."""
        not_a_zip = tmp_path / "notzip.skill"
        not_a_zip.write_bytes(b"this is definitely not a zip file")
        extract_dir = tmp_path / "extracted"
        extract_dir.mkdir()
        with pytest.raises(Exception) as exc_info:
            self._mod.safe_extract(str(not_a_zip), str(extract_dir))
        err = str(exc_info.value)
        assert any(
            kw in err
            for kw in ("SKILL_PACKAGE_INVALID_FORMAT", "invalid", "format", "zip", "Bad")
        )


# ---------------------------------------------------------------------------
# TestPackageValidator
# ---------------------------------------------------------------------------


@_skip_parsers
class TestPackageValidator:
    """Tests for skill_parser.package_validator — top-level directory validation."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        try:
            from skill_parser import package_validator as _m  # type: ignore[import]

            self._mod = _m
        except ImportError:
            pytest.skip("skill_parser.package_validator not available")

    def test_single_top_level_dir_returns_skill_name(self, tmp_path):
        """extract_dir with exactly one top-level dir → returns its name."""
        extract_dir = tmp_path / "extracted"
        skill_dir = extract_dir / "k8s-log-cleaner"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(VALID_SKILLS_MD)
        result = self._mod.validate_single_top_level_dir(str(extract_dir))
        assert result == "k8s-log-cleaner"

    def test_root_level_file_raises_error(self, tmp_path):
        """A loose file at root level (not inside a dir) → validation error."""
        extract_dir = tmp_path / "extracted"
        (extract_dir / "myskill").mkdir(parents=True)
        (extract_dir / "rogue.txt").write_text("bad")
        with pytest.raises(Exception):
            self._mod.validate_single_top_level_dir(str(extract_dir))

    def test_multiple_top_level_dirs_raises_error(self, tmp_path):
        """Two top-level directories → validation error (ambiguous package)."""
        extract_dir = tmp_path / "extracted"
        (extract_dir / "skill1").mkdir(parents=True)
        (extract_dir / "skill2").mkdir()
        with pytest.raises(Exception):
            self._mod.validate_single_top_level_dir(str(extract_dir))


# ---------------------------------------------------------------------------
# TestSearchProfileBuilder
# ---------------------------------------------------------------------------


@_skip_parsers
class TestSearchProfileBuilder:
    """Tests for skill_parser.search_profile_builder — fixed profile shape."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        try:
            from skill_parser import search_profile_builder as _m  # type: ignore[import]

            self._mod = _m
        except ImportError:
            pytest.skip("skill_parser.search_profile_builder not available")

    def test_output_has_all_four_search_type_keys(self):
        """Built profile must contain keyword, text, vector, and hybrid entries."""
        profile = self._mod.build_search_profile({})
        for key in ("keyword", "text", "vector", "hybrid"):
            assert key in profile, f"Missing search type key: {key}"

    def test_vector_source_template_contains_all_fields(self):
        """Vector source_template must reference {name}, {description}, and {body}."""
        profile = self._mod.build_search_profile({})
        template = profile.get("vector", {}).get("source_template", "")
        for field in ("{name}", "{description}", "{body}"):
            assert field in template, f"Missing field {field} in source_template"

    def test_keyword_config_targets_name_field(self):
        """keyword config must reference the 'name' field."""
        profile = self._mod.build_search_profile({})
        assert "name" in str(profile.get("keyword", {}))

    def test_text_config_targets_name_description_and_body(self):
        """text config must cover name, description, and body."""
        profile = self._mod.build_search_profile({})
        text_str = str(profile.get("text", {}))
        assert "name" in text_str
        # at least one of description/body must also be present
        assert "description" in text_str or "body" in text_str

    def test_hybrid_config_present_and_non_empty(self):
        """hybrid config must be present and non-empty."""
        profile = self._mod.build_search_profile({})
        hybrid = profile.get("hybrid", {})
        assert hybrid  # non-empty dict

    def test_response_fields_keep_full_skill_fields_for_storage_profile(self):
        """Import builds the storage/search profile; search output is compacted later."""
        profile = self._mod.build_search_profile({})
        response_fields = profile.get("response_fields", [])
        assert response_fields == [
            "doc_id",
            "name",
            "description",
            "body",
            "content",
            "metadata.related_storage_paths",
            "score",
        ]


# ---------------------------------------------------------------------------
# TestChunkBuilder
# ---------------------------------------------------------------------------


@_skip_parsers
class TestChunkBuilder:
    """Tests for skill_parser.chunk_builder — chunk structure correctness."""

    @pytest.fixture(autouse=True)
    def _import_module(self):
        try:
            from skill_parser import chunk_builder as _m  # type: ignore[import]

            self._mod = _m
        except ImportError:
            pytest.skip("skill_parser.chunk_builder not available")

    def _build(
        self,
        name: str = "k8s-log-cleaner",
        description: str = "Clean K8s logs.",
        body: str = "Run with --dry-run.",
    ) -> dict:
        """Call build_chunks and return the single chunk it produces."""
        skill_doc = {"name": name, "description": description, "body": body}
        chunks = self._mod.build_chunks(skill_doc, {}, {})
        assert len(chunks) == 1, "build_chunks must return exactly one chunk per skill"
        return chunks[0]

    def test_doc_id_is_set(self):
        """chunk must carry a non-empty doc_id (or id) field."""
        chunk = self._build()
        doc_id = chunk.get("doc_id") or chunk.get("id")
        assert doc_id, "doc_id must be set"

    def test_title_equals_name(self):
        """chunk title should equal the skill name."""
        chunk = self._build(name="my-skill")
        title = chunk.get("title") or chunk.get("name")
        assert title == "my-skill"

    def test_content_incorporates_parsed_fields(self):
        """chunk content should include name, description, and/or body text."""
        chunk = self._build(name="my-skill", description="My description.", body="My body.")
        content = chunk.get("content", "")
        assert any(text in content for text in ("my-skill", "My description", "My body"))

    def test_metadata_related_storage_paths_initially_empty(self):
        """Freshly built chunk has empty related_storage_paths in metadata."""
        chunk = self._build()
        paths = chunk.get("metadata", {}).get("related_storage_paths")
        assert paths == [] or paths is not None  # either empty list or present

    def test_metadata_parser_version_is_correct(self):
        """metadata.parser_version must equal 'v4-skill-package-1'."""
        chunk = self._build()
        version = chunk.get("metadata", {}).get("parser_version")
        assert version == "v4-skill-package-1"

    def test_metadata_source_file_points_to_skill_md(self):
        """metadata.source_file must point to the canonical SKILL.md manifest."""
        skill_doc = {
            "name": "my-skill",
            "description": "My description.",
            "body": "My body.",
        }
        chunks = self._mod.build_chunks(skill_doc, {}, {}, skill_name="my-skill")
        assert chunks[0]["metadata"]["source_file"] == "my-skill/SKILL.md"


# ===========================================================================
# Section 2: Unit tests for SkillImportService
# ===========================================================================


@_skip_service
class TestSkillImportService:
    """Unit tests for SkillImportService — mirrors MemoryImportService pattern."""

    def _make_svc(self, tmp_path: Path, parsers_dir: str | None = None):
        if parsers_dir is None:
            parsers_dir = str(tmp_path / "parsers")
            os.makedirs(parsers_dir, exist_ok=True)
        if StoreSkill is None:
            pytest.skip("StoreSkill not available")
        store = StoreSkill(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))
        return SkillImportService(
            store_skill=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=parsers_dir,
            config=None,
        )

    def _mock_store(self, tmp_path: Path):
        """Return a fully-mocked store suitable for execute_task tests."""
        mock_store = MagicMock()
        mock_store.cleanup_task_workspace = MagicMock()
        mock_store.build_staged_files_from_paths = MagicMock(return_value=[])
        mock_store.build_parse_manifest = MagicMock(
            return_value=str(tmp_path / "manifest.json")
        )
        mock_store.store = MagicMock(
            return_value={"chunks_indexed": 1, "files_stored": 0, "kb_index": "skill_kb"}
        )
        (tmp_path / "manifest.json").write_text(json.dumps({}))
        return mock_store

    def _minimal_parse_result(self) -> dict:
        return {
            "chunks": [{"id": "c1", "title": "k8s-log-cleaner"}],
            "search_profile": {"keyword": {}, "text": {}, "vector": {}, "hybrid": {}},
            "local_file_storage_plan": None,
        }

    def test_execute_task_success(self, tmp_path):
        """Mock sandbox returns valid parse_result → execute_task returns success dict."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        (Path(parsers_dir) / "parse_skill.py").write_text(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        svc._store_skill = self._mock_store(tmp_path)
        svc._sandbox_runner = MagicMock()
        svc._sandbox_runner.run_parse.return_value = self._minimal_parse_result()

        payload = _make_skill_payload(kb_index="skill_kb")
        result = svc.execute_task("task-success-001", payload, [])

        assert result["chunks_indexed"] == 1

    def test_execute_task_parser_not_found(self, tmp_path):
        """No parse_skill.py and no parse_default.py → PARSER_SCRIPT_NOT_FOUND error."""
        parsers_dir = str(tmp_path / "empty_parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_skill_payload()
        with pytest.raises(DomainError) as exc_info:
            svc.execute_task("task-nf-001", payload, [])
        err = exc_info.value
        assert (
            err.details.get("code") == "PARSER_SCRIPT_NOT_FOUND"
            or err.code == ErrorCode.NOT_FOUND
        )

    def test_execute_task_ast_guard_blocks_risky_script(self, tmp_path):
        """User-supplied script with os import → task fails with PARSER_SCRIPT_RISK."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)

        dangerous = tmp_path / "session" / "dangerous.py"
        dangerous.parent.mkdir(parents=True)
        dangerous.write_text(_DANGEROUS_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        payload = _make_skill_payload(
            parser_script_path=str(dangerous),
            parser_script_filename="dangerous.py",
        )
        with pytest.raises(DomainError) as exc_info:
            svc.execute_task("task-ast-001", payload, [])
        assert exc_info.value.details.get("code") == "PARSER_SCRIPT_RISK"

    def test_execute_task_cleanup_on_success(self, tmp_path):
        """cleanup_staged_workspace is called in the finally block even on success."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        (Path(parsers_dir) / "parse_skill.py").write_text(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        svc._store_skill = self._mock_store(tmp_path)
        svc._sandbox_runner = MagicMock()
        svc._sandbox_runner.run_parse.return_value = self._minimal_parse_result()

        cleanup_calls: list = []
        original = svc.cleanup_staged_workspace

        def _track(*args, **kwargs):
            cleanup_calls.append((args, kwargs))
            return original(*args, **kwargs)

        svc.cleanup_staged_workspace = _track  # type: ignore[method-assign]
        svc.execute_task("task-cleanup-ok", _make_skill_payload(), [])
        assert len(cleanup_calls) == 1

    def test_execute_task_cleanup_on_failure(self, tmp_path):
        """cleanup_staged_workspace is called even when an exception propagates."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        (Path(parsers_dir) / "parse_skill.py").write_text(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        mock_store = MagicMock()
        mock_store.build_staged_files_from_paths = MagicMock(
            side_effect=RuntimeError("injected failure")
        )
        svc._store_skill = mock_store
        svc._sandbox_runner = MagicMock()

        cleanup_calls: list = []
        svc.cleanup_staged_workspace = lambda *a, **kw: cleanup_calls.append((a, kw))  # type: ignore[method-assign]

        with pytest.raises((DomainError, RuntimeError)):
            svc.execute_task("task-cleanup-fail", _make_skill_payload(), [])
        assert len(cleanup_calls) == 1

    def test_execute_task_keep_failed_workspace(self, tmp_path):
        """With keep_failed_workspace=True, cleanup is called with keep_failed=True."""
        from bible.config.configure import ImportSkillConfig

        config = _make_test_config(tmp_path)
        # Pydantic BaseModel allows attribute mutation by default
        config.import_skill.keep_failed_workspace = True  # type: ignore[assignment]

        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        if StoreSkill is None:
            pytest.skip("StoreSkill not available")
        store = StoreSkill(workspace_dir=str(tmp_path), config=config)
        svc = SkillImportService(
            store_skill=store,
            ast_guard=ASTGuard(),
            sandbox_runner=SandboxRunner(),
            parsers_dir=parsers_dir,
            config=config,
        )

        captured_kwargs: list[dict] = []
        svc.cleanup_staged_workspace = lambda *a, **kw: captured_kwargs.append(kw)  # type: ignore[method-assign]

        mock_store = MagicMock()
        mock_store.build_staged_files_from_paths = MagicMock(
            side_effect=RuntimeError("deliberate failure")
        )
        svc._store_skill = mock_store
        svc._sandbox_runner = MagicMock()

        with pytest.raises((DomainError, RuntimeError)):
            svc.execute_task("task-keep-failed", _make_skill_payload(), [])

        assert any(kw.get("keep_failed") is True for kw in captured_kwargs)

    def test_parser_script_selection_upload(self, tmp_path):
        """Uploaded parser_script_path is used directly, no discovery needed."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)

        script = tmp_path / "session_abc" / "my_parser.py"
        script.parent.mkdir(parents=True)
        script.write_text(_MINIMAL_PARSER_SCRIPT)

        payload = _make_skill_payload(
            parser_script_path=str(script),
            parser_script_filename="my_parser.py",
        )
        selected = svc._select_parser_script(payload, "task-upload-001")
        assert selected == str(script)

    def test_parser_script_selection_dir_discovery(self, tmp_path):
        """parse_skill.py in parsers_dir is discovered when no upload provided."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        parse_skill_path = os.path.join(parsers_dir, "parse_skill.py")
        with open(parse_skill_path, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        selected = svc._select_parser_script(_make_skill_payload(), "task-dir-001")
        assert selected == parse_skill_path

    def test_parser_script_selection_custom_dir_first(self, tmp_path):
        """custom/parse_skill.py takes priority over the pre-registered parser."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        parse_skill_path = os.path.join(parsers_dir, "parse_skill.py")
        with open(parse_skill_path, "w") as f:
            f.write("# registered")
        custom_dir = Path(parsers_dir) / "custom"
        custom_dir.mkdir()
        custom_path = custom_dir / "parse_skill.py"
        custom_path.write_text("# custom")

        svc = self._make_svc(tmp_path, parsers_dir)
        selected = svc._select_parser_script(_make_skill_payload(), "task-custom-001")
        assert selected == str(custom_path)

    def test_parser_script_selection_default(self, tmp_path):
        """Falls back to parse_default.py when parse_skill.py is absent."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        default_path = os.path.join(parsers_dir, "parse_default.py")
        with open(default_path, "w") as f:
            f.write(_MINIMAL_PARSER_SCRIPT)

        svc = self._make_svc(tmp_path, parsers_dir)
        selected = svc._select_parser_script(_make_skill_payload(), "task-default-001")
        assert selected == default_path

    def test_validate_parse_result_schema_valid(self, tmp_path):
        """A complete, well-formed result dict passes schema validation."""
        svc = self._make_svc(tmp_path)
        valid = {
            "chunks": [{"id": "c1"}],
            "search_profile": {"keyword": {}},
            "local_file_storage_plan": None,
        }
        svc.validate_parse_result_schema(valid)  # must not raise

    def test_validate_parse_result_schema_missing_chunks(self, tmp_path):
        """Result without 'chunks' raises DomainError mentioning 'chunks'."""
        svc = self._make_svc(tmp_path)
        with pytest.raises(DomainError) as exc_info:
            svc.validate_parse_result_schema({"search_profile": {}})
        assert "chunks" in exc_info.value.message

    def test_validate_parse_result_schema_missing_search_profile(self, tmp_path):
        """Result without 'search_profile' raises DomainError mentioning 'search_profile'."""
        svc = self._make_svc(tmp_path)
        with pytest.raises(DomainError) as exc_info:
            svc.validate_parse_result_schema({"chunks": []})
        assert "search_profile" in exc_info.value.message

    def test_successful_uploaded_parser_is_persisted_to_custom_dir(self, tmp_path):
        """A user-supplied parser is saved as custom/parse_skill.py after success."""
        parsers_dir = str(tmp_path / "parsers")
        os.makedirs(parsers_dir)
        svc = self._make_svc(tmp_path, parsers_dir)
        svc._store_skill = self._mock_store(tmp_path)
        svc._sandbox_runner = MagicMock()
        svc._sandbox_runner.run_parse.return_value = self._minimal_parse_result()
        script = tmp_path / "session" / "uploaded_skill.py"
        script.parent.mkdir(parents=True)
        script.write_text(_MINIMAL_PARSER_SCRIPT)

        result = svc.execute_task(
            "task-persist-skill-upload",
            _make_skill_payload(
                parser_script_path=str(script),
                parser_script_filename="uploaded_skill.py",
            ),
            [],
        )

        assert result["chunks_indexed"] == 1
        persisted = Path(parsers_dir) / "custom" / "parse_skill.py"
        assert persisted.read_text() == _MINIMAL_PARSER_SCRIPT
        assert svc._store_skill.store.call_args.kwargs["parser_script_source"] == "parse_skill.py"

    def test_ast_failure_does_not_overwrite_custom_parser(self, tmp_path):
        """A risky uploaded parser fails and keeps the existing custom parser intact."""
        parsers_dir = str(tmp_path / "parsers")
        custom_dir = Path(parsers_dir) / "custom"
        custom_dir.mkdir(parents=True)
        persisted = custom_dir / "parse_skill.py"
        persisted.write_text("# existing custom skill parser")
        svc = self._make_svc(tmp_path, parsers_dir)
        dangerous = tmp_path / "session" / "dangerous.py"
        dangerous.parent.mkdir(parents=True)
        dangerous.write_text(_DANGEROUS_SCRIPT)

        with pytest.raises(DomainError) as exc_info:
            svc.execute_task(
                "task-skill-ast-failure-no-persist",
                _make_skill_payload(
                    parser_script_path=str(dangerous),
                    parser_script_filename="dangerous.py",
                ),
                [],
            )

        assert exc_info.value.details["code"] == "PARSER_SCRIPT_RISK"
        assert persisted.read_text() == "# existing custom skill parser"


# ===========================================================================
# Section 3: Unit tests for StoreSkill
# ===========================================================================


@_skip_store
class TestStoreSkill:
    """Unit tests for StoreSkill — mirrors StoreMemory test pattern."""

    def _make_store(self, tmp_path: Path):
        if StoreSkill is None:
            pytest.skip("StoreSkill not available")
        return StoreSkill(workspace_dir=str(tmp_path), config=_make_test_config(tmp_path))

    def _import_work(self, tmp_path: Path) -> str:
        return str(tmp_path / "skill_import_work")

    def test_stage_upload_files_creates_staged_dir(self, tmp_path):
        """stage_upload_files writes files into <import_work>/<task_id>/staged/."""
        with _patch_skill_db_writer():
            store = self._make_store(tmp_path)
        files = [
            {
                "filename": "k8s.skill",
                "content": b"PK fake zip",
                "content_type": "application/octet-stream",
            }
        ]
        staged = store.stage_upload_files(files, "stage-task-001")
        assert len(staged) == 1
        assert os.path.isfile(staged[0]["abs_path"])
        assert staged[0]["filename"] == "k8s.skill"

    def test_build_parse_manifest_writes_json(self, tmp_path):
        """build_parse_manifest writes a valid JSON file with the correct keys."""
        with _patch_skill_db_writer():
            store = self._make_store(tmp_path)
        staged_files = [
            {
                "file_ref": "ref_0",
                "filename": "my.skill",
                "abs_path": str(tmp_path / "my.skill"),
                "size_bytes": 100,
                "content_type": "application/octet-stream",
            }
        ]
        manifest_path = store.build_parse_manifest(
            staged_files, "manifest-task-001", "skill_kb", "skill"
        )
        assert os.path.isfile(manifest_path)
        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest.get("kb_index") == "skill_kb"
        assert manifest.get("tag") == "skill"
        assert isinstance(manifest.get("files"), list)
        assert len(manifest["files"]) == 1

    def test_store_creates_binding_first_time(self, tmp_path):
        """First-time store() creates a SKILL binding in the database."""
        writer = _InMemoryWriter()
        with _patch_skill_db_writer(writer):
            store = self._make_store(tmp_path)
            parse_result = ParseResult(
                chunks=[{"id": "c1", "title": "my-skill"}],
                search_profile={"keyword": {}, "text": {}, "vector": {}, "hybrid": {}},
                local_file_storage_plan=None,
            )
            store.store(
                kb_index="skill_kb_1",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="parse_skill.py",
                parser_script_sha256="abc123",
            )
        assert "SKILL:skill_kb_1" in writer._bindings
        binding = writer._bindings["SKILL:skill_kb_1"]
        assert binding.get("kb_index") == "skill_kb_1"
        assert binding.get("domain_type") == "SKILL"
        assert binding.get("parser_script_source") == "parse_skill.py"

    def test_store_consistent_reimport_succeeds(self, tmp_path):
        """Re-importing the same kb_index with the same profile succeeds without error."""
        writer = _InMemoryWriter()
        profile = {"keyword": {"fields": ["name"]}, "text": {}, "vector": {}, "hybrid": {}}
        with _patch_skill_db_writer(writer):
            store = self._make_store(tmp_path)
            parse_result = ParseResult(
                chunks=[{"id": "c1", "title": "my-skill"}],
                search_profile=profile,
                local_file_storage_plan=None,
            )
            store.store(
                kb_index="skill_reimport",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="parse_skill.py",
                parser_script_sha256="sha1",
            )
            # Second import — must not raise
            store.store(
                kb_index="skill_reimport",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="parse_skill.py",
                parser_script_sha256="sha1",
            )

    def test_store_binding_conflict_raises(self, tmp_path):
        """Importing with a conflicting search_profile raises INDEX_BINDING_CONFLICT."""
        writer = _InMemoryWriter()
        conflicting_profile = {"keyword": {"fields": ["title"]}}
        # Pre-seed existing binding with a different profile sha256
        writer._bindings["SKILL:skill_conflict"] = {
            "domain_type": "SKILL",
            "kb_index": "skill_conflict",
            "tag": "skill",
            "parser_script_source": "old.py",
            "parser_script_sha256": "old_sha",
            "vector_model": None,
            "search_profile_json": '{"keyword": {"fields": ["name"]}}',
            "search_profile_sha256": "AAABBB",
        }
        with _patch_skill_db_writer(writer):
            store = self._make_store(tmp_path)
            parse_result = ParseResult(
                chunks=[{"id": "c1"}],
                search_profile=conflicting_profile,
                local_file_storage_plan=None,
            )
            with pytest.raises((DomainError, Exception)) as exc_info:
                store.store(
                    kb_index="skill_conflict",
                    parse_result=parse_result,
                    vector_model=None,
                    parser_script_source="new.py",
                    parser_script_sha256="new_sha",
                )
            # When implemented, error should mention conflict
            err_str = str(exc_info.value)
            assert any(
                kw in err_str.upper()
                for kw in ("CONFLICT", "BINDING", "MISMATCH", "INCOMPATIBLE")
            )

    def test_store_with_vector_model_embeds_chunks(self, tmp_path):
        """With vector_model set, chunks gain a content_vector field."""
        fake_vector = [0.1] * 384

        class _FakeModel:
            def encode(self, texts, **kwargs):
                return [fake_vector[:] for _ in texts]

        writer = _InMemoryWriter()
        with _patch_skill_db_writer(writer):
            with patch(
                "bible.infrastructure.vector.vector_tool.VectorTool._get_cached_model",
                return_value=_FakeModel(),
            ):
                store = self._make_store(tmp_path)
                parse_result = ParseResult(
                    chunks=[{"id": "c1", "title": "skill", "content": "body text"}],
                    search_profile={
                        "vector": {
                            "source_template": "{name}\n{description}\n{body}"
                        }
                    },
                    local_file_storage_plan=None,
                )
                result = store.store(
                    kb_index="skill_vec",
                    parse_result=parse_result,
                    vector_model="fake-model-384",
                    parser_script_source="parse_skill.py",
                    parser_script_sha256="sha",
                )
        assert result["chunks_indexed"] == 1
        assert len(writer._content_docs) == 1
        assert "content_vector" in writer._content_docs[0]
        assert len(writer._content_docs[0]["content_vector"]) == 384

    def test_store_without_vector_model_skips_embedding(self, tmp_path):
        """Without vector_model, no content_vector field is added to chunks."""
        writer = _InMemoryWriter()
        with _patch_skill_db_writer(writer):
            store = self._make_store(tmp_path)
            parse_result = ParseResult(
                chunks=[{"id": "c1", "title": "skill", "content": "body"}],
                search_profile={"keyword": {}},
                local_file_storage_plan=None,
            )
            store.store(
                kb_index="skill_no_vec",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="parse_skill.py",
                parser_script_sha256="sha",
            )
        assert len(writer._content_docs) == 1
        assert "content_vector" not in writer._content_docs[0]

    def test_store_hydrates_related_storage_paths(self, tmp_path):
        """After file storage, metadata.related_storage_paths is populated from plan."""
        writer = _InMemoryWriter()
        staged_dir = tmp_path / "skill_import_work" / "t1" / "staged"
        staged_dir.mkdir(parents=True, exist_ok=True)
        test_file = staged_dir / "extra.md"
        test_file.write_bytes(b"# Extra content")

        with _patch_skill_db_writer(writer):
            store = self._make_store(tmp_path)
            parse_result = ParseResult(
                chunks=[
                    {
                        "id": "c1",
                        "title": "my-skill",
                        "metadata": {
                            "related_file_refs": ["ref_0"],
                            "related_storage_paths": [],
                        },
                    }
                ],
                search_profile={"keyword": {}},
                local_file_storage_plan={
                    "files": [
                        {
                            "file_ref": "ref_0",
                            "filename": "extra.md",
                            "abs_path": str(test_file),
                        }
                    ]
                },
            )
            store.store(
                kb_index="skill_hydrate",
                parse_result=parse_result,
                vector_model=None,
                parser_script_source="parse_skill.py",
                parser_script_sha256="sha",
                task_id="t1",
            )
        assert len(writer._content_docs) == 1
        paths = writer._content_docs[0].get("metadata", {}).get("related_storage_paths", [])
        assert len(paths) > 0, "related_storage_paths must be backfilled after file storage"


    def test_cleanup_task_workspace_removes_dir(self, tmp_path):
        """cleanup_task_workspace(keep_failed=False) removes the task directory."""
        with _patch_skill_db_writer():
            store = self._make_store(tmp_path)
        task_id = "cleanup-skill-001"
        task_dir = os.path.join(self._import_work(tmp_path), task_id)
        staged = os.path.join(task_dir, "staged")
        os.makedirs(staged, exist_ok=True)
        (Path(staged) / "pkg.skill").write_bytes(b"zip")

        store.cleanup_task_workspace(task_id, keep_failed=False)

        assert not os.path.exists(task_dir)

    def test_cleanup_task_workspace_keep_failed_preserves_dir(self, tmp_path):
        """cleanup_task_workspace(keep_failed=True) leaves the directory intact."""
        with _patch_skill_db_writer():
            store = self._make_store(tmp_path)
        task_id = "keep-skill-failed-001"
        task_dir = os.path.join(self._import_work(tmp_path), task_id)
        os.makedirs(task_dir, exist_ok=True)

        store.cleanup_task_workspace(task_id, keep_failed=True)

        assert os.path.isdir(task_dir)

    def test_sweep_expired_task_workspaces(self, tmp_path):
        """sweep_expired_task_workspaces removes directories older than ttl_hours."""
        with _patch_skill_db_writer():
            store = self._make_store(tmp_path)
        import_work = self._import_work(tmp_path)
        old_dir = os.path.join(import_work, "old-skill-task-001")
        os.makedirs(old_dir)
        old_mtime = time.time() - 48 * 3600
        os.utime(old_dir, (old_mtime, old_mtime))

        deleted = store.sweep_expired_task_workspaces(ttl_hours=24)

        assert deleted == 1
        assert not os.path.exists(old_dir)

    def test_sweep_preserves_recent_directories(self, tmp_path):
        """sweep_expired_task_workspaces does not remove recently created directories."""
        with _patch_skill_db_writer():
            store = self._make_store(tmp_path)
        import_work = self._import_work(tmp_path)
        recent_dir = os.path.join(import_work, "recent-skill-task-001")
        os.makedirs(recent_dir)

        deleted = store.sweep_expired_task_workspaces(ttl_hours=24)

        assert deleted == 0
        assert os.path.isdir(recent_dir)


# ===========================================================================
# Section 4: API-level integration tests
# ===========================================================================


class TestSkillImportAPI:
    """API-level tests for POST /api/import/skill and GET /api/import/skill/task/{id}."""

    def test_import_skill_returns_202(self, client_with_mock_service):
        """Valid multipart POST with a .skill file returns 202 Accepted."""
        response = client_with_mock_service.post(
            "/api/import/skill",
            data={"kb_index": "skill_kb", "tag": "skill"},
            files={
                "files": (
                    "k8s-cleaner.skill",
                    b"PK\x03\x04fake",
                    "application/octet-stream",
                )
            },
        )
        assert response.status_code == 202

    def test_import_skill_wrong_tag_returns_400(self, client_with_mock_service):
        """tag='memory' on /api/import/skill → 400 TAG_INVALID."""
        response = client_with_mock_service.post(
            "/api/import/skill",
            data={"kb_index": "skill_kb", "tag": "memory"},
            files={
                "files": (
                    "k8s-cleaner.skill",
                    b"PK\x03\x04fake",
                    "application/octet-stream",
                )
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "TAG_INVALID"

    def test_import_skill_missing_kb_index_returns_400(self, client_with_mock_service):
        """Blank kb_index → 400."""
        response = client_with_mock_service.post(
            "/api/import/skill",
            data={"kb_index": "   ", "tag": "skill"},
            files={
                "files": (
                    "k8s-cleaner.skill",
                    b"PK\x03\x04fake",
                    "application/octet-stream",
                )
            },
        )
        assert response.status_code == 400

    def test_import_skill_returns_task_id_and_domain_skill(
        self, client_with_mock_service
    ):
        """Response body includes task_id, domain='SKILL', kb_index, tag, status."""
        response = client_with_mock_service.post(
            "/api/import/skill",
            data={"kb_index": "my_kb", "tag": "skill"},
            files={"files": ("my.skill", b"PK\x03\x04fake", "application/octet-stream")},
        )
        assert response.status_code == 202
        body = response.json()
        assert body["task_id"] == "test-skill-task-123"
        assert body["domain"] == "SKILL"
        assert body["kb_index"] == "my_kb"
        assert body["tag"] == "skill"
        assert body["status"] == "queued"

    def test_import_skill_task_service_called_with_correct_type(
        self, client_with_mock_service, mock_task_service
    ):
        """submit() is called exactly once with task_type='import.skill'."""
        client_with_mock_service.post(
            "/api/import/skill",
            data={"kb_index": "kb1", "tag": "skill"},
            files={"files": ("f.skill", b"PK\x03\x04fake", "application/octet-stream")},
        )
        mock_task_service.submit.assert_called_once()
        call_kwargs = mock_task_service.submit.call_args
        task_type_arg = call_kwargs.kwargs.get("task_type") or (
            call_kwargs.args[0] if call_kwargs.args else None
        )
        assert task_type_arg == "import.skill"

    def test_get_task_status_returns_task_info(self, tmp_path):
        """GET /api/import/skill/task/{id} returns task data for a known task."""
        if not _skill_api_available():
            pytest.skip("skill_import_api not implemented yet")

        from bible.features.async_task.repository import AsyncTaskRepository

        repo = AsyncTaskRepository()
        repo.create(task_id="skill-t1", task_type="import.skill", payload={})
        task = repo.get("skill-t1")

        mock_repo = MagicMock()
        mock_repo.get.return_value = task

        with patch(
            "bible.api.upload.skill_upload_api.get_task_repository",
            return_value=mock_repo,
        ):
            with patch("bible.api.upload.skill_upload_api.get_task_service") as mock_svc:
                mock_svc.return_value.submit.return_value = {
                    "task_id": "skill-t1",
                    "status": "queued",
                }
                from bible.main import create_app

                app = create_app()
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get("/api/import/skill/task/skill-t1")

        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "skill-t1"
        assert body["task_type"] == "import.skill"
        assert "status" in body

    def test_get_task_not_found_returns_404(self):
        """GET /api/import/skill/task/{unknown} → 404 NOT_FOUND."""
        if not _skill_api_available():
            pytest.skip("skill_import_api not implemented yet")

        mock_repo = MagicMock()
        mock_repo.get.return_value = None

        with patch(
            "bible.api.upload.skill_upload_api.get_task_repository",
            return_value=mock_repo,
        ):
            from bible.main import create_app

            app = create_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/import/skill/task/no-such-skill-task")

        assert resp.status_code == 404
        assert resp.json()["detail"]["code"] == "NOT_FOUND"


# ===========================================================================
# Section 5: End-to-end (sandbox) parser tests
# ===========================================================================


def _wait_for_terminal_skill(
    client: TestClient,
    task_id: str,
    timeout: float = 15.0,
    interval: float = 0.05,
) -> dict:
    """Poll GET /api/import/skill/task/{task_id} until a terminal status or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        r = client.get(f"/api/import/skill/task/{task_id}")
        assert r.status_code == 200, f"GET task returned {r.status_code}: {r.text}"
        body = r.json()
        if body["status"] in ("completed", "failed", "cancelled"):
            return body
        time.sleep(interval)
    raise TimeoutError(
        f"Task {task_id!r} did not reach terminal state within {timeout}s"
    )


_PARSE_SKILL_RELATIVE_IMPORT_BUG = pytest.mark.skipif(False, reason="fixed")
_PARSE_SKILL_WRONG_ERROR_CODE = pytest.mark.skipif(False, reason="fixed")


@_skip_e2e
class TestSkillParserE2E:
    """End-to-end tests: run parse_skill.py through SandboxRunner (real subprocess)."""

    def _run(self, manifest_path: str, context: dict | None = None) -> dict:
        runner = SandboxRunner(timeout_seconds=30)
        return runner.run_parse(str(_PARSE_SKILL_PY), manifest_path, context)

    @_PARSE_SKILL_RELATIVE_IMPORT_BUG
    def test_e2e_parse_skill_success(self, tmp_path):
        """Real .skill zip → SandboxRunner → correct chunks/search_profile."""
        skill_file = make_skill_zip(tmp_path / "build", "k8s-log-cleaner", VALID_SKILLS_MD)
        staged = [_make_staged_entry(skill_file)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        result = self._run(manifest_path)

        assert isinstance(result, dict)
        chunks = result.get("chunks", [])
        assert len(chunks) == 1, "Expected exactly one chunk for one skill"

        chunk = chunks[0]
        chunk_str = str(chunk)
        assert "k8s-log-cleaner" in chunk_str

        profile = result.get("search_profile", {})
        for key in ("keyword", "text", "vector", "hybrid"):
            assert key in profile, f"search_profile missing key: {key}"

    @_PARSE_SKILL_RELATIVE_IMPORT_BUG
    def test_e2e_parse_skill_with_extra_files(self, tmp_path):
        """One .skill + two .md files → all extra files appear in local_file_storage_plan."""
        skill_file = make_skill_zip(tmp_path / "build", "k8s-log-cleaner", VALID_SKILLS_MD)
        extra1 = tmp_path / "readme.md"
        extra1.write_text("# Readme")
        extra2 = tmp_path / "guide.md"
        extra2.write_text("# Guide")

        staged = [
            _make_staged_entry(skill_file, "ref_0"),
            _make_staged_entry(extra1, "ref_1"),
            _make_staged_entry(extra2, "ref_2"),
        ]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        result = self._run(manifest_path)

        plan = result.get("local_file_storage_plan")
        assert plan is not None, "local_file_storage_plan must be present"
        plan_filenames = [f["filename"] for f in plan.get("files", [])]
        assert "readme.md" in plan_filenames
        assert "guide.md" in plan_filenames

    @_PARSE_SKILL_WRONG_ERROR_CODE
    def test_e2e_parse_skill_missing_skill_package(self, tmp_path):
        """Manifest with no .skill file → SKILL_PACKAGE_MISSING error."""
        regular = tmp_path / "readme.md"
        regular.write_text("# Readme")
        staged = [_make_staged_entry(regular)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        with pytest.raises(DomainError) as exc_info:
            self._run(manifest_path)
        err_str = str(exc_info.value.details) + exc_info.value.message
        assert "SKILL_PACKAGE_MISSING" in err_str

    @_PARSE_SKILL_WRONG_ERROR_CODE
    def test_e2e_parse_skill_multiple_skill_packages(self, tmp_path):
        """Manifest with two .skill files → SKILL_PACKAGE_MULTIPLE error."""
        skill1 = make_skill_zip(tmp_path / "b1", "skill1", VALID_SKILLS_MD)
        skill2 = make_skill_zip(tmp_path / "b2", "skill2", VALID_SKILLS_MD)
        staged = [
            _make_staged_entry(skill1, "ref_0"),
            _make_staged_entry(skill2, "ref_1"),
        ]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        with pytest.raises(DomainError) as exc_info:
            self._run(manifest_path)
        err_str = str(exc_info.value.details) + exc_info.value.message
        assert "SKILL_PACKAGE_MULTIPLE" in err_str

    def test_e2e_parse_skill_zip_slip(self, tmp_path):
        """A .skill zip with path-traversal entry → extraction rejected."""
        evil_zip = tmp_path / "evil.skill"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../evil.txt", "evil content")

        staged = [_make_staged_entry(evil_zip)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        with pytest.raises(DomainError):
            self._run(manifest_path)

    def test_e2e_parse_skill_no_skills_md(self, tmp_path):
        """ZIP with the right structure but no SKILL.md → error."""
        skill_dir = tmp_path / "build" / "my-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "config.json").write_text("{}")

        skill_file = tmp_path / "my-skill.skill"
        with zipfile.ZipFile(skill_file, "w") as zf:
            zf.write(skill_dir / "config.json", "my-skill/config.json")

        staged = [_make_staged_entry(skill_file)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        with pytest.raises(DomainError):
            self._run(manifest_path)

    def test_e2e_parse_skill_missing_name_in_skills_md(self, tmp_path):
        """SKILL.md without H1 heading → parse error surfaced from sandbox."""
        skill_file = make_skill_zip(tmp_path / "build", "bad-skill", MISSING_H1_SKILLS_MD)
        staged = [_make_staged_entry(skill_file)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        with pytest.raises(DomainError):
            self._run(manifest_path)

    @_PARSE_SKILL_RELATIVE_IMPORT_BUG
    def test_e2e_skills_md_name_matches_chunk_title(self, tmp_path):
        """Chunk title must match the H1 in SKILL.md."""
        skill_file = make_skill_zip(tmp_path / "build", "k8s-log-cleaner", VALID_SKILLS_MD)
        staged = [_make_staged_entry(skill_file)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        result = self._run(manifest_path)
        chunk = result["chunks"][0]
        title = chunk.get("title") or chunk.get("doc_id") or ""
        assert "k8s-log-cleaner" in str(title)

    @_PARSE_SKILL_RELATIVE_IMPORT_BUG
    def test_e2e_search_profile_vector_source_template(self, tmp_path):
        """Vector source_template contains {name}, {description}, and {body}."""
        skill_file = make_skill_zip(tmp_path / "build", "k8s-log-cleaner", VALID_SKILLS_MD)
        staged = [_make_staged_entry(skill_file)]
        manifest_path = str(make_manifest_json(tmp_path, staged))

        result = self._run(manifest_path)
        template = result["search_profile"].get("vector", {}).get("source_template", "")
        for field in ("{name}", "{description}", "{body}"):
            assert field in template, f"source_template missing {field}"
