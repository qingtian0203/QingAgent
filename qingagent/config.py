"""
全局配置 — 集中管理所有可调参数
"""
import os

# ============================================================
#  AI 视觉引擎配置
# ============================================================
# 本地 AI 模型（用于截图识别 + 意图理解）
VISION_MODEL = os.getenv("QA_VISION_MODEL", "gemma-4-26b-a4b-it-4bit")


# ── API 后端模式 ──────────────────────────────────────────────
# "ollama"  : Ollama 原生 /api/generate 格式（默认）
# "openai"  : OpenAI 兼容格式（oMLX / LM Studio / vLLM 等）
#
# 切换到 oMLX 只需两步：
#   1. 把 API_MODE 改为 "openai"
#   2. 把 OLLAMA_URL 改为 "http://localhost:8000/v1"
#      (oMLX 默认端口 8000，会自动补全 /chat/completions)
API_MODE  = os.getenv("QA_API_MODE",   "openai")            # 已切换到 oMLX
OLLAMA_URL = os.getenv("QA_OLLAMA_URL", "http://localhost:8000/v1")  # oMLX 地址
# oMLX / OpenAI 兼容后端的 API Key（Ollama 模式下留空即可）
API_KEY   = os.getenv("QA_API_KEY",    "68686688v")


VISION_TIMEOUT = 60  # 视觉识别超时（秒）
VISION_MAX_RETRIES = 3  # 识别失败最大重试次数

# Planner 用的模型（用于意图理解，可以和视觉模型不同）
PLANNER_MODEL = os.getenv("QA_PLANNER_MODEL", "gemma-4-26b-a4b-it-4bit")  # oMLX 模型 ID
PLANNER_URL = os.getenv("QA_PLANNER_URL", "http://localhost:8000/v1")      # oMLX 地址



# ============================================================
#  操作节奏配置
# ============================================================
# 点击后等待（秒）- 给应用留响应时间
ACTION_DELAY = 0.6
# 切换应用后等待（秒）
APP_SWITCH_DELAY = 1.5
# 缩略图唤醒后等待（秒）
THUMBNAIL_WAKE_DELAY = 1.5
# 最小窗口宽度（低于此判定为缩略图）
MIN_WINDOW_WIDTH = 400

# ============================================================
#  截图确认配置
# ============================================================
# 是否在每步操作后截图确认
VERIFY_AFTER_ACTION = True
# 确认截图保存目录（调试用）
DEBUG_SCREENSHOT_DIR = os.path.join(os.path.dirname(__file__), "..", "debug_screenshots")

# ============================================================
#  Web 服务配置
# ============================================================
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8077

# ============================================================
#  路径配置
# ============================================================
# 项目根目录（config.py 在 qingagent/ 下，根目录要向上一层）
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
