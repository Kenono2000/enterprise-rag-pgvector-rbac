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

-- 3. Document Chunks Table (Vector Embeddings, Content, Chunk Sequence)
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id VARCHAR(128) NOT NULL UNIQUE,
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    token_count INT,
    embedding vector(1536) NOT NULL,
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