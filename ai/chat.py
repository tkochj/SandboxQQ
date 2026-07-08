import json
import time
import logging
from typing import List, Optional, Callable
from datetime import datetime

from ai.config import AIConfig, SubAgentConfig
from ai.agent import AIAgent

logger = logging.getLogger(__name__)


class ChatMessage:
    def __init__(self, role: str, content: str, timestamp: float = 0,
                 tool_name: str = "", tool_args: dict = None,
                 agent_name: str = ""):
        self.role = role
        self.content = content
        self.timestamp = timestamp or time.time()
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.agent_name = agent_name

    def time_str(self):
        return datetime.fromtimestamp(self.timestamp).strftime("%H:%M:%S")


class ChatSession:
    def __init__(self, config: AIConfig):
        self.config = config
        self.agent = AIAgent(config)
        self.history: List[ChatMessage] = []
        self._on_new_message: Optional[Callable] = None

    def on_new_message(self, cb):
        self._on_new_message = cb

    def set_sandbox_root(self, root: str):
        self.agent.set_sandbox_root(root)

    def clear(self):
        self.agent.reset_chat()
        self.history.clear()

    def _add_history(self, role: str, content: str, tool_name="", tool_args=None, agent_name=""):
        msg = ChatMessage(role, content, tool_name=tool_name,
                          tool_args=tool_args or {}, agent_name=agent_name)
        self.history.append(msg)
        if self._on_new_message:
            self._on_new_message(msg)

    async def send(self, user_input: str) -> str:
        self._add_history("user", user_input)
        prev_msg = self.agent._on_message
        self.agent.on_message(prev_msg or (lambda role, content: None))
        self.agent.on_tool(lambda name, args: self._add_history(
            "tool" if "_result" not in name else "tool_result",
            str(args.get("result", "")) if isinstance(args, dict) else str(args),
            tool_name=name.replace("_result", ""),
            tool_args=args if isinstance(args, dict) else {},
        ))
        self.agent.on_thinking(lambda msg: self._add_history("thinking", msg))

        reply = await self.agent.run(user_input)
        self._add_history("assistant", reply)
        return reply
