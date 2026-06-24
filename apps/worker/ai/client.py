"""
LiteLLM wrapper with retry, budget tracking, and structured output support.
"""
import json
from typing import Any, Type, TypeVar
import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential
from pydantic import BaseModel

from config import settings

log = structlog.get_logger()
T = TypeVar("T", bound=BaseModel)


class AIClient:
    def __init__(self):
        self.base_url = settings.litellm_base_url
        self.api_key = settings.litellm_api_key
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=120.0,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def complete(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 2000,
    ) -> str:
        response = await self._client.post("/chat/completions", json={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        log.info("llm_complete",
                 model=model,
                 input_tokens=data.get("usage", {}).get("prompt_tokens"),
                 output_tokens=data.get("usage", {}).get("completion_tokens"))
        return content

    async def complete_structured(
        self,
        model: str,
        messages: list[dict],
        output_model: Type[T],
        temperature: float = 0.2,
    ) -> T:
        schema = output_model.model_json_schema()
        system_suffix = f"\n\nRespond with valid JSON matching this schema:\n{json.dumps(schema, indent=2)}"

        if messages and messages[0]["role"] == "system":
            messages[0]["content"] += system_suffix
        else:
            messages.insert(0, {"role": "system", "content": "You are a helpful assistant." + system_suffix})

        raw = await self.complete(model=model, messages=messages, temperature=temperature)

        # Extract JSON from response (handles markdown code blocks)
        clean = raw.strip()
        if clean.startswith("```"):
            lines = clean.split("\n")
            clean = "\n".join(lines[1:-1])

        return output_model.model_validate_json(clean)

    async def close(self):
        await self._client.aclose()


_client: AIClient | None = None


def get_client() -> AIClient:
    global _client
    if _client is None:
        _client = AIClient()
    return _client
