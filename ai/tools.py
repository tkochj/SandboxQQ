import os, sys, json, logging, subprocess, base64, unicodedata
from pathlib import Path
from typing import Dict, Any, List, Optional
from ai.config import ToolPermissions

logger = logging.getLogger(__name__)

class SandboxTool:
    name: str = ""
    display_name: str = ""
    description: str = ""
    parameters: dict = {}
    permission_key: str = ""

    def to_openai_tool(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}

    def is_allowed(self, perms: ToolPermissions) -> bool:
        if not self.permission_key: return True
        return getattr(perms, self.permission_key, True)

    async def run(self, sandbox_root: str, **kwargs) -> str:
        raise NotImplementedError

class ExecutePythonTool(SandboxTool):
    name = "execute_python"; display_name = "Python代码执行"
    description = "在沙盒中执行Python代码。可读写沙盒文件、安装包、处理数据。返回print输出或错误。"
    permission_key = "execute_python"
    parameters = {"type": "object", "properties": {"code": {"type": "string", "description": "Python代码"}, "timeout": {"type": "integer", "description": "超时秒数", "default": 30}}, "required": ["code"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        code = kwargs.get("code",""); timeout = kwargs.get("timeout",30)
        if not code.strip(): return "错误: 代码不能为空"
        sp = os.path.join(sandbox_root,"_sandbox_script.py")
        try:
            with open(sp,"w",encoding="utf-8") as f: f.write(code)
            sm = getattr(self, '_sandbox_manager', None)
            if not sm or not sm.proc_sandbox:
                return "错误: 沙盒未启动或无进程隔离，拒绝执行"
            proc = sm.proc_sandbox.spawn([sys.executable, sp], cwd=sandbox_root, capture_output=True)
            if not proc:
                return "错误: 沙盒拒绝执行"
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
                rcode = proc.returncode
            except subprocess.TimeoutExpired:
                sm.proc_sandbox.kill(proc.pid)
                return f"错误: 超时({timeout}秒)"
            out = (stdout or "") + (("[STDERR]\n"+stderr) if stderr else "") + (("\n[退出码: "+str(rcode)+"]") if rcode else "")
            return out.strip() or "(无输出)"
        except subprocess.TimeoutExpired: return f"错误: 超时({timeout}秒)"
        except Exception as e: return f"执行错误: {e}"
        finally:
            try: os.remove(sp)
            except Exception: pass

_SENSITIVE_FILES = {
    "ai_config.json", "bot_config.json", "bot_profiles.json",
    "conversation_memory.json", "user_config.json",
}

# Track known group_openids from incoming messages
_known_groups: dict = {}  # group_openid -> {"name": str, "last_seen": float, "bot_id": str}

def record_known_groups(event):
    """Call from AI stage to record group info from incoming events."""
    if "GROUP" in getattr(event, "msg_type", ""):
        gid = getattr(event, "channel_id", "")
        if gid:
            _known_groups.setdefault(gid, {})
            _known_groups[gid]["name"] = getattr(event, "content", "")[:30] or gid
            _known_groups[gid]["last_seen"] = __import__("time").time()
            _known_groups[gid]["bot_id"] = getattr(event, "bot_id", "")

class ReadFileTool(SandboxTool):
    name = "read_file"; display_name = "读取文件"
    description = "读取沙盒目录内的文件。路径相对于沙盒根目录。不允许读取配置文件。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"path":{"type":"string","description":"文件路径(相对沙盒根目录)"},"encoding":{"type":"string","description":"编码","default":"utf-8"}},"required":["path"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        rp = kwargs.get("path",""); enc = kwargs.get("encoding","utf-8")
        ap = _resolve(sandbox_root, rp)
        if not ap: return f"错误: 路径超出沙盒: {rp}"
        if not os.path.isfile(ap): return f"错误: 文件不存在: {rp}"
        if os.path.basename(ap) in _SENSITIVE_FILES:
            return f"错误: 不允许读取配置文件: {rp}"
        try:
            with open(ap,"r",encoding=enc) as f: c = f.read()
            if len(c)>10000: return f"(文件{os.path.getsize(ap)}bytes,显示前10000)\n{c[:10000]}"
            return c
        except Exception as e: return f"读取失败: {e}"

_WRITE_BLOCKED_FILES = {"ai_config.json", "bot_config.json", "bot_profiles.json", "conversation_memory.json"}
_WRITE_BLOCKED_EXT = (".py", ".exe", ".bat", ".ps1", ".dll", ".com", ".vbs", ".js")
_DOT_CONF = dict.fromkeys(map(ord, "\u3002\uff0e\u2024\ufe52\uff61\u00b7\u2219"), ".")

class WriteFileTool(SandboxTool):
    name = "write_file"; display_name = "写入文件"
    description = "写入文件到沙盒目录。路径相对于沙盒根目录，自动创建子目录。不允许写入可执行文件。"
    permission_key = "write_file"
    parameters = {"type":"object","properties":{"path":{"type":"string","description":"文件路径(相对沙盒根目录)"},"content":{"type":"string","description":"文件内容"}},"required":["path","content"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        rp = kwargs.get("path","").strip(); content = kwargs.get("content","")
        ap = _resolve(sandbox_root, rp)
        if not ap: return f"错误: 路径超出沙盒: {rp}"
        fname = os.path.basename(ap).strip().rstrip(". ")
        # Reject control/format/combining chars (zero-width, dot confusables, etc.)
        if any(unicodedata.category(c) in ("Cc", "Cf", "Mn") for c in fname):
            return f"错误: 文件名含非法字符: {rp}"
        # Map Unicode dot confusables -> ASCII period before extension check
        fname_check = unicodedata.normalize("NFKC", fname).translate(_DOT_CONF)
        ext = os.path.splitext(fname_check)[1].lower()
        if ext in _WRITE_BLOCKED_EXT:
            return f"错误: 不允许写入可执行文件: {rp}"
        if fname in _WRITE_BLOCKED_FILES:
            return f"错误: 不允许覆盖配置文件: {rp}"
        rp_normalized = rp.replace("\\", "/")
        if "/plugins/" in rp_normalized or rp_normalized.startswith("plugins/"):
            return f"错误: 不允许写入插件目录: {rp}"
        try:
            os.makedirs(os.path.dirname(ap), exist_ok=True)
            with open(ap,"w",encoding="utf-8") as f: f.write(content)
            return f"已写入{len(content)}字符到 {rp}"
        except Exception as e: return f"写入失败: {e}"

class ListFilesTool(SandboxTool):
    name = "list_files"; display_name = "列出文件"
    description = "列出沙盒目录内的文件和子目录。"
    permission_key = "list_files"
    parameters = {"type":"object","properties":{"path":{"type":"string","description":"目录路径(相对沙盒根目录)","default":""}}}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        rp = kwargs.get("path","")
        root = Path(sandbox_root).resolve()
        target = root if not rp else (root/rp).resolve()
        try: target.relative_to(root)
        except: return f"错误: 路径超出沙盒: {rp}"
        if not target.is_dir(): return f"错误: 目录不存在: {rp or '/'}"
        try:
            entries = []
            for e in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                p = "D" if e.is_dir() else "F"
                s = f" ({_fmt_size(e.stat().st_size)})" if e.is_file() else ""
                entries.append(f"[{p}] {e.name}{s}")
            return f"目录: {rp or '/'} ({len(entries)}项)\n"+"\n".join(entries) if entries else "(空目录)"
        except Exception as e: return f"列出失败: {e}"

ALLOWED_SHELL_COMMANDS = ["echo","dir","type","find","findstr","more","tree","where","ver"]

class RunShellTool(SandboxTool):
    name = "run_shell"; display_name = "Shell命令"
    description = "在沙盒目录内执行shell命令。只允许安全的只读命令。"
    permission_key = "run_shell"
    parameters = {"type":"object","properties":{"command":{"type":"string","description":"shell命令"},"timeout":{"type":"integer","description":"超时秒数","default":30}},"required":["command"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        cmd = kwargs.get("command",""); timeout = kwargs.get("timeout",30)
        if not cmd.strip(): return "错误: 命令不能为空"
        import shlex
        try:
            parts = shlex.split(cmd)
        except ValueError as e:
            return f"错误: 命令解析失败: {e}"
        if not parts:
            return "错误: 命令为空"
        base = parts[0].lower()
        if base not in ALLOWED_SHELL_COMMANDS:
            return f"错误: 命令 '{base}' 不在白名单中。允许: {', '.join(ALLOWED_SHELL_COMMANDS)}"
        try:
            sm = getattr(self, '_sandbox_manager', None)
            if not sm or not sm.proc_sandbox:
                return "错误: 沙盒未启动或无进程隔离，拒绝执行"
            proc = sm.proc_sandbox.spawn(parts, cwd=sandbox_root, capture_output=True, shell=False)
            if not proc:
                return "错误: 沙盒拒绝执行"
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                sm.proc_sandbox.kill(proc.pid)
                return f"错误: 超时({timeout}秒)"
            o = (stdout or "") + ("\n[STDERR]\n"+stderr[:2000] if stderr else "")
            if len(o)>5000: o = o[:5000]+"\n...(截断)"
            return o.strip() or "(无输出)"
        except subprocess.TimeoutExpired: return f"错误: 超时({timeout}秒)"
        except Exception as e: return f"执行错误: {e}"

class GenerateImageTool(SandboxTool):
    name = "generate_image"; display_name = "生成图片"
    description = "使用AI生成图片。需要配置图片生成API。output_format=link 时仅返回URL文本链接（适合群聊回复用），output_format=file 时下载到沙盒再发送文件。"
    permission_key = "execute_python"
    parameters = {"type":"object","properties":{"prompt":{"type":"string","description":"图片描述"},"size":{"type":"string","description":"尺寸 如 1024x1024","default":"1024x1024"},"output_format":{"type":"string","enum":["file","link"],"description":"输出格式: file=下载到沙盒后发送文件(默认), link=仅返回文本链接"}},"required":["prompt"]}
    config = None

    _last_file = ""

    async def run(self, sandbox_root: str, **kwargs) -> str:
        prompt = kwargs.get("prompt",""); size = kwargs.get("size","1024x1024")
        output_format = kwargs.get("output_format", "file")
        if not self.config or not self.config.image_gen_api_key:
            return "错误: 未配置图片生成API"
        import httpx, aiohttp, uuid
        pu = getattr(self, '_proxy_url', '') or None
        try:
            url = f"{self.config.image_gen_api_url.rstrip('/')}/images/generations"
            async with httpx.AsyncClient(timeout=60, proxy=pu) as client:
                resp = await client.post(url, json={"model":self.config.image_gen_model or "dall-e-3","prompt":prompt,"n":1,"size":size},
                    headers={"Authorization":f"Bearer {self.config.image_gen_api_key}","Content-Type":"application/json"})
            data = resp.json()
            img_url = data.get("data",[{}])[0].get("url","")
            if not img_url:
                return f"生成结果: {json.dumps(data,ensure_ascii=False)[:500]}"
            if output_format == "link":
                return f"图片已生成，链接: {img_url}\n你可以将此链接以 `![图片]({img_url})` 格式发送给用户。"
            ext = os.path.splitext(img_url.split("?")[0])[1] or ".png"
            local = os.path.join(sandbox_root, f"gen_img_{uuid.uuid4().hex}{ext}")
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(img_url, timeout=30, proxy=pu) as r:
                        if r.status == 200:
                            with open(local, "wb") as f:
                                f.write(await r.read())
                            if os.path.isfile(local) and os.path.getsize(local) > 0:
                                self._last_file = local
                                return f"图片已生成并保存到: {local}\n图片链接: {img_url}"
            except Exception:
                pass
            return f"图片已生成: {img_url}"
        except Exception as e: return f"生成失败: {e}"

class AnalyzeImageTool(SandboxTool):
    name = "analyze_image"; display_name = "分析图片"
    description = "分析图片内容。可以分析沙盒中的本地图片文件（传 image_path），或网络图片URL（传 image_url）。当用户发送图片消息、问图片里有什么、要求描述图片或理解图片内容时，必须调用此工具。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"image_path":{"type":"string","description":"图片路径(相对沙盒根目录)，与image_url二选一"},"image_url":{"type":"string","description":"网络图片URL，与image_path二选一"},"question":{"type":"string","description":"关于图片的问题","default":"请描述这张图片"}},"required":["question"]}
    config = None

    async def run(self, sandbox_root: str, **kwargs) -> str:
        ip = kwargs.get("image_path",""); iurl = kwargs.get("image_url","")
        question = kwargs.get("question","请描述这张图片")
        if not ip and not iurl:
            return "错误: 请提供 image_path 或 image_url"
        data_url = ""
        if ip:
            ap = _resolve(sandbox_root, ip)
            if not ap: return f"错误: 路径超出沙盒: {ip}"
            if not os.path.isfile(ap): return f"错误: 文件不存在: {ip}"
            try:
                with open(ap,"rb") as f: b64 = base64.b64encode(f.read()).decode()
                ext = Path(ap).suffix.lower()
                mime = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png","gif":"image/gif","webp":"image/webp"}.get(ext.lstrip("."),"image/png")
                data_url = f"data:{mime};base64,{b64}"
            except Exception as e:
                return f"读取图片失败: {e}"
        else:
            data_url = iurl
        try:
            # Resolve vision API from: dedicated vision config -> active provider -> global config
            pc = self.config.get_active_provider_config() if self.config and hasattr(self.config, 'get_active_provider_config') else None
            use_key = self.config.vision_api_key if self.config and self.config.vision_api_key else (pc.api_key if pc else None)
            use_url = self.config.vision_api_url if self.config and self.config.vision_api_url else (pc.api_url if pc else None)
            use_model = self.config.vision_model if self.config and self.config.vision_model else (pc.model if pc else None)

            if not use_key:
                return "错误: 未配置识图 API Key（请设置 vision_api_key，或确保当前 AI 供应商支持 Vision）"
            import httpx
            pu = getattr(self, '_proxy_url', '') or None
            api_url = use_url.rstrip("/") + "/chat/completions"
            payload = {"model": use_model, "messages": [{"role": "user", "content": [{"type": "text", "text": question}, {"type": "image_url", "image_url": {"url": data_url}}]}], "max_tokens": 1024}
            async with httpx.AsyncClient(timeout=60, proxy=pu) as client:
                resp = await client.post(api_url, json=payload,
                    headers={"Authorization": f"Bearer {use_key}", "Content-Type": "application/json"})
                resp.raise_for_status()
                result = resp.json()["choices"][0]["message"]["content"]
                return result.strip() or "(无描述)"
        except Exception as e:
            err = str(e)
            if any(k in err.lower() for k in ("does not support image", "image input", "not support", "vision")):
                model_name = use_model or "当前模型"
                return f"{model_name} 不支持图片识别，请配置支持 Vision 的模型（如 glm-4v-flash、gpt-4o、qwen-vl-plus）"
            return f"分析失败: {err[:300]}"

class GenerateVideoTool(SandboxTool):
    name = "generate_video"; display_name = "生成视频"
    description = "使用AI生成视频。返回视频URL。需要配置视频生成API。"
    permission_key = "execute_python"
    parameters = {"type":"object","properties":{"prompt":{"type":"string","description":"视频描述"},"duration":{"type":"integer","description":"时长(秒)","default":5}},"required":["prompt"]}
    config = None

    async def run(self, sandbox_root: str, **kwargs) -> str:
        prompt = kwargs.get("prompt",""); duration = kwargs.get("duration",5)
        if not self.config or not self.config.video_gen_api_key:
            return "错误: 未配置视频生成API"
        import httpx
        pu = getattr(self, '_proxy_url', '') or None
        try:
            url = f"{self.config.video_gen_api_url.rstrip('/')}/video/generations"
            async with httpx.AsyncClient(timeout=120, proxy=pu) as client:
                resp = await client.post(url, json={"model":self.config.video_gen_model or "default","prompt":prompt,"duration":duration},
                    headers={"Authorization":f"Bearer {self.config.video_gen_api_key}","Content-Type":"application/json"})
            data = resp.json()
            return f"视频生成结果: {json.dumps(data,ensure_ascii=False)[:500]}"
        except Exception as e: return f"生成失败: {e}"

class WebDownloadTool(SandboxTool):
    name = "web_download"; display_name = "下载文件"
    description = "从URL下载文件到沙盒目录。支持任何公开可访问的URL。"
    permission_key = "execute_python"
    parameters = {"type":"object","properties":{"url":{"type":"string","description":"文件URL"},"save_path":{"type":"string","description":"保存路径(相对沙盒根目录)","default":""}},"required":["url"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        url = kwargs.get("url",""); save_path = kwargs.get("save_path","")
        import aiohttp, uuid
        pu = getattr(self, '_proxy_url', '') or None
        fname = save_path or os.path.basename(url.split("?")[0]) or f"download_{uuid.uuid4().hex}"
        ap = _resolve(sandbox_root, fname) if not save_path else _resolve(sandbox_root, save_path)
        if not ap: return f"错误: 路径超出沙盒"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=60, proxy=pu) as r:
                    if r.status != 200: return f"下载失败: HTTP {r.status}"
                    with open(ap,"wb") as f:
                        f.write(await r.read())
            size = os.path.getsize(ap)
            return f"已下载 {_fmt_size(size)} 到 {os.path.basename(ap)}"
        except Exception as e: return f"下载错误: {e}"

class CompressTool(SandboxTool):
    name = "compress_files"; display_name = "压缩文件"
    description = "将沙盒内的文件/目录压缩为zip包。"
    permission_key = "write_file"
    parameters = {"type":"object","properties":{"paths":{"type":"string","description":"要压缩的路径(逗号分隔,相对沙盒根目录)"},"output":{"type":"string","description":"输出zip文件名","default":"archive.zip"}},"required":["paths"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        paths = kwargs.get("paths",""); output = kwargs.get("output","archive.zip")
        import zipfile
        items = [p.strip() for p in paths.split(",") if p.strip()]
        out_path = _resolve(sandbox_root, output)
        if not out_path: return "错误: 输出路径超出沙盒"
        try:
            with zipfile.ZipFile(out_path,"w",zipfile.ZIP_DEFLATED) as zf:
                for item in items:
                    ap = _resolve(sandbox_root, item)
                    if not ap: return f"错误: 路径超出沙盒: {item}"
                    if os.path.isfile(ap):
                        zf.write(ap, item)
                    elif os.path.isdir(ap):
                        for root, _, files in os.walk(ap):
                            for f in files:
                                fp = os.path.join(root, f)
                                zf.write(fp, os.path.relpath(fp, sandbox_root))
            return f"已压缩 {len(items)} 项到 {output} ({_fmt_size(os.path.getsize(out_path))})"
        except Exception as e: return f"压缩失败: {e}"

class SearchFilesTool(SandboxTool):
    name = "search_files"; display_name = "搜索文件"
    description = "在沙盒目录中按名称模式搜索文件。支持通配符如 *.txt, data*.csv"
    permission_key = "list_files"
    parameters = {"type":"object","properties":{"pattern":{"type":"string","description":"文件名模式(支持通配符 *,?)"},"path":{"type":"string","description":"搜索目录(相对沙盒根目录)","default":""}},"required":["pattern"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        pattern = kwargs.get("pattern","*"); rp = kwargs.get("path","")
        import fnmatch
        root = Path(sandbox_root).resolve()
        target = root if not rp else (root/rp).resolve()
        try: target.relative_to(root)
        except: return f"错误: 路径超出沙盒: {rp}"
        try:
            results = []
            for f in target.rglob("*"):
                if f.is_file() and fnmatch.fnmatch(f.name, pattern):
                    rel = f.relative_to(root)
                    results.append(f"[F] {rel} ({_fmt_size(f.stat().st_size)})")
            if not results: return f"未找到匹配 '{pattern}' 的文件"
            return f"找到 {len(results)} 个文件:\n" + "\n".join(results[:50])
        except Exception as e: return f"搜索失败: {e}"

class SystemInfoTool(SandboxTool):
    name = "system_info"; display_name = "系统信息"
    description = "获取沙盒运行环境信息：操作系统、Python版本、磁盘空间、内存等。"
    permission_key = ""
    parameters = {"type":"object","properties":{"info_type":{"type":"string","description":"信息类型: all/os/python/disk/memory","default":"all"}}}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        it = kwargs.get("info_type","all")
        import platform, shutil
        lines = []
        if it in ("all","os"): lines.append(f"系统: {platform.system()} {platform.release()} {platform.version()}")
        if it in ("all","python"): lines.append(f"Python: {sys.version}")
        if it in ("all","disk"):
            usage = shutil.disk_usage(sandbox_root)
            lines.append(f"磁盘: 总{_fmt_size(usage.total)} 可用{_fmt_size(usage.free)}")
        if it in ("all","memory"):
            try:
                import psutil
                mem = psutil.virtual_memory()
                lines.append(f"内存: 总{_fmt_size(mem.total)} 可用{_fmt_size(mem.available)}")
            except: lines.append("内存: 无法获取(无psutil)")
        return "\n".join(lines) if lines else "未知类型"

class WebSearchTool(SandboxTool):
    name = "web_search"; display_name = "搜索网络"
    description = "搜索互联网获取实时信息。当用户询问最新信息、时事、或需要联网查询时使用。"
    permission_key = ""
    parameters = {"type":"object","properties":{"query":{"type":"string","description":"搜索关键词"}},"required":["query"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        query = kwargs.get("query","")
        if not query: return "错误: 搜索词不能为空"
        import httpx
        pu = getattr(self, '_proxy_url', '') or None
        try:
            async with httpx.AsyncClient(timeout=15, proxy=pu) as c:
                r = await c.get(f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1")
                data = r.json()
                results = []
                for topic in data.get("RelatedTopics", [])[:5]:
                    if "Text" in topic:
                        results.append(topic["Text"])
                return "\n".join(results) if results else "无搜索结果"
        except Exception as e: return f"搜索失败: {e}"

class PdfExtractTool(SandboxTool):
    name = "pdf_extract"; display_name = "提取PDF文本"
    description = "从PDF文件中提取文本内容。需要安装 PyMuPDF(fitz)。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"path":{"type":"string","description":"PDF路径(相对沙盒根目录)"}},"required":["path"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        rp = kwargs.get("path","")
        ap = _resolve(sandbox_root, rp)
        if not ap: return f"错误: 路径超出沙盒: {rp}"
        if not os.path.isfile(ap): return f"错误: 文件不存在: {rp}"
        try:
            import fitz
            doc = fitz.open(ap)
            text = "\n".join([page.get_text() for page in doc])
            doc.close()
            if len(text) > 10000: text = text[:10000] + "\n...(截断)"
            return text or "(无文本内容)"
        except ImportError: return "错误: 需要安装 PyMuPDF (pip install PyMuPDF)"
        except Exception as e: return f"PDF提取失败: {e}"

class OcrTool(SandboxTool):
    name = "ocr_image"; display_name = "图片文字识别(OCR)"
    description = "从图片中识别提取文字。需要安装 pytesseract 和 Tesseract-OCR。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"image_path":{"type":"string","description":"图片路径(相对沙盒根目录)"},"lang":{"type":"string","description":"语言(chi_sim=中文,eng=英文)","default":"chi_sim+eng"}},"required":["image_path"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        ip = kwargs.get("image_path",""); lang = kwargs.get("lang","chi_sim+eng")
        ap = _resolve(sandbox_root, ip)
        if not ap: return f"错误: 路径超出沙盒: {ip}"
        if not os.path.isfile(ap): return f"错误: 文件不存在: {ip}"
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(ap)
            text = pytesseract.image_to_string(img, lang=lang)
            return text.strip() or "(未识别到文字)"
        except ImportError: return "错误: 需要安装 pytesseract (pip install pytesseract)"
        except Exception as e: return f"OCR失败: {e}"

class TranslateTool(SandboxTool):
    name = "translate"; display_name = "翻译"
    description = "翻译文本。支持多语言互译（中/英/日/韩/法等）。"
    permission_key = ""
    parameters = {"type":"object","properties":{"text":{"type":"string","description":"要翻译的文本"},"target_lang":{"type":"string","description":"目标语言: zh/en/ja/ko/fr/de/es","default":"zh"}},"required":["text"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        text = kwargs.get("text",""); target = kwargs.get("target_lang","zh")
        if not text: return "错误: 文本不能为空"
        try:
            import httpx
            pu = getattr(self, '_proxy_url', '') or None
            async with httpx.AsyncClient(timeout=15, proxy=pu) as c:
                resp = await c.post("https://api.mymemory.translated.net/get", data={"q": text, "langpair": f"auto|{target}"})
                data = resp.json()
                return data.get("responseData", {}).get("translatedText", "") or "(翻译失败)"
        except Exception as e: return f"翻译失败: {e}"

class HashTool(SandboxTool):
    name = "hash_text"; display_name = "哈希/加密"
    description = "计算文本的哈希值(MD5/SHA1/SHA256)或Base64编解码。"
    permission_key = ""
    parameters = {"type":"object","properties":{"text":{"type":"string","description":"要处理的文本"},"algorithm":{"type":"string","description":"算法: md5/sha1/sha256/base64_encode/base64_decode","default":"md5"}},"required":["text"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        text = kwargs.get("text",""); algo = kwargs.get("algorithm","md5")
        import hashlib, base64
        try:
            if algo == "md5": return hashlib.md5(text.encode()).hexdigest()
            if algo == "sha1": return hashlib.sha1(text.encode()).hexdigest()
            if algo == "sha256": return hashlib.sha256(text.encode()).hexdigest()
            if algo == "base64_encode": return base64.b64encode(text.encode()).decode()
            if algo == "base64_decode":
                try: return base64.b64decode(text).decode()
                except: return "(Base64解码失败，非有效编码)"
            return f"未知算法: {algo}"
        except Exception as e: return f"错误: {e}"

class DateTimeTool(SandboxTool):
    name = "datetime_tool"; display_name = "日期时间"
    description = "获取当前时间/日期，或进行时间格式转换、时区查询。"
    permission_key = ""
    parameters = {"type":"object","properties":{"action":{"type":"string","description":"操作: now/timestamp/format","default":"now"},"format":{"type":"string","description":"时间格式(如 %Y-%m-%d %H:%M:%S)","default":""},"timestamp":{"type":"integer","description":"时间戳(秒)","default":0}}}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        action = kwargs.get("action","now"); fmt = kwargs.get("format",""); ts = kwargs.get("timestamp",0)
        from datetime import datetime, timezone
        try:
            if action == "now":
                now = datetime.now()
                return now.strftime(fmt or "%Y-%m-%d %H:%M:%S")
            if action == "timestamp":
                return str(int(datetime.now().timestamp()))
            if action == "format" and ts > 0:
                dt = datetime.fromtimestamp(ts)
                return dt.strftime(fmt or "%Y-%m-%d %H:%M:%S")
            return datetime.now().isoformat()
        except Exception as e: return f"错误: {e}"

class DataConvertTool(SandboxTool):
    name = "convert_data"; display_name = "数据格式转换"
    description = "在CSV/JSON/XML/YAML之间转换数据格式。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"input_path":{"type":"string","description":"输入文件路径(相对沙盒根目录)"},"output_format":{"type":"string","description":"目标格式: json/csv/yaml/xml"},"output_path":{"type":"string","description":"输出文件路径(可选)","default":""}},"required":["input_path","output_format"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        ip = kwargs.get("input_path",""); of = kwargs.get("output_format","json"); op = kwargs.get("output_path","")
        ap = _resolve(sandbox_root, ip)
        if not ap or not os.path.isfile(ap): return "错误: 文件不存在"
        try:
            ext = os.path.splitext(ap)[1].lower()
            import csv, json, io
            data = None
            with open(ap, "r", encoding="utf-8") as f:
                if ext == ".csv":
                    reader = csv.DictReader(f)
                    data = [row for row in reader]
                elif ext in (".json",):
                    data = json.load(f)
                elif ext in (".yaml", ".yml"):
                    import yaml
                    data = yaml.safe_load(f)
                else: return f"不支持输入格式: {ext}"
            if data is None: return "错误: 无法读取数据"
            out = ""
            if of == "json":
                out = json.dumps(data, ensure_ascii=False, indent=2)
            elif of == "csv":
                if isinstance(data, list) and data:
                    output = io.StringIO()
                    w = csv.DictWriter(output, fieldnames=data[0].keys())
                    w.writeheader(); w.writerows(data)
                    out = output.getvalue()
                else: return "数据格式无法转为CSV"
            elif of == "yaml":
                import yaml
                out = yaml.dump(data, allow_unicode=True)
            elif of == "xml":
                out = json.dumps(data, ensure_ascii=False, indent=2) + "\n(XML转换需安装dicttoxml)"
            else: return f"不支持输出格式: {of}"
            if op:
                op_path = _resolve(sandbox_root, op)
                if op_path:
                    with open(op_path, "w", encoding="utf-8") as f:
                        f.write(out)
                    return f"已转换并保存到: {op} ({len(out)}字符)"
            return f"转换结果:\n{out[:3000]}"
        except ImportError as e: return f"需要安装依赖: {e}"
        except Exception as e: return f"转换失败: {e}"

class QRCodeTool(SandboxTool):
    name = "qrcode"; display_name = "二维码生成"
    description = "生成二维码图片并保存到沙盒。需要安装 qrcode 和 Pillow。"
    permission_key = "write_file"
    parameters = {"type":"object","properties":{"text":{"type":"string","description":"二维码内容(URL/文本)"},"filename":{"type":"string","description":"文件名","default":"qrcode.png"}},"required":["text"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        text = kwargs.get("text",""); fname = kwargs.get("filename","qrcode.png")
        if not text: return "错误: 内容不能为空"
        ap = _resolve(sandbox_root, fname)
        if not ap: return "错误: 路径超出沙盒"
        try:
            import qrcode
            img = qrcode.make(text)
            img.save(ap)
            return f"二维码已生成: {fname} (内容: {text[:50]})"
        except ImportError: return "错误: 需要安装 qrcode (pip install qrcode[pil])"
        except Exception as e: return f"生成失败: {e}"

class ChartTool(SandboxTool):
    name = "create_chart"; display_name = "创建图表"
    description = "根据数据创建图表(折线图/柱状图/饼图/散点图)。需要安装 matplotlib。"
    permission_key = "execute_python"
    parameters = {"type":"object","properties":{"data":{"type":"string","description":"数据(JSON数组,如[{\"x\":\"A\",\"y\":10},...])"},"chart_type":{"type":"string","description":"图表类型: line/bar/pie/scatter","default":"bar"},"title":{"type":"string","description":"图表标题","default":""},"filename":{"type":"string","description":"保存文件名","default":"chart.png"}},"required":["data"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        data_json = kwargs.get("data","[]"); ct = kwargs.get("chart_type","bar"); title = kwargs.get("title",""); fname = kwargs.get("filename","chart.png")
        ap = _resolve(sandbox_root, fname)
        if not ap: return "错误: 路径超出沙盒"
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import json
            data = json.loads(data_json) if isinstance(data_json, str) else data_json
            if not data: return "错误: 数据为空"
            plt.rcParams["font.sans-serif"] = ["SimHei", "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            fig, ax = plt.subplots(figsize=(8, 5))
            if ct == "bar":
                ax.bar([d.get("x",d.get("label","")) for d in data], [d.get("y",d.get("value",0)) for d in data])
            elif ct == "line":
                ax.plot([d.get("x",d.get("label","")) for d in data], [d.get("y",d.get("value",0)) for d in data], marker="o")
            elif ct == "pie":
                ax.pie([d.get("y",d.get("value",0)) for d in data], labels=[d.get("x",d.get("label","")) for d in data], autopct="%1.1f%%")
            elif ct == "scatter":
                xs = [d.get("x",i) for i,d in enumerate(data)]
                ys = [d.get("y",d.get("value",0)) for d in data]
                ax.scatter(xs, ys)
            if title: ax.set_title(title)
            plt.tight_layout()
            fig.savefig(ap, dpi=150)
            plt.close(fig)
            return f"图表已保存: {fname}"
        except ImportError: return "错误: 需要安装 matplotlib (pip install matplotlib)"
        except Exception as e: return f"创建图表失败: {e}"

class SendFileTool(SandboxTool):
    name = "send_file"; display_name = "发送文件给用户"
    description = "将沙盒内的文件发送给QQ用户。支持图片/视频/音频/文档等格式。"
    permission_key = "read_file"
    _last_file = ""
    parameters = {"type":"object","properties":{"file_path":{"type":"string","description":"文件路径(相对沙盒根目录)"},"description":{"type":"string","description":"文件描述","default":""}},"required":["file_path"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        fp = kwargs.get("file_path",""); desc = kwargs.get("description","")
        ap = _resolve(sandbox_root, fp)
        if not ap: return f"错误: 路径超出沙盒: {fp}"
        if not os.path.isfile(ap): return f"错误: 文件不存在: {fp}"
        size = os.path.getsize(ap)
        fname = os.path.basename(ap)
        self._last_file = ap
        return f"已准备发送文件: {fname} ({_fmt_size(size)})\n{('描述: '+desc) if desc else ''}"

class GetGroupMembersTool(SandboxTool):
    name = "get_group_members"; display_name = "获取群成员"
    description = "获取指定群聊的成员列表。需要群聊的 openid。返回成员ID列表。"
    permission_key = ""
    parameters = {"type":"object","properties":{"group_openid":{"type":"string","description":"群聊 openid"}},"required":["group_openid"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        gid = kwargs.get("group_openid","")
        if not gid:
            return "错误: 缺少 group_openid"
        bm = getattr(self, '_bot_manager', None)
        bot_id = getattr(self, '_current_bot_id', "")
        if not bm:
            return "错误: Bot管理器不可用"
        platform = bm.get_platform(bot_id) if hasattr(bm, 'get_platform') else None
        if not platform or not hasattr(platform, '_client') or not platform._client:
            return "错误: 机器人未连接"
        try:
            from botpy.http import Route
            route = Route("GET", "/v2/groups/{group_openid}/members", group_openid=gid)
            import asyncio
            loop = platform._loop
            if not loop or loop.is_closed():
                return "错误: 机器人事件循环已关闭"
            future = asyncio.run_coroutine_threadsafe(
                platform._client.api._http.request(route),
                loop,
            )
            result = future.result(timeout=15)
            if isinstance(result, dict):
                members = result.get("members", []) or result.get("data", [])
                if members:
                    lines = [f"   {m.get('id','')} {m.get('username','')}" for m in members[:50]]
                    return f"群成员 ({len(members)} 人):\n" + "\n".join(lines)
                return f"API返回: {json.dumps(result, ensure_ascii=False)[:500]}"
            return f"API返回: {str(result)[:500]}"
        except Exception as e:
            return f"获取群成员失败: {e}"

class GetKnownGroupsTool(SandboxTool):
    name = "get_known_groups"; display_name = "已知群聊列表"
    description = "列出机器人曾互动过的群聊。返回群聊名称和openid。"
    permission_key = ""
    parameters = {"type":"object","properties":{}}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        if not _known_groups:
            return "暂无已知群聊。机器人收到群消息后会自动记录。"
        lines = []
        import time
        now = time.time()
        for gid, info in sorted(_known_groups.items(), key=lambda x: x[1].get("last_seen", 0), reverse=True):
            name = info.get("name", gid)[:20]
            last_seen = now - info.get("last_seen", 0)
            ls_str = f"{int(last_seen)}秒前" if last_seen < 3600 else f"{int(last_seen/60)}分钟前" if last_seen < 86400 else f"{int(last_seen/86400)}天前"
            lines.append(f"  [{gid[:12]}...] {name} ({ls_str})")
        return f"已知群聊 ({len(lines)} 个):\n" + "\n".join(lines)

class SendGroupMessageTool(SandboxTool):
    name = "send_group_message"; display_name = "发送群消息"
    description = "向指定的群聊发送消息。需要群聊的 openid。注意：只能在私聊中使用此工具，用于将消息转发到群聊。"
    permission_key = ""  # always allowed - controlled by msg_type check in AI stage
    parameters = {"type":"object","properties":{"group_openid":{"type":"string","description":"目标群聊的 openid"},"content":{"type":"string","description":"消息内容"}},"required":["group_openid","content"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        group_openid = kwargs.get("group_openid","")
        content = kwargs.get("content","")
        if not group_openid or not content:
            return "错误: 缺少 group_openid 或 content"
        bm = getattr(self, '_bot_manager', None)
        bot_id = getattr(self, '_current_bot_id', "")
        if not bm:
            return "错误: Bot管理器不可用"
        try:
            success = await bm.send_message(channel_id=group_openid, content=content, bot_id=bot_id)
            if success:
                return f"消息已成功发送到群聊 {group_openid}"
            return f"错误: 发送到群聊 {group_openid} 失败"
        except Exception as e:
            return f"发送错误: {e}"

class CleanSandboxTool(SandboxTool):
    name = "clean_sandbox"; display_name = "清理沙盒"
    description = "清理沙盒目录中的临时文件和生成的文件。保留目录结构，只删除 outputs/、downloads/、temp/ 等目录下的文件，以及沙盒根目录的 .py/.png/.jpg/.txt/.zip 文件。"
    permission_key = "write_file"
    parameters = {"type":"object","properties":{"confirm":{"type":"boolean","description":"确认清理，必须为true"}},"required":["confirm"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        if not kwargs.get("confirm"):
            return "错误: 请设置 confirm=true 确认清理操作"
        import shutil
        removed = 0; errors = 0; kept_dirs = 0
        # Clean specific subdirectories
        for sub in ("outputs", "downloads", "temp", "_cache"):
            sp = os.path.join(sandbox_root, sub)
            if os.path.isdir(sp):
                try:
                    for entry in os.listdir(sp):
                        ep = os.path.join(sp, entry)
                        try:
                            if os.path.isfile(ep) or os.path.islink(ep):
                                os.remove(ep); removed += 1
                            elif os.path.isdir(ep):
                                shutil.rmtree(ep); removed += 1
                        except Exception:
                            errors += 1
                    kept_dirs += 1
                except Exception:
                    errors += 1
        # Clean root-level generated files
        for entry in os.listdir(sandbox_root):
            ep = os.path.join(sandbox_root, entry)
            if os.path.isfile(ep):
                ext = os.path.splitext(entry)[1].lower()
                if ext in (".py", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".zip", ".txt", ".csv", ".json", ".xml", ".html", ".pdf"):
                    try:
                        os.remove(ep); removed += 1
                    except Exception:
                        errors += 1
        msg = f"清理完成: 删除了 {removed} 个文件"
        if errors: msg += f", {errors} 个错误"
        if kept_dirs: msg += f", 保留了 {kept_dirs} 个子目录"
        return msg

TOOL_REGISTRY: List[SandboxTool] = [
    ExecutePythonTool(), ReadFileTool(), WriteFileTool(),
    ListFilesTool(), RunShellTool(),
    GenerateImageTool(), AnalyzeImageTool(), GenerateVideoTool(),
    WebDownloadTool(), CompressTool(), SearchFilesTool(), SystemInfoTool(),
    WebSearchTool(),
    PdfExtractTool(), OcrTool(), TranslateTool(), HashTool(),
    DateTimeTool(), DataConvertTool(), QRCodeTool(), ChartTool(),
    SendFileTool(), CleanSandboxTool(), SendGroupMessageTool(),
    GetGroupMembersTool(), GetKnownGroupsTool(),
]

def get_tool_definitions(perms: Optional[ToolPermissions] = None) -> List[dict]:
    result = []
    for t in TOOL_REGISTRY:
        if perms and not t.is_allowed(perms): continue
        result.append(t.to_openai_tool())
    return result

def get_tool_by_name(name: str) -> Optional[SandboxTool]:
    for t in TOOL_REGISTRY:
        if t.name == name: return t
    return None

def set_tool_config(config, sandbox_manager=None, bot_manager=None):
    for t in TOOL_REGISTRY:
        t.config = config
        t._sandbox_manager = sandbox_manager
        t._bot_manager = bot_manager
        # Expose proxy URL for tools that make HTTP requests from the main process
        t._proxy_url = (
            sandbox_manager.proxy_sandbox.proxy_url
            if sandbox_manager and getattr(sandbox_manager, 'proxy_sandbox', None)
            else ""
        )

def _resolve(sandbox_root: str, rel_path: str) -> Optional[str]:
    root = Path(sandbox_root).resolve()
    target = (root / rel_path).resolve()
    try: target.relative_to(root); return str(target)
    except ValueError: return None

def _fmt_size(size):
    for u in ["B","KB","MB","GB"]:
        if size<1024:
            return f"{size:.1f}{u}"
        size /= 1024
    return f"{size:.1f}TB"
