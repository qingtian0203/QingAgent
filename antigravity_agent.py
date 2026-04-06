import pyautogui
import requests
import base64
import os
import io
import json
import time
import pyperclip  
from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID

# --- 配置 ---
MODEL_NAME = "gemma4:26b" 
OLLAMA_URL = "http://localhost:11434/api/generate"
APP_NAME = "Antigravity"
TARGET_DESC = "界面右侧对话面板中，带有‘Ask anything...’提示文字的输入矩形框中心"

def get_window_and_activate(name):
    window_list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    found = []
    for window in window_list:
        owner = window.get('kCGWindowOwnerName', '')
        if name.lower() in owner.lower():
            bounds = window.get('kCGWindowBounds', {})
            w, h = bounds.get('Width', 0), bounds.get('Height', 0)
            if w > 40: found.append({'rect': (int(bounds['X']), int(bounds['Y']), int(w), int(h)), 'size': w*h})
    
    if not found: return None
    found.sort(key=lambda x: x['size'], reverse=True)
    best = found[0]
    
    if best['rect'][2] < 400:
        print(f"⚠️ 发现 {name} 缩略图，视觉唤醒...")
        pyautogui.click(best['rect'][0] + best['rect'][2]/2, best['rect'][1] + best['rect'][3]/2)
        time.sleep(1.5)
        return get_window_and_activate(name)
    return best['rect']

def ask_ai(img_b64, desc):
    prompt = f"这是一张 IDE 截图。请找到【{desc}】。只返回 JSON: {{'rx': 0-1000, 'ry': 0-1000}}"
    payload = {"model": MODEL_NAME, "prompt": prompt, "images": [img_b64], "stream": False}
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=60).json()
        clean = res['response'].replace("```json", "").replace("```", "").strip()
        start, end = clean.find('{'), clean.rfind('}') + 1
        return json.loads(clean[start:end])
    except: return None

if __name__ == "__main__":
    print(f"🚦 Antigravity Agent 启动...")
    os.system(f'osascript -e "tell application \\"{APP_NAME}\\" to activate" 2>/dev/null')
    
    rect = get_window_and_activate(APP_NAME)
    if rect:
        screenshot = pyautogui.screenshot(region=rect)
        # 存个图让你查岗
        screenshot.save("debug_antigravity_vision.png")
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        img_data = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        coords = ask_ai(img_data, TARGET_DESC)
        if coords:
            # 物理坐标公式：$tx = rect_x + \frac{rx}{1000} \times rect_w$
            tx = rect[0] + (coords['rx'] / 1000) * rect[2]
            ty = rect[1] + (coords['ry'] / 1000) * rect[3]
            pyautogui.moveTo(tx, ty, duration=0.8)
            pyautogui.click()
            pyperclip.copy("Antigravity，我是 LeBron Agent。帮晴帅检查一下这段 Android 混淆逻辑。")
            pyautogui.hotkey('command', 'v')
            pyautogui.press('enter')
            print("✅ 消息已注入 Antigravity！")