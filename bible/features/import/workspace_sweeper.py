from __future__ import annotations

"""Periodic background sweeper that removes expired task workspaces."""

import threading

from bible.common.logger import get_logger

logger = get_logger(__name__)

class WorkspaceSweeper:
    """Daemon thread that periodically calls ``StoreMemory.sweep_expired_task_workspaces``.

    On startup it runs one immediate sweep to clean up any leftovers from a
    previous server run, then repeats every *interval_seconds*.  When
    *ttl_hours* is 0 the sweeper does nothing (TTL disabled).
    """

    def __init__(
        self,
        store: "StoreMemory",
        ttl_hours: int = 24,
        interval_seconds: int = 3600,
    ) -> None:
        self._store = store
        self._ttl_hours = ttl_hours
        self._interval = float(interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        pass

    def start(self) -> None:
        if self._ttl_hours <= 0:
            logger.info("WorkspaceSweeper: TTL disabled (workspace_ttl_hours=0); sweeper not started.")
            return
        if self._thread is not None and self._thread.is_alive():
            logger.warning("WorkspaceSweeper: already running, start() ignored.")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="workspace-sweeper",
        )
        self._thread.start()
        logger.info(
            "WorkspaceSweeper started: TTL=%dh, interval=%ds.",
            self._ttl_hours,
            int(self._interval),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the sweeper to stop and wait for the thread to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        logger.info("WorkspaceSweeper stopped.")

    def _loop(self) -> None:
        self._sweep_once()
        while not self._stop_event.wait(timeout=self._interval):
            self._sweep_once()

    def _sweep_once(self) -> None:
        try:
            deleted = self._store.sweep_expired_task_workspaces(ttl_hours=self._ttl_hours)
            if deleted:
                logger.info("WorkspaceSweeper: removed %d expired task workspace(s).", deleted)
            else:
                logger.debug("WorkspaceSweeper: sweep complete, nothing to remove.")
        except Exception:
            logger.exception("WorkspaceSweeper: unexpected error during sweep.")

