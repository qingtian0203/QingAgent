from __future__ import annotations

"""
Web 服务 — 提供 HTTP API 和简单的 Web 界面

可以通过浏览器或手机访问，发送自然语言指令。
"""
import json
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import os

from .. import config
from ..skills import SkillRegistry
from ..planner.planner import Planner


# 全局实例（在启动时初始化）
_planner: Planner = None


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

                result = _planner.execute(command)
                self._json_response(result)

            except json.JSONDecodeError:
                self._json_response({"success": False, "message": "请求格式错误"})
        else:
            self.send_error(404)

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
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def log_message(self, format, *args):
        """静默普通访问日志，只打印错误"""
        if args and "404" in str(args):
            super().log_message(format, *args)


def start_server(host: str = None, port: int = None):
    """启动 Web 服务"""
    global _planner

    # 初始化 Skill 注册中心和 Planner
    registry = SkillRegistry()
    registry.auto_register()
    _planner = Planner(registry)

    h = host or config.SERVER_HOST
    p = port or config.SERVER_PORT

    server = HTTPServer((h, p), QingAgentHandler)
    print(f"\n{'='*50}")
    print(f"🚀 QingAgent Web 服务已启动")
    print(f"🌐 本机访问: http://localhost:{p}")
    print(f"📱 手机访问: http://<你的IP>:{p}")
    print(f"{'='*50}\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 服务已停止")
        server.server_close()


def _get_ui_html() -> str:
    """内嵌的 Web 界面 HTML"""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>QingAgent - 晴帅的 AI 助手</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif;
            background: #0a0a0f;
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        .header {
            padding: 20px 24px;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }

        .header h1 {
            font-size: 20px;
            font-weight: 600;
            background: linear-gradient(135deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .header p {
            font-size: 13px;
            color: #666;
            margin-top: 4px;
        }

        .chat-area {
            flex: 1;
            overflow-y: auto;
            padding: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .msg {
            max-width: 85%;
            padding: 12px 16px;
            border-radius: 16px;
            font-size: 14px;
            line-height: 1.6;
            animation: fadeIn 0.3s ease;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(8px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .msg.user {
            align-self: flex-end;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            border-bottom-right-radius: 4px;
        }

        .msg.agent {
            align-self: flex-start;
            background: #1a1a2e;
            border: 1px solid rgba(255,255,255,0.08);
            border-bottom-left-radius: 4px;
        }

        .msg.agent.success { border-left: 3px solid #4ade80; }
        .msg.agent.error { border-left: 3px solid #f87171; }
        .msg.agent.loading {
            border-left: 3px solid #667eea;
            color: #888;
        }

        .input-area {
            padding: 16px 20px;
            background: #111118;
            border-top: 1px solid rgba(255,255,255,0.06);
            display: flex;
            gap: 10px;
        }

        .input-area input {
            flex: 1;
            padding: 12px 16px;
            border-radius: 12px;
            border: 1px solid rgba(255,255,255,0.1);
            background: #1a1a2e;
            color: white;
            font-size: 15px;
            outline: none;
            transition: border-color 0.2s;
        }

        .input-area input:focus {
            border-color: #667eea;
        }

        .input-area input::placeholder { color: #555; }

        .input-area button {
            padding: 12px 20px;
            border-radius: 12px;
            border: none;
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: white;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            transition: opacity 0.2s;
        }

        .input-area button:hover { opacity: 0.85; }
        .input-area button:disabled { opacity: 0.4; cursor: not-allowed; }

        .quick-actions {
            padding: 12px 20px;
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
            background: #0d0d14;
        }

        .quick-btn {
            padding: 6px 14px;
            border-radius: 20px;
            border: 1px solid rgba(255,255,255,0.1);
            background: transparent;
            color: #aaa;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .quick-btn:hover {
            border-color: #667eea;
            color: #667eea;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>🤖 QingAgent</h1>
        <p>晴帅的私人 AI 桌面助手 · 自然语言操控你的电脑</p>
    </div>

    <div class="quick-actions">
        <button class="quick-btn" onclick="quickSend('看看工作群有没有新消息')">📱 查微信消息</button>
        <button class="quick-btn" onclick="quickSend('看看今天有什么任务')">📅 查日历</button>
        <button class="quick-btn" onclick="quickSend('打开晴天的API调试器')">🔧 API调试器</button>
        <button class="quick-btn" onclick="quickSend('打开百度')">🌐 打开浏览器</button>
    </div>

    <div class="chat-area" id="chatArea">
        <div class="msg agent">
            👋 你好晴帅！我是 QingAgent，你的私人桌面助手。<br><br>
            试试说：<em>"给晴天发条微信说下午开会"</em>
        </div>
    </div>

    <div class="input-area">
        <input type="text" id="cmdInput" placeholder="输入自然语言指令..."
               onkeydown="if(event.key===\'Enter\')sendCmd()">
        <button id="sendBtn" onclick="sendCmd()">发送</button>
    </div>

    <script>
        const chatArea = document.getElementById('chatArea');
        const cmdInput = document.getElementById('cmdInput');
        const sendBtn = document.getElementById('sendBtn');

        function addMessage(text, type, extraClass = '') {
            const div = document.createElement('div');
            div.className = `msg ${type} ${extraClass}`;
            div.innerHTML = text;
            chatArea.appendChild(div);
            chatArea.scrollTop = chatArea.scrollHeight;
            return div;
        }

        function quickSend(text) {
            cmdInput.value = text;
            sendCmd();
        }

        async function sendCmd() {
            const cmd = cmdInput.value.trim();
            if (!cmd) return;

            addMessage(cmd, 'user');
            cmdInput.value = '';
            sendBtn.disabled = true;

            const loadingMsg = addMessage('⏳ 正在执行...', 'agent', 'loading');

            try {
                const res = await fetch('/api/execute', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ command: cmd })
                });
                const data = await res.json();

                loadingMsg.remove();

                let content = data.message || '执行完成';
                if (data.data) {
                    content += '<br><br><pre style="white-space:pre-wrap;font-size:12px;color:#999;">'
                             + data.data + '</pre>';
                }

                addMessage(content, 'agent', data.success ? 'success' : 'error');
            } catch (e) {
                loadingMsg.remove();
                addMessage('❌ 网络错误：' + e.message, 'agent', 'error');
            }

            sendBtn.disabled = false;
            cmdInput.focus();
        }
    </script>
</body>
</html>'''
