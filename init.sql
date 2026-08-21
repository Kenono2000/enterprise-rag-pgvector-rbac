CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE IF NOT EXISTS enterprise_documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(100) NOT NULL,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL, 
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_docs_allowed_roles 
ON enterprise_documents USING GIN (allowed_roles);
CREATE INDEX IF NOT EXISTS idx_docs_hnsw_embedding 
ON enterprise_documents 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);
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