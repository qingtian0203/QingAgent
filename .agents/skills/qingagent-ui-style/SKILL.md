---
name: QingAgent Web UI 设计规范
description: QingAgent Web 控制台的视觉设计语言、CSS Token、组件规范和新增 UI 的执行原则。所有对 app.py 的 UI 改动必须先读此文档，确保风格一致性。
---

# QingAgent Web UI 设计规范

## 核心原则

> **降噪融合**：功能性元素退到背景隐藏，需要时才浮现。拒绝视觉噪音。

1. **克制 > 装饰**：不加无意义的边框、阴影、颜色，所有视觉元素必须有功能意图
2. **透明叠加 > 实色填充**：背景色用极低透明度的白色叠加，而不是固定颜色
3. **状态过渡 > 跳变**：交互动画 0.18s ease，不生硬，不过长
4. **内敛 hover > 高亮 hover**：hover 只轻微提亮（+5% 透明度），不做颜色跳变

---

## 设计令牌（CSS Variables）

全部定义在 `:root` 中，**任何新组件必须使用这些变量，禁止硬编码颜色**：

```css
:root {
    /* 背景层次（从深到浅） */
    --bg-primary:   #0b0b11;              /* 页面最底层背景 */
    --bg-secondary: #13131d;              /* 顶栏、底栏背景 */
    --bg-card:      #1a1a2e;              /* 卡片、输入框背景 */
    --border:       rgba(255,255,255,0.06); /* 分割线 */

    /* 文字 */
    --text-primary:   #e8e8ed;            /* 主要文字 */
    --text-secondary: #8888a0;            /* 次要文字、时间戳 */

    /* 强调色（渐变方向：135deg） */
    --accent-start: #667eea;              /* 紫蓝 */
    --accent-end:   #764ba2;              /* 深紫 */

    /* 状态色 */
    --success: #4ade80;                   /* 成功、在线指示 */
    --error:   #f87171;                   /* 失败、急停按钮 */

    /* 安全区（iOS 刘海屏） */
    --safe-bottom: env(safe-area-inset-bottom, 0px);
}
```

---

## 字体

```css
font-family: 'Inter', -apple-system, BlinkMacSystemFont, "SF Pro Display", sans-serif;
```

- 正文：400（Regular）
- 标签/次要信息：400，`rgba(255,255,255,0.55)`
- 按钮/强调：500（Medium）
- 标题：600（SemiBold）

---

## 组件规范

### 气泡消息（`.msg-bubble`）

| 属性 | Agent 气泡 | User 气泡 |
|------|-----------|----------|
| 背景 | `var(--bg-card)` | `linear-gradient(135deg, --accent-start, --accent-end)` |
| 圆角 | `16px 16px 16px 4px` | `16px 16px 4px 16px` |
| 最大宽 | 80% | 80% |
| 字色 | `var(--text-primary)` | `white` |

---

### 快捷 Chip（`.quick-chip`）

```css
.quick-chip {
    padding: 5px 12px;
    border-radius: 6px;
    border: none;
    background: rgba(255,255,255,0.05);
    color: rgba(255,255,255,0.55);
    font-size: 11px;
    font-weight: 400;
    cursor: pointer;
    white-space: nowrap;
    transition: all 0.18s ease;
    letter-spacing: 0.2px;
}
.quick-chip:hover  { background: rgba(255,255,255,0.09); color: rgba(255,255,255,0.80); }
.quick-chip:active { background: rgba(255,255,255,0.13); transform: scale(0.95); }
```

**设计意图**：Chip 是辅助快捷入口，不应比消息气泡更抢眼。无边框，极低透明度底，hover 轻浮现。

---

### 急停按钮（`.emergency-btn`）

```css
.emergency-btn {
    padding: 4px 10px;
    border-radius: 6px;
    border: 1px solid rgba(239,68,68,0.3);
    background: transparent;
    color: rgba(239,68,68,0.75);
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.2px;
    white-space: nowrap;
    flex-shrink: 0;
    transition: all 0.18s ease;
}
.emergency-btn:hover  { background: rgba(239,68,68,0.08); color: #f87171; border-color: rgba(239,68,68,0.55); }
.emergency-btn:active { background: rgba(239,68,68,0.15); transform: scale(0.95); }
```

**设计意图**：危险操作保持低调，正常状态不抢眼（透明底），hover 时才显现红色背景。

---

### 输入框（`.input-area input`）

```css
.input-area input {
    flex: 1;
    padding: 9px 14px;
    border-radius: 8px;                  /* 矩形感，非胶囊 */
    border: 1px solid rgba(255,255,255,0.07);
    background: rgba(255,255,255,0.04);
    color: rgba(255,255,255,0.88);
    font-size: 14px;
    font-family: inherit;
    outline: none;
    transition: border-color 0.2s, background 0.2s;
}
.input-area input:focus {
    border-color: rgba(255,255,255,0.18);
    background: rgba(255,255,255,0.06);
}
.input-area input::placeholder { color: rgba(255,255,255,0.25); font-size: 13px; }
```

---

### 发送/话筒按钮（`.send-btn`、`.mic-btn`）

```css
.send-btn, .mic-btn {
    width: 34px; height: 34px;
    border-radius: 8px;
    border: none;
    background: rgba(255,255,255,0.06);
    color: rgba(255,255,255,0.7);
    font-size: 16px;
    display: flex; align-items: center; justify-content: center;
    transition: all 0.18s ease;
    cursor: pointer;
}
.send-btn         { color: #a5b4fc; }
.send-btn:hover   { background: rgba(102,126,234,0.18); color: #818cf8; }
.send-btn:active,
.mic-btn:active   { transform: scale(0.9); opacity: 0.7; }
```

---

### 卡片（文件选择 / HITL 确认区域）

内容类卡片统一规范：
```css
background: var(--bg-card);       /* #1a1a2e */
border: 1px solid var(--border);  /* rgba(255,255,255,0.06) */
border-radius: 12px;
padding: 12px 14px;
```

次级按钮（如"选择"、"取消"）：
```css
border-radius: 6px;
border: 1px solid rgba(255,255,255,0.1);
background: rgba(255,255,255,0.05);
color: rgba(255,255,255,0.6);
font-size: 12px;
padding: 4px 10px;
transition: all 0.18s ease;
```

---

### 滚动条

```css
::-webkit-scrollbar { width: 4px; height: 4px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb {
    background: rgba(255,255,255,0.12);
    border-radius: 99px;
}
::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.22); }
* { scrollbar-width: thin; scrollbar-color: rgba(255,255,255,0.12) transparent; }
```

---

## UI 修改的执行原则

新增或修改 `qingagent/server/app.py` 中的 UI 组件时，必须遵守：

### ✅ 应该做
- 复用上方 CSS 变量（`var(--bg-card)` 等），不硬编码颜色
- 透明度叠加：背景用 `rgba(255,255,255, 0.04~0.10)` 区间
- 按钮统一 `border-radius: 6px~8px`（矩形圆角，不用胶囊形 `border-radius: 20px+`）
- 所有交互加 `transition: all 0.18s ease`
- hover 只做微调（±5% 透明度、色相轻移），不做颜色跳变
- 功能性图标文字：emoji + 1~3 个汉字，`font-size: 11px`

### ❌ 不应该做
- 实色大面积填充（`background: #667eea`）用于次要按钮
- 胶囊形按钮（`border-radius: 20px+`）用于功能按钮（仅适用于 tag/badge）
- 加粗边框（`border-width: 2px+`）在非强调场景
- `box-shadow` 用于普通卡片（只在弹窗、急停等极少场合使用）
- 超过 `0.3s` 的 transition
- 新增颜色变量（先确认无法复用现有 token）

---

## 代码结构说明

所有 UI HTML/CSS/JS 都硬编码在 `qingagent/server/app.py` 的 `_get_ui_html()` 函数内（单文件无依赖部署）。

**修改后必须重启服务** (`python main.py serve`) 才能看到效果，因为 HTML 在内存中。

若服务器已设置 `Cache-Control: no-cache`，可以用 `🔃 强刷` 按钮（quick-bar 最右侧）清除浏览器缓存。

---

## 布局结构

```
.app (flex-col, max-width: 600px, margin: 0 auto)
 ├── .header              (顶栏：logo + 标题 + 状态点 + 急停)
 ├── .quick-bar           (横向滚动 Chip 快捷区)
 ├── .chat-area           (消息列表，flex-grow: 1，overflow-y: auto)
 │    ├── .msg-row.agent  (AI 气泡，左对齐)
 │    └── .msg-row.user   (用户气泡，右对齐)
 └── .input-area          (底栏：输入框 + 话筒 + 发送)
```
