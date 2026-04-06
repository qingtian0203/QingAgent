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
APP_NAME = "Chatbox"
TARGET_DESC = "带有‘在这里输入你的问题...’提示文字的灰色长条输入框"

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
    
    # 🌟 核心：发现是缩略图就点一下唤醒
    if best['rect'][2] < 400:
        print(f"⚠️ 发现 {name} 缩略图，正在视觉唤醒...")
        pyautogui.click(best['rect'][0] + best['rect'][2]/2, best['rect'][1] + best['rect'][3]/2)
        time.sleep(1.5)
        return get_window_and_activate(name)
    return best['rect']

def ask_ai(img_b64, desc):
    prompt = f"这是一张软件截图。请找到【{desc}】的中心。只返回 JSON: {{'rx': 0-1000, 'ry': 0-1000}}"
    payload = {"model": MODEL_NAME, "prompt": prompt, "images": [img_b64], "stream": False}
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=60).json()
        clean = res['response'].replace("```json", "").replace("```", "").strip()
        start, end = clean.find('{'), clean.rfind('}') + 1
        return json.loads(clean[start:end])
    except: return None

if __name__ == "__main__":
    print(f"🚦 Chatbox Agent 启动...")
    os.system(f'osascript -e "tell application \\"{APP_NAME}\\" to activate" 2>/dev/null')
    
    rect = get_window_and_activate(APP_NAME)
    if rect:
        screenshot = pyautogui.screenshot(region=rect)
        buf = io.BytesIO()
        screenshot.save(buf, format="PNG")
        img_data = base64.b64encode(buf.getvalue()).decode('utf-8')
        
        coords = ask_ai(img_data, TARGET_DESC)
        if coords:
            tx = rect[0] + (coords['rx'] / 1000) * rect[2]
            ty = rect[1] + (coords['ry'] / 1000) * rect[3]
            pyautogui.click(tx, ty)
            pyperclip.copy("报告晴总：Chatbox 专属 Agent 对线成功！")
            pyautogui.hotkey('command', 'v')
            pyautogui.press('enter')
            print("✅ 任务完成！")