# engine.py
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

def secure_search(question: str, user_role: str) -> tuple[list, str]:
    """
    Simulates in-database RBAC filtering for the MCP demo.
    In production, this is replaced by the asyncpg query in main.py.
    """
    authorized_docs = []
    for doc in DOCUMENTS_DB:
        if user_role in doc["allowed_roles"] or "public" in doc["allowed_roles"]:
            authorized_docs.append(doc)
            
    if not authorized_docs:
        return [], f"User role '{user_role}' is not authorized to view any matching documents."
        
    # Sort by mock similarity
    authorized_docs.sort(key=lambda x: x["similarity"], reverse=True)
    return authorized_docs, ""