import os
import tempfile
from pathlib import Path
import yaml
from bible_cc_plugin.config import resolve_config, BibleConfigError


def test_resolve_config_from_env():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
            "daemon": {"port": 9777},
            "capture": {"mode": "key_moments", "tool_result_max_chars": 200},
            "detection": {"model": "claude-sonnet-4-5"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            cfg = resolve_config()
            assert cfg.base_url == "http://localhost:5555"
            assert cfg.daemon_port == 9777
            assert cfg.capture_mode == "key_moments"
            assert cfg.tool_result_max_chars == 200
            assert cfg.detection_model == "claude-sonnet-4-5"
            assert cfg.source_client == "claude-code"
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)


def test_missing_base_url_raises():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text("daemon:\n  port: 9777\n")
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            resolve_config()
            assert False, "should have raised"
        except BibleConfigError:
            pass
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)


def test_env_var_overrides_yaml():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://yaml.example.com:5555"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        os.environ["BIBLE_ATLAS_BASE_URL"] = "http://env.example.com:5555"
        try:
            cfg = resolve_config()
            assert cfg.base_url == "http://env.example.com:5555"
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)
            os.environ.pop("BIBLE_ATLAS_BASE_URL", None)


def test_defaults_when_empty_config():
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            cfg = resolve_config()
            assert cfg.daemon_port == 9777
            assert cfg.capture_mode == "key_moments"
            assert cfg.tool_result_max_chars == 250
            assert cfg.recall_top_k == 8
            assert cfg.recall_min_score == 0.35
            assert cfg.enable_memory_recall is True
            assert cfg.enable_knowledge_recall is False
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)


def test_env_only_no_yaml_file():
    """Config should work with env var only, no YAML file."""
    os.environ["BIBLE_ATLAS_BASE_URL"] = "http://env-only:5555"
    try:
        cfg = resolve_config()
        assert cfg.base_url == "http://env-only:5555"
        assert cfg.daemon_port == 9777
        assert cfg.enable_memory_recall is True
    finally:
        os.environ.pop("BIBLE_ATLAS_BASE_URL", None)


def test_bool_only_accepts_actual_bools():
    """String 'false' in YAML should fall back to default, not become True."""
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
            "recall": {"enable_memory": "false"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            cfg = resolve_config()
            assert cfg.enable_memory_recall is True
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)


def test_invalid_range_falls_back():
    """Out-of-range values should fall back to defaults."""
    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
            "daemon": {"port": 22},
            "recall": {"top_k": 999},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            cfg = resolve_config()
            assert cfg.daemon_port == 9777
            assert cfg.recall_top_k == 8
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)
