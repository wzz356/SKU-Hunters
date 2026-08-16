"""真实 LLM API 连通性测试 — 用趋势官角色发起一次真实调用"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 加载 .env
env_path = Path(__file__).resolve().parent.parent / ".env"
for line in env_path.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from app.engine.llm import complete, get_llm_config, load_prompt

cfg = get_llm_config()
print(f"供应商配置: {cfg['base_url']} | 模型: {cfg['model']}")
print("发起真实调用...")

result = complete(
    system_prompt=load_prompt("trend_agent"),
    user_prompt=(
        "品类: 潮玩\n目标市场: CN\n候选关键词: Labubu\n"
        "数据: 淘宝联想词返回10条真实需求词（拉布布娃衣/拉布布盲盒/拉布布挂件等），"
        "B站5分区474个排行视频命中0个。\n"
        "请按发言卡格式输出你的趋势陈述（100字以内）。"
    ),
    max_tokens=300,
)

if result:
    print("\n=== 趋势官真实返回 ===")
    print(result)
    print("\nAPI 可用，Key 有效。")
else:
    print("\n调用失败或被降级——检查 Key 有效性")
