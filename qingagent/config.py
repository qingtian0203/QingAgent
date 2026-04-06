"""
全局配置 — 集中管理所有可调参数
"""
import os

# ============================================================
#  AI 视觉引擎配置
# ============================================================
# 本地 Ollama 多模态模型（用于截图识别）
VISION_MODEL = os.getenv("QA_VISION_MODEL", "gemma4:26b")
OLLAMA_URL = os.getenv("QA_OLLAMA_URL", "http://localhost:11434/api/generate")
VISION_TIMEOUT = 60  # 视觉识别超时（秒）
VISION_MAX_RETRIES = 3  # 识别失败最大重试次数

# Planner 用的模型（用于意图理解，可以和视觉模型不同）
PLANNER_MODEL = os.getenv("QA_PLANNER_MODEL", "gemma4:26b")
PLANNER_URL = os.getenv("QA_PLANNER_URL", "http://localhost:11434/api/generate")

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
