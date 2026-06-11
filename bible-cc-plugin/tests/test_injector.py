from bible_cc_plugin.config import BibleCCConfig
from bible_cc_plugin.client import BibleAtlasClient
from bible_cc_plugin.daemon.buffer import Buffer
from bible_cc_plugin.daemon.injector import ContextInjector


def test_inject_when_recall_disabled_returns_empty():
    buf = Buffer(":memory:")
    buf.open()
    try:
        cfg = BibleCCConfig(
            base_url="http://localhost:5555",
            enable_memory_recall=False,
            enable_knowledge_recall=False,
        )
        client = BibleAtlasClient(base_url="http://localhost:5555")
        injector = ContextInjector(cfg, client, buf)
        result = injector.inject("sess-1", "hello")
        assert result == ""
    finally:
        buf.close()


def test_notify_manual_save():
    buf = Buffer(":memory:")
    buf.open()
    try:
        cfg = BibleCCConfig(base_url="http://localhost:5555")
        client = BibleAtlasClient(base_url="http://localhost:5555")
        injector = ContextInjector(cfg, client, buf)
        injector.notify_manual_save("sess-1")
        assert "sess-1" in injector._manual_saves
    finally:
        buf.close()
