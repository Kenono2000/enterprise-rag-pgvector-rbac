import asyncio
import os
from openai import AsyncOpenAI
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

openai_api_key = os.getenv("OPENAI_API_KEY")
_openai_clients: dict[asyncio.AbstractEventLoop, AsyncOpenAI] = {}


def get_openai_client() -> AsyncOpenAI | None:
    """Return an AsyncOpenAI client scoped to the currently running event loop."""
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


async def generate_embedding(text: str, dimensions: int = 1536) -> list[float]:
    client = get_openai_client()
    if client:
        response = await client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=dimensions
        )
        return response.data[0].embedding

    else:
        # Mock embedding for local dev/testing
        return [0.01 * (i % 5) for i in range(dimensions)]

async def chat_completion(prompt: str, model: str = "gpt-4o", temperature: float = 0.0) -> str:
    client = get_openai_client()
    if client:
        completion = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature
        )
        return completion.choices[0].message.content
    return f"[Local Mock Response for]: {prompt[:50]}..."


async def chat_completion_stream(prompt: str, model: str = "gpt-4o", temperature: float = 0.0):
    """Async generator yielding LLM response tokens in real-time."""
    client = get_openai_client()
    if client:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        async for chunk in stream:
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
    if openai_api_key:
        from openai import OpenAI
        sync_client = OpenAI(api_key=openai_api_key)
        stream = sync_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            content = chunk.choices[0].delta.content or ""
            if content:
                yield content
    else:
        mock_text = f"[Local Mock Response for]: {prompt[:50]}..."
        for word in mock_text.split(" "):
            yield word + " "


