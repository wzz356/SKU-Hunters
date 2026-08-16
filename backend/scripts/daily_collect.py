"""每日趋势采集 — 一键跑完趋势扫描+历史回溯，按日期累积进 archive（演示曲线来源）

用法（backend/ 目录）：
    ./venv/Scripts/python scripts/daily_collect.py

做什么：
  1. 依次调用 trend_scan.py（实时五源+联想词打分）和
     trend_backfill.py（UApiPro 历史检索实测环比）——复用已验证的入口
  2. 把两份快照合并为一条当日记录，追加进 data/trend_archive.jsonl
     （JSON Lines，一行一天；同日重复运行会覆盖当天那行，可安全重跑）

为什么存在：演示日评委问"趋势曲线哪来的"，打开 trend_archive.jsonl——
从 2026-08-14 起每天一行真实采集记录，曲线不是赛前突击攒的。

调度：由 Windows 计划任务「SKU-Hunters-DailyCollect」每天 12:05 自动执行
（注册命令见 docs/guides/demo-walkthrough.md；电脑关机错过则当天缺行，
手动补跑即可，同日重跑会覆盖）。

注：全程约 2-3 分钟（历史回溯每词每平台 1 次请求 + 间隔防限流）。
控制台输出只用 ASCII（计划任务下 GBK 控制台打印中文/符号会炸）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PYTHON = BACKEND / "venv" / "Scripts" / "python.exe"
SCAN_SNAPSHOT = BACKEND / "data" / "trend_scan_snapshot.json"
HISTORY_SNAPSHOT = BACKEND / "data" / "trend_history.json"
ARCHIVE_FILE = BACKEND / "data" / "trend_archive.jsonl"


def _run_step(script: str) -> bool:
    """子进程跑一个采集脚本（-X utf8 防 GBK 控制台炸）；返回是否成功"""
    result = subprocess.run(
        [str(PYTHON), "-X", "utf8", str(BACKEND / "scripts" / script)],
        cwd=BACKEND,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        tail = (result.stderr or result.stdout).strip().splitlines()[-3:]
        print(f"[FAIL] {script}: {' / '.join(tail)[:200]}")
        return False
    print(f"[OK] {script}")
    return True


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def append_to_archive(record: dict) -> int:
    """追加当日记录（同日覆盖）；返回 archive 总天数"""
    lines = []
    if ARCHIVE_FILE.exists():
        lines = [
            json.loads(line)
            for line in ARCHIVE_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    lines = [r for r in lines if r.get("date") != record["date"]]
    lines.append(record)
    lines.sort(key=lambda r: r["date"])
    ARCHIVE_FILE.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
        encoding="utf-8",
    )
    return len(lines)


def main() -> int:
    today = datetime.now(timezone.utc).astimezone().date().isoformat()
    print(f"daily collect for {today}")

    scan_ok = _run_step("trend_scan.py")
    backfill_ok = _run_step("trend_backfill.py")
    if not (scan_ok or backfill_ok):
        print("[FAIL] both steps failed, nothing archived")
        return 1

    record = {
        "date": today,
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "scan": _load_json(SCAN_SNAPSHOT) if scan_ok else None,
        "history": _load_json(HISTORY_SNAPSHOT) if backfill_ok else None,
    }
    days = append_to_archive(record)

    # 控制台简报：archive 深度 + 当日机会池命中情况
    print(f"archive depth: {days} day(s) -> {ARCHIVE_FILE.name}")
    if record["scan"]:
        ascii_grade = {"机会池": "OPPORTUNITY", "观察": "WATCH", "淘汰": "REJECTED"}
        grades = {}
        for card in record["scan"].get("cards", []):
            label = ascii_grade.get(card["grade"], card["grade"])
            grades[label] = grades.get(label, 0) + 1
        print("today grades: " + ", ".join(f"{g}x{n}" for g, n in sorted(grades.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
