-- 1. Confirm the thread and message were persisted
SELECT thread_id, title, allowed_roles, created_at
FROM shared_chat_threads;

SELECT message_id, thread_id, role, content, metadata, created_at
FROM shared_chat_messages
ORDER BY created_at ASC;

-- 2. Confirm a cross-agent fact
SELECT memory_id, memory_key, value, source, allowed_roles
FROM agent_memories;

-- 3. Confirm RBAC pre-filter: this should return rows only for roles that overlap allowed_roles
SELECT count(*) FROM shared_chat_messages m
JOIN shared_chat_threads t ON t.thread_id = m.thread_id
WHERE t.allowed_roles ?| ARRAY['engineer']::text[];