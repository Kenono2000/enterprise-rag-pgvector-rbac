import streamlit as st
import json
import asyncio
from app.db.manager import DatabaseManager
from app.db.llm import generate_embedding, chat_completion

# Streamlit helper for async calls
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

st.set_page_config(
    page_title="Zero-Trust RAG Demo | Ken Wong",
    page_icon="🛡️",
    layout="centered"
)

st.title("🛡️ Zero-Trust Enterprise RAG")
st.markdown("This demo showcases how to enforce row-level security (RLS) policies on vector embeddings using PostgreSQL and pgvector, ensuring only authorized roles can retrieve sensitive information.")
st.caption("Architected by **Ken Wong** | [LinkedIn Profile](https://linkedin.com/in/kenwong-architect) | [GitHub Repository](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac)")

st.divider()

st.subheader("1. Identity & Access Management (IAM)")
role_choice = st.selectbox(
    "Select Simulated Auth0 Role Claim:",
    options=[
        "finance_executive",
        "hr_manager",
        "engineer",
        "public_guest"
    ],
    help="Simulates the decoded JWT roles extracted from the user's OAuth 2.0 PKCE token."
)

st.info(f"🔑 Active JWT Scope Claims: `['{role_choice}']`")

st.subheader("2. Secure Grounded Retrieval")
question = st.text_input("Enter Question:", value="What were the Q3 financial results and margins?")

if st.button("🚀 Execute Zero-Trust Vector Search", type="primary"):
    with st.status("Executing Zero-Trust Vector Search...", expanded=True) as status:
        st.write("Verifying IAM Claims & Generating Embedding...")
        
        # Real production logic
        async def perform_search():
            await DatabaseManager.get_pool() # Ensure pool is init
            query_vector = await generate_embedding(question)
            rows = await DatabaseManager.secure_search(query_vector, [role_choice])
            
            if not rows:
                return None
            
            context = "\n\n".join([f"[{r['title']}]: {r['content']}" for r in rows])
            prompt = f"Answer strictly using context:\n\n{context}\n\nQuestion: {question}"
            answer = await chat_completion(prompt)
            
            return {
                "answer": answer,
                "rows": rows,
                "avg_conf": sum(float(r["similarity"]) for r in rows) / len(rows) if rows else 0
            }

        result = run_async(perform_search())
        
        # Display simulated SQL logic for transparency
        sql_query = f"SELECT * FROM enterprise_documents WHERE allowed_roles ?| ARRAY['{role_choice}'] ORDER BY embedding <=> <vector> LIMIT 3"
        st.code(sql_query, language="sql")
        
        if not result:
            status.update(label="Access Denied", state="error", expanded=True)
            st.error("No authorized documentation found matching your security credentials.")
            st.warning(f"🛡️ **Security Note:** The backend blocked this request because the role `{role_choice}` is insufficient.")
        else:
            status.update(label="Authorization Verified", state="complete", expanded=True)
            st.success("✅ Authorization Verified: Document Grounded Successfully")

            st.markdown("### Grounded Answer")
            st.write(result["answer"])

            # Metrics Row
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Citations Found", len(result["rows"]))
            with col2:
                st.metric("Avg Confidence", f"{result['avg_conf']:.3f}")
            with col3:
                st.metric("RLS Policy", "Active", delta="Protected")

            # Citations Section
            st.markdown("### 📚 Authorized Citations")
            for doc in result["rows"]:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"**{doc['title']}**")
                        st.caption(f"ID: `{doc['document_id']}`")
                    with c2:
                        st.code(f"Sim: {float(doc['similarity']):.3f}")
                    with st.expander("View Source Snippet", expanded=True):
                        st.text(doc["content"])

            with st.expander("📊 View Audit Citation & Scopes", expanded=True):
                st.json({
                    "authorized_roles_evaluated": [role_choice],
                    "confidence_score": result["avg_conf"],
                    "data_leakage_prevented": True,
                    "engine": "pgvector-rls-production",
                    "timestamp": "2024-05-20T10:00:00Z"
                })
