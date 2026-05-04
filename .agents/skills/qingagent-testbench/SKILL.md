---
name: QingAgent 测试台与模型验证
description: QingAgent 测试台、benchmark、视觉识别、模型能力验证、ADB/debug endpoint 联调页面的开发和排障指南。修改测试台 Tab、模型评测 UI、vision benchmark 或验证报告前必读。
---

# QingAgent 测试台与模型验证

## 定位

测试台用于验证 QingAgent 的底层能力，不是业务功能本身。它回答的问题是：

- 模型能否识别目标 UI？
- ADB / 浏览器 / macOS 控件能否稳定执行？
- debug endpoint 能否证明前端动作真的落到后端？
- 自动化测试报告是否可复查？

不要把测试台做成营销页，也不要把它和多 Agent 群聊的协作协议混在一起。

## 常见任务

| 任务 | 优先检查 |
|---|---|
| 视觉识别不准 | 截图质量、目标描述、三段定位、兜底坐标 |
| 模型调用失败 | `qingagent/config.py` 的 OpenAI 兼容 URL / model / key |
| Web UI 看不懂 | 控件尺寸、状态提示、结果报告、错误信息 |
| ADB 执行不稳 | 设备状态、权限弹窗、uiautomator dump、contentDescription |
| API 断言失败 | debug endpoint、请求日志、测试数据重置 |

## 验证层级

优先级从高到低：

1. 结构化接口断言：debug endpoint / API response。
2. uiautomator / Accessibility 节点：resource-id、contentDescription、text。
3. 视觉识别：截图 + 模型理解。
4. 固定坐标：只作为临时兜底。

测试台 UI 应该把这几层结果分开展示，避免“视觉看起来成功”掩盖“后端没有记录”。

## QingOA 自动化验证线

QingOA 是当前最重要的自动化验证场。测试台相关开发要优先服务这条链路：

- App 打卡 PoC：启动 App、定位入口、输入坐标、点击、截图、后端断言、请求日志。
- WAP workflow：登录、待办、审批、退回、重提、最终完成。
- API debug：`/debug/attendance/latest`、`/debug/leave/latest`、`/debug/workflow/state`。

## UI 修改原则

- 控件尺寸保持紧凑，给日志、截图、报告留空间。
- 按钮文案要说明动作结果，例如“开始测试”“保存报告”“复制命令”。
- 异常信息要可复制，不要只 Toast。
- 长日志和报告放在可滚动区域，不要挤压主操作区。
- 对关键测试结果使用明确状态：`通过` / `失败` / `跳过` / `需人工确认`。

## 修改后验证

```bash
cd /Users/konglingjia/AIProject/QingAgent
./venv/bin/python -m compileall qingagent
python main.py serve
```

然后打开：

- `http://127.0.0.1:8077/`
- `http://127.0.0.1:8077/group-chat`

如果涉及 QingOA App 自动化，优先跑：

```bash
NO_PROXY=127.0.0.1,localhost ./venv/bin/python -m qingagent.qingoa_punch_poc \
  --api-base http://127.0.0.1:8010 \
  --mode success
```
