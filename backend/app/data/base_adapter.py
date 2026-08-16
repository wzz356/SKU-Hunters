"""Base 数据访问层 — 统一适配器 + provider protocol + mock/fixture provider

约束：
- BaseDataAdapter 只能由 connector_gateway 或数据服务层持有，不能直接注入 Agent。
- 真实配置只从环境变量读取（FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_BASE_APP_TOKEN / FEISHU_DATA_TABLE_ID / FEISHU_SUMMARY_TABLE_ID）。
- 缺少配置时应用可启动；只有真正调用 Base 数据时才抛 BaseUnavailable。
- 当前未接入真实飞书 Base API（无字段映射），真实 provider 一律 fail-closed。
- 不打印 Token、不猜测飞书 API 字段、不伪造真实数据。
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Protocol

import requests
from pydantic import ValidationError

from app.schemas.base_data import BasePlatform, BaseQuery, BaseRecord, BaseRecordPage


class BaseUnavailable(Exception):
    """Base 数据源不可用（配置缺失或真实 API 未接入），与「无数据」严格区分"""


class BaseProviderError(Exception):
    """Base provider 调用失败（网络/超时等），与「无数据」严格区分"""


def _has_base_config() -> bool:
    """是否配置了真实飞书 Base 环境变量（只判断存在性，不读取 Token 值）"""
    return bool(os.getenv("FEISHU_BASE_APP_TOKEN")) and bool(os.getenv("FEISHU_DATA_TABLE_ID"))

def _resolve_provider_mode() -> str:
    """解析 Base 数据源模式：mock / feishu / disabled（默认 disabled = 生产 fail-closed）

    - mock：本地 fixture，仅显式开启（开发/演示/测试）
    - feishu：真实飞书 Base（需配置，未接字段映射前仍 fail-closed）
    - disabled：默认，任何 Base 数据调用都抛 BaseUnavailable（生产安全默认）
    """
    return os.getenv("BASE_PROVIDER_MODE", "disabled").strip().lower()

def _provider_for_mode(mode: str) -> BaseProvider:
    """按模式实例化 provider；未知/禁用模式 → BaseUnavailable（fail-closed）"""
    if mode == "mock":
        return MockBaseProvider()
    if mode == "feishu":
        if not _has_base_config():
            raise BaseUnavailable("BASE_PROVIDER_MODE=feishu 但缺少 FEISHU_BASE_APP_TOKEN / FEISHU_DATA_TABLE_ID")
        return FeishuBaseProvider()
    if mode == "disabled":
        raise BaseUnavailable("BASE_PROVIDER_MODE=disabled（默认），Base 数据访问已关闭")
    raise BaseUnavailable(f"未知 BASE_PROVIDER_MODE: {mode!r}")


class BaseProvider(Protocol):
    """Base 数据 provider 抽象接口（真实实现未接入，先定义协议）"""

    def search_records(
        self,
        keyword: str,
        platform: str | None = None,
        category: str | None = None,
        as_of: str | None = None,
        snapshot_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> BaseRecordPage: ...

    def get_summary(
        self,
        category: str | None = None,
        as_of: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]: ...

    def get_date_distribution(
        self,
        keyword: str,
        as_of: str | None = None,
        snapshot_id: str | None = None,
    ) -> list[dict[str, Any]]: ...


# ── 本地 fixture provider（演示/测试用，非真实数据）────────────

_FIXTURE_RECORDS: list[dict[str, Any]] = [
    {
        "record_id": "fixture-001", "keyword": "小风扇", "platform": "xiaohongshu",
        "category": "小风扇", "summary": "便携小风扇夏季通勤需求上升",
        "heat_index": 82.5, "interaction": 1200.0, "brand": "几素",
        "price_range": "39-99 元", "record_date": "2026-08-01",
        "source_url": "https://example.com/fan/001", "snapshot_id": "snap-2026-08-10",
        "ingested_at": "2026-08-10T10:00:00+00:00",
        "raw_value": {"likes": 1200, "comments": 88},
    },
    {
        "record_id": "fixture-002", "keyword": "小风扇", "platform": "bilibili",
        "category": "小风扇", "summary": "B站小风扇测评视频热度高",
        "heat_index": 75.0, "interaction": 900.0, "brand": None,
        "price_range": "49-99 元", "record_date": "2026-08-02",
        "source_url": "https://example.com/fan/002", "snapshot_id": "snap-2026-08-10",
        "ingested_at": "2026-08-10T10:05:00+00:00",
        "raw_value": {"views": 50000, "danmaku": 300},
    },
    {
        "record_id": "fixture-003", "keyword": "保温杯", "platform": "taobao",
        "category": "保温杯", "summary": "保温杯搜索联想词集中在品牌与容量",
        "heat_index": 60.0, "interaction": 400.0, "brand": "哈尔斯",
        "price_range": "59-159 元", "record_date": "2026-08-03",
        "source_url": None, "snapshot_id": "snap-2026-08-10",
        "ingested_at": "2026-08-10T10:10:00+00:00",
        "raw_value": {"suggest_count": 25},
    },
    {
        "record_id": "fixture-004", "keyword": "三丽鸥", "platform": "weibo",
        "category": "IP", "summary": "三丽鸥联名话题讨论活跃",
        "heat_index": 90.0, "interaction": 5000.0, "brand": "三丽鸥",
        "price_range": None, "record_date": "2026-08-04",
        "source_url": "https://example.com/ip/001", "snapshot_id": "snap-2026-08-11",
        "ingested_at": "2026-08-11T09:00:00+00:00",
        "raw_value": {"reposts": 800, "comments": 1500},
    },
    {
        "record_id": "fixture-005", "keyword": "小风扇", "platform": "google_trends",
        "category": "小风扇", "summary": "Google Trends 小风扇搜索热度上升",
        "heat_index": 70.0, "interaction": None, "brand": None,
        "price_range": None, "record_date": "2026-08-05",
        "source_url": "https://example.com/trends/001", "snapshot_id": "snap-2026-08-11",
        "ingested_at": "2026-08-11T09:10:00+00:00",
        "raw_value": {"level": 70, "growth": 12.5},
    },
]


# ── 企划品类归一化与父品类匹配 ──────────────────────────
# 父品类 → 匹配子串：明细 category 含该子串即归入父品类。
# 例：「风扇」作为唯一企划品类，便携小风扇/手持小风扇/桌面风扇/塔扇/循环扇等归入其中。
CATEGORY_PARENT_PATTERNS: dict[str, str] = {"风扇": "扇"}


def normalize_category(category: str | None) -> str | None:
    """企划层品类归一化：含「扇」的子品类（小风扇/便携小风扇/塔扇/循环扇…）统一为父品类「风扇」。

    旧任务里的历史名称（如「小风扇」）查询时兼容映射到「风扇」，聚合所有「扇」子品类。
    不含「扇」的品类（如雨伞、香薰）原样返回。
    """
    if not category:
        return category
    for parent, pattern in CATEGORY_PARENT_PATTERNS.items():
        if pattern in category:
            return parent
    return category


def category_matches(record_category, query_category):
    """明细 category 是否匹配查询品类：父品类按子串规则，普通品类等值匹配。

    - 查询「风扇」→ 明细 category 含「扇」即匹配（便携小风扇/落地扇/塔扇…）
    - 查询普通品类（雨伞/香薰）→ 等值匹配
    """
    if not query_category:
        return True
    pattern = CATEGORY_PARENT_PATTERNS.get(query_category)
    if pattern:
        return pattern in (record_category or "")
    return record_category == query_category


def _filter_records(
    records: list[BaseRecord],
    keyword: str | None = None,
    platform: str | None = None,
    category: str | None = None,
    as_of: str | None = None,
    snapshot_id: str | None = None,
) -> list[BaseRecord]:
    """内存过滤（Mock 与 Feishu provider 共用）：keyword 子串 / platform 等值 / category 等值 / as_of 边界 / snapshot 锁定"""
    result = list(records)
    if keyword:
        result = [r for r in result if keyword.lower() in r.keyword.lower()]
    if platform:
        result = [r for r in result if r.platform == platform]
    if category:
        result = [r for r in result if category_matches(r.category, category)]
    if as_of:
        result = [r for r in result if r.record_date <= as_of]  # 不读未来数据
    if snapshot_id:
        result = [r for r in result if r.snapshot_id == snapshot_id]  # 快照锁定
    return result


class MockBaseProvider:
    """本地 fixture provider — 未接真实飞书 API，仅用于演示与测试"""

    def __init__(self, records: list[dict[str, Any]] | None = None):
        self._records = [BaseRecord.model_validate(r) for r in (records or _FIXTURE_RECORDS)]

    def _filtered(self, keyword: str | None, platform: str | None, category: str | None, as_of: str | None, snapshot_id: str | None = None) -> list[BaseRecord]:
        return _filter_records(self._records, keyword, platform, category, as_of, snapshot_id)

    def search_records(self, keyword, platform=None, category=None, as_of=None, snapshot_id=None, page=1, page_size=20):
        filtered = self._filtered(keyword, platform, category, as_of, snapshot_id)
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        page_records = filtered[start:end]
        return BaseRecordPage(
            records=page_records,
            total=total,
            page=page,
            page_size=page_size,
            has_more=end < total,
        )

    def get_summary(self, category=None, as_of=None, snapshot_id=None):
        filtered = self._filtered(None, None, category, as_of)
        if snapshot_id:
            filtered = [r for r in filtered if r.snapshot_id == snapshot_id]
        total_heat = sum(r.heat_index or 0 for r in filtered)
        return {
            "category": category or "all",
            "snapshot_id": snapshot_id,
            "record_count": len(filtered),
            "avg_heat_index": round(total_heat / len(filtered), 2) if filtered else 0.0,
            "brands": sorted({r.brand for r in filtered if r.brand}),
        }

    def get_date_distribution(self, keyword, as_of=None, snapshot_id=None):
        filtered = self._filtered(keyword, None, None, as_of, snapshot_id)
        dist: dict[str, int] = {}
        for r in filtered:
            dist[r.record_date] = dist.get(r.record_date, 0) + 1
        return [{"date": d, "count": c} for d, c in sorted(dist.items())]


class FeishuBaseProvider:
    """真实飞书 Base provider（只读）— 从飞书多维表格读取采集记录

    - 认证复用 FeishuAuth（FEISHU_APP_ID/APP_SECRET → tenant_access_token），不自行维护 token。
    - 数据定位：FEISHU_BASE_APP_TOKEN（多维表格 ID）+ FEISHU_DATA_TABLE_ID（明细）/ FEISHU_SUMMARY_TABLE_ID（汇总）。
    - 缺配置 → BaseUnavailable；网络/飞书非零错误码 → BaseProviderError；与「无数据」严格区分。
    - 字段映射以 docs/guides/feishu-base-mapping.md §四/§五 为准（真实字段名未核对前为设计假设）。
    - 分页：飞书 page_token 游标；一期「拉全表 + 内存过滤 + 内存分页」，超 2 万条需 filter 下推优化。
    """

    _API = "https://open.feishu.cn/open-apis/bitable/v1/apps"
    _REQ_TIMEOUT = 10

    def __init__(
        self,
        auth: Any | None = None,
        app_token: str | None = None,
        data_table_id: str | None = None,
        summary_table_id: str | None = None,
    ):
        self._auth = auth
        self._app_token = app_token or os.getenv("FEISHU_BASE_APP_TOKEN")
        self._data_table_id = data_table_id or os.getenv("FEISHU_DATA_TABLE_ID")
        self._summary_table_id = summary_table_id or os.getenv("FEISHU_SUMMARY_TABLE_ID")
        self._caveats: list[dict[str, Any]] = []
        self._records_cache: list[BaseRecord] | None = None
        self._summary_cache: list[dict[str, Any]] | None = None

    # ── 配置与认证 ──────────────────────────────

    def _ensure_config(self) -> None:
        if not self._app_token or not self._data_table_id:
            raise BaseUnavailable("飞书 Base 配置缺失：FEISHU_BASE_APP_TOKEN / FEISHU_DATA_TABLE_ID")

    def _get_auth(self) -> Any:
        """复用 feishu.auth.FeishuAuth，不自行维护 token"""
        if self._auth is not None:
            return self._auth
        from feishu.auth import FeishuAuth
        from feishu.config import FeishuConfig

        config = FeishuConfig.from_env()
        if not config.app_id or not config.app_secret:
            raise BaseUnavailable("飞书认证配置缺失：FEISHU_APP_ID / FEISHU_APP_SECRET")
        return FeishuAuth(config)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_auth().get_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    def _post(
        self, table_id: str, body: dict[str, Any], page_token: str | None = None
    ) -> dict[str, Any]:
        """调用飞书记录查询接口，返回 data；网络/超时/非零错误码 → BaseProviderError"""
        url = f"{self._API}/{self._app_token}/tables/{table_id}/records/search"
        params: dict[str, str] = {}
        if page_token:
            params["page_token"] = page_token
        try:
            resp = requests.post(
                url, headers=self._headers(), json=body, params=params, timeout=self._REQ_TIMEOUT
            )
        except requests.RequestException as e:
            raise BaseProviderError(f"飞书 Base 请求失败（网络/超时）: {e}") from e
        # 先检查 HTTP 状态码，避免 4xx/5xx 且 code=0 的异常响应被误判成功
        if resp.status_code >= 400:
            raise BaseProviderError(f"飞书 Base HTTP 错误：status={resp.status_code}")
        try:
            data = resp.json()
        except ValueError as e:
            raise BaseProviderError(f"飞书 Base 响应非 JSON（HTTP {resp.status_code}）") from e
        if data.get("code") != 0:
            raise BaseProviderError(f"飞书 Base 返回错误 code={data.get('code')} msg={data.get('msg')}")
        return data.get("data", {})

    # ── 字段转换 ──────────────────────────────

    @staticmethod
    def _to_float(raw: Any) -> float | None:
        if raw is None:
            return None
        try:
            return float(raw)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_text(raw: Any) -> str | None:
        """将飞书文本/单选字段统一转换为纯文本。"""
        if raw is None:
            return None
        if isinstance(raw, str):
            return raw
        if isinstance(raw, list):
            parts = []
            for item in raw:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            return "".join(parts) if parts else None
        if isinstance(raw, dict) and "text" in raw:
            return str(raw["text"])
        return str(raw) if raw else None

    @staticmethod
    def _normalize_heat(raw: float | None) -> float | None:
        """将原始互动量按约定对数归一化到 0-100。"""
        if raw is None:
            return None
        if raw <= 0:
            return 0.0
        if raw <= 100:
            return round(raw, 2)
        import math

        lg = math.log10(raw)
        if lg < 3:
            return round(50 + (lg - 2) * 10, 2)
        if lg < 4:
            return round(70 + (lg - 3) * 5, 2)
        return round(min(100, 80 + (lg - 4) * 5), 2)

    @staticmethod
    def _ms_to_date(ms: Any) -> str | None:
        """毫秒时间戳 → YYYY-MM-DD"""
        if ms is None:
            return None
        try:
            return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _ms_to_iso(ms: Any) -> str | None:
        """毫秒时间戳 → ISO8601"""
        if ms is None:
            return None
        try:
            return datetime.fromtimestamp(float(ms) / 1000, tz=timezone.utc).isoformat()
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _to_url(raw: Any) -> str | None:
        """飞书 Url 字段（dict{link,text} 或 str）→ 链接；空/非 http(s) → None"""
        if raw is None:
            return None
        link = raw.get("link") if isinstance(raw, dict) else raw
        if not link:
            return None
        text = str(link)
        return text if text.startswith(("http://", "https://")) else None

    @staticmethod
    def _to_json(raw: Any) -> Any:
        """dict 原样；str 按 JSON 解析；失败 → None（raw_value / brands 通用）"""
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return None

    def _to_brands(self, raw: Any) -> list[str]:
        """飞书 brands 字段 → list[str]（兼容 JSON 字符串 / 文本列表 / 普通字符串 / 已 list）

        不伪造品牌；无法解析时返回空列表。
        """
        if raw is None:
            return []
        if isinstance(raw, list):
            if all(isinstance(x, str) for x in raw):
                return [x for x in raw if x]
            parts = []
            for item in raw:
                if isinstance(item, dict) and "text" in item:
                    parts.append(str(item["text"]))
                elif isinstance(item, str):
                    parts.append(item)
            text = "".join(parts)
        elif isinstance(raw, dict) and "text" in raw:
            text = str(raw["text"])
        else:
            text = str(raw) if raw else ""
        parsed = self._to_json(text) if text else None
        if isinstance(parsed, list):
            return [str(x) for x in parsed if x]
        if text:
            return [text]
        return []

    @staticmethod
    def _unwrap_text_list(raw: Any) -> Any:
        """飞书富文本列表 [{"text": "...", "type": "text"}] → 拼接为纯文本；否则原样返回

        仅当 list 中每项为 dict 且含 "text" 键、且不含结构化 "count"/"value" 键时判定为
        飞书文本列表（区别于已 list 的痛点/场景条目），拼接后便于后续 JSON 解析。
        """
        if isinstance(raw, list) and raw and all(
            isinstance(i, dict) and "text" in i and "count" not in i and "value" not in i
            for i in raw
        ):
            return "".join(str(i.get("text", "")) for i in raw)
        return raw

    @staticmethod
    def _to_pain_points(raw: Any) -> list[dict[str, Any]]:
        """飞书 pain_points 字段（JSON 文本 / 已 list / 文本列表）→ [{"text": str, "count": number}]

        仅在 JSON 结果为 list 时接受；每项须 dict，text 非空字符串，count 可转非负数；
        非法项跳过，不抛异常，不伪造。错误 JSON / dict / 普通字符串 → []。
        """
        raw = FeishuBaseProvider._unwrap_text_list(raw)
        parsed = FeishuBaseProvider._to_json(raw)
        if not isinstance(parsed, list):
            return []
        out: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            raw_text = item.get("text")
            if not isinstance(raw_text, str) or not raw_text.strip():
                continue
            text = raw_text.strip()
            if not text:
                continue
            count = item.get("count")
            if count is None:
                continue
            try:
                count_f = float(count)
            except (ValueError, TypeError):
                continue
            if count_f < 0:
                continue
            out.append({"text": text, "count": count_f})
        return out

    @staticmethod
    def _to_scenes(raw: Any) -> list[dict[str, Any]]:
        """飞书 scenes 字段（JSON 文本 / 已 list / 文本列表）→ [{"name": str, "value": number}]

        仅在 JSON 结果为 list 时接受；每项须 dict，name 非空字符串，value 可转非负数；
        非法项跳过，不抛异常，不伪造。错误 JSON / dict / 普通字符串 → []。
        """
        raw = FeishuBaseProvider._unwrap_text_list(raw)
        parsed = FeishuBaseProvider._to_json(raw)
        if not isinstance(parsed, list):
            return []
        out: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict):
                continue
            raw_name = item.get("name")
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue
            name = raw_name.strip()
            if not name:
                continue
            value = item.get("value")
            if value is None:
                continue
            try:
                value_f = float(value)
            except (ValueError, TypeError):
                continue
            if value_f < 0:
                continue
            out.append({"name": name, "value": value_f})
        return out

    def _to_base_record(self, fields: dict[str, Any], record_id: str) -> tuple[BaseRecord | None, dict[str, Any] | None]:
        """飞书字段 → BaseRecord；非法 platform/字段校验失败 → (None, caveat)（跳过但不静默吞掉）"""
        platform_raw = self._to_text(fields.get("platform"))
        try:
            platform = BasePlatform(platform_raw) if platform_raw else None
        except ValueError:
            return None, {"record_id": record_id, "field": "platform", "reason": f"非法 platform: {platform_raw!r}"}

        data = {
            "record_id": self._to_text(fields.get("record_id")) or record_id,
            "keyword": self._to_text(fields.get("keyword")),
            "platform": platform,
            "category": self._to_text(fields.get("category")) or "",
            "summary": self._to_text(fields.get("summary")) or "",
            "heat_index": self._normalize_heat(self._to_float(fields.get("heat_index"))),
            "interaction": self._to_float(fields.get("interaction")),
            "brand": self._to_text(fields.get("brand")),
            "price_range": self._to_text(fields.get("price_range")),
            "record_date": self._ms_to_date(fields.get("record_date")),
            "source_url": self._to_url(fields.get("source_url")),
            "snapshot_id": self._to_text(fields.get("snapshot_id")),
            "ingested_at": self._ms_to_iso(fields.get("ingested_at")),
            "raw_value": self._to_json(self._to_text(fields.get("raw_value"))),
        }
        try:
            return BaseRecord.model_validate(data), None
        except ValidationError as e:
            return None, {"record_id": record_id, "field": None, "reason": str(e)}

    # ── 拉取 ──────────────────────────────

    def _fetch_all(self) -> list[BaseRecord]:
        """page_token 游标拉取明细表全量并转为 BaseRecord（跳过非法记录、记 caveat；带请求级缓存）"""
        if self._records_cache is not None:
            return self._records_cache
        self._ensure_config()
        records: list[BaseRecord] = []
        caveats: list[dict[str, Any]] = []
        page_token: str | None = None
        max_pages = 100  # 防御：异常时兜底
        for _ in range(max_pages):
            body: dict[str, Any] = {"limit": 500}
            data = self._post(self._data_table_id, body, page_token=page_token)
            for item in data.get("items", []):
                record, caveat = self._to_base_record(item.get("fields", {}), item.get("record_id", ""))
                if record is not None:
                    records.append(record)
                elif caveat is not None:
                    caveats.append(caveat)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break  # 无进展保护
        self._caveats = caveats
        self._records_cache = records
        return records

    def _fetch_summary_rows(self) -> list[dict[str, Any]]:
        """拉取汇总表全量原始字段；汇总表未配置 → BaseUnavailable；带请求级缓存"""
        if self._summary_cache is not None:
            return self._summary_cache
        if not self._summary_table_id:
            raise BaseUnavailable("飞书汇总表未配置：FEISHU_SUMMARY_TABLE_ID")
        self._ensure_config()
        rows: list[dict[str, Any]] = []
        page_token: str | None = None
        max_pages = 100
        for _ in range(max_pages):
            body: dict[str, Any] = {"limit": 500}
            data = self._post(self._summary_table_id, body, page_token=page_token)
            for item in data.get("items", []):
                fields = item.get("fields", {})
                row = dict(fields)
                # 飞书文本字段为 [{"text": "...", "type": "text"}]，归一化为 str 便于匹配
                row["category"] = self._to_text(row.get("category"))
                row["snapshot_id"] = self._to_text(row.get("snapshot_id"))
                rows.append(row)
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        self._summary_cache = rows
        return rows

    # ── 查询接口（BaseProvider protocol）──────────────

    def search_records(self, keyword, platform=None, category=None, as_of=None, snapshot_id=None, page=1, page_size=20) -> BaseRecordPage:
        all_records = self._fetch_all()
        filtered = _filter_records(all_records, keyword, platform, category, as_of, snapshot_id)
        total = len(filtered)
        start = (page - 1) * page_size
        end = start + page_size
        page_records = filtered[start:end]
        return BaseRecordPage(records=page_records, total=total, page=page, page_size=page_size, has_more=end < total)

    def get_summary(self, category=None, as_of=None, snapshot_id=None) -> dict[str, Any]:
        rows = self._fetch_summary_rows()
        matched: list[dict[str, Any]] = []
        for row in rows:
            if category is not None and row.get("category") != category:
                continue
            if snapshot_id is not None and row.get("snapshot_id") != snapshot_id:
                continue
            if as_of is not None:
                row_as_of = self._ms_to_date(row.get("as_of"))
                if row_as_of is None or row_as_of > as_of:
                    continue
            matched.append(row)
        if not matched:
            # 一期不做静默实时聚合降级：无匹配快照即明确失败
            raise BaseUnavailable("飞书汇总表无匹配快照（category/as_of/snapshot_id 无命中）")
        # 确定性选择：指定 snapshot_id 应唯一；否则按 as_of 降序选最新；重复即歧义
        if snapshot_id is not None:
            if len(matched) > 1:
                raise BaseProviderError(f"汇总表快照 {snapshot_id} 存在 {len(matched)} 条重复，无法确定性选择")
            row = matched[0]
        else:
            matched.sort(key=lambda r: r.get("as_of") or 0, reverse=True)
            row = matched[0]
            if len(matched) > 1 and (matched[1].get("as_of") or 0) == (row.get("as_of") or 0):
                raise BaseProviderError("汇总表存在多条相同 as_of 的快照，无法确定性选择")
        brands = self._to_brands(row.get("brands"))
        return {
            "category": row.get("category") or category or "all",
            "snapshot_id": row.get("snapshot_id"),
            "record_count": int(self._to_float(row.get("record_count")) or 0),
            "avg_heat_index": self._normalize_heat(self._to_float(row.get("avg_heat_index"))) or 0.0,
            "brands": brands,
            "pain_points": self._to_pain_points(row.get("pain_points")),
            "scenes": self._to_scenes(row.get("scenes")),
        }

    def get_date_distribution(self, keyword, as_of=None, snapshot_id=None) -> list[dict[str, Any]]:
        all_records = self._fetch_all()
        filtered = _filter_records(all_records, keyword, None, None, as_of, snapshot_id)
        dist: dict[str, int] = {}
        for r in filtered:
            dist[r.record_date] = dist.get(r.record_date, 0) + 1
        return [{"date": d, "count": c} for d, c in sorted(dist.items())]

    @property
    def caveats(self) -> list[dict[str, Any]]:
        """最近一次拉取中被跳过的非法记录（结构化 caveat，供审计，不静默吞掉）"""
        return list(self._caveats)

    def clear_cache(self) -> None:
        """清空明细/汇总表缓存与 caveat（下一次查询重新拉取飞书）"""
        self._records_cache = None
        self._summary_cache = None
        self._caveats = []


# ── 统一适配器 ────────────────────────────────────────────

class BaseDataAdapter:
    """Base 数据访问层（仅 connector_gateway / 数据服务层持有，不注入 Agent）

    - 延迟初始化 provider，import 阶段不读配置、不失败。
    - session/request 级缓存，缓存 key 含查询条件 + as_of + snapshot_id。
    - 数据源故障（BaseUnavailable/BaseProviderError）与「无数据」（空结果）严格区分。
    """

    def __init__(self, provider: BaseProvider | None = None):
        self._provider = provider
        self._cache: dict[str, Any] = {}

    @property
    def provider(self) -> BaseProvider:
        if self._provider is None:
            self._provider = _provider_for_mode(_resolve_provider_mode())
        return self._provider

    def _cache_key(self, method: str, **kwargs: Any) -> str:
        return json.dumps({"method": method, **kwargs}, sort_keys=True, default=str)

    def search_records(self, keyword, platform=None, category=None, as_of=None, snapshot_id=None, page=1, page_size=20) -> BaseRecordPage:
        # 统一经 BaseQuery 校验：as_of 日期格式、page/page_size 边界、platform 枚举
        query = BaseQuery(keyword=keyword, platform=platform, category=category, as_of=as_of, snapshot_id=snapshot_id, page=page, page_size=page_size)
        key = self._cache_key(
            "search_records", keyword=query.keyword, platform=query.platform,
            category=query.category, as_of=query.as_of, snapshot_id=query.snapshot_id,
            page=query.page, page_size=query.page_size,
        )
        if key in self._cache:
            return self._cache[key]
        result = self.provider.search_records(query.keyword, query.platform, query.category, query.as_of, query.snapshot_id, query.page, query.page_size)
        self._cache[key] = result
        return result

    def search_all(self, keyword="", platform=None, category=None, as_of=None, snapshot_id=None) -> list[BaseRecord]:
        """翻页收集全部记录（供聚合统计使用，避免只统计默认 page_size=20 的第一页）

        含最大页数与无进展保护，防止 provider 异常持续返回 has_more=True 导致死循环。
        """
        records: list[BaseRecord] = []
        page = 1
        max_pages = 100  # 防御上限：正常数据远不会达到，异常时兜底
        while page <= max_pages:
            result = self.search_records(keyword, platform, category, as_of, snapshot_id, page=page, page_size=200)
            records.extend(result.records)
            if not result.has_more:
                break
            if not result.records:
                # 无进展保护：has_more=True 但本页无记录 → provider 异常，终止翻页
                break
            page += 1
        return records

    def get_summary(self, category=None, as_of=None, snapshot_id=None) -> dict[str, Any]:
        query = BaseQuery(category=category, as_of=as_of, snapshot_id=snapshot_id)
        key = self._cache_key("get_summary", category=query.category, as_of=query.as_of, snapshot_id=query.snapshot_id)
        if key in self._cache:
            return self._cache[key]
        result = self.provider.get_summary(query.category, query.as_of, query.snapshot_id)
        self._cache[key] = result
        return result

    def get_date_distribution(self, keyword, as_of=None, snapshot_id=None) -> list[dict[str, Any]]:
        query = BaseQuery(keyword=keyword, as_of=as_of, snapshot_id=snapshot_id)
        key = self._cache_key("get_date_distribution", keyword=query.keyword, as_of=query.as_of, snapshot_id=query.snapshot_id)
        if key in self._cache:
            return self._cache[key]
        result = self.provider.get_date_distribution(query.keyword, query.as_of, query.snapshot_id)
        self._cache[key] = result
        return result

    def compute_heat_index(self, keyword, as_of=None, snapshot_id=None) -> float | None:
        """基于全部记录计算综合热度指数（简单平均，供 TrendDataView 使用）"""
        records = self.search_all(keyword, as_of=as_of, snapshot_id=snapshot_id)
        heats = [r.heat_index for r in records if r.heat_index is not None]
        if not heats:
            return None
        return round(sum(heats) / len(heats), 2)

    def build_evidence_refs(self, records: list[BaseRecord]) -> list[dict[str, str]]:
        """从记录生成可点击证据引用；source_url 缺失/无效的记录被跳过（不伪造链接）"""
        refs: list[dict[str, str]] = []
        for r in records:
            if not r.source_url:
                continue
            refs.append({
                "url": r.source_url,
                "title": f"{r.keyword} · {r.platform}",
                "snippet": (r.summary or "")[:200],
            })
        return refs

    def clear_cache(self) -> None:
        self._cache.clear()


class BaseQueryPort(Protocol):
    """受限查询端口协议 — View 只能通过这组只读方法访问 Base 数据

    这是「应用层能力隔离」的类型契约：View 依赖本协议，而非完整 BaseDataAdapter。
    """

    def search_records(
        self,
        keyword: str,
        platform: str | None = None,
        category: str | None = None,
        as_of: str | None = None,
        snapshot_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> BaseRecordPage: ...

    def search_all(
        self,
        keyword: str = "",
        platform: str | None = None,
        category: str | None = None,
        as_of: str | None = None,
        snapshot_id: str | None = None,
    ) -> list[BaseRecord]: ...

    def get_summary(
        self,
        category: str | None = None,
        as_of: str | None = None,
        snapshot_id: str | None = None,
    ) -> dict[str, Any]: ...

    def get_date_distribution(
        self,
        keyword: str,
        as_of: str | None = None,
        snapshot_id: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def compute_heat_index(self, keyword: str, as_of: str | None = None, snapshot_id: str | None = None) -> float | None: ...

    def build_evidence_refs(self, records: list[BaseRecord]) -> list[dict[str, str]]: ...

class RestrictedQueryPort:
    """受限查询端口 — 只暴露只读查询方法，隐藏 adapter 的管理方法（如 clear_cache）

    View 持有本端口（而非完整 BaseDataAdapter），公共接口仅限 BaseQueryPort 的只读查询。
    内部仍持有一个 adapter 引用（私有 _adapter），但 View 无法通过本端口调用管理/写方法。
    注意：这仍是应用层能力隔离（Python 反射可绕过），不是进程级安全边界。
    """

    def __init__(self, adapter: BaseDataAdapter):
        self._adapter = adapter

    def search_records(self, keyword, platform=None, category=None, as_of=None, snapshot_id=None, page=1, page_size=20):
        return self._adapter.search_records(keyword, platform, category, as_of, snapshot_id, page, page_size)

    def search_all(self, keyword="", platform=None, category=None, as_of=None, snapshot_id=None):
        return self._adapter.search_all(keyword, platform, category, as_of, snapshot_id)

    def get_summary(self, category=None, as_of=None, snapshot_id=None):
        return self._adapter.get_summary(category, as_of, snapshot_id)

    def get_date_distribution(self, keyword, as_of=None, snapshot_id=None):
        return self._adapter.get_date_distribution(keyword, as_of, snapshot_id)

    def compute_heat_index(self, keyword, as_of=None, snapshot_id=None):
        return self._adapter.compute_heat_index(keyword, as_of, snapshot_id)

    def build_evidence_refs(self, records):
        return self._adapter.build_evidence_refs(records)
