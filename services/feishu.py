import json
import time
import requests
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, FEISHU_CHAT_ID

BASE_URL = "https://open.feishu.cn/open-apis"

_token_cache = {"token": None, "expire_at": 0}


def get_tenant_access_token() -> str:
    if _token_cache["token"] and time.time() < _token_cache["expire_at"] - 60:
        return _token_cache["token"]

    resp = requests.post(
        f"{BASE_URL}/auth/v1/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
    )
    data = resp.json()
    _token_cache["token"] = data["tenant_access_token"]
    _token_cache["expire_at"] = time.time() + data["expire"]
    return _token_cache["token"]


def _headers():
    return {
        "Authorization": f"Bearer {get_tenant_access_token()}",
        "Content-Type": "application/json; charset=utf-8",
    }


def get_meeting_minutes_transcript(meeting_id: str) -> str:
    """通过妙记 API 获取会议逐字稿"""
    # PLACEHOLDER_CONTINUE
    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{meeting_id}/transcript",
        headers=_headers(),
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 获取逐字稿失败: {data}")
        return ""

    paragraphs = data.get("data", {}).get("paragraphs", [])
    lines = []
    for p in paragraphs:
        speaker = p.get("speaker", {}).get("user_name", "未知")
        content = p.get("content", "")
        lines.append(f"{speaker}: {content}")
    return "\n".join(lines)


def get_minutes_by_meeting(meeting_id: str) -> dict:
    """通过会议 ID 获取关联的妙记信息"""
    resp = requests.get(
        f"{BASE_URL}/vc/v1/meetings/{meeting_id}",
        headers=_headers(),
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 获取会议信息失败: {data}")
        return {}
    meeting = data.get("data", {}).get("meeting", {})
    return meeting


def send_message_to_chat(chat_id: str, content: str):
    """发送文本消息到飞书群"""
    resp = requests.post(
        f"{BASE_URL}/im/v1/messages",
        headers=_headers(),
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
    """创建飞书文档，返回文档 URL"""
    resp = requests.post(
        f"{BASE_URL}/docx/v1/documents",
        headers=_headers(),
        json={"title": title},
    )
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 创建文档失败: {data}")
        return ""

    document = data.get("data", {}).get("document", {})
    document_id = document.get("document_id", "")

    blocks = content.split("\n")
    body_blocks = []
    for block in blocks:
        if not block.strip():
            continue
        if block.startswith("## "):
            body_blocks.append({
                "block_type": 3,  # heading2
                "heading2": {
                    "elements": [{"text_run": {"content": block[3:]}}]
                },
            })
        else:
            body_blocks.append({
                "block_type": 2,  # text
                "text": {
                    "elements": [{"text_run": {"content": block}}]
                },
            })

    if body_blocks:
        doc_block_resp = requests.get(
            f"{BASE_URL}/docx/v1/documents/{document_id}/blocks/{document_id}",
            headers=_headers(),
        )
        doc_block_data = doc_block_resp.json()
        page_block_id = doc_block_data.get("data", {}).get("block", {}).get("block_id", document_id)

        requests.post(
            f"{BASE_URL}/docx/v1/documents/{document_id}/blocks/{page_block_id}/children",
            headers=_headers(),
            json={"children": body_blocks, "index": 0},
        )

    doc_url = f"https://bytedance.feishu.cn/docx/{document_id}"
    return doc_url


def send_summary_and_doc(summary: str, doc_url: str):
    """发送摘要+文档链接到群"""
    message = f"📋 会议纪要已生成\n\n{summary}\n\n📄 完整版文档: {doc_url}"
    send_message_to_chat(FEISHU_CHAT_ID, message)
