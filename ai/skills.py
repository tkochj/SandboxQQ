import os
import logging
from typing import List, Optional
from ai.config import SkillConfig

logger = logging.getLogger(__name__)

BUILTIN_SKILLS = [
    SkillConfig(
        name="数据分析",
        description="分析CSV/JSON/Excel等数据文件，生成统计报告和可视化图表",
        system_prompt=(
            "你是一个数据分析专家。当用户提供数据文件时：\n"
            "1. 先用 list_files 确认文件位置\n"
            "2. 用 read_file 读取数据了解结构\n"
            "3. 用 execute_python 执行分析（使用 pandas/matplotlib）\n"
            "4. 将图表保存为图片文件，用文字描述分析结果"
        ),
    ),
    SkillConfig(
        name="代码审查",
        description="审查沙盒内代码文件，提供改进建议",
        system_prompt=(
            "你是一个代码审查专家。审查用户指定的代码文件：\n"
            "1. 读取代码文件\n"
            "2. 分析代码质量、安全性、性能\n"
            "3. 给出具体的改进建议和示例代码\n"
            "4. 可执行代码验证建议的正确性"
        ),
    ),
    SkillConfig(
        name="文件整理",
        description="自动整理沙盒目录内的文件，按类型/日期分类",
        system_prompt=(
            "你是一个文件管理助手。帮助用户整理沙盒目录：\n"
            "1. 扫描目录结构\n"
            "2. 按文件类型/日期/大小分类\n"
            "3. 创建分类子目录并移动文件\n"
            "4. 生成整理报告"
        ),
    ),
    SkillConfig(
        name="网页抓取",
        description="从网页获取信息(需要网络权限)",
        system_prompt=(
            "你是一个网页信息获取助手。当用户需要从网页获取信息时：\n"
            "1. 使用 Python requests/httpx 获取网页内容\n"
            "2. 解析提取有用信息\n"
            "3. 将结果保存到沙盒文件或直接返回"
        ),
    ),
    SkillConfig(
        name="图片处理",
        description="处理图片：格式转换、缩放、裁剪、添加水印等",
        system_prompt=(
            "你是一个图片处理专家。当用户需要处理图片时：\n"
            "1. 使用 Pillow 库读取和操作图片\n"
            "2. 支持格式转换(jpg/png/webp)、缩放、裁剪、旋转\n"
            "3. 支持添加文字水印、滤镜效果\n"
            "4. 处理后的图片保存到沙盒并告知用户路径"
        ),
    ),
    SkillConfig(
        name="文档生成",
        description="生成各种文档：PDF报告、Markdown文档、Excel报表等",
        system_prompt=(
            "你是一个文档生成助手。根据用户需求生成文档：\n"
            "1. Markdown文档直接写入沙盒文件\n"
            "2. 使用 reportlab 或 fpdf 生成 PDF\n"
            "3. 使用 openpyxl 生成 Excel 报表\n"
            "4. 文档保存后告知用户文件路径"
        ),
    ),
    SkillConfig(
        name="网络工具",
        description="网络诊断和查询：ping、DNS查询、HTTP检测等",
        system_prompt=(
            "你是一个网络工具助手。帮助用户进行网络诊断：\n"
            "1. 使用 socket/httpx 检测网络连通性\n"
            "2. DNS 域名解析查询\n"
            "3. HTTP 请求检测网站状态\n"
            "4. 注意沙盒网络可能有白名单限制"
        ),
    ),
]


class SkillsManager:
    def __init__(self):
        self.skills: List[SkillConfig] = []
        self._load_builtin()

    def _load_builtin(self):
        for s in BUILTIN_SKILLS:
            if not any(x.name == s.name for x in self.skills):
                self.skills.append(s)

    def add(self, skill: SkillConfig):
        self.skills = [s for s in self.skills if s.name != skill.name]
        self.skills.append(skill)

    def remove(self, name: str):
        self.skills = [s for s in self.skills if s.name != name]

    def get(self, name: str) -> Optional[SkillConfig]:
        for s in self.skills:
            if s.name == name:
                return s
        return None

    def get_enabled(self) -> List[SkillConfig]:
        return [s for s in self.skills if s.enabled]

    def to_config_list(self) -> list:
        return [s.to_dict() for s in self.skills]

    def load_from_config(self, skills_data: list):
        for s in skills_data:
            if isinstance(s, dict):
                self.add(SkillConfig.from_dict(s))
            elif isinstance(s, SkillConfig):
                self.add(s)
