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
        "allowed_roles": ["engineer", "finance_executive", "hr_manager"],
        "similarity": 0.910
    }

]

def secure_search(question: str, user_role: str) -> dict:
    """
    Simulates the RAGResponse from main.py
    """
    authorized_docs = []
    for doc in DOCUMENTS_DB:
        # Simulate JSONB overlap logic: ?| ARRAY[...]
        if user_role in doc["allowed_roles"] or "public" in doc["allowed_roles"]:
            authorized_docs.append(doc)
            
    if not authorized_docs:
        return {
            "answer": "No authorized documentation found matching your security credentials.",
            "citations": [],
            "confidence_score": 0.0,
            "error": f"User role '{user_role}' is not authorized."
        }
        
    # Sort by mock similarity
    authorized_docs.sort(key=lambda x: x["similarity"], reverse=True)
    top_docs = authorized_docs[:3]
    
    avg_conf = sum(d["similarity"] for d in top_docs) / len(top_docs)
    
    return {
        "answer": f"Based on the authorized documents ({', '.join([d['title'] for d in top_docs])}), the system confirms that security protocols and operational metrics are within expected parameters.",
        "citations": top_docs,
        "confidence_score": round(avg_conf, 3),
        "error": None
    }