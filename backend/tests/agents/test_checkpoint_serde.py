"""第五阶段：严格 MsgPack / checkpoint 序列化测试

背景：进入 state dict 的 app.schemas 枚举默认未被注册，JsonPlusSerializer
反序列化时会提示 "Deserializing unregistered type" 警告，开启
LANGGRAPH_STRICT_MSGPACK=true 严格模式后可能直接阻断。

graph.py 将 7 个枚举注册到 JsonPlusSerializer 的 allowed_msgpack_modules。
本测试验证：
  1. 所有进入 state 的枚举能在注册后的 serde 下 round-trip（类型不丢）
  2. 严格序列化下，含枚举的 state 通过 checkpoint 存取后枚举类型保留
  3. 每个枚举类名确实已注册（防止将来新增枚举遗漏注册）
"""

from app.engine.graph import _ALLOWED_MSGPACK_TYPES, _serde
from app.schemas.brief import BudgetRange, WeightTemplate
from app.schemas.challenge import ChallengeStance
from app.schemas.evidence import Confidence
from app.schemas.recommendation import Decision
from app.schemas.review import ConflictType
from app.schemas.testcase import Outcome
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

# 与 graph.py 注册表一一对应，缺一即失败
ENUM_TYPES = [
    WeightTemplate,
    BudgetRange,
    ChallengeStance,
    Confidence,
    Decision,
    ConflictType,
    Outcome,
]
EXPECTED_REGISTRY = {
    ("app.schemas.brief", "WeightTemplate"),
    ("app.schemas.brief", "BudgetRange"),
    ("app.schemas.challenge", "ChallengeStance"),
    ("app.schemas.evidence", "Confidence"),
    ("app.schemas.recommendation", "Decision"),
    ("app.schemas.review", "ConflictType"),
    ("app.schemas.testcase", "Outcome"),
}


class TestRegistryComplete:
    """注册表与枚举全集一致，防止新增枚举漏注册。"""

    def test_registry_has_all_enum_types(self):
        registered = {(et.__module__, et.__name__) for et in ENUM_TYPES}
        assert registered == EXPECTED_REGISTRY
        assert EXPECTED_REGISTRY <= _ALLOWED_MSGPACK_TYPES


class TestEnumSerdeRoundTrip:
    """所有枚举成员经注册后的 serde 序列化/反序列化往返不丢值、不丢类型。"""

    def test_all_members_roundtrip(self):
        payload: dict = {}
        for et in ENUM_TYPES:
            payload[et.__name__] = [m for m in et]

        blob = _serde.dumps_typed(payload)
        # 返回 (serde 类型标记, 字节流) 二元组
        assert isinstance(blob, tuple) and isinstance(blob[1], bytes)
        loaded = _serde.loads_typed(blob)

        assert loaded == payload
        for et in ENUM_TYPES:
            for member in loaded[et.__name__]:
                # 类型必须保留为枚举实例，而不是被降级成普通 str
                assert type(member) is et

    def test_embedded_in_state_dict(self):
        """枚举嵌套在完整 state 结构中也能 round-trip。"""
        payload = {
            "weight_template": WeightTemplate.IMAGE,
            "budget_range": BudgetRange.LOW,
            "stance": ChallengeStance.OPPOSE,
            "confidence": Confidence.MEDIUM,
            "decision": Decision.HOLD,
            "conflict": ConflictType.C1_DATA_SIGNAL,
            "outcome": Outcome.FLOP,
            "nested": {"conflict": ConflictType.C2_QUOTE_DEVIATION},
        }
        loaded = _serde.loads_typed(_serde.dumps_typed(payload))
        assert loaded == payload
        assert loaded["weight_template"] is WeightTemplate.IMAGE
        assert loaded["nested"]["conflict"] is ConflictType.C2_QUOTE_DEVIATION


class _State(TypedDict):
    conflict: ConflictType
    stance: ChallengeStance
    confidence: Confidence
    decision: Decision
    outcome: Outcome


def _produce(state: _State) -> _State:
    return {
        "conflict": ConflictType.C4_HUMAN_AI,
        "stance": ChallengeStance.REVISE,
        "confidence": Confidence.HIGH,
        "decision": Decision.APPROVE,
        "outcome": Outcome.HIT,
    }


class TestCheckpointEnumRoundTrip:
    """含枚举的 state 经真实 checkpoint 存取后枚举类型保留（严格 MsgPack 场景）。"""

    def test_memory_checkpoint_preserves_enum(self):
        g = StateGraph(_State)
        g.add_node("produce", _produce)
        g.add_edge(START, "produce")
        g.add_edge("produce", END)
        app = g.compile(checkpointer=MemorySaver(serde=_serde))

        config = {"configurable": {"thread_id": "serde-test-1"}}
        app.invoke({}, config)
        snapshot = app.get_state(config)

        assert snapshot.values["decision"] is Decision.APPROVE
        assert snapshot.values["conflict"] is ConflictType.C4_HUMAN_AI
        assert snapshot.values["stance"] is ChallengeStance.REVISE
        assert snapshot.values["confidence"] is Confidence.HIGH
        assert snapshot.values["outcome"] is Outcome.HIT

    def test_strict_msgpack_env_checkpoint_works(self, monkeypatch):
        """显式开启严格 MsgPack 后，注册过的枚举 checkpoint 仍能正常读写。"""
        monkeypatch.setenv("LANGGRAPH_STRICT_MSGPACK", "true")
        g = StateGraph(_State)
        g.add_node("produce", _produce)
        g.add_edge(START, "produce")
        g.add_edge("produce", END)
        app = g.compile(checkpointer=MemorySaver(serde=_serde))

        config = {"configurable": {"thread_id": "serde-test-2"}}
        app.invoke({}, config)
        snapshot = app.get_state(config)
        assert snapshot.values["decision"] is Decision.APPROVE
        assert snapshot.values["outcome"] is Outcome.HIT
