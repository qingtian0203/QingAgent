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
from PIL import Image
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


def __b64_to_img(b64_str: str) -> Image.Image:
    """将 base64 图片字符串解析为 PIL Image 对象"""
    return Image.open(io.BytesIO(base64.b64decode(b64_str)))

def __img_to_b64(img: Image.Image) -> str:
    """将 PIL Image 对象转换为 base64 字符串"""
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def __get_crop_box(px: float, py: float, w: int, h: int, box_size: int) -> tuple[int, int, int, int]:
    """计算安全包围裁剪框，确保框子不会超出图片整体边界"""
    left = max(0, int(px - box_size / 2))
    top = max(0, int(py - box_size / 2))
    right = min(w, left + box_size)
    bottom = min(h, top + box_size)
    # 反向拉伸保证裁剪框大小(当撞到屏幕某条边界时)
    if right - left < box_size: left = max(0, right - box_size)
    if bottom - top < box_size: top = max(0, bottom - box_size)
    return left, top, right, bottom

def _single_find_call(img_b64: str, description: str, context: str) -> dict | None:
    """单次调用大模型进行中心点推测（剥离出的内部子环节）"""
    prompt = (
        f"这是一张{context}。请找到【{description}】的最精确的视觉物理绝对中心位置。"
        f"只返回 JSON 格式: {{\"rx\": 0-1000, \"ry\": 0-1000}}，"
        f"其中 rx 和 ry 是该元素中心相对于当前图片宽高的千分比坐标。"
        f"绝对不要返回任何其他文字或外发散解释。"
    )

    text = _call_llm(prompt, img_b64)
    if text is None:
        return None

    try:
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            print(f"⚠️ AI 返回内容无法解析为 JSON：{text[:100]}")
            return None

        coords = json.loads(clean[start:end])
        rx, ry = coords.get("rx", -1), coords.get("ry", -1)
        if not (0 <= rx <= 1000 and 0 <= ry <= 1000):
            print(f"⚠️ AI 返回坐标超出范围：rx={rx}, ry={ry}")
            return None

        return {"rx": rx, "ry": ry}
    except Exception as e:
        print(f"❌ AI 解析 JSON 失败：{e}")
        return None


# ======= 以下为辅助标点画圈测试函数 =======
def _draw_cross_for_debug(cur_img, cur_x, cur_y, name):
    try:
        from PIL import ImageDraw
        import os
        draw = ImageDraw.Draw(cur_img)
        r = int(max(5, cur_img.width * 0.05))
        draw.ellipse((cur_x - r, cur_y - r, cur_x + r, cur_y + r), outline="red", width=2)
        draw.line((cur_x - r*2, cur_y, cur_x + r*2, cur_y), fill="red", width=2)
        draw.line((cur_x, cur_y - r*2, cur_x, cur_y + r*2), fill="red", width=2)
        out_path = os.path.join("/Users/konglingjia/AIProject/QingAgent/", name)
        cur_img.save(out_path)
    except Exception as e:
        pass


def find_element(
    img_b64: str,
    description: str,
    context: str = "软件截图",
) -> dict | None:
    """
    用 AI 视觉模型在截图中定位元素（已升级为：三段式防偏锁心微操策略）。
    1. 全图找大势
    2. 300x300 截取大体框纠正漂移错觉
    3. 80x80 指甲盖截取强迫模型中心对齐点杀
    （自带 debug_stage1/2/3 打印机制）
    """
    res_stage1 = _single_find_call(img_b64, description, context)
    if not res_stage1:
        return None

    try:
        img = __b64_to_img(img_b64)
        img_w, img_h = img.width, img.height
    except Exception as e:
        print(f"⚠️ 图片解析失败，退回单阶段低精寻结果：{e}")
        return res_stage1

    px1 = (res_stage1["rx"] / 1000.0) * img_w
    py1 = (res_stage1["ry"] / 1000.0) * img_h
    print(f"🔍 [段1-全景粗寻] {description[:10]}... -> x={px1:.0f}, y={py1:.0f}")
    _draw_cross_for_debug(img.copy(), px1, py1, "debug_stage1.png")

    l2, t_box2, r2, b2 = __get_crop_box(px1, py1, img_w, img_h, 300)
    crop2 = img.crop((l2, t_box2, r2, b2))
    res_stage2 = _single_find_call(__img_to_b64(crop2), description, context)
    if not res_stage2:
        return res_stage1

    px2 = l2 + (res_stage2["rx"] / 1000.0) * crop2.width
    py2 = t_box2 + (res_stage2["ry"] / 1000.0) * crop2.height
    print(f"🎯 [段2-包容纠偏] 300x300框定后 -> x={px2:.1f}, y={py2:.1f}")
    _draw_cross_for_debug(crop2.copy(), (res_stage2["rx"] / 1000.0) * crop2.width, (res_stage2["ry"] / 1000.0) * crop2.height, "debug_stage2.png")

    l3, t_box3, r3, b3 = __get_crop_box(px2, py2, img_w, img_h, 80)
    crop3 = img.crop((l3, t_box3, r3, b3))
    res_stage3 = _single_find_call(__img_to_b64(crop3), description, context)
    if not res_stage3:
        return {"rx": int(px2 / img_w * 1000), "ry": int(py2 / img_h * 1000)}

    final_px = l3 + (res_stage3["rx"] / 1000.0) * crop3.width
    final_py = t_box3 + (res_stage3["ry"] / 1000.0) * crop3.height
    print(f"🔬 [段3-极限锁心] 80x80显微绝杀 -> x={final_px:.1f}, y={final_py:.1f}")
    _draw_cross_for_debug(crop3.copy(), (res_stage3["rx"] / 1000.0) * crop3.width, (res_stage3["ry"] / 1000.0) * crop3.height, "debug_stage3.png")

    return {
        "rx": int(final_px / img_w * 1000),
        "ry": int(final_py / img_h * 1000)
    }

def find_element_bounds(
    img_b64: str,
    description: str,
    context: str = "软件截图",
) -> dict | None:
    """
    用 AI 视觉模型查找元素的边界框，直接返回左上角和右下角的归一化坐标。
    用于拖拽画框等需要大面积覆盖的操作。
    不使用多段显微策略（多段会切碎图片丢失整体外围信息），单次全局扫描。

    返回:
        {"rx1": ..., "ry1": ..., "rx2": ..., "ry2": ...} 或 None
    """
    prompt = (
        f"这是一张{context}。请找到【{description}】的整体边界框（Bounding Box）。"
        f"请返回该元素左上角和右下角的精确百分比像素坐标。"
        f"只返回 JSON 格式: {{\"rx1\": 0-1000, \"ry1\": 0-1000, \"rx2\": 0-1000, \"ry2\": 0-1000}}，"
        f"rx1 和 ry1 是左上角，rx2 和 ry2 是右下角。"
        f"绝对不要返回任何其他文字或外发散解释。"
    )
    
    import time as _time
    t0 = _time.time()
    text = _call_llm(prompt, img_b64)
    if text is None:
        return None

    try:
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            print(f"⚠️ AI 边界框返回内容无法解析为 JSON：{text[:100]}")
            return None

        coords = json.loads(clean[start:end])
        rx1, ry1 = coords.get("rx1", -1), coords.get("ry1", -1)
        rx2, ry2 = coords.get("rx2", -1), coords.get("ry2", -1)
        
        if not (0 <= rx1 <= 1000 and 0 <= ry1 <= 1000 and 0 <= rx2 <= 1000 and 0 <= ry2 <= 1000):
            print(f"⚠️ AI 返回边界坐标超出范围：rx1={rx1}, ry1={ry1}, rx2={rx2}, ry2={ry2}")
            return None

        print(f"📦 [边界识别] {description[:15]}... -> 从({rx1},{ry1})到({rx2},{ry2})，耗时: {_time.time() - t0:.1f}s")
        return {
            "rx1": rx1, "ry1": ry1,
            "rx2": rx2, "ry2": ry2
        }
    except Exception as e:
        print(f"❌ AI 解析边界 Box 失败：{e}")
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
