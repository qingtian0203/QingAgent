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

# 任务队列：异步执行，避免 HTTP 超时
_tasks: dict = {}  # task_id -> {"status": "running"/"done", "result": {...}}
_task_counter = 0
_task_lock = threading.Lock()


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
        elif parsed.path == "/api/skills":
            self._api_skills()
        elif parsed.path == "/api/health":
            self._json_response({"status": "ok", "version": "0.1.0"})
        elif parsed.path.startswith("/api/task/"):
            task_id = parsed.path.split("/")[-1]
            self._api_task_status(task_id)
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

                # 异步执行：立即返回 task_id，前端轮询结果
                global _task_counter
                with _task_lock:
                    _task_counter += 1
                    task_id = str(_task_counter)
                    _tasks[task_id] = {"status": "running", "result": None, "command": command}

                thread = threading.Thread(
                    target=self._run_task, args=(task_id, command), daemon=True
                )
                thread.start()

                self._json_response({"task_id": task_id, "status": "running"})

            except json.JSONDecodeError:
                self._json_response({"success": False, "message": "请求格式错误"})
        elif parsed.path.startswith("/api/cancel/"):
            task_id = parsed.path.split("/")[-1]
            if task_id in _tasks:
                _tasks[task_id]["status"] = "cancelled"
            self._json_response({"success": True})
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
        """在后台线程中执行任务"""
        try:
            cancel_check = lambda: _tasks.get(task_id, {}).get("status") == "cancelled"
            result = _planner.execute(command, cancel_check=cancel_check)
            # 如果在执行完毕后发现用户中途点了取消，就不要强行标记为 done（防止诈尸）
            if not cancel_check():
                _tasks[task_id] = {"status": "done", "result": result}
        except Exception as e:
            if _tasks.get(task_id, {}).get("status") != "cancelled":
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

        if task["status"] == "running":
            self._json_response({"status": "running", "task_id": task_id})
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


def start_server(host: str = None, port: int = None):
    """启动 Web 服务"""
    global _planner

    registry = SkillRegistry()
    registry.auto_register()
    _planner = Planner(registry)

    h = host or config.SERVER_HOST
    p = port or config.SERVER_PORT
    local_ip = _get_local_ip()

    server = HTTPServer((h, p), QingAgentHandler)
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
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <title>QingAgent</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');

        * { margin: 0; padding: 0; box-sizing: border-box; }

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

        /* === 快捷操作 === */
        .quick-bar {
            padding: 10px 16px;
            display: flex;
            gap: 8px;
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
            flex-shrink: 0;
            background: var(--bg-primary);
            border-bottom: 1px solid var(--border);
        }
        .quick-bar::-webkit-scrollbar { display: none; }

        .quick-chip {
            padding: 7px 14px;
            border-radius: 20px;
            border: 1px solid rgba(102,126,234,0.25);
            background: rgba(102,126,234,0.08);
            color: var(--accent-start);
            font-size: 12px;
            font-weight: 500;
            cursor: pointer;
            white-space: nowrap;
            transition: all 0.2s;
            -webkit-tap-highlight-color: transparent;
        }

        .quick-chip:active {
            background: rgba(102,126,234,0.2);
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
            padding: 12px 16px;
            padding-bottom: calc(12px + var(--safe-bottom));
            background: var(--bg-secondary);
            border-top: 1px solid var(--border);
            display: flex;
            gap: 10px;
            align-items: center;
            flex-shrink: 0;
        }

        .input-area input {
            flex: 1;
            padding: 12px 16px;
            border-radius: 24px;
            border: 1px solid rgba(255,255,255,0.08);
            background: var(--bg-card);
            color: white;
            font-size: 15px;
            font-family: inherit;
            outline: none;
            transition: border-color 0.2s;
            -webkit-appearance: none;
        }

        .input-area input:focus {
            border-color: var(--accent-start);
        }

        .input-area input::placeholder { color: #555; }

        .send-btn, .mic-btn {
            width: 44px; height: 44px;
            border-radius: 50%;
            border: none;
            color: white;
            font-size: 18px;
            cursor: pointer;
            display: flex; align-items: center; justify-content: center;
            transition: all 0.2s;
            flex-shrink: 0;
            -webkit-tap-highlight-color: transparent;
        }

        .send-btn {
            background: linear-gradient(135deg, var(--accent-start), var(--accent-end));
        }

        .mic-btn {
            background: rgba(255,255,255,0.08);
            border: 1px solid rgba(255,255,255,0.15);
            font-size: 20px;
            margin-right: 8px;
        }

        .mic-btn:hover {
            background: rgba(255,255,255,0.15);
        }

        .mic-btn.recording {
            background: rgba(239,68,68,0.25);
            border-color: #ef4444;
            animation: micPulse 1s ease-in-out infinite;
        }

        @keyframes micPulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(239,68,68,0.4); }
            50% { box-shadow: 0 0 0 10px rgba(239,68,68,0); }
        }

        .mic-btn.unsupported {
            opacity: 0.2;
            cursor: not-allowed;
        }

        .send-btn:active, .mic-btn:active { transform: scale(0.9); }
        .send-btn:disabled { opacity: 0.3; }
    </style>
</head>
<body>
<div class="app">
    <div class="header">
        <div class="header-avatar">🤖</div>
        <div class="header-info">
            <h1>QingAgent</h1>
            <p>晴帅的私人 AI 桌面助手</p>
        </div>
        <div class="status-dot" id="statusDot" title="在线"></div>
    </div>

    <div class="quick-bar">
        <div class="quick-chip" onclick="quickSend('给AI发条微信说测试消息')">📱 微信发消息</div>
        <div class="quick-chip" onclick="quickSend('看看工作群有没有新消息')">💬 查消息</div>
        <div class="quick-chip" onclick="quickSend('看看今天有什么任务')">📅 查日历</div>
        <div class="quick-chip" onclick="quickSend('打开晴天的API调试器')">🔧 API调试</div>
        <div class="quick-chip" onclick="quickSend('打开百度')">🌐 浏览器</div>
    </div>

    <div class="chat-area" id="chatArea">
        <div class="msg-row agent">
            <div class="msg-bubble">
                👋 你好晴帅！我已在你的电脑上待命。<br><br>
                发送自然语言指令，我来帮你操控桌面应用。
            </div>
        </div>
    </div>

    <div class="input-area">
        <input type="text" id="cmdInput" placeholder="输入指令..."
               enterkeyhint="send"
               onkeydown="if(event.key==='Enter'){event.preventDefault();sendCmd();}">
        <button class="mic-btn" id="micBtn" title="语音输入">🎤</button>
        <button class="send-btn" id="sendBtn" onclick="sendCmd()">➤</button>
    </div>
</div>

<script>
    const chatArea = document.getElementById('chatArea');
    const cmdInput = document.getElementById('cmdInput');
    const sendBtn = document.getElementById('sendBtn');
    const statusDot = document.getElementById('statusDot');
    const micBtn = document.getElementById('micBtn');

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
        _recognition.continuous = false;     // 单次识别模式
        _recognition.interimResults = true;  // 实时显示中间结果

        _recognition.onstart = () => {
            _isListening = true;
            micBtn.classList.add('recording');
            micBtn.textContent = '⏺';
            cmdInput.placeholder = '🎙 正在聆听...';
        };

        _recognition.onresult = (event) => {
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
            addMsg('⚠️ 当前浏览器不支持语音识别 (Web Speech API)。请使用 Chrome 浏览器。', 'agent', 'error');
        };
    }

    function stopListening() {
        _isListening = false;
        micBtn.classList.remove('recording');
        micBtn.textContent = '🎤';
        cmdInput.placeholder = '输入指令...';
        cmdInput.focus();
    }

    function now() {
        return new Date().toLocaleTimeString('zh-CN', {hour:'2-digit', minute:'2-digit'});
    }

    function addMsg(html, type, cls = '') {
        const row = document.createElement('div');
        row.className = `msg-row ${type} ${cls}`;
        row.innerHTML = `
            <div class="msg-bubble">${html}</div>
            <div class="msg-time">${now()}</div>
        `;
        chatArea.appendChild(row);
        chatArea.scrollTop = chatArea.scrollHeight;
        return row;
    }

    function quickSend(text) {
        if (isProcessing) return; // 拦截快捷指令
        cmdInput.value = text;
        sendCmd();
    }

    let _pollCancelled = false;  // 轮询中断标志
    let _cancelBtnCounter = 0;   // 按钮唯一 ID 计数器

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

        // 加载动画 + 计时器
        const loadingRow = addMsg(
            `正在执行操控...<div class="loading-dots"><span></span><span></span><span></span></div>
             <div style="display:flex; align-items:center; margin-top:4px;">
                 <div class="timer" id="${timerId}">⏱ 0s</div>
                 <button class="cancel-btn" id="${cancelBtnId}" style="display:none;">✖ 终止</button>
             </div>`,
            'agent'
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
                body: JSON.stringify({ command: cmd })
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
                    } else {
                        // 显示取消按钮
                        const cb = document.getElementById(cancelBtnId);
                        if (cb) {
                            cb.style.display = 'inline-block';
                            cb.onclick = () => cancelTask(taskId, timerInterval, loadingRow);
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
            content += `<div class="msg-data">${data.data}</div>`;
        }
        addMsg(content, 'agent', data.success ? 'success' : 'error');
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
</script>
</body>
</html>'''
