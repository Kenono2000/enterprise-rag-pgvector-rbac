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

    # LLM & Vector Embeddings
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API key for text-embedding-3-large and gpt-4o",
    )

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
