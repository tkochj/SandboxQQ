import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


@dataclass
class ToolCall:
    id: str = ""
    name: str = ""
    arguments: dict = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)

    @classmethod
    def from_openai(cls, data: dict):
        choice = data["choices"][0]
        msg = choice.get("message", {})
        content = msg.get("content") or ""
        finish = choice.get("finish_reason", "")
        usage = data.get("usage", {})

        tool_calls = []
        for tc in msg.get("tool_calls", []):
            try:
                args = json.loads(tc["function"]["arguments"])
            except (json.JSONDecodeError, KeyError):
                args = {}
            tool_calls.append(ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=args,
            ))

        return cls(content=content, tool_calls=tool_calls,
                   finish_reason=finish, usage=usage)


class Provider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def close(self):
        ...
