from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class ModelClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelResponse:
    text: str
    raw: dict[str, Any]
    latency_ms: int


class OpenAIResponsesClient:
    def __init__(self, model: str, api_key: str | None = None, base_url: str | None = None, timeout: int = 120):
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.timeout = timeout
        if not self.api_key:
            raise ModelClientError("OPENAI_API_KEY is not set")

    def complete(self, messages: list[dict[str, Any]], temperature: float = 0.0) -> ModelResponse:
        payload = {
            "model": self.model,
            "input": _responses_input(messages),
            "temperature": temperature,
        }
        started = time.time()
        request = urllib.request.Request(
            f"{self.base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ModelClientError(f"OpenAI API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ModelClientError(f"OpenAI API request failed: {exc.reason}") from exc
        return ModelResponse(text=_extract_output_text(raw), raw=raw, latency_ms=int((time.time() - started) * 1000))


def _responses_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        if role == "tool":
            role = "user"
            content = f"Tool observation for {message.get('name', 'tool')}:\n{content}"
        items.append({"role": role if role in {"system", "user", "assistant"} else "user", "content": content})
    return items


def _extract_output_text(raw: dict[str, Any]) -> str:
    if isinstance(raw.get("output_text"), str):
        return raw["output_text"]
    chunks: list[str] = []
    for item in raw.get("output", []) or []:
        for content in item.get("content", []) or []:
            text = content.get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()
