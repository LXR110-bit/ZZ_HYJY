"""
chat_id ↔ 我们生成的纪要文档 token 进程内映射缓存。
用于会议结束后 N 小时内，监听到智能纪要卡片时反查应该往哪篇文档追加截图。
"""
import threading
import time
from typing import Optional

# {chat_id: [(timestamp, topic, doc_token), ...]}，按时间倒序
_store: dict[str, list[tuple[float, str, str]]] = {}
_lock = threading.Lock()

# 同一个智能纪要 URL 重复触发去重（key=minute_doc_token）
_processed: set[str] = set()
_processed_lock = threading.Lock()

DEFAULT_TTL = 8 * 3600  # 8 小时


def record(chat_id: str, topic: str, doc_token: str) -> None:
    """记录一次会议结束生成的文档"""
    with _lock:
        bucket = _store.setdefault(chat_id, [])
        bucket.insert(0, (time.time(), topic, doc_token))
        # 顺手清理超时的
        cutoff = time.time() - DEFAULT_TTL
        _store[chat_id] = [x for x in bucket if x[0] >= cutoff]


def find_recent(chat_id: str, max_age_seconds: int = DEFAULT_TTL) -> Optional[tuple[str, str]]:
    """查最近一条该 chat 的纪要文档。返回 (topic, doc_token)，找不到返回 None。"""
    cutoff = time.time() - max_age_seconds
    with _lock:
        bucket = _store.get(chat_id, [])
        for ts, topic, token in bucket:
            if ts >= cutoff:
                return topic, token
    return None


def consume_once(minute_doc_token: str) -> bool:
    """
    去重：如果这个智能纪要 token 已经处理过，返回 False；
    否则标记为已处理并返回 True。
    """
    with _processed_lock:
        if minute_doc_token in _processed:
            return False
        _processed.add(minute_doc_token)
        # 进程级别集合，简单防爆：超过 1000 条时清理最早 500 条
        if len(_processed) > 1000:
            for x in list(_processed)[:500]:
                _processed.discard(x)
    return True
