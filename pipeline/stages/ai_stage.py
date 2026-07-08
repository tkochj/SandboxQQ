import asyncio
import json
import os
import logging
import uuid
from typing import Callable, Optional

import aiohttp

from pipeline.stage import Stage
from ai.base import Provider
from ai.provider import ProviderManager, OpenAIProvider
from ai.config import AIConfig
from ai.tools import get_tool_definitions, get_tool_by_name, set_tool_config
from ai.memory import ConversationMemory
from ai.sub_agent import SubAgentManager
from ai.skills import SkillsManager
from ai.plugins import PluginManager

logger = logging.getLogger(__name__)


class AIResponseStage(Stage):
    name = "ai_response"

    def __init__(
        self,
        provider_manager: ProviderManager,
        get_config: Callable,
        get_sandbox_root: Callable = None,
        memory: Optional[ConversationMemory] = None,
        log_func: Optional[Callable] = None,
        sandbox_manager=None,
    ):
        self._provider_manager = provider_manager
        self._get_config = get_config
        self._get_sandbox_root = get_sandbox_root
        self._memory = memory or ConversationMemory()
        self._log = log_func
        self._sandbox_manager = sandbox_manager

    async def _analyze_image(self, img_path: str, config) -> str:
        if not os.path.isfile(img_path):
            return ""
        api_key = getattr(config, "vision_api_key", None) or getattr(config, "api_key", "")
        api_url = getattr(config, "vision_api_url", None) or getattr(config, "api_url", "")
        model = getattr(config, "vision_model", None) or getattr(config, "model", "")
        if not api_key:
            return ""
        try:
            import base64
            from pathlib import Path
            with open(img_path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            ext = Path(img_path).suffix.lower()
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "gif": "image/gif", "webp": "image/webp"}.get(ext.lstrip("."), "image/png")
            data_url = f"data:{mime};base64,{b64}"
            url = f"{api_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": [
                        {"type": "text", "text": "请详细描述这张图片的内容"},
                        {"type": "image_url", "image_url": {"url": data_url}},
                    ]},
                ],
                "max_tokens": 1024,
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    else:
                        text = await resp.text()
                        if "does not support image" in text or "image input" in text.lower():
                            logger.warning(f"Vision model {model} does not support image input")
                        else:
                            logger.warning(f"Vision API error {resp.status}: {text[:200]}")
        except Exception as e:
            logger.warning(f"Vision analysis failed: {e}")
        return ""

    async def _download_img(self, url: str, sandbox_root: str) -> str:
        ext = os.path.splitext(url.split("?")[0])[1] or ".png"
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            ext = ".png"
        local = os.path.join(sandbox_root, f"qq_img_{uuid.uuid4().hex}{ext}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as resp:
                    if resp.status == 200:
                        with open(local, "wb") as f:
                            f.write(await resp.read())
                        return local if os.path.isfile(local) and os.path.getsize(local) > 0 else ""
        except Exception as e:
            logger.warning(f"Download image failed: {e}")
        return ""

    async def process(self, event):
        if event.is_stopped:
            yield
            return

        config = self._get_config()
        if not config:
            event.set_reply("AI 未配置")
            yield
            return

        pc = config.get_active_provider_config() if hasattr(config, 'get_active_provider_config') else None
        if not pc or not pc.api_key:
            event.set_reply("AI 未配置，请在设置中填写 API Key")
            yield
            return

        sandbox_root = self._get_sandbox_root() if self._get_sandbox_root else ""

        user_content = event.content
        vision_analysis = ""

        saved_images = []
        if event.attachments:
            parts = [user_content] if user_content.strip() else []
            for a in event.attachments:
                atype = a.get("type", "")
                url = a.get("url", "")
                if atype == "image" and url:
                    local_path = await self._download_img(url, sandbox_root)
                    if local_path:
                        saved_images.append(local_path)
                        analysis = await self._analyze_image(local_path, config)
                        if analysis:
                            vision_analysis = analysis
                            parts.append(f"[图片已保存到 {local_path}，自动分析: {analysis[:200]}]")
                            continue
                        parts.append(f"[图片已保存到 {local_path}，用户想知道图片内容]")
                    else:
                        parts.append(f"[用户发送了一张图片，但无法下载查看]")
                else:
                    parts.append(f"[{atype}: {url if url else a.get('name','')}]")
            user_content = "\n".join(parts)

        if not user_content.strip():
            yield
            return

        channel_key = f"{event.platform_name}:{event.channel_id}"
        self._memory.add_message(channel_key, "user", user_content)
        if self._log:
            self._log(f"[AI] 用户: {user_content[:80]}")

        self._memory.configure(
            context_window=config.context_window,
            context_mode=config.context_mode,
        )

        system = pc.system_prompt or config.system_prompt
        skills_mgr = SkillsManager()
        skills_mgr.load_from_config(config.skills)
        enabled_skills = skills_mgr.get_enabled()
        if enabled_skills:
            system += "\n\n## 可用专业技能\n你可以根据任务需要激活以下技能：\n"
            for s in enabled_skills:
                system += f"\n### {s.name}: {s.description}\n{s.system_prompt}\n"
        if config.enable_thinking and config.thinking_model:
            system += "\n\n## 深度思考\n对于复杂问题，你可以先调用深度思考模型分析，再给出最终答案。\n"
            system += f"思考模型: {config.thinking_model}\n"

        # Check @mention sub-agent routing
        if config.sub_agents:
            for sa in config.sub_agents:
                if sa.enabled and sa.name:
                    tag = f"@{sa.name}"
                    if tag in user_content:
                        task = user_content.replace(tag, "").strip()
                        if task:
                            sub_mgr = SubAgentManager(config)
                            sub_mgr.build(config.sub_agents)
                            result = await sub_mgr.run_sub_agent(sa.name, task, sandbox_root)
                            event.set_reply(f"[子Agent {sa.name}]: {result[:1500]}")
                            yield
                            return

        max_rounds = pc.max_tool_rounds or config.max_tool_rounds or 10
        enable_tools = pc.enable_tools or config.enable_tools

        provider = self._provider_manager.get_or_create(config, pc if pc and pc.name != "default" else None)
        if not provider:
            event.set_reply("AI 提供者初始化失败")
            yield
            return

        try:
            tools = None
            if enable_tools:
                tools = get_tool_definitions(config.tool_permissions)
                if config.sub_agents:
                    sub_mgr = SubAgentManager(config)
                    sub_mgr.build(config.sub_agents)
                    for sa in config.sub_agents:
                        if sa.enabled and sa.name:
                            tools.append({
                                "type": "function",
                                "function": {
                                    "name": f"delegate_to_{sa.name}",
                                    "description": f"将任务委派给子Agent [{sa.name}] 处理",
                                    "parameters": {"type": "object", "properties": {"task": {"type": "string", "description": "要委派的任务"}}, "required": ["task"]},
                                },
                            })
                else:
                    sub_mgr = None
            else:
                sub_mgr = None

            # Add plugin tools
            plugin_mgr = PluginManager()
            plugin_mgr.load_all()
            for plug in plugin_mgr.get_all():
                td = getattr(plug, "get_tool_definitions", None)
                if td:
                    try:
                        import inspect
                        if inspect.iscoroutinefunction(td):
                            ptools = await td()
                        else:
                            ptools = td()
                        if ptools:
                            tools.extend(ptools)
                    except Exception as e:
                        logger.warning(f"插件工具加载失败: {e}")

            messages = [{"role": "system", "content": system}]
            messages.extend(self._memory.get_history(channel_key, system))
            if vision_analysis:
                messages.append({"role": "system", "content": f"用户附带了一张图片，自动识图结果:\n{vision_analysis[:500]}"})
            messages.append({"role": "user", "content": user_content})

            set_tool_config(config, self._sandbox_manager)

            for rnd in range(max_rounds):
                # Thinking mode
                if rnd == 0 and config.enable_thinking and config.thinking_model:
                    if self._log:
                        self._log("[AI] 深度思考中...")
                    think_cfg = AIConfig()
                    think_cfg.api_key = config.api_key
                    think_cfg.api_url = config.api_url
                    think_cfg.provider = config.provider
                    think_cfg.model = config.thinking_model
                    think_cfg.max_tokens = config.thinking_budget
                    think_provider = OpenAIProvider(think_cfg)
                    try:
                        think_resp = await think_provider.chat([
                            {"role": "system", "content": "你是一个深度思考助手，分析任务并提供思路。"},
                            {"role": "user", "content": f"分析任务: {user_content}"},
                        ], max_tokens=config.thinking_budget)
                        if think_resp and think_resp.content:
                            messages.append({"role": "system", "content": f"深度思考:\n{think_resp.content[:1000]}"})
                            if self._log:
                                self._log(f"[AI] 思考输出: {think_resp.content[:100]}")
                    except Exception as e:
                        logger.warning(f"Thinking failed: {e}")

                response = await provider.chat(messages, tools=tools)
                reply = response.content or ""
                has_tools = bool(response.tool_calls)

                if not has_tools:
                    self._memory.add_message(channel_key, "assistant", reply)
                    if self._log:
                        self._log(f"[AI] 回复: {reply[:200]}")
                    event.set_reply(reply[:1500])
                    yield
                    return

                messages.append({"role": "assistant", "content": reply, "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in response.tool_calls
                ]})

                for tc in response.tool_calls:
                    if tc.name.startswith("delegate_to_") and sub_mgr:
                        agent_name = tc.name.replace("delegate_to_", "")
                        task = tc.arguments.get("task", "")
                        result = await sub_mgr.run_sub_agent(agent_name, task, sandbox_root)
                        if self._log:
                            self._log(f"[子Agent] {agent_name}: {result[:200]}")
                    else:
                        tool = get_tool_by_name(tc.name)
                        if not tool:
                            # Check plugin tools
                            plugin_result = await self._run_plugin_tool(tc.name, tc.arguments)
                            if plugin_result is not None:
                                result = plugin_result
                            else:
                                result = f"未知工具: {tc.name}"
                        else:
                            if self._log:
                                self._log(f"[AI] 调用工具: {tc.name}")
                            try:
                                result = await tool.run(sandbox_root, **tc.arguments)
                                if hasattr(tool, '_last_file') and tool._last_file and not event.reply_file:
                                    if os.path.isfile(tool._last_file):
                                        event.reply_file = tool._last_file
                                        if self._log:
                                            self._log(f"[AI] 生成文件准备发送: {tool._last_file}")
                            except Exception as e:
                                result = f"工具执行错误: {e}"
                    messages.append({"role": "tool", "content": str(result)[:3000], "tool_call_id": tc.id})

            event.set_reply("已达到最大工具调用轮次")
        except Exception as e:
            err = str(e)
            if "does not support image" in err or "image input" in err.lower():
                event.set_reply("收到图片，但我当前的模型不支持直接识别图片。如需识图请配置 Vision API。")
            else:
                event.set_reply(f"AI 处理失败: {err[:200]}")
            logger.error(f"AI stage error: {err[:200]}")
        yield

    async def _run_plugin_tool(self, tool_name: str, args: dict) -> Optional[str]:
        from ai.plugins import PluginManager
        pm = PluginManager()
        pm.load_all()
        for plug in pm.get_all():
            if hasattr(plug, tool_name):
                try:
                    fn = getattr(plug, tool_name)
                    import inspect
                    if inspect.iscoroutinefunction(fn):
                        result = await fn(**args)
                    else:
                        result = fn(**args)
                    return str(result) if result else None
                except Exception as e:
                    return f"插件工具执行错误: {e}"
        return None


