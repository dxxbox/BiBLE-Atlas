from __future__ import annotations

from bible.config.configure import BibleAtlasConfig, FileSystemLocalConfig


def test_filesystem_config_accepts_file_system_alias_and_hash_algo():
    config = BibleAtlasConfig.load_config_from_dict(
        {
            "file_system": {
                "backend": "local",
                "local": {"root_dir": "/tmp/files", "hash_algo": "sha1"},
            }
        }
    )

    assert config.filesystem.backend == "local"
    assert config.filesystem.local.root_dir == "/tmp/files"
    assert config.filesystem.local.hash_algo == "sha1"
    assert config.filesystem.local.has_algo == "sha1"


def test_filesystem_local_config_accepts_legacy_has_algo():
    local = FileSystemLocalConfig(has_algo="sha256")

    assert local.hash_algo == "sha256"
    assert local.has_algo == "sha256"
