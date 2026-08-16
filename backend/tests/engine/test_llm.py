"""LLM 入口的 prompt 保险丝测试 — cap_user_prompt

锁定：短文本原样通过；超长按 2/3 头 + 1/3 尾截断，中段省略有显式标记，
总长受控；指令所在的 system prompt 不经过此函数（由 complete 调用位置保证）。
"""

from app.engine.llm import cap_user_prompt


class TestCapUserPrompt:
    def test_short_text_unchanged(self):
        text = "短材料"
        assert cap_user_prompt(text) == text
        assert cap_user_prompt(text, max_chars=10) == text

    def test_exact_limit_unchanged(self):
        text = "x" * 100
        assert cap_user_prompt(text, max_chars=100) == text

    def test_long_text_truncated_with_marker(self):
        head_part = "头" * 800
        mid_part = "中" * 800
        tail_part = "尾" * 400
        text = head_part + mid_part + tail_part  # 2000 字符
        result = cap_user_prompt(text, max_chars=1200)

        assert "已省略" in result
        assert "800 字符" in result  # 省略量 = 2000 - 1200
        assert result.startswith("头" * 10)
        assert result.endswith("尾" * 10)
        # 总长 = 上限 + 标记行
        assert len(result) < 1200 + 40

    def test_head_tail_ratio(self):
        """头 2/3 尾 1/3：Brief 在头、反馈/历史在尾，都要保住"""
        text = "A" * 600 + "B" * 600 + "C" * 600
        result = cap_user_prompt(text, max_chars=900)
        assert "A" * 500 in result      # 头部 600 全保（600=900*2/3）
        assert "C" * 300 in result      # 尾部 300 保
        assert "B" * 400 not in result  # 中段被截
