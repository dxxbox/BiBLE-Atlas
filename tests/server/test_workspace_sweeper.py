"""
Tests for WorkspaceSweeper.

Covers:
1. TTL=0  → sweeper refuses to start (disabled)
2. start() creates a daemon thread; stop() joins it
3. Double-start is a no-op (warns, doesn't spawn second thread)
4. _sweep_once delegates to StoreMemory.sweep_expired_task_workspaces with correct TTL
5. Exceptions in sweep are swallowed (thread survives)
6. stop() signals the event so _loop exits promptly
"""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, call, patch

import pytest

import importlib
WorkspaceSweeper = importlib.import_module("bible.features.import.workspace_sweeper").WorkspaceSweeper


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sweeper(ttl_hours: int = 24, interval_seconds: int = 3600) -> tuple[WorkspaceSweeper, MagicMock]:
    store = MagicMock()
    store.sweep_expired_task_workspaces.return_value = 0
    sweeper = WorkspaceSweeper(store=store, ttl_hours=ttl_hours, interval_seconds=interval_seconds)
    return sweeper, store


# ---------------------------------------------------------------------------
# 1. TTL disabled
# ---------------------------------------------------------------------------

class TestWorkspaceSweeperDisabled:
    def test_ttl_zero_does_not_start_thread(self):
        sweeper, store = _make_sweeper(ttl_hours=0)
        sweeper.start()
        assert sweeper._thread is None
        store.sweep_expired_task_workspaces.assert_not_called()

    def test_ttl_negative_does_not_start_thread(self):
        sweeper, store = _make_sweeper(ttl_hours=-1)
        sweeper.start()
        assert sweeper._thread is None

    def test_stop_on_disabled_sweeper_is_safe(self):
        sweeper, _ = _make_sweeper(ttl_hours=0)
        sweeper.start()
        sweeper.stop()  # must not raise


# ---------------------------------------------------------------------------
# 2. Lifecycle: start / stop
# ---------------------------------------------------------------------------

class TestWorkspaceSweeperLifecycle:
    def test_start_creates_daemon_thread(self):
        sweeper, _ = _make_sweeper(interval_seconds=9999)
        sweeper.start()
        assert sweeper._thread is not None
        assert sweeper._thread.daemon is True
        sweeper.stop()

    def test_thread_name_is_workspace_sweeper(self):
        sweeper, _ = _make_sweeper(interval_seconds=9999)
        sweeper.start()
        assert sweeper._thread is not None
        assert sweeper._thread.name == "workspace-sweeper"
        sweeper.stop()

    def test_stop_signals_event_and_joins_thread(self):
        sweeper, _ = _make_sweeper(interval_seconds=9999)
        sweeper.start()
        assert sweeper._thread is not None
        thread = sweeper._thread
        sweeper.stop(timeout=5.0)
        # After stop, thread should no longer be alive (event was set)
        assert not thread.is_alive()
        assert sweeper._thread is None

    def test_double_start_does_not_spawn_second_thread(self):
        sweeper, _ = _make_sweeper(interval_seconds=9999)
        sweeper.start()
        thread1 = sweeper._thread
        sweeper.start()  # should be a no-op
        assert sweeper._thread is thread1
        sweeper.stop()


# ---------------------------------------------------------------------------
# 3. Sweep delegation
# ---------------------------------------------------------------------------

class TestWorkspaceSweeperSweep:
    def test_sweep_once_calls_sweep_with_correct_ttl(self):
        sweeper, store = _make_sweeper(ttl_hours=48, interval_seconds=9999)
        sweeper._sweep_once()
        store.sweep_expired_task_workspaces.assert_called_once_with(ttl_hours=48)

    def test_sweep_once_called_immediately_on_start(self):
        """Sweeper runs one sweep immediately, then waits for interval."""
        store = MagicMock()
        store.sweep_expired_task_workspaces.return_value = 0

        # Use a very long interval so only the immediate sweep fires
        sweeper = WorkspaceSweeper(store=store, ttl_hours=24, interval_seconds=9999)
        sweeper.start()
        # Give thread a moment to run the immediate sweep
        time.sleep(0.2)
        sweeper.stop(timeout=3.0)

        store.sweep_expired_task_workspaces.assert_called_with(ttl_hours=24)
        assert store.sweep_expired_task_workspaces.call_count >= 1

    def test_sweep_logs_deleted_count_when_nonzero(self, caplog):
        """When sweep deletes directories, a log message is emitted."""
        import logging
        sweeper, store = _make_sweeper(ttl_hours=24, interval_seconds=9999)
        store.sweep_expired_task_workspaces.return_value = 3

        # get_logger sets propagate=False; temporarily re-enable so caplog captures records.
        sweeper_logger = logging.getLogger("bible.features.import.workspace_sweeper")
        sweeper_logger.propagate = True
        try:
            with caplog.at_level(logging.INFO, logger="bible.features.import.workspace_sweeper"):
                sweeper._sweep_once()
        finally:
            sweeper_logger.propagate = False

        assert any("3" in r.message for r in caplog.records)

    def test_sweep_exception_is_swallowed(self):
        """An exception in sweep_expired_task_workspaces must not crash the thread."""
        sweeper, store = _make_sweeper(ttl_hours=24, interval_seconds=9999)
        store.sweep_expired_task_workspaces.side_effect = RuntimeError("disk error")
        # Must not raise
        sweeper._sweep_once()


# ---------------------------------------------------------------------------
# 4. stop() promptness
# ---------------------------------------------------------------------------

class TestWorkspaceSweeperStop:
    def test_stop_returns_before_next_interval(self):
        """With a 1h interval, stop() should return well before 1h."""
        sweeper, _ = _make_sweeper(ttl_hours=24, interval_seconds=3600)
        sweeper.start()
        start = time.monotonic()
        sweeper.stop(timeout=3.0)
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"stop() took too long: {elapsed:.1f}s"
