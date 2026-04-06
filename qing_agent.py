import pyautogui
import requests
import base64
import os
import io
import json
import time
import pyperclip  
from Quartz import CGWindowListCopyWindowInfo, kCGWindowListOptionOnScreenOnly, kCGNullWindowID

# --- 配置区 ---
MODEL_NAME = "gemma4:26b" 
OLLAMA_URL = "http://localhost:11434/api/generate"

def get_window_and_activate(name_list):
    """
    🌟 V7.1 升级：增加全城普查逻辑
    """
    window_list = CGWindowListCopyWindowInfo(kCGWindowListOptionOnScreenOnly, kCGNullWindowID)
    found = []
    all_owners = set() # 用来记录所有看到的进程名

    for window in window_list:
        owner = window.get('kCGWindowOwnerName', '')
        all_owners.add(owner)
        
        # 模糊匹配：只要名字里包含“微”或者“We”就尝试
        if any(n.lower() in owner.lower() for n in name_list):
            bounds = window.get('kCGWindowBounds', {})
            w, h = bounds.get('Width', 0), bounds.get('Height', 0)
            if w > 40: 
                found.append({'rect': (int(bounds['X']), int(bounds['Y']), int(w), int(h)), 'size': w*h, 'owner': owner})
    
    if not found:
        print("\n--- 🕵️ 侦察兵报告：找不到匹配进程，当前屏幕可见进程如下 ---")
        # 打印前 15 个进程名，帮你对线
        for name in sorted(list(all_owners))[:15]:
            print(f"- {name}")
        print("--------------------------------------------------")
        return None
    
    found.sort(key=lambda x: x['size'], reverse=True)
    best = found[0]
    
    # 如果是缩略图，先点一下唤醒
    if best['rect'][2] < 400:
        print(f"⚠️ 发现缩略图 ({best['owner']})，尝试视觉唤醒...")
        tx = best['rect'][0] + best['rect'][2] / 2
        ty = best['rect'][1] + best['rect'][3] / 2
        pyautogui.click(tx, ty)
        time.sleep(1.5)
        return get_window_and_activate(name_list)
    
    print(f"✅ 成功锁定：{best['owner']}")
    return best['rect']

def capture_vision_input(window_rect):
    wx, wy, ww, wh = window_rect
    try:
        screenshot = pyautogui.screenshot(region=(wx, wy, ww, wh))
        buffered = io.BytesIO()
        screenshot.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode('utf-8')
    except Exception as e:
        print(f"❌ 截图失败（请检查权限）：{e}")
        return None

def ask_ai_v7(img_base64, desc):
    prompt = f"这是一张软件截图。请找到【{desc}】。请只返回 JSON: {{'rx': 0-1000, 'ry': 0-1000}}"
    payload = {"model": MODEL_NAME, "prompt": prompt, "images": [img_base64], "stream": False}
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=60).json()
        text = res['response']
        clean = text.replace("```json", "").replace("```", "").strip()
        start = clean.find('{')
        end = clean.rfind('}') + 1
        return json.loads(clean[start:end])
    except: return None

if __name__ == "__main__":
    # 🎯 尝试更多可能的“暗号”
    NAMES = ["微信", "WeChat", "wechat"]
    CONTACT_NAME = "晴天灬Pura"

    print(f"🚦 LeBron Agent V7.1 启动...")
    
    # 强制唤醒（双语尝试）
    os.system('osascript -e "tell application \"WeChat\" to activate" 2>/dev/null')
    os.system('osascript -e "tell application \"微信\" to activate" 2>/dev/null')
    
    rect = get_window_and_activate(NAMES)
    
    if rect:
        img_data = capture_vision_input(rect)
        if img_data:
            print(f"🧠 大脑正在搜索联系人：{CONTACT_NAME}...")
            c_coords = ask_ai_v7(img_data, f"左侧列表中名字为‘{CONTACT_NAME}’的整行区域中心")
            
            if c_coords:
                tx = rect[0] + (c_coords['rx'] / 1000) * rect[2]
                ty = rect[1] + (c_coords['ry'] / 1000) * rect[3]
                pyautogui.click(tx, ty)
                time.sleep(0.8)
                
                # 再次获取输入框
                img_data_chat = capture_vision_input(rect)
                i_coords = ask_ai_v7(img_data_chat, "聊天区域底部的输入框中心")
                if i_coords:
                    ix = rect[0] + (i_coords['rx'] / 1000) * rect[2]
                    iy = rect[1] + (i_coords['ry'] / 1000) * rect[3]
                    pyautogui.click(ix, iy)
                    pyperclip.copy("报告晴总：V7.1 终于对上线了！")
                    pyautogui.hotkey('command', 'v')
                    pyautogui.press('enter')
                    print("🎉 任务完成！")
    else:
        print("❌ 依然找不到微信。请看上面的【侦察兵报告】，找找有没有类似微信的名字？")