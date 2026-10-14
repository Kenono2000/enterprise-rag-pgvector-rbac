from __future__ import annotations

import asyncio
import os
from openai import AsyncAzureOpenAI, AsyncOpenAI, OpenAI, AzureOpenAI
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

openai_api_key = os.getenv("OPENAI_API_KEY")
azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
azure_openai_api_key = os.getenv("AZURE_OPENAI_API_KEY")
azure_openai_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

_openai_clients: dict[asyncio.AbstractEventLoop, AsyncOpenAI | AsyncAzureOpenAI] = {}


def is_azure_backend() -> bool:
    """Return True if Azure OpenAI should be used."""
    backend = os.getenv("RETRIEVAL_BACKEND", "").lower()
    return (backend == "azure" or bool(azure_openai_endpoint)) and bool(azure_openai_endpoint and azure_openai_api_key)


def get_openai_client() -> AsyncOpenAI | AsyncAzureOpenAI | None:
    """Return an AsyncOpenAI or AsyncAzureOpenAI client scoped to the currently running event loop."""
    if is_azure_backend():
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            client = _openai_clients.get(loop)
            if client is None or client.is_closed():
                client = AsyncAzureOpenAI(
                    azure_endpoint=azure_openai_endpoint,
                    api_key=azure_openai_api_key,
                    api_version=azure_openai_api_version,
                )
                _openai_clients[loop] = client
            return client

        return AsyncAzureOpenAI(
            azure_endpoint=azure_openai_endpoint,
            api_key=azure_openai_api_key,
            api_version=azure_openai_api_version,
        )

    if not openai_api_key:
        return None

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        client = _openai_clients.get(loop)
        if client is None or client.is_closed():
            client = AsyncOpenAI(api_key=openai_api_key)
            _openai_clients[loop] = client
        return client

    return AsyncOpenAI(api_key=openai_api_key)


def _get_embedding_model_or_deployment() -> str:
    if is_azure_backend():
        return os.getenv("AZURE_OPENAI_EMBEDDING_DEPLOYMENT", "text-embedding-3-large")
    return "text-embedding-3-large"


def _get_chat_model_or_deployment(default_model: str = "gpt-4o") -> str:
    if is_azure_backend():
        return os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT", default_model)
    return default_model


async def generate_embedding(text: str, dimensions: int = 1536) -> list[float]:
    client = get_openai_client()
    if client:
        model = _get_embedding_model_or_deployment()
        # For standard OpenAI text-embedding-3-large, dimensions can be customized.
        # For Azure OpenAI, pass dimensions if supported or default to deployment behavior.
        kwargs = {"model": model, "input": text}
        if dimensions:
            kwargs["dimensions"] = dimensions
        response = await client.embeddings.create(**kwargs)
        return response.data[0].embedding

    # Mock embedding for local dev/testing
    return [0.01 * (i % 5) for i in range(dimensions)]


async def chat_completion(prompt: str, model: str = "gpt-4o", temperature: float = 0.0) -> str:
    client = get_openai_client()
    if client:
        target_model = _get_chat_model_or_deployment(model)
        completion = await client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
        )
        return completion.choices[0].message.content
    return f"[Local Mock Response for]: {prompt[:50]}..."


async def chat_completion_stream(prompt: str, model: str = "gpt-4o", temperature: float = 0.0):
    """Async generator yielding LLM response tokens in real-time."""
    client = get_openai_client()
    if client:
        target_model = _get_chat_model_or_deployment(model)
        stream = await client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content
    else:
        # Mock streaming tokens for local dev and testing
        mock_text = f"[Local Mock Response for]: {prompt[:50]}..."
        for word in mock_text.split(" "):
            yield word + " "


def chat_completion_stream_sync(prompt: str, model: str = "gpt-4o", temperature: float = 0.0):
    """Synchronous generator yielding LLM response tokens (compatible with st.write_stream)."""
    if is_azure_backend():
        sync_client = AzureOpenAI(
            azure_endpoint=azure_openai_endpoint,
            api_key=azure_openai_api_key,
            api_version=azure_openai_api_version,
        )
        target_model = _get_chat_model_or_deployment(model)
        stream = sync_client.chat.completions.create(
            model=target_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content
    elif openai_api_key:
        sync_client = OpenAI(api_key=openai_api_key)
        stream = sync_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            if not chunk.choices:
                continue
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content
    else:
        mock_text = f"[Local Mock Response for]: {prompt[:50]}..."
        for word in mock_text.split(" "):
            yield word + " "
