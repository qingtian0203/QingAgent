from __future__ import annotations

"""
AI Planner — 意图识别 + 多步骤任务链执行器

接收用户的自然语言指令，规划为一到多个步骤：
1. 目标应用（微信/浏览器/Antigravity/晴天Util）
2. 要执行的操作（发消息/查消息/打开网页...）
3. 关键参数，支持 ${stepN.key} 占位符引用前一步输出

然后按顺序执行每一步，任意步骤失败则立即停止。
"""
import re
import json
import threading
import requests
from .. import config
from ..skills import SkillRegistry
from ..memory import MemoryManager


class Planner:
    """
    AI 调度器 — 把自然语言变成一条或多条 Skill 调用链。

    工作原理:
    1. 把所有 Skill 的意图描述拼成一个"能力说明书"
    2. 把用户指令 + 能力说明书一起发给 LLM
    3. LLM 返回 JSON 步骤数组：[{step, app, intent, slots, description}, ...]
    4. 按顺序执行每一步，前一步的输出通过 ${stepN.key} 传递到后续步骤
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self._capability_doc = registry.get_full_capability_description()
        # 初始化记忆管理器（加载 memory.json + 维护历史滑动窗口）
        self.memory = MemoryManager()
        # 进度回调，由外层（server）注入，用于向 Web UI 推送步骤进度
        self._progress_callback = None
        # 跨轮次上下文：用 threading.local() 实现线程隔离，防止多用户并发时 step0 数据相互覆盖
        # 每个执行线程独立持有自己上一次任务的输出，不会被其他线程的并发写入污染
        self._thread_local = threading.local()
        # 审核暂停-恢复：confirm_send 拦截时暂存剩余步骤，确认后自动继续
        self._pending_resume: dict | None = None

    def _get_global_context(self) -> dict:
        """获取当前线程的跨轮次上下文（线程安全）"""
        return getattr(self._thread_local, "global_context", {})

    def _set_global_context(self, ctx: dict):
        """设置当前线程的跨轮次上下文（线程安全）"""
        self._thread_local.global_context = ctx

    # ──────────────────────────────────────────────────────────────
    #  核心方法 1：AI 解析任务链
    # ──────────────────────────────────────────────────────────────

    def parse_task_chain(self, user_input: str) -> dict | None:
        """
        用 AI 把用户的自然语言指令分解为任务链（一到多个步骤）。

        返回：
            {
                "steps": [
                    {
                        "step": 1,
                        "app": "OS控制",
                        "intent": "custom_screenshot",
                        "slots": {"target": "整个屏幕"},
                        "description": "截取当前屏幕"
                    },
                    {
                        "step": 2,
                        "app": "微信",
                        "intent": "send_message",
                        "slots": {
                            "contact_name": "丸子",
                            "message": "[粘贴]",
                            "image_path": "${step1.screenshot_path}"
                        },
                        "description": "把截图通过微信发给丸子"
                    }
                ]
            }
            解析失败返回 None
        """
        memory_context = self.memory.build_context_prompt()

        prompt = f"""你是一个任务规划器。把用户的自然语言指令分解为一到多个操作步骤。

{memory_context}


{self._capability_doc}

重要规则：
- 如果只有一个操作，steps 数组只有 1 个元素
- 多个步骤必须按执行顺序排列
- 步骤之间有数据依赖时，用 ${{stepN.key}} 引用前面步骤的 data 输出
  - 截图步骤的输出字段：screenshot_path（图片文件路径）
  - 其他步骤的通用输出字段：value
- 用户指令中明确提到了某个应用名或别名时，必须使用该应用，不要默认去微信
  - "给AG发消息" → app=Antigravity，不是微信
  - "给AG/Antigravity/编辑器/Cursor发消息" 是 Antigravity
  - "给xx发微信" 才是微信
- message/prompt 参数是最终要发给对方的内容，不要包含"问一下""告诉他""说一下"等指令描述词
- 人称转换：用户说"问她干嘛呢"，实际发给对方应该是"你干嘛呢"
- 示例1："给丸子发条微信说下午开会" → 1步，微信 send_message
- 示例2："截图然后微信发给丸子" → 2步，先截图(step1)，再微信发送(image_path="${{step1.screenshot_path}}")
- 示例3："截下微信的图，把这个截图发给晴天小米" → 2步：先截图System.custom_screenshot(target=微信)，再微信发图(image_path="${{step1.screenshot_path}}", contact_name=晴天小米)
- 示例4："截个图然后通过微信告诉她" → 2步：先截图，再 send_message(image_path="${{step1.screenshot_path}}")
- 【关键判断】：只要指令同时含截图 + 发送两个动作，必须拆分为 2 步；不能把两步合并成 1 步
- 【Web交互拦截】：如果用户说"发给我"、"让我看看"、"发到这个聊天"、"在这看"、"发给QingAI"，表示只需在当前 Web 界面上查看。**绝对不要去调用微信发送**！只需执行那个获取动作的 1 步即可（例如 1步：用 System 截图），获取完成后会自动显示展示在这里。
- 示例5："截图微信发给我" / "截图微信让我看看" → 1步，app=System，intent=app_screenshot，slots={{"app_name": "微信"}} （不需要拆分两步！）
- 示例6："打开微信" → 1步，app=System，intent=open_app，slots={{"app_name": "微信"}}
- 示例7："帮我启动Safari" → 1步，app=System，intent=open_app，slots={{"app_name": "Safari"}}
- 示例8："切换到日历" → 1步，app=System，intent=open_app，slots={{"app_name": "日历"}}
- 【打开应用规则】：用户说"打开xx""启动xx""切换到xx""进入xx"时，必须用 System.open_app，xx 直接作为 app_name 填入
- 【找文件规则】：如果用户说"发送："或"这是一个绝对路径"并给出了带 '/' 的物理路径，注意！这说明上一步模糊查找结束了，请你**必须回头看上一文的初衷（比如想把文件发给谁）！** 在本次规划中，你**不仅**要安排 `System.prepare_file(filename="该绝对路径")` 步骤，还**必须**紧随其后立刻增加一个步骤 `WeChat.send_message(contact_name="历史中提到的人", message="[粘贴]")` 将文件发出去！绝不能只执行查找而忘了发送！
- 【审核阻断后继续规则】：如果用户只说了一句短促的 "确认已无误，微信发送"，这说明前面动作已经就绪，绝对不容许重新切应用选人，必须直接调用 `WeChat.confirm_send_action`！
用户指令："{user_input}"

请返回 JSON 格式（不要包含其他任何内容）：
{{
    "steps": [
        {{
            "step": 1,
            "app": "应用名称",
            "intent": "意图名称",
            "slots": {{参数名: 参数值}},
            "description": "步骤简短描述（10字以内）"
        }}
    ]
}}

如果完全无法理解用户意图，返回：
{{"steps": [], "error": "无法理解的指令"}}
"""

        payload = {
            "model": config.PLANNER_MODEL,
            "prompt": prompt,
            "stream": False,
        }

        mode = getattr(config, "API_MODE", "ollama").lower()
        api_key = getattr(config, "API_KEY", "")
        url = config.PLANNER_URL

        try:
            if mode == "openai":
                if not url.endswith("/chat/completions"):
                    url = url.rstrip("/") + "/chat/completions"
                headers = {"Content-Type": "application/json"}
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"
                oai_payload = {
                    "model": config.PLANNER_MODEL,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "max_tokens": 600,
                }
                res = requests.post(url, json=oai_payload, headers=headers, timeout=30)
                res.raise_for_status()
                text = res.json()["choices"][0]["message"]["content"].strip()
            else:
                res = requests.post(url, json=payload, timeout=30)
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

            steps = result.get("steps", [])
            if not steps or result.get("error"):
                print(f"⚠️ Planner 无法理解指令：{user_input}，错误：{result.get('error', '步骤为空')}")
                return None

            return result

        except Exception as e:
            # 🚨 FailSafeException 必须穿透，不能被 Planner 吞掉
            import pyautogui
            if isinstance(e, pyautogui.FailSafeException):
                print("🚨 [FAILSAFE 触发] Planner 层 — 物理急停信号穿透")
                raise
            print(f"❌ Planner 解析失败：{e}")
            return None

    # ──────────────────────────────────────────────────────────────
    #  核心方法 2：占位符替换（步骤间上下文传递）
    # ──────────────────────────────────────────────────────────────

    def _resolve_placeholders(self, slots: dict, context: dict) -> dict:
        """
        替换 slots 中所有 ${stepN.key} 占位符为前面步骤的实际输出值。

        示例：
            slots = {"image_path": "${step1.screenshot_path}"}
            context = {"step1": {"screenshot_path": "/tmp/abc.png"}}
            → {"image_path": "/tmp/abc.png"}

        参数:
            slots: 当前步骤的参数字典
            context: 已完成步骤的输出集合 {"step1": {...}, "step2": {...}}

        返回:
            替换后的 slots 字典
        """
        resolved = {}
        pattern = re.compile(r'\$\{(step\d+)\.(\w+)\}')

        for key, value in slots.items():
            if isinstance(value, str):
                def replacer(m):
                    step_key = m.group(1)   # e.g. "step1"
                    field = m.group(2)       # e.g. "screenshot_path"
                    step_data = context.get(step_key, {})
                    if isinstance(step_data, dict):
                        actual = step_data.get(field)
                        if actual is not None:
                            print(f"  🔗 占位符替换：${{{step_key}.{field}}} → {actual}")
                            return str(actual)
                    print(f"  ⚠️ 占位符 ${{{step_key}.{field}}} 找不到对应值，保留原文")
                    return m.group(0)
                resolved[key] = pattern.sub(replacer, value)
            else:
                resolved[key] = value

        return resolved

    # ──────────────────────────────────────────────────────────────
    #  核心方法 3：任务链执行器
    # ──────────────────────────────────────────────────────────────

    def execute(self, user_input: str, cancel_check=None) -> dict:
        """
        完整执行流程：解析任务链 → 逐步执行 → 上下文传递。

        参数:
            user_input: 用户自然语言指令
            cancel_check: 可选的回调函数，返回 True 表示用户已取消

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

        # ── 步骤 1：AI 解析任务链 ──────────────────────────────────
        print("\n🧠 正在规划任务...")
        t0 = _time.time()
        task_chain = self.parse_task_chain(user_input)
        print(f"⏱️ [Planner 规划] 耗时：{_time.time() - t0:.1f}s")

        if not task_chain:
            return {
                "success": False,
                "message": "抱歉，我没理解你的指令。试试说得更具体？",
                "data": None,
            }

        steps = task_chain["steps"]
        total_steps = len(steps)

        # 打印任务计划
        print(f"\n📋 计划执行 {total_steps} 个步骤：")
        for s in steps:
            print(f"  步骤 {s['step']}: [{s['app']}] {s['intent']} — {s.get('description', '')}")
            if s.get("slots"):
                print(f"    参数：{s['slots']}")

        # ── 步骤 2：逐步执行，并做上下文传递 ──────────────────────
        # 继承本线程上一次执行的最终结果为 step0，支持“发刚才的图”等跨轮次指令
        # _get_global_context() 线程安全，不会读到其他用户的执行结果
        prev_ctx = self._get_global_context()
        context = {"step0": prev_ctx} if prev_ctx else {}
        last_result = None

        # 用 while 循环支持 confirm_send 审核通过后动态追加后续步骤
        step_index = 0
        while step_index < len(steps):
            step = steps[step_index]
            step_index += 1
            step_num = step_index            # 1-based 序号
            total_steps = len(steps)        # 动态更新（resume 后步骤数会增加）
            app_name = step.get("app", "")
            intent_name = step.get("intent", "")
            slots = step.get("slots", {})
            description = step.get("description", f"{app_name}.{intent_name}")

            print(f"\n{'─'*40}")
            print(f"🔢 步骤 {step_num}/{total_steps}：{description}")

            # 通知外层（server）当前进度，用于推送给 Web UI
            if self._progress_callback:
                try:
                    self._progress_callback(step_num, total_steps, description)
                except Exception:
                    pass

            # 占位符替换（把前面步骤的输出注入当前步骤的参数）
            if context:
                slots = self._resolve_placeholders(slots, context)
                print(f"  解析后参数：{slots}")

            # 中断检查（执行前）
            if cancel_check and cancel_check():
                msg = f"步骤 {step_num}/{total_steps} 前被用户取消"
                print(f"🛑 {msg}")
                self.memory.append_history(user_input, f"🛑 {msg}")
                return {"success": False, "message": msg, "data": None}

            # 查找对应 Skill
            skill = self.registry.get_skill_by_name(app_name)
            if not skill:
                result_tuple = self.registry.find_skill_for_intent(intent_name)
                if result_tuple:
                    skill, intent_name = result_tuple
                else:
                    msg = f"步骤 {step_num}/{total_steps} 失败：找不到应用「{app_name}」的操作能力"
                    self.memory.append_history(user_input, f"❌ {msg}")
                    print(f"\n⏱️ ===== 总耗时：{_time.time() - total_start:.1f}s =====")
                    return {"success": False, "message": msg, "data": None}

            # 执行前最后一次中断检查（高危操作保护）
            if cancel_check and cancel_check():
                msg = f"步骤 {step_num}/{total_steps} 已在「{skill.app_name}」执行前被拦截"
                print(f"🛑 [拦截] {msg}")
                self.memory.append_history(user_input, f"🛑 {msg}")
                return {"success": False, "message": msg, "data": None}

            # ── 执行 ──
            print(f"🚀 执行：{skill.app_name}.{intent_name}")
            t0 = _time.time()
            try:
                result = skill.execute(intent_name, slots, cancel_check=cancel_check)
            except Exception as e:
                import pyautogui
                if isinstance(e, pyautogui.FailSafeException):
                    print("🚨 [FAILSAFE 触发] 执行层 — 物理急停")
                    raise
                result = {"success": False, "message": f"步骤 {step_num} 执行异常：{e}", "data": None}

            print(f"⏱️ [步骤 {step_num} 耗时] {_time.time() - t0:.1f}s")

            # 提前计算，供 status_icon 和失败处理共用
            _is_confirm = (
                isinstance(result.get("data"), dict)
                and result["data"].get("type") == "confirm_send"
            )
            status_icon = "✅" if result["success"] else ("⏸️" if _is_confirm else "❌")
            print(f"{status_icon} 步骤 {step_num} 结果：{result['message']}")
            if result.get("data"):
                print(f"  📦 步骤输出：{result['data']}")

            # 把步骤输出存入上下文供后续引用
            step_data = result.get("data")
            if isinstance(step_data, dict):
                context[f"step{step_num}"] = step_data
            elif step_data is not None:
                context[f"step{step_num}"] = {"value": step_data}
            else:
                context[f"step{step_num}"] = {}

            last_result = result
            # 刷新本线程的跨轮次上下文（线程安全，不影响其他并发任务）
            self._set_global_context(context[f"step{step_num}"])

            # ── 失败处理：区分「审核暂停」和「真正失败」──
            if not result["success"]:
                if _is_confirm:
                    # 审核拦截不是真正失败，暂存后续步骤，等用户确认后恢复
                    remaining = steps[step_index:]
                    if remaining:
                        self._pending_resume = {
                            "remaining_steps": remaining,
                            "context": dict(context),
                            "original_user_input": user_input,
                        }
                        print(f"⏸️  [审核暂停] 已暂存后续 {len(remaining)} 个步骤，确认后自动继续")
                    return {"success": False, "message": result["message"], "data": result["data"]}

                if total_steps == 1:
                    msg = result["message"]
                else:
                    msg = f"[步骤 {step_num}/{total_steps}：{description}] {result['message']}"
                self.memory.append_history(user_input, f"❌ {msg}")
                print(f"\n⏱️ ===== 总耗时：{_time.time() - total_start:.1f}s =====")
                return {"success": False, "message": msg, "data": result.get("data")}

            # ── confirm_send_action 成功 → 自动恢复暂存的后续步骤 ──
            if intent_name == "confirm_send_action" and self._pending_resume is not None:
                resume_data = self._pending_resume
                self._pending_resume = None
                for k, v in resume_data["context"].items():
                    if k not in context:
                        context[k] = v
                steps = steps[:step_index] + resume_data["remaining_steps"]
                total_steps = len(steps)
                print(f"▶️  [自动恢复] 继续执行剩余 {len(resume_data['remaining_steps'])} 个步骤")
                for rs in resume_data["remaining_steps"]:
                    print(f"   → [{rs.get('app')}] {rs.get('intent')} — {rs.get('description', '')}")

        # ── 全部步骤完成 ──────────────────────────────────────────
        if total_steps == 1:
            final_msg = last_result["message"]
        else:
            final_msg = f"✅ 全部 {total_steps} 步已完成"

        self.memory.append_history(user_input, f"✅ {final_msg}")
        print(f"\n⏱️ ===== 总耗时：{_time.time() - total_start:.1f}s =====")
        return {
            "success": True,
            "message": final_msg,
            "data": last_result.get("data") if last_result else None,
        }
