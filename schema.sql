-- ============================================================================
-- schema.sql
-- PostgreSQL 16 + pgvector Normalized Architecture with Dual Indexing
-- Consolidated Database Initialization & Migration Script
-- ============================================================================

-- 1. Create Required Extensions (Idempotent)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Master Documents Table (Metadata, Governance, De-duplication)
CREATE TABLE IF NOT EXISTS documents (
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

-- 3. Document Chunks Table (Vector Embeddings, 16-bit halfvec Compaction, Content, Chunk Sequence)
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id VARCHAR(128) NOT NULL UNIQUE,
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    token_count INT,
    embedding vector(1536) NOT NULL,
    embedding_halfvec halfvec(1536) GENERATED ALWAYS AS (embedding::halfvec(1536)) STORED,
    embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-large',
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Clean up / Migrate legacy enterprise_documents table or views if present
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables 
        WHERE table_schema = CURRENT_SCHEMA() 
          AND table_name = 'enterprise_documents' 
          AND table_type = 'BASE TABLE'
    ) THEN
        -- Migrate master documents
        INSERT INTO documents (document_id, title, allowed_roles, created_at)
        SELECT 
            document_id,
            title,
            allowed_roles,
            created_at
        FROM enterprise_documents
        ON CONFLICT (document_id) DO UPDATE
        SET title = EXCLUDED.title, allowed_roles = EXCLUDED.allowed_roles;

        -- Migrate chunks
        INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, embedding, embedding_model, created_at)
        SELECT 
            d.id,
            ed.document_id,
            0,
            ed.content,
            ed.embedding,
            COALESCE(ed.embedding_model, 'text-embedding-3-large'),
            ed.created_at
        FROM enterprise_documents ed
        JOIN documents d ON ed.document_id = d.document_id
        ON CONFLICT (chunk_id) DO UPDATE
        SET content = EXCLUDED.content, embedding = EXCLUDED.embedding;

        DROP TABLE enterprise_documents CASCADE;
    END IF;
END $$;

-- Drop any legacy views or triggers if they exist
DROP TRIGGER IF EXISTS trg_enterprise_docs_io_insert ON enterprise_documents;
DROP VIEW IF EXISTS enterprise_documents CASCADE;
DROP FUNCTION IF EXISTS trg_enterprise_documents_upsert CASCADE;

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
DO $$
BEGIN
    EXECUTE 'SET hnsw.iterative_scan = ''relaxed_order''';
    EXECUTE 'SET hnsw.max_scan_tuples = 20000';
EXCEPTION WHEN OTHERS THEN
    NULL; -- Gracefully no-op on pgvector < 0.8.0
END $$;

-- 5.2 GIN Role Index: constant-time JSONB role membership pre-filter
CREATE INDEX IF NOT EXISTS idx_documents_allowed_roles_gin 
ON documents 
USING gin (allowed_roles jsonb_path_ops);

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
CREATE TABLE IF NOT EXISTS sdlc_outbox_events (
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
CREATE TABLE IF NOT EXISTS sdlc_workflow_checkpoints (
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
CREATE TABLE IF NOT EXISTS token_consumption_ledger (
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

CREATE TABLE IF NOT EXISTS token_managed_limits (
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

CREATE INDEX IF NOT EXISTS idx_token_limits_caller
ON token_managed_limits (caller_id);

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
