"""
飞书对接测试脚本
1. 测试获取 tenant_access_token
2. 测试发送消息（需要 chat_id）
"""
import os
import sys

# 添加 backend 目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from feishu.auth import FeishuAuth
from feishu.bot import FeishuBot
from feishu.config import FeishuConfig


def test_token():
    """测试获取 token"""
    print("=" * 50)
    print("测试 1: 获取 tenant_access_token")
    print("=" * 50)

    # 从 .env 读取凭证，禁止在代码中硬编码 App ID / Secret
    config = FeishuConfig.from_env()
    auth = FeishuAuth(config)

    try:
        token = auth.get_token()
        print("✅ Token 获取成功！")
        print(f"   Token 前20位: {token[:20]}...")
        return auth
    except Exception as e:  # noqa: BLE001 — 手动测试脚本，打印所有错误
        print(f"❌ Token 获取失败: {e}")
        return None


def test_send_message(auth, chat_id):
    """测试发送消息"""
    print("\n" + "=" * 50)
    print(f"测试 2: 发送消息到群 {chat_id}")
    print("=" * 50)

    bot = FeishuBot(auth)

    try:
        result = bot.send_text(chat_id, "🤖 你好！我是 SKU 委员会机器人，对接测试成功！")
        if result.get("code") == 0:
            print("✅ 消息发送成功！")
            print(f"   消息 ID: {result.get('data', {}).get('message_id', '')}")
        else:
            print("❌ 消息发送失败")
            print(f"   错误码: {result.get('code')}")
            print(f"   错误信息: {result.get('msg')}")
    except Exception as e:  # noqa: BLE001 — 手动测试脚本，打印所有错误
        print(f"❌ 发送异常: {e}")


def test_send_card(auth, chat_id):
    """测试发送卡片消息"""
    print("\n" + "=" * 50)
    print("测试 3: 发送趋势官卡片")
    print("=" * 50)

    bot = FeishuBot(auth)

    try:
        result = bot.send_committee_report(
            chat_id=chat_id,
            role="trend",
            content="**市场趋势分析**：\n\n"
                   "解压玩具类目近30天搜索量环比增长 **47%**，处于上升期早期。\n\n"
                   "• 抖音相关话题播放量突破 50 亿\n"
                   "• 淘宝搜索指数连续 14 天上涨\n"
                   "• 小红书笔记发布量日均 2000+",
            evidence=[
                "淘宝搜索指数 - 2026.08",
                "抖音热榜数据 - 2026.08",
                "小红书趋势洞察 - 2026.08",
            ],
        )
        if result.get("code") == 0:
            print("✅ 卡片发送成功！")
        else:
            print("❌ 卡片发送失败")
            print(f"   错误码: {result.get('code')}")
            print(f"   错误信息: {result.get('msg')}")
    except Exception as e:  # noqa: BLE001 — 手动测试脚本，打印所有错误
        print(f"❌ 发送异常: {e}")


if __name__ == "__main__":
    # 测试 1: 获取 token
    auth = test_token()
    if not auth:
        print("\n❌ Token 获取失败，无法继续测试")
        sys.exit(1)

    # 如果提供了 chat_id，测试发消息
    if len(sys.argv) > 1:
        chat_id = sys.argv[1]
        test_send_message(auth, chat_id)
        test_send_card(auth, chat_id)
    else:
        print("\n💡 提示：如果要测试发消息，请传入 chat_id 作为参数")
        print("   用法: python test_feishu.py oc_xxxxxxxxxx")
        print("\n   chat_id 获取方式：")
        print("   1. 群设置 → 群信息 → 群 ID")
        print("   2. 或者用飞书 API 获取群列表")
