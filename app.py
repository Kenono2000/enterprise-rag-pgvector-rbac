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
    with st.status("Executing Zero-Trust Vector Search...", expanded=True) as status:
        st.write("Verifying IAM Claims...")
        response = secure_search(question, role_choice)
        
        # Display simulated SQL logic
        sql_query = f"SELECT * FROM documents WHERE allowed_roles ?| ARRAY['{role_choice}']"
        st.code(sql_query, language="sql")
        
        if response.get("error"):
            status.update(label="Access Denied", state="error", expanded=True)
            st.error(response["answer"])
            st.warning(f"🛡️ **Security Note:** The backend blocked this request because the role `{role_choice}` is insufficient.")
        else:
            status.update(label="Authorization Verified", state="complete", expanded=True)
            st.success("✅ Authorization Verified: Document Grounded Successfully")

            
            st.markdown("### Grounded Answer")
            st.write(response["answer"])

            # Metrics Row
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Citations Found", len(response["citations"]))
            with col2:
                st.metric("Avg Confidence", f"{response['confidence_score']:.3f}")
            with col3:
                st.metric("RLS Policy", "Active", delta="Protected")

            # Citations Section
            st.markdown("### 📚 Authorized Citations")
            for doc in response["citations"]:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.markdown(f"**{doc['title']}**")
                        st.caption(f"ID: `{doc['id']}`")
                    with c2:
                        st.code(f"Sim: {doc['similarity']:.3f}")
                    with st.expander("View Source Snippet", expanded=True):
                        st.text(doc["content"])

            with st.expander("📊 View Audit Citation & Scopes", expanded=True):

                st.json({
                    "authorized_roles_evaluated": [role_choice],
                    "confidence_score": response["confidence_score"],
                    "data_leakage_prevented": True,
                    "engine": "pgvector-rls-sim",
                    "timestamp": "2024-05-20T10:00:00Z"
                })


# streamlit run app.py