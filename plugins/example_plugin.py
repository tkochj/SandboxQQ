# -*- coding: utf-8 -*-
import logging
logger = logging.getLogger(__name__)

class Plugin:
    name = "示例插件"
    description = "这是一个插件示例，收到消息后回复Hello"
    version = "1.0"

    async def on_message(self, content, sender, channel):
        if "hello" in content.lower():
            return f"Hello! You said: {content[:50]}"
        return None

    async def get_tool_definitions(self):
        return [{
            "type": "function",
            "function": {
                "name": "hello_tool",
                "description": "Example tool - say hello",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        }]

    async def hello_tool(self, name: str) -> str:
        return f"Hello, {name}! From example plugin"
