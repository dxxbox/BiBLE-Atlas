"""
Unit tests for all IFileSystemGateway implementations and FileSystemFactory.

Covers:
  - LocalFileSystemGateway  – real disk I/O on pytest tmp_path
  - MinioFileSystemGateway  – mock minio.Minio client (no server needed)
  - S3FileSystemGateway     – mock boto3 S3 client (no server needed)
  - FileSystemFactory       – backend routing, caching, reset, constructor args
  - Cross-backend           – storage_path portability guarantee
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bible.infrastructure.file_system.factory import FileSystemFactory
from bible.infrastructure.file_system.local import LocalFileSystemGateway
from bible.infrastructure.file_system.minio import MinioFileSystemGateway
from bible.infrastructure.file_system.s3 import S3FileSystemGateway
from bible.infrastructure.file_system.types import FileStoreResult, FileSystemError


# ===========================================================================
# Shared helpers
# ===========================================================================

_CONTENT = b"hello file system"


def _stream(data: bytes = _CONTENT) -> io.BytesIO:
    return io.BytesIO(data)


# ---------------------------------------------------------------------------
# Fake exceptions – simulate "object not found" without real SDK installed
# ---------------------------------------------------------------------------

class _MinioNoSuchKey(Exception):
    """Mimics minio.error.S3Error with code='NoSuchKey'."""
    code = "NoSuchKey"


class _MinioGenericError(Exception):
    """Generic MinIO error that is NOT a not-found signal."""
    code = "InternalError"


class _S3NoSuchKey(Exception):
    """Mimics botocore ClientError for NoSuchKey."""
    response: dict[str, Any] = {
        "Error": {"Code": "NoSuchKey"},
        "ResponseMetadata": {"HTTPStatusCode": 404},
    }


class _S3NotFound404(Exception):
    """Mimics botocore ClientError with HTTP 404 status."""
    response: dict[str, Any] = {
        "Error": {"Code": "404"},
        "ResponseMetadata": {"HTTPStatusCode": 404},
    }


class _S3GenericError(Exception):
    """Generic S3 error that is NOT a not-found signal."""
    response: dict[str, Any] = {
        "Error": {"Code": "InternalError"},
        "ResponseMetadata": {"HTTPStatusCode": 500},
    }


# ===========================================================================
# LocalFileSystemGateway — store
# ===========================================================================

class TestLocalFileSystemGatewayStore:
    def _gw(self, tmp_path) -> LocalFileSystemGateway:
        return LocalFileSystemGateway(root_dir=str(tmp_path / "files"))

    def test_store_writes_file_to_disk(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"hello world"), domain="MEMORY", kb_index="kb1", filename="test.txt")
        abs_path = tmp_path / "files" / result.storage_path
        assert abs_path.is_file()
        assert abs_path.read_bytes() == b"hello world"

    def test_store_returns_all_six_fields(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"data"), domain="MEMORY", kb_index="kb1", filename="f.bin")
        assert result.storage_path != ""
        assert result.file_hash != ""
        assert result.size_bytes == 4
        assert result.filename != ""
        assert result.domain == "MEMORY"
        assert result.kb_index == "kb1"

    def test_store_hash_matches_content(self, tmp_path):
        content = b"check my hash"
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(content), domain="MEMORY", kb_index="kb1", filename="h.bin")
        assert result.file_hash == hashlib.sha256(content).hexdigest()

    def test_store_size_bytes_matches_content(self, tmp_path):
        content = b"x" * 1234
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(content), domain="MEMORY", kb_index="kb1", filename="big.bin")
        assert result.size_bytes == 1234

    def test_store_path_is_relative(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"rel"), domain="MEMORY", kb_index="kb1", filename="r.txt")
        assert not Path(result.storage_path).is_absolute()

    def test_store_path_includes_domain_and_kb_index(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"x"), domain="SKILL", kb_index="myidx", filename="a.txt")
        assert result.storage_path.startswith("SKILL/myidx/")

    def test_store_with_task_id_in_path(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(
            io.BytesIO(b"x"), domain="MEMORY", kb_index="kb1",
            filename="a.txt", task_id="task-abc",
        )
        assert "task-abc" in result.storage_path

    def test_store_without_task_id_uses_default_segment(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"x"), domain="MEMORY", kb_index="kb1", filename="a.txt")
        assert "default" in result.storage_path

    def test_store_no_temp_file_left_after_success(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"clean"), domain="MEMORY", kb_index="kb1", filename="c.txt")
        parent = (tmp_path / "files" / result.storage_path).parent
        assert list(parent.glob(".upload-*.tmp")) == []

    def test_store_empty_file(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b""), domain="MEMORY", kb_index="kb1", filename="empty.txt")
        assert result.size_bytes == 0
        assert result.file_hash == hashlib.sha256(b"").hexdigest()

    def test_store_two_files_same_name_produce_same_path(self, tmp_path):
        gw = self._gw(tmp_path)
        r1 = gw.store(io.BytesIO(b"a"), domain="MEMORY", kb_index="kb1", filename="f.txt")
        r2 = gw.store(io.BytesIO(b"b"), domain="MEMORY", kb_index="kb1", filename="f.txt")
        assert r1.storage_path == r2.storage_path

    def test_store_two_files_different_names_produce_different_paths(self, tmp_path):
        gw = self._gw(tmp_path)
        r1 = gw.store(io.BytesIO(b"a"), domain="MEMORY", kb_index="kb1", filename="a.txt")
        r2 = gw.store(io.BytesIO(b"b"), domain="MEMORY", kb_index="kb1", filename="b.txt")
        assert r1.storage_path != r2.storage_path


# ===========================================================================
# LocalFileSystemGateway — open_read / exists / delete
# ===========================================================================

class TestLocalFileSystemGatewayReadExistsDelete:
    def _gw(self, tmp_path) -> LocalFileSystemGateway:
        return LocalFileSystemGateway(root_dir=str(tmp_path / "files"))

    def _store(self, gw, content: bytes = b"hello") -> str:
        return gw.store(io.BytesIO(content), domain="MEMORY", kb_index="kb1", filename="f.txt").storage_path

    def test_open_read_returns_correct_content(self, tmp_path):
        gw = self._gw(tmp_path)
        path = self._store(gw, b"read me back")
        with gw.open_read(path) as f:
            assert f.read() == b"read me back"

    def test_open_read_nonexistent_raises_file_not_found(self, tmp_path):
        gw = self._gw(tmp_path)
        with pytest.raises(FileSystemError) as exc:
            gw.open_read("MEMORY/kb1/20990101/default/nonexistent.txt")
        assert exc.value.code == "FILE_NOT_FOUND"

    def test_exists_true_after_store(self, tmp_path):
        gw = self._gw(tmp_path)
        assert gw.exists(self._store(gw)) is True

    def test_exists_false_for_unknown_path(self, tmp_path):
        gw = self._gw(tmp_path)
        assert gw.exists("MEMORY/kb1/20990101/default/ghost.txt") is False

    def test_exists_false_for_invalid_path_does_not_raise(self, tmp_path):
        gw = self._gw(tmp_path)
        assert gw.exists("../escape") is False

    def test_exists_false_for_directory(self, tmp_path):
        gw = self._gw(tmp_path)
        (tmp_path / "files" / "MEMORY").mkdir(parents=True, exist_ok=True)
        assert gw.exists("MEMORY") is False

    def test_delete_removes_file_and_returns_true(self, tmp_path):
        gw = self._gw(tmp_path)
        path = self._store(gw)
        assert gw.delete(path) is True
        assert not gw.exists(path)

    def test_delete_nonexistent_returns_false(self, tmp_path):
        gw = self._gw(tmp_path)
        assert gw.delete("MEMORY/kb1/20990101/default/ghost.txt") is False

    def test_delete_then_exists_returns_false(self, tmp_path):
        gw = self._gw(tmp_path)
        path = self._store(gw)
        gw.delete(path)
        assert gw.exists(path) is False


# ===========================================================================
# LocalFileSystemGateway — path security & filename sanitisation
# ===========================================================================

class TestLocalFileSystemGatewayPathSecurity:
    def _gw(self, tmp_path) -> LocalFileSystemGateway:
        return LocalFileSystemGateway(root_dir=str(tmp_path / "files"))

    def test_directory_traversal_in_storage_path_raises(self, tmp_path):
        gw = self._gw(tmp_path)
        with pytest.raises(FileSystemError) as exc:
            gw.open_read("../../etc/passwd")
        assert exc.value.code == "INVALID_STORAGE_PATH"

    def test_absolute_storage_path_raises(self, tmp_path):
        gw = self._gw(tmp_path)
        with pytest.raises(FileSystemError) as exc:
            gw.open_read("/etc/passwd")
        assert exc.value.code == "INVALID_STORAGE_PATH"

    def test_delete_with_traversal_path_returns_false(self, tmp_path):
        gw = self._gw(tmp_path)
        assert gw.delete("../../etc/passwd") is False

    def test_special_chars_in_filename_are_sanitized(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(
            io.BytesIO(b"x"), domain="MEMORY", kb_index="kb1",
            filename="my file (v2)!.txt",
        )
        assert " " not in result.filename
        assert "(" not in result.filename
        assert "!" not in result.filename

    def test_path_traversal_in_filename_is_stripped(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(
            io.BytesIO(b"x"), domain="MEMORY", kb_index="kb1",
            filename="../../../etc/passwd",
        )
        assert ".." not in result.filename
        assert "/" not in result.filename

    def test_empty_filename_falls_back_to_unnamed(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"x"), domain="MEMORY", kb_index="kb1", filename="")
        assert result.filename == "unnamed.bin"

    def test_empty_domain_falls_back_to_unknown(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(io.BytesIO(b"x"), domain="", kb_index="kb1", filename="f.txt")
        assert result.domain == "UNKNOWN"
        assert result.storage_path.startswith("UNKNOWN/")

    def test_special_chars_in_domain_are_sanitized(self, tmp_path):
        gw = self._gw(tmp_path)
        result = gw.store(
            io.BytesIO(b"x"), domain="my domain!", kb_index="kb/1", filename="f.txt",
        )
        assert " " not in result.storage_path
        assert "!" not in result.storage_path


# ===========================================================================
# MinioFileSystemGateway helpers
# ===========================================================================

def _minio_gw(bucket: str = "my-bucket", prefix: str = "") -> tuple[MinioFileSystemGateway, MagicMock]:
    client = MagicMock()
    return MinioFileSystemGateway(client=client, bucket=bucket, prefix=prefix), client


# ===========================================================================
# MinioFileSystemGateway — store
# ===========================================================================

class TestMinioFileSystemGatewayStore:

    def test_store_calls_put_object(self):
        gw, client = _minio_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="file.json")
        assert client.put_object.call_count == 1

    def test_store_uses_correct_bucket(self):
        gw, client = _minio_gw(bucket="special-bucket")
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="file.json")
        assert client.put_object.call_args[0][0] == "special-bucket"

    def test_store_key_ends_with_sanitized_filename(self):
        gw, client = _minio_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="my file.json")
        assert client.put_object.call_args[0][1].endswith("my_file.json")

    def test_store_with_prefix_prepends_prefix_to_key(self):
        gw, client = _minio_gw(prefix="bible-data")
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert client.put_object.call_args[0][1].startswith("bible-data/")

    def test_store_without_prefix_key_does_not_start_with_slash(self):
        gw, client = _minio_gw(prefix="")
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert not client.put_object.call_args[0][1].startswith("/")

    def test_store_key_contains_domain_and_kb_index(self):
        gw, client = _minio_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="my_kb", filename="f.json")
        key = client.put_object.call_args[0][1]
        assert "MEMORY" in key and "my_kb" in key

    def test_store_passes_correct_size(self):
        data = b"exact size content"
        gw, client = _minio_gw()
        gw.store(io.BytesIO(data), domain="MEMORY", kb_index="kb1", filename="f.bin")
        assert client.put_object.call_args[0][3] == len(data)

    def test_store_returns_file_store_result(self):
        gw, client = _minio_gw()
        assert isinstance(gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json"), FileStoreResult)

    def test_store_result_has_correct_metadata(self):
        gw, client = _minio_gw()
        result = gw.store(_stream(_CONTENT), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert result.domain == "MEMORY"
        assert result.kb_index == "kb1"
        assert result.filename == "f.json"
        assert result.size_bytes == len(_CONTENT)
        assert result.file_hash  # non-empty sha256 hex

    def test_store_result_storage_path_not_prefixed(self):
        gw, client = _minio_gw(bucket="bkt", prefix="pfx")
        result = gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert "bkt" not in result.storage_path
        assert not result.storage_path.startswith("pfx")

    def test_store_task_id_included_in_key(self):
        gw, client = _minio_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json", task_id="t-abc")
        assert "t-abc" in client.put_object.call_args[0][1]

    def test_store_wraps_client_exception_in_file_system_error(self):
        gw, client = _minio_gw()
        client.put_object.side_effect = RuntimeError("network gone")
        with pytest.raises(FileSystemError) as exc_info:
            gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert exc_info.value.code == "FILE_STORE_FAILED"
        assert "MinIO" in exc_info.value.message


# ===========================================================================
# MinioFileSystemGateway — open_read / exists / delete
# ===========================================================================

class TestMinioFileSystemGatewayOpenRead:

    def test_open_read_returns_client_response(self):
        gw, client = _minio_gw()
        fake = MagicMock()
        client.get_object.return_value = fake
        assert gw.open_read("MEMORY/kb1/20260522/t1/f.json") is fake

    def test_open_read_calls_get_object_with_correct_args(self):
        gw, client = _minio_gw(bucket="bkt", prefix="pfx")
        client.get_object.return_value = MagicMock()
        gw.open_read("MEMORY/kb1/20260522/t1/f.json")
        client.get_object.assert_called_once_with("bkt", "pfx/MEMORY/kb1/20260522/t1/f.json")

    def test_open_read_not_found_raises_file_not_found(self):
        gw, client = _minio_gw()
        client.get_object.side_effect = _MinioNoSuchKey()
        with pytest.raises(FileSystemError) as exc_info:
            gw.open_read("MEMORY/kb1/20260522/t1/missing.json")
        assert exc_info.value.code == "FILE_NOT_FOUND"

    def test_open_read_generic_error_raises_file_not_found(self):
        gw, client = _minio_gw()
        client.get_object.side_effect = _MinioGenericError("broken")
        with pytest.raises(FileSystemError) as exc_info:
            gw.open_read("MEMORY/kb1/20260522/t1/f.json")
        assert exc_info.value.code == "FILE_NOT_FOUND"


class TestMinioFileSystemGatewayExists:

    def test_exists_returns_true_when_stat_succeeds(self):
        gw, client = _minio_gw()
        client.stat_object.return_value = MagicMock()
        assert gw.exists("MEMORY/kb1/20260522/t1/f.json") is True

    def test_exists_calls_stat_object_with_correct_key(self):
        gw, client = _minio_gw(bucket="bkt", prefix="pfx")
        client.stat_object.return_value = MagicMock()
        gw.exists("MEMORY/kb1/20260522/t1/f.json")
        client.stat_object.assert_called_once_with("bkt", "pfx/MEMORY/kb1/20260522/t1/f.json")

    def test_exists_returns_false_on_no_such_key(self):
        gw, client = _minio_gw()
        client.stat_object.side_effect = _MinioNoSuchKey()
        assert gw.exists("MEMORY/kb1/20260522/t1/missing.json") is False

    def test_exists_returns_false_on_generic_error(self):
        gw, client = _minio_gw()
        client.stat_object.side_effect = _MinioGenericError("unknown")
        assert gw.exists("MEMORY/kb1/20260522/t1/f.json") is False


class TestMinioFileSystemGatewayDelete:

    def test_delete_returns_true_on_success(self):
        gw, client = _minio_gw()
        assert gw.delete("MEMORY/kb1/20260522/t1/f.json") is True
        client.remove_object.assert_called_once()

    def test_delete_calls_remove_object_with_correct_key(self):
        gw, client = _minio_gw(bucket="bkt", prefix="pfx")
        gw.delete("MEMORY/kb1/20260522/t1/f.json")
        client.remove_object.assert_called_once_with("bkt", "pfx/MEMORY/kb1/20260522/t1/f.json")

    def test_delete_returns_false_on_failure(self):
        gw, client = _minio_gw()
        client.remove_object.side_effect = RuntimeError("forbidden")
        assert gw.delete("MEMORY/kb1/20260522/t1/f.json") is False


# ===========================================================================
# S3FileSystemGateway helpers
# ===========================================================================

def _s3_gw(bucket: str = "my-bucket", prefix: str = "") -> tuple[S3FileSystemGateway, MagicMock]:
    client = MagicMock()
    return S3FileSystemGateway(client=client, bucket=bucket, prefix=prefix), client


# ===========================================================================
# S3FileSystemGateway — store
# ===========================================================================

class TestS3FileSystemGatewayStore:

    def test_store_calls_put_object(self):
        gw, client = _s3_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert client.put_object.call_count == 1

    def test_store_uses_keyword_arguments(self):
        """boto3 S3 client requires keyword-only args."""
        gw, client = _s3_gw(bucket="bkt", prefix="pfx")
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        kw = client.put_object.call_args.kwargs
        assert kw["Bucket"] == "bkt"
        assert kw["Key"].startswith("pfx/")
        assert "Body" in kw
        assert "ContentLength" in kw

    def test_store_key_ends_with_sanitized_filename(self):
        gw, client = _s3_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="my file.json")
        assert client.put_object.call_args.kwargs["Key"].endswith("my_file.json")

    def test_store_with_prefix_prepends_prefix_to_key(self):
        gw, client = _s3_gw(prefix="archive")
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert client.put_object.call_args.kwargs["Key"].startswith("archive/")

    def test_store_without_prefix_key_does_not_start_with_slash(self):
        gw, client = _s3_gw(prefix="")
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert not client.put_object.call_args.kwargs["Key"].startswith("/")

    def test_store_passes_correct_content_length(self):
        data = b"exact content"
        gw, client = _s3_gw()
        gw.store(io.BytesIO(data), domain="MEMORY", kb_index="kb1", filename="f.bin")
        assert client.put_object.call_args.kwargs["ContentLength"] == len(data)

    def test_store_returns_file_store_result(self):
        gw, client = _s3_gw()
        assert isinstance(gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json"), FileStoreResult)

    def test_store_result_has_correct_metadata(self):
        gw, client = _s3_gw()
        result = gw.store(_stream(_CONTENT), domain="MEMORY", kb_index="kb2", filename="r.json")
        assert result.domain == "MEMORY"
        assert result.kb_index == "kb2"
        assert result.filename == "r.json"
        assert result.size_bytes == len(_CONTENT)
        assert len(result.file_hash) == 64  # sha256 hex

    def test_store_result_storage_path_not_prefixed(self):
        gw, client = _s3_gw(bucket="bkt", prefix="pfx")
        result = gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert "bkt" not in result.storage_path
        assert not result.storage_path.startswith("pfx")

    def test_store_task_id_included_in_key(self):
        gw, client = _s3_gw()
        gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json", task_id="task-42")
        assert "task-42" in client.put_object.call_args.kwargs["Key"]

    def test_store_wraps_client_exception_in_file_system_error(self):
        gw, client = _s3_gw()
        client.put_object.side_effect = RuntimeError("S3 down")
        with pytest.raises(FileSystemError) as exc_info:
            gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        assert exc_info.value.code == "FILE_STORE_FAILED"
        assert "S3" in exc_info.value.message


# ===========================================================================
# S3FileSystemGateway — open_read / exists / delete
# ===========================================================================

class TestS3FileSystemGatewayOpenRead:

    def test_open_read_returns_body_stream(self):
        gw, client = _s3_gw()
        fake_body = MagicMock()
        client.get_object.return_value = {"Body": fake_body}
        assert gw.open_read("MEMORY/kb1/20260522/t1/f.json") is fake_body

    def test_open_read_calls_get_object_with_correct_kwargs(self):
        gw, client = _s3_gw(bucket="bkt", prefix="pfx")
        client.get_object.return_value = {"Body": MagicMock()}
        gw.open_read("MEMORY/kb1/20260522/t1/f.json")
        client.get_object.assert_called_once_with(
            Bucket="bkt", Key="pfx/MEMORY/kb1/20260522/t1/f.json",
        )

    def test_open_read_nosuchkey_response_raises_file_not_found(self):
        gw, client = _s3_gw()
        client.get_object.side_effect = _S3NoSuchKey()
        with pytest.raises(FileSystemError) as exc_info:
            gw.open_read("MEMORY/kb1/20260522/t1/missing.json")
        assert exc_info.value.code == "FILE_NOT_FOUND"

    def test_open_read_404_response_raises_file_not_found(self):
        gw, client = _s3_gw()
        client.get_object.side_effect = _S3NotFound404()
        with pytest.raises(FileSystemError) as exc_info:
            gw.open_read("MEMORY/kb1/20260522/t1/missing.json")
        assert exc_info.value.code == "FILE_NOT_FOUND"

    def test_open_read_generic_error_raises_file_not_found(self):
        gw, client = _s3_gw()
        client.get_object.side_effect = _S3GenericError()
        with pytest.raises(FileSystemError) as exc_info:
            gw.open_read("MEMORY/kb1/20260522/t1/f.json")
        assert exc_info.value.code == "FILE_NOT_FOUND"


class TestS3FileSystemGatewayExists:

    def test_exists_returns_true_when_head_object_succeeds(self):
        gw, client = _s3_gw()
        client.head_object.return_value = {}
        assert gw.exists("MEMORY/kb1/20260522/t1/f.json") is True

    def test_exists_calls_head_object_with_correct_kwargs(self):
        gw, client = _s3_gw(bucket="bkt", prefix="pfx")
        client.head_object.return_value = {}
        gw.exists("MEMORY/kb1/20260522/t1/f.json")
        client.head_object.assert_called_once_with(
            Bucket="bkt", Key="pfx/MEMORY/kb1/20260522/t1/f.json",
        )

    def test_exists_returns_false_on_nosuchkey(self):
        gw, client = _s3_gw()
        client.head_object.side_effect = _S3NoSuchKey()
        assert gw.exists("MEMORY/kb1/20260522/t1/missing.json") is False

    def test_exists_returns_false_on_404(self):
        gw, client = _s3_gw()
        client.head_object.side_effect = _S3NotFound404()
        assert gw.exists("MEMORY/kb1/20260522/t1/missing.json") is False

    def test_exists_returns_false_on_generic_error(self):
        gw, client = _s3_gw()
        client.head_object.side_effect = _S3GenericError()
        assert gw.exists("MEMORY/kb1/20260522/t1/f.json") is False


class TestS3FileSystemGatewayDelete:

    def test_delete_returns_true_on_success(self):
        gw, client = _s3_gw()
        assert gw.delete("MEMORY/kb1/20260522/t1/f.json") is True
        client.delete_object.assert_called_once()

    def test_delete_calls_delete_object_with_correct_kwargs(self):
        gw, client = _s3_gw(bucket="bkt", prefix="pfx")
        gw.delete("MEMORY/kb1/20260522/t1/f.json")
        client.delete_object.assert_called_once_with(
            Bucket="bkt", Key="pfx/MEMORY/kb1/20260522/t1/f.json",
        )

    def test_delete_returns_false_on_failure(self):
        gw, client = _s3_gw()
        client.delete_object.side_effect = RuntimeError("no permission")
        assert gw.delete("MEMORY/kb1/20260522/t1/f.json") is False


# ===========================================================================
# FileSystemFactory — config helpers
# ===========================================================================

def _local_cfg(tmp_path, backend: str = "local"):
    from bible.config.configure import BibleAtlasConfig, FileSystemConfig, FileSystemLocalConfig
    return BibleAtlasConfig(
        file_system=FileSystemConfig(
            backend=backend,
            local=FileSystemLocalConfig(root_dir=str(tmp_path / "files")),
        )
    )


def _minio_factory_cfg(tmp_path):
    from bible.config.configure import (
        BibleAtlasConfig, FileSystemConfig, FileSystemLocalConfig, FileSystemMinioConfig,
    )
    return BibleAtlasConfig(
        file_system=FileSystemConfig(
            backend="minio",
            local=FileSystemLocalConfig(root_dir=str(tmp_path / "files")),
            minio=FileSystemMinioConfig(
                endpoint="localhost:9000",
                access_key="minioadmin",
                secret_key="minioadmin",
                bucket="test-bucket",
                prefix="test-prefix",
                secure=False,
            ),
        )
    )


def _s3_factory_cfg(tmp_path):
    from bible.config.configure import (
        BibleAtlasConfig, FileSystemConfig, FileSystemLocalConfig, FileSystemS3Config,
    )
    return BibleAtlasConfig(
        file_system=FileSystemConfig(
            backend="s3",
            local=FileSystemLocalConfig(root_dir=str(tmp_path / "files")),
            s3=FileSystemS3Config(
                bucket="test-s3-bucket",
                prefix="test-prefix",
                region="us-east-1",
                access_key="AKID",
                secret_key="SECRET",
            ),
        )
    )


# ===========================================================================
# FileSystemFactory — routing, caching, reset, constructor args
# ===========================================================================

class TestFileSystemFactory:

    # ---- local backend ----

    def test_local_backend_returns_local_gateway(self, tmp_path):
        gw = FileSystemFactory(_local_cfg(tmp_path, "local")).get_gateway()
        assert isinstance(gw, LocalFileSystemGateway)

    def test_get_gateway_caches_instance(self, tmp_path):
        factory = FileSystemFactory(_local_cfg(tmp_path))
        assert factory.get_gateway() is factory.get_gateway()

    def test_reset_clears_cache(self, tmp_path):
        factory = FileSystemFactory(_local_cfg(tmp_path))
        gw1 = factory.get_gateway()
        factory.reset()
        assert gw1 is not factory.get_gateway()

    def test_backend_name_is_case_insensitive(self, tmp_path):
        gw = FileSystemFactory(_local_cfg(tmp_path, "LOCAL")).get_gateway()
        assert isinstance(gw, LocalFileSystemGateway)

    def test_local_gateway_uses_root_dir_from_config(self, tmp_path):
        gw = FileSystemFactory(_local_cfg(tmp_path)).get_gateway()
        result = gw.store(io.BytesIO(b"cfg"), domain="MEMORY", kb_index="k", filename="f.txt")
        assert (tmp_path / "files" / result.storage_path).is_file()

    # ---- unsupported / unknown backend ----

    # def test_minio_backend_raises_when_package_missing(self, tmp_path):
    #     """minio package not installed → FILE_SYSTEM_BACKEND_UNSUPPORTED."""
    #     with pytest.raises(FileSystemError) as exc:
    #         FileSystemFactory(_local_cfg(tmp_path, "minio")).get_gateway()
    #     assert exc.value.code == "FILE_SYSTEM_BACKEND_UNSUPPORTED"
    #     assert "minio" in exc.value.message.lower() or "MinIO" in exc.value.message

    # def test_s3_backend_raises_when_package_missing(self, tmp_path):
    #     """boto3 package not installed → FILE_SYSTEM_BACKEND_UNSUPPORTED."""
    #     with pytest.raises(FileSystemError) as exc:
    #         FileSystemFactory(_local_cfg(tmp_path, "s3")).get_gateway()
    #     assert exc.value.code == "FILE_SYSTEM_BACKEND_UNSUPPORTED"
    #     assert "S3" in exc.value.message or "s3" in exc.value.message.lower()

    def test_unknown_backend_raises_unsupported(self, tmp_path):
        with pytest.raises(FileSystemError) as exc:
            FileSystemFactory(_local_cfg(tmp_path, "hdfs")).get_gateway()
        assert exc.value.code == "FILE_SYSTEM_BACKEND_UNSUPPORTED"
        assert "hdfs" in exc.value.message

    # ---- minio backend (mocked package) ----

    def test_minio_factory_builds_gateway_when_package_available(self, tmp_path):
        fake_mod = MagicMock()
        fake_client = MagicMock()
        fake_mod.Minio.return_value = fake_client
        with patch.dict(sys.modules, {"minio": fake_mod}):
            gw = FileSystemFactory(_minio_factory_cfg(tmp_path)).get_gateway()
        assert isinstance(gw, MinioFileSystemGateway)
        assert gw._client is fake_client
        assert gw._bucket == "test-bucket"
        assert gw._prefix == "test-prefix"

    def test_minio_factory_passes_endpoint_and_credentials(self, tmp_path):
        fake_mod = MagicMock()
        fake_mod.Minio.return_value = MagicMock()
        with patch.dict(sys.modules, {"minio": fake_mod}):
            FileSystemFactory(_minio_factory_cfg(tmp_path)).get_gateway()
        fake_mod.Minio.assert_called_once_with(
            "localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False,
            region=None,
        )

    def test_minio_factory_gateway_is_cached(self, tmp_path):
        fake_mod = MagicMock()
        fake_mod.Minio.return_value = MagicMock()
        with patch.dict(sys.modules, {"minio": fake_mod}):
            factory = FileSystemFactory(_minio_factory_cfg(tmp_path))
            assert factory.get_gateway() is factory.get_gateway()
        assert fake_mod.Minio.call_count == 1

    # ---- s3 backend (mocked package) ----

    def test_s3_factory_builds_gateway_when_package_available(self, tmp_path):
        fake_mod = MagicMock()
        fake_client = MagicMock()
        fake_mod.client.return_value = fake_client
        with patch.dict(sys.modules, {"boto3": fake_mod}):
            gw = FileSystemFactory(_s3_factory_cfg(tmp_path)).get_gateway()
        assert isinstance(gw, S3FileSystemGateway)
        assert gw._client is fake_client
        assert gw._bucket == "test-s3-bucket"
        assert gw._prefix == "test-prefix"

    def test_s3_factory_passes_credentials_and_region(self, tmp_path):
        fake_mod = MagicMock()
        fake_mod.client.return_value = MagicMock()
        with patch.dict(sys.modules, {"boto3": fake_mod}):
            FileSystemFactory(_s3_factory_cfg(tmp_path)).get_gateway()
        fake_mod.client.assert_called_once_with(
            "s3",
            region_name="us-east-1",
            aws_access_key_id="AKID",
            aws_secret_access_key="SECRET",
        )

    def test_s3_factory_with_custom_endpoint_url(self, tmp_path):
        from bible.config.configure import (
            BibleAtlasConfig, FileSystemConfig, FileSystemLocalConfig, FileSystemS3Config,
        )
        cfg = BibleAtlasConfig(
            file_system=FileSystemConfig(
                backend="s3",
                local=FileSystemLocalConfig(root_dir=str(tmp_path / "files")),
                s3=FileSystemS3Config(
                    bucket="bkt",
                    endpoint_url="http://localhost:4566",
                    access_key="x",
                    secret_key="y",
                ),
            )
        )
        fake_mod = MagicMock()
        fake_mod.client.return_value = MagicMock()
        with patch.dict(sys.modules, {"boto3": fake_mod}):
            FileSystemFactory(cfg).get_gateway()
        assert fake_mod.client.call_args.kwargs["endpoint_url"] == "http://localhost:4566"

    def test_s3_factory_gateway_is_cached(self, tmp_path):
        fake_mod = MagicMock()
        fake_mod.client.return_value = MagicMock()
        with patch.dict(sys.modules, {"boto3": fake_mod}):
            factory = FileSystemFactory(_s3_factory_cfg(tmp_path))
            assert factory.get_gateway() is factory.get_gateway()
        assert fake_mod.client.call_count == 1


# ===========================================================================
# Cross-backend: storage_path portability
# ===========================================================================

class TestStoragePathPortability:
    """storage_path in FileStoreResult must be identical across all backends for the same inputs."""

    def test_local_minio_s3_produce_same_hash_and_size(self, tmp_path):
        """All backends compute the same sha256 hash and byte count for identical content."""
        local_gw = LocalFileSystemGateway(root_dir=str(tmp_path / "files"))
        minio_gw, _ = _minio_gw(prefix="pfx")
        s3_gw, _ = _s3_gw(prefix="pfx")

        data = b"identical content"
        kwargs = dict(domain="MEMORY", kb_index="kb1", filename="f.json", task_id="task-xyz")

        r_local = local_gw.store(io.BytesIO(data), **kwargs)
        r_minio = minio_gw.store(io.BytesIO(data), **kwargs)
        r_s3 = s3_gw.store(io.BytesIO(data), **kwargs)

        assert r_local.file_hash == r_minio.file_hash == r_s3.file_hash
        assert r_local.size_bytes == r_minio.size_bytes == r_s3.size_bytes == len(data)
        assert r_local.file_hash == hashlib.sha256(data).hexdigest()

    def test_minio_and_s3_produce_same_storage_path(self):
        """minio and s3 both delegate to build_storage_path → identical paths."""
        minio_gw, _ = _minio_gw(prefix="pfx")
        s3_gw, _ = _s3_gw(prefix="pfx")

        data = b"same content"
        kwargs = dict(domain="MEMORY", kb_index="kb1", filename="f.json", task_id="task-xyz")

        r_minio = minio_gw.store(io.BytesIO(data), **kwargs)
        r_s3 = s3_gw.store(io.BytesIO(data), **kwargs)

        assert r_minio.storage_path == r_s3.storage_path

    def test_local_storage_path_contains_expected_segments(self, tmp_path):
        """Local path includes domain, kb_index, task_id, and filename."""
        gw = LocalFileSystemGateway(root_dir=str(tmp_path / "files"))
        result = gw.store(
            io.BytesIO(b"x"), domain="MEMORY", kb_index="my_kb",
            filename="report.json", task_id="task-001",
        )
        parts = result.storage_path.split("/")
        assert parts[0] == "MEMORY"
        assert parts[1] == "my_kb"
        assert parts[3] == "task-001"
        assert parts[4] == "report.json"

    def test_storage_path_never_contains_bucket_or_prefix(self):
        """storage_path must be bucket-agnostic (portable across backends)."""
        minio_gw, _ = _minio_gw(bucket="my-minio-bucket", prefix="data/v2")
        s3_gw, _ = _s3_gw(bucket="my-s3-bucket", prefix="archive/2026")

        r_minio = minio_gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")
        r_s3 = s3_gw.store(_stream(), domain="MEMORY", kb_index="kb1", filename="f.json")

        for result in (r_minio, r_s3):
            assert "bucket" not in result.storage_path
            assert "data/v2" not in result.storage_path
            assert "archive" not in result.storage_path
