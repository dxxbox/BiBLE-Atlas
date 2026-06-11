import pytest
import os
import tempfile
from pathlib import Path
import yaml

# Check if mcp package is actually importable
try:
    import mcp  # noqa: F401
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp package not installed")
def test_server_creation():
    from bible_cc_plugin.mcp_server import _make_server

    with tempfile.TemporaryDirectory() as tmp:
        config_path = Path(tmp) / "config.yaml"
        config_path.write_text(yaml.dump({
            "bible": {"base_url": "http://localhost:5555"},
        }))
        os.environ["BIBLE_CC_CONFIG_PATH"] = str(config_path)
        try:
            server = _make_server()
            assert server is not None
        finally:
            os.environ.pop("BIBLE_CC_CONFIG_PATH", None)
