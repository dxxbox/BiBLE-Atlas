from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterable

from bible.common.logger import get_logger

from ..base import IDatabaseWriter
from ..types import BulkWriteResult, DatabaseError, DomainType, IndexBinding

if TYPE_CHECKING:
    from bible.config.configure import BibleAtlasConfig
    from psycopg_pool import ConnectionPool


class PostgresWriter(IDatabaseWriter):
    _TABLE_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

    def __init__(self, pool: "ConnectionPool", cfg: "BibleAtlasConfig") -> None:
        self._pool = pool
        pg_cfg = cfg.database.postgres
        self._binding_table = pg_cfg.binding_table
        self._content_table = pg_cfg.content_table
        self._file_registry_table = pg_cfg.file_registry_table
        self._async_task_table = pg_cfg.async_task_table
        self._bulk_chunk_size = pg_cfg.bulk_chunk_size
        self._logger = get_logger(__name__)

        self._validate_table_name(self._binding_table)
        self._validate_table_name(self._content_table)
        self._validate_table_name(self._file_registry_table)
        self._validate_table_name(self._async_task_table)

    # ------------------------------------------------------------------
    # Index binding operations
    # ------------------------------------------------------------------

    def get_binding_by_domain_index(self, domain: DomainType, kb_index: str) -> IndexBinding | None:
        from psycopg import sql
        from psycopg.rows import dict_row

        query = sql.SQL(
            """
            SELECT
                domain_type, kb_index, tag, parser_script_source, parser_script_sha256,
                vector_model, search_profile_json, search_profile_sha256,
                is_active, created_at, updated_at, deleted_at
            FROM {}
            WHERE domain_type = %s AND kb_index = %s AND is_active = TRUE
            LIMIT 1
            """
        ).format(sql.Identifier(self._binding_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (domain, kb_index))
                    row = cur.fetchone()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/index from Postgres.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        if row is None:
            return None
        return self._to_binding(row)

    def get_binding_by_domain_tag(self, domain: DomainType, tag: str) -> IndexBinding | None:
        from psycopg import sql
        from psycopg.rows import dict_row

        query = sql.SQL(
            """
            SELECT
                domain_type, kb_index, tag, parser_script_source, parser_script_sha256,
                vector_model, search_profile_json, search_profile_sha256,
                is_active, created_at, updated_at, deleted_at
            FROM {}
            WHERE domain_type = %s AND tag = %s AND is_active = TRUE
            ORDER BY updated_at DESC NULLS LAST
            LIMIT 2
            """
        ).format(sql.Identifier(self._binding_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (domain, tag))
                    rows = cur.fetchall()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to query index binding by domain/tag from Postgres.",
                details={"domain_type": domain, "tag": tag},
            ) from exc
        if not rows:
            return None
        if len(rows) > 1:
            self._logger.error(
                "Duplicated active bindings found for same domain/tag in Postgres: domain=%s tag=%s count=%d",
                domain, tag, len(rows),
            )
        return self._to_binding(rows[0])

    def create_index_binding(self, binding_doc: dict[str, Any]) -> dict[str, Any]:
        from psycopg import errors as pg_errors, sql
        from psycopg.types.json import Jsonb

        required = {
            "domain_type",
            "kb_index",
            "tag",
            "parser_script_source",
            "parser_script_sha256",
            "search_profile_json",
            "search_profile_sha256",
        }
        missing = [key for key in required if key not in binding_doc]
        if missing:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="create_index_binding requires complete binding_doc.",
                details={"missing_fields": missing},
            )

        now = self._now_iso()
        payload = {
            **binding_doc,
            "is_active": bool(binding_doc.get("is_active", True)),
            "created_at": binding_doc.get("created_at", now),
            "updated_at": now,
            "deleted_at": None,
        }
        query = sql.SQL(
            """
            INSERT INTO {} (
                domain_type, kb_index, tag, parser_script_source, parser_script_sha256,
                vector_model, search_profile_json, search_profile_sha256,
                is_active, created_at, updated_at, deleted_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s
            )
            """
        ).format(sql.Identifier(self._binding_table))
        params = (
            payload["domain_type"],
            payload["kb_index"],
            payload["tag"],
            payload["parser_script_source"],
            payload["parser_script_sha256"],
            payload.get("vector_model"),
            Jsonb(payload["search_profile_json"]),
            payload["search_profile_sha256"],
            payload["is_active"],
            payload["created_at"],
            payload["updated_at"],
            payload["deleted_at"],
        )
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                conn.commit()
        except pg_errors.UniqueViolation as exc:
            raise DatabaseError(
                code="INDEX_BINDING_CONFLICT",
                message=f"Index binding already exists for {payload['domain_type']}::{payload['kb_index']}.",
            ) from exc
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to create index binding in Postgres.",
                details={
                    "domain_type": payload["domain_type"],
                    "kb_index": payload["kb_index"],
                    "tag": payload["tag"],
                },
            ) from exc

        return {"created": True, "_id": self._binding_doc_id(payload["domain_type"], payload["kb_index"])}

    def deactivate_binding(self, domain: DomainType, kb_index: str) -> dict[str, Any]:
        from psycopg import sql
        from psycopg.rows import dict_row

        now = self._now_iso()
        query = sql.SQL(
            """
            UPDATE {}
               SET is_active = FALSE,
                   deleted_at = %s,
                   updated_at = %s
             WHERE domain_type = %s
               AND kb_index = %s
               AND is_active = TRUE
         RETURNING domain_type, kb_index
            """
        ).format(sql.Identifier(self._binding_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (now, now, domain, kb_index))
                    updated = cur.fetchone()
                conn.commit()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to deactivate index binding in Postgres.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        if updated is None:
            raise DatabaseError(
                code="INDEX_NOT_BOUND",
                message=f"Binding not found for {domain}::{kb_index}.",
            )
        return {"updated": True, "_id": self._binding_doc_id(domain, kb_index)}

    def update_binding(
        self,
        domain: DomainType,
        kb_index: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        """Update arbitrary fields on an existing binding row."""
        from psycopg import sql

        if not patch:
            return {"updated": False, "_id": self._binding_doc_id(domain, kb_index)}

        now = self._now_iso()
        patch_with_ts = {**patch, "updated_at": now}
        set_fragments = [
            sql.SQL("{} = %s").format(sql.Identifier(k))
            for k in patch_with_ts
        ]
        query = sql.SQL(
            "UPDATE {} SET {} WHERE domain_type = %s AND kb_index = %s"
        ).format(
            sql.Identifier(self._binding_table),
            sql.SQL(", ").join(set_fragments),
        )
        params = list(patch_with_ts.values()) + [domain, kb_index]
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, params)
                conn.commit()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to update index binding in Postgres.",
                details={"domain_type": domain, "kb_index": kb_index},
            ) from exc
        return {"updated": True, "_id": self._binding_doc_id(domain, kb_index)}

    # ------------------------------------------------------------------
    # Bulk content / file-registry operations
    # ------------------------------------------------------------------

    def bulk_upsert_content_docs(
        self,
        index: str,
        docs: list[dict[str, Any]],
        *,
        vector_options: dict[str, Any] | None = None,
    ) -> BulkWriteResult:
        del vector_options
        return self._bulk_upsert_json_records(
            table_name=self._content_table,
            index=index,
            records=docs,
            id_fields=("_id", "doc_id", "chunk_id"),
        )

    def bulk_upsert_file_registry(
        self,
        index: str,
        file_records: list[dict[str, Any]],
    ) -> BulkWriteResult:
        return self._bulk_upsert_json_records(
            table_name=self._file_registry_table,
            index=index,
            records=file_records,
            id_fields=("_id", "file_id", "storage_path"),
        )

    # ------------------------------------------------------------------
    # Async task operations
    # ------------------------------------------------------------------

    def create_async_task(self, task_doc: dict[str, Any]) -> None:
        from psycopg import errors as pg_errors, sql
        from psycopg.types.json import Jsonb

        task_id = str(task_doc.get("task_id") or "").strip()
        if not task_id:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="create_async_task requires task_doc with task_id.",
            )
        now = self._now_iso()
        payload = {**task_doc, "created_at": task_doc.get("created_at", now), "updated_at": now}
        query = sql.SQL(
            """
            INSERT INTO {} (task_id, payload, created_at, updated_at)
            VALUES (%s, %s, %s, %s)
            """
        ).format(sql.Identifier(self._async_task_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        query,
                        (task_id, Jsonb(payload), payload["created_at"], payload["updated_at"]),
                    )
                conn.commit()
        except pg_errors.UniqueViolation as exc:
            raise DatabaseError(
                code="INDEX_BINDING_CONFLICT",
                message=f"Async task already exists: {task_id}.",
            ) from exc
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to create async task in Postgres.",
                details={"task_id": task_id},
            ) from exc

    def get_async_task(self, task_id: str) -> dict[str, Any] | None:
        from psycopg import sql
        from psycopg.rows import dict_row

        query = sql.SQL(
            "SELECT payload FROM {} WHERE task_id = %s LIMIT 1"
        ).format(sql.Identifier(self._async_task_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_id,))
                    row = cur.fetchone()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to get async task from Postgres.",
                details={"task_id": task_id},
            ) from exc
        if row is None:
            return None
        return row["payload"]

    def find_async_task_by_idempotency(
        self, task_type: str, idempotency_key: str
    ) -> dict[str, Any] | None:
        from psycopg import sql
        from psycopg.rows import dict_row

        query = sql.SQL(
            """
            SELECT payload FROM {}
            WHERE payload->>'task_type' = %s
              AND payload->>'idempotency_key' = %s
            LIMIT 1
            """
        ).format(sql.Identifier(self._async_task_table))
        try:
            with self._pool.connection() as conn:
                with conn.cursor(row_factory=dict_row) as cur:
                    cur.execute(query, (task_type, idempotency_key))
                    row = cur.fetchone()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to find async task by idempotency from Postgres.",
                details={"task_type": task_type, "idempotency_key": idempotency_key},
            ) from exc
        if row is None:
            return None
        return row["payload"]

    def update_async_task(
        self,
        task_id: str,
        patch_doc: dict[str, Any],
        expected_statuses: list[str] | None = None,
    ) -> bool:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        existing = self.get_async_task(task_id)
        if existing is None:
            return False
        if expected_statuses and existing.get("status") not in expected_statuses:
            return False

        now = self._now_iso()
        updated_payload = {**existing, **patch_doc, "updated_at": now}
        where_clause = sql.SQL("WHERE task_id = %s")
        query = sql.SQL(
            "UPDATE {} SET payload = %s, updated_at = %s "
        ).format(sql.Identifier(self._async_task_table)) + where_clause
        try:
            with self._pool.connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(query, (Jsonb(updated_payload), now, task_id))
                conn.commit()
        except Exception as exc:
            raise DatabaseError(
                code="DATABASE_BACKEND_UNAVAILABLE",
                message="Failed to update async task in Postgres.",
                details={"task_id": task_id},
            ) from exc
        return True

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _bulk_upsert_json_records(
        self,
        table_name: str,
        index: str,
        records: list[dict[str, Any]],
        id_fields: tuple[str, ...],
    ) -> BulkWriteResult:
        from psycopg import sql
        from psycopg.types.json import Jsonb

        if not index:
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message="bulk upsert requires index.",
            )
        if not records:
            return BulkWriteResult()

        query = sql.SQL(
            """
            INSERT INTO {} (index_name, row_id, payload, created_at, updated_at)
            VALUES (%s, %s, %s, NOW(), NOW())
            ON CONFLICT (index_name, row_id)
            DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
            """
        ).format(sql.Identifier(table_name))

        result = BulkWriteResult()
        for chunk in self._chunked(records, self._bulk_chunk_size):
            params: list[tuple[str, str, Any]] = []
            for record in chunk:
                row_id = self._extract_row_id(record, id_fields)
                if not row_id:
                    result.fail_count += 1
                    result.errors.append(
                        {
                            "reason": f"missing id fields: {id_fields}",
                            "record_preview": list(record.keys())[:10],
                        }
                    )
                    continue
                payload = {k: v for k, v in record.items() if k != "_id"}
                params.append((index, row_id, Jsonb(payload)))

            if not params:
                continue
            try:
                with self._pool.connection() as conn:
                    with conn.cursor() as cur:
                        cur.executemany(query, params)
                    conn.commit()
                result.success_count += len(params)
            except Exception as exc:
                result.fail_count += len(params)
                result.errors.append({"reason": repr(exc), "batch_size": len(params)})
                self._logger.warning(
                    "Postgres bulk upsert batch failed: table=%s index=%s batch_size=%d error=%s",
                    table_name, index, len(params), repr(exc),
                )
        return result

    def _extract_row_id(self, data: dict[str, Any], fields: tuple[str, ...]) -> str | None:
        for f in fields:
            value = data.get(f)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _binding_doc_id(self, domain: DomainType, kb_index: str) -> str:
        return f"{domain}::{kb_index}"

    def _to_binding(self, row: dict[str, Any]) -> IndexBinding:
        return IndexBinding(
            domain_type=row["domain_type"],
            kb_index=row["kb_index"],
            tag=row["tag"],
            parser_script_source=row["parser_script_source"],
            parser_script_sha256=row["parser_script_sha256"],
            vector_model=row.get("vector_model"),
            search_profile_json=row["search_profile_json"],
            search_profile_sha256=row["search_profile_sha256"],
            is_active=bool(row.get("is_active", True)),
            created_at=self._iso_if_datetime(row.get("created_at")),
            updated_at=self._iso_if_datetime(row.get("updated_at")),
            deleted_at=self._iso_if_datetime(row.get("deleted_at")),
        )

    def _iso_if_datetime(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        return str(value)

    def _chunked(self, docs: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
        for idx in range(0, len(docs), size):
            yield docs[idx : idx + size]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _validate_table_name(self, table_name: str) -> None:
        if not self._TABLE_RE.match(table_name):
            raise DatabaseError(
                code="DATABASE_INVALID_ARGUMENT",
                message=f"Invalid postgres table name: {table_name!r}",
            )
