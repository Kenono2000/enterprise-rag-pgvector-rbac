import os
from openai import AsyncOpenAI
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

openai_api_key = os.getenv("OPENAI_API_KEY")
openai_client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None

async def generate_embedding(text: str, dimensions: int = 1536) -> list[float]:
    if openai_client:
        response = await openai_client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=dimensions
        )
        return response.data[0].embedding
    else:
        # Mock embedding for local dev/testing
        return [0.01 * (i % 5) for i in range(dimensions)]

async def chat_completion(prompt: str, model: str = "gpt-4o", temperature: float = 0.0) -> str:
    if openai_client:
        completion = await openai_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature
        )
        return completion.choices[0].message.content
    return f"[Local Mock Response for]: {prompt[:50]}..."
