from __future__ import annotations

"""
视觉引擎模块 — 截图采集 + AI 视觉识别

负责对指定窗口区域截图，然后调用多模态大模型
在截图中定位目标元素，返回归一化坐标。

支持两种 API 后端（通过 config.API_MODE 切换）：
  - "ollama"   : Ollama 原生 /api/generate 格式（默认）
  - "openai"   : OpenAI 兼容格式（oMLX / LM Studio / vLLM 等）
"""
import io
import json
import base64
import time
import pyautogui
import requests
from .. import config


def _call_llm(prompt: str, img_b64: str | None = None) -> str | None:
    """
    统一的 LLM 调用入口，自动适配 Ollama / OpenAI 两种 API 格式。

    参数:
        prompt: 文字提示
        img_b64: 可选，base64 编码的图片（视觉任务）

    返回:
        模型返回的文字内容，失败返回 None
    """
    mode = getattr(config, "API_MODE", "ollama").lower()
    model = config.VISION_MODEL
    url   = config.OLLAMA_URL
    timeout = config.VISION_TIMEOUT

    if mode == "openai":
        # ── OpenAI 兼容格式（oMLX / LM Studio / vLLM）──────────────
        # URL 示例：http://localhost:8000/v1/chat/completions
        if not url.endswith("/chat/completions"):
            # 自动补全路径（用户只配置 base url 时）
            url = url.rstrip("/") + "/chat/completions"

        content: list = [{"type": "text", "text": prompt}]
        if img_b64:
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{img_b64}"}
            })

        payload = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "stream": False,
            "max_tokens": 512,
        }

        try:
            headers = {"Content-Type": "application/json"}
            api_key = getattr(config, "API_KEY", "")
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            res = requests.post(url, json=payload, headers=headers, timeout=timeout)
            res.raise_for_status()
            return res.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"❌ OpenAI API 调用失败：{e}")
            return None


    else:
        # ── Ollama 原生格式（默认）─────────────────────────────────
        payload: dict = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        if img_b64:
            payload["images"] = [img_b64]

        try:
            res = requests.post(url, json=payload, timeout=timeout)
            res.raise_for_status()
            return res.json().get("response", "").strip()
        except Exception as e:
            print(f"❌ Ollama API 调用失败：{e}")
            return None



def capture_screenshot(rect: tuple, save_path: str = None) -> str | None:
    """
    截取指定区域的屏幕截图。

    参数:
        rect: (x, y, w, h) 窗口物理坐标
        save_path: 可选，保存截图到文件（调试用）

    返回:
        base64 编码的 PNG 图片字符串，失败返回 None
    """
    try:
        screenshot = pyautogui.screenshot(region=rect)
        if save_path:
            screenshot.save(save_path)
            print(f"📸 调试截图已保存：{save_path}")

        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        return base64.b64encode(buf.getvalue()).decode("utf-8")
    except Exception as e:
        print(f"❌ 截图失败（请检查屏幕录制权限）：{e}")
        return None


def find_element(
    img_b64: str,
    description: str,
    context: str = "软件截图",
) -> dict | None:
    """
    用 AI 视觉模型在截图中定位元素。

    参数:
        img_b64: base64 编码的截图
        description: 要找的元素描述，如 "聊天输入框的中心"
        context: 截图上下文描述，如 "微信聊天界面" / "IDE界面"

    返回:
        {"rx": 0-1000, "ry": 0-1000} 归一化坐标，失败返回 None
    """
    prompt = (
        f"这是一张{context}。请找到【{description}】的精确中心位置。"
        f"只返回 JSON 格式: {{\"rx\": 0-1000, \"ry\": 0-1000}}，"
        f"其中 rx 和 ry 是该元素中心相对于图片宽高的千分比坐标。"
        f"不要返回任何其他文字。"
    )

    text = _call_llm(prompt, img_b64)
    if text is None:
        return None

    try:
        # 提取 JSON
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            print(f"⚠️ AI 返回内容无法解析为 JSON：{text[:100]}")
            return None

        coords = json.loads(clean[start:end])

        # 基本校验
        rx, ry = coords.get("rx", -1), coords.get("ry", -1)
        if not (0 <= rx <= 1000 and 0 <= ry <= 1000):
            print(f"⚠️ AI 返回坐标超出范围：rx={rx}, ry={ry}")
            return None

        return coords
    except Exception as e:
        print(f"❌ AI 识别失败：{e}")
        return None


def find_element_with_retry(
    img_b64: str,
    description: str,
    context: str = "软件截图",
    max_retries: int = None,
) -> dict | None:
    """
    带重试的元素定位 — 视觉 AI 不是 100% 准确，多试几次。

    参数:
        img_b64: 截图 base64
        description: 元素描述
        context: 截图上下文
        max_retries: 最大重试次数（默认使用配置值）

    返回:
        归一化坐标或 None
    """
    retries = max_retries or config.VISION_MAX_RETRIES

    for attempt in range(retries):
        if attempt > 0:
            print(f"🔄 第 {attempt + 1}/{retries} 次重试定位【{description}】...")
            time.sleep(1)

        result = find_element(img_b64, description, context)
        if result:
            return result

    print(f"❌ 经过 {retries} 次尝试仍无法定位【{description}】")
    return None


def find_elements_batch(
    img_b64: str,
    elements: dict[str, str],
    context: str = "软件截图",
) -> dict[str, dict] | None:
    """
    批量定位多个元素 — 一次截图一次 AI 调用，返回所有元素坐标。

    参数:
        img_b64: 截图 base64
        elements: {element_key: description}，如 {
            "input": "任务内容输入框",
            "today": "今天按钮",
            "confirm": "确认添加按钮",
        }
        context: 截图上下文描述

    返回:
        {element_key: {"rx": 0-1000, "ry": 0-1000}} 或 None
    """
    # 构建枚举描述
    element_list = "\n".join(
        f"- \"{k}\": {desc}" for k, desc in elements.items()
    )
    keys = list(elements.keys())
    empty_json = "{" + ", ".join(f'"{k}": {{"rx": ?, "ry": ?}}' for k in keys) + "}"

    prompt = (
        f"这是一张{context}。请同时找到以下所有元素的精确中心位置：\n"
        f"{element_list}\n\n"
        f"只返回 JSON 格式（所有 rx/ry 均为 0-1000 的千分比坐标）:\n"
        f"{empty_json}\n"
        f"不要返回任何其他文字。"
    )

    text = _call_llm(prompt, img_b64)
    if text is None:
        return None

    try:
        # 提取 JSON
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            print(f"⚠️ 批量定位 AI 返回无法解析：{text[:200]}")
            return None

        coords_map = json.loads(clean[start:end])

        # 校验每个坐标
        result = {}
        for k, v in coords_map.items():
            if not isinstance(v, dict):
                continue
            rx, ry = v.get("rx", -1), v.get("ry", -1)
            if 0 <= rx <= 1000 and 0 <= ry <= 1000:
                result[k] = {"rx": rx, "ry": ry}
            else:
                print(f"⚠️ 批量定位「{k}」坐标越界：rx={rx}, ry={ry}")

        return result if result else None

    except Exception as e:
        print(f"❌ 批量定位 AI 失败：{e}")
        return None


def read_screen_content(
    img_b64: str,
    question: str,
    context: str = "软件截图",
) -> str | None:
    """
    用 AI 阅读截图内容 — 不是定位元素，而是提取信息。

    参数:
        img_b64: 截图 base64
        question: 要回答的问题，如 "这个聊天窗口中最新的3条消息内容是什么？"
        context: 截图上下文描述

    返回:
        AI 的文字回答，失败返回 None
    """
    prompt = f"这是一张{context}。{question}\n请用中文回答，简洁明了。"
    return _call_llm(prompt, img_b64)
