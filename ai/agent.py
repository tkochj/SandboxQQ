import json
import logging
from typing import List, Optional, Callable
from ai.config import AIConfig
from ai.provider import AIProvider, AIMessage
from ai.tools import get_tool_definitions, get_tool_by_name
from ai.skills import SkillsManager
from ai.sub_agent import SubAgentManager

logger = logging.getLogger(__name__)


class AIAgent:
    def __init__(self, config: AIConfig, sandbox_root: str = ""):
        self.config = config
        self.sandbox_root = sandbox_root
        self.provider = AIProvider(config)
        self.messages: List[AIMessage] = []
        self.skills_mgr = SkillsManager()
        self.sub_agent_mgr = SubAgentManager(config)
        self._on_message: Optional[Callable] = None
        self._on_tool: Optional[Callable] = None
        self._on_thinking: Optional[Callable] = None
        from ai.tools import set_tool_config
        set_tool_config(config)

    def on_message(self, cb): self._on_message = cb
    def on_tool(self, cb): self._on_tool = cb
    def on_thinking(self, cb): self._on_thinking = cb

    def set_sandbox_root(self, root: str):
        self.sandbox_root = root

    def reset_chat(self):
        self.messages = []
        self.sub_agent_mgr.build(self.config.sub_agents)

    def add_system_prompt(self):
        prompt = self.config.system_prompt
        if self.config.vision_api_key or self.config.api_key:
            prompt += "\n\n## 图片识别能力\n你可以用 analyze_image 工具分析沙盒目录内的图片文件。"
        if self.config.image_gen_api_key:
            prompt += "\n\n## 图片生成能力\n你可以用 generate_image 工具根据文字描述生成图片。"
        if self.config.video_gen_api_key:
            prompt += "\n\n## 视频生成能力\n你可以用 generate_video 工具根据文字描述生成视频。"
        skills = self.skills_mgr.get_enabled()
        if skills:
            prompt += "\n\n## 可用专业技能\n你可以根据任务需要激活以下技能：\n"
            for s in skills:
                prompt += f"\n### {s.name}: {s.description}\n{s.system_prompt}\n"
        self.messages.append(AIMessage("system", prompt))

    def add_user_message(self, content: str):
        self.messages.append(AIMessage("user", content))
        if self._on_message:
            self._on_message("user", content)

    def _apply_context_mode(self):
        if self.config.context_mode == "truncation":
            total = sum(len(m.content or "") for m in self.messages)
            limit = self.config.context_window
            if total > limit:
                while total > limit and len(self.messages) > 2:
                    removed = self.messages.pop(1)
                    total -= len(removed.content or "")
                    logger.info(f"截断上下文: 移除 {removed.role} 消息")
        elif self.config.context_mode == "compression":
            if len(self.messages) > 20:
                keep_raw = 5
                summary_msgs = self.messages[1:-keep_raw]
                summary_content = "\n".join(
                    f"[{m.role}]: {m.content[:100]}" for m in summary_msgs
                )
                self.messages = self.messages[:1] + [
                    AIMessage("system", f"(上下文已压缩，最近消息摘要:\n{summary_content})")
                ] + self.messages[-keep_raw:]
                logger.info("上下文已压缩")

    async def run(self, user_input: str) -> str:
        if not self.sandbox_root:
            return "错误: 沙盒根目录未设置"
        if not self.config.api_key:
            return "错误: 未配置 API Key"

        if not self.messages or self.messages[0].role != "system":
            self.messages = []
            self.add_system_prompt()
            self.sub_agent_mgr.close_all()
            self.sub_agent_mgr.build(self.config.sub_agents)

        self.add_user_message(user_input)

        sub_agent_prefix = self._check_sub_agent_call(user_input)
        if sub_agent_prefix:
            return sub_agent_prefix

        self._apply_context_mode()

        tools = None
        if self.config.enable_tools:
            tools = get_tool_definitions(self.config.tool_permissions)
            if self.config.enable_web_search:
                tools.append({
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "搜索互联网获取实时信息。当用户询问最新信息、时事、或需要联网查询时使用。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "搜索关键词"}
                            },
                            "required": ["query"],
                        },
                    },
                })
            tools.extend(self._get_sub_agent_tools())

        for _ in range(self.config.max_tool_rounds):
            # Thinking mode
            if self.config.enable_thinking and self.config.thinking_model:
                if self._on_thinking:
                    self._on_thinking("思考中...")
                thinking_msg = AIMessage("user", f"请先分析这个任务: {user_input}\n用(思考)...(结束思考)包裹你的分析过程，然后给出最终答案。")
                try:
                    thinking_cfg = AIConfig()
                    thinking_cfg.api_key = self.config.api_key
                    thinking_cfg.api_url = self.config.api_url
                    thinking_cfg.provider = self.config.provider
                    thinking_cfg.model = self.config.thinking_model
                    thinking_cfg.max_tokens = self.config.thinking_budget
                    thinking_provider = AIProvider(thinking_cfg)
                    think_resp = await thinking_provider.chat([AIMessage("system", "你是一个深度思考助手。"), thinking_msg])
                    logger.info(f"思考输出: {think_resp.content[:100]}...")
                    self.messages.insert(-1, AIMessage("system", f"深度思考:\n{think_resp.content}"))
                except Exception as e:
                    logger.warning(f"思考失败: {e}")

            try:
                response = await self.provider.chat(self.messages, tools=tools)
            except Exception as e:
                err = f"AI请求失败: {e}"
                self.messages.append(AIMessage("assistant", err))
                return err

            self.messages.append(response)
            if self._on_message:
                self._on_message("assistant", response.content or "")

            if not response.tool_calls:
                return response.content or "(无文本回复)"

            for tc in response.tool_calls:
                # Handle sub-agent calls
                if tc.name.startswith("delegate_to_"):
                    agent_name = tc.name.replace("delegate_to_", "")
                    task = tc.arguments.get("task", "")
                    result = await self.sub_agent_mgr.run_sub_agent(agent_name, task, self.sandbox_root)
                    self.messages.append(AIMessage.tool_result(tc.id, tc.name, result))
                    if self._on_tool:
                        self._on_tool(f"子Agent[{agent_name}]", {"result": result[:200]})
                    continue

                if tc.name == "web_search":
                    result = await self._web_search(tc.arguments.get("query", ""))
                    self.messages.append(AIMessage.tool_result(tc.id, tc.name, result))
                    if self._on_tool:
                        self._on_tool("web_search", {"query": tc.arguments.get("query", ""), "result": result[:200]})
                    continue

                tool = get_tool_by_name(tc.name)
                if not tool:
                    result = f"未知工具: {tc.name}"
                else:
                    if self._on_tool:
                        self._on_tool(tc.name, tc.arguments)
                    try:
                        result = await tool.run(self.sandbox_root, **tc.arguments)
                    except Exception as e:
                        result = f"工具执行错误: {e}"
                    if self._on_tool:
                        self._on_tool(tc.name + "_result", {"result": str(result)[:500]})

                self.messages.append(AIMessage.tool_result(tc.id, tc.name, str(result)[:3000]))

        return "已达到最大工具调用轮次"

    def _check_sub_agent_call(self, user_input: str) -> str:
        for sa in self.config.sub_agents:
            if sa.enabled and sa.name:
                lower_name = sa.name.lower()
                lower_input = user_input.lower().strip()
                if lower_input.startswith(f"@{lower_name} ") or lower_input == f"@{lower_name}":
                    task = user_input[len(sa.name)+2:].strip() if len(user_input) > len(sa.name)+2 else ""
                    logger.info(f"路由到子Agent {sa.name}: {task}")
                    return f"已将任务路由给子Agent '{sa.name}'处理，请等待结果..."
                if lower_input.startswith(f"/{lower_name} ") or lower_input == f"/{lower_name}":
                    task = user_input[len(sa.name)+2:].strip() if len(user_input) > len(sa.name)+2 else ""
                    logger.info(f"路由到子Agent {sa.name}: {task}")
                    return f"已将任务路由给子Agent '{sa.name}'处理，请等待结果..."
        return ""

    async def _web_search(self, query: str) -> str:
        try:
            import httpx
            provider = self.config.search_provider.lower()
            if provider == "duckduckgo":
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1")
                    data = r.json()
                    results = []
                    for topic in data.get("RelatedTopics", [])[:5]:
                        if "Text" in topic:
                            results.append(topic["Text"])
                    return "\n".join(results) if results else "无搜索结果"
            else:
                return f"搜索提供商 {provider} 暂不支持"
        except Exception as e:
            return f"搜索失败: {e}"

    def _get_sub_agent_tools(self) -> list:
        agents = [s for s in self.config.sub_agents if s.enabled and s.name]
        if not agents:
            return []
        return [{
            "type": "function",
            "function": {
                "name": f"delegate_to_{a.name}",
                "description": f"将任务委派给子Agent [{a.name}] 处理",
                "parameters": {"type": "object", "properties": {"task": {"type": "string", "description": "要委派的任务"}}, "required": ["task"]},
            },
        } for a in agents]

    async def close(self):
        await self.provider.close()
        await self.sub_agent_mgr.close_all()
