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
        get_config: Callable[[str], AIConfig],
        get_sandbox_root: Callable = None,
        memory: Optional[ConversationMemory] = None,
        log_func: Optional[Callable] = None,
        sandbox_manager=None,
        bot_manager=None,
    ):
        self._provider_manager = provider_manager
        self._get_config = get_config
        self._get_sandbox_root = get_sandbox_root
        self._memory = memory or ConversationMemory()
        self._log = log_func
        self._sandbox_manager = sandbox_manager
        self._bot_manager = bot_manager
        if bot_manager:
            from ai.plugins import set_bot_manager
            set_bot_manager(bot_manager)
        self._known_users: dict = {}  # channel_key -> {user_id: display_name}

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
            pu = ""
            if self._sandbox_manager and getattr(self._sandbox_manager, 'proxy_sandbox', None):
                pu = self._sandbox_manager.proxy_sandbox.proxy_url or ""
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=60, proxy=pu or None) as resp:
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
            pu = ""
            if self._sandbox_manager and getattr(self._sandbox_manager, 'proxy_sandbox', None):
                pu = self._sandbox_manager.proxy_sandbox.proxy_url or ""
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30, proxy=pu or None) as resp:
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

        config = self._get_config(getattr(event, 'bot_id', ''))
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

        # Attach sender identity for multi-user context
        sender_tag = event.sender_name or event.sender_id
        if sender_tag:
            if event.sender_id:
                user_content = f"[{sender_tag}]({event.sender_id}): {user_content}"
            else:
                user_content = f"[{sender_tag}]: {user_content}"

        # Record known users per conversation channel for @ mention support
        channel_key = f"{event.bot_id}:{event.platform_name}:{event.channel_id}"
        if event.sender_id and sender_tag:
            self._known_users.setdefault(channel_key, {})
            self._known_users[channel_key][event.sender_id] = sender_tag

        # Record known groups for group info tools
        from ai.tools import record_known_groups
        record_known_groups(event)
        self._memory.add_message(channel_key, "user", user_content)
        if self._log:
            self._log(f"[AI] 用户: {user_content[:80]}")

        self._memory.configure(
            context_window=config.context_window,
            context_mode=config.context_mode,
        )

        system = pc.system_prompt or config.system_prompt
        # Identify the bot in multi-bot scenarios
        bot_label = event.bot_id or ""
        if bot_label:
            system = f"[当前机器人: {bot_label}]\n" + system
        # Chat type and time awareness
        import datetime
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
        chat_type = "群聊" if "GROUP" in event.msg_type else ("私聊" if "C2C" in event.msg_type else event.msg_type)
        system += f"\n[当前时间: {now}] [聊天类型: {chat_type}]"
        # Expose known users for @ mention ability in group chats
        users = self._known_users.get(channel_key, {})
        if users and "GROUP" in event.msg_type:
            roster = "\n".join(f"  [{name}]({uid})" for uid, name in users.items())
            system += f"\n\n## 群成员\n以下是在本群中出现过的成员，你可以用 `<@对方openID>` 格式 @ 他们：\n{roster}\n"
            system += "\n在回复群消息时，如需 @ 某人，请直接在回复内容中包含 `<@对方openID>`。"
        skills_mgr = SkillsManager()
        skills_mgr.load_from_config(config.skills)
        enabled_skills = skills_mgr.get_enabled()
        if enabled_skills:
            system += "\n\n## 可用专业技能\n你可以根据任务需要激活以下技能：\n"
            for s in enabled_skills:
                system += f"\n### {s.name}: {s.description}\n{s.system_prompt}\n"
        if config.vision_api_key or config.api_key:
            system += "\n\n## 图片识别能力\n如果用户问图片内容、描述图片、或理解图片含义，你必须先调用 analyze_image 工具分析沙盒中的图片文件，再回答用户。不要假装看到图片内容。\n"
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

        max_rounds = max(pc.max_tool_rounds or 0, config.max_tool_rounds or 0, 10)
        enable_tools = pc.enable_tools or config.enable_tools

        logger.debug(
            "AI stage: bot=%s channel=%s type=%s pc.name=%s pc.enable_tools=%s cfg.enable_tools=%s enable_tools=%s",
            event.bot_id, event.channel_id, event.msg_type,
            pc.name, pc.enable_tools, config.enable_tools, enable_tools,
        )

        provider = self._provider_manager.get_or_create(config, pc if pc and pc.name != "default" else None)
        if not provider:
            event.set_reply("AI 提供者初始化失败")
            yield
            return

        self._plugin_tool_map: dict = {}
        try:
            tools = None
            if enable_tools:
                tools = get_tool_definitions(config.tool_permissions)
                # Remove context-restricted tools (added conditionally below)
                _CONTEXT_TOOLS = {"send_group_message", "get_known_groups", "get_group_members"}
                tools = [t for t in tools if t["function"]["name"] not in _CONTEXT_TOOLS]

                sub_mgr = None
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
                # Add context-specific tools only in their respective chat types
                if "C2C" in event.msg_type:
                    bm = getattr(self, '_bot_manager', None)
                    if bm:
                        sm_tool = get_tool_by_name("send_group_message")
                        if sm_tool:
                            tools.append(sm_tool.to_openai_tool())
                if "GROUP" in event.msg_type:
                    for tname in ("get_known_groups", "get_group_members"):
                        t = get_tool_by_name(tname)
                        if t:
                            tools.append(t.to_openai_tool())

                # Add plugin tools (only when tools are enabled)
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
                                for pt in ptools:
                                    pname = pt["function"]["name"]
                                    tools.append(pt)
                                    self._plugin_tool_map[pname] = plug
                        except Exception as e:
                            logger.warning(f"插件工具加载失败: {e}")
            else:
                sub_mgr = None

            messages = [{"role": "system", "content": system}]
            messages.extend(self._memory.get_history(channel_key, system))
            if vision_analysis:
                messages.append({"role": "system", "content": f"用户附带了一张图片，自动识图结果:\n{vision_analysis[:500]}"})
            messages.append({"role": "user", "content": user_content})

            set_tool_config(config, self._sandbox_manager, self._bot_manager)

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
                            plugin_result = await self._run_plugin_tool(tc.name, tc.arguments, event, sandbox_root)
                            if plugin_result is not None:
                                result = plugin_result
                            else:
                                result = f"未知工具: {tc.name}"
                        else:
                            if self._log:
                                self._log(f"[AI] 调用工具: {tc.name}")
                            try:
                                tool._current_bot_id = getattr(event, 'bot_id', '')
                                tool._current_channel_id = getattr(event, 'channel_id', '')
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

    async def _run_plugin_tool(self, tool_name: str, args: dict, event=None, sandbox_root="") -> Optional[str]:
        # Fast path: use the tool-to-plugin map built during tool definition loading
        plug = getattr(self, '_plugin_tool_map', {}).get(tool_name)
        if plug:
            try:
                if event:
                    plug._current_bot_id = getattr(event, 'bot_id', '')
                    plug._current_channel_id = getattr(event, 'channel_id', '')
                fn = getattr(plug, tool_name, None)
                if fn:
                    import inspect
                    kw = {**args, "sandbox_root": sandbox_root} if sandbox_root else args
                    result = await fn(**kw) if inspect.iscoroutinefunction(fn) else fn(**kw)
                    return str(result) if result else None
            except Exception as e:
                return f"插件工具执行错误: {e}"
        # Fallback: linear scan for backward compatibility
        from ai.plugins import PluginManager
        pm = PluginManager()
        pm.load_all()
        for plug in pm.get_all():
            if hasattr(plug, tool_name):
                try:
                    if event:
                        plug._current_bot_id = getattr(event, 'bot_id', '')
                        plug._current_channel_id = getattr(event, 'channel_id', '')
                    fn = getattr(plug, tool_name)
                    import inspect
                    kw = {**args, "sandbox_root": sandbox_root} if sandbox_root else args
                    result = await fn(**kw) if inspect.iscoroutinefunction(fn) else fn(**kw)
                    return str(result) if result else None
                except Exception as e:
                    return f"插件工具执行错误: {e}"
        return None


