#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, warnings
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"] = "1"
os.environ["HUGGINGFACE_HUB_VERBOSITY"] = "error"
warnings.filterwarnings("ignore")

"""
MLX VLM vs Ollama 速度对比测试
=========================================
测试场景1：文本推理（Planner 意图解析）
测试场景2：视觉识别（Vision 元素定位）

所有 MLX 模型均为多模态 VLM，使用 mlx_vlm 加载。
"""

import time, json, base64, io, requests, tempfile

# ─── 配置 ────────────────────────────────────────────────────
TEXT_PROMPT = (
    "你是一个AI助手，请理解以下指令并返回JSON格式。\n"
    "指令：帮我添加一个明天下午3点的产品评审日程\n"
    'JSON格式：{"app": "晴天Util", "action": "add_calendar", '
    '"slots": {"title": "...", "date": "..."}}'
)

VISION_PROMPT = (
    "这是一张新建任务弹窗截图。请找到以下元素的中心位置：\n"
    "- input: 任务内容输入框\n"
    "- date_btn: 今天按钮\n"
    "- confirm: 确认添加按钮\n"
    '只返回JSON：{"input":{"rx":?,"ry":?},"date_btn":{"rx":?,"ry":?},"confirm":{"rx":?,"ry":?}}'
)

OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:26b"

HF_CACHE = os.path.expanduser("~/.cache/huggingface/hub")
MLX_MODELS = [
    ("gemma-3-27b (qat-4bit)", f"{HF_CACHE}/models--mlx-community--gemma-3-27b-it-qat-4bit/snapshots/fc4e000f32af1b7b6779294e490a7d2a80bac611"),
    ("gemma-4-26b (a4b-4bit)", f"{HF_CACHE}/models--mlx-community--gemma-4-26b-a4b-it-4bit/snapshots/8bcfa0de037c2b1bfa323a1e8d1f0132243b9e87"),
    ("gemma-4-31b (it-4bit)",  f"{HF_CACHE}/models--mlx-community--gemma-4-31b-it-4bit/snapshots/535c5606372deb5d5ab7e29280f111ef2a8e084e"),
]

# ─── 假截图 ──────────────────────────────────────────────────
def _make_fake_img_path() -> str:
    """生成一张 300x400 灰色测试图，返回临时文件路径"""
    from PIL import Image
    img = Image.new("RGB", (300, 400), color=(230, 230, 230))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    img.save(tmp.name)
    return tmp.name

def _img_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# ─── Ollama ───────────────────────────────────────────────────
def test_ollama(prompt: str, img_path: str = None) -> dict:
    payload = {"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}
    if img_path:
        payload["images"] = [_img_to_b64(img_path)]
    t0 = time.time()
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=180)
        res.raise_for_status()
        data = res.json()
        elapsed = time.time() - t0
        tokens = data.get("eval_count", 0)
        return {"success": True, "elapsed": elapsed, "tokens": tokens,
                "tps": tokens / elapsed if elapsed > 0 else 0,
                "preview": data.get("response", "")[:80]}
    except Exception as e:
        return {"success": False, "elapsed": time.time() - t0, "error": str(e)}

# ─── MLX VLM ─────────────────────────────────────────────────
def test_mlx_vlm(model_path: str, prompt: str, img_path: str = None) -> dict:
    try:
        from mlx_vlm import load, generate
        from mlx_vlm.prompt_utils import apply_chat_template
        from mlx_vlm.utils import load_config

        # 加载模型
        t_load = time.time()
        print(f"    ⏳ 加载模型（约需 10~30s）...")
        config = load_config(model_path)
        model, processor = load(model_path, {"trust_remote_code": True})
        load_time = time.time() - t_load
        print(f"    ✅ 加载完成 {load_time:.1f}s")

        # 构建对话格式
        formatted = apply_chat_template(processor, config, prompt,
                                        num_images=1 if img_path else 0)

        # 预热
        _ = generate(model, processor, formatted,
                     image=img_path or "",
                     max_tokens=10, verbose=False)

        # 正式测试
        t0 = time.time()
        result = generate(model, processor, formatted,
                          image=img_path or "",
                          max_tokens=200, verbose=False)
        elapsed = time.time() - t0

        # mlx_vlm generate 返回字符串，估算 token 数
        token_est = max(len(result) // 2, 1)
        tps_est = token_est / elapsed if elapsed > 0 else 0

        return {
            "success": True,
            "load_time": load_time,
            "elapsed": elapsed,
            "token_est": token_est,
            "tps_est": tps_est,
            "preview": result[:80],
        }

    except Exception as e:
        import traceback
        return {"success": False, "elapsed": 0, "error": str(e)[:120],
                "tb": traceback.format_exc()[-200:]}


# ─── 格式化 ───────────────────────────────────────────────────
def show(label: str, text_r: dict, vision_r: dict):
    print(f"\n{'─'*62}")
    print(f"🔍 {label}")
    print(f"{'─'*62}")

    def _tps(r):
        return r.get("tps") or r.get("tps_est", 0)

    if text_r.get("success"):
        load_s = f"  加载={text_r['load_time']:.0f}s" if "load_time" in text_r else ""
        print(f"  📝 文本  {text_r['elapsed']:6.1f}s  ~{_tps(text_r):>6.1f} tok/s{load_s}")
        print(f"     ↳ {text_r.get('preview','')}")
    else:
        print(f"  📝 文本  ❌ {text_r.get('error','')[:80]}")

    if vision_r.get("success"):
        load_s = f"  (已缓存模型)" if "load_time" not in vision_r else f"  加载={vision_r['load_time']:.0f}s"
        print(f"  🖼️  视觉  {vision_r['elapsed']:6.1f}s  ~{_tps(vision_r):>6.1f} tok/s{load_s}")
        print(f"     ↳ {vision_r.get('preview','')}")
    else:
        print(f"  🖼️  视觉  ⚠️  {vision_r.get('error','')[:80]}")


# ─── 主流程 ──────────────────────────────────────────────────
def main():
    from datetime import datetime
    print("=" * 62)
    print("🚀 MLX VLM vs Ollama 速度对比")
    print(f"   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 62)

    # 生成测试图片（全程复用同一张）
    img_path = _make_fake_img_path()
    print(f"\n✅ 测试图片已生成：{img_path}")

    results = {}

    # ── Ollama ──
    print(f"\n▶ Ollama ({OLLAMA_MODEL})")
    print("  📝 文本推理...")
    ot = test_ollama(TEXT_PROMPT)
    print("  🖼️  视觉识别...")
    ov = test_ollama(VISION_PROMPT, img_path)
    results["Ollama gemma4:26b"] = {"text": ot, "vision": ov}
    show(f"Ollama — {OLLAMA_MODEL}", ot, ov)

    # ── MLX VLM ──
    for name, model_path in MLX_MODELS:
        print(f"\n▶ MLX  {name}")
        print("  📝 文本推理（+加载）...")
        mt = test_mlx_vlm(model_path, TEXT_PROMPT)  # 纯文本，不传图
        print("  🖼️  视觉识别（复用已加载模型）...")
        # 注意：这里重新调用会重新加载；实际场景中同一进程只需加载一次
        mv = test_mlx_vlm(model_path, VISION_PROMPT, img_path)
        results[f"MLX {name}"] = {"text": mt, "vision": mv}
        show(f"MLX — {name}", mt, mv)

        # 释放 MLX 显存
        try:
            import mlx.core as mx
            mx.clear_cache()
        except Exception:
            pass

    # ── 汇总 ──
    print(f"\n\n{'='*62}")
    print("📊 汇总（首次加载后耗时，tok/s 估算）")
    print(f"{'─'*62}")
    print(f"  {'模型':<36} {'文本(tok/s)':>12} {'文本(s)':>8} {'视觉(s)':>8}")
    print(f"{'─'*62}")
    for n, r in results.items():
        t, v = r["text"], r["vision"]
        t_tps = f"{t.get('tps') or t.get('tps_est',0):.1f}" if t.get("success") else "失败"
        t_s   = f"{t['elapsed']:.1f}" if t.get("success") else "-"
        v_s   = f"{v['elapsed']:.1f}" if v.get("success") else "N/A"
        print(f"  {n:<36} {t_tps:>12} {t_s:>8} {v_s:>8}")
    print(f"{'='*62}")

    os.unlink(img_path)
    out = "/tmp/mlx_vlm_benchmark.json"
    with open(out, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n💾 详细数据：{out}")

if __name__ == "__main__":
    main()
