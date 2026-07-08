import os, sys, json, logging, subprocess, base64
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
            r = subprocess.run([sys.executable,sp],cwd=sandbox_root,capture_output=True,text=True,timeout=timeout,env={**os.environ,"SANDBOX_ROOT":sandbox_root})
            o = (r.stdout or "") + (("[STDERR]\n"+r.stderr) if r.stderr else "") + (("\n[退出码: "+str(r.returncode)+"]") if r.returncode else "")
            return o.strip() or "(无输出)"
        except subprocess.TimeoutExpired: return f"错误: 超时({timeout}秒)"
        except Exception as e: return f"执行错误: {e}"
        finally:
            try: os.remove(sp)
            except Exception: pass

class ReadFileTool(SandboxTool):
    name = "read_file"; display_name = "读取文件"
    description = "读取沙盒目录内的文件。路径相对于沙盒根目录。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"path":{"type":"string","description":"文件路径(相对沙盒根目录)"},"encoding":{"type":"string","description":"编码","default":"utf-8"}},"required":["path"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        rp = kwargs.get("path",""); enc = kwargs.get("encoding","utf-8")
        ap = _resolve(sandbox_root, rp)
        if not ap: return f"错误: 路径超出沙盒: {rp}"
        if not os.path.isfile(ap): return f"错误: 文件不存在: {rp}"
        try:
            with open(ap,"r",encoding=enc) as f: c = f.read()
            if len(c)>10000: return f"(文件{os.path.getsize(ap)}bytes,显示前10000)\n{c[:10000]}"
            return c
        except Exception as e: return f"读取失败: {e}"

class WriteFileTool(SandboxTool):
    name = "write_file"; display_name = "写入文件"
    description = "写入文件到沙盒目录。路径相对于沙盒根目录，自动创建子目录。"
    permission_key = "write_file"
    parameters = {"type":"object","properties":{"path":{"type":"string","description":"文件路径(相对沙盒根目录)"},"content":{"type":"string","description":"文件内容"}},"required":["path","content"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        rp = kwargs.get("path",""); content = kwargs.get("content","")
        ap = _resolve(sandbox_root, rp)
        if not ap: return f"错误: 路径超出沙盒: {rp}"
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

class RunShellTool(SandboxTool):
    name = "run_shell"; display_name = "Shell命令"
    description = "在沙盒目录内执行shell命令。危险命令自动拦截。"
    permission_key = "run_shell"
    parameters = {"type":"object","properties":{"command":{"type":"string","description":"shell命令"},"timeout":{"type":"integer","description":"超时秒数","default":30}},"required":["command"]}

    async def run(self, sandbox_root: str, **kwargs) -> str:
        cmd = kwargs.get("command",""); timeout = kwargs.get("timeout",30)
        if not cmd.strip(): return "错误: 命令不能为空"
        for d in ["format","del /f","rd /s","rmdir /s","shutdown","taskkill"]:
            if d in cmd.lower(): return f"错误: 危险命令被拦截: {d}"
        try:
            r = subprocess.run(cmd,cwd=sandbox_root,capture_output=True,text=True,timeout=timeout,shell=True)
            o = (r.stdout or "") + ("\n[STDERR]\n"+r.stderr[:2000] if r.stderr else "")
            if len(o)>5000: o = o[:5000]+"\n...(截断)"
            return o.strip() or "(无输出)"
        except subprocess.TimeoutExpired: return f"错误: 超时({timeout}秒)"
        except Exception as e: return f"执行错误: {e}"

class GenerateImageTool(SandboxTool):
    name = "generate_image"; display_name = "生成图片"
    description = "使用AI生成图片。返回图片URL。需要配置图片生成API。"
    permission_key = "execute_python"
    parameters = {"type":"object","properties":{"prompt":{"type":"string","description":"图片描述"},"size":{"type":"string","description":"尺寸 如 1024x1024","default":"1024x1024"}},"required":["prompt"]}
    config = None

    _last_file = ""

    async def run(self, sandbox_root: str, **kwargs) -> str:
        prompt = kwargs.get("prompt",""); size = kwargs.get("size","1024x1024")
        if not self.config or not self.config.image_gen_api_key:
            return "错误: 未配置图片生成API"
        import httpx, aiohttp, uuid
        try:
            url = f"{self.config.image_gen_api_url.rstrip('/')}/images/generations"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(url, json={"model":self.config.image_gen_model or "dall-e-3","prompt":prompt,"n":1,"size":size},
                    headers={"Authorization":f"Bearer {self.config.image_gen_api_key}","Content-Type":"application/json"})
            data = resp.json()
            img_url = data.get("data",[{}])[0].get("url","")
            if img_url:
                ext = os.path.splitext(img_url.split("?")[0])[1] or ".png"
                local = os.path.join(sandbox_root, f"gen_img_{uuid.uuid4().hex}{ext}")
                try:
                    async with aiohttp.ClientSession() as sess:
                        async with sess.get(img_url, timeout=30) as r:
                            if r.status == 200:
                                with open(local, "wb") as f:
                                    f.write(await r.read())
                                if os.path.isfile(local) and os.path.getsize(local) > 0:
                                    self._last_file = local
                                    return f"图片已生成并保存到: {local}\n图片链接: {img_url}"
                except Exception:
                    pass
                return f"图片已生成: {img_url}"
            return f"生成结果: {json.dumps(data,ensure_ascii=False)[:500]}"
        except Exception as e: return f"生成失败: {e}"

class AnalyzeImageTool(SandboxTool):
    name = "analyze_image"; display_name = "分析图片"
    description = "使用AI分析图片内容。读取沙盒内的图片文件并返回描述。"
    permission_key = "read_file"
    parameters = {"type":"object","properties":{"image_path":{"type":"string","description":"图片路径(相对沙盒根目录)"},"question":{"type":"string","description":"关于图片的问题","default":"请描述这张图片"}},"required":["image_path"]}
    config = None

    async def run(self, sandbox_root: str, **kwargs) -> str:
        ip = kwargs.get("image_path",""); question = kwargs.get("question","请描述这张图片")
        ap = _resolve(sandbox_root, ip)
        if not ap: return f"错误: 路径超出沙盒: {ip}"
        if not os.path.isfile(ap): return f"错误: 文件不存在: {ip}"
        try:
            with open(ap,"rb") as f: b64 = base64.b64encode(f.read()).decode()
            ext = Path(ap).suffix.lower()
            mime = {"jpg":"image/jpeg","jpeg":"image/jpeg","png":"image/png","gif":"image/gif","webp":"image/webp"}.get(ext.lstrip("."),"image/png")
            data_url = f"data:{mime};base64,{b64}"
            if self.config and self.config.vision_api_key:
                import httpx
                api_url = (self.config.vision_api_url or self.config.api_url).rstrip("/") + "/chat/completions"
                api_key = self.config.vision_api_key or self.config.api_key
                model = self.config.vision_model or self.config.model
                payload = {"model":model,"messages":[{"role":"user","content":[{"type":"text","text":question},{"type":"image_url","image_url":{"url":data_url}}]}],"max_tokens":1024}
                async with httpx.AsyncClient(timeout=60) as client:
                    resp = await client.post(api_url, json=payload,
                        headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"})
                    resp.raise_for_status()
                    return resp.json()["choices"][0]["message"]["content"]
            return f"图片已读取({os.path.getsize(ap)}bytes)，未配置识图模型"
        except Exception as e: return f"分析失败: {e}"

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
        try:
            url = f"{self.config.video_gen_api_url.rstrip('/')}/video/generations"
            async with httpx.AsyncClient(timeout=120) as client:
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
        fname = save_path or os.path.basename(url.split("?")[0]) or f"download_{uuid.uuid4().hex}"
        ap = _resolve(sandbox_root, fname) if not save_path else _resolve(sandbox_root, save_path)
        if not ap: return f"错误: 路径超出沙盒"
        try:
            async with aiohttp.ClientSession() as sess:
                async with sess.get(url, timeout=60) as r:
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

TOOL_REGISTRY: List[SandboxTool] = [
    ExecutePythonTool(), ReadFileTool(), WriteFileTool(),
    ListFilesTool(), RunShellTool(),
    GenerateImageTool(), AnalyzeImageTool(), GenerateVideoTool(),
    WebDownloadTool(), CompressTool(), SearchFilesTool(), SystemInfoTool(),
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

def set_tool_config(config):
    for t in TOOL_REGISTRY:
        t.config = config

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
