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
def secure_search(question: str, role_choice: str):
    authorized_docs = [
        doc for doc in DOCUMENTS_DB 
        if role_choice in doc["allowed_roles"] or "public" in doc["allowed_roles"]
    ]
    is_financial_query = "financial" in question.lower()
    is_authorized_for_finance = role_choice in ["finance_executive", "compliance_auditor"]
    if is_financial_query and not is_authorized_for_finance:
        return None, "🚫 Access Denied: No authorized records found matching your JWT role permissions."
    if not authorized_docs:
        return None, "🚫 Access Denied: No authorized records found matching your JWT role permissions."
    return authorized_docs, None