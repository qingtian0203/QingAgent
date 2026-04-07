"""用小模型快速验证 MLX 速度"""
import time
from mlx_lm import load, generate

PROMPT = '你是指令解析器。用户说："给丸子发微信说下午开会"，返回JSON: {"app":"","intent":"","slots":{},"confidence":""}'

print("📦 加载 gemma-3-4b-it（约2.5GB，首次需下载）...")
t0 = time.time()
model, tokenizer = load("mlx-community/gemma-3-4b-it-4bit")
print(f"✅ 加载耗时：{time.time()-t0:.1f}s\n🏃 推理中...")

t1 = time.time()
response = generate(model, tokenizer, prompt=PROMPT, max_tokens=150, verbose=True)
infer_time = time.time() - t1

print(f"\n✅ 推理耗时：{infer_time:.2f}s")
print(f"📝 回复：{response[:200]}")
