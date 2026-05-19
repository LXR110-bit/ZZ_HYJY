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

    children_id, descendants = _build_doc_descendants(content)
    if descendants:
        r = requests.post(
            f"{BASE_URL}/docx/v1/documents/{document_id}/blocks/{document_id}/descendant",
            headers=_tenant_headers(),
            json={"children_id": children_id, "index": 0, "descendants": descendants},
        )
        d = r.json()
        if d.get("code") != 0:
            print(f"[feishu] descendant 失败，降级为纯文本: {d}")
            _fallback_text_only(document_id, content)

    return f"https://feishu.cn/docx/{document_id}"


def _gen_tmp_id() -> str:
    import uuid
    return uuid.uuid4().hex[:24]


def _parse_doc_blocks(content: str):
    """把 markdown 文本拆成 [('text', line) | ('table', [[...rows...]])] 列表。"""
    lines = content.split("\n")
    result, i = [], 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                # 跳过 |---|---| 分隔行
                if not all(set(c) <= set("-: ") for c in cells if c):
                    rows.append(cells)
                i += 1
            if rows:
                result.append(("table", rows))
            continue
        if stripped:
            result.append(("text", line))
        i += 1
    return result


_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_BULLET_RE = re.compile(r"^\s*[-*]\s+(.*)")
_ORDERED_RE = re.compile(r"^\s*\d+\.\s+(.*)")


def _parse_inline(text: str) -> list:
    """把 **xxx** 拆成 text_run 列表，支持加粗。其余按普通 text_run。"""
    elements = []
    pos = 0
    for m in _BOLD_RE.finditer(text):
        if m.start() > pos:
            elements.append({"text_run": {"content": text[pos:m.start()]}})
        elements.append({
            "text_run": {
                "content": m.group(1),
                "text_element_style": {"bold": True},
            }
        })
        pos = m.end()
    if pos < len(text):
        elements.append({"text_run": {"content": text[pos:]}})
    if not elements:
        elements.append({"text_run": {"content": text}})
    return elements


def _text_block(tmp_id: str, line: str) -> dict:
    if line.startswith("# "):
        return {"block_id": tmp_id, "block_type": 3,
                "heading1": {"elements": _parse_inline(line[2:])}}
    if line.startswith("## "):
        return {"block_id": tmp_id, "block_type": 4,
                "heading2": {"elements": _parse_inline(line[3:])}}
    if line.startswith("### "):
        return {"block_id": tmp_id, "block_type": 5,
                "heading3": {"elements": _parse_inline(line[4:])}}

    m = _BULLET_RE.match(line)
    if m:
        return {"block_id": tmp_id, "block_type": 12,
                "bullet": {"elements": _parse_inline(m.group(1))}}
    m = _ORDERED_RE.match(line)
    if m:
        return {"block_id": tmp_id, "block_type": 13,
                "ordered": {"elements": _parse_inline(m.group(1))}}

    return {"block_id": tmp_id, "block_type": 2,
            "text": {"elements": _parse_inline(line)}}


def _build_table(rows) -> tuple[str, list]:
    """构造一个表格 + 所有单元格 + 单元格内文本的 descendant 列表。"""
    table_id = _gen_tmp_id()
    col_count = max(len(r) for r in rows)
    cell_ids, descendants = [], []
    for row in rows:
        row_padded = row + [""] * (col_count - len(row))
        for cell_text in row_padded:
            cell_id, text_id = _gen_tmp_id(), _gen_tmp_id()
            cell_ids.append(cell_id)
            descendants.append({
                "block_id": cell_id,
                "block_type": 32,
                "table_cell": {},
                "children": [text_id],
            })
            descendants.append({
                "block_id": text_id,
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": cell_text}}]},
            })
    descendants.insert(0, {
        "block_id": table_id,
        "block_type": 31,
        "table": {"property": {"row_size": len(rows), "column_size": col_count}},
        "children": cell_ids,
    })
    return table_id, descendants


def _build_doc_descendants(content: str):
    parts = _parse_doc_blocks(content)
    children_id, descendants = [], []
    for kind, payload in parts:
        if kind == "text":
            tmp_id = _gen_tmp_id()
            children_id.append(tmp_id)
            descendants.append(_text_block(tmp_id, payload))
        else:
            table_id, table_descs = _build_table(payload)
            children_id.append(table_id)
            descendants.extend(table_descs)
    return children_id, descendants


def _fallback_text_only(document_id: str, content: str):
    """descendant API 失败时的兜底：把表格行转成"字段：值"列表，全部用普通文本写入。"""
    body_blocks = []
    parts = _parse_doc_blocks(content)
    for kind, payload in parts:
        if kind == "text":
            line = payload
            if line.startswith("## "):
                body_blocks.append({"block_type": 4,
                                    "heading2": {"elements": [{"text_run": {"content": line[3:]}}]}})
            else:
                body_blocks.append({"block_type": 2,
                                    "text": {"elements": [{"text_run": {"content": line}}]}})
        else:
            rows = payload
            headers = rows[0] if rows else []
            for row in rows[1:]:
                for col_idx, cell in enumerate(row):
                    field = headers[col_idx] if col_idx < len(headers) else f"列{col_idx + 1}"
                    body_blocks.append({"block_type": 2,
                                        "text": {"elements": [{"text_run": {"content": f"{field}: {cell}"}}]}})
                body_blocks.append({"block_type": 2,
                                    "text": {"elements": [{"text_run": {"content": "---"}}]}})
    if body_blocks:
        requests.post(
            f"{BASE_URL}/docx/v1/documents/{document_id}/blocks/{document_id}/children",
            headers=_tenant_headers(),
            json={"children": body_blocks, "index": 0},
        )


def send_summary_and_doc(summary: str, doc_url: str):
    message = f"📋 会议纪要已生成\n\n{summary}\n\n📄 完整版文档: {doc_url}"
    send_message_to_chat(FEISHU_CHAT_ID, message)
