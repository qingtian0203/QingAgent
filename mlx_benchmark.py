"""
MLX vs Ollama 速度对比测试
用法：
  只测 Ollama：/tmp/mlx_test_env/bin/python3 mlx_benchmark.py ollama
  只测 MLX   ：/tmp/mlx_test_env/bin/python3 mlx_benchmark.py mlx
  都测       ：/tmp/mlx_test_env/bin/python3 mlx_benchmark.py both
"""
import time
import sys
import requests

# ---- 配置 ----
OLLAMA_URL   = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "gemma4:26b"
MLX_MODEL    = "mlx-community/gemma-3-27b-it-4bit"  # HuggingFace 对应版本

# 模拟 Planner 解析的 prompt
PROMPT = '你是指令解析器。用户说："给丸子发微信说下午开会"，返回JSON: {"app":"","intent":"","slots":{},"confidence":""}'


def test_ollama():
    print("\n🦙 [Ollama] 开始测试...")
    try:
        t = time.time()
        res = requests.post(OLLAMA_URL, json={
            "model": OLLAMA_MODEL,
            "prompt": PROMPT,
            "stream": False,
        }, timeout=120)
        res.raise_for_status()
        data = res.json()
        elapsed = time.time() - t

        tokens = data.get("eval_count", 0)
        ns     = data.get("eval_duration", 1)
        speed  = tokens / (ns / 1e9) if ns > 0 else 0

        print(f"  ✅ 总耗时：{elapsed:.2f}s")
        print(f"  🚀 速度：{speed:.1f} tokens/s（输出 {tokens} tokens）")
        print(f"  📝 回复：{data.get('response','')[:200]}")
        return elapsed, speed
    except requests.exceptions.ConnectionError:
        print("  ❌ Ollama 未运行，请先启动 Ollama")
        return None, None
    except Exception as e:
        print(f"  ❌ 失败：{e}")
        return None, None


def test_mlx():
    print("\n⚡ [MLX] 开始测试...")
    try:
        from mlx_lm import load, generate

        print(f"  📦 加载模型：{MLX_MODEL}")
        print("     首次运行会从 HuggingFace 下载（约 14GB），请耐心等待...")

        t0 = time.time()
        model, tokenizer = load(MLX_MODEL)
        load_time = time.time() - t0
        print(f"  ✅ 模型加载完成，耗时：{load_time:.1f}s")

        print("  🏃 开始推理...")
        t1 = time.time()
        response = generate(
            model, tokenizer,
            prompt=PROMPT,
            max_tokens=200,
            verbose=True,   # 自动打印 tokens/s
        )
        infer_time = time.time() - t1

        print(f"  ✅ 推理耗时：{infer_time:.2f}s")
        print(f"  📝 回复：{response[:200]}")
        return infer_time
    except Exception as e:
        print(f"  ❌ 失败：{e}")
        return None


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "both"

    ollama_time = ollama_speed = mlx_time = None

    if mode in ("ollama", "both"):
        ollama_time, ollama_speed = test_ollama()

    if mode in ("mlx", "both"):
        mlx_time = test_mlx()

    # 汇总对比
    if ollama_time and mlx_time:
        print("\n" + "="*45)
        print("📊 对比汇总")
        print(f"  Ollama：{ollama_time:.2f}s  [{ollama_speed:.1f} tokens/s]")
        print(f"  MLX   ：{mlx_time:.2f}s（推理部分）")
        ratio = ollama_time / mlx_time
        if ratio > 1:
            print(f"  🏆 MLX 快了 {ratio:.1f}x")
        else:
            print(f"  🦙 Ollama 快了 {1/ratio:.1f}x")
