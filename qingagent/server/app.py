from __future__ import annotations

"""
Web 服务 — 提供 HTTP API 和移动端友好的 Web 聊天界面

手机和电脑在同一局域网下即可访问，支持自然语言远程操控桌面。
"""
import json
import socket
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse

from .. import config
from ..skills import SkillRegistry
from ..planner.planner import Planner


# 全局实例
_planner: Planner = None

# ── 任务队列（串行执行，防止多设备同时操控鼠标造成物理冲突）────────────────
# 所有任务放入 _task_queue，由唯一的 worker 线程逐一取出执行，确保同一时刻
# 最多只有 1 个任务在控制鼠标/键盘，彻底杜绝物理操作竞态
import queue as _queue_module
_tasks: dict = {}  # task_id -> {"status": "queued"/"running"/"done", "result": {...}}
_task_counter = 0
_task_lock = threading.Lock()
_task_queue: _queue_module.Queue = _queue_module.Queue()  # 串行消费队列


def _get_local_ip() -> str:
    """获取当前 Mac 的 WiFi IP 地址"""
    try:
        import netifaces
        addrs = netifaces.ifaddresses("en0")
        inet = addrs.get(netifaces.AF_INET)
        if inet:
            for link in inet:
                ip = link.get("addr")
                if ip and not ip.startswith("127."):
                    return ip
    except Exception:
        pass
    # fallback
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class QingAgentHandler(SimpleHTTPRequestHandler):
    """HTTP 请求处理器"""

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/index.html":
            self._serve_ui()
        elif parsed.path == "/benchmark":
            self._serve_benchmark()
        elif parsed.path == "/api/skills":
            self._api_skills()
        elif parsed.path == "/api/health":
            self._json_response({"status": "ok", "version": "0.1.0"})
        elif parsed.path.startswith("/api/task/"):
            task_id = parsed.path.split("/")[-1]
            self._api_task_status(task_id)
        elif parsed.path == "/api/image":
            # 提供图片预览接口 (限 /tmp/ 目录下的 png 图片)
            from urllib.parse import parse_qs
            import os
            query = parse_qs(parsed.query)
            image_path = query.get("path", [""])[0]
            if image_path and "/tmp/" in image_path and image_path.endswith(".png"):
                if os.path.exists(image_path):
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    with open(image_path, "rb") as f:
                        self.wfile.write(f.read())
                    return
                else:
                    self.send_error(404, "Image not found")
            else:
                self.send_error(400, "Invalid image path")
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/execute":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")

            try:
                data = json.loads(body)
                command = data.get("command", "")

                if not command.strip():
                    self._json_response({"success": False, "message": "指令不能为空"})
                    return

                # 放入串行队列：立即返回 task_id，worker 线程顺序执行
                global _task_counter
                with _task_lock:
                    _task_counter += 1
                    task_id = str(_task_counter)
                    # 计算当前排队位置（队列长度 = 前方等待的任务数）
                    queue_pos = _task_queue.qsize()
                    _tasks[task_id] = {
                        "status": "queued",
                        "result": None,
                        "command": command,
                        "mode": data.get("mode", "safe"),
                        "queue_pos": queue_pos,  # 前方有多少个任务在等
                    }

                _task_queue.put(task_id)
                self._json_response({"task_id": task_id, "status": "queued", "queue_pos": queue_pos})

            except json.JSONDecodeError:
                self._json_response({"success": False, "message": "请求格式错误"})
        elif parsed.path.startswith("/api/cancel/"):
            task_id = parsed.path.split("/")[-1]
            if task_id == "all":
                # 一次性取消所有正在运行的任务
                cancelled_count = 0
                for tid in list(_tasks.keys()):
                    if _tasks[tid].get("status") == "running":
                        _tasks[tid]["status"] = "cancelled"
                        cancelled_count += 1
                self._json_response({"success": True, "cancelled": cancelled_count})
            elif task_id in _tasks:
                _tasks[task_id]["status"] = "cancelled"
                self._json_response({"success": True})
            else:
                self._json_response({"success": False, "message": "任务不存在"})
        elif parsed.path == "/api/emergency_stop":
            # 🚨 最高级别紧急终止：取消所有任务 + 触发 FAILSAFE
            for tid in list(_tasks.keys()):
                if _tasks[tid].get("status") == "running":
                    _tasks[tid]["status"] = "cancelled"

            def _do_emergency_stop():
                import time as _t
                _t.sleep(0.1)  # 等取消信号传递到执行线程
                try:
                    from ..core.actions import emergency_stop
                    emergency_stop()
                except Exception as e:
                    print(f"⚠️ 紧急终止执行失败：{e}")

            threading.Thread(target=_do_emergency_stop, daemon=True).start()
            self._json_response({"success": True, "message": "🚨 紧急终止指令已发出"})
        elif parsed.path == "/api/benchmark/intent":
            self._benchmark_intent()
        elif parsed.path == "/api/benchmark/vision":
            self._benchmark_vision()
        elif parsed.path == "/api/benchmark/speed":
            self._benchmark_speed()
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    @staticmethod
    def _run_task(task_id: str, command: str):
        """执行单个任务（由 worker 线程调用，同一时刻只会有 1 个任务在这里跑）"""
        # 标记为 running，清空排队位置信息
        _tasks[task_id]["status"] = "running"
        _tasks[task_id].pop("queue_pos", None)
        
        # 将本次任务的模式打入全局环境变量供底层技能感知
        import os
        os.environ["QINGAGENT_MODE"] = _tasks[task_id].get("mode", "safe")

        try:
            cancel_check = lambda: _tasks.get(task_id, {}).get("status") == "cancelled"

            # 进度回调：执行多步骤任务链时，把每步进度写入任务状态供前端轮询
            def progress_callback(current_step: int, total_steps: int, description: str):
                if task_id in _tasks and _tasks[task_id].get("status") == "running":
                    _tasks[task_id]["progress"] = {
                        "current_step": current_step,
                        "total_steps": total_steps,
                        "description": description,
                    }

            _planner._progress_callback = progress_callback
            result = _planner.execute(command, cancel_check=cancel_check)
            # 如果在执行完毕后发现用户中途点了取消，就不要强行标记为 done（防止诈尸）
            if not cancel_check():
                _tasks[task_id] = {"status": "done", "result": result}
        except Exception as e:
            import pyautogui
            if isinstance(e, pyautogui.FailSafeException):
                # 物理 FAILSAFE 触发 → 把任务标记为 cancelled，UI 显示急停信息
                _tasks[task_id] = {
                    "status": "cancelled",
                    "result": {
                        "success": False,
                        "message": "🚨 任务被物理急停（鼠标到达屏幕左上角），已安全中断",
                        "data": None,
                    },
                }
                print("🚨 [FAILSAFE] 任务线程已终止，UI 状态已同步为 cancelled")
            elif _tasks.get(task_id, {}).get("status") != "cancelled":
                _tasks[task_id] = {
                    "status": "done",
                    "result": {"success": False, "message": f"执行出错：{e}", "data": None},
                }


    def _api_task_status(self, task_id: str):
        """查询任务执行状态"""
        task = _tasks.get(task_id)
        if not task:
            self._json_response({"error": "任务不存在"}, 404)
            return

        if task["status"] == "queued":
            # 正在排队等待：返回当前在队列中的实时位置（队列里比我早的任务数）
            ahead = sum(
                1 for t in _tasks.values()
                if t.get("status") in ("queued", "running") and t is not task
            )
            self._json_response({"status": "queued", "task_id": task_id, "ahead": ahead})
        elif task["status"] == "running":
            response = {"status": "running", "task_id": task_id}
            # 如果有步骤进度，一起返回给前端
            if task.get("progress"):
                response["progress"] = task["progress"]
            self._json_response(response)
        elif task["status"] == "cancelled":
            self._json_response({"status": "cancelled", "task_id": task_id})
            _tasks.pop(task_id, None)
        else:
            self._json_response({
                "status": "done",
                "task_id": task_id,
                "result": task["result"],
            })
            # 清理已完成的任务
            _tasks.pop(task_id, None)

    def _json_response(self, data: dict, status: int = 200):
        """返回 JSON 响应"""
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _api_skills(self):
        """返回所有已注册 Skill 的描述"""
        skills_info = {}
        for name, skill in _planner.registry.get_all_skills().items():
            intents = {}
            for intent_name, intent in skill.get_intents().items():
                intents[intent_name] = {
                    "description": intent.description,
                    "required_slots": intent.required_slots,
                    "optional_slots": intent.optional_slots,
                    "examples": intent.examples,
                }
            skills_info[name] = {
                "app_name": skill.app_name,
                "intents": intents,
            }
        self._json_response(skills_info)

    def _serve_benchmark(self):
        """返回模型测试台页面"""
        html = _get_benchmark_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _read_post_body(self) -> dict:
        """读取并解析 POST JSON body"""
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode("utf-8")
        return json.loads(body) if body else {}

    # ─── 模型注册表 ───────────────────────────────────────────────────────
    @staticmethod
    def _bench_models():
        """返回所有可用的基准测试模型配置"""
        from .. import config as _cfg
        return {
            "omlx_26b": {
                "id": "omlx_26b", "label": "oMLX · Gemma 4 26B",
                "color": "#60a5fa", "engine": "oMLX",
                "mode": "openai", "url": "http://localhost:8000/v1",
                "model": "gemma-4-26b-a4b-it-4bit", "key": _cfg.API_KEY,
            },
            "omlx_31b": {
                "id": "omlx_31b", "label": "oMLX · Gemma 4 31B",
                "color": "#818cf8", "engine": "oMLX",
                "mode": "openai", "url": "http://localhost:8000/v1",
                "model": "gemma-4-31b-it-4bit", "key": _cfg.API_KEY,
            },
            "ollama_26b": {
                "id": "ollama_26b", "label": "Ollama · Gemma 4 26B",
                "color": "#facc15", "engine": "Ollama",
                "mode": "ollama", "url": "http://localhost:11434/api/generate",
                "model": "gemma4:26b", "key": "",
            },
            "ollama_31b": {
                "id": "ollama_31b", "label": "Ollama · Gemma 4 31B",
                "color": "#fb923c", "engine": "Ollama",
                "mode": "ollama", "url": "http://localhost:11434/api/generate",
                "model": "gemma4:31b", "key": "",
            },
        }

    @staticmethod
    def _bench_call(mc: dict, prompt: str, image_b64: str = None, max_tokens: int = 512):
        """统一模型调用，返回 (text, error, prompt_tokens, completion_tokens)"""
        import requests as _req
        try:
            if mc["mode"] == "openai":
                url = mc["url"].rstrip("/") + "/chat/completions"
                hdr = {"Content-Type": "application/json"}
                if mc.get("key"):
                    hdr["Authorization"] = f"Bearer {mc['key']}"
                content = [{"type": "text", "text": prompt}]
                if image_b64:
                    content.append({"type": "image_url",
                                    "image_url": {"url": f"data:image/png;base64,{image_b64}"}})
                resp = _req.post(url, json={
                    "model": mc["model"],
                    "messages": [{"role": "user", "content": content}],
                    "stream": False, "max_tokens": max_tokens,
                }, headers=hdr, timeout=120)
                
                rj = resp.json() 
                if not resp.ok:
                    err_msg = rj.get("error", {}).get("message", str(rj)) if isinstance(rj.get("error"), dict) else str(rj.get("error", rj))
                    return None, f"HTTP {resp.status_code}: {err_msg}", 0, 0
                    
                text = rj["choices"][0]["message"]["content"].strip()
                usage = rj.get("usage", {})
                return text, None, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
            else:  # ollama
                body = {"model": mc["model"], "prompt": prompt, "stream": False}
                if image_b64:
                    body["images"] = [image_b64]
                resp = _req.post(mc["url"], json=body, timeout=120)
                
                rj = resp.json()
                if not resp.ok:
                    return None, f"HTTP {resp.status_code}: {rj.get('error', str(rj))}", 0, 0
                    
                text = rj.get("response", "").strip()
                return text, None, rj.get("prompt_eval_count", 0), rj.get("eval_count", 0)
        except Exception as e:
            return None, str(e), 0, 0

    def _benchmark_intent(self):
        """意图解析测试：单模型调用，支持预热"""
        import time
        try:
            data = self._read_post_body()
            text = data.get("text", "").strip()
            model_id = data.get("model_id", "omlx_26b")
            warmup = data.get("warmup", False)

            if not text:
                self._json_response({"error": "text 不能为空"}); return

            models = self._bench_models()
            mc = models.get(model_id)
            if not mc:
                self._json_response({"error": f"未知模型: {model_id}"}); return

            capability_doc = _planner.registry.get_full_capability_description()
            prompt = f"""你是一个应用控制层，从用户指令中识别目标应用和操作意图。

已注册的技能：
{capability_doc}

用户说：「{text}」

请仅返回一个严格的 JSON（不要包含任何多余文字）：
{{
  "steps": [
    {{
      "app": "应用名",
      "intent": "意图名",
      "slots": {{}},
      "description": "简短描述"
    }}
  ]
}}"""

            # 预热
            warmup_elapsed = None
            if warmup:
                t0 = time.time()
                self._bench_call(mc, "好", max_tokens=8)
                warmup_elapsed = round(time.time() - t0, 2)

            # 正式测试
            t0 = time.time()
            raw_text, error, pt, ct = self._bench_call(mc, prompt, max_tokens=512)
            elapsed = round(time.time() - t0, 2)

            # 解析 JSON
            parsed_ok, parsed_data = False, None
            if raw_text:
                try:
                    t = raw_text
                    if t.startswith("```json"): t = t[7:]
                    elif t.startswith("```"): t = t[3:]
                    if t.endswith("```"): t = t[:-3]
                    parsed_data = json.loads(t.strip())
                    parsed_ok = True
                except Exception:
                    pass

            self._json_response({
                "success": True,
                "model_id": model_id, "label": mc["label"], "color": mc["color"],
                "elapsed": elapsed, "warmup_elapsed": warmup_elapsed,
                "raw": raw_text, "parsed_ok": parsed_ok, "parsed": parsed_data,
                "error": error,
            })
        except Exception as e:
            self._json_response({"success": False, "error": str(e)})

    def _benchmark_vision(self):
        """视觉定位测试：单模型调用，支持预热"""
        import time
        try:
            data = self._read_post_body()
            image_b64 = data.get("image_b64", "")
            desc = data.get("desc", "").strip()
            model_id = data.get("model_id", "omlx_26b")
            warmup = data.get("warmup", False)
            img_w = data.get("img_w", 0)  # 图片原始宽高（用于像素坐标归一化）
            img_h = data.get("img_h", 0)

            if not image_b64 or not desc:
                self._json_response({"error": "image_b64 和 desc 不能为空"}); return

            models = self._bench_models()
            mc = models.get(model_id)
            if not mc:
                self._json_response({"error": f"未知模型: {model_id}"}); return

            prompt = f"""这是一张应用界面截图。
请找到以下元素：{desc}

请仅返回一个严格 JSON（不要包含任何其他内容）：
{{"x": 0, "y": 0}}
其中 x, y 是元素中心点的千分比相对坐标（0 到 1000 之间的整数，例如 500 代表图片正中间）。"""

            # 预热
            warmup_elapsed = None
            if warmup:
                t0 = time.time()
                self._bench_call(mc, "好", max_tokens=8)
                warmup_elapsed = round(time.time() - t0, 2)

            # 正式测试
            t0 = time.time()
            raw_text, error, pt, ct = self._bench_call(mc, prompt, image_b64=image_b64, max_tokens=64)
            elapsed = round(time.time() - t0, 2)

            # 解析坐标
            coord = None
            if raw_text:
                try:
                    t = raw_text
                    if t.startswith("```json"): t = t[7:]
                    elif t.startswith("```"): t = t[3:]
                    if t.endswith("```"): t = t[:-3]
                    coord = json.loads(t.strip())
                except Exception:
                    import re
                    m = re.search(r'"x"\s*:\s*([\d.]+).*?"y"\s*:\s*([\d.]+)', raw_text, re.S)
                    if m:
                        coord = {"x": float(m.group(1)), "y": float(m.group(2))}

            # 归一化坐标（如果是千分比坐标 [0~1000] 则除以 1000）
            norm_coord = None
            if coord:
                nx = coord["x"] / 1000.0 if coord["x"] > 1 else coord["x"]
                ny = coord["y"] / 1000.0 if coord["y"] > 1 else coord["y"]
                norm_coord = {"x": round(nx, 4), "y": round(ny, 4),
                              "px": coord["x"], "py": coord["y"]}

            self._json_response({
                "success": True,
                "model_id": model_id, "label": mc["label"], "color": mc["color"],
                "elapsed": elapsed, "warmup_elapsed": warmup_elapsed,
                "raw": raw_text, "coord": coord, "norm_coord": norm_coord,
                "error": error,
            })
        except Exception as e:
            self._json_response({"success": False, "error": str(e)})

    def _benchmark_speed(self):
        """速度基准测试：单模型调用"""
        import time
        try:
            data = self._read_post_body()
            model_id = data.get("model_id", "omlx_26b")
            warmup = data.get("warmup", False)

            models = self._bench_models()
            mc = models.get(model_id)
            if not mc:
                self._json_response({"error": f"未知模型: {model_id}"}); return

            prompt = "请用中文简要介绍一下大语言模型的工作原理，包括 Transformer 架构、注意力机制、预训练与微调三个方面，300字内。"

            # 预热
            warmup_elapsed = None
            if warmup:
                t0 = time.time()
                self._bench_call(mc, "好", max_tokens=8)
                warmup_elapsed = round(time.time() - t0, 2)

            # 正式测试
            t0 = time.time()
            text_out, error, pt, ct = self._bench_call(mc, prompt, max_tokens=512)
            elapsed = round(time.time() - t0, 2)
            tps = round(ct / elapsed, 1) if ct and elapsed > 0 else None

            self._json_response({
                "success": True,
                "model_id": model_id, "label": mc["label"], "color": mc["color"],
                "elapsed": elapsed, "warmup_elapsed": warmup_elapsed,
                "prompt_tokens": pt, "completion_tokens": ct, "tps": tps,
                "preview": (text_out or "")[:200],
                "error": error,
            })
        except Exception as e:
            self._json_response({"success": False, "error": str(e)})


            capability_doc = _planner.registry.get_full_capability_description()
            prompt = f"""你是一个应用控制层，从用户指令中识别目标应用和操作意图。

已注册的技能：
{capability_doc}

用户说：「{text}」

请仅返回一个严格的 JSON（不要包含任何多余文字）：
{{
  "steps": [
    {{
      "app": "应用名",
      "intent": "意图名",
      "slots": {{}},
      "description": "简短描述"
    }}
  ]
}}"""

            results = []
            # 模型配置：oMLX 26B/31B + Ollama 26B/31B
            model_configs = [
                {"id": "omlx_26b", "label": "oMLX · Gemma 4 26B",
                 "mode": "openai", "url": "http://localhost:8000/v1",
                 "model": "gemma-4-26b-a4b-it-4bit", "key": _cfg.API_KEY},
                {"id": "omlx_31b", "label": "oMLX · Gemma 4 31B",
                 "mode": "openai", "url": "http://localhost:8000/v1",
                 "model": "gemma-4-31b-a4b-it-4bit", "key": _cfg.API_KEY},
                {"id": "ollama_26b", "label": "Ollama · Gemma 4 26B",
                 "mode": "ollama", "url": "http://localhost:11434/api/generate",
                 "model": "gemma4:26b", "key": ""},
                {"id": "ollama_31b", "label": "Ollama · Gemma 4 31B",
                 "mode": "ollama", "url": "http://localhost:11434/api/generate",
                 "model": "gemma4:31b", "key": ""},
            ]

            import requests as _req
            for mc in model_configs:
                t0 = time.time()
                raw_text = None
                error = None
                try:
                    if mc["mode"] == "openai":
                        url = mc["url"].rstrip("/") + "/chat/completions"
                        hdr = {"Content-Type": "application/json"}
                        if mc["key"]:
                            hdr["Authorization"] = f"Bearer {mc['key']}"
                        resp = _req.post(url, json={
                            "model": mc["model"],
                            "messages": [{"role": "user", "content": prompt}],
                            "stream": False, "max_tokens": 512,
                        }, headers=hdr, timeout=60)
                        resp.raise_for_status()
                        raw_text = resp.json()["choices"][0]["message"]["content"].strip()
                    else:
                        resp = _req.post(mc["url"], json={
                            "model": mc["model"], "prompt": prompt, "stream": False
                        }, timeout=90)
                        resp.raise_for_status()
                        raw_text = resp.json().get("response", "").strip()
                except Exception as e:
                    error = str(e)

                elapsed = round(time.time() - t0, 2)

                # 尝试解析 JSON
                parsed_ok = False
                parsed_data = None
                if raw_text:
                    try:
                        t = raw_text
                        if t.startswith("```json"): t = t[7:]
                        elif t.startswith("```"): t = t[3:]
                        if t.endswith("```"): t = t[:-3]
                        parsed_data = json.loads(t.strip())
                        parsed_ok = True
                    except Exception:
                        pass

                results.append({
                    "id": mc["id"], "label": mc["label"],
                    "elapsed": elapsed,
                    "raw": raw_text,
                    "parsed_ok": parsed_ok,
                    "parsed": parsed_data,
                    "error": error,
                })

            self._json_response({"success": True, "results": results})
        except Exception as e:
            self._json_response({"success": False, "error": str(e)})

    def _serve_ui(self):
        """返回内嵌的 Web 界面"""
        html = _get_ui_html()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        """静默普通访问日志"""
        pass

from http.server import HTTPServer
from socketserver import ThreadingMixIn

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True

def start_server(host: str = None, port: int = None):
    """启动 Web 服务"""
    global _planner

    registry = SkillRegistry()
    registry.auto_register()
    _planner = Planner(registry)

    h = host or config.SERVER_HOST
    p = port or config.SERVER_PORT
    local_ip = _get_local_ip()

    # ── 启动串行任务 worker 线程（唯一消费者）────────────────────────
    # 所有来自不同设备的请求都放入 _task_queue，此线程按顺序逐一取出执行
    # 保证同一时刻只有 1 个任务在操控鼠标/键盘，彻底消除物理操作竞态
    def _task_worker():
        while True:
            task_id = _task_queue.get()  # 阻塞等待，有任务才继续
            try:
                task = _tasks.get(task_id)
                if not task or task.get("status") == "cancelled":
                    # 任务已在排队期间被取消，直接跳过
                    continue
                command = task["command"]
                QingAgentHandler._run_task(task_id, command)
            except Exception as e:
                print(f"⚠️ Worker 异常：{e}")
            finally:
                _task_queue.task_done()

    worker = threading.Thread(target=_task_worker, daemon=True, name="task-worker")
    worker.start()
    print("✅ 任务队列 Worker 已启动（串行执行，防止物理操作并发冲突）")

    server = ThreadedHTTPServer((h, p), QingAgentHandler)
    print(f"\n{'='*50}")
    print(f"🚀 QingAgent Web 服务已启动")
    print(f"🌐 本机访问: http://localhost:{p}")
    print(f"📱 手机访问: http://{local_ip}:{p}")
    print(f"{'='*50}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
        server.server_close()


def _get_ui_html() -> str:
    """内嵌的 Web 界面 HTML — 移动端优先设计"""
    return '''<!DOCTYPE html>
<html lang="zh-CN" id="htmlRoot">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>QingAgent</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

        * { margin: 0; padding: 0; box-sizing: border-box; }

        /* === 全局滚动条美化（深色主题匹配） === */
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb {
            background: rgba(255, 255, 255, 0.12);
            border-radius: 99px;
        }
        ::-webkit-scrollbar-thumb:hover { background: rgba(255, 255, 255, 0.22); }
        * { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.12) transparent; }

        :root {
            --bg-primary: #0b0b11;
            --bg-secondary: #13131d;
            --bg-card: #1a1a2e;
            --border: rgba(255,255,255,0.06);
            --text-primary: #e8e8ed;
            --text-secondary: #8888a0;
            --accent-start: #667eea;
            --accent-end: #764ba2;
            --success: #4ade80;
            --error: #f87171;
            --safe-bottom: env(safe-area-inset-bottom, 0px);
        }

        /* === 浅色主题覆盖 === */
        [data-theme="light"] {
            --bg-primary: #f0f2f7;
            --bg-secondary: #ffffff;
            --bg-card: #eef0ff;
            --bg-card-inner: #e6eaff;
            --border: rgba(90,111,232,0.13);
            --text-primary: #111827;
            --text-secondary: #4b5563;
            --accent-start: #5a6fe8;
            --accent-end: #6a3f9e;
            --success: #16a34a;
            --error: #dc2626;
        }
        [data-theme="light"] ::-webkit-scrollbar-thumb {
            background: rgba(0,0,0,0.14);
        }
        /* 快捷栏 chip - 深文字、可辨识背景 */
        [data-theme="light"] .quick-chip {
            background: rgba(90,111,232,0.08);
            color: #374151;
            border: 1px solid rgba(90,111,232,0.15);
        }
        [data-theme="light"] .quick-chip:hover {
            background: rgba(90,111,232,0.16);
            color: var(--accent-start);
            border-color: rgba(90,111,232,0.3);
        }
        /* Agent 消息气泡 */
        [data-theme="light"] .msg-row.agent .msg-bubble {
            background: #f5f6ff;
            color: #111827;
            border: 1px solid rgba(90,111,232,0.16);
            box-shadow: 0 2px 10px rgba(90,111,232,0.08);
        }
        /* 气泡内的数据卡片（日历/文件选择等） */
        [data-theme="light"] .msg-row.agent .msg-bubble [style*="var(--bg-card)"],
        [data-theme="light"] .msg-row.agent .msg-bubble > div > div {
            /* 通过继承 --bg-card 变量自动生效 */
        }
        /* 数据/代码展示块 */
        [data-theme="light"] .msg-data {
            background: #f0f4ff;
            color: #1e293b;
            border: 1px solid rgba(90,111,232,0.15);
        }
        /* 输入区 */
        [data-theme="light"] .input-area {
            background: #ffffff;
            border-top: 1px solid rgba(0,0,0,0.09);
        }
        [data-theme="light"] .input-area input {
            background: #f0f2f7;
            color: #111827;
            border-color: rgba(0,0,0,0.12);
        }
        [data-theme="light"] .input-area input::placeholder {
            color: rgba(0,0,0,0.32);
        }
        [data-theme="light"] .input-area input:focus {
            background: #e8ecf8;
            border-color: rgba(90,111,232,0.4);
        }
        [data-theme="light"] .send-btn {
            background: rgba(90,111,232,0.1);
            color: var(--accent-start);
        }
        [data-theme="light"] .send-btn:hover {
            background: rgba(90,111,232,0.2);
        }
        [data-theme="light"] .mic-btn {
            background: rgba(0,0,0,0.05);
            color: #374151;
        }
        [data-theme="light"] .mic-btn:hover {
            background: rgba(0,0,0,0.1);
        }
        /* 模式胶囊开关 */
        [data-theme="light"] .mode-capsule {
            background: rgba(0,0,0,0.07);
            border-color: rgba(0,0,0,0.1);
        }
        [data-theme="light"] .mode-btn {
            color: rgba(0,0,0,0.35);
        }
        [data-theme="light"] .mode-btn.safe.active {
            color: #16a34a;
        }
        [data-theme="light"] .mode-btn.fast.active {
            color: #dc2626;
        }
        [data-theme="light"] .mode-indicator {
            background: rgba(0,0,0,0.07);
        }
        /* 弹窗 */
        [data-theme="light"] .modal-overlay { background: rgba(0,0,0,0.32); }
        [data-theme="light"] .modal-content {
            background: #ffffff;
            border: 1px solid rgba(0,0,0,0.1);
            box-shadow: 0 20px 60px rgba(0,0,0,0.18);
            color: #111827;
        }
        [data-theme="light"] .skill-card {
            background: #f8f9fc;
            border-color: rgba(0,0,0,0.07);
            color: #111827;
        }
        [data-theme="light"] .skill-card:hover {
            background: rgba(90,111,232,0.06);
            border-color: rgba(90,111,232,0.2);
        }
        /* 主题切换按钮 (布局样式已提至 header-btn 统一处理) */
        .theme-toggle {
            width: 30px; height: 30px;
            border-radius: 8px;
            background: rgba(128, 138, 157, 0.12);
            color: var(--text-secondary);
            font-size: 15px;
        }
        .theme-toggle:hover {
            background: rgba(102,126,234,0.15);
            color: var(--accent-start);
            transform: translateY(-1px);
        }
        [data-theme="light"] .theme-toggle:hover {
            background: rgba(90,111,232,0.12);
            color: var(--accent-start);
        }
        .theme-toggle:active {
            transform: scale(0.96);
        }

        html, body {
            height: 100%;
            overflow: hidden;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            -webkit-font-smoothing: antialiased;
        }

        .app {
            display: flex;
            flex-direction: column;
            height: 100%;
            max-width: 600px;
            margin: 0 auto;
        }

        /* === 顶部栏 === */
        .header {
            padding: 16px 20px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border);
            display: flex;
            align-items: center;
            gap: 12px;
            flex-shrink: 0;
        }

        .header-avatar {
            width: 40px; height: 40px;
            border-radius: 12px;
            background: linear-gradient(135deg, var(--accent-start), var(--accent-end));
            display: flex; align-items: center; justify-content: center;
            font-size: 20px;
            flex-shrink: 0;
        }

        .header-info h1 {
            font-size: 16px; font-weight: 600;
            background: linear-gradient(135deg, var(--accent-start), var(--accent-end));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header-info p {
            font-size: 11px; color: var(--text-secondary);
            margin-top: 2px;
        }

        .status-dot {
            width: 8px; height: 8px;
            border-radius: 50%;
            background: var(--success);
            margin-left: auto;
            flex-shrink: 0;
            animation: pulse 2s infinite;
        }

        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
        }

        /* === 顶部功能按键及统一样式 === */
        .header-btn, .theme-toggle, .emergency-btn {
            border: none;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer;
            transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
            flex-shrink: 0;
            white-space: nowrap;
            -webkit-tap-highlight-color: transparent;
        }

        .header-btn, .emergency-btn {
            padding: 6px 12px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 500;
            gap: 4px;
        }

        .header-btn {
            background: rgba(128, 138, 157, 0.12);
            color: var(--text-secondary);
        }
        .header-btn:hover {
            background: rgba(128, 138, 157, 0.2);
            color: var(--text-primary);
            transform: translateY(-1px);
        }
        .header-btn:active {
            transform: scale(0.96);
        }

        /* === 聊天区 === */
        .chat-area {
            flex: 1;
            overflow-y: auto;
            -webkit-overflow-scrolling: touch;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .msg-row {
            display: flex;
            flex-direction: column;
            animation: slideIn 0.3s ease;
        }

        @keyframes slideIn {
            from { opacity: 0; transform: translateY(12px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .msg-row.user { align-items: flex-end; }
        .msg-row.agent { align-items: flex-start; }

        .msg-bubble {
            max-width: 88%;
            padding: 12px 16px;
            border-radius: 18px;
            font-size: 14px;
            line-height: 1.65;
            word-break: break-word;
        }

        .msg-row.user .msg-bubble {
            background: linear-gradient(135deg, var(--accent-start), var(--accent-end));
            color: white;
            border-bottom-right-radius: 6px;
        }

        .msg-row.agent .msg-bubble {
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-bottom-left-radius: 6px;
        }

        .msg-row.agent.success .msg-bubble { border-left: 3px solid var(--success); }
        .msg-row.agent.error .msg-bubble { border-left: 3px solid var(--error); }

        .msg-time {
            font-size: 10px;
            color: var(--text-secondary);
            margin-top: 4px;
            padding: 0 4px;
        }

        /* 加载动画 */
        .loading-dots {
            display: inline-flex;
            gap: 4px;
            padding: 4px 0;
        }

        .loading-dots span {
            width: 6px; height: 6px;
            border-radius: 50%;
            background: var(--accent-start);
            animation: bounce 1.4s infinite ease-in-out;
        }

        .loading-dots span:nth-child(1) { animation-delay: 0s; }
        .loading-dots span:nth-child(2) { animation-delay: 0.2s; }
        .loading-dots span:nth-child(3) { animation-delay: 0.4s; }

        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
            40% { transform: scale(1); opacity: 1; }
        }

        .timer {
            font-size: 11px;
            color: var(--text-secondary);
            margin-top: 6px;
        }

        .cancel-btn {
            margin-left: 12px;
            padding: 2px 10px;
            border-radius: 12px;
            background: rgba(248,113,113,0.1);
            color: var(--error);
            border: 1px solid rgba(248,113,113,0.3);
            font-size: 11px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .cancel-btn:active {
            transform: scale(0.95);
            background: rgba(248,113,113,0.2);
        }

        /* 数据展示 */
        .msg-data {
            margin-top: 10px;
            padding: 10px 12px;
            background: rgba(0,0,0,0.3);
            border-radius: 10px;
            font-size: 12px;
            color: var(--text-secondary);
            white-space: pre-wrap;
            line-height: 1.5;
            max-height: 200px;
            overflow-y: auto;
        }

        /* === 输入区 === */
        .input-area {
            padding: 10px 14px;
            padding-bottom: calc(10px + var(--safe-bottom));
            background: var(--bg-secondary);
            border-top: 1px solid var(--border);
            display: flex;
            gap: 8px;
            align-items: center;
            flex-shrink: 0;
        }

        .input-area input {
            flex: 1;
            padding: 9px 14px;
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.07);
            background: rgba(255,255,255,0.04);
            color: rgba(255,255,255,0.88);
            font-size: 14px;
            font-family: inherit;
            outline: none;
            transition: border-color 0.2s, background 0.2s;
            -webkit-appearance: none;
        }

        .input-area input:focus {
            border-color: rgba(255,255,255,0.18);
            background: rgba(255,255,255,0.06);
        }

        .input-area input::placeholder { color: rgba(255,255,255,0.25); font-size:13px; }

        .send-btn, .mic-btn {
            width: 34px; height: 34px;
            border-radius: 8px;
            border: none;
            color: rgba(255,255,255,0.7);
            font-size: 16px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: all 0.18s ease;
            flex-shrink: 0;
            -webkit-tap-highlight-color: transparent;
            background: rgba(255,255,255,0.06);
        }

        .send-btn {
            color: #a5b4fc;
        }
        .send-btn:hover {
            background: rgba(102,126,234,0.18);
            color: #818cf8;
        }

        .mic-btn {
            font-size: 16px;
        }
        .mic-btn:hover {
            background: rgba(255,255,255,0.1);
        }

        .mic-btn.recording {
            background: rgba(239,68,68,0.2);
            border: 1px solid rgba(239,68,68,0.4);
            color: #fca5a5;
            animation: micPulse 1s ease-in-out infinite;
        }

        @keyframes micPulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.4); }
            50% { box-shadow: 0 0 0 6px rgba(239,68,68,0); }
        }

        .mic-btn.unsupported {
            opacity: 0.2;
            cursor: not-allowed;
        }

        .send-btn:active, .mic-btn:active { transform: scale(0.9); opacity: 0.7; }
        .send-btn:disabled { opacity: 0.2; }

        /* 紧急停止按钮 (布局样式已提至 header-btn) */
        .emergency-btn {
            background: rgba(239, 68, 68, 0.1);
            color: #ef4444;
            font-weight: 600;
        }
        .emergency-btn:hover {
            background: rgba(239, 68, 68, 0.18);
            transform: translateY(-1px);
        }
        .emergency-btn:active {
            transform: scale(0.96);
        }
        
        /* 双轨状态胶囊开关 */
        .mode-capsule {
            display: flex;
            align-items: center;
            background: rgba(0, 0, 0, 0.2);
            border-radius: 20px;
            padding: 4px;
            margin: 0 16px 12px 16px;
            width: 160px;
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.05);
            position: relative;
        }
        .mode-btn {
            flex: 1;
            padding: 6px 0;
            font-size: 13px;
            font-weight: 500;
            color: rgba(255, 255, 255, 0.4);
            border-radius: 16px;
            cursor: pointer;
            text-align: center;
            position: relative;
            z-index: 2;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            -webkit-tap-highlight-color: transparent;
        }
        .mode-btn.safe.active {
            color: #10b981;
            text-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
        }
        .mode-btn.fast.active {
            color: #ef4444;
            text-shadow: 0 0 10px rgba(239, 68, 68, 0.6);
            animation: pulseFast 2s infinite;
        }
        @keyframes pulseFast {
            0%, 100% { text-shadow: 0 0 8px rgba(239, 68, 68, 0.4); }
            50% { text-shadow: 0 0 16px rgba(239, 68, 68, 0.8), 0 0 4px rgba(255, 255, 255, 0.5); }
        }
        .mode-slider {
            position: absolute;
            top: 4px; bottom: 4px; left: 4px;
            width: 76px;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.1);
            box-shadow: inset 0 1px 1px rgba(255,255,255,0.2), 0 2px 4px rgba(0,0,0,0.2);
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 1;
        }
        .mode-slider.fast-active {
            transform: translateX(76px);
            background: rgba(239, 68, 68, 0.15);
            box-shadow: inset 0 1px 1px rgba(239,68,68,0.3), 0 2px 8px rgba(239,68,68,0.2);
        }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="header-avatar" style="background:none; padding:0;">
            <img src="data:image/png;base64,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gAABAgQIECBAgAABAgSKIvDAY09u2rHr4MfTrGy1alq1AHC6PvdHX/ruQ5tWa2K2Q4AAAQIECBAgQIAAAQIECBAgQKCIAp/9xj2bpmv1P1qt2lYlAAyJ5utvv3fXr03XZwWAq9VZ2yFAgAABAgQIECBAgAABAgQIECikwFStvukrdz30a2lmthoFrkoAuPfI6Y/e88gBf/dvNTpqGwQIECBAgAABAgQIECBAgAABAoUX+IcHdg3vOnDso6tRaO4BYH2u+btf+u7Oa9tJkvu2VgPMNggQIECAAAECBAgQIECAAAECBAisVCDNyj7zjXuurc/N/e5Kx7rU+rmGcuFtjNf94OH9HxqZmNlyqUI8ToAAAQIECBAgQIAAAQIECBAgQKBMAqfGJrfced/uD6UZWp7zzjUAHBmf+cNv37erkecEjE2AAAECBAgQIECAAAECBAgQIEAgVoGvfm9n4+TY5B/mWX9uAWBILl/37Qd33dZotYbynICxCRAgQIAAAQIECBAgQIAAAQIECMQq0Gg2h77+vYdvS7O0vOaQWwB48MTYR3606/CGvAo3LgECBAgQIECAAAECBAgQIECAAIFeEPjhw3s37D9y6iN5zSWXADAklu/6+g8evbHd9sEfeTXOuAQIECBAgAABAgQIECBAgAABAr0h0E4q1S9854GQpbXflceMcgkAHz1w/A8OHB25PI+CjUmAAAECBAgQIECAAAECBAgQIECg1wT2Hjp5+Y7dh/4gj3llHgDONZu/89XvP7o5j2KNSYAAAQIECBAgQIAAAQIECBAgQKBXBb5w+32b02wt6/llGgCGtyn2P/jYoQ+OTkwLALPulPEIECBAgAABAgQIECBAgAABAgR6WuDU+PTmH+zc98E0Y8tyopkGgI1G633fvn9PX5YFGosAAQIECBAgQIAAAQIECBAgQIBAWQS++o8P9TUajfdlOd/MAsCQTK7bsefw+ydmapuyLNBYBAgQIECAAAECBAgQIECAAAECBMoiMD45s+meRw68P83asppzZgFgq5X8zrfu39XMqjDjECBAgAABAgQIECBAgAABAgQIECijwFfu2tlMs7as5p5JABgSyb4dew+9d2KqviWrwoxDgAABAgQIECBAgAABAgQIECBAoIwCY5MzW+599In3pZlbFvPPJAAMhbzn9vt2t7MoyBgECBAgQIAAAQIE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IxEgQIAAAQIECBAgQIAAAQIECBAojED4EwDVavo2wMJUpBACBAgQIECAAAECBAgQIECAAAECBDITmP8V4PBJQALAzEgNRIAAAQIECBAgQIAAAQIECBAgQKA4Amn2l74D0N8ALE5PVEKAAAECBAgQIECAAAECBAgQIEAgM4E0+/Puv8w4DUSAAAECBAgQIECAAAECBAgQIECgeAICwOL1REUECBAgQIAAAQIECBAgQIAAAQIEMhMQAGZGaSACBAgQIECAAAECBAgQIECAAAECxRMQABavJyoiQIAAAQIECBAgQIAAAQIECBAgkJmAADAzSgMRIECAAAECBAgQIECAAAECBAgQKJ6AALB4PVERAQIECBAgQIAAAQIECBAgQIAAgcwEBICZURqIAAECBAgQIECAAAECBAgQIECAQPEEBIDF64mKCBAgQIAAAQIECBAgQIAAAQIECGQmIADMjNJABAgQIECAAAECBAgQIECAAAECBIonIAAsXk9URIAAAQIECBAgQIAAAQIECBAgQCAzAQFgZpQGIkCAAAECBAgQIECAAAECBAgQIFA8AQFg8XqiIgIECBAgQIAAAQIECBAgQIAAAQKZCQgAM6M0EAECBAgQIECAAAECBAgQIECAAIHiCQgAi9cTFREgQIAAAQIECBAgQIAAAQIECBDITEAAmBmlgQgQIECAAAECBAgQIECAAAECBAgUT0AAWLyeqIgAAQIECBAgQIAAAQIECBAgQIBAZgICwMwoDUSAAAECBAgQIECAAAECBAgQIECgeAICwOL1REUECBAgQIAAAQIECBAgQIAAAQIEMhMQAGZGaSACBAgQIECAAAECBAgQIECAAAECxRMQABavJyoiQIAAAQIECBAgQIAAAQIECBAgkJmAADAzSgMRIECAAAECBAgQIECAAAECBAgQKJ6AALB4PVERAQIECBAgQIAAAQIECBAgQIAAgcwEBICZURqIAAECBAgQIECAAAECBAgQIECAQPEEBIDF64mKCBAgQIAAAQIECBAgQIAAAQIECGQmIADMjNJABAgQIECAAAECBAgQIECAAAECBIonIAAsXk9URIAAAQIECBAgQIAAAQIECBAgQCAzAQFgZpQGIkCAAAECBAgQIECAAAECBAgQIFA8AQFg8XqiIgIECBAgQIAAAQIECBAgQIAAAQKZCQgAM6M0EAECBAgQIECAAAECBAgQIECAAIHiCQgAi9cTFREgQIAAAQIECBAgQIAAAQIECBDITEAAmBmlgQgQIECAAAECBAgQIECAAAECBAgUT0AAWLyeqIgAAQIECBAgQIAAAQIECBAgQIBAZgICwMwoDUSAAAECBAgQIECAAAECBAgQIECgeAICwOL1REUECBAgQIAAAQIECBAgQIAAAQIEMhMQAGZGaSACBAgQIECAAAECBAgQIECAAAECxRPoT5J20mq1ilfZEhVVKpUlHnF3NwKpJ9Nu5HplnXY4BDSjmMyuH92dHHj8ocLXOrB+S9I3sL7wdaYFbrnijclgdV0UtSZJHMf+cERNKq04ak2SRuh9+lXsS6UdzlHa4VgVwaWdxPPvqq2+cAoYy6UZx3OqnZ5Tx7CrhudTO5LnVPo6JZbL1z/7J1GUWq1Wkiu2xXGe0phrJrXaXOFd549QlTj21Xr4sd+Mo9Tktf/i7Um1r6/w/U8LjOeYGscpVeoZi2ksdZ59IvWnP/9jK/ps8b4TKKpANKHq/ME1jn8AOHHoiWT3jruL2vJzdW256vpk3abLz90u8pVWs/jhT5H9Fqst/ZlaaccRVlTmX1gX/x8AKq1QYxoCRnFJX6hE0v9qHC+q0rZH8lp1fg9NQ8DiX9IaY6iz+JLnV/jo/cU/R0nr7e+rJrXrNp9femGvz4a0anqqXtj6zi+sEkkAON2oJI1IfqT+3JvemlSqcfzDmjzl/GdDFtfTADCOHTW23sfxjMpiHzIGAQIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCggAS9h0UyZAgAABAgQIECBAgAABAgQIECiPgACwPL02UwIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCggAS9h0UyZAgAABAgQIECBAgAABAgQIECiPgACwPL02UwIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCggAS9h0UyZAgAABAgQIECBAgAABAgQIECiPgACwPL02UwIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCggAS9h0UyZAgAABAgQIECBAgAABAgQIECiPgACwPL02UwIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCggAS9h0UyZAgAABAgQIECBAgAABAgQIECiPgACwPL02UwIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCggAS9h0UyZAgAABAgQIECBAgAABAgQIECiPgACwPL02UwIECBAgQIAAAQIECBAgQIAAgRIKCABL2HRTJkCAAAECBAgQIECAAAECBAgQKI+AALA8vTZTAgQIECBAgAABAgQIECBAgACBEgoIAEvYdFMmQIAAAQIECBAgQIAAAQIECBAoj4AAsDy9NlMCBAgQIECAAAECBAgQIECAAIESCvSnc261WlFMvVKpJO12O5paYyg0Fs8YLM+vsa+/cv7Nwl6vtltJ/1yjsPWdX9hgeP4PDQycf1chr09PTSZTtThMP/XR30/iOKImyXWXbShkv59WVHjqVyL5p7W52dmkEb6KfpmbaybNZrPoZcZXX2X+FDCCuttJOPuLoM4kqfb3Jf39xXe96ZW3JC+6+bVRmH7/a3+ZjBw/HEWtWzf3RVHnunXrk5t/7pejqHVgw9Zk/bZro6g1liKb7WbSiuSY2tdf/PP+WPp+fp0xvP6PocbzTWO6XvyzlPM00x0hDQFdCBDITiCWZ1T63I/h+Z8ep2L5R5WZEFa2Qggcw6U+FEedIakIKUAMokmSBoBz9eIHgI1GM0m/XLIWiCOsSGddqcTx/O/rCwFgBP9Q1ZitB9U4QtW52kxSn57MeufPZbxqJCdU1Wo1GRhcl4tB1oMOrhtO1m3YlPWwpR4vDQDbkTz/Yymz1DuUyUcnEMnLlOhcFUyAAAECBAgQIECAAAECBAgQIECgEAICwEK0QREECBAgQIAAAQIECBAgQIAAAQIE8hEQAObjalQCBAgQIECAAAECBAgQIECAAAEChRAQABaiDYogQIAAAQIECBAgQIAAAQIECBAgkI+AADAfV6MSIECAAAECBAgQIECAAAECBAgQKISAALAQbVAEAQIECBAgQIAAAQIECBAgQIAAgXwEBID5uBqVAAECBAgQIECAAAECBAgQIECAQCEEBICFaIMiCBAgQIAAAQIECBAgQIAAAQIECOQjIADMx9WoBAgQIECAAAECBAgQIECAAAECBAohIAAsRBsUQYAAAQIECBAgQIAAAQIECBAgQCAfAQFgPq5GJUCAAAECBAgQIECAAAECBAgQIFAIAQFgIdqgCAIECBAgQIAAAQIECBAgQIAAAQL5CAgA83E1KgECBAgQIECAAAECBAgQIECAAIFCCAgAC9EGRRAgQIAAAQIECBAgQIAAAQIECBDIR0AAmI+rUQkQIECAAAECBAgQIECAAAECBAgUQkAAWIg2KIIAAQIECBAgQIAAAQIECBAgQIBAPgICwHxcjUqAAAECBAgQIECAAAECBAgQIECgEAICwEK0QREECBAgQIAAAQIECBAgQIAAAQIE8hEQAObjalQCBAgQIECAAAECBAgQIECAAAEChRAQABaiDYogQIAAAQIECBAgQIAAAQIECBAgkI+AADAfV6MSIECAAAECBAgQIECAAAECBAgQKISAALAQbVAEAQIECBAgQIAAAQIECBAgQIAAgXwEBID5uBqVAAECBAgQIECAAAECBAgQIECAQCEEBICFaIMiCBAgQIAAAQIECBAgQIAAAQIECOQjIADMx9WoBAgQIECAAAECBAgQIECAAAECBAohIAAsRBsUQYAAAQIECBAgQIAAAQIECBAgQCAfAQFgPq5GJUCAAAECBAgQIECAAAECBAgQIFAIAQFgIdqgCAIECBAgQIAAAQIECBAgQIAAAQL5CAgA83E1KgECBAgQIECAAAECBAgQIECAAIFCCAgAC9EGRRAgQIAAAQIECBAgQIAAAQIECBDIR0AAmI+rUQkQIECAAAECBAgQIECAAAECBAgUQkAAWIg2KIIAAQIECBAgQIAAAQIECBAgQIBAPgICwHxcjUqAAAECBAgQIECAAAECBAgQIECgEAICwEK0QREECBAgQIAAAQIECBAgQIAAAQIE8hEQAObjalQCBAgQIECAAAECBAgQIECAAAEChRAQABaiDYogQIAAAQIECBAgQIAAAQIECBAgkI+AADAfV6MSIECAAAECBAgQIECAAAECBAgQxQ1AegAAQABJREFUKISAALAQbVAEAQIECBAgQIAAAQIECBAgQIAAgXwEBID5uBqVAAECBAgQIECAAAECBAgQIECAQCEEBICFaIMiCBAgQIAAAQIECBAgQIAAAQIECOQjIADMx9WoBAgQIECAAAECBAgQIECAAAECBAohUHnZK17Vft273leIYpZTRKVSWc5iliGwtgKV5tpuf5lbP3lgV/LgN/5ymUuv7WKzzUbSaBXftdJOkniOUsX3PLvXjYxNnL1a+O/tVqvwNc4XGPbVdjv8z4UAgXIJxPNDKklaodhIDlOnJ6fi2I/Ca6n+geEoar322dcnL33FTxW+1o1XPTPZ/KzrC19nWmA1PU+N5DkV0zlKLLWmdbZiOE8NdUZjGsUz/0yRP/xvH0u8AzCihimVAAECBAgQIECAAAECBAgQIECAQKcCAsBOxSxPgAABAgQIECBAgAABAgQIECBAICIBAWBEzVIqAQIECBAgQIAAAQIECBAgQIAAgU4FBICdilmeAAECBAgQIECAAAECBAgQIECAQEQCAsCImqVUAgQIECBAgAABAgQIECBAgAABAp0KCAA7FbM8AQIECBAgQIAAAQIECBAgQIAAgYgEBIARNUupBAgQIECAAAECBAgQIECAAAECBDoVEAB2KmZ5AgQIECBAgAABAgQIECBAgAABAhEJCAAjapZSCRAgQIAAAQIECBAgQIAAAQIECHQqIADsVMzyBAgQIECAAAECBAgQIECAAAECBCISEABG1CylEiBAgAABAgQIECBAgAABAgQIEOhUQADYqZjlCRAgQIAAAQIECBAgQIAAAQIECEQkIACMqFlKJUCAAAECBAgQIECAAAECBAgQINCpgACwUzHLEyBAgAABAgQIECBAgAABAgQIEIhIQAAYUbOUSoAAAQIECBAgQIAAAQIECBAgQKBTAQFgp2KWJ0CAAAECBAgQIECAAAECBAgQIBCRgAAwomYplQABAgQIECBAgAABAgQIECBAgECnAgLATsUsT4AAAQIECBAgQIAAAQIECBAgQCAiAQFgRM1SKgECBAgQIECAAAECBAgQIECAAIFOBQSAnYpZngABAgQIECBAgAABAgQIECBAgEBEAgLAiJqlVAIECBAgQIAAAQIECBAgQIAAAQKdCggAOxWzPAECBAgQIECAAAECBAgQIECAAIGIBASAETVLqQQIECBAgAABAgQIECBAgAABAgQ6FRAAdipmeQIECBAgQIAAAQIECBAgQIAAAQIRCQgAI2qWUgkQIECAAAECBAgQIECAAAECBAh0KiAA7FTM8gQIECBAgAABAgQIECBAgAABAgQiEhAARtQspRIgQIAAAQIECBAgQIAAAQIECBDoVEAA2KmY5QkQIECAAAECBAgQIECAAAECBAhEJCAAjKhZSiVAgAABAgQIECBAgAABAgQIECDQqYAAsFMxyxMgQIAAAQIECBAgQIAAAQIECBCISEAAGFGzlEqAAAECBAgQIECAAAECBAgQIECgUwEBYKdilidAgAABAgQIECBAgAABAgQIECAQkYAAMKJmKZUAAQIECBAgQIAAAQIECBAgQIBApwICwE7FLE+AAAECBAgQIECAAAECBAgQIEAgIgEBYETNUioBAgQIECBAgAABAgQIECBAgACBTgUEgJ2KWZ4AAQIECBAgQIAAAQIECBAgQIBARAICwIiapVQCBAgQIECAAAECBAgQIECAAAECnQoIADsVszwBAgQIECBAgAABAgQIECBAgACBiAQEgBE1S6kECBAgQIAAAQIECBAgQIAAAQIEOhUQAHYqZnkCBAgQIECAAAECBAgQIECAAAECEQn0R1SrUgkQyFigUqkm/f0DGY+az3CNditJWs18Bi/pqO12OvH5/5VUIIdpn0HNYWBDEiBAgECRBSqVSpHLO6+2ShJLpe1w7tdszJ1XezGvNubqyVy9VsziFlRVDad9lUhO/foHhxZU7yYBAisVmA8Am804XlSnP1jj+eG60tZYf6FATL2vJH0Lyy/k7W1XPju55U3vLGRtC4t6aMf3kr27dyy8u3C3W+1wWh3JidX4qYmk1QrBagyX9IzVhQABAgRWLhDT4TRNKiJJqy7btH7lvVm1EeLYCSZP7k9+8O0Dq6aykg21I/kHwHZ7MGm34/glwLf8zx9K+vrjeL9SNOfTK9nJV3Hd9PkUz3MqjuPpmfa1kzie/au4s9kUAQIECBAgQIAAAQIECBAgQIAAgV4SEAD2UjfNhQABAgQIECBAgAABAgQIECBAgMACAQHgAhA3CRAgQIAAAQIECBAgQIAAAQIECPSSgACwl7ppLgQIECBAgAABAgQIECBAgAABAgQWCAgAF4C4SYAAAQIECBAgQIAAAQIECBAgQKCXBASAvdRNcyFAgAABAgQIECBAgAABAgQIECCwQEAAuADETQIECBAgQIAAAQIECBAgQIAAAQK9JCAA7KVumgsBAgQIECBAgAABAgQIECBAgACBBQICwAUgbhIgQIAAAQIECBAgQIAAAQIECBDoJQEBYC9101wIECBAgAABAgQIECBAgAABAgQILBAQAC4AcZMAAQIECBAgQIAAAQIECBAgQIBALwkIAHupm+ZCgAABAgQIECBAgAABAgQIECBAYIGAAHABiJsECBAgQIAAAQIECBAgQIAAAQIEeklAANhL3TQXAgQIECBAgAABAgQIECBAgAABAgsEBIALQNwkQIAAAQIECBAgQIAAAQIECBAg0EsCAsBe6qa5ECBAgAABAgQIECBAgAABAgQIEFggIABcAOImAQIECBAgQIAAAQIECBAgQIAAgV4SEAD2UjfNhQABAgQIECBAgAABAgQIECBAgMACAQHgAhA3CRAgQIAAAQIECBAgQIAAAQIECPSSgACwl7ppLgQIECBAgAABAgQIECBAgAABAgQWCAgAF4C4SYAAAQIECBAgQIAAAQIECBAgQKCXBASAvdRNcyFAgAABAgQIECBAgAABAgQIECCwQEAAuADETQIECBAgQIAAAQIECBAgQIAAAQK9JCAA7KVumgsBAgQIECBAgAABAgQIECBAgACBBQICwAUgbhIgQIAAAQIECBAgQIAAAQIECBDoJQEBYC9101wIECBAgAABAgQIECBAgAABAgQILBAQAC4AcZMAAQIECBAgQIAAAQIECBAgQIBALwkIAHupm+ZCgAABAgQIECBAgAABAgQIECBAYIGAAHABiJsECBAgQIAAAQIECBAgQIAAAQIEeklAANhL3TQXAgQIECBAgAABAgQIECBAgAABAgsEBIALQNwkQIAAAQIECBAgQIAAAQIECBAg0EsCAsBe6qa5ECBAgAABAgQIECBAgAABAgQIEFggIABcAOImAQIECBAgQIAAAQIECBAgQIAAgV4SEAD2UjfNhQABAgQIECBAgAABAgQIECBAgMACAQHgAhA3CRAgQIAAAQIECBAgQIAAAQIECPSSgACwl7ppLgQIECBAgAABAgQIECBAgAABAgQWCAgAF4C4SYAAAQIECBAgQIAAAQIECBAgQKCXBASAvdRNcyFAgAABAgQIECBAgAABAgQIECCwQEAAuADETQIECBAgQIAAAQIECBAgQIAAAQK9JCAA7KVumgsBAgQIECBAgAABAgQIECBAgACBBQICwAUgbhIgQIAAAQIECBAgQIAAAQIECBDoJYH+mCbTbrdjKletBAovUJuZTE4f2FP4OtMCpybGkkoEh4DGXCNptVpRmLaTAFqJolRFEiBAgAABAgQKKRDXa9RWUonhhDp0utpuhnP/SE5UI3iNcvbJE1GpZ0v2PUOB+QAwpoNWLC+sY3lVXYnkmJru85WYis3wSZrnUKdOHE3uvvOreW4is7H7+/uS/v7iv2l5dqaW1Ov1zOad+0ARHQNyt7ABAgQIECBAoFACMb1OLRTcEsVUKo0lHine3dX2bNIXyT+qN9oDxQNcoqJYAkDP/SUauMK7i/9qeoUTtDoBAgQIECBAgAABAgQIECBAgACBMgsIAMvcfXMnQIAAAQIECBAgQIAAAQIECBDoeQEBYM+32AQJECBAgAABAgQIECBAgAABAgTKLCAALHP3zZ0AAQIECBAgQIAAAQIECBAgQKDnBQSAPd9iEyRAgAABAgQIECBAgAABAgQIECizgACwzN03dwIECBAgQIAAAQIECBAgQIAAgZ4XEAD2fItNkAABAgQIECBAgAABAgQIECBAoMwCAsAyd9/cCRAgQIAAAQIECBAgQIAAAQIEel5AANjzLTZBAgQIECBAgAABAgQIECBAgACBMgsIAMvcfXMnQIAAAQIECBAgQIAAAQIECBDoeQEBYM+32AQJECBAgAABAgQIECBAgAABAgTKLCAALHP3zZ0AAQIECBAgQIAAAQIECBAgQKDnBQSAPd9iEyRAgAABAgQIECBAgAABAgQIECizgACwzN03dwIECBAgQIAAAQIECBAgQIAAgZ4XEAD2fItNkAABAgQIECBAgAABAgQIECBAoMwCAsAyd9/cCRAgQIAAAQIECBAgQIAAAQIEel5AANjzLTZBAgQIECBAgAABAgQIECBAgACBMgsIAMvcfXMnQIAAAQIECBAgQIAAAQIECBDoeQEBYM+32AQJECBAgAABAgQIECBAgAABAgTKLCAALHP3zZ0AAQIECBAgQIAAAQIECBAgQKDnBQSAPd9iEyRAgAABAgQIECBAgAABAgQIECizgACwzN03dwIECBAgQIAAAQIECBAgQIAAgZ4XEAD2fItNkAABAgQIECBAgAABAgQIECBAoMwCAsAyd9/cCRAgQIAAAQIECBAgQIAAAQIEel5AANjzLTZBAgQIECBAgAABAgQIECBAgACBMgsIAMvcfXMnQIAAAQIECBAgQIAAAQIECBDoeQEBYM+32AQJECBAgAABAgQIECBAgAABAgTKLCAALHP3zZ0AAQIECBAgQIAAAQIECBAgQKDnBQSAPd9iEyRAgAABAgQIECBAgAABAgQIECizgACwzN03dwIECBAgQIAAAQIECBAgQIAAgZ4XEAD2fItNkAABAgQIECBAgAABAgQIECBAoMwCAsAyd9/cCRAgQIAAAQIECBAgQIAAAQIEel5AANjzLTZBAgQIECBAgAABAgQIECBAgACBMgsIAMvcfXMnQIAAAQIECBAgQIAAAQIECBDoeQEBYM+32AQJECBAgAABAgQIECBAgAABAgTKLCAALHP3zZ0AAQIECBAgQIAAAQIECBAgQKDnBQSAPd9iEyRAgAABAgQIECBAgAABAgQIECizgACwzN03dwIECBAgQIAAAQIECBAgQIAAgZ4XEAD2fItNkAABAgQIECBAgAABAgQIECBAoMwCAsAyd9/cCRAgQIAAAQIECBAgQIAAAQIEel5AANjzLTZBAgQIECBAgAABAgQIECBAgACBMgv0J0k7abfb0RjEVGs0qArNXKDamst8zDwGrCTNpG8wjn8HqFYrSRJDqaHMSiX8L4ZLPIf+ZHBoMAbRpNVqJ41GI4pa0yJj2FVbrVY05ymVdiuJ5NmfJH3hFDCCS3rel+4DMVzS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AQIECBAgQCAOAQFgHH1SJQECBAgQIECAAAECBAgQIECAAIGuBASAXbFZiQABAgQIECBAgAABAgQIECBAgEAcAgLAOPqkSgIECBAgQIAAAQIECBAgQIAAAQJdCQgAu2KzEgECBAgQIECAAAECBAgQIECAAIE4BASAcfRJlQQIECBAgAABAgQIECBAgAABAgS6EhAAdsVmJQIECBAgQIAAAQIECBAgQIAAAQJxCAgA4+iTKgkQIECAAAECBAgQIECAAAECBAh0JSAA7IrNSgQIECBAgAABAgQIECBAgAABAgTiEBAAxtEnVRIgQIAAAQIECBAgQIAAAQIECBDoSkAA2BWblQgQIECAAAECBAgQIECAAAECBAjEISAAjKNPqiRAgAABAgQIECBAgAABAgQIECDQlYAAsCs2KxEgQIAAAQIECBAgQIAAAQIECBCIQ0AAGEefVEmAAAECBAgQIECAAAECBAgQIECgKwEBYFdsViJAgAABAgQIECBAgAABAgQIECAQh4AAMI4+qZIAAQIECBAgQIAAAQIECBAgQIBAVwICwK7YrESAAAECBAgQIECAAAECBAgQIEAgDgEBYBx9UiUBAgQIECBAgAABAgQIECBAgACBrgQEgF2xWYkAAQIECBAgQIAAAQIECBAgQIBAHAICwDj6pEoCBAgQIECAAAECBAgQIECAAAECXQkIALtisxIBAgQIECBAgAABAgQIECBAgACBOAQEgHH0SZUECBAgQIAAAQIECBAgQIAAAQIEuhIQAHbFZiUCBAgQIECAAAECBAgQIECAAAECcQgIAOPokyoJECBAgAABAgQIECBAgAABAgQIdCUgAOyKzUoECBAgQIAAAQIECBAgQIAAAQIE4hAQAMbRJ1USIECAAAECBAgQIECAAAECBAgQ6EpAANgVm5UIECBAgAABAgQIECBAgAABAgQIxCEgAIyjT6okQIAAAQIECBAgQIAAAQIECBAg0JWAALArNisRIECAAAECBAgQIECAAAECBAgQiENAABhHn1RJgAABAgQIECBAgAABAgQIECBAoCsBAWBXbFYiQIAAAQIECBAgQIAAAQIECBAgEIeAADCOPqmSAAECBAgQIECAAAECBAgQIECAQFcCAsCu2KxEgAABAgQIECBAgAABAgQIECBAIA4BAWAcfVIlAQIECBAgQIAAAQIECBAgQIAAga4EBIBdsVmJAAECBAgQIECAAAECBAgQIECAQBwCAsA4+qRKAgQIECBAgAABAgQIECBAgAABAl0JCAC7YrMSAQIECBAgQIAAAQIECBAgQIAAgTgEBIBx9EmVBAgQIECAAAECBAgQIECAAAECBLoS6E/XajQaXa28FitV1mKj3WyzEkelcVTZTQPWbp1Wq5k894Yb166ADrbcmJ1KZkYPdbDG2i06W59L6rX62hWw7C23k0qlb9lLr+WCmzevD7XGcRT41P/xH9aSatnbPnT0RPKxT/3lspdfywWfPHEiefL4ibUsYVnbHm61kk3hK4bL5NhE0qrG8W+rn//w/x4DafLksRPJv/vjT0RRa1pku90ufq3htL/SiOPY/+u/8obkWVdfWXzTUOGHPvVXUdSZFtluN6OpNYZCX/TP/nny4p/9FzGUmtz93z+VHHvi0Shq7YvgcJpCVkOdzYjylBian/4sjeLnacCMZDc91/Y4zlLPlesKAQIECBAgQIAAAQIECBAgQIAAAQKdCAgAO9GyLAECBAgQIECAAAECBAgQIECAAIHIBASAkTVMuQQIECBAgAABAgQIECBAgAABAgQ6ERAAdqJlWQIECBAgQIAAAQIECBAgQIAAAQKRCQgAI2uYcgkQIECAAAECBAgQIECAAAECBAh0IiAA7ETLsgQIECBAgAABAgQIECBAgAABAgQiExAARtYw5RIgQIAAAQIECBAgQIAAAQIECBDoREAA2ImWZQkQIECAAAECBAgQIECAAAECBAhEJiAAjKxhyiVAgAABAgQIECDw/7N37zGWnnd9wJ/3nNmZ2Zmdvcyu9+J48Q2HQNw4xiVquKSQC5A2LgUqLmpTKlrRqKJq+xcViD+LkJCqoqK2okiUXrhKNIIkDSQBUUNBgSQkzsWxY2wnMd14fYnt9V5m55y37zvLbBYj1ec9fmbn95t8TjKe2d3nfc73fH7vuX1n1iZAgAABAgQIEBgioAAcomUtAQIECBAgQIAAAQIECBAgQIAAgWQCCsBkAxOXAAECBAgQIECAAAECBAgQIECAwBABBeAQLWsJECBAgAABAgQIECBAgAABAgQIJBNQACYbmLgECBAgQIAAAQIECBAgQIAAAQIEhggoAIdoWUuAAAECBAgQIECAAAECBAgQIEAgmYACMNnAxCVAgAABAgQIECBAgAABAgQIECAwREABOETLWgIECBAgQIAAAQIECBAgQIAAAQLJBBSAyQYmLgECBAgQIECAAAECBAgQIECAAIEhAgrAIVrWEiBAgAABAgQIECBAgAABAgQIEEgmoABMNjBxCRAgQIAAAQIECBAgQIAAAQIECAwRUAAO0bKWAAECBAgQIECAAAECBAgQIECAQDIBBWCygYlLgAABAgQIECBAgAABAgQIECBAYIiAAnCIlrUECBAgQIAAAQIECBAgQIAAAQIEkgkoAJMNTFwCBAgQIECAAAECBAgQIECAAAECQwQUgEO0rCVAgAABAgQIECBAgAABAgQIECCQTEABmGxg4hIgQIAAAQIECBAgQIAAAQIECBAYIqAAHKJlLQECBAgQIECAAAECBAgQIECAAIFkAgrAZAMTlwABAgQIECBAgAABAgQIECBAgMAQAQXgEC1rCRAgQIAAAQIECBAgQIAAAQIECCQTUAAmG5i4BAgQIECAAAECBAgQIECAAAECBIYIKACHaFlLgAABAgQIECBAgAABAgQIECBAIJmAAjDZwMQlQIAAAQIECBAgQIAAAQIECBAgMERAAThEy1oCBAgQIECAAAECBAgQIECAAAECyQQUgMkGJi4BAgQIECBAgAABAgQIECBAgACBIQIKwCFa1hIgQIAAAQIECBAgQIAAAQIECBBIJqAATDYwcQkQIECAAAECBAgQIECAAAECBAgMEVAADtGylgABAgQIECBAgAABAgQIECBAgEAyAQVgsoGJS4AAAQIECBAgQIAAAQIECBAgQGCIgAJwiJa1BAgQIECAAAECBAgQIECAAAECBJIJKACTDUxcAgQIECBAgAABAgQIECBAgAABAkMEFIBDtKwlQIAAAQIECBAgQIAAAQIECBAgkExAAZhsYOISIECAAAECBAgQIECAAAECBAgQGCKwUEpbptPpkGOsnUGgaZoZVlmyNwWacvfr35jipj39hcfKx//o8RRZ04Sctt3DaveR4LJ47pky6p4DMlwWNl7IELPcsn6g/Ng/+t4UWX/1f/12+ZV3PxI+68bScrmwtBQ+Zx/wXf/5p8tX3nw6RdZ7vuVtKXK2o1FplvbnyNr2r6fjP6a+/a1vKm9/85tSmE4n5zrSzRRZS5Pn/VRTcrxPWVw9XFbWbwo//+WDp8pkM/59v4d8YaMtz17Kca4eWc5h2nT3/Sx9Si/aJnif0mfMkLO/T2XJ2WftX6P4CcArEv5JgAABAgQIECBAgAABAgQIECBAYE8KKAD35FjdKAIECBAgQIAAAQIECBAgQIAAAQJXBBSAzgQCBAgQIECAAAECBAgQIECAAAECe1hAAbiHh+umESBAgAABAgQIECBAgAABAgQIEFAAOgcIECBAgAABAgQIECBAgAABAgQI7GEBBeAeHq6bRoAAAQIECBAgQIAAAQIECBAgQEAB6BwgQIAAAQIECBAgQIAAAQIECBAgsIcFFIB7eLhuGgECBAgQIECAAAECBAgQIECAAAEFoHOAAAECBAgQIECAAAECBAgQIECAwB4WUADu4eG6aQQIECBAgAABAgQIECBAgAABAgQUgM4BAgQIECBAgAABAgQIECBAgAABAntYQAG4h4frphEgQIAAAQIECBAgQIAAAQIECBBQADoHCBAgQIAAAQIECBAgQIAAAQIECOxhAQXgHh6um0aAAAECBAgQIECAAAECBAgQIEBAAegcIECAAAECBAgQIECAAAECBAgQILCHBRSAe3i4bhoBAgQIECBAgAABAgQIECBAgAABBaBzgAABAgQIECBAgAABAgQIECBAgMAeFlAA7uHhumkECBAgQIAAAQIECBAgQIAAAQIEFIDOAQIECBAgQIAAAQIECBAgQIAAAQJ7WEABuIeH66YRIECAAAECBAgQIECAAAECBAgQUAA6BwgQIECAAAECBAgQIECAAAECBAjsYQEF4B4erptGgAABAgQIECBAgAABAgQIECBAQAHoHCBAgAABAgQIECBAgAABAgQIECCwhwUUgHt4uG4aAQIECBAgQIAAAQIECBAgQIAAAQWgc4AAAQIECBAgQIAAAQIECBAgQIDAHhZQAO7h4bppBAgQIECAAAECBAgQIECAAAECBBSAzgECBAgQIECAAAECBAgQIECAAAECe1hAAbiHh+umESBAgAABAgQIECBAgAABAgQIEFAAOgcIECBAgAABAgQIECBAgAABAgQI7GEBBeAeHq6bRoAAAQIECBAgQIAAAQIECBAgQEAB6BwgQIAAAQIECBAgQIAAAQIECBAgsIcFFIB7eLhuGgECBAgQIECAAAECBAgQIECAAAEFoHOAAAECBAgQIECAAAECBAgQIECAwB4WUADu4eG6aQQIECBAgAABAgQIECBAgAABAgQUgM4BAgQIECBAgAABAgQIECBAgAABAntYQAG4h4frphEgQIAAAQIECBAgQIAAAQIECBBQADoHCBAgQIAAAQIECBAgQIAAAQIECOxhAQXgHh6um0aAAAECBAgQIECAAAECBAgQIEBAAegcIECAAAECBAgQIECAAAECBAgQILCHBRSAe3i4bhoBAgQIECBAgAABAgQIECBAgAABBaBzgAABAgQIECBAgAABAgQIECBAgMAeFljob1vbtnv4Ju7eTWuaZveu3DXvnkB3f2rHObr1xaXFcnz9yO5ZDbjmJzan5eKFiwOO2J2l08mktNPp7lz5wGu91ExLU3I8/u9bXRt463Zn+agZl+WF/btz5QOv9Zbbbi9f93X3DDzq+i9/4vkXyjPn49/3e5n7H3iwPHH2qeuPNMc1Tkc5nqfapsuZ42GqlGlbmunmHNO4voeceeLJ8pFPP3h9r3TOa5tOLnbvUyZzHn19D2uSnKd9zM3utUqGy/59i+XwsePhoy6vrpY2yQlw5OjxMtm4EN60D7i2lONONRp3lUqOqJ1q9z41QdgtzjSmW6z9KZvi0rzmtfe0X/sd70gRtj8H2iSd2rh7wTpSAKY4r3Yi5KQ9vxPbVt9zeeP5sv7co9X33YkN/+CP/7R87JPx37BcvHihXN68vBME1fdcSPQY9aHf+63qt38nNlzq3qycXD+6E1tX33OjO0/7j+iXd//2+8offvBPosfcyveb7/1A+eKzz6XIevDoeoqcV0LmKCvLRldUX4r//H+5e0Hdf2S4TKfjrgDM8eL/0JGDGUi7nnpavnj++RRZb7vzr5dv+Nt/P3zWSfft1MvdR4bL4uWNMk7yjeqykMO0n/vFydbPVYU/BaZd+beZoADs+/Qmyw+pZcnZnZ2ffN8vlCSvqMLflwQkQIAAAQIECBAgQIAAAQIECBAgEFJAARhyLEIRIECAAAECBAgQIECAAAECBAgQqCOgAKzjaBcCBAgQIECAAAECBAgQIECAAAECIQUUgCHHIhQBAgQIECBAgAABAgQIECBAgACBOgIKwDqOdiFAgAABAgQIECBAgAABAgQIECAQUkABGHIsQhEgQIAAAQIECBAgQIAAAQIECBCoI6AArONoFwIECBAgQIAAAQIECBAgQIAAAQIhBRSAIcciFAECBAgQIECAAAECBAgQIECAAIE6AgrAOo52IUCAAAECBAgQIECAAAECBAgQIBBSQAEYcixCESBAgAABAgQIECBAgAABAgQIEKgjoACs42gXAgQIECBAgAABAgQIECBAgAABAiEFFIAhxyIUAQIECBAgQIAAAQIECBAgQIAAgToCCsA6jnYhQIAAAQIECBAgQIAAAQIECBAgEFJAARhyLEIRIECAAAECBAgQIECAAAECBAgQqCOgAKzjaBcCBAgQIECAAAECBAgQIECAAAECIQUUgCHHIhQBAgQIECBAgAABAgQIECBAgACBOgIKwDqOdiFAgAABAgQIECBAgAABAgQIECAQUkABGHIsQhEgQIAAAQIECBAgQIAAAQIECBCoI6AArONoFwIECBAgQIAAAQIECBAgQIAAAQIhBRSAIcciFAECBAgQIECAAAECBAgQIECAAIE6AgrAOo52IUCAAAECBAgQIECAAAECBAgQIBBSQAEYcixCESBAgAABAgQIECBAgAABAgQIEKgjoACs42gXAgQIECBAgAABAgQIECBAgAABAiEFFIAhxyIUAQIECBAgQIAAAQIECBAgQIAAgToCCsA6jnYhQIAAAQIECBAgQIAAAQIECBAgEFJAARhyLEIRIECAAAECBAgQIECAAAECBAgQqCOgAKzjaBcCBAgQIECAAAECBAgQIECAAAECIQUUgCHHIhQBAgQIECBAgAABAgQIECBAgACBOgIKwDqOdiFAgAABAgQIECBAgAABAgQIECAQUkABGHIsQhEgQIAAAQIECBAgQIAAAQIECBCoI6AArONoFwIECBAgQIAAAQIECBAgQIAAAQIhBRSAIcciFAECBAgQIECAAAECBAgQIECAAIE6AgrAOo52IUCAAAECBAgQIECAAAECBAgQIBBSQAEYcixCESBAgAABAgQIECBAgAABAgQIEKgjoACs42gXAgQIECBAgAABAgQIECBAgAABAiEFFIAhxyIUAQIECBAgQIAAAQIECBAgQIAAgToCCsA6jnYhQIAAAQIECBAgQIAAAQIECBAgEFJAARhyLEIRIECAAAECBAgQIECAAAECBAgQqCOgAKzjaBcCBAgQIECAAAECBAgQIECAAAECIQUUgCHHIhQBAgQIECBAgAABAgQIECBAgACBOgIKwDqOdiFAgAABAgQIECBAgAABAgQIECAQUmCh7WO1W/8MGfDFoZokUdtmWqYvDu/XL0ugaZqXdfz1Ong0aso3337D9bq6l3U9T3z2+fIn//tPX9Ye1+vg19x+S/mWb3j99bq6ua/nN977vvKxTz0w9/HX88Af+oHvL2urq9fzKue+ruXF8dzHXs8DF0Ztubhx/npe5dzXNZlOS/8R/XLH7beVlZWV6DG38t133x+W8889myLra776q1PkXF4Yl686cSRF1n37FsrS0mL4rJuTzXK5+8hwaTa7n1VI8tr/P/7GezOQloXFpXL3N35biqyHbnhF9zwV//V/f4rGT3ll5NNmVNruvUqGSxv/JcpVxmmSsFvnapbuJ8ljf38SZCHtsy5cCZxItw+c4NJ2ZwHVuoMajXL8wGpfUn/jrcfq3vgd2u3DTz5SfvXjH9+h3etu+8a/+U3lO/7ed9fddAd2+9RDD6UpAH/ge7+7nDye41wtib6lcilJAdh2b1f6j+iX2269udzelYAZLgdX95ez8Um3KF/9yldmIC2H9i+Wt33NV6TIunL4cDlwLP5j6uTypbLZfWS4jC53j1JJSoB/+6vvzEBaVvYtlb/2N96YIuu0jMtmkjdU/TNqhsukdO+nkjxPTRN8k3J75m2SArDP22Rqq7aBA3/ue580ly5qjkYljaigBAgQIECAAAECBAgQIECAAAECBGIJKABjzUMaAgQIECBAgAABAgQIECBAgAABAlUFFIBVOW1GgAABAgQIECBAgAABAgQIECBAIJaAAjDWPKQhQIAAAQIECBAgQIAAAQIECBAgUFVAAViV02YECBAgQIAAAQIECBAgQIAAAQIEYgkoAGPNQxoCBAgQIECAAAECBAgQIECAAAECVQUUgFU5bUaAAAECBAgQIECAAAECBAgQIEAgloACMNY8pCFAgAABAgQIECBAgAABAgQIECBQVUABWJXTZgQIECBAgAABAgQIECBAgAABAgRiCSgAY81DGgIECBAgQIAAAQIECBAgQIAAAQJVBRSAVTltRoAAAQIECBAgQIAAAQIECBAgQCCWgAIw1jykIUCAAAECBAgQIECAAAECBAgQIFBVQAFYldNmBAgQIECAAAECBAgQIECAAAECBGIJKABjzUMaAgQIECBAgAABAgQIECBAgAABAlUFFIBVOW1GgAABAgQIECBAgAABAgQIECBAIJaAAjDWPKQhQIAAAQIECBAgQIAAAQIECBAgUFVAAViV02YECBAgQIAAAQIECBAgQIAAAQIEYgkoAGPNQxoCBAgQIECAAAECBAgQIECAAAECVQUUgFU5bUaAAAECBAgQIECAAAECBAgQIEAgloACMNY8pCFAgAABAgQIECBAgAABAgQIECBQVUABWJXTZgQIECBAgAABAgQIECBAgAABAgRiCSgAY81DGgIECBAgQIAAAQIECBAgQIAAAQJVBRSAVTltRoAAAQIECBAgQIAAAQIECBAgQCCWgAIw1jykIUCAAAECBAgQIECAAAECBAgQIFBVQAFYldNmBAgQIECAAAECBAgQIECAAAECBGIJKABjzUMaAgQIECBAgAABAgQIECBAgAABAlUFFIBVOW1GgAABAgQIECBAgAABAgQIECBAIJaAAjDWPKQhQIAAAQIECBAgQIAAAQIECBAgUFVAAViV02YECBAgQIAAAQIECBAgQIAAAQIEYgkoAGPNQxoCBAgQIECAAAECBAgQIECAAAECVQUUgFU5bUaAAAECBAgQIECAAAECBAgQIEAgloACMNY8pCFAgAABAgQIECBAgAABAgQIECBQVUABWJXTZgQIECBAgAABAgQIECBAgAABAgRiCSgAY81DGgIECBAgQIAAAQIECBAgQIAAAQJVBRSAVTltRoAAAQIECBAgQIAAAQIECBAgQCCWgAIw1jykIUCAAAECBAgQIECAAAECBAgQIFBVQAFYldNmBAgQIECAAAECBAgQIECAAAECBGIJKABjzUMaAgQIECBAgAABAgQIECBAgAABAlUFFIBVOW1GgAABAgQIECBAgAABAgQIECBAIJaAAjDWPKQhQIAAAQIECBAgQIAAAQIECBAgUFVAAViV02YECBAgQIAAAQIECBAgQIAAAQIEYgks9HGm02msVNJcN4Gmaa7bdb3cK8pynk5LU1aX973cm3tdjr/zK28pP/qOt1+X63q5V3LihrXy7P0fernb7Pjx7/jut5Xv/657d/x6alzB+uFDpW3bGlvt+B5td79KcWk6zybHc2rTNmWUwPUD739/+fCHPppi/D/yr364HDhwIEXWo0cOpcg5Km05MNrMkXU0LpME31pvu9d+oyZB0G7q5y5cKJPNSYr5f8/f/TspcpaFpXK5zfE6tX82nbY5nlNzDL9L2b3uy/HKr4s67ZPmSNumOU9zvJ7u35+keY+S5L1U/xjV35u2CsD+F1kuOR4Cuvd/WUAT5UzzINCZjkc5XlgfWFkut52+McVZ0L9Z2Tz3XPisp297Zbn16PHwOfuACyOPVNUH1T9JZWHtcyZ4Un36qafLI3/2SPVR7cSGb/8H31dOnTq1E1tX37PduFh9z53YsJ1OysaF53di6+p79q9TsnyzsknyQDXpfkjh8iRHAXjyeI7n/uloX3kyyfwzlQBZnvqzvJ+68gCd4EVK9WeSnd4wzwvVLOdqlpzbZ1aOlmI7rc8ECBAgQIAAAQIECBAgQIAAAQIECAwSUAAO4rKYAAECBAgQIECAAAECBAgQIECAQC4BBWCueUlLgAABAgQIECBAgAABAgQIECBAYJCAAnAQl8UECBAgQIAAAQIECBAgQIAAAQIEcgkoAHPNS1oCBAgQIECAAAECBAgQIECAAAECgwQUgIO4LCZAgAABAgQIECBAgAABAgQIECCQS0ABmGte0hIgQIAAAQIECBAgQIAAAQIECBAYJKAAHMRlMQECBAgQIECAAAECBAgQIECAAIFcAgrAXPOSlgABAgQIECBAgAABAgQIECBAgMAgAQXgIC6LCRAgQIAAAQIECBAgQIAAAQIECOQSUADmmpe0BAgQIECAAAECBAgQIECAAAECBAYJKAAHcVlMgAABAgQIECBAgAABAgQIECBAIJeAAjDXvKQlQIAAAQIECBAgQIAAAQIECBAgMEhAATiIy2ICBAgQIECAAAECBAgQIECAAAECuQQUgLnmJS0BAgQIECBAgAABAgQIECBAgACBQQIKwEFcFhMgQIAAAQIECBAgQIAAAQIECBDIJaAAzDUvaQkQIECAAAECBAgQIECAAAECBAgMElAADuKymAABAgQIECBAgAABAgQIECBAgEAuAQVgrnlJS4AAAQIECBAgQIAAAQIECBAgQGCQgAJwEJfFBAgQIECAAAECBAgQIECAAAECBHIJKABzzUtaAgQIECBAgAABAgQIECBAgAABAoMEFICDuCwmQIAAAQIECBAgQIAAAQIECBAgkEtAAZhrXtISIECAAAECBAgQIECAAAECBAgQGCSgABzEZTEBAgQIECBAgAABAgQIECBAgACBXAIKwFzzkpYAAQIECBAgQIAAAQIECBAgQIDAIAEF4CAuiwkQIECAAAECBAgQIECAAAECBAjkElAA5pqXtAQIECBAgAABAgQIECBAgAABAgQGCSgAB3FZTIAAAQIECBAgQIAAAQIECBAgQCCXgAIw17ykJUCAAAECBAgQIECAAAECBAgQIDBIQAE4iMtiAgQIECBAgAABAgQIECBAgAABArkEFIC55iUtAQIECBAgQIAAAQIECBAgQIAAgUECCsBBXBYTIECAAAECBAgQIECAAAECBAgQyCWgAMw1L2kJECBAgAABAgQIECBAgAABAgQIDBJQAA7ispgAAQIECBAgQIAAAQIECBAgQIBALgEFYK55SUuAAAECBAgQIECAAAECBAgQIEBgkIACcBCXxQQIECBAgAABAgQIECBAgAABAgRyCSgAc81LWgIECBAgQIAAAQIECBAgQIAAAQKDBBSAg7gsJkCAAAECBAgQIECAAAECBAgQIJBLQAGYa17SEiBAgAABAgQIECBAgAABAgQIEBgkoAAcxGUxAQIECBAgQIAAAQIECBAgQIAAgVwCCsBc85KWAAECBAgQIECAAAECBAgQIECAwCCBhVLacnlzc9BBu7m4aZrdvPo9d929ZxbTpsnRV0/bUi4lOVMmo4WyuHQgRdrJZLP0H9EvbX8C9B8JLucvnC9tmyPr5NzzCURLGY/HZXl5OUXWtnSPqQkeV7/zLW8q3/nGb05h+tSzz5XPP/RQiqz7L1xIkbN/TN24eDFF1n1LS2VpJf79v903Ku3COIXpJz7xifLFp59JkfU//I93pci5fOBg+fYf/JEUWftXKDlepXRPpylEe9AsonlmvzX6JKz96/5pO0lxtmZ5j5Il5/bQczQq22l9JkCAAAECBAgQIECAAAECBAgQIEBgkIACcBCXxQQIECBAgAABAgQIECBAgAABAgRyCSgAc81LWgIECBAgQIAAAQIECBAgQIAAAQKDBBSAg7gsJkCAAAECBAgQIECAAAECBAgQIJBLQAGYa17SEiBAgAABAgQIECBAgAABAgQIEBgkoAAcxGUxAQIECBAgQIAAAQIECBAgQIAAgVwCCsBc85KWAAECBAgQIECAAAECBAgQIECAwCABBeAgLosJECBAgAABAgQIECBAgAABAgQI5BJQAOaal7QECBAgQIAAAQIECBAgQIAAAQIEBgkoAAdxWUyAAAECBAgQIECAAAECBAgQIEAgl4ACMNe8pCVAgAABAgQIECBAgAABAgQIECAwSEABOIjLYgIECBAgQIAAAQIECBAgQIAAAQK5BBSAueYlLQECBAgQIECAAAECBAgQIECAAIFBAgrAQVwWEyBAgAABAgQIECBAgAABAgQIEMgloADMNS9pCRAgQIAAAQIECBAgQIAAAQIECAwSUAAO4rKYAAECBAgQIECAAAECBAgQIECAQC4BBWCueUlLgAABAgQIECBAgAABAgQIECBAYJCAAnAQl8UECBAgQIAAAQIECBAgQIAAAQIEcgkoAHPNS1oCBAgQIECAAAECBAgQIECAAAECgwQUgIO4LCZAgAABAgQIECBAgAABAgQIECCQS0ABmGte0hIgQIAAAQIECBAgQIAAAQIECBAYJKAAHMRlMQECBAgQIECAAAECBAgQIECAAIFcAgrAXPOSlgABAgQIECBAgAABAgQIECBAgMAgAQXgIC6LCRAgQIAAAQIECBAgQIAAAQIECOQSUADmmpe0BAgQIECAAAECBAgQIECAAAECBAYJKAAHcVlMgAABAgQIECBAgAABAgQIECBAIJeAAjDXvKQlQIAAAQIECBAgQIAAAQIECBAgMEhAATiIy2ICBAgQIECAAAECBAgQIECAAAECuQQUgLnmJS0BAgQIECBAgAABAgQIECBAgACBQQIKwEFcFhMgQIAAAQIECBAgQIAAAQIECBDIJaAAzDUvaQkQIECAAAECBAgQIECAAAECBAgMElAADuKymAABAgQIECBAgAABAgQIECBAgEAuAQVgrnlJS4AAAQIECBAgQIAAAQIECBAgQGCQgAJwEJfFBAgQIECAAAECBAgQIECAAAECBHIJKABzzUtaAgQIECBAgAABAgQIECBAgAABAoMEFICDuCwmQIAAAQIECBAgQIAAAQIECBAgkEtAAZhrXtISIECAAAECBAgQIECAAAECBAgQGCSgABzEZTEBAgQIECBAgAABAgQIECBAgACBXAIKwFzzkpYAAQIECBAgQIAAAQIECBAgQIDAIAEF4CAuiwkQIECAAAECBAgQIECAAAECBAjkElAA5pqXtAQIECBAgAABAgQIECBAgAABAgQGCSy0bSmTyWTQQbu5uGma3bz6ma87S86Zb1CAhVlMNy5Nyt3f+c8CiL10hG+659Xl3/3rf/rSCwOs+MVf+uXyW7/9vgBJ/v8RJt2D6rR/YE1w+U///mfK+pEjCZJ2ERf3p8h56fyF8n8fejRF1pXlpbLafUS/bIzHZbP7yHBZO3iojEY5Xqcsra5kIC2Tzc3y3NmzKbKWyxvl8qUL4bO+5z0fKO99/++Ez9kH3H/qljJeznGufsc//4kUpn3IaTtNkzVD0P5l33Sa47VfW/qcObJOp87TDOf/TmRsuztV/5Hh0nb3/SRRu7t+W/wEYIazSkYCBAgQIECAAAECBAgQIECAAAECcwooAOeEcxgBAgQIECBAgAABAgQIECBAgACBDAIKwAxTkpEAAQIECBAgQIAAAQIECBAgQIDAnAIKwDnhHEaAAAECBAgQIECAAAECBAgQIEAgg4ACMMOUZCRAgAABAgQIECBAgAABAgQIECAwp4ACcE44hxEgQIAAAQIECBAgQIAAAQIECBDIIKAAzDAlGQkQIECAAAECBAgQIECAAAECBAjMKaAAnBPOYQQIECBAgAABAgQIECBAgAABAgQyCCgAM0xJRgIECBAgQIAAAQIECBAgQIAAAQJzCigA54RzGAECBAgQIECAAAECBAgQIECAAIEMAgrADFOSkQABAgQIECBAgAABAgQIECBAgMCcAgrAOeEcRoAAAQIECBAgQIAAAQIECBAgQCCDgAIww5RkJECAAAECBAgQIECAAAECBAgQIDCngAJwTjiHESBAgAABAgQIECBAgAABAgQIEMggoADMMCUZCRAgQIAAAQIECBAgQIAAAQIECMwpoACcE85hBAgQIECAADDxcQQAAEAASURBVAECBAgQIECAAAECBDIIKAAzTElGAgQIECBAgAABAgQIECBAgAABAnMKKADnhHMYAQIECBAgQIAAAQIECBAgQIAAgQwCCsAMU5KRAAECBAgQIECAAAECBAgQIECAwJwCCsA54RxGgAABAgQIECBAgAABAgQIECBAIIOAAjDDlGQkQIAAAQIECBAgQIAAAQIECBAgMKeAAnBOOIcRIECAAAECBAgQIECAAAECBAgQyCCgAMwwJRkJECBAgAABAgQIECBAgAABAgQIzCmgAJwTzmEECBAgQIAAAQIECBAgQIAAAQIEMggoADNMSUYCBAgQIECAAAECBAgQIECAAAECcwooAOeEcxgBAgQIECBAgAABAgQIECBAgACBDAIKwAxTkpEAAQIECBAgQIAAAQIECBAgQIDAnAIKwDnhHEaAAAECBAgQIECAAAECBAgQIEAgg4ACMMOUZCRAgAABAgQIECBAgAABAgQIECAwp4ACcE44hxEgQIAAAQIECBAgQIAAAQIECBDIIKAAzDAlGQkQIECAAAECBAgQIECAAAECBAjMKaAAnBPOYQQIECBAgAABAgQIECBAgAABAgQyCCgAM0xJRgIECBAgQIAAAQIECBAgQIAAAQJzCigA54RzGAECBAgQIECAAAECBAgQIECAAIEMAgrADFOSkQABAgQIECBAgAABAgQIECBAgMCcAgrAOeEcRoAAAQIECBAgQIAAAQIECBAgQCCDgAIww5RkJECAAAECBAgQIECAAAECBAgQIDCngAJwTjiHESBAgAABAgQIECBAgAABAgQIEMggoADMMCUZCRAgQIAAAQIECBAgQIAAAQIECMwpoACcE85hBAgQIECAAAECBAgQIECAAAECBDIIKAAzTElGAgQIECBAgAABAgQIECBAgAABAnMKLMx5nMNeQqBt29I0zUus8sdDBHrTDJc+5YHDRzNELZtlXD754J+lyNo243LLzTeHzzrpztMs5+p4PA7veTVgksfTZjwq+1aWr8aO/MXC4mJplhYjR9zKNh6NStt9ZLiMFsZllORc7V6kZCAtzagp4841w6Vtx6Wd7Asf9dCRI+UVp0+Hz9kHPL96tEzG8R+n+qxZnvu3spYcr6n7rBkuV96iZDHNkjPD5GXcUQGn6o7wNnfe9bXtq9789h3ZfCc2VarthGqOPTM9BuR4W1XKFx79dPmj3/xvKU6AH/8X7yg/+H3fFT9rO+kyTuPn7BK2Tf89oBxna9vkMO0Hn+VNYD/5DNPvKvVetacNfxk1fVGZQTU85dWA7XRSJufPXf115C8mm5OyubEZOeJWto3JpGxMcjym/vc/OVMef/ZSeNM+4Gb3jcoslyzPU71nlqxZ3qNm8cxyX/pSzhyvU67cp76UOupX/Xk6neQxjer44lyP/P6vlBzfUn9xcr8mQIAAAQIECBAgQIAAAQIECBAgQGAmAQXgTEwWESBAgAABAgQIECBAgAABAgQIEMgpoADMOTepCRAgQIAAAQIECBAgQIAAAQIECMwkoACcickiAgQIECBAgAABAgQIECBAgAABAjkFFIA55yY1AQIECBAgQIAAAQIECBAgQIAAgZkEFIAzMVlEgAABAgQIECBAgAABAgQIECBAIKeAAjDn3KQmQIAAAQIECBAgQIAAAQIECBAgMJOAAnAmJosIECBAgAABAgQIECBAgAABAgQI5BRQAOacm9QECBAgQIAAAQIECBAgQIAAAQIEZhJQAM7EZBEBAgQIECBAgAABAgQIECBAgACBnAIKwJxzk5oAAQIECBAgQIAAAQIECBAgQIDATAIKwJmYLCJAgAABAgQIECBAgAABAgQIECCQU0ABmHNuUhMgQIAAAQIECBAgQIAAAQIECBCYSUABOBOTRQQIECBAgAABAgQIECBAgAABAgRyCigAc85NagIECBAgQIAAAQIECBAgQIAAAQIzCSgAZ2KyiAABAgQIECBAgAABAgQIECBAgEBOAQVgzrlJTYAAAQIECBAgQIAAAQIECBAgQGAmAQXgTEwWESBAgAABAgQIECBAgAABAgQIEMgpoADMOTepCRAgQIAAAQIECBAgQIAAAQIECMwkoACcickiAgQIECBAgAABAgQIECBAgAABAjkFFIA55yY1AQIECBAgQIAAAQIECBAgQIAAgZkEFIAzMVlEgAABAgQIECBAgAABAgQIECBAIKeAAjDn3KQmQIAAAQIECBAgQIAAAQIECBAgMJOAAnAmJosIECBAgAABAgQIECBAgAABAgQI5BRQAOacm9QECBAgQIAAAQIECBAgQIAAAQIEZhJQAM7EZBEBAgQIECBAgAABAgQIECBAgACBnAIKwJxzk5oAAQIECBAgQIAAAQIECBAgQIDATAIKwJmYLCJAgAABAgQIECBAgAABAgQIECCQU0ABmHNuUhMgQIAAAQIECBAgQIAAAQIECBCYSUABOBOTRQQIECBAgAABAgQIECBAgAABAgRyCigAc85NagIECBAgQIAAAQIECBAgQIAAAQIzCSgAZ2KyiAABAgQIECBAgAABAgQIECBAgEBOAQVgzrlJTYAAAQIECBAgQIAAAQIECBAgQGAmAQXgTEwWESBAgAABAgQIECBAgAABAgQIEMgpoADMOTepCRAgQIAAAQIECBAgQIAAAQIECMwkoACcickiAgQIECBAgAABAgQIECBAgAABAjkFFIA55yY1AQIECBAgQIAAAQIECBAgQIAAgZkEFIAzMVlEgAABAgQIECBAgAABAgQIECBAIKeAAjDn3KQmQIAAAQIECBAgQIAAAQIECBAgMJOAAnAmJosIECBAgAABAgQIECBAgAABAgQI5BRQAOacm9QECBAgQIAAAQIECBAgQIAAAQIEZhJY6Fe1bTvT4giLMmWN4PVSGZqmKf1HhovZ15/S/rXD5bbXfn39jXdgx7PTlfK7n/j8Duy8E1vmeExtR/1TQI77/0Mf+b2dGFT1PU/ccKzc+61vrL7vzmzYnacJnv9znKHXTijJ/X96bebAX3ecWV6nPP7MufLpz54NjHkl2uZoX5mMt94ChM/67KVJmYRPeSWg16n1B5XJNFPW+pPamR2n0yxPVP3tT/LcnyPmVj/lPlX/ftWPf+vZP9edqz7ETuyY5YQdj8c7cfN3ZM820ZNAksfWsnr4WPmar/+2HZlX7U3/fHNafuNDj9Tetvp+benvU0kqiyRvAPshvfNnfrb6rHZiw3vuurPc++1v2Ymt6+/ZTrszNdOL6/oE9XfM8ujfvVXJMvqupG5GOf7CyqNnnyvv+sjD9U+r2jvuXytluftIcGnafvZJnlOTFAAJxp4uYv++L8t7vyzfUOlPgskkS/2f65TNcq5myZml/N0+S3O8otpO6zMBAgQIECBAgAABAgQIECBAgAABAoMEFICDuCwmQIAAAQIECBAgQIAAAQIECBAgkEtAAZhrXtISIECAAAECBAgQIECAAAECBAgQGCSgABzEZTEBAgQIECBAgAABAgQIECBAgACBXAIKwFzzkpYAAQIECBAgQIAAAQIECBAgQIDAIAEF4CAuiwkQIECAAAECBAgQIECAAAECBAjkElAA5pqXtAQIECBAgAABAgQIECBAgAABAgQGCSgAB3FZTIAAAQIECBAgQIAAAQIECBAgQCCXgAIw17ykJUCAAAECBAgQIECAAAECBAgQIDBIQAE4iMtiAgQIECBAgAABAgQIECBAgAABArkEFIC55iUtAQIECBAgQIAAAQIECBAgQIAAgUECCsBBXBYTIECAAAECBAgQIECAAAECBAgQyCWgAMw1L2kJECBAgAABAgQIECBAgAABAgQIDBJQAA7ispgAAQIECBAgQIAAAQIECBAgQIBALgEFYK55SUuAAAECBAgQIECAAAECBAgQIEBgkIACcBCXxQQIECBAgAABAgQIECBAgAABAgRyCSgAc81LWgIECBAgQIAAAQIECBAgQIAAAQKDBBSAg7gsJkCAAAECBAgQIECAAAECBAgQIJBLQAGYa17SEiBAgAABAgQIECBAgAABAgQIEBgkoAAcxGUxAQIECBAgQIAAAQIECBAgQIAAgVwCCsBc85KWAAECBAgQIECAAAECBAgQIECAwCABBeAgLosJECBAgAABAgQIECBAgAABAgQI5BJQAOaal7QECBAgQIAAAQIECBAgQIAAAQIEBgkoAAdxWUyAAAECBAgQIECAAAECBAgQIEAgl4ACMNe8pCVAgAABAgQIECBAgAABAgQIECAwSEABOIjLYgIECBAgQIAAAQIECBAgQIAAAQK5BBSAueYlLQECBAgQIECAAAECBAgQIECAAIFBAgrAQVwWEyBAgAABAgQIECBAgAABAgQIEMgloADMNS9pCRAgQIAAAQIECBAgQIAAAQIECAwSUAAO4rKYAAECBAgQIECAAAECBAgQIECAQC4BBWCueUlLgAABAgQIECBAgAABAgQIECBAYJCAAnAQl8UECBAgQIAAAQIECBAgQIAAAQIEcgkoAHPNS1oCBAgQIECAAAECBAgQIECAAAECgwQUgIO4LCZAgAABAgQIECBAgAABAgQIECCQS0ABmGte0hIgQIAAAQIECBAgQIAAAQIECBAYJKAAHMRlMQECBAgQIECAAAECBAgQIECAAIFcAgrAXPOSlgABAgQIECBAgAABAgQIECBAgMAgAQXgIC6LCRAgQIAAAQIECBAgQIAAAQIECOQSUADmmpe0BAgQIECAAAECBAgQIECAAAECBAYJKAAHcVlMgAABAgQIECBAgAABAgQIECBAIJeAAjDXvKQlQIAAAQIECBAgQIAAAQIECBAgMEhgoV/dtu2ggyx+aYEsptPpZmle+uYEWdEnzZHWPar+KTPpUKcp5p9n+qPNS/UHtUM73nDs8A7tXHfbUXeW/v7776u76Q7tNl5oy6j7iH45fcsd5YZTp6PH3Mr387/w8+Wpp55MkfXRLzybIufy6sHy6td9a4qsT567UNrV9fhZR93L/2mO11Pdu5T4nhLumED/fqqd7tj21TbuUnbvpxME7W5x02S57+soqp2gL9ooR0/R36deFNwvqwgoAKsw5t3kygNAjntX04w76BxZMz1gZXkZ0E++TVAAXvHMcZ6W6STNg9fy8mKKrE135//Cn59JkXW8ry3jBKxHjp8u66V//I9/+dRDD5fHH388ftAu4ccfO5si54HDx8r49DekyDopk9IuLIXP2vTPpUmepq7EzBFWsVL/1O9fT2coK64UgDnO0/pTsmMugf48da7mmlndtP4KcF1PuxEgQIAAAQIECBAgQIAAAQIECBAIJaAADDUOYQgQIECAAAECBAgQIECAAAECBAjUFVAA1vW0GwECBAgQIECAAAECBAgQIECAAIFQAgrAUOMQhgABAgQIECBAgAABAgQIECBAgEBdAQVgXU+7ESBAgAABAgQIECBAgAABAgQIEAgloAAMNQ5hCBAgQIAAAQIECBAgQIAAAQIECNQVUADW9bQbAQIECBAgQIAAAQIECBAgQIAAgVACCsBQ4xCGAAECBAgQIECAAAECBAgQIECAQF0BBWBdT7sRIECAAAECBAgQIECAAAECBAgQCCWgAAw1DmEIECBAgAABAgQIECBAgAABAgQI1BVQANb1tBsBAgQIECBAgAABAgQIECBAgACBUAIKwFDjEIYAAQIECBAgQIAAAQIECBAgQIBAXQEFYF1PuxEgQIAAAQIECBAgQIAAAQIECBAIJaAADDUOYQgQIECAAAECBAgQIECAAAECBAjUFVAA1vW0GwECBAgQIECAAAECBAgQIECAAIFQAgrAUOMQhgABAgQIECBAgAABAgQIECBAgEBdAQVgXU+7ESBAgAABAgQIECBAgAABAgQIEAgloAAMNQ5hCBAgQIAAAQIECBAgQIAAAQIECNQVUADW9bQbAQIECBAgQIAAAQIECBAgQIAAgVACCsBQ4xCGAAECBAgQIECAAAECBAgQIECAQF0BBWBdT7sRIECAAAECBAgQIECAAAECBAgQCCWgAAw1DmEIECBAgAABAgQIECBAgAABAgQI1BVQANb1tBsBAgQIECBAgAABAgQIECBAgACBUAIKwFDjEIYAAQIECBAgQIAAAQIECBAgQIBAXQEFYF1PuxEgQIAAAQIECBAgQIAAAQIECBAIJaAADDUOYQgQIECAAAECBAgQIECAAAECBAjUFVAA1vW0GwECBAgQIECAAAECBAgQIECAAIFQAgrAUOMQhgABAgQIECBAgAABAgQIECBAgEBdAQVgXU+7ESBAgAABAgQIECBAgAABAgQIEAgloAAMNQ5hCBAgQIAAAQIECBAgQIAAAQIECNQVUADW9bQbAQIECBAgQIAAAQIECBAgQIAAgVACCsBQ4xCGAAECBAgQIECAAAECBAgQIECAQF0BBWBdT7sRIECAAAECBAgQIECAAAECBAgQCCWgAAw1DmEIECBAgAABAgQIECBAgAABAgQI1BVQANb1tBsBAgQIECBAgAABAgQIECBAgACBUAIKwFDjEIYAAQIECBAgQIAAAQIECBAgQIBAXQEFYF1PuxEgQIAAAQIECBAgQIAAAQIECBAIJaAADDUOYQgQIECAAAECBAgQIECAAAECBAjUFVAA1vW0GwECBAgQIECAAAECBAgQIECAAIFQAgrAUOMQhgABAgQIECBAgAABAgQIECBAgEBdAQVgXU+7ESBAgAABAgQIECBAgAABAgQIEAgl0Nz5mrvbW7/xe0KF2hthmhQ3o+lj5oiaJeaVuW/BpjgFSqKoKUDv/z+/Vf78kU+myPqRP7yvnDpxIkXWpsnz/apRaVOYPvWZT5cnH/pU+KznmsVyodkXPmcfcO3k8TLelyPruBmnMH3yi8+Xn/2fv5sia9udp9PRYoKsbWlzPEx1lmmCdkkTZW2nCc7T7YgZ3qj096k889+Wjf45E2me+ffnafz7f3+vH7UZ7vvds1SXM8u9/7MffGdZiH7Hl48AAQKZBNruRXU7jf/E2puOR6MyHuco1kajRE9XSebfdO1//5HhkuWF9Xg07u5TOYq1hST3qSyeGe5HMhIgQIAAAQJf3gI53vl9ec/IrSdAgAABAgQIECBAgAABAgQIECAwt4ACcG46BxIgQIAAAQIECBAgQIAAAQIECBCIL6AAjD8jCQkQIECAAAECBAgQIECAAAECBAjMLaAAnJvOgQQIECBAgAABAgQIECBAgAABAgTiCygA489IQgIECBAgQIAAAQIECBAgQIAAAQJzCygA56ZzIAECBAgQIECAAAECBAgQIECAAIH4AgrA+DOSkAABAgQIECBAgAABAgQIECBAgMDcAgrAuekcSIAAAQIECBAgQIAAAQIECBAgQCC+gAIw/owkJECAAAECBAgQIECAAAECBAgQIDC3gAJwbjoHEiBAgAABAgQIECBAgAABAgQIEIgvoACMPyMJCRAgQIAAAQIECBAgQIAAAQIECMwtoACcm86BBAgQIECAAAECBAgQIECAAAECBOILKADjz0hCAgQIECBAgAABAgQIECBAgAABAnMLKADnpnMgAQIECBAgQIAAAQIECBAgQIAAgfgCCsD4M5KQAAECBAgQIECAAAECBAgQIECAwNwCCsC56RxIgAABAgQIECBAgAABAgQIECBAIL6AAjD+jCQkQIAAAQIECBAgQIAAAQIECBAgMLeAAnBuOgcSIECAAAECBAgQIECAAAECBAgQiC+gAIw/IwkJECBAgAABAgQIECBAgAABAgQIzC2gAJybzoEECBAgQIAAAQIECBAgQIAAAQIE4gsoAOPPSEICBAgQIECAAAECBAgQIECAAAECcwsoAOemcyABAgQIECBAgAABAgQIECBAgACB+AIKwPgzkpAAAQIECBAgQIAAAQIECBAgQIDA3AIKwLnpHEiAAAECBAgQIECAAAECBAgQIEAgvoACMP6MJCRAgAABAgQIECBAgAABAgQIECAwt4ACcG46BxIgQIAAAQIECBAgQIAAAQIECBCIL6AAjD8jCQkQIECAAAECBAgQIECAAAECBAjMLaAAnJvOgQQIECBAgAABAgQIECBAgAABAgTiCygA489IQgIECBAgQIAAAQIECBAgQIAAAQJzCygA56ZzIAECBAgQIECAAAECBAgQIECAAIH4AgrA+DOSkAABAgQIECBAgAABAgQIECBAgMDcAgrAuekcSIAAAQIECBAgQIAAAQIECBAgQCC+gAIw/owkJECAAAECBAgQIECAAAECBAgQIDC3gAJwbjoHEiBAgAABAgQIECBAgAABAgQIEIgvoACMPyMJCRAgQIAAAQIECBAgQIAAAQIECMwtoACcm86BBAgQIECAAAECBAgQIECAAAECBOILKADjz0hCAgQIECBAgAABAgQIECBAgAABAnMLKADnpnMgAQIECBAgQIAAAQIECBAgQIAAgfgCCsD4M5KQAAECBAgQIECAAAECBAgQIECAwNwCCsC56RxIgAABAgQIECBAgAABAgQIECBAIL7AQttlnEw34yeVcEcEmqbp9u0/4l/adho/5F8kbJo83fqVcyA+bdv2j1bxLz/8Q/+4fNVN6/GDdgmPrh8pWeY/zfQ8NcrxmHr0la8qx+54Vfhz9ad/6qfKr/3SL4bP2Qf8r7/2a+XW225PkfXHf/THUuRcO3iw/Mvvf0uKrB968PPldz7ymfBZ+6fTts3xOBUeM2vArdf/CcJvnas5Xv9neZ2aYOpXI7Ztno6imeZ575fhvX//rm8zyXu/tvTnaY7Hqe7Zv2Q6U68+GPiCAAECBAgQIECAAAECBAgQIECAAIHZBBSAszlZRYAAAQIECBAgQIAAAQIECBAgQCClgAIw5diEJkCAAAECBAgQIECAAAECBAgQIDCbgAJwNierCBAgQIAAAQIECBAgQIAAAQIECKQUUACmHJvQBAgQIECAAAECBAgQIECAAAECBGYTUADO5mQVAQIECBAgQIAAAQIECBAgQIAAgZQCCsCUYxOaAAECBAgQIECAAAECBAgQIECAwGwCCsDZnKwiQIAAAQIECBAgQIAAAQIECBAgkFJAAZhybEITIECAAAECBAgQIECAAAECBAgQmE1AATibk1UECBAgQIAAAQIECBAgQIAAAQIEUgooAFOOTWgCBAgQIECAAAECBAgQIECAAAECswkoAGdzsooAAQIECBAgQIAAAQIECBAgQIBASgEFYMqxCU2AAAECBAgQIECAAAECBAgQIEBgNgEF4GxOVhEgQIAAAQIECBAgQIAAAQIECBBIKaAATDk2oQkQIECAAAECBAgQIECAAAECBAjMJqAAnM3JKgIECBAgQIAAAQIECBAgQIAAAQIpBRSAKccmNAECBAgQIECAAAECBAgQIECAAIHZBBSAszlZRYAAAQIECBAgQIAAAQIECBAgQCClgAIw5diEJkCAAAECBAgQIECAAAECBAgQIDCbgAJwNierCBAgQIAAAQIECBAgQIAAAQIECKQUUACmHJvQBAgQIECAAAECBAgQIECAAAECBGYTUADO5mQVAQIECBAgQIAAAQIECBAgQIAAgZQCCsCUYxOaAAECBAgQIECAAAECBAgQIECAwGwCCsDZnKwiQIAAAQIECBAgQIAAAQIECBAgkFJAAZhybEITIECAAAECBAgQIECAAAECBAgQmE1AATibk1UECBAgQIAAAQIECBAgQIAAAQIEUgooAFOOTWgCBAgQIECAAAECBAgQIECAAAECswkoAGdzsooAAQIECBAgQIAAAQIECBAgQIBASgEFYMqxCU2AAAECBAgQIECAAAECBAgQIEBgNgEF4GxOVhEgQIAAAQIECBAgQIAAAQIECBBIKaAATDk2oQkQIECAAAECBAgQIECAAAECBAjMJqAAnM3JKgIECBAgQIAAAQIECBAgQIAAAQIpBRSAKccmNAECBAgQIECAAAECBAgQIECAAIHZBBSAszlZRYAAAQIECBAgQIAAAQIECBAgQCClgAIw5diEJkCAAAECBAgQIECAAAECBAgQIDCbgAJwNierCBAgQIAAAQIECBAgQIAAAQIECKQUUACmHJvQBAgQIECAAAECBAgQIECAAAECBGYTUADO5mQVAQIECBAgQIAAAQIECBAgQIAAgZQCCsCUYxOaAAECBAgQIECAAAECBAgQIECAwGwCCsDZnKwiQIAAAQIECBAgQIAAAQIECBAgkFJAAZhybEITIECAAAECBAgQIECAAAECBAgQmE1gYWtZO9tiqwYINAPW7uLStpt9kyTrLjK5agIzCzz33PPliScmM6/fzYXT6XQ3r37QdX/uc58btH63Fi8uLZUTJ0/s1tXPcb3xnwBG41FZWLjycmWOG3hdD3nm6WfK6oEnrut1zntll144N++h1/W45cWFstCdAxku7WSzXHzh+fBRxwtLZbxvKXxOAQm0Jceb1LZ/Q5Uka/fOz4m1IwI5ztUrNz3+OXDlPrUjg/qy33TrFfXmZp43gVkmNho1pUnwejXTnatJ1FS2bZ77VCLWFHf/n/u5/1Ief/DjKbI++OA3lf37V1Jkvfvuu1PkfN3rXlfe8573pMg6Go3LaBT/ierw+nq58StuSmH6Ez/xb8rW+8AEaZ+5/4MJUpZy0y23lh/6J/8wRdbzZx4rf/DOXw6f9ZY77yk3v/prw+fMFzBPAdC28QuA7flneJ3atpMyneb45m/TjDvaHPPP8ny6da523wDKcsn0njqFaZPnsb/3jP/KP8XUhSRAgAABAgQIECBAgAABAgQIECAQU0ABGHMuUhEgQIAAAQIECBAgQIAAAQIECBCoIqAArMJoEwIECBAgQIAAAQIECBAgQIAAAQIxBRSAMeciFQECBAgQIECAAAECBAgQIECAAIEqAgrAKow2IUCAAAECBAgQIECAAAECBAgQIBBTQAEYcy5SESBAgAABAgQIECBAgAABAgQIEKgioACswmgTAgQIECBAgAABAgQIECBAgAABAjEFFIAx5yIVAQIECBAgQIAAAQIECBAgQIAAgSoCCsAqjDYhQIAAAQIECBAgQIAAAQIECBAgEFNAARhzLlIRIECAAAECBAgQIECAAAECBAgQqCKgAKzCaBMCBAgQIECAAAECBAgQIECAAAECMQUUgDHnIhUBAgQIECBAgAABAgQIECBAgACBKgIKwCqMNiFAgAABAgQIECBAgAABAgQIECAQU0ABGHMuUhEgQIAAAQIECBAgQIAAAQIECBCoIqAArMJoEwIECBAgQIAAAQIECBAgQIAAAQIxBRSAMeciFQECBAgQIECAAAECBAgQIECAAIEqAgrAKow2IUCAAAECBAgQIECAAAECBAgQIBBTQAEYcy5SESBAgAABAgQIECBAgAABAgQIEKgioACswmgTAgQIECBAgAABAgQIECBAgAABAjEFFIAx5yIVAQIECBAgQIAAAQIECBAgQIAAgSoCCsAqjDYhQIAAAQIECBAgQIAAAQIECBAgEFNAARhzLlIRIECAAAECBAgQIECAAAECBAgQqCKgAKzCaBMCBAgQIECAAAECBAgQIECAAAECMQUUgDHnIhUBAgQIECBAgAABAgQIECBAgACBKgIKwCqMNiFAgAABAgQIECBAgAABAgQIECAQU0ABGHMuUhEgQIAAAQIECBAgQIAAAQIECBCoIqAArMJoEwIECBAgQIAAAQIECBAgQIAAAQIxBRSAMeciFQECBAgQIECAAAECBAgQIECAAIEqAgrAKow2IUCAAAECBAgQIECAAAECBAgQIBBTQAEYcy5SESBAgAABAgQIECBAgAABAgQIEKgioACswmgTAgQIECBAgAABAgQIECBAgAABAjEFFIAx5yIVAQIECBAgQIAAAQIECBAgQIAAgSoCCsAqjDYhQIAAAQIECBAgQIAAAQIECBAgEFNAARhzLlIRIECAAAECBAgQIECAAAECBAgQqCKgAKzCaBMCBAgQIECAAAECBAgQIECAAAECMQUUgDHnIhUBAgQIECBAgAABAgQIECBAgACBKgIKwCqMNiFAgAABAgQIECBAgAABAgQIECAQU0ABGHMuUhEgQIAAAQIECBAgQIAAAQIECBCoIqAArMJoEwIECBAgQIAAAQIECBAgQIAAAQIxBRSAMeciFQECBAgQIECAAAECBAgQIECAAIEqAgrAKow2IUCAAAECBAgQIECAAAECBAgQIBBTYKGP1Xb/c6krMG3b0kzr7vnlvlvbNl/uBNVvf9ORZnG9Mv3458CRE6dL0/0vw2W8sNDNP8fj/1133ZWBtNxxxx1lPB6nyPr4Y58t/Uf0y3LTltffnWP+o7X1UkZbL62is5bPH1sLn7EPeOzEybK0miPryupKWVtdCu+6uK97jEry2H/lOSrH81SOZ/7t0zNP2hSnav++b5s2+ue2f4OaJW1/309w/9+KmCDnX5ybWV77pxHdepBKk7Z0r1K7+m/rgSD6o1WufCmerDrSvgBy+XIW6KuqHD8I3GydrPEfXF/xlXeWm27/mhQn1XjfYprH/7e+9a0pTE+fPl327duXIuun7r+/vOfXfz181re84fXljff+rfA5+4AH77irjJdXUmT92AdfmyLn8v795cCRoymyHlo/VG5Yjz//1eXu5f80/vNpP/R2upnmG1WjUY7XU1fuTDnmv3UOJIl65XXqFd3I/2xLXwDmQM30NnW65Rp58l/KlqYAzFKofIk2/lfdXT/TM1V8UAkJECBAgAABAgQIECBAgAABAgQIBBNQAAYbiDgECBAgQIAAAQIECBAgQIAAAQIEagooAGtq2osAAQIECBAgQIAAAQIECBAgQIBAMAEFYLCBiEOAAAECBAgQIECAAAECBAgQIECgpoACsKamvQgQIECAAAECBAgQIECAAAECBAgEE1AABhuIOAQIECBAgAABAgQIECBAgAABAgRqCigAa2raiwABAgQIECBAgAABAgQIECBAgEAwAQVgsIGIQ4AAAQIECBAgQIAAAQIECBAgQKCmgAKwpqa9CBAgQIAAAQIECBAgQIAAAQIECAQTUAAGG4g4BAgQIECAAAECBAgQIECAAAECBGoKKABratqLAAECBAgQIECAAAECBAgQIECAQDABBWCwgYhDgAABAgQIECBAgAABAgQIECBAoKaAArCmpr0IECBAgAABAgQIECBAgAABAgQIBBNQAAYbiDgECBAgQIAAAQIECBAgQIAAAQIEagooAGtq2osAAQIECBAgQIAAAQIECBAgQIBAMAEFYLCBiEOAAAECBAgQIECAAAECBAgQIECgpoACsKamvQgQIECAAAECBAgQIECAAAECBAgEE1AABhuIOAQIECBAgAABAgQIECBAgAABAgRqCigAa2raiwABAgQIECBAgAABAgQIECBAgEAwAQVgsIGIQ4AAAQIECBAgQIAAAQIECBAgQKCmgAKwpqa9CBAgQIAAAQIECBAgQIAAAQIECAQTUAAGG4g4BAgQIECAAAECBAgQIECAAAECBGoKKABratqLAAECBAgQIECAAAECBAgQIECAQDABBWCwgYhDgAABAgQIECBAgAABAgQIECBAoKaAArCmpr0IECBAgAABAgQIECBAgAABAgQIBBNQAAYbiDgECBAgQIAAAQIECBAgQIAAAQIEagooAGtq2osAAQIECBAgQIAAAQIECBAgQIBAMAEF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" style="width:40px; height:40px; object-fit:cover; border-radius:12px;" />
        </div>
        <div class="header-info">
            <h1>QingAgent</h1>
            <p>晴帅的私人 AI 桌面助手</p>
        </div>
        <div class="status-dot" id="statusDot" title="在线"></div>
        <button class="header-btn" onclick="clearHistory()" title="一键清屏，重新开始">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path><line x1="10" y1="11" x2="10" y2="17"></line><line x1="14" y1="11" x2="14" y2="17"></line></svg>
            <span>清屏</span>
        </button>
        <button class="header-btn" onclick="window.location.href='/benchmark'" title="模型横评测试台">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"></polyline><line x1="12" y1="19" x2="20" y2="19"></line></svg>
            <span>测试台</span>
        </button>
        <button class="theme-toggle" id="themeToggleBtn" onclick="toggleTheme()" title="切换明/暗主题">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>
        </button>
        <button class="emergency-btn" onclick="emergencyStop()" title="立即终止所有正在执行的任务">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
            <span>急停</span>
        </button>
    </div>

    <div class="chat-area" id="chatArea">
        <div class="msg-row agent">
            <div class="msg-bubble">
                👋 你好晴帅！我已在你的电脑上待命。<br><br>
                发送自然语言指令，我来帮你操控桌面应用。
            </div>
        </div>
    </div>
    <div class="mode-capsule">
        <div class="mode-slider" id="modeSlider"></div>
        <div class="mode-btn safe active" id="modeSafe" onclick="toggleMode('safe')" style="display:flex; align-items:center; justify-content:center; gap:4px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
            <span>安全</span>
        </div>
        <div class="mode-btn fast" id="modeFast" onclick="toggleMode('fast')" style="display:flex; align-items:center; justify-content:center; gap:4px;">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg>
            <span>极速</span>
        </div>
    </div>

    <div class="input-area">
        <input type="text" id="cmdInput" placeholder="输入指令..."
               enterkeyhint="send">
        <button class="mic-btn" id="micBtn" title="语音输入">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"></path><path d="M19 10v2a7 7 0 0 1-14 0v-2"></path><line x1="12" y1="19" x2="12" y2="23"></line><line x1="8" y1="23" x2="16" y2="23"></line></svg>
        </button>
        <button class="send-btn" id="sendBtn" onclick="sendCmd()" title="发送">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
        </button>
    </div>
</div>

<script>
    const STORAGE_KEY = 'qingagent_chat_history';
    const MAX_HISTORY = 50; // 最多保留 50 条消息记录

    const chatArea = document.getElementById('chatArea');
    const cmdInput = document.getElementById('cmdInput');
    const sendBtn = document.getElementById('sendBtn');
    const statusDot = document.getElementById('statusDot');
    const micBtn = document.getElementById('micBtn');

    let _history = [];
    function saveHistory() {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(_history)); } catch(e) {}
    }

    // 页面启动时恢复历史消息数据（如果旧数据格式非法，catch 内自动清空）
    try {
        const h = localStorage.getItem(STORAGE_KEY);
        if (h) {
            _history = JSON.parse(h);
            if (!Array.isArray(_history)) _history = [];
            _history.forEach(item => {
                const row = document.createElement('div');
                row.className = `msg-row ${item.role} ${item.cls || ''}`;
                row.innerHTML = `<div class="msg-bubble">${item.html}</div><div class="msg-time">${item.time || ''}</div>`;
                chatArea.appendChild(row);
            });
            setTimeout(() => { chatArea.scrollTop = chatArea.scrollHeight; }, 100);
        }
    } catch(e) {
        _history = [];
    }

    function clearHistory() {
        chatArea.innerHTML = `
        <div class="msg-row agent">
            <div class="msg-bubble">
                👋 屏幕已清空，我在等待你的桌面指令...
            </div>
        </div>`;
        _history = [];
        saveHistory();
    }

    let isProcessing = false; // 全局防抖锁

    // ============================================================
    //  语音识别模块（Web Speech API）
    // ============================================================
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    let _recognition = null;
    let _isListening = false;

    if (SpeechRecognition) {
        _recognition = new SpeechRecognition();
        _recognition.lang = 'zh-CN';       // 中文识别
        _recognition.continuous = true;      // 开启连续识别，阻断 WebKit 的原生默认结束 Bug
        _recognition.interimResults = true;  // 实时显示中间结果

        let _silenceTimer = null;
        function resetSilenceTimer() {
            if (_silenceTimer) clearTimeout(_silenceTimer);
            _silenceTimer = setTimeout(() => {
                // 如果 2.5 秒没有检测到新语音，强行人工阻断并收尾，避免原生 Bug 导致的硬件流死锁
                if (_isListening && _recognition) {
                    try { _recognition.stop(); } catch(e) {}
                }
            }, 2500);
        }

        _recognition.onstart = () => {
            _isListening = true;
            micBtn.classList.add('recording');
            micBtn.textContent = '⏺';
            cmdInput.placeholder = '🎙 正在聆听...';
            resetSilenceTimer(); // 开始录音时启动防挂死探针
        };

        _recognition.onresult = (event) => {
            resetSilenceTimer(); // 只要还在说话，就不停重置探针
            let finalText = '';
            let interimText = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalText += transcript;
                } else {
                    interimText += transcript;
                }
            }
            // 实时预览：中间结果灰色显示在 placeholder
            if (interimText) {
                cmdInput.placeholder = '🎙 ' + interimText;
            }
            // 最终结果追加到输入框
            if (finalText) {
                cmdInput.value += finalText;
            }
        };

        _recognition.onerror = (event) => {
            console.warn('语音识别错误:', event.error);
            if (event.error === 'not-allowed') {
                addMsg('⚠️ 麦克风权限被拒绝。请在浏览器设置中允许麦克风访问。', 'agent', 'error');
            } else if (event.error === 'no-speech') {
                // 没有检测到语音，静默处理
            } else {
                addMsg('⚠️ 语音识别失败: ' + event.error, 'agent', 'error');
            }
            stopListening();
        };

        _recognition.onend = () => {
            stopListening();
        };

        micBtn.onclick = () => {
            if (isProcessing) return;
            if (_isListening) {
                _recognition.stop();
            } else {
                try {
                    _recognition.start();
                } catch (e) {
                    // 可能是已经在运行
                    _recognition.stop();
                    setTimeout(() => _recognition.start(), 200);
                }
            }
        };
    } else {
        // 浏览器不支持
        micBtn.classList.add('unsupported');
        micBtn.title = '当前浏览器不支持语音识别';
        micBtn.onclick = () => {
            addMsg(`⚠️ 语音功能受限！手机浏览器在 HTTP 连接下（非 HTTPS）为了保护隐私，默认禁用了麦克风 API。\n\n【解决办法】：在手机的 Chrome 地址栏输入 chrome://flags/#unsafely-treat-insecure-origin-as-secure，将目前的局域网 IP（比如 http://192.168.1.17:8002）填入白名单并开启，即可强制启用语音！`, 'agent', 'error');
        };
    }

    function stopListening() {
        _isListening = false;
        micBtn.classList.remove('recording');
        micBtn.textContent = '🎤';
        cmdInput.placeholder = '输入指令...';
        cmdInput.focus();
        
        // 苹果专属终极杀招：手动探测底部硬件媒体流并强行截断，破除黄点死锁
        if (navigator.mediaDevices && navigator.mediaDevices.getUserMedia) {
            navigator.mediaDevices.getUserMedia({ audio: true })
                .then(stream => {
                    stream.getTracks().forEach(track => track.stop());
                }).catch(e => {});
        }
    }

    function now() {
        return new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
    }

    function addMsg(html, type, cls = '', save = true) {
        const timeStr = now();
        const row = document.createElement('div');
        row.className = `msg-row ${type} ${cls}`;
        row.innerHTML = `
            <div class="msg-bubble">${html}</div>
            <div class="msg-time">${timeStr}</div>
        `;
        chatArea.appendChild(row);
        chatArea.scrollTop = chatArea.scrollHeight;
        
        // 保存到纯数据账本中
        if (save) {
            _history.push({role: type, html: html, cls: cls, time: timeStr});
            if (_history.length > MAX_HISTORY * 2) {
                _history = _history.slice(-MAX_HISTORY * 2);
            }
            saveHistory();
        }
        return row;
    }

    // 清缓存强制刷新——解决浏览器缓存旧版 JS/CSS 的问题
    async function hardReload() {
        const btn = event.currentTarget;
        btn.style.opacity = '0.4';
        btn.style.pointerEvents = 'none';
        btn.textContent = '⏳ 刷新中...';
        // 清除所有 Service Worker 缓存
        if ('caches' in window) {
            const keys = await caches.keys();
            await Promise.all(keys.map(k => caches.delete(k)));
        }
        // 强制绕过 HTTP 缓存重新加载
        const url = new URL(location.href);
        url.searchParams.set('_t', Date.now());
        location.replace(url.toString());
    }

    function quickSend(text) {
        if (isProcessing) return; // 拦截快捷指令
        cmdInput.value = text;
        sendCmd();
    }

    let _pollCancelled = false;  // 轮询中断标志
    let _cancelBtnCounter = 0;   // 按钮唯一 ID 计数器

    let _currentMode = 'safe';
    function toggleMode(mode) {
        if (isProcessing) {
            addMsg("⚠️ 操控执行中，为防止状态错落请稍候再切换极速/安全模式。", "agent", "error", false);
            return;
        }
        _currentMode = mode;
        const slider = document.getElementById('modeSlider');
        const safeBtn = document.getElementById('modeSafe');
        const fastBtn = document.getElementById('modeFast');
        if (mode === 'fast') {
            slider.classList.add('fast-active');
            fastBtn.classList.add('active');
            safeBtn.classList.remove('active');
            statusDot.style.background = '#ef4444'; // 危险霓虹红
            statusDot.style.boxShadow = '0 0 12px rgba(239,68,68,0.8)';
            addMsg("⚠️ **极速盲发模式已解除封印**！<br>所有涉及到对外发送的操作（微信、邮件等）都将无视人工阻断界限！请再次确定这是你想要的！", "agent", "error", false);
        } else {
            slider.classList.remove('fast-active');
            safeBtn.classList.add('active');
            fastBtn.classList.remove('active');
            statusDot.style.background = '#10b981'; // 安全绿荫
            statusDot.style.boxShadow = '0 0 8px rgba(16,185,129,0.5)';
            addMsg("🛡️ 已退回**安全护航模式**，所有的微信图片及敏感文字操作在发出前，都会进入挂起状态等待你的绝对确认。", "agent", "success", false);
        }
    }

    async function sendCmd() {
        if (isProcessing) return; // 拦截并发发送
        const cmd = cmdInput.value.trim();
        if (!cmd) return;

        isProcessing = true;
        _pollCancelled = false;
        cmdInput.disabled = true;
        sendBtn.disabled = true;
        statusDot.style.background = '#facc15'; // 黄色=忙碌

        addMsg(cmd, 'user');
        cmdInput.value = '';

        // 用唯一 ID 防止多次发送造成 DOM id 冲突
        _cancelBtnCounter++;
        const cancelBtnId = 'cancelBtn_' + _cancelBtnCounter;
        const timerId = 'execTimer_' + _cancelBtnCounter;
        const progressId = 'stepProgress_' + _cancelBtnCounter;

        // 加载动画 + 计时器 + 步骤进度 (中间状态，不要存入 localStorage 账本！)
        const loadingRow = addMsg(
            `正在执行操控...<div class="loading-dots"><span></span><span></span><span></span></div>
             <div id="${progressId}" style="font-size:11px; color:rgba(255,255,255,0.6); margin-top:2px; min-height:14px;"></div>
             <div style="display:flex; align-items:center; margin-top:4px;">
                 <div class="timer" id="${timerId}">⏱ 0s</div>
                 <button class="cancel-btn" id="${cancelBtnId}" style="display:none;">✖ 终止</button>
             </div>`,
            'agent', '', false
        );

        const startTime = Date.now();
        const timerEl = document.getElementById(timerId);
        const timerInterval = setInterval(() => {
            const elapsed = Math.floor((Date.now() - startTime) / 1000);
            if (timerEl) timerEl.textContent = `⏱ ${elapsed}s`;
        }, 1000);

        try {
            // 提交任务
            const submitRes = await fetch('/api/execute', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ command: cmd, mode: _currentMode })
            });
            const submitData = await submitRes.json();

            if (!submitData.task_id) {
                clearInterval(timerInterval);
                loadingRow.remove();
                showResult(submitData);
                return;
            }

            // 轮询任务状态
            const taskId = submitData.task_id;
            const pollResult = async () => {
                // 核心：如果已被取消，彻底停止轮询递归
                if (_pollCancelled) return;

                try {
                    const res = await fetch(`/api/task/${taskId}`);
                    const data = await res.json();

                    if (_pollCancelled) return; // 二次防护

                    if (data.status === 'done') {
                        clearInterval(timerInterval);
                        loadingRow.remove();
                        showResult(data.result);
                    } else if (data.status === 'cancelled') {
                        clearInterval(timerInterval);
                        loadingRow.remove();
                        addMsg('🛑 操作已被终止', 'agent', 'error');
                        finish();
                    } else if (data.status === 'queued') {
                        // 排队中：实时显示前方任务数
                        const stepEl = document.getElementById(progressId);
                        if (stepEl) {
                            const ahead = data.ahead || 0;
                            stepEl.textContent = ahead > 0
                                ? `⏳ 排队中，前方还有 ${ahead} 个任务…`
                                : '⏳ 即将开始执行…';
                        }
                        setTimeout(pollResult, 1000);
                    } else {
                        // running 状态：显示取消按钮和步骤进度
                        const cb = document.getElementById(cancelBtnId);
                        if (cb) {
                            cb.style.display = 'inline-block';
                            cb.onclick = () => cancelTask(taskId, timerInterval, loadingRow);
                        }
                        // 多步骤：更新步骤进度提示
                        if (data.progress) {
                            const p = data.progress;
                            const stepEl = document.getElementById(progressId);
                            if (stepEl) {
                                stepEl.textContent = `步骤 ${p.current_step}/${p.total_steps}：${p.description}`;
                            }
                        }
                        setTimeout(pollResult, 1000);
                    }
                } catch (e) {
                    if (_pollCancelled) return;
                    clearInterval(timerInterval);
                    loadingRow.remove();
                    addMsg('❌ 查询状态失败：' + e.message, 'agent', 'error');
                    finish();
                }
            };
            pollResult();

        } catch (e) {
            clearInterval(timerInterval);
            loadingRow.remove();
            addMsg('❌ 网络错误：' + e.message, 'agent', 'error');
            finish();
        }
    }

        function showResult(data) {
        let content = data.message || '执行完成';
        if (data.data) {
            const d = data.data;
            if (typeof d === 'object' && d !== null) {
                // =============== [新增拦截层 1]：多文件二选一 ================
                if (d.type === 'file_choice' && Array.isArray(d.items)) {
                    const fileIcons = {
                        'pdf': '📕', 'doc': '📄', 'docx': '📄',
                        'xls': '📊', 'xlsx': '📊', 'ppt': '📋', 'pptx': '📋',
                        'jpg': '🖼️', 'jpeg': '🖼️', 'png': '🖼️', 'gif': '🖼️',
                        'zip': '🗄️', 'rar': '🗄️', '7z': '🗄️',
                        'mp4': '🎥', 'mp3': '🎧', 'txt': '📝', 'md': '📝',
                    };
                    const getIcon = name => {
                        const ext = name.split('.').pop().toLowerCase();
                        return fileIcons[ext] || '📂';
                    };
                    const getDir = path => {
                        const parts = path.split('/');
                        const home = parts.indexOf('konglingjia');
                        return home > 0 ? '~/' + parts.slice(home + 1, -1).join('/') : parts.slice(0, -1).join('/') || '/';
                    };

                    content += `<div style="margin-top:8px; display:flex; flex-direction:column; gap:6px;">`;
                    d.items.forEach((item, idx) => {
                        const escapedPath = item.path.replace(/'/g, "\\\\'");
                        const icon = getIcon(item.name);
                        const dir = getDir(item.path);
                        content += `
                        <div style="
                            background: rgba(255,255,255,0.03);
                            border: 1px solid rgba(255,255,255,0.07);
                            border-radius: 10px;
                            padding: 10px 12px;
                            cursor: pointer;
                            transition: all 0.18s ease;
                            display: flex;
                            align-items: center;
                            gap: 12px;
                        " 
                        onmouseover="this.style.background='rgba(102,126,234,0.12)'; this.style.borderColor='rgba(102,126,234,0.35)';"
                        onmouseout="this.style.background='rgba(255,255,255,0.03)'; this.style.borderColor='rgba(255,255,255,0.07)';"
                        onclick="this.style.opacity='0.4'; this.style.pointerEvents='none'; quickSend('请发送：${escapedPath}');">
                            <div style="
                                width: 36px; height: 36px;
                                border-radius: 8px;
                                background: rgba(102,126,234,0.15);
                                display: flex; align-items: center; justify-content: center;
                                font-size: 17px;
                                flex-shrink: 0;
                            ">${icon}</div>
                            <div style="flex:1; min-width:0;">
                                <div style="font-size:13px; font-weight:500; color:#e2e8f0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.name}</div>
                                <div style="font-size:10px; color:rgba(255,255,255,0.35); margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${dir}</div>
                            </div>
                            <div style="font-size:10px; color:rgba(102,126,234,0.7); flex-shrink:0; padding: 2px 8px; background:rgba(102,126,234,0.1); border-radius:6px;">选择</div>
                        </div>`;
                    });
                    content += `
                    <button onclick="addMsg('已放弃文件选择', 'user'); this.parentElement.style.display='none';" 
                     style="margin-top:2px; padding:7px; border-radius:8px; background:transparent; border:1px solid rgba(239,68,68,0.15); color:rgba(239,68,68,0.6); font-size:11px; cursor:pointer; width:100%; transition:0.2s;"
                     onmouseover="this.style.background='rgba(239,68,68,0.07)'" 
                     onmouseout="this.style.background='transparent'">
                        ✕ 都不对，放弃本次操作
                    </button>
                    </div>`;
                } 
                // =============== [新增拦截层 2]：微信发送前确认 ================
                else if (d.type === 'confirm_send' && d.screenshot_path) {
                    const imgUrl = `/api/image?path=${encodeURIComponent(d.screenshot_path)}`;
                    content += `<div style="margin-top:8px;">
                        <img src="${imgUrl}" alt="\u5f85\u786e\u8ba4\u622a\u56fe" style="width:100%; border-radius:10px; border:1px solid rgba(255,255,255,0.06); display:block;" />
                        <div style="display:flex; align-items:center; justify-content:space-between; margin-top:8px; padding:8px 10px; background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); border-radius:8px;">
                            <span style="font-size:11px; color:rgba(255,255,255,0.4); display:flex; align-items:center; gap:4px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line></svg> \u5185\u5bb9\u5df2\u5c31\u7eea\uff0c\u5f85\u786e\u8ba4</span>
                            <div style="display:flex; gap:8px;">
                                <button
                                    onclick="quickSend('\u6267\u884c\u5fae\u4fe1\u786e\u8ba4\u53d1\u9001'); this.closest('div[style]').style.opacity='0.4'; this.closest('div[style]').style.pointerEvents='none';"
                                    onmouseover="this.style.background='rgba(52,211,153,0.25)'; this.style.borderColor='rgba(52,211,153,0.5)';"
                                    onmouseout="this.style.background='rgba(52,211,153,0.1)'; this.style.borderColor='rgba(52,211,153,0.25)';"
                                    style="padding:5px 12px; background:rgba(52,211,153,0.1); border:1px solid rgba(52,211,153,0.25); border-radius:6px; color:#6ee7b7; font-size:11px; font-weight:500; cursor:pointer; transition:all 0.15s; display:flex; align-items:center; justify-content:center; gap:4px;">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg> \u786e\u8ba4\u53d1\u9001
                                </button>
                                <button
                                    onclick="addMsg('\u5df2\u53d6\u6d88\u53d1\u4ef6', 'user'); this.parentElement.parentElement.style.opacity='0.3';"
                                    onmouseover="this.style.background='rgba(239,68,68,0.15)'; this.style.borderColor='rgba(239,68,68,0.4)';"
                                    onmouseout="this.style.background='transparent'; this.style.borderColor='rgba(255,255,255,0.12)';"
                                    style="padding:5px 12px; background:transparent; border:1px solid rgba(255,255,255,0.12); border-radius:6px; color:rgba(255,255,255,0.45); font-size:11px; cursor:pointer; transition:all 0.15s; display:flex; align-items:center; justify-content:center; gap:4px;">
                                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg> \u53d6\u6d88
                                </button>
                            </div>
                        </div>
                    </div>`;
                }
                // =============== [新增拦截层 3]：添加日程成功确认卡片 ================
                else if (d.ui_type === 'calendar_task') {
                    const typeTag = d.task_type
                        ? `<span style="
                            font-size: 10px;
                            color: var(--text-secondary);
                            background: rgba(255,255,255,0.05);
                            padding: 1px 6px; border-radius: 4px;
                            margin-left: 6px; white-space: nowrap;
                          ">${d.task_type}</span>`
                        : '';
                    content += `<div style="
                        margin: 12px 0 0 0;
                        background: var(--bg-card);
                        border: 1px solid var(--border);
                        border-radius: 14px;
                        overflow: hidden;
                        min-width: 220px;
                    ">
                        <!-- 头部 -->
                        <div style="
                            display: flex; align-items: center; gap: 10px;
                            padding: 12px 16px;
                            border-bottom: 1px solid var(--border);
                        ">
                            <div style="
                                width: 28px; height: 28px; border-radius: 7px;
                                background: rgba(74,222,128,0.15);
                                border: 1px solid rgba(74,222,128,0.25);
                                display: flex; align-items: center; justify-content: center; color: #4ade80;
                                font-size: 14px; flex-shrink: 0;
                            "><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg></div>
                            <div style="flex: 1;">
                                <div style="font-size: 12px; font-weight: 600; color: #4ade80; line-height: 1;">已添加日程</div>
                                <div style="font-size: 10px; color: var(--text-secondary); margin-top: 3px; display:flex; align-items:center; gap:3px;"><svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg> ${d.date}</div>
                            </div>
                        </div>
                        <!-- 任务内容行 -->
                        <div style="
                            display: flex; align-items: center; gap: 10px;
                            padding: 12px 16px;
                        ">
                            <div style="
                                width: 14px; height: 14px; flex-shrink: 0;
                                border-radius: 50%;
                                border: 1.5px solid var(--border);
                                display: flex; align-items: center; justify-content: center;
                            "></div>
                            <div style="flex: 1; display: flex; align-items: center; flex-wrap: wrap; gap: 2px;">
                                <div style="font-size: 14px; font-weight: 500; color: var(--text-primary);">${d.title}</div>
                                ${typeTag}
                            </div>
                        </div>
                    </div>`;
                }
                // =============== [新增拦截层 4]：日历查询结果列表 ================
                else if (d.ui_type === 'calendar_query') {
                    const tasks = d.tasks || [];
                    const total = tasks.length;
                    const completed = tasks.filter(t => t.completed).length;
                    const pct = total > 0 ? Math.round(completed / total * 100) : 0;

                    // 进度条颜色：全完成绿，有未完成紫蓝
                    const barColor = (completed === total && total > 0)
                        ? 'linear-gradient(90deg,#4ade80,#22c55e)'
                        : 'linear-gradient(90deg, var(--accent-start), var(--accent-end))';

                    // 负向偏移让卡片突破气泡宽度限制
                    let html = `<div style="
                        margin: 12px 0 0 0;
                        background: var(--bg-card);
                        border: 1px solid var(--border);
                        border-radius: 14px;
                        overflow: hidden;
                        min-width: 220px;
                    ">
                        <!-- 头部标题行 -->
                        <div style="
                            display: flex;
                            align-items: center;
                            justify-content: space-between;
                            padding: 12px 16px 10px;
                            border-bottom: 1px solid var(--border);
                        ">
                            <div style="display: flex; align-items: center; gap: 8px;">
                                <div style="
                                    width: 28px; height: 28px; border-radius: 7px;
                                    background: linear-gradient(135deg, var(--accent-start), var(--accent-end));
                                    display: flex; align-items: center; justify-content: center; color: #fff;
                                    font-size: 14px; flex-shrink: 0;
                                "><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg></div>
                                <div>
                                    <div style="font-size: 13px; font-weight: 600; color: var(--text-primary); line-height: 1;">${d.date}</div>
                                    <div style="font-size: 10px; color: var(--text-secondary); margin-top: 2px;">${d.target_date || ''}</div>
                                </div>
                            </div>
                            <div style="
                                font-size: 11px; font-weight: 500;
                                color: ${completed===total && total>0 ? '#4ade80' : 'var(--text-secondary)'};
                                background: ${completed===total && total>0 ? 'rgba(74,222,128,0.1)' : 'rgba(255,255,255,0.06)'};
                                padding: 3px 10px; border-radius: 20px;
                            ">${completed} / ${total} 已完成</div>
                        </div>`;

                    // 进度条（只在有任务时显示）
                    if (total > 0) {
                        html += `<div style="padding: 0 16px;">
                            <div style="height: 2px; background: var(--border); border-radius: 1px; margin: 0;">
                                <div style="height: 100%; width: ${pct}%; background: ${barColor}; border-radius: 1px; transition: width 0.4s ease;"></div>
                            </div>
                        </div>`;
                    }

                    // 任务列表
                    if (total === 0) {
                        html += `<div style="
                            text-align: center; padding: 24px 16px;
                            color: var(--text-secondary); font-size: 12px;
                            display: flex; align-items: center; justify-content: center; gap: 6px;
                        "><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8h1a4 4 0 0 1 0 8h-1"></path><path d="M2 8h16v9a4 4 0 0 1-4 4H6a4 4 0 0 1-4-4V8z"></path><line x1="6" y1="1" x2="6" y2="4"></line><line x1="10" y1="1" x2="10" y2="4"></line><line x1="14" y1="1" x2="14" y2="4"></line></svg> <span>当日暂无任何任务安排</span></div>`;
                    } else {
                        html += `<div style="padding: 8px 12px; display: flex; flex-direction: column; gap: 6px;">`;
                        tasks.forEach(t => {
                            const isDone = t.completed;
                            const titleStyle = isDone
                                ? 'text-decoration: line-through; color: var(--text-secondary);'
                                : 'color: var(--text-primary);';
                            const rowBg = isDone
                                ? 'rgba(0,0,0,0.02)'
                                : 'rgba(90,111,232,0.05)';
                            const dotColor = isDone ? 'var(--success)' : 'var(--border)';
                            const dotInner = isDone
                                ? `<div style="width:6px;height:6px;border-radius:50%;background:#4ade80;"></div>`
                                : '';
                            const badge = t.task_type
                                ? `<span style="
                                    font-size: 10px;
                                    color: rgba(255,255,255,0.3);
                                    background: rgba(255,255,255,0.04);
                                    padding: 1px 6px; border-radius: 4px;
                                    margin-left: 6px; white-space: nowrap;
                                  ">${t.task_type}</span>`
                                : '';

                            html += `
                            <div style="
                                display: flex; align-items: center; gap: 10px;
                                padding: 10px 12px;
                                background: ${rowBg};
                                border-radius: 10px;
                                transition: background 0.15s;
                            ">
                                <!-- 状态小圆点 -->
                                <div style="
                                    width: 14px; height: 14px; flex-shrink: 0;
                                    border-radius: 50%;
                                    border: 1.5px solid ${dotColor};
                                    display: flex; align-items: center; justify-content: center;
                                ">${dotInner}</div>
                                <!-- 标题 + 标签 -->
                                <div style="flex: 1; min-width: 0; display: flex; align-items: center; flex-wrap: wrap; gap: 2px;">
                                    <div style="font-size: 13px; line-height: 1.4; ${titleStyle}">${t.title}</div>
                                    ${badge}
                                </div>
                            </div>`;
                        });
                        html += `</div>`;
                    }

                    html += `</div>`;
                    content += html;
                }
                // ================= 默认常规大图片和JSON ================
                else if (d.screenshot_path) {
                    const imgUrl = `/api/image?path=${encodeURIComponent(d.screenshot_path)}`;
                    content += `<div class="msg-data" style="padding:4px; max-height:unset;">
                        <a href="${imgUrl}" target="_blank" title="点击查看大图或长按保存" style="display:block;">
                            <img src="${imgUrl}" alt="截图" style="width:100%; border-radius:8px; display:block;" />
                        </a>
                        <div style="margin-top:8px; text-align:center;">
                             <a href="${imgUrl}" download="qingagent_screenshot.png" style="display:inline-block; padding:6px 16px; background:linear-gradient(135deg, #667eea, #764ba2); color:white; font-size:12px; border-radius:16px; text-decoration:none; font-weight:500;">⬇️ 下载原图到本地</a>
                        </div>
                    </div>`;
                } else {
                    // JSON兜底删除，避免与UI卡片重复或破坏美观
                }
            } else {
                content += `<div class="msg-data">${d}</div>`;
            }
        }
        addMsg(content, 'agent', data.success ? 'success' : 'error', true);
        finish();
    }

    function finish() {
        isProcessing = false;
        cmdInput.disabled = false;
        sendBtn.disabled = false;
        statusDot.style.background = '#4ade80'; // 绿色=空闲
        cmdInput.focus();
    }

    async function cancelTask(taskId, timerInterval, loadingRow) {
        // 1. 先发取消请求到后端（时序最优先！）
        _pollCancelled = true;  // 立刻停止轮询递归
        clearInterval(timerInterval);

        try {
            await fetch(`/api/cancel/${taskId}`, { method: 'POST' });
        } catch (e) {}

        // 2. 请求发完再更新 UI
        loadingRow.remove();
        addMsg('🛑 已发送终止信号，后台正在中断操作...', 'agent', 'error');
        finish();
    }

    async function emergencyStop() {
        // 🚨 最高级别紧急终止
        // 1. 标记所有轮询停止
        _pollCancelled = true;

        // 2. 调用最高权限的停止接口（取消所有任务 + FAILSAFE）
        try {
            const res = await fetch('/api/emergency_stop', { method: 'POST' });
            const data = await res.json();
            addMsg(`🚨 紧急停止：${data.message || '已执行'}`, 'agent', 'error');
        } catch(e) {
            addMsg('⚠️ 紧急停止请求失败（服务离线？）。<br>物理急救：把鼠标快速移到屏幕左上角(0,0)！', 'agent', 'error');
        }

        // 3. 恢复 UI 状态
        finish();
    }

    // ── 明暗主题切换 ─────────────────────────────────────────
    const SVG_MOON = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
    const SVG_SUN = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;

    function toggleTheme() {
        const root = document.getElementById('htmlRoot');
        const btn  = document.getElementById('themeToggleBtn');
        const isLight = root.getAttribute('data-theme') === 'light';
        if (isLight) {
            root.removeAttribute('data-theme');
            btn.innerHTML = SVG_MOON;
            localStorage.setItem('qa_theme', 'dark');
        } else {
            root.setAttribute('data-theme', 'light');
            btn.innerHTML = SVG_SUN;
            localStorage.setItem('qa_theme', 'light');
        }
    }
    // 页面加载时恢复上次的主题选择
    (function initTheme() {
        const saved = localStorage.getItem('qa_theme');
        if (saved === 'light') {
            document.getElementById('htmlRoot').setAttribute('data-theme', 'light');
            const btn = document.getElementById('themeToggleBtn');
            if (btn) btn.innerHTML = SVG_SUN;
        }
    })();
</script>
</body>
</html>'''





def _get_benchmark_html() -> str:
    """模型测试台页面 v2：单模型独立运行 + 历史对比"""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>🧪 模型测试台 · QingAgent</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
:root {
  --bg:#0b0b11; --bg2:#13131d; --card:#1a1a2e; --card2:#1e1e30;
  --border:rgba(255,255,255,0.07); --text:#e8e8ed; --muted:#8888a0;
  --as:#667eea; --ae:#764ba2; --green:#4ade80; --red:#f87171;
  --btn-bg:rgba(255,255,255,0.04); --btn-hov:rgba(255,255,255,0.08); --bdg:rgba(255,255,255,0.06);
}
html[data-theme="light"] {
  --bg:#f6f7fa; --bg2:#ffffff; --card:rgba(255,255,255,0.7); --card2:#fafafa;
  --border:rgba(0,0,0,0.06); --text:rgba(0,0,0,0.85); --muted:rgba(0,0,0,0.45);
  --as:#667eea; --ae:#764ba2; --green:#22c55e; --red:#ef4444;
  --btn-bg:rgba(0,0,0,0.03); --btn-hov:rgba(0,0,0,0.06); --bdg:rgba(0,0,0,0.05);
}
.theme-toggle{background:transparent;border:none;color:var(--muted);cursor:pointer;transition:.18s;display:flex;align-items:center;justify-content:center;}
.theme-toggle:hover{color:var(--text);}
*{box-sizing:border-box;margin:0;padding:0;}
body{font-family:'Inter',-apple-system,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;flex-direction:column;}

/* ── 顶栏 ── */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:12px 20px;background:var(--bg2);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20;}
.topbar-left{display:flex;align-items:center;gap:10px;}
.logo{width:30px;height:30px;border-radius:8px;background:linear-gradient(135deg,var(--as),var(--ae));display:flex;align-items:center;justify-content:center;font-size:15px;}
.topbar h1{font-size:14px;font-weight:600;}
.topbar-sub{font-size:10px;color:var(--muted);margin-top:2px;}
.back{padding:5px 12px;border-radius:6px;border:1px solid var(--border);background:var(--btn-bg);color:var(--muted);font-size:11px;cursor:pointer;text-decoration:none;transition:.18s;}
.back:hover{background:var(--btn-hov);color:var(--text);}

/* ── Tab ── */
.tabs{display:flex;gap:4px;padding:14px 20px 0;border-bottom:1px solid var(--border);}
.tab-btn{padding:7px 14px;border-radius:7px 7px 0 0;border:none;background:transparent;color:var(--muted);font-size:12px;font-weight:500;cursor:pointer;border-bottom:2px solid transparent;transition:.18s;}
.tab-btn:hover{color:var(--text);background:var(--btn-bg);}
.tab-btn.active{color:var(--text);background:var(--card);border-bottom-color:var(--as);}

/* ── 主布局 ── */
.layout{display:grid;grid-template-columns:320px 1fr;flex:1;overflow:hidden;}
@media(max-width:760px){.layout{grid-template-columns:1fr;}}

/* ── 左侧配置面板 ── */
.config{padding:16px;overflow-y:auto;border-right:1px solid var(--border);display:flex;flex-direction:column;gap:12px;}
.section{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;}
.sec-title{font-size:10px;font-weight:600;color:var(--muted);letter-spacing:.4px;margin-bottom:10px;text-transform:uppercase;}

/* 模型按钮组 */
.model-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;}
.model-btn{display:flex;align-items:center;gap:7px;padding:8px 10px;border-radius:8px;border:1.5px solid var(--border);background:var(--btn-bg);cursor:pointer;transition:.18s;text-align:left;}
.model-btn:hover{background:var(--btn-hov);}
.model-btn.selected{border-color:var(--dot-color,#667eea);background:rgba(var(--dot-rgb,102 126 234)/.12);}
.model-dot{width:9px;height:9px;border-radius:50%;flex-shrink:0;}
.model-name{font-size:11px;font-weight:600;color:var(--text);}
.model-engine{font-size:9px;color:var(--muted);}

/* 输入区 */
.tab-input{display:none;flex-direction:column;gap:8px;}
.tab-input.active{display:flex;}
label.lbl{font-size:10px;color:var(--muted);font-weight:500;}
textarea,input[type=text],input[type=file]{width:100%;padding:8px 10px;background:var(--btn-bg);border:1px solid var(--btn-bg);border-radius:7px;color:var(--text);font-size:12px;font-family:inherit;outline:none;transition:border-color .2s;}
textarea{min-height:70px;resize:vertical;}
textarea:focus,input:focus{border-color:rgba(255,255,255,.2);}
input[type=file]{color:var(--muted);}

/* 滑块 */
.slider-row{display:flex;align-items:center;gap:8px;}
.slider-row label{font-size:10px;color:var(--muted);white-space:nowrap;}
.slider-row input[type=range]{flex:1;accent-color:var(--as);}
.slider-val{font-size:11px;color:var(--text);min-width:24px;text-align:right;}

/* 预热选项 */
.warmup-row{display:flex;align-items:center;gap:6px;padding:4px 0;}
.warmup-row input[type=checkbox]{accent-color:var(--as);}
.warmup-row span{font-size:11px;color:var(--muted);}

/* 运行按钮 */
.action-row{display:flex;gap:8px;align-items:center;}
.run-btn{flex:1;display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:9px;border-radius:8px;border:none;background:linear-gradient(135deg,var(--as),var(--ae));color:#fff;font-size:13px;font-weight:600;cursor:pointer;transition:opacity .18s;}
.run-btn:disabled{opacity:.4;cursor:not-allowed;}
.run-btn:not(:disabled):hover{opacity:.88;}
.clear-btn{padding:8px 12px;border-radius:8px;border:1px solid var(--border);background:var(--btn-bg);color:var(--muted);font-size:11px;cursor:pointer;transition:.18s;}
.clear-btn:hover{background:var(--btn-hov);color:var(--text);}

/* loading */
.loading{display:none;align-items:center;gap:6px;font-size:11px;color:var(--muted);}
.loading.show{display:flex;}
.spinner{width:12px;height:12px;border-radius:50%;border:2px solid rgba(255,255,255,.1);border-top-color:var(--as);animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}

/* ── 右侧结果面板 ── */
.results{padding:16px;overflow-y:auto;display:flex;flex-direction:column;gap:12px;}

/* vision 画布区 */
.vision-ws{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:12px;}
.ws-top{display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;gap:8px;flex-wrap:wrap;}
.ws-title{font-size:11px;font-weight:600;color:var(--muted);}
.legend{display:flex;gap:8px;flex-wrap:wrap;}
.legend-item{display:flex;align-items:center;gap:4px;font-size:10px;color:var(--muted);}
.legend-dot{width:8px;height:8px;border-radius:50%;}
.canvas-wrap{position:relative;display:inline-block;border-radius:8px;overflow:hidden;border:1px solid var(--border);background:#000;max-width:100%;}
.canvas-wrap img{display:block;max-width:100%;height:auto;}
#dotCanvas{position:absolute;top:0;left:0;width:100%;height:100%;pointer-events:none;}

/* 对比摘要表 */
.summary{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;}
.summary-head{padding:10px 14px;border-bottom:1px solid var(--border);font-size:11px;font-weight:600;color:var(--muted);}
.summary-table{width:100%;border-collapse:collapse;font-size:11px;}
.summary-table th{padding:7px 10px;text-align:left;color:var(--muted);font-weight:500;border-bottom:1px solid var(--border);}
.summary-table td{padding:7px 10px;border-bottom:1px solid rgba(255,255,255,.04);}
.summary-table tr:last-child td{border-bottom:none;}
.best{color:var(--green);font-weight:600;}

/* 历史列表 */
.history-head{display:flex;align-items:center;justify-content:space-between;}
.history-head span{font-size:11px;font-weight:600;color:var(--muted);}
.count-badge{background:var(--bdg);border-radius:20px;padding:2px 8px;font-size:10px;color:var(--muted);}
.empty{text-align:center;padding:32px;color:var(--muted);font-size:12px;}

/* 历史卡片 */
.hist-card{background:var(--card);border:1px solid var(--border);border-radius:10px;overflow:hidden;transition:.2s;}
.hist-head{display:flex;align-items:center;justify-content:space-between;padding:9px 13px;background:var(--btn-bg);}
.hist-model{display:flex;align-items:center;gap:6px;font-size:11px;font-weight:600;}
.hist-badges{display:flex;align-items:center;gap:6px;}
.time-badge{font-family:'JetBrains Mono',monospace;font-size:10px;padding:2px 7px;border-radius:12px;background:var(--bdg);color:var(--muted);}
.time-badge.fast{background:rgba(74,222,128,.12);color:var(--green);}
.ok-badge{font-size:9px;padding:2px 6px;border-radius:10px;}
.ok-badge.ok{background:rgba(74,222,128,.12);color:var(--green);}
.ok-badge.fail{background:rgba(248,113,113,.12);color:var(--red);}
.warmup-tag{font-size:9px;padding:2px 6px;border-radius:10px;background:rgba(250,204,21,.1);color:#facc15;}
.hist-body{padding:10px 13px;}
.coord-txt{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text);margin-bottom:6px;}
.json-pre{background:rgba(0,0,0,.3);border-radius:7px;padding:8px 10px;font-size:10px;font-family:'JetBrains Mono',monospace;color:#a5f3fc;overflow-x:auto;white-space:pre-wrap;word-break:break-all;max-height:160px;overflow-y:auto;border:1px solid rgba(255,255,255,.05);}
.json-pre.err{color:var(--red);}
.speed-row{display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid var(--border);font-size:11px;}
.speed-row:last-child{border-bottom:none;}
.speed-val{font-family:'JetBrains Mono',monospace;font-weight:600;}
.bar-wrap{height:3px;background:rgba(255,255,255,.06);border-radius:2px;margin-top:8px;overflow:hidden;}
.bar{height:100%;border-radius:2px;background:linear-gradient(90deg,var(--as),var(--ae));transition:width .5s ease;}
</style>
<script>
(function(){if(localStorage.getItem('qa_theme')==='light')document.documentElement.setAttribute('data-theme','light');})();
</script>
</head>
<body>

<!-- 顶栏 -->
<div class="topbar">
  <div class="topbar-left">
    <div class="logo">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 2v7.31"></path><path d="M14 9.3V2"></path><path d="M8.5 2h7"></path><path d="M14 9.3a6.5 6.5 0 1 1-4 0"></path><line x1="5.52" y1="16" x2="18.48" y2="16"></line></svg>
    </div>
    <div>
      <div class="topbar h1" style="font-size:14px;font-weight:600;">模型测试台</div>
      <div class="topbar-sub">单模型独立运行 · 历史结果对比</div>
    </div>
  </div>
  <div style="display:flex; align-items:center; gap:16px;">
    <button class="theme-toggle" id="themeToggleBtn" onclick="toggleTheme()" title="切换明/暗主题">
        <!-- SVG -->
    </button>
    <a class="back" href="/" style="display:flex;align-items:center;gap:4px;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="19" y1="12" x2="5" y2="12"></line><polyline points="12 19 5 12 12 5"></polyline></svg> 返回控制台</a>
  </div>
</div>

<!-- Tab 选择 -->
<div class="tabs">
  <button class="tab-btn active" onclick="switchTab('intent',this)" style="display:inline-flex; align-items:center; gap:5px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 1.98-3A2.5 2.5 0 0 1 9.5 2Z"></path><path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-1.98-3A2.5 2.5 0 0 0 14.5 2Z"></path></svg> 意图解析</button>
  <button class="tab-btn" onclick="switchTab('vision',this)" style="display:inline-flex; align-items:center; gap:5px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"></path><circle cx="12" cy="12" r="3"></circle></svg> 视觉定位</button>
  <button class="tab-btn" onclick="switchTab('speed',this)" style="display:inline-flex; align-items:center; gap:5px;"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"></polygon></svg> 速度基准</button>
</div>

<!-- 主布局 -->
<div class="layout">

  <!-- 左侧配置 -->
  <div class="config">

    <!-- 模型选择 -->
    <div class="section">
      <div class="sec-title">选择模型</div>
      <div class="model-grid" id="modelGrid"></div>
    </div>

    <!-- 测试输入 (按 Tab 切换) -->
    <div class="section">
      <div id="inp-intent" class="tab-input active">
        <label class="lbl">测试语句</label>
        <textarea id="intentText" placeholder="例：帮我给晴天发一条微信说明天上午九点开会"></textarea>
      </div>
      <div id="inp-vision" class="tab-input">
        <label class="lbl">上传截图</label>
        <input type="file" id="visionFile" accept="image/*" onchange="onImgLoad(this)">
        <label class="lbl" style="margin-top:6px;">元素描述</label>
        <input type="text" id="visionDesc" placeholder="例：右上角的绿色 + 添加按钮">
      </div>
      <div id="inp-speed" class="tab-input">
        <p style="font-size:11px;color:var(--muted);line-height:1.7;">
          将发送固定中文 Prompt 测量推理速度。<br>
          点击 <strong style="color:var(--text)">运行</strong> 即可开始，结果追加到历史。
        </p>
      </div>
    </div>

    <!-- 选项 -->
    <div class="section">
      <div class="warmup-row">
        <input type="checkbox" id="warmupCheck">
        <span>预热模式 <span style="font-size:9px;">（先发一次短包丢弃冷启动时间）</span></span>
      </div>
    </div>

    <!-- 操作 -->
    <div class="action-row">
      <button class="run-btn" id="runBtn" onclick="runBenchmark()">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" stroke="none"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg> 运行
      </button>
      <button class="clear-btn" onclick="clearHistory()" style="display:flex;align-items:center;justify-content:center;">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
      </button>
    </div>
    <div class="loading" id="mainLoading">
      <div class="spinner"></div>
      <span id="loadingTxt">正在请求模型...</span>
    </div>

  </div><!-- /config -->

  <!-- 右侧结果 -->
  <div class="results" id="resultsPanel">

    <!-- Vision 画布工作台 -->
    <div class="vision-ws" id="visionWS" style="display:none;">
      <div class="ws-top">
        <span class="ws-title">视觉定位画布</span>
        <div class="legend" id="dotLegend"></div>
        <div class="slider-row">
          <label>标记大小</label>
          <input type="range" id="dotSize" min="6" max="40" value="14" oninput="redrawDots()">
          <span class="slider-val" id="dotSizeVal">14</span>
        </div>
      </div>
      <div class="canvas-wrap">
        <img id="visionPreview" src="" alt="">
        <canvas id="dotCanvas"></canvas>
      </div>
    </div>

    <!-- 对比摘要 -->
    <div class="summary" id="summaryWrap" style="display:none;">
      <div class="summary-head" style="display:flex; align-items:center; gap:5px;">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="20" x2="12" y2="10"></line><line x1="18" y1="20" x2="18" y2="4"></line><line x1="6" y1="20" x2="6" y2="16"></line></svg> 快速对比（本次 Tab 所有运行）
      </div>
      <table class="summary-table">
        <thead><tr><th>模型</th><th>耗时</th><th>额外指标</th></tr></thead>
        <tbody id="summaryBody"></tbody>
      </table>
    </div>

    <!-- 历史 -->
    <div class="history-head">
      <span>历史记录</span>
      <span class="count-badge" id="histCount">0 条</span>
    </div>
    <div id="histList"><div class="empty">选择模型并点击运行，结果将显示在这里</div></div>

  </div><!-- /results -->
</div><!-- /layout -->

<script>
// ── 模型注册表 ─────────────────────────────────────────────
const MODELS = [
  {id:'omlx_26b',  label:'Gemma 4 26B', engine:'oMLX',   color:'#60a5fa'},
  {id:'omlx_31b',  label:'Gemma 4 31B', engine:'oMLX',   color:'#818cf8'},
  {id:'ollama_26b',label:'Gemma 4 26B', engine:'Ollama', color:'#facc15'},
  {id:'ollama_31b',label:'Gemma 4 31B', engine:'Ollama', color:'#fb923c'},
];

// ── 状态 ────────────────────────────────────────────────────
let currentTab   = 'intent';
let selectedModel = 'omlx_26b';
let history      = {intent:[], vision:[], speed:[]};  // 每个 Tab 独立历史
let visionDots   = [];   // 当前 vision tab 的所有坐标点 [{label,color,nx,ny}]
let visionImgNW  = 0, visionImgNH = 0;  // 图片原始尺寸
let visionB64    = '';

// ── 主题与 SVG 常量 ──────────────────────────────────────────
const SVG_MOON = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>`;
const SVG_SUN = `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>`;

function toggleTheme() {
    const root = document.documentElement;
    const btn = document.getElementById('themeToggleBtn');
    const isLight = root.getAttribute('data-theme') === 'light';
    if (isLight) {
        root.removeAttribute('data-theme');
        if(btn) btn.innerHTML = SVG_MOON;
        localStorage.setItem('qa_theme', 'dark');
    } else {
        root.setAttribute('data-theme', 'light');
        if(btn) btn.innerHTML = SVG_SUN;
        localStorage.setItem('qa_theme', 'light');
    }
}

// ── 初始化 ──────────────────────────────────────────────────
(function init() {
  // 设置主题按钮初始状态
  const btn = document.getElementById('themeToggleBtn');
  if (btn) btn.innerHTML = document.documentElement.getAttribute('data-theme') === 'light' ? SVG_SUN : SVG_MOON;

  // 渲染模型按钮
  const grid = document.getElementById('modelGrid');
  MODELS.forEach(m => {
    const btn = document.createElement('button');
    btn.className = 'model-btn' + (m.id === selectedModel ? ' selected' : '');
    btn.dataset.id = m.id;
    btn.style.setProperty('--dot-color', m.color);
    btn.innerHTML = `
      <span class="model-dot" style="background:${m.color}"></span>
      <div>
        <div class="model-name">${m.label}</div>
        <div class="model-engine">${m.engine}</div>
      </div>`;
    btn.onclick = () => selectModel(m.id);
    grid.appendChild(btn);
  });
})();

// ── Tab ─────────────────────────────────────────────────────
function switchTab(id, el) {
  currentTab = id;
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  document.querySelectorAll('.tab-input').forEach(p => p.classList.remove('active'));
  document.getElementById('inp-'+id).classList.add('active');
  renderHistory();
  // vision 工作台显示控制
  document.getElementById('visionWS').style.display = id==='vision' ? '' : 'none';
}

// ── 模型选择 ────────────────────────────────────────────────
function selectModel(id) {
  selectedModel = id;
  document.querySelectorAll('.model-btn').forEach(b => {
    b.classList.toggle('selected', b.dataset.id === id);
  });
}

// ── 运行 ─────────────────────────────────────────────────────
async function runBenchmark() {
  const warmup = document.getElementById('warmupCheck').checked;
  const m = MODELS.find(x => x.id === selectedModel);

  document.getElementById('runBtn').disabled = true;
  const loadEl = document.getElementById('mainLoading');
  loadEl.classList.add('show');

  const wTxt = warmup ? ' (含预热)' : '';
  document.getElementById('loadingTxt').textContent =
    `正在请求 ${m.engine} ${m.label}${wTxt}...`;

  try {
    if (currentTab === 'intent') await runIntent(warmup, m);
    else if (currentTab === 'vision') await runVision(warmup, m);
    else await runSpeed(warmup, m);
  } catch(e) {
    alert('请求失败：'+e.message);
  } finally {
    document.getElementById('runBtn').disabled = false;
    loadEl.classList.remove('show');
  }
}

// ── 意图解析 ─────────────────────────────────────────────────
async function runIntent(warmup, m) {
  const text = document.getElementById('intentText').value.trim();
  if (!text) { alert('请输入测试语句'); return; }
  const t_start = Date.now();
  const res = await fetch('/api/benchmark/intent', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({text, model_id: m.id, warmup})
  });
  const d = await res.json();
  const total_elapsed = (Date.now() - t_start) / 1000;
  if (!d.success) { alert('失败：'+(d.error||'')); return; }
  history.intent.unshift({...d, input: text, ts: Date.now(), total_elapsed});
  renderHistory();
}

// ── 视觉定位 ─────────────────────────────────────────────────
async function runVision(warmup, m) {
  if (!visionB64) { alert('请先上传截图'); return; }
  const desc = document.getElementById('visionDesc').value.trim();
  if (!desc) { alert('请输入元素描述'); return; }
  const t_start = Date.now();
  const res = await fetch('/api/benchmark/vision', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({
      image_b64: visionB64, desc, model_id: m.id, warmup,
      img_w: visionImgNW, img_h: visionImgNH
    })
  });
  const d = await res.json();
  const total_elapsed = (Date.now() - t_start) / 1000;
  if (!d.success) { alert('失败：'+(d.error||'')); return; }
  history.vision.unshift({...d, input: desc, ts: Date.now(), total_elapsed});

  // 如果有归一化坐标，加入画布点
  if (d.norm_coord) {
    visionDots.push({label:d.label, color:d.color, nx:d.norm_coord.x, ny:d.norm_coord.y});
    updateLegend();
    redrawDots();
  }
  renderHistory();
}

// ── 速度基准 ─────────────────────────────────────────────────
async function runSpeed(warmup, m) {
  const t_start = Date.now();
  const res = await fetch('/api/benchmark/speed', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({model_id: m.id, warmup})
  });
  const d = await res.json();
  const total_elapsed = (Date.now() - t_start) / 1000;
  if (!d.success) { alert('失败：'+(d.error||'')); return; }
  history.speed.unshift({...d, ts: Date.now(), total_elapsed});
  renderHistory();
}

// ── 图片上传 ─────────────────────────────────────────────────
function onImgLoad(input) {
  const file = input.files[0]; if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    visionB64 = e.target.result.split(',')[1];
    const img = document.getElementById('visionPreview');
    img.src = e.target.result;
    img.onload = () => {
      visionImgNW = img.naturalWidth;
      visionImgNH = img.naturalHeight;
      document.getElementById('visionWS').style.display = '';
      // 新图片清空旧点
      visionDots = [];
      updateLegend();
      clearCanvas();
    };
  };
  reader.readAsDataURL(file);
}

// ── Canvas ───────────────────────────────────────────────────
function clearCanvas() {
  const c = document.getElementById('dotCanvas');
  const img = document.getElementById('visionPreview');
  c.width = img.clientWidth; c.height = img.clientHeight;
  c.getContext('2d').clearRect(0,0,c.width,c.height);
}

function redrawDots() {
  const sz = parseInt(document.getElementById('dotSize').value);
  document.getElementById('dotSizeVal').textContent = sz;
  const c = document.getElementById('dotCanvas');
  const img = document.getElementById('visionPreview');
  c.width = img.clientWidth; c.height = img.clientHeight;
  const ctx = c.getContext('2d');
  ctx.clearRect(0,0,c.width,c.height);
  visionDots.forEach(pt => {
    const px = pt.nx * c.width, py = pt.ny * c.height;
    // 光晕
    ctx.beginPath(); ctx.arc(px,py,sz+5,0,Math.PI*2);
    ctx.fillStyle = pt.color+'28'; ctx.fill();
    // 实心圆
    ctx.beginPath(); ctx.arc(px,py,sz/2,0,Math.PI*2);
    ctx.fillStyle = pt.color; ctx.fill();
    // 十字
    ctx.strokeStyle = pt.color; ctx.lineWidth = 1.5; ctx.globalAlpha = .7;
    ctx.beginPath();
    ctx.moveTo(px-sz,py); ctx.lineTo(px+sz,py);
    ctx.moveTo(px,py-sz); ctx.lineTo(px,py+sz);
    ctx.stroke(); ctx.globalAlpha = 1;
  });
}

function updateLegend() {
  const el = document.getElementById('dotLegend');
  el.innerHTML = visionDots.map(pt =>
    `<div class="legend-item">
      <span class="legend-dot" style="background:${pt.color}"></span>
      ${escHtml(pt.label)}
    </div>`).join('');
}

window.addEventListener('resize', () => { if(visionDots.length) redrawDots(); });

// ── 清空历史 ─────────────────────────────────────────────────
function clearHistory() {
  if (!confirm('确认清空当前 Tab 的历史记录？')) return;
  history[currentTab] = [];
  if (currentTab === 'vision') { visionDots = []; updateLegend(); clearCanvas(); }
  renderHistory();
}

// ── 渲染历史 ─────────────────────────────────────────────────
function renderHistory() {
  const list = history[currentTab];
  document.getElementById('histCount').textContent = list.length + ' 条';

  // 对比摘要
  renderSummary(list);

  const el = document.getElementById('histList');
  if (list.length === 0) {
    el.innerHTML = '<div class="empty">运行测试后，结果将显示在这里</div>';
    return;
  }
  el.innerHTML = list.map((r,i) => renderCard(r, i)).join('');
}

function renderCard(r, i) {
  const m = MODELS.find(x => x.id === r.model_id) || {};
  const warmupTag = r.warmup_elapsed != null
    ? `<span class="warmup-tag">预热 ${r.warmup_elapsed}s</span>` : '';
  const timeCls = isFastest(r) ? 'fast' : '';

  let body = '';
  if (currentTab === 'intent') {
    const status = r.error ? 'fail' : (r.parsed_ok ? 'ok' : 'fail');
    const statusTxt = r.error ? '✗ 请求失败' : (r.parsed_ok ? '✓ JSON 解析' : '✗ 解析失败');
    body = `
      <div class="hist-body">
        <div style="margin-bottom:6px;font-size:10px;color:var(--muted);">
          输入：<span style="color:var(--text)">${escHtml(r.input||'')}</span>
        </div>
        <span class="ok-badge ${status}" style="margin-bottom:8px;display:inline-block;">${statusTxt}</span>
        ${r.error
          ? `<div class="json-pre err">${escHtml(r.error)}</div>`
          : `<pre class="json-pre">${escHtml(JSON.stringify(r.parsed||r.raw,null,2))}</pre>`}
      </div>`;
  } else if (currentTab === 'vision') {
    const nc = r.norm_coord;
    const coordTxt = nc
      ? `像素: (${nc.px}, ${nc.py}) · 归一化: (${nc.x}, ${nc.y})`
      : (r.error ? '请求失败' : '坐标解析失败');
    const dotColor = m.color || '#fff';
    body = `
      <div class="hist-body">
        <div style="font-size:10px;color:var(--muted);margin-bottom:4px;">
          描述：<span style="color:var(--text)">${escHtml(r.input||'')}</span>
        </div>
        <div class="coord-txt" style="color:${nc?'var(--text)':'var(--red)'}">
          <span class="model-dot" style="background:${dotColor};display:inline-block;margin-right:4px;vertical-align:middle;"></span>
          ${escHtml(coordTxt)}
        </div>
        ${r.error
          ? `<div class="json-pre err">${escHtml(r.error)}</div>`
          : `<pre class="json-pre">${escHtml(r.raw||'')}</pre>`}
      </div>`;
  } else {
    // speed
    const maxTps = Math.max(...history.speed.map(x=>x.tps||0));
    const barPct = maxTps > 0 ? Math.round((r.tps||0)/maxTps*100) : 0;
    body = `
      <div class="hist-body">
        <div class="speed-row"><span>Token/s</span>
          <span class="speed-val" style="color:${isFastest(r)?'var(--green)':'var(--text)'}">${r.tps??'—'}</span></div>
        <div class="speed-row"><span>输入 tokens</span><span class="speed-val">${r.prompt_tokens||'—'}</span></div>
        <div class="speed-row"><span>输出 tokens</span><span class="speed-val">${r.completion_tokens||'—'}</span></div>
        <div class="bar-wrap"><div class="bar" style="width:${barPct}%"></div></div>
        ${r.preview?`<div style="margin-top:8px;font-size:10px;color:var(--muted);line-height:1.6">${escHtml(r.preview)}…</div>`:''}
        ${r.error?`<div class="json-pre err" style="margin-top:8px">${escHtml(r.error)}</div>`:''}
      </div>`;
  }

  return `
    <div class="hist-card" id="hcard-${i}">
      <div class="hist-head">
        <div class="hist-model">
          <span class="model-dot" style="background:${m.color||'#fff'}"></span>
          ${escHtml(r.label||'')}
        </div>
        <div class="hist-badges" style="display:flex; flex-direction:column; align-items:flex-end;">
          <div style="display:flex; gap:6px; align-items:center;">
             ${warmupTag}
             <span class="time-badge ${timeCls}">网终总计: ${fmtT(r.total_elapsed)}</span>
             <span class="time-badge ${timeCls}" style="opacity:0.8;">纯推理: ${fmtT(r.elapsed)}</span>
          </div>
          <div style="font-size:9px;color:rgba(255,255,255,0.3);margin-top:2px;">
             I/O及解析开销: ${r.total_elapsed && r.elapsed ? fmtT(r.total_elapsed - r.elapsed) : '—'}
          </div>
        </div>
      </div>
      ${body}
    </div>`;
}

function renderSummary(list) {
  const sw = document.getElementById('summaryWrap');
  // 只统计成功没有 error 的记录
  const validList = list.filter(r => !r.error);
  if (validList.length < 2) { sw.style.display='none'; return; }
  sw.style.display = '';

  // 按 model_id 分组取最佳
  const best = {};
  validList.forEach(r => {
    if (!best[r.model_id] || r.elapsed < best[r.model_id].elapsed) best[r.model_id] = r;
  });
  const rows = Object.values(best).sort((a,b)=>a.elapsed-b.elapsed);
  const minT = rows[0].elapsed;

  const tbody = document.getElementById('summaryBody');
  tbody.innerHTML = rows.map(r => {
    const extra = currentTab==='speed'
      ? (r.tps != null ? r.tps+' tok/s' : '—')
      : (currentTab==='vision' && r.norm_coord
        ? `(${r.norm_coord.x}, ${r.norm_coord.y})`
        : (r.parsed_ok != null ? (r.parsed_ok?'✓':'✗') : '—'));
    const m = MODELS.find(x=>x.id===r.model_id)||{};
    return `<tr>
      <td><span class="model-dot" style="background:${m.color||'#fff'};display:inline-block;margin-right:5px;vertical-align:middle;"></span>${escHtml(r.label||'')}</td>
      <td class="${r.elapsed===minT?'best':''}">${fmtT(r.elapsed)}</td>
      <td style="color:var(--muted)">${extra}</td>
    </tr>`;
  }).join('');
}

// ── 辅助函数 ────────────────────────────────────────────────
function isFastest(r) {
  const list = history[currentTab];
  if (list.length === 0) return false;
  const minT = Math.min(...list.map(x=>x.elapsed));
  return r.elapsed === minT;
}

function fmtT(s) {
  return s >= 60 ? (s/60).toFixed(1)+' min' : s.toFixed(2)+' s';
}

function fmtDate(ts) {
  const d = new Date(ts);
  return d.getHours().toString().padStart(2,'0')+':'+
    d.getMinutes().toString().padStart(2,'0')+':'+
    d.getSeconds().toString().padStart(2,'0');
}

function escHtml(s) {
  return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
</script>
</body>
</html>'''
