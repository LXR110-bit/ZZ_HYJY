"""一次性补录近七天日志：python -m services.backfill_meeting_ledger。

只有唯一候选时关联无会议 ID 的行；自动成功用紧邻的 smart_notes meeting 行核对。
"""
import argparse
import gzip
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from services import meeting_ledger


def parse_logs(log_dir: Path, now: float) -> list[dict]:
    files = sorted(log_dir.glob("feishu-bot.log*"),
                   key=lambda p: int(p.name.split(".")[2]) if len(p.name.split(".")) > 2 else 0,
                   reverse=True)
    meetings, active, self_jobs = {}, set(), set()
    recent_doc = None
    successes = {}
    for path in files:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as stream:
            for number, line in enumerate(stream, 1):
                evidence = f"{path.name}:{number}"
                gate = re.search(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] \[gate\] meeting=(\S+) topic=(.*?) attend=True\b", line)
                if gate:
                    stamp, mid, topic = gate.groups()
                    ts = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
                    meetings[mid] = {"meeting_id": mid, "topic": topic, "meeting_time": ts,
                                     "status": "unknown", "minute_token": "", "doc_url": "",
                                     "source": "日志补录", "evidence": [evidence]}
                    active.add(mid)
                probe = re.search(r"妙记可读性探测: state=(\w+) minute=(\w+)", line)
                pending = [mid for mid in active if not meetings[mid]["minute_token"]]
                if probe and len(pending) == 1:
                    row = meetings[pending[0]]
                    row["minute_token"] = probe[2]
                    row["evidence"].append(evidence)
                    if probe[1] == "forbidden":
                        row["status"] = "forbidden"
                        active.discard(pending[0])
                no_token = re.search(r"未取到 minute_token，放弃: (.*?) reason=(\S+)", line)
                if no_token:
                    matching = [mid for mid in active if meetings[mid]["topic"] == no_token[1]]
                    if len(matching) == 1:
                        row = meetings[matching[0]]
                        row["status"] = "no_recording" if no_token[2] == "no_recording_url" else "timeout" if no_token[2] == "processing" else "error"
                        row["evidence"].append(evidence)
                        active.discard(matching[0])
                if "轮询超时逐字稿仍为空" in line and len(active) == 1:
                    mid = next(iter(active)); meetings[mid]["status"] = "timeout"
                    meetings[mid]["evidence"].append(evidence); active.discard(mid)
                doc = re.search(r"\[event\] 已发送群消息，文档: (https://\S+)", line)
                if doc:
                    recent_doc = (doc[1], evidence)
                smart = re.search(r"\[smart_notes\] 开始等待智能纪要: meeting=(\S+)", line)
                if smart and recent_doc and smart[1] in active:
                    row = meetings[smart[1]]
                    row.update(status="generated", doc_url=recent_doc[0])
                    row["evidence"].extend([recent_doc[1], evidence])
                    active.discard(smart[1]); recent_doc = None
                job = re.search(r"\[minute_request\] 拉取结果 minute=(\w+) status=ok", line)
                if job:
                    self_jobs.add(job[1])
                created = re.search(r"\[minute_request\] 文档已创建 .* url=(https://\S+)", line)
                if created:
                    if len(self_jobs) == 1:
                        successes[next(iter(self_jobs))] = (created[1], evidence)
                    self_jobs.clear()
                failed = re.search(r"\[minute_request\] 处理异常 minute=(\w+)", line)
                if failed:
                    self_jobs.discard(failed[1])
    for row in meetings.values():
        if row["minute_token"] in successes:
            url, evidence = successes[row["minute_token"]]
            row.update(status="generated", doc_url=url)
            row["evidence"].append(evidence)
    return sorted((r for r in meetings.values() if now-7*86400 <= r["meeting_time"] <= now),
                  key=lambda r: r["meeting_time"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log-dir", default="/var/log")
    parser.add_argument("--now", type=float, default=None)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    rows = parse_logs(Path(args.log_dir), args.now or time.time())
    existing = {r.get("meeting_id") for r in meeting_ledger.entries()}
    for row in rows:
        if args.write and row["meeting_id"] not in existing:
            meeting_ledger.record(row)
        print(f"{row['meeting_id']} | {row['status']} | {row['minute_token']} | {','.join(row['evidence'])}")
    print(f"TOTAL={len(rows)} write={args.write}")


if __name__ == "__main__":
    main()
