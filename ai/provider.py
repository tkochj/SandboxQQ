import asyncio
import json
import logging
import hashlib
from typing import Optional, List, Dict, Any

import httpx

from ai.config import AIConfig, ProviderConfig
from ai.base import Provider, LLMResponse, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider(Provider):
    def __init__(self, config):
        self.config = config
        self._http: Optional[httpx.AsyncClient] = None
        self._http_loop_id: int = 0
        self._api_key = getattr(config, "api_key", "")
        self._api_url = getattr(config, "api_url", "https://api.openai.com/v1")
        self._model = getattr(config, "model", "gpt-4o")
        self._temperature = getattr(config, "temperature", 0.7)
        self._max_tokens = getattr(config, "max_tokens", 4096)

    async def _get_client(self) -> httpx.AsyncClient:
        current_loop = id(asyncio.get_running_loop())
        if self._http is not None and not self._http.is_closed and self._http_loop_id == current_loop:
            return self._http
        if self._http is not None:
            try:
                await self._http.aclose()
            except Exception:
                pass
        self._http = httpx.AsyncClient(timeout=60.0)
        self._http_loop_id = current_loop
        return self._http

    async def chat(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._api_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            return LLMResponse.from_openai(resp.json())
        except httpx.HTTPStatusError as e:
            logger.error(f"AI API error: {e.response.status_code} {e.response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            raise

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()
            self._http = None


class ProviderManager:
    def __init__(self):
        self._providers: Dict[str, Provider] = {}

    def _config_key(self, api_url: str, api_key: str, model: str, provider_type: str) -> str:
        raw = f"{api_url}|{api_key}|{model}|{provider_type}"
        return hashlib.md5(raw.encode()).hexdigest()

    def get_or_create(self, config: AIConfig, pc: Optional[ProviderConfig] = None) -> Provider:
        if pc:
            key = self._config_key(pc.api_url, pc.api_key, pc.model, pc.provider)
            if key in self._providers:
                return self._providers[key]
            provider = OpenAIProvider(pc)
        else:
            key = self._config_key(config.api_url, config.api_key, config.model, config.provider)
            if key in self._providers:
                return self._providers[key]
            provider = OpenAIProvider(config)
        self._providers[key] = provider
        return provider

    def get_by_name(self, config: AIConfig, name: str) -> Optional[Provider]:
        for p in config.providers:
            if p.name == name and p.api_key:
                return self.get_or_create(config, p)
        return None

    async def close_all(self):
        for provider in self._providers.values():
            await provider.close()
        self._providers.clear()


class AIMessage:
    def __init__(self, role: str, content: str = "",
                 tool_calls: Optional[List[ToolCall]] = None,
                 tool_call_id: Optional[str] = None,
                 name: Optional[str] = None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id
        self.name = name

    def to_dict(self) -> dict:
        d = {"role": self.role}
        if self.content:
            d["content"] = self.content
        if self.tool_calls:
            d["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_response(cls, data: dict):
        role = data.get("role", "assistant")
        content = data.get("content") or ""
        tool_calls_data = data.get("tool_calls", [])
        tool_calls = []
        for tc in tool_calls_data:
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=args,
            ))
        return cls(role=role, content=content, tool_calls=tool_calls)

    @classmethod
    def tool_result(cls, tool_call_id: str, name: str, result: str):
        return cls(role="tool", content=str(result), tool_call_id=tool_call_id, name=name)


class AIProvider:
    def __init__(self, config: AIConfig):
        self.config = config
        self._http: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is not None:
            if not self._http.is_closed:
                await self._http.aclose()
        self._http = httpx.AsyncClient(timeout=60.0)
        return self._http

    async def chat(
        self,
        messages: List[AIMessage],
        tools: Optional[List[Dict]] = None,
    ) -> AIMessage:
        client = await self._get_client()
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.config.api_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.config.model,
            "messages": [m.to_dict() for m in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            choice = data["choices"][0]
            msg_data = choice["message"]
            return AIMessage.from_response(msg_data)
        except httpx.HTTPStatusError as e:
            logger.error(f"AI API error: {e.response.status_code} {e.response.text[:500]}")
            raise
        except Exception as e:
            logger.error(f"AI request failed: {e}")
            raise

    async def close(self):
        if self._http and not self._http.is_closed:
            await self._http.aclose()
