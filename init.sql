-- 1. Enable Extensions
-- pgvector: Allows storing and searching high-dimensional vectors (embeddings)
-- uuid-ossp: Provides functions to generate globally unique identifiers (UUIDs)
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 2. Documents & Chunks Table
-- This table stores the processed document text along with its metadata and vector representation.
CREATE TABLE IF NOT EXISTS enterprise_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL, -- The actual text chunk used for RAG
    -- allowed_roles: JSONB array used for Role-Based Access Control (RBAC).
    -- This ensures users only retrieve documents they are authorized to see.
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    -- embedding: 1536-dimensional vector (standard for models like OpenAI's text-embedding-3-small)
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. Performance Indexing
-- Fast JSONB index for RBAC (?| operator)
-- GIN (Generalized Inverted Index) allows instant lookup of roles within the JSONB array.
CREATE INDEX IF NOT EXISTS idx_docs_allowed_roles 
ON enterprise_documents USING GIN (allowed_roles);

-- HNSW (Hierarchical Navigable Small World) Cosine Distance Index
-- Optimized for fast 'Approximate Nearest Neighbor' search at scale.
-- vector_cosine_ops: Uses Cosine Similarity, the standard metric for RAG.
CREATE INDEX IF NOT EXISTS idx_docs_hnsw_embedding 
ON enterprise_documents 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 4. Seed Sample Data
-- Pre-populated with dummy 1536d vectors for demonstration.
-- The (SELECT array_agg...) subquery generates a dummy vector mathematically for testing.
INSERT INTO enterprise_documents (document_id, title, content, allowed_roles, embedding)
VALUES 
(
    'FIN-2026-001',
    'Executive Q3 Financial Audit',
    'Operating margins in Q3 increased by 14.2% following the backend modernization and zero-trust identity migration.',
    '["finance_executive", "compliance_auditor"]'::jsonb,
    (SELECT array_agg(0.01 * (i % 5))::vector(1536) FROM generate_series(1, 1536) i)
),
(
    'HR-2026-042',
    'Internal Compensation & Benefits Policy',
    'Annual performance bonuses for senior architects are benchmarked against top-tier FinTech industry percentiles.',
    '["hr_manager", "executive"]'::jsonb,
    (SELECT array_agg(0.02 * (i % 3))::vector(1536) FROM generate_series(1, 1536) i)
),
(
    'ENG-2026-105',
    'Public Engineering Guidelines',
    'All backend microservices must implement asynchronous non-blocking I/O and Pydantic DTO validation.',
    '["public", "engineer", "finance_executive", "hr_manager"]'::jsonb,
    (SELECT array_agg(0.015 * (i % 4))::vector(1536) FROM generate_series(1, 1536) i)
);