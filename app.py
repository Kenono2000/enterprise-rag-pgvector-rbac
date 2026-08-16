"""
Public Interactive Demo: Zero-Trust Enterprise RAG
By Ken Wong | Senior AI Solutions Architect
"""
import streamlit as st
import json

st.set_page_config(
    page_title="Zero-Trust RAG Demo | Ken Wong",
    page_icon="🛡️",
    layout="centered"
)

st.title("🛡️ Zero-Trust Enterprise RAG")
st.markdown("### Interactive In-Database RBAC & Vector Search Demo")
st.caption("Architected by **Ken Wong** | [LinkedIn Profile](https://linkedin.com/in/kenwong-architect) | [GitHub Repository](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac)")

st.divider()

# 1. Identity Selector
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

# 2. Database Documents Knowledge Base
DOCUMENTS_DB = [
    {
        "id": "FIN-2026-001",
        "title": "Executive Q3 Financial Audit",
        "content": "Operating margins in Q3 increased by 14.2% following the backend modernization and zero-trust identity migration.",
        "allowed_roles": ["finance_executive", "compliance_auditor"],
        "similarity": 0.894
    },
    {
        "id": "HR-2026-042",
        "title": "Internal Compensation & Bonus Policy",
        "content": "Annual performance bonuses for senior architects are benchmarked against top-tier FinTech percentiles.",
        "allowed_roles": ["hr_manager", "executive"],
        "similarity": 0.862
    },
    {
        "id": "ENG-2026-105",
        "title": "Public Engineering Standards",
        "content": "All backend microservices must implement asynchronous non-blocking I/O and Pydantic DTO contracts.",
        "allowed_roles": ["public", "engineer", "finance_executive", "hr_manager", "public_guest"],
        "similarity": 0.910
    }
]

# 3. Query Section
st.subheader("2. Secure Grounded Retrieval")
question = st.text_input("Enter Question:", value="What were the Q3 financial results and margins?")

if st.button("🚀 Execute Zero-Trust Vector Search", type="primary"):
    st.write("---")
    
    # In-Database RBAC Simulation (?| JSONB Intersection)
    authorized_docs = [
        doc for doc in DOCUMENTS_DB 
        if role_choice in doc["allowed_roles"] or "public" in doc["allowed_roles"]
    ]

    st.markdown("#### 🔍 Database Execution Trace")
    st.code(f"""SELECT title, content, similarity \nFROM enterprise_documents \nWHERE allowed_roles ?| ARRAY['{role_choice}'] \nORDER BY embedding <=> query_vector LIMIT 3;""", language="sql")

    if not authorized_docs or (role_choice not in ["finance_executive", "compliance_auditor"] and "financial" in question.lower()):
        st.error("🚫 Access Denied: No authorized records found matching your JWT role permissions.")
        st.warning("Shift-Left Security prevented unauthorized data from reaching the LLM context.")
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