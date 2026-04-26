from __future__ import annotations

"""
CodeQuerySkill — 多项目代码知识库查询

支持用自然语言查询任意已注册项目的：
  - 某接口被哪些页面调用（query_interface）
  - 某页面的接口/跳转/功能详情（query_page）
  - 某页面被哪些页面调用/跳转来源（query_navigation）
  - 项目概览（query_overview）

使用示例：
  "查一下 OA 里 vs/api/oa_getajax 被哪些页面用了"
  "OA 的 MattersTodoDetails_NewActivity 有哪些接口"
  "OA 里谁会跳转到登录页"
  "OA 大概有哪些模块"
"""

import json
import re
import requests
from pathlib import Path

from .base import BaseSkill, Intent
from .project_registry import PROJECTS, find_project, list_projects
from qingagent import config


# ── LLM 调用工具 ────────────────────────────────────────────────

def _ask_llm(system_prompt: str, user_prompt: str, max_tokens: int = 800) -> str:
    """直接调用本机 MLX 模型（与 Planner 同一个接口）。"""
    url = config.PLANNER_URL.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {config.API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": config.PLANNER_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": 0.2,
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"（AI 推理失败：{e}）"


# ── 知识库读取工具 ──────────────────────────────────────────────

def _load_file(docs_root: str, relative: str, max_chars: int = 80000) -> str:
    """读取知识库文件，截断超长内容。"""
    p = Path(docs_root) / relative
    if not p.exists():
        return f"（文件不存在：{relative}）"
    content = p.read_text("utf-8", errors="ignore")
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n…（内容过长，已截断）"
    return content


def _load_page_json(docs_root: str, page_id: str) -> str:
    """按 page_id 加载单页详情 JSON，找不到时返回提示。"""
    kg_dir = Path(docs_root) / "page_knowledge"
    # 精确匹配
    target = kg_dir / f"{page_id}.json"
    if target.exists():
        return target.read_text("utf-8", errors="ignore")
    # 模糊匹配（忽略大小写）
    pid_lower = page_id.lower()
    for f in kg_dir.glob("*.json"):
        if pid_lower in f.stem.lower():
            return f.read_text("utf-8", errors="ignore")
    return f"（未找到页面 {page_id} 的知识卡）"


def _search_in_file(content: str, keyword: str, context_lines: int = 4) -> str:
    """在文件内容里检索关键词，返回命中段落（最多 10 处）。"""
    lines = content.splitlines()
    hits = []
    for i, line in enumerate(lines):
        if keyword.lower() in line.lower():
            start = max(0, i - 1)
            end   = min(len(lines), i + context_lines)
            hits.append("\n".join(lines[start:end]))
            if len(hits) >= 10:
                break
    return "\n\n---\n\n".join(hits) if hits else "（未找到匹配内容）"


# ── Skill 定义 ──────────────────────────────────────────────────

class CodeQuerySkill(BaseSkill):
    """多项目代码知识库查询 Skill。"""

    app_name    = "CodeQuery"
    ui_label    = "代码知识库查询"
    app_aliases = [
        "查代码", "查项目", "查接口", "查页面", "查跳转",
        "代码查询", "oa查询", "项目知识库",
        "查一下", "帮我查",
    ]
    app_context = "代码知识库查询"

    # 不需要激活任何 App
    def activate(self): return True
    def find_window(self): return True

    def register_intents(self):

        self.add_intent(Intent(
            name="query_interface",
            description="查询某个项目中某个接口（API）被哪些页面/类调用",
            required_slots=["query"],
            optional_slots=[],
            examples=[
                "查一下 OA 里 vs/api/oa_getajax 被哪些页面用了",
                "OA 中 oa_signin 接口是哪个页面调的",
                "帮我查 OA 的打卡接口在哪里被调用",
                "oa 的登录接口有哪些页面用到了",
            ],
        ))

        self.add_intent(Intent(
            name="query_page",
            description="查询某个项目中某个页面/Activity/Fragment 的接口、跳转、功能详情",
            required_slots=["query"],
            optional_slots=[],
            examples=[
                "OA 的 MattersTodoDetails_NewActivity 有哪些接口",
                "查一下 OA 里 LoginActivity 的详情",
                "帮我看看 OA 的审批详情页有哪些功能",
                "oa 考勤页面用了哪些接口",
            ],
        ))

        self.add_intent(Intent(
            name="query_navigation",
            description="查询某个项目中某个页面的跳转来源（谁调用了它）或跳转目标",
            required_slots=["query"],
            optional_slots=[],
            examples=[
                "OA 里谁会跳转到登录页",
                "OA 的首页能跳到哪些页面",
                "帮我查 OA MattersTodoListActivity 的入口在哪里",
                "oa 审批列表页是从哪里进来的",
            ],
        ))

        self.add_intent(Intent(
            name="query_overview",
            description="查询某个项目的整体结构、模块划分、功能概览",
            required_slots=["query"],
            optional_slots=[],
            examples=[
                "OA 有哪些模块",
                "帮我介绍一下 OA 项目结构",
                "OA 大概有哪些功能",
                "现在有哪些项目的知识库",
            ],
        ))

    # ──────────────────────────────────────────────────────────────
    #  执行方法
    # ──────────────────────────────────────────────────────────────

    def _resolve_project(self, query: str) -> "tuple":
        """从 query 中识别项目，返回 (cfg, 无法识别时的提示)。"""
        result = find_project(query)
        if result:
            _, cfg = result
            return cfg, ""
        # 没识别到，列出所有项目让用户选
        tip = "未识别到目标项目，请在问题中包含项目名称。\n\n" + list_projects()
        return None, tip

    def execute_query_interface(self, slots: dict) -> dict:
        """查询某接口被哪些页面调用（直接解析 api_catalog.md，不调 LLM）。"""
        query = slots.get("query", "")
        cfg, err = self._resolve_project(query)
        if not cfg:
            return {"success": False, "message": err, "data": None}

        catalog = _load_file(cfg["docs_root"], cfg["api_catalog"])

        # 关键词清洗
        keyword = re.sub(
            r'(?:oa|fangapp|查一下|帮我查|的|里|中|接口|被|哪些|页面|调用了|用了|在哪|有没有|和|相关)',
            '', query, flags=re.IGNORECASE
        ).strip()

        if not keyword:
            return {"success": False, "message": "请提供要查询的接口关键词，例如：AppCompanyCoord", "data": None}

        # 解析 api_catalog.md：提取命中的接口块
        # 格式：## `URL`\n**调用页面**：PageA · PageB
        block_pattern = re.compile(
            r'##\s+`([^`]+)`\s*\n\*\*调用页面\*\*：(.+?)(?=\n##|\Z)', re.DOTALL
        )
        results = []
        for m in block_pattern.finditer(catalog):
            url = m.group(1).strip()
            pages_raw = m.group(2).strip()
            if keyword.lower() in url.lower() or keyword.lower() in pages_raw.lower():
                pages = [p.strip() for p in re.split(r'[·\·\s]+', pages_raw) if p.strip()]
                results.append({"url": url, "pages": pages})

        if not results:
            tip = "未找到包含「" + keyword + "」的相关接口，请换其他关键词。"
            return {"success": True, "message": tip, "data": None}

        # 格式化输出
        lines = [f"找到 {len(results)} 个相关接口：\n"]
        all_pages = set()
        for i, r in enumerate(results, 1):
            url = r["url"]
            # 提取 method 名（URL 末尾的 method=xxx 或接口路径最后一段）
            method_match = re.search(r'method=(\w+)', url) or re.search(r'/(\w+)$', url)
            short_name = method_match.group(1) if method_match else url
            pages = r["pages"]
            all_pages.update(pages)
            lines.append(f"{'①②③④⑤⑥⑦⑧⑨⑩'[i-1] if i <= 10 else str(i)+'.'} {short_name}")
            lines.append(f"   完整路径：{url}")
            lines.append(f"   调用页面（共 {len(pages)} 个）：{'、'.join(pages)}")
            lines.append("")

        lines.append(f"影响范围：以上 {len(all_pages)} 个页面涉及该接口，后台改动时需联动验证。")

        return {"success": True, "message": "\n".join(lines), "data": {"count": len(results)}}


    def execute_query_page(self, slots: dict) -> dict:
        """查询某页面的详情。"""
        query = slots.get("query", "")
        cfg, err = self._resolve_project(query)
        if not cfg:
            return {"success": False, "message": err, "data": None}

        # 尝试从 query 里提取类名
        # 匹配 XxxActivity / XxxFragment 等
        match = re.search(r'([A-Z]\w+(?:Activity|Fragment|Page|Screen))', query)
        if match:
            page_id = match.group(1)
        else:
            # 用关键词在 nav_reverse.md 里模糊匹配
            nav = _load_file(cfg["docs_root"], cfg["nav_reverse"])
            keyword = re.sub(
                r'(?:oa|fangapp|查一下|帮我|的|里|中|页面|详情|接口|功能)',
                '', query, flags=re.IGNORECASE
            ).strip()
            hits = _search_in_file(nav, keyword)
            system = f"从下面的导航索引中，提取出用户询问的页面的 Activity/Fragment 类名（只回答类名，不要其他内容）："
            page_id = _ask_llm(system, f"用户问题：{query}\n\n片段：{hits}", max_tokens=50).strip()

        page_json = _load_page_json(cfg["docs_root"], page_id)

        system = (
            f"你是 {cfg['name']} 项目的代码助手，用中文回答。"
            "根据页面知识卡回答，格式如下：\n"
            "【页面】类名 — 一句话说明这个页面做什么\n"
            "【接口】每条接口路径后括号说明用途，无数据写暂无记录\n"
            "【跳转来源】谁会打开这个页面及触发条件，无数据写暂无记录\n"
            "【跳转去向】能跳到哪些页面，无数据写暂无记录"
        )
        user = f"问题：{query}\n\n页面知识卡（{page_id}）：\n{page_json}"
        answer = _ask_llm(system, user)

        return {"success": True, "message": answer, "data": {"page_id": page_id}}

    def execute_query_navigation(self, slots: dict) -> dict:
        """查询页面跳转来源/目标。"""
        query = slots.get("query", "")
        cfg, err = self._resolve_project(query)
        if not cfg:
            return {"success": False, "message": err, "data": None}

        nav_reverse = _load_file(cfg["docs_root"], cfg["nav_reverse"])

        # 提取搜索关键词
        keyword = re.sub(
            r'(?:oa|fangapp|查一下|帮我|的|里|中|谁会|跳转到|进来的|入口|在哪)',
            '', query, flags=re.IGNORECASE
        ).strip()

        hits = _search_in_file(nav_reverse, keyword)

        system = (
            f"你是 {cfg['name']} 项目的代码助手，用中文回答。"
            "根据导航索引回答跳转来源问题，格式如下：\n"
            "第一行：找到 X 个入口会跳转到该页面。\n"
            "然后编号列出：\n"
            "  1. 来源页面类名 — 触发条件（用户做了什么操作）\n"
            "  2. 来源页面类名 — 触发条件\n"
            "如果没有找到入口，说明该页面可能是主入口或知识库暂未覆盖。"
        )
        user = f"问题：{query}\n\n导航索引命中：\n{hits}"
        answer = _ask_llm(system, user)

        return {"success": True, "message": answer, "data": {"hits": hits}}

    def execute_query_overview(self, slots: dict) -> dict:
        """查询项目整体概览或列出所有知识库。"""
        query = slots.get("query", "")

        # 如果问的是"有哪些项目"，直接列出
        if any(w in query for w in ["哪些项目", "知识库", "有什么项目"]):
            return {"success": True, "message": list_projects(), "data": None}

        cfg, err = self._resolve_project(query)
        if not cfg:
            return {"success": False, "message": err, "data": None}

        skill_doc = _load_file(cfg["docs_root"], cfg["skill_md"])

        system = (
            f"你是 {cfg['name']} 项目的代码助手。"
            "根据下面的项目概览文档，用中文简洁介绍项目结构、模块划分或回答用户问题。"
        )
        user = f"问题：{query}\n\n项目概览：\n{skill_doc}"
        answer = _ask_llm(system, user, max_tokens=600)

        return {"success": True, "message": answer, "data": None}
