"""小红书公开数据导入器（本地 JSON/CSV）

功能：
  - 批量导入本地 JSON / CSV 文件
  - 按 note_url 去重（同批次取 captured_at 最新；跨批次按唯一键 upsert）
  - 清洗：缺失字段补默认、非法数字归 None、tags 规范化
  - 隐私过滤：不保存手机号、真实姓名、私信、登录凭证等
  - 保留原始数据与采集来源（source_type / source_url / captured_at）

数据来源边界：
  - 仅处理小红书官方授权 API、官方导出文件或用户提供的公开数据文件
  - 不实现验证码绕过 / 登录破解 / 反爬绕过 / 批量注册 / 高频抓取
  - 无合法数据源时不做"实时抓取"，仅导入本地文件并做样例验证

用法：
  python -m app.xhs.ingestor path/to/a.json path/to/b.csv [--keyword 关键词] [--db /abs/xhs.db]
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.xhs import store

# 字段别名 -> 规范列
_FIELD_ALIASES = {
    "id": ("id", "note_id", "nid", "笔记id"),
    "note_url": ("note_url", "url", "link", "note_link", "笔记链接"),
    "title": ("title", "题目", "标题"),
    "content": ("content", "body", "text", "正文"),
    "publish_time": ("publish_time", "pub_time", "date", "发布时间"),
    "likes": ("likes", "like", "like_count", "点赞"),
    "collects": ("collects", "collect", "collect_count", "favorite", "收藏"),
    "comments": ("comments", "comment", "comment_count", "评论"),
    "views": ("views", "view", "view_count", "read", "阅读"),
    "tags": ("tags", "tag", "label", "labels", "标签"),
    "query_keyword": ("query_keyword", "keyword", "query", "关键词"),
    "captured_at": ("captured_at", "capture_time", "采集时间"),
    "source_type": ("source_type", "来源"),
    "source_url": ("source_url", "来源链接"),
}

# 隐私：字段名命中即整字段丢弃
_PRIVACY_FIELD_RE = re.compile(
    r"(phone|mobile|tel|real_name|id_card|idcard|id_no|password|passwd|pwd|"
    r"token|access_token|secret|cookie|login_credential|private_message|dm|chat)",
    re.IGNORECASE,
)
# 隐私：文本内容中剥离明显敏感串
_PRIVACY_PATTERNS = [
    re.compile(r"1[3-9]\d{9}"),                  # 大陆手机号
    re.compile(r"\d{17}[\dXx]"),                 # 18 位身份证
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),  # 邮箱
    re.compile(r"AK[A-Za-z0-9]{16,}"),           # AccessKey
    re.compile(r"SK[A-Za-z0-9]{16,}"),           # SecretKey
]

# 常见中英文停用词（词频统计用）
STOPWORDS = {
    "的", "了", "和", "是", "在", "有", "就", "不", "都", "而", "及", "与", "着",
    "或", "一个", "没有", "我们", "你们", "他们", "这个", "那个", "什么", "怎么",
    "可以", "因为", "所以", "但是", "如果", "以及", "the", "a", "an", "and", "or",
    "of", "to", "in", "for", "on", "with", "is", "are", "was", "were", "it", "this",
}


def parse_int(value) -> int | None:
    """非法数字返回 None，不抛异常。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip().replace(",", "")
    if not s or s.lower() in {"none", "null", "na", "n/a", "-"}:
        return None
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return None


def split_tags(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(t).strip() for t in value if str(t).strip()]
    if isinstance(value, (int, float)):
        return [str(value)]
    s = str(value)
    parts = re.split(r"[,，;；|#\s]+", s)
    return [p.strip().lstrip("#") for p in parts if p.strip()]


def _strip_privacy_text(text: str | None) -> str | None:
    """从文本中剥离手机号/身份证/邮箱等敏感串。"""
    if not text:
        return text
    for pat in _PRIVACY_PATTERNS:
        text = pat.sub("[已脱敏]", text)
    return text


def _has_privacy_field(record: dict) -> bool:
    """检查记录是否含隐私字段名。"""
    return any(_PRIVACY_FIELD_RE.search(str(k)) for k in record.keys())


def sanitize_record(record: dict) -> dict:
    """隐私过滤 + 字段清洗，返回可安全入库的 dict（仅保留规范字段）。"""
    clean: dict = {}
    for canon, aliases in _FIELD_ALIASES.items():
        val = None
        for a in aliases:
            if a in record and record[a] is not None:
                val = record[a]
                break
        clean[canon] = val

    # 隐私字段名整字段丢弃
    clean = {k: v for k, v in clean.items() if k not in store.PRIVACY_FIELD_NAMES}

    # 文本脱敏
    clean["title"] = _strip_privacy_text(clean.get("title"))
    clean["content"] = _strip_privacy_text(clean.get("content"))

    # 数字清洗
    for k in ("likes", "collects", "comments", "views"):
        clean[k] = parse_int(clean.get(k))

    # tags 规范化
    clean["tags"] = split_tags(clean.get("tags"))

    # 默认值（用 or 兜底：setdefault 不会覆盖已存在的 None 键）
    clean["query_keyword"] = clean.get("query_keyword") or ""
    clean["source_type"] = clean.get("source_type") or "xhs"
    clean["source_url"] = clean.get("source_url") or clean.get("note_url")
    clean["captured_at"] = clean.get("captured_at") or datetime.now(timezone.utc).isoformat()
    # id 缺省用 note_url 派生，保证主键可用
    if not clean.get("id"):
        clean["id"] = clean.get("note_url") or f"auto-{uuid.uuid4().hex[:12]}"
    return clean


def load_json(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        # 兼容 {"notes": [...]} / {keyword: [...]} 包裹结构
        for k in ("notes", "items", "data", "records"):
            if isinstance(data.get(k), list):
                return data[k]
        # 单条 dict
        if any("note_url" in d or "url" in d for d in [data]):
            return [data]
        raise ValueError(f"无法识别的 JSON 结构: {path.name}")
    if isinstance(data, list):
        return data
    raise ValueError(f"JSON 顶层必须是 list 或 dict: {path.name}")


def load_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(r) for r in reader if any(v for v in r.values())]


def load_file(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix in (".json",):
        return load_json(path)
    if suffix in (".csv", ".tsv"):
        return load_csv(path)
    raise ValueError(f"不支持的格式 {suffix}（仅支持 .json/.csv/.tsv）")


def _dedupe_batch(records: list[dict]) -> tuple[list[dict], int]:
    """同批次内按 note_url 去重，保留 captured_at 最新的一条。"""
    best: dict[str, dict] = {}
    dropped = 0
    for r in records:
        key = r.get("note_url") or r.get("id")
        if not key:
            dropped += 1  # 无唯一键，视为无法定位，跳过
            continue
        if key in best:
            dropped += 1
            if (r.get("captured_at") or "") > (best[key].get("captured_at") or ""):
                best[key] = r
        else:
            best[key] = r
    return list(best.values()), dropped


def ingest_paths(paths: list[str], db_path: str | None = None,
                 keyword: str | None = None) -> dict:
    """批量导入本地文件，返回汇总统计与每条 run 记录。"""
    conn = store.connect(db_path)
    summary = {"inserted": 0, "updated": 0, "skipped": 0, "invalid": 0, "total": 0}
    runs: list[dict] = []
    for p in paths:
        path = Path(p)
        run_id = uuid.uuid4().hex[:12]
        started = datetime.now(timezone.utc).isoformat()
        run = {"run_id": run_id, "keyword": keyword or "", "file_path": str(path),
               "status": "failed", "total": 0, "inserted": 0, "updated": 0,
               "skipped": 0, "invalid": 0, "started_at": started, "finished_at": None,
               "message": ""}
        try:
            raw = load_file(path)
            run["total"] = len(raw)
            clean_records = []
            invalid = 0
            for rec in raw:
                # 隐私字段名直接拒收该条（无法保证不泄露）
                if _has_privacy_field(rec):
                    invalid += 1
                    continue
                clean = sanitize_record(rec)
                if not (clean.get("note_url") or clean.get("id")):
                    invalid += 1
                    continue
                clean_records.append(clean)
            run["invalid"] = invalid

            deduped, dropped = _dedupe_batch(clean_records)
            run["skipped"] = dropped + invalid

            res = store.upsert_notes(conn, deduped)
            run["inserted"] = res["inserted"]
            run["updated"] = res["updated"]
            run["status"] = "success" if invalid == 0 else "partial"
            run["finished_at"] = datetime.now(timezone.utc).isoformat()
            run["message"] = f"导入完成: 新增{res['inserted']}, 更新{res['updated']}, 跳过{dropped + invalid}"

            summary["inserted"] += res["inserted"]
            summary["updated"] += res["updated"]
            summary["skipped"] += dropped + invalid
            summary["invalid"] += invalid
            summary["total"] += len(raw)
        except Exception as e:  # noqa: BLE001
            run["status"] = "failed"
            run["finished_at"] = datetime.now(timezone.utc).isoformat()
            run["message"] = str(e)
        store.add_run(conn, run)
        runs.append(run)
    conn.close()
    return {"summary": summary, "runs": runs}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="小红书公开数据本地导入器")
    ap.add_argument("files", nargs="+", help="待导入的 JSON/CSV 文件路径")
    ap.add_argument("--keyword", default=None, help="本次导入对应的搜索关键词")
    ap.add_argument("--db", default=None, help="SQLite 库路径（默认 backend/data/xhs.db）")
    args = ap.parse_args(argv)
    result = ingest_paths(args.files, db_path=args.db, keyword=args.keyword)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
