"""追加式会议账本；写入失败不阻断原有自动生成。"""
import json
import threading
import time
from pathlib import Path
from config import DRY_RUN
from services.log import log

LEDGER_FILE = Path(__file__).parent.parent / ".meeting_ledger.jsonl"
_lock = threading.Lock()


def record(entry: dict) -> None:
    if DRY_RUN:
        return
    try:
        with _lock:
            with LEDGER_FILE.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(entry, recorded_at=time.time()), ensure_ascii=False) + "\n")
    except OSError as exc:
        log(f"[ledger] 写入失败 error={type(exc).__name__}")


def generated(minute_token: str, doc_url: str) -> None:
    record({"minute_token": minute_token, "status": "generated", "doc_url": doc_url})


def entries() -> list[dict]:
    with _lock:
        try:
            lines = LEDGER_FILE.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            return []
    result = []
    for line in lines:
        try:
            row = json.loads(line)
            if isinstance(row, dict):
                result.append(row)
        except ValueError:
            log("[ledger] 忽略损坏的单行")
    return result


def missing(now: float | None = None) -> list[dict]:
    now = time.time() if now is None else now
    meetings, completed = {}, set()
    for row in entries():
        token = row.get("minute_token")
        if row.get("status") == "generated" and token:
            completed.add(token)
        key = row.get("meeting_id")
        if key:
            meetings[key] = row
    return sorted((row for row in meetings.values()
                   if now - 7 * 86400 <= row["meeting_time"] <= now
                   and row["status"] not in ("generated", "processing")
                   and row.get("minute_token") not in completed),
                  key=lambda row: row["meeting_time"], reverse=True)
