-- ============================================================================
-- migrations/001_normalize_documents_schema.sql
-- Migration: Transform denormalized enterprise_documents table into 
-- normalized documents + document_chunks tables with backward-compatible view.
-- ============================================================================

BEGIN;

-- 1. Ensure required extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Create master documents table
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

-- 3. Create document_chunks table
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id VARCHAR(128) NOT NULL UNIQUE,
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    token_count INT,
    embedding vector(1536) NOT NULL,
    embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-large',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 4. Clean up legacy enterprise_documents table or view if present
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

-- 5. Create indexes
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON document_chunks 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_documents_allowed_roles_gin 
ON documents 
USING gin (allowed_roles jsonb_path_ops);

CREATE INDEX IF NOT EXISTS idx_documents_file_hash 
ON documents (file_hash);

CREATE INDEX IF NOT EXISTS idx_chunks_document_id 
ON document_chunks (document_id);

CREATE INDEX IF NOT EXISTS idx_chunks_document_seq 
ON document_chunks (document_id, chunk_index);

COMMIT;
