"""
project_registry.py — 项目知识库注册表

以后新增项目只需在 PROJECTS 字典里加一条记录，CodeQuerySkill 会自动识别。

结构说明：
  - aliases   : 用户说话时可能用到的项目名（不区分大小写）
  - docs_root : 知识库文件所在的根目录（绝对路径）
  - skill_md  : 项目概览入口文档（相对 docs_root）
  - api_catalog : 接口目录（相对 docs_root）
  - nav_reverse : 反向导航索引（相对 docs_root）
  - page_knowledge_dir : 单页详情 JSON 目录（相对 docs_root）
"""

PROJECTS: dict[str, dict] = {
    "oa": {
        "name": "Fang OA",
        "aliases": ["oa", "方oa", "fang_oa", "oa项目", "oa工程", "oajob", "房oa"],
        "docs_root": "/Users/konglingjia/AndroidStudioProjects/Fang_oa/docs",
        "skill_md": "SKILL.md",
        "api_catalog": "api_catalog.md",
        "nav_reverse": "nav_reverse.md",
        "page_knowledge_dir": "page_knowledge",
    },
    "qingoa": {
        "name": "QingOA FullStack",
        "aliases": ["qingoa", "qing oa", "qingoafullstack", "晴天oa", "qingoa项目", "oa demo"],
        "docs_root": "/Users/konglingjia/AIProject/QingOaFullStack",
        "skill_md": "AGENTS.md",
        "api_catalog": "AGENTS.md",
        "nav_reverse": "AGENTS.md",
        "page_knowledge_dir": ".agents",
    },
    # 以后新增项目在这里追加，格式相同
    # "fangapp": {
    #     "name": "大房 App",
    #     "aliases": ["大房", "fangapp", "房app", "搜房"],
    #     "docs_root": "/Users/konglingjia/AndroidStudioProjects/FangApp/docs",
    #     "skill_md": "SKILL.md",
    #     "api_catalog": "api_catalog.md",
    #     "nav_reverse": "nav_reverse.md",
    #     "page_knowledge_dir": "page_knowledge",
    # },
}


from typing import Optional, Tuple


def find_project(query: str) -> Optional[Tuple[str, dict]]:
    """
    从用户输入中识别目标项目。
    返回 (project_key, project_config) 或 None。

    注意：Planner 提取 slot 时可能丢失项目名（如把 "OA 里查 xxx" 提取成 "xxx"），
    因此当只注册了一个项目时，直接默认返回该项目，无需用户在 query 里显式包含项目名。
    """
    q = query.lower()
    for key, cfg in PROJECTS.items():
        for alias in cfg["aliases"]:
            if alias.lower() in q:
                return key, cfg

    # 未在 query 里找到项目名：若只有一个项目则默认使用它
    active = {k: v for k, v in PROJECTS.items()}
    if len(active) == 1:
        key, cfg = next(iter(active.items()))
        return key, cfg

    return None


def list_projects() -> str:
    """返回所有已注册项目的简介，给 AI 展示。"""
    lines = ["## 已注册的项目知识库\n"]
    for key, cfg in PROJECTS.items():
        aliases = "、".join(cfg["aliases"][:4])
        lines.append(f"- **{cfg['name']}**（关键词：{aliases}）")
    return "\n".join(lines)
