from __future__ import annotations

"""
AI Planner — 意图识别 + 槽位提取

接收用户的自然语言指令，识别出：
1. 目标应用（微信/浏览器/Antigravity/晴天Util）
2. 要执行的操作（发消息/查消息/打开网页...）
3. 关键参数（联系人、消息内容、URL...）

然后交给对应的 Skill 执行。
"""
import json
import requests
from .. import config
from ..skills import SkillRegistry
from ..memory import MemoryManager


class Planner:
    """
    AI 调度器 — 把自然语言变成 Skill 调用。

    工作原理:
    1. 把所有 Skill 的意图描述拼成一个"能力说明书"
    2. 把用户指令 + 能力说明书一起发给 LLM
    3. LLM 返回 JSON：{app, intent, slots}
    4. 根据返回调用对应 Skill 的 execute()
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._capability_doc = registry.get_full_capability_description()
        # 初始化记忆管理器（加载 memory.json + 维护历史滑动窗口）
        self.memory = MemoryManager()

    def parse_intent(self, user_input: str) -> dict | None:
        """
        用 AI 解析用户的自然语言指令。

        参数:
            user_input: 用户输入的自然语言，如 "给晴天发条微信说下午开会"

        返回:
            {
                "app": "微信",
                "intent": "send_message",
                "slots": {"contact_name": "晴天", "message": "下午开会"},
                "confidence": "high"
            }
            解析失败返回 None
        """
        # 构建记忆上下文（用户信息 + 联系人 + 最近历史）
        memory_context = self.memory.build_context_prompt()

        prompt = f"""你是一个指令解析器。根据用户的自然语言指令，识别出要操作的应用、具体操作和参数。

{memory_context}


{self._capability_doc}

重要规则：
- 用户指令中明确提到了某个应用名或别名时，必须使用该应用，不要默认去微信
- "给AG发消息说xxx" → app=Antigravity，不是微信！AG是Antigravity的简写
- "给xx发微信" 才是微信，"给AG/Antigravity/编辑器/Cursor发消息" 是Antigravity
- message/prompt 参数是最终要发给对方的内容，不要包含"问一下""告诉他""说一下"等指令描述词
- 注意人称转换：用户说"问她干嘛呢"，实际发给对方应该是"你干嘛呢"
- 示例："给丸子发微信问一下她干嘛呢" → app=微信, contact_name="丸子", message="你干嘛呢"
- 示例："给AG发消息说 测试一下" → app=Antigravity, intent=send_prompt, prompt="测试一下"

用户指令："{user_input}"

请返回 JSON 格式（不要返回其他任何内容）：
{{
    "app": "应用名称",
    "intent": "意图名称",
    "slots": {{参数名: 参数值}},
    "confidence": "high/medium/low"
}}

如果无法识别用户意图，返回：
{{"app": null, "intent": null, "slots": {{}}, "confidence": "none"}}
"""

        payload = {
            "model": config.PLANNER_MODEL,
            "prompt": prompt,
            "stream": False,
        }

        try:
            res = requests.post(
                config.PLANNER_URL, json=payload, timeout=30
            )
            res.raise_for_status()
            text = res.json().get("response", "")

            # 提取 JSON
            clean = text.replace("```json", "").replace("```", "").strip()
            start = clean.find("{")
            end = clean.rfind("}") + 1
            if start == -1 or end == 0:
                print(f"⚠️ Planner 返回无法解析：{text[:200]}")
                return None

            result = json.loads(clean[start:end])

            if result.get("confidence") == "none" or result.get("app") is None:
                print(f"⚠️ Planner 无法理解指令：{user_input}")
                return None

            return result

        except Exception as e:
            print(f"❌ Planner 解析失败：{e}")
            return None

    def execute(self, user_input: str, cancel_check=None) -> dict:
        """
        完整执行流程：解析 → 查找 Skill → 执行。

        参数:
            user_input: 用户自然语言指令
            cancel_check: 可选的回调函数，返回 boolean 代表是否在执行中途被用户主动取消

        返回:
            {"success": bool, "message": str, "data": any}
        """
        import time as _time
        total_start = _time.time()

        print(f"\n{'='*50}")
        print(f"📥 收到指令：{user_input}")
        print(f"{'='*50}")

        if cancel_check and cancel_check():
            return {"success": False, "message": "指令已取消", "data": None}

        # 步骤 1：AI 解析意图
        print("\n🧠 正在理解指令...")
        t0 = _time.time()
        parsed = self.parse_intent(user_input)
        print(f"⏱️ [Planner 意图解析] 耗时：{_time.time() - t0:.1f}s")

        if not parsed:
            return {
                "success": False,
                "message": "抱歉，我没理解你的指令。试试说得更具体？",
                "data": None,
            }

        app_name = parsed["app"]
        intent_name = parsed["intent"]
        slots = parsed.get("slots", {})
        confidence = parsed.get("confidence", "unknown")

        print(f"📋 解析结果：应用={app_name}, 操作={intent_name}, "
              f"参数={slots}, 置信度={confidence}")

        # 置信度太低时请求确认
        if confidence == "low":
            print(f"⚠️ 置信度较低，建议确认：你是想用 {app_name} 执行 {intent_name} 吗？")

        # 步骤 2：查找对应 Skill
        skill = self.registry.get_skill_by_name(app_name)
        if not skill:
            result = self.registry.find_skill_for_intent(intent_name)
            if result:
                skill, intent_name = result
            else:
                return {
                    "success": False,
                    "message": f"找不到应用 {app_name} 的操作能力",
                    "data": None,
                }

        # 在高危的系统自动化操作前，做最后一次强校验
        if cancel_check and cancel_check():
            print(f"🛑 [中断拦截] 拦截了即将在 {skill.app_name} 执行的 {intent_name} 操作")
            return {
                "success": False,
                "message": "已成功拦截阻断该操作！",
                "data": None,
            }

        # 步骤 3：执行
        print(f"\n🚀 开始执行：{skill.app_name}.{intent_name}...")
        t0 = _time.time()
        result = skill.execute(intent_name, slots)
        print(f"⏱️ [Skill 执行总计] 耗时：{_time.time() - t0:.1f}s")

        # 打印结果
        status = "✅" if result["success"] else "❌"
        print(f"\n{status} {result['message']}")
        if result.get("data"):
            print(f"📄 返回数据：\n{result['data']}")

        # 记录到历史滑动窗口
        self.memory.append_history(user_input, f"{status} {result['message']}")

        print(f"\n⏱️ ===== 总耗时：{_time.time() - total_start:.1f}s =====")
        return result
