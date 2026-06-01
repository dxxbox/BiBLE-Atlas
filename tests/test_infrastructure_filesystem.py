from __future__ import annotations

from io import BytesIO

import pytest

from bible.common.errors import ErrorCode
from bible.config.configure import BibleAtlasConfig
from bible.infrastructure.file_system.factory import FileSystemFactory
from bible.infrastructure.file_system.local import LocalFileSystemGateway
from bible.infrastructure.file_system.types import FileSystemError


def test_local_file_system_store_read_exists_delete(tmp_path):
    gateway = LocalFileSystemGateway(root_dir=str(tmp_path), chunk_size=2)

    result = gateway.store(
        BytesIO(b"hello"),
        domain="MEMORY",
        kb_index="kb/main",
        filename="../unsafe name.txt",
        task_id="task 1",
    )

    assert result.size_bytes == 5
    assert result.file_hash == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
    assert result.filename == "unsafe_name.txt"
    assert gateway.exists(result.storage_path) is True
    with gateway.open_read(result.storage_path) as reader:
        assert reader.read() == b"hello"
    assert gateway.delete(result.storage_path) is True
    assert gateway.exists(result.storage_path) is False


def test_local_file_system_rejects_path_escape(tmp_path):
    gateway = LocalFileSystemGateway(root_dir=str(tmp_path))

    with pytest.raises(FileSystemError) as exc_info:
        gateway.open_read("../secret.txt")

    assert exc_info.value.code == ErrorCode.INVALID_STORAGE_PATH
    assert gateway.exists("../secret.txt") is False
    assert gateway.delete("../secret.txt") is False


def test_file_system_factory_caches_and_resets(tmp_path):
    config = BibleAtlasConfig.load_config_from_dict(
        {
            "filesystem": {
                "backend": "local",
                "local": {"root_dir": str(tmp_path), "hash_algo": "sha256"},
            }
        }
    )
    factory = FileSystemFactory(config)

    first = factory.get_gateway()
    second = factory.get_gateway()
    assert first is second

    factory.reset()
    assert factory.get_gateway() is not first
