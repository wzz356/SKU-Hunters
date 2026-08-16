"""
飞书卡片模板 - 7个委员的发言卡片
每个委员有不同的颜色和图标
"""
from typing import Any

# 委员配置：名字、颜色、图标
COMMITTEE_CONFIG = {
    "trend": {
        "name": "🔍 趋势官",
        "color": "blue",
        "subtitle": "市场研究总监",
    },
    "user": {
        "name": "👥 用户官",
        "color": "green",
        "subtitle": "用户研究负责人",
    },
    "ip": {
        "name": "🧸 IP官",
        "color": "purple",
        "subtitle": "IP合作经理",
    },
    "creative": {
        "name": "🎨 创意官",
        "color": "orange",
        "subtitle": "商品策划经理",
    },
    "business": {
        "name": "💰 商业官",
        "color": "red",
        "subtitle": "财务评审",
    },
    "global": {
        "name": "🌍 全球化官",
        "color": "turquoise",
        "subtitle": "海外运营负责人",
    },
    "learning": {
        "name": "📈 学习官",
        "color": "wathet",
        "subtitle": "数据分析负责人",
    },
    "challenge": {
        "name": "⚔️ 质询",
        "color": "indigo",
        "subtitle": "圆桌质询环节",
    },
    "decision": {
        "name": "🎯 Decision Engine",
        "color": "gold",
        "subtitle": "立项建议合成",
    },
    "retro": {
        "name": "📝 复盘",
        "color": "grey",
        "subtitle": "会后复盘",
    },
    "qa": {
        "name": "💬 问答",
        "color": "grey",
        "subtitle": "答疑",
    },
}


def build_committee_card(
    role: str,
    content: str,
    evidence: list[str] | None = None,
    score: float | None = None,
    extra_fields: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    生成委员发言卡片

    Args:
        role: 委员角色 (trend/user/ip/creative/business/global/learning)
        content: 主要内容（分析结论）
        evidence: 证据列表
        score: 评分（0-100），商业官用
        extra_fields: 额外字段 {标题: 内容}
    """
    cfg = COMMITTEE_CONFIG.get(role, COMMITTEE_CONFIG["trend"])

    elements = []

    # 副标题（岗位）
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**{cfg['subtitle']}**",
        },
    })

    elements.append({"tag": "hr"})

    # 主要内容
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": content,
        },
    })

    # 评分（商业官专用）
    if score is not None:
        elements.append({"tag": "hr"})
        score_color = "green" if score >= 80 else "orange" if score >= 60 else "red"
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**机会值评分：<font color='{score_color}'>{score:.1f} / 100</font>**",
            },
        })

    # 额外字段
    if extra_fields:
        elements.append({"tag": "hr"})
        for k, v in extra_fields.items():
            elements.append({
                "tag": "div",
                "fields": [
                    {
                        "is_short": True,
                        "text": {
                            "tag": "lark_md",
                            "content": f"**{k}**\n{v}",
                        },
                    },
                ],
            })

    # 证据列表
    if evidence:
        elements.append({"tag": "hr"})
        evidence_text = "\n".join([f"• {e}" for e in evidence[:5]])  # 最多显示5条
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**📎 证据来源**\n{evidence_text}",
            },
        })

    # 底部备注
    elements.append({"tag": "hr"})
    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": "SKU Hunters · AI Product Committee · 演示数据（Mock Agent）",
            },
        ],
    })

    card = {
        "config": {
            "wide_screen_mode": True,
        },
        "header": {
            "title": {
                "tag": "plain_text",
                "content": cfg["name"],
            },
            "template": cfg["color"],
        },
        "elements": elements,
    }

    return card


def build_start_card(topic: str) -> dict[str, Any]:
    """生成评审开始卡片"""
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "⚡ 评审开始"},
            "template": "blue",
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**评审主题**：{topic}\n\nAI 委员会已启动，七位委员正在分析中...",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": "📊 第一幕：趋势官、用户官、IP官 并行分析中...",
                },
            },
        ],
    }


def build_summary_card(topic: str, final_score: float, recommendation: str) -> dict[str, Any]:
    """生成最终总结卡片"""
    score_color = "green" if final_score >= 80 else "orange" if final_score >= 60 else "red"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "🎯 评审结论"},
            "template": score_color,
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**评审主题**：{topic}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**综合机会值：<font color='{score_color}'>{final_score:.1f} / 100</font>**",
                },
            },
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**Decision Engine 建议**\n{recommendation}",
                },
            },
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "✅ 通过立项"},
                        "type": "primary",
                        "value": {"action": "approve", "topic": topic},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "❌ 否决"},
                        "type": "danger",
                        "value": {"action": "reject", "topic": topic},
                    },
                ],
            },
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [
                    {"tag": "plain_text", "content": "💡 以上为 AI 建议，最终决策由商品经理拍板"},
                ],
            },
        ],
    }


def build_gate_card(
    gate: str,
    prompt: str,
    session_id: str,
    gate_label: str = "人工决策",
) -> dict[str, Any]:
    """生成人工 Gate 决策卡片，按钮 value 携带 session_id 以便恢复 checkpoint。"""
    if gate == "retro":
        actions = [
            {"tag": "button", "text": {"tag": "plain_text", "content": "💬 继续提问"},
             "type": "default",
             "value": {"session_id": session_id, "gate": gate, "action": "question"}},
            {"tag": "button", "text": {"tag": "plain_text", "content": "📝 结束复盘"},
             "type": "primary",
             "value": {"session_id": session_id, "gate": gate, "action": "done"}},
        ]
    else:
        actions = [
            {"tag": "button", "text": {"tag": "plain_text", "content": "✅ 确认"},
             "type": "primary",
             "value": {"session_id": session_id, "gate": gate, "action": "confirm"}},
            {"tag": "button", "text": {"tag": "plain_text", "content": "❌ 否决"},
             "type": "danger",
             "value": {"session_id": session_id, "gate": gate, "action": "reject"}},
        ]

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🚪 {gate_label}"},
            "template": "orange" if gate != "retro" else "grey",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**{prompt}**"}},
            {"tag": "hr"},
            {
                "tag": "div",
                "text": {"tag": "lark_md",
                         "content": f"会议 ID：`{session_id}`\n\n"
                                    "支持文本指令："
                                    "`修改 <意见>` / `追问 <问题>` "
                                    "/ `通过` / `否决 <理由>`"},
            },
            {"tag": "hr"},
            {"tag": "action", "actions": actions},
            {"tag": "hr"},
            {
                "tag": "note",
                "elements": [{"tag": "plain_text",
                              "content": "AI 建议仅供参考·演示数据（Mock Agent）"}],
            },
        ],
    }
    return card
