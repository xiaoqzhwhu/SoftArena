from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ResearchClient:
    base_url: str
    api_key: str
    model: str = "gpt-5.5"
    timeout_sec: int = 45

    @classmethod
    def from_env(cls) -> "ResearchClient":
        api_key = os.environ.get("RESEARCH_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("RESEARCH_API_KEY is required for online searchAgent runs")
        return cls(
            base_url=os.environ.get("RESEARCH_BASE_URL", "http://localhost:3003/v1").strip(),
            api_key=api_key,
            model=os.environ.get("RESEARCH_MODEL", "gpt-5.5").strip(),
            timeout_sec=int(os.environ.get("RESEARCH_TIMEOUT_SEC", "45")),
        )

    def responses(self, prompt: str, *, web_search: bool = False, max_output_tokens: int = 2400) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [{"role": "user", "content": prompt}],
            "max_output_tokens": max_output_tokens,
        }
        if web_search:
            payload["tools"] = [{"type": os.environ.get("RESEARCH_WEB_SEARCH_TOOL", "web_search").strip() or "web_search"}]
        try:
            return self._post_responses(payload)
        except RuntimeError as exc:
            if not web_search or payload.get("tools") == [{"type": "web_search_preview"}]:
                raise
            fallback = dict(payload)
            fallback["tools"] = [{"type": "web_search_preview"}]
            try:
                return self._post_responses(fallback)
            except RuntimeError:
                raise exc

    def _post_responses(self, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            self.base_url.rstrip("/") + "/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_sec) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"research model HTTP {exc.code}: {body[:1200]}") from exc


def extract_response_text(payload: dict[str, Any]) -> str:
    if isinstance(payload.get("text"), dict):
        value = payload["text"].get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    parts: list[str] = []
    for item in payload.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []) or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "\n".join(part for part in parts if part).strip()


def extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {"items": data}
    except json.JSONDecodeError:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(raw[start : end + 1])
        return data if isinstance(data, dict) else {"items": data}
    raise ValueError("response did not contain a JSON object")
