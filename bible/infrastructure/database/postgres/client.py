from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from ..types import DatabaseError

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig
    from psycopg_pool import ConnectionPool


class PostgresClientProvider:
    def __init__(self, cfg: "BibleAtlasConfig") -> None:
        pg_cfg = cfg.database.postgres
        self._dsn = pg_cfg.dsn
        self._pool_min_size = pg_cfg.pool_min_size
        self._pool_max_size = pg_cfg.pool_max_size
        self._pool_timeout_seconds = pg_cfg.pool_timeout_seconds
        self._pool: "ConnectionPool | None" = None
        self._lock = threading.RLock()

    def get_pool(self) -> "ConnectionPool":
        with self._lock:
            if self._pool is not None:
                return self._pool

            try:
                from psycopg_pool import ConnectionPool
            except ImportError as exc:
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="psycopg-pool is not installed. "
                    "Install it with: pip install 'psycopg[pool]'",
                ) from exc

            pool = ConnectionPool(
                conninfo=self._dsn,
                min_size=self._pool_min_size,
                max_size=self._pool_max_size,
                timeout=self._pool_timeout_seconds,
            )
            try:
                with pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                        cur.fetchone()
            except Exception as exc:
                pool.close()
                raise DatabaseError(
                    code="DATABASE_BACKEND_UNAVAILABLE",
                    message="Postgres connectivity check failed.",
                    details={
                        "dsn": self._mask_dsn(self._dsn),
                        "pool_min_size": self._pool_min_size,
                        "pool_max_size": self._pool_max_size,
                    },
                ) from exc

            self._pool = pool
            return pool

    def close(self) -> None:
        with self._lock:
            if self._pool is None:
                return
            self._pool.close()
            self._pool = None

    def _mask_dsn(self, dsn: str) -> str:
        if "@" not in dsn:
            return dsn
        prefix, suffix = dsn.split("@", 1)
        if ":" in prefix:
            user = prefix.split(":", 1)[0]
            return f"{user}:***@{suffix}"
        return f"{prefix}@{suffix}"
