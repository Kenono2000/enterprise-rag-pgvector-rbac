-- ============================================================================
-- schema.sql
-- PostgreSQL 16 + pgvector Normalized Architecture with Dual Indexing
-- Consolidated Database Initialization, Migration & Seed Script
-- ============================================================================

-- Set strict search path and error handling
SET client_min_messages = warning;

-- 1. Create Required Extensions (Idempotent)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================================================
-- Helper Functions & Triggers for Automatic Timestamp Updates
-- ============================================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 2. Master Documents Table (Metadata, Governance, De-duplication)
DROP TABLE IF EXISTS document_chunks CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS sdlc_outbox_events CASCADE;
DROP TABLE IF EXISTS sdlc_workflow_checkpoints CASCADE;
DROP TABLE IF EXISTS token_consumption_ledger CASCADE;
DROP TABLE IF EXISTS token_managed_limits CASCADE;

CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    source_path TEXT,
    file_hash CHAR(64) UNIQUE,
    file_type VARCHAR(16) DEFAULT 'markdown',
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Trigger for documents updated_at
DROP TRIGGER IF EXISTS trg_documents_updated_at ON documents;
CREATE TRIGGER trg_documents_updated_at
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 3. Document Chunks Table (Vector Embeddings, 16-bit halfvec Compaction, Content, Chunk Sequence)
CREATE TABLE document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id VARCHAR(128) NOT NULL UNIQUE,
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    token_count INT,
    embedding vector(1536) NOT NULL,
    embedding_halfvec halfvec(1536) GENERATED ALWAYS AS (embedding::halfvec(1536)) STORED,
    embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-small',
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- 5. High-Performance Dual Indexing & Lookup Indexes
-- ============================================================================

-- 5.1 HNSW Vector Index: sub-millisecond approximate nearest neighbor search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 5.1a 16-bit Half-Precision (halfvec) HNSW Index: additional 50% RAM savings (cumulative 75% over 3072-d)
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_halfvec_hnsw
ON document_chunks
USING hnsw ((embedding::halfvec(1536)) halfvec_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 5.1b pgvector 0.8+ Iterative Index Scan Tuning (prevents overfiltering on narrow RBAC roles)
-- NOTE: hnsw.iterative_scan = 'relaxed_order' and hnsw.max_scan_tuples = 20000 are
-- PGC_USERSET session GUCs. They are applied per connection at runtime by
-- DatabaseManager.configure_iterative_scan() (pool init hook + per-query SET) rather
-- than persisted here, because SET inside a DO block only affects the current
-- transaction and never survives into later sessions.

-- 5.2 GIN Role Index: constant-time JSONB role membership pre-filter
-- Uses the default jsonb_ops operator class because the RBAC queries use the
-- key-existence operator ?| (allowed_roles ?| $2::text[]), which jsonb_path_ops
-- does NOT support (path_ops accelerates only @>, @?, @@).
CREATE INDEX IF NOT EXISTS idx_documents_allowed_roles_gin 
ON documents 
USING gin (allowed_roles);

-- 5.3 Unique / B-Tree Index on file_hash for cryptographic de-duplication
CREATE INDEX IF NOT EXISTS idx_documents_file_hash 
ON documents (file_hash);

-- 5.4 Foreign Key Index for low-latency joins and cascading operations
CREATE INDEX IF NOT EXISTS idx_chunks_document_id 
ON document_chunks (document_id);

-- 5.5 Chunk Sequence Index
CREATE INDEX IF NOT EXISTS idx_chunks_document_seq 
ON document_chunks (document_id, chunk_index);

-- 5.6 GIN Full-Text Search Index: sparse keyword matching and lexical search
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv 
ON document_chunks 
USING gin (tsv);

-- 5.7 Transactional Outbox & Distributed Worker Queue (FOR UPDATE SKIP LOCKED)
CREATE TABLE sdlc_outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_key VARCHAR(128) NOT NULL UNIQUE,
    aggregate_type VARCHAR(64) NOT NULL DEFAULT 'sdlc_webhook',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    locked_by VARCHAR(128),
    locked_at TIMESTAMP WITH TIME ZONE,
    attempts INT NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_sdlc_outbox_pending
ON sdlc_outbox_events (created_at ASC)
WHERE status = 'PENDING';

-- 5.8 LangGraph PostgreSQL Checkpoint Persistence (PostgresSaver Crash-Resilient Resume)
CREATE TABLE sdlc_workflow_checkpoints (
    thread_id VARCHAR(255) NOT NULL,
    checkpoint_ns VARCHAR(255) NOT NULL DEFAULT '',
    checkpoint_id VARCHAR(255) NOT NULL,
    parent_checkpoint_id VARCHAR(255),
    checkpoint_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_sdlc_checkpoints_thread
ON sdlc_workflow_checkpoints (thread_id, created_at DESC);

-- 5.9 Token Consumption Ledger & Managed Budget Limits
CREATE TABLE token_consumption_ledger (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    caller_id VARCHAR(128) NOT NULL,
    model VARCHAR(100) NOT NULL DEFAULT 'gpt-4o',
    prompt_tokens INT NOT NULL DEFAULT 0,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens INT NOT NULL,
    operation_type VARCHAR(64) NOT NULL DEFAULT 'rag_query',
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_token_ledger_caller_time
ON token_consumption_ledger (caller_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_token_ledger_created_at
ON token_consumption_ledger (created_at DESC);

CREATE TABLE token_managed_limits (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    caller_id VARCHAR(128) NOT NULL UNIQUE,
    max_budget_tokens BIGINT NOT NULL DEFAULT 50000,
    current_tokens BIGINT NOT NULL DEFAULT 0,
    enforce_limit BOOLEAN NOT NULL DEFAULT TRUE,
    is_blocked BOOLEAN NOT NULL DEFAULT FALSE,
    tier VARCHAR(32) NOT NULL DEFAULT 'standard',
    reset_interval VARCHAR(32) NOT NULL DEFAULT 'cumulative',
    last_reset_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Trigger for token_managed_limits updated_at
DROP TRIGGER IF EXISTS trg_token_managed_limits_updated_at ON token_managed_limits;
CREATE TRIGGER trg_token_managed_limits_updated_at
    BEFORE UPDATE ON token_managed_limits
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE INDEX IF NOT EXISTS idx_token_limits_caller
ON token_managed_limits (caller_id);

-- ============================================================================
-- 5.10 Shared Chat + Agent Memory (free, self-hosted, pgvector-backed)
-- ============================================================================
-- Shared chat threads/messages and cross-agent memory facts. Every row carries
-- an allowed_roles JSONB column served by the same jsonb_ops GIN ?| pre-filter
-- contract as documents, so shared memory inherits the project's zero-trust
-- RBAC invariants (see app/memory/store.py).

DROP TABLE IF EXISTS shared_chat_messages CASCADE;
DROP TABLE IF EXISTS shared_chat_threads CASCADE;
DROP TABLE IF EXISTS agent_memories CASCADE;

-- Shared chat threads: a conversation visible to every role in allowed_roles.
CREATE TABLE shared_chat_threads (
    thread_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title VARCHAR(255) NOT NULL,
    created_by VARCHAR(128) NOT NULL DEFAULT 'anonymous',
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shared_threads_allowed_roles_gin
    ON shared_chat_threads USING gin (allowed_roles);

CREATE INDEX IF NOT EXISTS idx_shared_threads_created_at
    ON shared_chat_threads (created_at DESC);

-- Shared chat messages: each message embedded for semantic recall.
CREATE TABLE shared_chat_messages (
    message_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    thread_id UUID NOT NULL REFERENCES shared_chat_threads(thread_id) ON DELETE CASCADE,
    role VARCHAR(32) NOT NULL DEFAULT 'user',
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_shared_messages_thread
    ON shared_chat_messages (thread_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_shared_messages_embedding_hnsw
    ON shared_chat_messages
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Agent memories: durable cross-agent facts with semantic embeddings.
-- memory_key is unique so re-learning a fact upserts rather than duplicates.
CREATE TABLE agent_memories (
    memory_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    memory_key VARCHAR(128) NOT NULL UNIQUE,
    value TEXT NOT NULL,
    source VARCHAR(64) NOT NULL DEFAULT 'agent',
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding vector(1536),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agent_memories_allowed_roles_gin
    ON agent_memories USING gin (allowed_roles);

CREATE INDEX IF NOT EXISTS idx_agent_memories_embedding_hnsw
    ON agent_memories
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_agent_memories_key
    ON agent_memories (memory_key);

-- Trigger for shared_chat_threads updated_at
DROP TRIGGER IF EXISTS trg_shared_threads_updated_at ON shared_chat_threads;
CREATE TRIGGER trg_shared_threads_updated_at
    BEFORE UPDATE ON shared_chat_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- Trigger for agent_memories updated_at
DROP TRIGGER IF EXISTS trg_agent_memories_updated_at ON agent_memories;
CREATE TRIGGER trg_agent_memories_updated_at
    BEFORE UPDATE ON agent_memories
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- NOTE: hnsw.iterative_scan / hnsw.max_scan_tuples / hnsw.ef_search are
-- PGC_USERSET session GUCs applied per connection at runtime by
-- DatabaseManager.configure_iterative_scan() (pool init hook + per query).
-- They are deliberately NOT persisted here (see ins_0932def6).

-- Retention support: cleanup of stale shared-chat messages.
-- Call SharedMemoryStore.cleanup_expired_messages(older_than_days) or schedule
-- this as a periodic job (e.g. pg_cron / cron invoking psql) to bound table
-- growth. Uses the covering index idx_shared_messages_thread_cleanup.
CREATE INDEX IF NOT EXISTS idx_shared_messages_thread_cleanup
    ON shared_chat_messages (thread_id, created_at DESC);

CREATE OR REPLACE FUNCTION cleanup_expired_shared_messages(older_than_days INTEGER)
RETURNS INTEGER LANGUAGE plpgsql AS $$
DECLARE
    deleted_count INTEGER;
BEGIN
    DELETE FROM shared_chat_messages
    WHERE created_at < CURRENT_TIMESTAMP - (older_than_days || ' days')::interval;
    GET DIAGNOSTICS deleted_count = ROW_COUNT;
    RETURN deleted_count;
END;
$$;

-- ============================================================================
-- 6. Deterministic Mock Seed Data (100% Offline Testing & Initial Boot)
-- ============================================================================

-- Master Documents Seed
INSERT INTO documents (document_id, title, file_hash, allowed_roles)
VALUES 
(
    'FIN-2026-001',
    'Executive Q3 Financial Audit',
    'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
    '["finance_executive", "compliance_auditor"]'::jsonb
),
(
    'HR-2026-042',
    'Internal Compensation & Benefits Policy',
    'a1b2c3d4e5f60718293a4b5c6d7e8f90123456789abcdef0123456789abcdef0',
    '["hr_manager", "executive"]'::jsonb
),
(
    'ENG-2026-105',
    'Public Engineering Guidelines',
    'fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210',
    '["engineer", "finance_executive", "hr_manager"]'::jsonb
)
ON CONFLICT (document_id) DO NOTHING;

-- Chunks Seed (Vectors generated with deterministic formulas)
INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, embedding)
SELECT 
    d.id,
    'FIN-2026-001_chunk_1',
    0,
    'Operating margins in Q3 increased by 14.2% following the backend modernization and zero-trust identity migration.',
    (SELECT array_agg(0.01 * (i % 5))::vector(1536) FROM generate_series(1, 1536) i)
FROM documents d WHERE d.document_id = 'FIN-2026-001'
ON CONFLICT (chunk_id) DO NOTHING;

INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, embedding)
SELECT 
    d.id,
    'HR-2026-042_chunk_1',
    0,
    'Annual performance bonuses for senior architects are benchmarked against top-tier FinTech industry percentiles.',
    (SELECT array_agg(0.02 * (i % 3))::vector(1536) FROM generate_series(1, 1536) i)
FROM documents d WHERE d.document_id = 'HR-2026-042'
ON CONFLICT (chunk_id) DO NOTHING;

INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, embedding)
SELECT 
    d.id,
    'ENG-2026-105_chunk_1',
    0,
    'All backend microservices must implement asynchronous non-blocking I/O and Pydantic DTO validation.',
    (SELECT array_agg(0.015 * (i % 4))::vector(1536) FROM generate_series(1, 1536) i)
FROM documents d WHERE d.document_id = 'ENG-2026-105'
ON CONFLICT (chunk_id) DO NOTHING;

-- Managed Token Limits Seed
INSERT INTO token_managed_limits (caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked)
VALUES 
    ('global', 100000, 0, TRUE, FALSE),
    ('anonymous', 25000, 0, TRUE, FALSE),
    ('legacy-header-user', 50000, 0, TRUE, FALSE)
ON CONFLICT (caller_id) DO NOTHING;
