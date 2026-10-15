"""
app/config.py
-------------
Centralized configuration and environment variable validation using Pydantic BaseSettings.
Validates database connection, authentication, and observability credentials at application startup.
"""

from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database Configuration
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="PostgreSQL connection string with pgvector extension enabled",
    )

    # Multi-Cloud Backend Provider Switcher: 'pgvector', 'azure', 'gcp', 'databricks'
    RETRIEVAL_BACKEND: str = Field(
        default="pgvector",
        description="Active vector retrieval backend: 'pgvector', 'azure', 'gcp', or 'databricks'",
    )

    # Azure AI Configuration
    AZURE_OPENAI_ENDPOINT: Optional[str] = Field(default=None, description="Azure OpenAI Endpoint")
    AZURE_OPENAI_API_KEY: Optional[str] = Field(default=None, description="Azure OpenAI API Key")
    AZURE_OPENAI_API_VERSION: str = Field(default="2024-06-01", description="Azure OpenAI API Version")
    AZURE_OPENAI_CHAT_DEPLOYMENT: str = Field(default="gpt-4o", description="Azure OpenAI Chat Deployment")
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str = Field(default="text-embedding-3-large", description="Azure OpenAI Embedding Deployment")
    AZURE_SEARCH_ENDPOINT: Optional[str] = Field(default=None, description="Azure AI Search Endpoint")
    AZURE_SEARCH_API_KEY: Optional[str] = Field(default=None, description="Azure AI Search API Key")
    AZURE_SEARCH_INDEX_NAME: str = Field(default="enterprise-documents-index", description="Azure AI Search Index Name")

    # Google Cloud Vertex AI / BigQuery Configuration
    GCP_PROJECT_ID: Optional[str] = Field(default=None, description="Google Cloud Project ID")
    GCP_REGION: str = Field(default="us-central1", description="Google Cloud Region for Vertex AI")
    GCP_INDEX_ENDPOINT_ID: Optional[str] = Field(default=None, description="Vertex AI Vector Search Index Endpoint ID")
    GCP_DEPLOYED_INDEX_ID: str = Field(default="enterprise_rag_index", description="Vertex AI Deployed Index ID")
    GCP_VECTOR_STORE: str = Field(default="vertex_ai", description="GCP vector store: 'vertex_ai' or 'bigquery'")
    GEMINI_API_KEY: Optional[str] = Field(default=None, description="Google Gemini API Key")

    # Databricks Mosaic AI Configuration
    DATABRICKS_HOST: Optional[str] = Field(default=None, description="Databricks workspace host")
    DATABRICKS_TOKEN: Optional[str] = Field(default=None, description="Databricks Personal Access Token (PAT)")
    DATABRICKS_VECTOR_SEARCH_ENDPOINT_NAME: str = Field(default="enterprise_vs_endpoint", description="Databricks Vector Search endpoint name")
    DATABRICKS_INDEX_NAME: str = Field(default="main.enterprise_rag.document_chunks_index", description="Databricks Unity Catalog 3-level index name")

    # Google OAuth 2.0 & RBAC
    REQUIRE_GOOGLE_AUTH: bool = Field(
        default=False,
        description="Enforce Google ID token verification via JWKS (True in production)",
    )
    GOOGLE_CLIENT_ID: Optional[str] = Field(
        default=None,
        description="Google Cloud OAuth 2.0 Web Client ID",
    )
    GOOGLE_CLIENT_SECRET: Optional[str] = Field(
        default=None,
        description="Google Cloud OAuth 2.0 Client Secret (optional for PKCE)",
    )
    GOOGLE_REDIRECT_URI: str = Field(
        default="http://localhost:8501/",
        description="Registered OAuth 2.0 redirect URI",
    )

    # Autonomous SDLC Webhook
    GITHUB_WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="Secret key to verify incoming GitHub webhook HMAC-SHA256 signatures",
    )

    # Runtime & Observability
    ENVIRONMENT: str = Field(
        default="development",
        description="Environment name: development, staging, or production",
    )
    HOST: str = Field(default="0.0.0.0", description="FastAPI host binding")
    PORT: int = Field(default=8000, description="FastAPI port binding")
    OTEL_ENABLED: bool = Field(
        default=False,
        description="Flag to enable OpenTelemetry / distributed tracing metrics",
    )
    OTEL_SERVICE_NAME: str = Field(
        default="enterprise-rag-pgvector-rbac",
        description="OpenTelemetry service name attribute",
    )


settings = Settings()
