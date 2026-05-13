import json
import re
import time
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID
from services.tokens import get_user_access_token

BASE_URL = "https://open.feishu.cn/open-apis"

_tenant_cache = {"token": None, "expire_at": 0}


def get_tenant_access_token() -> str:
    """应用身份 token，用于发消息、创建文档、查会议基础信息。"""
    if _tenant_cache["token"] and time.time() < _tenant_cache["expire_at"] - 60:
        return _tenant_cache["token"]
    resp = requests.post(
        f"{BASE_URL}/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
    )
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {data}")
    _tenant_cache["token"] = data["tenant_access_token"]
    _tenant_cache["expire_at"] = time.time() + data["expire"]
    return _tenant_cache["token"]


def _tenant_headers():
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def _user_headers():
    return {
        "Authorization": f"Bearer {get_user_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def get_minute_token_by_meeting(meeting_id: str) -> str:
    """通过会议 ID 拿到对应妙记的 minute_token。

    响应 data.recording.url 形如 https://meetings.feishu.cn/minutes/obcnk2h1a34f6596ra19nj58
    截取 /minutes/ 后面的部分即是 minute_token。
    """
    resp = requests.get(
        f"{BASE_URL}/vc/v1/meetings/{meeting_id}/recording",
        headers=_tenant_headers(),
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 获取会议录制信息失败: {data}")
        return ""
    url = data.get("data", {}).get("recording", {}).get("url", "")
    m = re.search(r"/minutes/([A-Za-z0-9]+)", url)
    if not m:
        print(f"[feishu] 从 url 解析 minute_token 失败: {url}")
        return ""
    return m.group(1)


def get_meeting_minutes_transcript(meeting_id: str) -> str:
    """完整流程：meeting_id → minute_token → 逐字稿文本。

    飞书妙记逐字稿 API 返回纯文本（不是 JSON），content-type 为 text/plain。
    """
    minute_token = get_minute_token_by_meeting(meeting_id)
    if not minute_token:
        return ""
    print(f"[feishu] 获取到 minute_token: {minute_token}")

    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{minute_token}/transcript",
        headers=_user_headers(),
    )
    print(f"[feishu] transcript API status={resp.status_code} ct={resp.headers.get('Content-Type')}")

    # 飞书返回 text/plain 纯文本逐字稿
    content_type = resp.headers.get("Content-Type", "")
    if resp.status_code == 200 and "application/json" not in content_type:
        # 飞书有时不带 charset，requests 会用 ISO-8859-1 猜测导致中文乱码
        # 强制按 UTF-8 解码原始字节
        return resp.content.decode("utf-8", errors="replace")

    # 失败时返回 JSON 错误
    try:
        data = resp.json()
        print(f"[feishu] 获取逐字稿失败: {data}")
    except Exception:
        print(f"[feishu] 获取逐字稿失败，原始响应前 200 字节: {resp.text[:200]}")
    return ""


def send_message_to_chat(chat_id: str, content: str):
    """发送文本消息到飞书群（应用身份）。"""
    resp = requests.post(
        f"{BASE_URL}/im/v1/messages",
        headers=_tenant_headers(),
        params={"receive_id_type": "chat_id"},
        json={
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": content}),
        },
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 发送消息失败: {data}")
    return data


def create_document(title: str, content: str) -> str:
    """创建飞书文档，返回文档 URL。"""
    resp = requests.post(
        f"{BASE_URL}/docx/v1/documents",
        headers=_tenant_headers(),
        json={"title": title},
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 创建文档失败: {data}")
        return ""
    document_id = data.get("data", {}).get("document", {}).get("document_id", "")

    body_blocks = []
    for block in content.split("\n"):
        if not block.strip():
            continue
        if block.startswith("## "):
            body_blocks.append({
                "block_type": 4,
                "heading2": {"elements": [{"text_run": {"content": block[3:]}}]},
            })
        else:
            body_blocks.append({
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": block}}]},
            })

    if body_blocks:
        requests.post(
            f"{BASE_URL}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=_tenant_headers(),
            json={"children": body_blocks, "index": 0},
        )

    return f"https://feishu.cn/docx/{document_id}"


def send_summary_and_doc(summary: str, doc_url: str):
    message = f"📋 会议纪要已生成\n\n{summary}\n\n📄 完整版文档: {doc_url}"
    send_message_to_chat(FEISHU_CHAT_ID, message)
