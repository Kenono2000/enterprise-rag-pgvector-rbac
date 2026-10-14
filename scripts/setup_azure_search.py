"""
scripts/setup_azure_search.py
-----------------------------
Creates or updates the Azure AI Search index with vector search profiles,
HNSW vector configuration, Bing Semantic Re-ranker, and Zero-Trust RBAC role filtering.
"""
from __future__ import annotations

import os
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SimpleField,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    VectorSearchProfile,
    SemanticConfiguration,
    SemanticPrioritizedFields,
    SemanticField,
    SemanticSearch,
)


def create_index(recreate: bool = False) -> SearchIndex:
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    key = os.getenv("AZURE_SEARCH_API_KEY")
    index_name = os.getenv("AZURE_SEARCH_INDEX_NAME", "enterprise-documents-index")
    vector_dims = int(os.getenv("AZURE_SEARCH_VECTOR_DIMENSIONS", "1536"))

    if not endpoint or not key:
        raise ValueError("❌ AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY must be configured in environment.")

    client = SearchIndexClient(endpoint=endpoint, credential=AzureKeyCredential(key))

    if recreate:
        try:
            client.delete_index(index_name)
            print(f"[RECREATE] Deleted existing index: {index_name}")
        except Exception as e:
            print(f"Index did not exist or could not be deleted: {e}")

    # Configure HNSW vector search profile
    vector_search = VectorSearch(
        algorithms=[HnswAlgorithmConfiguration(name="hnsw-config")],
        profiles=[VectorSearchProfile(name="vector-profile", algorithm_configuration_name="hnsw-config")],
    )

    # Configure Semantic Ranker (Bing AI re-ranking)
    semantic_config = SemanticConfiguration(
        name="semantic-config",
        prioritized_fields=SemanticPrioritizedFields(
            title_field=SemanticField(field_name="title"),
            content_fields=[SemanticField(field_name="content")],
        ),
    )

    fields = [
        SimpleField(name="id", type=SearchFieldDataType.String, key=True),
        SearchableField(name="document_id", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="title", type=SearchFieldDataType.String, filterable=True),
        SearchableField(name="content", type=SearchFieldDataType.String),
        SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, filterable=True),
        # Collection field for multi-role Zero-Trust RBAC:
        SimpleField(
            name="allowed_roles",
            type=SearchFieldDataType.Collection(SearchFieldDataType.String),
            filterable=True,
        ),
        # 1536 dimensions matching PostgreSQL pgvector embeddings
        SearchField(
            name="embedding",
            type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
            searchable=True,
            vector_search_dimensions=vector_dims,
            vector_search_profile_name="vector-profile",
        ),
    ]

    index = SearchIndex(
        name=index_name,
        fields=fields,
        vector_search=vector_search,
        semantic_search=SemanticSearch(configurations=[semantic_config]),
    )

    try:
        created_or_updated = client.create_or_update_index(index)
    except Exception as e:
        if "Cannot change" in str(e) or "dimensions" in str(e).lower():
            print(f"Index dimension/schema changed, deleting and recreating index {index_name}...")
            client.delete_index(index_name)
            created_or_updated = client.create_or_update_index(index)
        else:
            raise

    print(f"[OK] Successfully created / updated Azure AI Search index: {index_name}")
    return created_or_updated


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Create or update Azure AI Search index.")
    parser.add_argument("--recreate", action="store_true", help="Delete and recreate index if it exists.")
    args = parser.parse_args()
    create_index(recreate=args.recreate)
