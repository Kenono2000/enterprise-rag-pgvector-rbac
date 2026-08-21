import streamlit as st
import json
from engine import secure_search, DOCUMENTS_DB
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
st.info("💡 Data and Security Logic are decoupled from this UI, allowing the same Zero-Trust rules to apply to MCP/AI Agents.")
st.subheader("2. Secure Grounded Retrieval")
question = st.text_input("Enter Question:", value="What were the Q3 financial results and margins?")
if st.button("🚀 Execute Zero-Trust Vector Search", type="primary"):
    st.write("Executing search...")
    authorized_docs, error_msg = secure_search(question, role_choice)
    st.markdown("### Search Results")
    st.code("SELECT * FROM documents WHERE...", language="sql")
    if error_msg:
        st.error(error_msg)
        st.warning("Security Note: The backend blocked this request because the user's role claim is insufficient.")
    else:
        top_doc = authorized_docs[0]
        st.success("✅ Authorization Verified: Document Grounded Successfully")
        st.markdown(f"**Grounded Answer:**")
        st.write(top_doc["content"])
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Source Document", top_doc["title"])
        with col2:
            st.metric("Cosine Similarity Score", f"{top_doc['similarity']}")
        with st.expander("View Audit Citation & Scopes"):
            st.json({
                "document_id": top_doc["id"],
                "allowed_roles": top_doc["allowed_roles"],
                "evaluated_user_role": role_choice,
                "data_leakage_prevented": True
            })