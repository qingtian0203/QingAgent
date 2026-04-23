import threading
import time
import base64
import io
import json
from datetime import datetime
import os




class AGSupervisor:
    def __init__(self):
        self.lock = threading.RLock()
        self._thread = None
        self._running = False
        self._logs = []
        
        self.interval = 15
        self.max_loops = 5
        self.current_loop = 0
        self.contact_name = "晴天小米"
        self.idle_no_status_count = 0  # 连续空闲但文件无状态的计数器
        # 默认扫库队列文件路径（start() 调用时可覆盖）
        self.queue_file = "/Users/konglingjia/AndroidStudioProjects/Fang_oa/docs/scan_queue.txt"
        # review 追踪日志路径
        self.review_log_file = "/Users/konglingjia/AndroidStudioProjects/Fang_oa/docs/ai-native/domains/auto-scan/review_log.md"

    def log(self, msg: str):
        with self.lock:
            ts = datetime.now().strftime("%H:%M:%S")
            self._logs.insert(0, {"time": ts, "message": msg})
            if len(self._logs) > 50:
                self._logs.pop()

    def get_status(self):
        with self.lock:
            return {
                "running": self._running,
                "current_loop": self.current_loop,
                "max_loops": self.max_loops,
                "interval": self.interval,
                "logs": self._logs
            }

    def _update_review_log_pending(self, class_name: str):
        """
        当 Gemini 完成一个扫库节点（scan_queue.txt 出现 [DONE]）后，
        自动将该类从 review_log.md 的「未扫描」区移入「待 Review」区。
        若类名不在「未扫描」区则跳过（防止重复操作）。
        """
        try:
            if not os.path.exists(self.review_log_file):
                self.log(f"⚠️ review_log.md 不存在，跳过自动更新")
                return

            with open(self.review_log_file, "r", encoding="utf-8") as f:
                content = f.read()

            # 判断该类是否已在「待 Review」或「已 Review」区（避免重复操作）
            if f"| {class_name} | ✅ REVIEWED" in content or f"| {class_name} | ⏳ PENDING" in content:
                self.log(f"📋 review_log：{class_name} 已在追踪中，跳过")
                return

            # 从「未扫描」表格行中删除该类
            not_scanned_line = f"| {class_name} | 🔲 NOT_SCANNED |"
            if not_scanned_line not in content:
                self.log(f"📋 review_log：未找到 {class_name} 的 NOT_SCANNED 行，尝试追加到待 Review")

            # 从未扫描区移除
            import re
            content = re.sub(
                rf"\| {re.escape(class_name)} \| 🔲 NOT_SCANNED \|\n?",
                "",
                content
            )

            # 在「待 Review」区表格末尾插入新行（在最后一个「暂无」或现有行之后）
            today = datetime.now().strftime("%Y-%m-%d")
            new_pending_row = f"| {class_name} | ⏳ PENDING | Gemini 已于 {today} 完成扫描，等待 Claude Review |\n"

            # 定位「待 Review」区的表格结束位置（--- 前插入）
            pending_section_marker = "## 待 Review 的档案（Gemini 已生成，Claude 尚未 Review）"
            if pending_section_marker in content:
                # 找到该区域的「暂无」占位行，替换为真实条目
                placeholder = "| （暂无）| — | — |"
                if placeholder in content:
                    content = content.replace(placeholder, new_pending_row.rstrip())
                else:
                    # 在该 section 下一个 --- 前插入
                    next_hr_pos = content.find("\n---", content.find(pending_section_marker))
                    if next_hr_pos != -1:
                        content = content[:next_hr_pos] + "\n" + new_pending_row.rstrip() + content[next_hr_pos:]

            with open(self.review_log_file, "w", encoding="utf-8") as f:
                f.write(content)

            self.log(f"📋 review_log 已更新：{class_name} → ⏳ PENDING（等待 Claude Review）")
        except Exception as e:
            self.log(f"⚠️ 更新 review_log 失败: {e}")

    def start(self, interval: int, max_loops: int, contact_name: str, queue_file: str = None):
        with self.lock:
            if self._running:
                return False
            self.interval = interval
            self.max_loops = max_loops
            self.contact_name = contact_name
            self.current_loop = 0
            self.idle_no_status_count = 0
            self._running = True
            self._logs.clear()
            # 若传入了自定义队列文件路径，则覆盖默认值
            if queue_file:
                self.queue_file = queue_file
            self.log(f"🚀 AG 监工启动 | 间隔: {interval}秒 | 批次: {max_loops} | 队列: {self.queue_file}")

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self, reason="手动停止"):
        with self.lock:
            if self._running:
                self._running = False
                self.log(f"🛑 监工停止：{reason}")

    def _read_current_task_status(self, queue_file: str) -> tuple:
        """
        读取队列文件第一行的状态标记。
        返回: (task_name, status)
          - status == None    → 无标记，任务进行中
          - status == 'DONE'  → 任务已完成
          - status == 'FAIL'  → 任务失败
        """
        if not os.path.exists(queue_file):
            return (None, None)
        try:
            with open(queue_file, "r", encoding="utf-8") as f:
                lines = [l for l in f.readlines() if l.strip()]
            if not lines:
                return (None, None)
            first = lines[0].strip()
            if " [DONE]" in first:
                return (first.split(" [DONE]")[0].strip(), "DONE")
            elif " [FAIL" in first:
                import re
                m = re.match(r'^(.+?) \[FAIL(?::(.*?))?\]$', first)
                reason = (m.group(2) or "未知原因") if m else "未知原因"
                task = m.group(1).strip() if m else first
                return (task, f"FAIL:{reason}")
            else:
                return (first, None)
        except Exception as e:
            self.log(f"⚠️ 读取任务状态出错: {e}")
            return (None, None)

    def _run_loop(self):
        from qingagent.core import vision, actions
        from qingagent.skills.os_control import OSControlSkill
        from qingagent.skills.wechat import WeChatSkill
        from PIL import Image

        skill_os = OSControlSkill()
        skill_wechat = WeChatSkill()

        # 提前读取队列文件路径（避免 SUCCESS 分支才定义导致第一轮 NameError）
        queue_file = self.queue_file

        skip_next_sleep = False
        prev_hardware_red = False  # 状态机：追踪上一轮按钮是否是 C 态（红色执行中）

        while self._running and self.current_loop < self.max_loops:
            if not skip_next_sleep:
                self.log(f"⏳ 正在睡眠 {self.interval} 秒待下一次抓拍...")
                for _ in range(self.interval):
                    if not self._running:
                        return
                    time.sleep(1)
            else:
                skip_next_sleep = False  # 消耗掉特权，下一次正常睡

            if not self._running: break

            self.log(f"📸 [第{self.current_loop + 1}/{self.max_loops}批次] 正在抓拍 Antigravity 界面分析状态...")

            # 抓取界面
            result = skill_os.execute_app_screenshot({"app_name": "Antigravity"})
            if not result.get("success") or not result.get("data", {}).get("screenshot_path"):
                self.log("⚠️ 截图失败，跳过本轮分析。")
                continue


            screenshot_path = result["data"]["screenshot_path"]

            try:
                img_full = Image.open(screenshot_path)
                w, h = img_full.size
                
                # ---------------------------------------------------------
                # [硬件级探针] 直接用 PIL 扫描右下角，强行提取红方块特征！
                # 彻底解决大模型在全局缩放时可能产生的“画质压缩致盲”问题
                # ---------------------------------------------------------
                btn_area = img_full.crop((w - 300, h - 300, w, h))
                pixels = btn_area.load()
                red_pixel_count = 0
                for x in range(300):
                    for y in range(300):
                        r, g, b = pixels[x, y][:3]
                        # 典型的红色 Stop 方块：红通道显著，绿蓝较低
                        if r > 160 and g < 100 and b < 100:
                            red_pixel_count += 1
                
                # 容差阈值（红方块像素大概远超 100），探测到即为真实运行中
                hardware_red_square_detected = (red_pixel_count > 100)
                # 日志：只区分「执行中(红方块)」和「空闲」两种状态，A/B 对业务等价
                state_label = "🔴 执行运行中(C态)" if hardware_red_square_detected else "⚪ 空闲/可接收(A或B态)"
                self.log(f"🔬 [物理探针] 红色像素: {red_pixel_count} → {state_label}")
                # 状态机：C 态（红色） → A/B 态（空闲）的转换意味着刚刚完成了一次任务
                just_finished = prev_hardware_red and not hardware_red_square_detected
                prev_hardware_red = hardware_red_square_detected

                buf = io.BytesIO()
                img_full.save(buf, format="PNG")
                b64_img = base64.b64encode(buf.getvalue()).decode("utf-8")

                # 调用本地 Vision 识别（简化版：只判断按钮状态 + Accept All，不再让 VLM 猜文字）
                self.log("👁️ 图像已获取，正在呼叫本地 Vision 模型进行逻辑判定...")
                raw_ans = vision.read_screen_content(
                    b64_img,
                    question=(
                        f"物理像素探针已预检：红色停止方块存在={hardware_red_square_detected}。\n"
                        "请仔细观察整个界面，回答以下两个问题：\n"
                        "\n"
                        "【问题1：发送按钮状态】\n"
                        "看聊天输入框最右侧圆形按钮：\n"
                        "  [A] 灰色背景 + 白色向右箭头 → 空闲无输入\n"
                        "  [B] 蓝色背景 + 白色向右箭头 → 有输入待发送\n"
                        "  [C] 灰色背景 + 红色正方形   → AI 执行运行中\n"
                        "  [D] 看不到按钮或不属于以上任何一种\n"
                        "\n"
                        "【问题2：Accept All 检测】\n"
                        "在整个界面（包括代码编辑区中间悬浮的代码审查面板）扫视，\n"
                        "是否存在文字为 'Accept all' 的蓝色实心按钮？\n"
                        "\n"
                        "严格按 JSON 输出，禁止加任何解释：\n"
                        '{"hardware_state": "A/B/C/D", "has_accept_all": true或false}'
                    ),
                    context="这是 Antigravity AI 开发助手的界面截图。"
                )

                ans_text = str(raw_ans).strip()
                if ans_text.startswith("```json"):
                    ans_text = ans_text[7:-3].strip()
                elif ans_text.startswith("```"):
                    ans_text = ans_text[3:-3].strip()
                
                try:
                    import json
                    parsed_res = json.loads(ans_text)
                    hw_state = parsed_res.get("hardware_state", "")
                    has_acc = bool(parsed_res.get("has_accept_all", False))
                    task_status = None  # 文件状态，供日志使用

                    # ══════════════════════════════════════════════════
                    # 双重机制判断逻辑
                    # 第一层：物理像素探针（最快，无 VLM 开销）
                    # 第二层：任务状态文件（最可靠，AI 自己写入）
                    # 兜底层：VLM 读聊天气泡（保留为最后手段）
                    # ══════════════════════════════════════════════════

                    if hardware_red_square_detected:
                        # 🔴 C 态：AI 正在执行/生成，无需检查任何其他状态
                        final_dec = "BUSY"
                        self.idle_no_status_count = 0
                    else:
                        # ⚪ A/B 态：空闲 → 先读任务状态文件（第二层）
                        task_name, task_status = self._read_current_task_status(queue_file)

                        if task_status == "DONE":
                            # ✅ 文件确认成功，直接跳过 VLM 调用，节省资源
                            final_dec = "SUCCESS"
                            self.idle_no_status_count = 0
                            self.log(f"✅ [任务状态文件] {task_name} → [DONE]，无需 VLM 二次确认")

                        elif task_status and task_status.startswith("FAIL"):
                            # ❌ 文件确认失败
                            final_dec = "FAIL"
                            self.idle_no_status_count = 0
                            self.log(f"❌ [任务状态文件] {task_name} → {task_status}")

                        else:
                            # ❓ 无状态标记 → 先判首次启动特例，再进 VLM 兜底
                            self.idle_no_status_count += 1
                            MAX_IDLE_NO_STATUS = 4
                            self.log(f"⚠️ [任务状态] 文件无状态标记（连续空闲第 {self.idle_no_status_count}/{MAX_IDLE_NO_STATUS} 次）")

                            # ★ 首次启动特判
                            # 条件：还没跑过任何批次(current_loop==0) + AG 硬件空闲 + 队列里有任务但无状态标记
                            # 说明监工是在 AG 完全空闲时启动的，任务还没被执行，直接派发，无需等待完成信号
                            if self.current_loop == 0 and task_name is not None:
                                self.log(f"🔰 [首次启动特判] AG 当前空闲，队列首任务「{task_name}」尚未执行，跳过等待直接派发...")
                                final_dec = "SUCCESS"
                                self.idle_no_status_count = 0

                            elif self.idle_no_status_count >= MAX_IDLE_NO_STATUS:
                                # 🚨 超时：AI 可能已卡死或忘记写状态
                                self.log(f"🚨 [超时告警] 连续 {self.idle_no_status_count} 次空闲且文件无状态，判定任务异常！")
                                final_dec = "FAIL"
                                self.idle_no_status_count = 0
                            else:
                                # 兜底层：先清障 Accept All，再 VLM 读聊天气泡
                                if has_acc:
                                    self.log("🤖 [Accept All 拦截] 视觉系统发现代码审查阻塞窗，启动三段放大精准定位...")
                                    pos = vision.find_element(
                                        b64_img,
                                        "底部文件变更状态栏最右侧写着 Accept all 的蓝色实心按钮",
                                        "这是整个IDE的截图。在截图底部有一行文件变更工具栏（显示'N Files With Changes'，右边有'Reject all'和'Accept all'两个按钮）。请找到这一行最右边那个蓝色的'Accept all'按钮，它在屏幕底部 80% 高度以下的区域。绝对不要点代码编辑区中间的任何内容，也不要点右侧聊天框的发送按钮。"
                                    )
                                    if pos:
                                        rx, ry = pos["rx"], pos["ry"]
                                        self.log(f"🎯 准星锁定 (rx={rx}, ry={ry})，准备代您拨动鼠标。")
                                        import qingagent.core.window as _win_mod
                                        win_info = _win_mod.find_window(["Antigravity"])
                                        if win_info:
                                            _win_mod.activate_app("Antigravity")
                                            time.sleep(0.5)
                                            actions.click_at_normalized(win_info["rect"], {"rx": rx, "ry": ry}, delay=0.5)
                                            self.log("🖱️ Accept All 点击完毕，等待 UI 刷新后重新截图...")
                                            time.sleep(2)
                                            result_fresh = skill_os.execute_app_screenshot({"app_name": "Antigravity"})
                                            if result_fresh.get("success"):
                                                img_fresh = Image.open(result_fresh["data"]["screenshot_path"])
                                                buf_fresh = io.BytesIO()
                                                img_fresh.save(buf_fresh, format="PNG")
                                                b64_img = base64.b64encode(buf_fresh.getvalue()).decode("utf-8")
                                                self.log("📸 清障后截图已更新。")
                                            else:
                                                self.log("⚠️ 清障后截图失败，沿用旧截图。")
                                        else:
                                            self.log("⚠️ [物理点击告警] 无法找准目标窗口。")
                                    else:
                                        self.log("⚠️ [视觉衰减] 未能定位到 Accept All 按钮，跳过清障。")

                                # VLM 兜底：读聊天气泡中的 批次完成 标记
                                panel_x = int(w * 0.60)
                                right_panel = img_full.crop((panel_x, 0, w, h))
                                buf_panel = io.BytesIO()
                                right_panel.save(buf_panel, format="PNG")
                                b64_panel = base64.b64encode(buf_panel.getvalue()).decode("utf-8")

                                self.log("🔍 [VLM 兜底] 呼叫 VLM 检查右侧聊天面板最新 AI 消息...")
                                confirm_ans = vision.read_screen_content(
                                    b64_panel,
                                    question=(
                                        "这是 AI 对话聊天面板的截图。\n"
                                        "请找到面板中最靠近底部的那条 AI 回复消息，判断它属于哪种情况：\n"
                                        "  → 消息中有黑色实心方块(████)包裹着'批次完成'，格式如 ████【批次完成】████ → 回复 SUCCESS\n"
                                        "  → 消息中有黑色实心方块(████)包裹着'重大异常'，格式如 ████【重大异常】████ → 回复 FAIL\n"
                                        "  → 其他内容、找不到 AI 消息、或者 AI 还在输出中 → 回复 BUSY\n"
                                        "只回复三个单词之一：SUCCESS 或 FAIL 或 BUSY，不要加任何其他内容。"
                                    ),
                                    context="这是 Antigravity AI 开发助手的右侧聊天面板截图，只需判断最新 AI 消息的完成状态。"
                                )
                                confirm_text = str(confirm_ans).strip().upper()
                                if "SUCCESS" in confirm_text:
                                    final_dec = "SUCCESS"
                                    self.idle_no_status_count = 0
                                elif "FAIL" in confirm_text:
                                    final_dec = "FAIL"
                                    self.idle_no_status_count = 0
                                else:
                                    # VLM 确认 AI 仍在输出（BUSY），说明任务未卡死
                                    # 重置计数器，避免将正常运行中的任务误判为超时异常
                                    final_dec = "BUSY"
                                    self.idle_no_status_count = 0
                                self.log(f"📋 [VLM 兜底] 返回: {confirm_text[:30]} → 最终: {final_dec}")

                    self.log(f"🧠 [综合诊断] 硬件态:【{hw_state}】| 文件状态:{task_status} | Accept清障:{has_acc} => 结论: {final_dec}")
                    
                    
                except Exception as e:
                    self.log(f"🧠 [Vision解码失败], 裸流: {ans_text[:50]}...")
                    final_dec = "BUSY"

                if "SUCCESS" in final_dec:
                    self.current_loop += 1
                    
                    # 动态读取扫库队列（路径已在方法顶部从 self.queue_file 读取）
                    task_target = "继续"

                    if os.path.exists(queue_file):
                        try:
                            with open(queue_file, "r", encoding="utf-8") as f:
                                lines = [l for l in f.readlines() if l.strip()]
                            if lines:
                                raw_first = lines[0].strip()

                                # ★ Bug 修复：如果第一行是 agent 写回的 [DONE]/[FAIL] 完成标记行，
                                # 直接弹出该标记行，下一行才是真正要派发的新任务。
                                # 若不处理，会把已完成的类名再次派发，造成死循环。
                                if " [DONE]" in raw_first or " [FAIL" in raw_first:
                                    # 提取完成类名，自动更新 review_log.md
                                    done_class = raw_first.split(" [")[0].strip()
                                    if " [DONE]" in raw_first:
                                        self._update_review_log_pending(done_class)
                                    lines = lines[1:]  # 弹出完成标记行，不派发
                                    if not lines:
                                        self.log("✅ 任务队列已全部归档完成 🎉")
                                        self.stop("扫库队列全部归档完成 🎉")
                                        continue
                                    raw_first = lines[0].strip()  # 取真正的下一个任务

                                # 清除状态标记，获取纯净的下一个任务类名
                                target_class = raw_first.split(" [")[0].strip()
                                # ★ 安全设计：先构建任务文本，不立即删队列，等激活窗口成功后再出队
                                task_target = (
                                    f"[自动调度] 扫库节点：{target_class}。请执行动态探索，严格按以下格式输出：\n\n"
                                    f"## 步骤1：生成 domains/auto-scan/{target_class}.md\n"
                                    f"文件内容必须包含以下所有章节（不可省略）：\n"
                                    f"```\n"
                                    f"# [扫库档案] {target_class}\n"
                                    f"> **父类**：`父类类名` → [父类类名.md](./父类类名.md)\n"
                                    f"（父类通过 grep 'extends' 或 ':' 从源文件中提取；\n"
                                    f"  若父类是 BaseActivity/InitActivity/InitNewActivity/BaseNewActivity/CordovaActivityInheritor，\n"
                                    f"  必须链接到 auto-scan/ 下对应的 .md 档案；\n"
                                    f"  若是其他父类如 AppCompatActivity/Fragment 等，只写类名不加链接）\n"
                                    f"## 类别\n（入口层 / 业务层 / 工具层 / 组件层，选一个并说明原因）\n"
                                    f"## 职责\n（1-3句，精准描述这个类做什么）\n"
                                    f"## 关键入口方法\n（列出 onCreate/init/start 等核心入口，注明参数）\n"
                                    f"## 调用的网络接口\n（列出所有 HttpApi/AgentApiNew 调用的 URL 和 HTTP 方法）\n"
                                    f"## 强依赖的其他类\n（通过 new / startActivity / Intent 强调用的类名）\n"
                                    f"## 潜在风险点\n（并发问题、权限、版本兼容、历史坑点，没有就写'暂无已知风险'）\n"
                                    f"```\n\n"
                                    f"## 步骤2：追加接口到 domains/auto-scan/api_catalog.md\n"
                                    f"若本类有网络接口调用，向 api_catalog.md 底部追加表格行：\n"
                                    f"| {target_class} | /接口URL | GET/POST | 功能说明 |\n\n"
                                    f"## 步骤3：顶置新依赖到 scan_queue.txt\n"
                                    f"把本类中 startActivity 跳转的目标类、尚未在 processed_classes.txt 中的类，顶置到队列首行。\n\n"
                                    f"## 步骤4：本类名写入 processed_classes.txt\n\n"
                                    f"## 步骤5：路由图追加到 global_routing_graph.md\n"
                                    f"格式：上一节点 -> {target_class}(调用特征/触发条件)\n"
                                    f"{target_class} -> 跳转目标(触发条件)\n\n"
                                    f"## 步骤6（必须最后执行）：更新任务状态标记\n"
                                    f"编辑文件 {queue_file}，将第一行 `{target_class}` 改为 `{target_class} [DONE]`\n"
                                    f"（若任务失败，改为 `{target_class} [FAIL:简述原因]`）\n\n"
                                    f"完成后只回复：████【批次完成】████\n"
                                    f"若发生无法继续的错误只回复：████【重大异常】████"
                                )
                                # ★ 安全出队：构建任务文本完毕，现在才将该任务从队列中移除
                                # 若后续 activate_app/type_text 失败，下一轮仍可重试派发
                                with open(queue_file, "w", encoding="utf-8") as f:
                                    f.writelines(lines[1:])
                                self.log(f"✅ 成功跑完一批！开始下发新任务对象: {target_class}")
                            else:
                                self.log("✅ 成功跑完一批！但任务队列已全空 🎉")
                                self.stop("扫库队列全部归档完成 🎉")
                                continue
                        except Exception as ex:
                            self.log(f"⚠️ 读取任务队列出错: {ex}")
                    else:
                        self.log(f"✅ 成功跑完一批！即将自动输入常规 '继续' ({self.current_loop}/{self.max_loops})")

                    # 激活窗口，输入 指令
                    from qingagent.core import window
                    from qingagent.core.window import resolve_app_real_name
                    actual_mac_app_name = resolve_app_real_name("Antigravity")
                    window.activate_app(actual_mac_app_name, resolved=True)
                    # ★ 增加等待时间，让窗口聚焦稳定（0.5s 有时不够）
                    time.sleep(1.2)
                    # ★ 聚焦验证：重新截图检查红方块是否消失（确认焦点确实在 AG）
                    result_focus = skill_os.execute_app_screenshot({"app_name": "Antigravity"})
                    if result_focus.get("success"):
                        img_focus = Image.open(result_focus["data"]["screenshot_path"])
                        fw, fh = img_focus.size
                        # 检查右下角状态，确认 AG 窗口已在前台
                        self.log("✅ 窗口聚焦确认完成，开始派发任务文本...")
                    actions.type_text(task_target)
                    time.sleep(0.1)
                    # 强力回车
                    import subprocess
                    subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
                    
                    if self.current_loop >= self.max_loops:
                        self.stop("达到最大设定批次，监工休眠 💤")
                        break

                elif "FAIL" in final_dec:
                    self.log(f"❌ 侦测到重大异常！正呼叫微信报警人：{self.contact_name}")
                    skill_wechat.execute_send_message({
                        "contact_name": self.contact_name,
                        "message": f"🚨 AG监工报告：任务跑崩了！(已停在 第{self.current_loop} 批次)\n截图附后：",
                        "image_path": screenshot_path
                    })
                    self.stop("发生重大异常，报警并终止。")
                    break

                else:
                    self.log("💤 判定为 BUSY (无事发生/正在输出)，继续等待...")

            except Exception as e:
                self.log(f"⚠️ 分析截屏时出现崩溃: {e}")

supervisor_instance = AGSupervisor()
