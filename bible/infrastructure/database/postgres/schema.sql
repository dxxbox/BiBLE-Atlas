-- Index binding table: one binding represents the unique active config for domain + kb_index.
CREATE TABLE IF NOT EXISTS v4_index_binding (
    domain_type TEXT NOT NULL,
    kb_index TEXT NOT NULL,
    tag TEXT NOT NULL,
    parser_script_source TEXT NOT NULL,
    parser_script_sha256 TEXT NOT NULL,
    vector_model TEXT NULL,
    search_profile_json JSONB NOT NULL,
    search_profile_sha256 TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ NULL,
    PRIMARY KEY (domain_type, kb_index)
);

-- Ensure the same domain + tag can only have one active binding.
CREATE UNIQUE INDEX IF NOT EXISTS uq_v4_binding_domain_tag_active
    ON v4_index_binding(domain_type, tag)
    WHERE is_active = TRUE;

-- Content docs upsert table (idempotent by index_name + row_id).
CREATE TABLE IF NOT EXISTS v4_content_docs (
    index_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_name, row_id)
);

CREATE INDEX IF NOT EXISTS idx_v4_content_docs_index
    ON v4_content_docs(index_name);

-- File registry upsert table (idempotent by index_name + row_id).
CREATE TABLE IF NOT EXISTS v4_file_registry (
    index_name TEXT NOT NULL,
    row_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (index_name, row_id)
);

CREATE INDEX IF NOT EXISTS idx_v4_file_registry_index
    ON v4_file_registry(index_name);

-- Async task table (idempotent by task_id, payload stores full task document).
CREATE TABLE IF NOT EXISTS v4_async_tasks (
    task_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (task_id)
);

CREATE INDEX IF NOT EXISTS idx_v4_async_tasks_type_idempotency
    ON v4_async_tasks((payload->>'task_type'), (payload->>'idempotency_key'));
