import tempfile
from pathlib import Path
from bible_cc_plugin.daemon.buffer import Buffer


def test_create_session():
    with tempfile.TemporaryDirectory() as tmp:
        buf = Buffer(str(Path(tmp) / "test.db"))
        buf.open()
        try:
            buf.create_session("sess-1")
            session = buf.get_session("sess-1")
            assert session["session_id"] == "sess-1"
            assert session["status"] == "active"
            assert session["turn_count"] == 0
        finally:
            buf.close()


def test_add_turn_and_get_turns():
    with tempfile.TemporaryDirectory() as tmp:
        buf = Buffer(str(Path(tmp) / "test.db"))
        buf.open()
        try:
            buf.create_session("sess-1")
            buf.add_turn("sess-1", "user", "Hello")
            buf.add_turn("sess-1", "assistant", "Hi there", [{"name": "read", "content": "file contents"}])

            turns = buf.get_turns("sess-1")
            assert len(turns) == 2
            assert turns[0]["role"] == "user"
            assert turns[0]["content"] == "Hello"
            assert turns[1]["role"] == "assistant"
            assert buf.get_turn_count("sess-1") == 2
            assert buf.get_buffered_chars("sess-1") > 0
        finally:
            buf.close()


def test_add_and_get_pending_moments():
    with tempfile.TemporaryDirectory() as tmp:
        buf = Buffer(str(Path(tmp) / "test.db"))
        buf.open()
        try:
            buf.create_session("sess-1")
            buf.add_moment("sess-1", "decision", "Chose Python", "Decided to use Python.", "3-5")
            buf.add_moment("sess-1", "accomplishment", "Config done", "Config system complete.", "6-8")

            pending = buf.get_pending_moments("sess-1")
            assert len(pending) == 2
            assert pending[0]["flushed"] == 0

            buf.mark_moment_flushed(pending[0]["id"])
            still_pending = buf.get_pending_moments("sess-1")
            assert len(still_pending) == 1
        finally:
            buf.close()
