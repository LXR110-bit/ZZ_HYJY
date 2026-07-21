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


def get_minute_summary(minute_token: str) -> str:
    """获取飞书妙记的智能纪要（AI 生成的摘要）。"""
    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{minute_token}",
        headers=_user_headers(),
    )
    content_type = resp.headers.get("Content-Type", "")
    if resp.status_code == 200 and "application/json" not in content_type:
        return resp.content.decode("utf-8", errors="replace")
    try:
        data = resp.json()
        if data.get("code") == 0:
            # 尝试从 JSON 结构中提取纪要内容
            minute_data = data.get("data", {}).get("minute", {})
            summary = minute_data.get("summary", "") or minute_data.get("content", "")
            if summary:
                return summary
        print(f"[feishu] 获取智能纪要: {data}")
    except Exception:
        print(f"[feishu] 获取智能纪要失败，原始响应前 200 字节: {resp.text[:200]}")
    return ""


def get_meeting_minutes_transcript(meeting_id: str) -> str:
    """完整流程：meeting_id → minute_token → 逐字稿 + AI 产物。

    同时拉取逐字稿和 AI 产物（结构化摘要），拼在一起返回给 Claude 处理。
    """
    minute_token = get_minute_token_by_meeting(meeting_id)
    if not minute_token:
        print("[feishu] 未获取到 minute_token（可能未开启录制），跳过")
        return ""
    print(f"[feishu] 获取到 minute_token: {minute_token}")

    # 拉逐字稿
    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{minute_token}/transcript",
        headers=_user_headers(),
    )
    print(f"[feishu] transcript API status={resp.status_code} ct={resp.headers.get('Content-Type')}")

    transcript = ""
    content_type = resp.headers.get("Content-Type", "")
    if resp.status_code == 200 and "application/json" not in content_type:
        transcript = resp.content.decode("utf-8", errors="replace")
    else:
        try:
            data = resp.json()
            print(f"[feishu] 获取逐字稿失败: {data}")
        except Exception:
            print(f"[feishu] 获取逐字稿失败，原始响应前 200 字节: {resp.text[:200]}")

    # 拉 AI 产物
    artifacts = get_minute_artifacts(minute_token)
    summary = ""
    if artifacts:
        summary = artifacts.get("summary", "")
        print(f"[feishu] 获取到 AI 产物，summary 长度: {len(summary)} 字符")

    # 拼接：优先都给 Claude，让它综合判断
    parts = []
    if summary:
        parts.append(f"【飞书智能纪要】\n{summary}")
    if transcript:
        parts.append(f"【逐字稿】\n{transcript}")

    if not parts:
        return ""
    return "\n\n---\n\n".join(parts)


def get_minute_meta(minute_token: str) -> dict:
    """获取妙记基本信息（标题等）。失败返回空 dict。"""
    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{minute_token}",
        headers=_user_headers(),
    )
    if resp.status_code != 200:
        print(f"[feishu] minute meta API status={resp.status_code}")
        return {}
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 获取妙记信息失败: code={data.get('code')}, msg={data.get('msg', '')[:100]}")
        return {}
    minute = data.get("data", {}).get("minute", {})
    return {
        "title": minute.get("title", ""),
        "topic": minute.get("topic", ""),
        "owner": minute.get("owner", {}),
    }


def get_transcript_by_minute_token(minute_token: str) -> str:
    """直接用 minute_token 拉逐字稿 + AI 产物，返回拼接文本。"""
    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{minute_token}/transcript",
        headers=_user_headers(),
    )
    print(f"[feishu] transcript API (by token) status={resp.status_code}")

    transcript = ""
    content_type = resp.headers.get("Content-Type", "")
    if resp.status_code == 200 and "application/json" not in content_type:
        transcript = resp.content.decode("utf-8", errors="replace")
    else:
        try:
            data = resp.json()
            print(f"[feishu] 获取逐字稿失败: {data}")
        except Exception:
            print(f"[feishu] 获取逐字稿失败，原始响应前 200 字节: {resp.text[:200]}")

    artifacts = get_minute_artifacts(minute_token)
    summary = ""
    if artifacts:
        summary = artifacts.get("summary", "")
        print(f"[feishu] AI 产物 summary 长度: {len(summary)} 字符")

    parts = []
    if summary:
        parts.append(f"【飞书智能纪要】\n{summary}")
    if transcript:
        parts.append(f"【逐字稿】\n{transcript}")

    if not parts:
        return ""
    return "\n\n---\n\n".join(parts)



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

    # 设为组织内可编辑 + 转移所有权给用户（不阻塞主流程）
    try:
        set_doc_tenant_editable(document_id)
        transfer_doc_owner(document_id, "ou_a6cee6c6461d5ba265b68fea58f89b3a")
    except Exception as e:
        print(f"[feishu] 设置文档权限失败（不影响内容生成）: {e}")

    return f"https://feishu.cn/docx/{document_id}"


def set_doc_tenant_editable(doc_token: str) -> bool:
    """把 docx 设为组织内任何人可编辑。返回是否成功。"""
    r = requests.patch(
        f"{BASE_URL}/drive/v1/permissions/{doc_token}/public",
        headers=_tenant_headers(),
        params={"type": "docx"},
        json={"link_share_entity": "tenant_editable"},
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        print(f"[feishu] 设置组织内可编辑失败: {d}")
        return False
    return True


def add_doc_owner(doc_token: str, open_id: str) -> bool:
    """把指定用户设为文档管理者（full_access），这样用户可以改权限。"""
    r = requests.post(
        f"{BASE_URL}/drive/v1/permissions/{doc_token}/members",
        headers=_tenant_headers(),
        params={"type": "docx"},
        json={
            "member_type": "openid",
            "member_id": open_id,
            "perm": "full_access",
        },
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        print(f"[feishu] 设置文档管理者失败: {d}")
        return False
    return True


def transfer_doc_owner(doc_token: str, open_id: str) -> bool:
    """把文档所有权转移给指定用户，转移后用户可授予任意权限。"""
    r = requests.post(
        f"{BASE_URL}/drive/v1/permissions/{doc_token}/members/transfer_owner",
        headers=_tenant_headers(),
        params={"type": "docx"},
        json={
            "member_type": "openid",
            "member_id": open_id,
        },
        timeout=15,
    )
    d = r.json()
    if d.get("code") != 0:
        print(f"[feishu] 转移文档所有权失败: {d}")
        return False
    print(f"[feishu] 文档所有权已转移给 {open_id}")
    return True


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


def send_summary_and_doc(summary: str, doc_url: str, chat_id: str = ""):
    message = f"📋 会议纪要已生成\n\n{summary}\n\n📄 完整版文档: {doc_url}"
    send_message_to_chat(chat_id or FEISHU_CHAT_ID, message)


# ====== 智能纪要图片追加相关 ======


def get_docx_blocks(doc_token: str) -> list[dict]:
    """拉取 docx 全部 block，处理分页。"""
    items: list[dict] = []
    page_token = ""
    while True:
        params = {"page_size": 500}
        if page_token:
            params["page_token"] = page_token
        r = requests.get(
            f"{BASE_URL}/docx/v1/documents/{doc_token}/blocks",
            headers=_tenant_headers(),
            params=params,
            timeout=15,
        )
        d = r.json()
        if d.get("code") != 0:
            print(f"[feishu] 拉 docx blocks 失败: {d}")
            return items
        data = d.get("data", {})
        items.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page_token = data.get("page_token", "")
        if not page_token:
            break
    return items


def download_image(image_token: str) -> bytes:
    """从 drive 下载文档媒体（图片）。"""
    r = requests.get(
        f"{BASE_URL}/drive/v1/medias/{image_token}/download",
        headers=_tenant_headers(),
        timeout=60,
    )
    if r.status_code != 200:
        # 可能是 json 报错
        try:
            print(f"[feishu] 下载图片 {image_token} 失败: {r.json()}")
        except Exception:
            print(f"[feishu] 下载图片 {image_token} 失败 status={r.status_code}")
        return b""
    return r.content


def append_image_to_docx(doc_token: str, image_bytes: bytes, file_name: str = "image.jpg") -> str:
    """
    在 docx 末尾追加一张图。两步：
      1. 创建 empty image block
      2. 把图上传到 docx_image，parent_node 用刚拿到的 block_id
    返回新 block_id；失败返回 ''。
    """
    # 1. 在 root 末尾创建 empty image block
    r1 = requests.post(
        f"{BASE_URL}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
        headers=_tenant_headers(),
        json={"children": [{"block_type": 27, "image": {"token": ""}}], "index": -1},
        timeout=30,
    )
    d1 = r1.json()
    if d1.get("code") != 0:
        print(f"[feishu] 创建空 image block 失败: {d1}")
        return ""
    new_block_id = d1["data"]["children"][0]["block_id"]

    # 2. 上传图片到这个 block（multipart 上传不能带 application/json header）
    upload_headers = {"Authorization": f"Bearer {get_tenant_access_token()}"}
    files = {"file": (file_name, image_bytes, "image/jpeg")}
    data = {
        "file_name": file_name,
        "parent_type": "docx_image",
        "parent_node": new_block_id,
        "size": str(len(image_bytes)),
    }
    r2 = requests.post(
        f"{BASE_URL}/drive/v1/medias/upload_all",
        headers=upload_headers,
        files=files,
        data=data,
        timeout=120,
    )
    d2 = r2.json()
    if d2.get("code") != 0:
        print(f"[feishu] 上传图片到 docx 失败: {d2}")
        return ""
    return new_block_id


def append_heading_to_docx(doc_token: str, text: str, level: int = 2) -> str:
    """在 docx 末尾追加一个标题。level 1-9 对应 heading1-heading9。
    block_type 映射：heading1=3, heading2=4, heading3=5 ..."""
    block_type = 2 + level
    heading_key = f"heading{level}"
    r = requests.post(
        f"{BASE_URL}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
        headers=_tenant_headers(),
        json={
            "children": [{
                "block_type": block_type,
                heading_key: {"elements": [{"text_run": {"content": text}}]},
            }],
            "index": -1,
        },
        timeout=30,
    )
    d = r.json()
    if d.get("code") != 0:
        print(f"[feishu] 追加标题失败: {d}")
        return ""
    return d["data"]["children"][0]["block_id"]


def append_text_to_docx(doc_token: str, text: str) -> str:
    """在 docx 末尾追加一段普通文字。"""
    r = requests.post(
        f"{BASE_URL}/docx/v1/documents/{doc_token}/blocks/{doc_token}/children",
        headers=_tenant_headers(),
        json={
            "children": [{
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": text}}]},
            }],
            "index": -1,
        },
        timeout=30,
    )
    d = r.json()
    if d.get("code") != 0:
        print(f"[feishu] 追加文字失败: {d}")
        return ""
    return d["data"]["children"][0]["block_id"]


# ====== 智能纪要主动拉取 ======


def get_minute_artifacts(minute_token: str) -> dict | None:
    """获取妙记 AI 产物（智能纪要结构化内容）。

    返回包含 keywords, summary, minute_chapters, minute_todos, transcript 的字典，
    如果尚未生成或请求失败则返回 None。
    """
    resp = requests.get(
        f"{BASE_URL}/minutes/v1/minutes/{minute_token}/artifacts",
        headers=_user_headers(),
    )
    if resp.status_code != 200:
        print(f"[feishu] artifacts API status={resp.status_code}")
        return None
    data = resp.json()
    if data.get("code") != 0:
        print(f"[feishu] 获取 AI 产物失败: code={data.get('code')}, msg={data.get('msg', '')[:100]}")
        return None
    artifacts = data.get("data", {})
    if not artifacts.get("summary") and not artifacts.get("minute_chapters"):
        # AI 产物尚未生成完毕
        return None
    return artifacts


def _extract_text_from_elements(elements: list) -> str:
    """从 block elements 列表中拼接纯文本。"""
    parts = []
    for el in elements:
        text_run = el.get("text_run", {})
        content = text_run.get("content", "")
        if content:
            parts.append(content)
    return "".join(parts)


def extract_smart_notes_content(doc_token: str) -> dict:
    """从智能纪要 docx 中提取文本内容和图片列表。"""
    blocks = get_docx_blocks(doc_token)
    if not blocks:
        return {"texts": [], "images": []}

    texts = []
    images = []

    for block in blocks:
        block_type = block.get("block_type")

        if block_type == 2:
            content = _extract_text_from_elements(block.get("text", {}).get("elements", []))
            if content.strip():
                texts.append({"type": "text", "content": content, "level": 0})

        elif 3 <= block_type <= 9:
            level = block_type - 2
            heading_key = f"heading{level}"
            content = _extract_text_from_elements(block.get(heading_key, {}).get("elements", []))
            if content.strip():
                texts.append({"type": "heading", "content": content, "level": level})

        elif block_type == 12:
            content = _extract_text_from_elements(block.get("bullet", {}).get("elements", []))
            if content.strip():
                texts.append({"type": "text", "content": f"- {content}", "level": 0})

        elif block_type == 13:
            content = _extract_text_from_elements(block.get("ordered", {}).get("elements", []))
            if content.strip():
                texts.append({"type": "text", "content": content, "level": 0})

        elif block_type == 27:
            image_token = block.get("image", {}).get("token", "")
            caption = block.get("image", {}).get("caption", {}).get("content", "")
            if image_token:
                images.append({"token": image_token, "caption": caption})

    return {"texts": texts, "images": images}


def poll_minute_artifacts(minute_token: str, max_attempts: int = 8, interval: int = 30) -> dict | None:
    """轮询等待妙记 AI 产物生成完毕，返回 artifacts 字典。"""
    for attempt in range(max_attempts):
        artifacts = get_minute_artifacts(minute_token)
        if artifacts:
            chapters = artifacts.get("minute_chapters", [])
            print(f"[feishu] AI 产物已就绪 (attempt {attempt+1}): {len(chapters)} 章节")
            return artifacts

        if attempt < max_attempts - 1:
            print(f"[feishu] AI 产物未就绪 (attempt {attempt+1}/{max_attempts})，{interval}s 后重试")
            time.sleep(interval)

    print(f"[feishu] AI 产物在 {max_attempts * interval}s 内未就绪，放弃")
    return None


def append_smart_notes_to_doc(our_doc_token: str, artifacts: dict) -> dict:
    """把 AI 产物的结构化内容追加到我们的纪要文档末尾。"""
    summary = artifacts.get("summary", "")
    chapters = artifacts.get("minute_chapters", [])
    todos = artifacts.get("minute_todos", [])

    if not summary and not chapters:
        print("[feishu] AI 产物内容为空，跳过追加")
        return {"texts_appended": 0, "images_appended": 0}

    append_heading_to_docx(our_doc_token, "附录：飞书智能纪要", level=2)
    texts_count = 0

    # 追加总结
    if summary:
        append_heading_to_docx(our_doc_token, "会议总结", level=3)
        # summary 可能是 markdown 格式，按段落追加
        for para in summary.split("\n"):
            para = para.strip()
            if para:
                append_text_to_docx(our_doc_token, para)
                texts_count += 1
                time.sleep(0.15)

    # 追加章节摘要
    if chapters:
        append_heading_to_docx(our_doc_token, "章节摘要", level=3)
        for ch in chapters:
            title = ch.get("title", "")
            content = ch.get("summary_content", "")
            if title:
                append_heading_to_docx(our_doc_token, title, level=4)
                texts_count += 1
            if content:
                append_text_to_docx(our_doc_token, content)
                texts_count += 1
            time.sleep(0.15)

    # 追加待办事项
    if todos:
        append_heading_to_docx(our_doc_token, "待办事项", level=3)
        for todo in todos:
            content = todo.get("content", "")
            if content:
                append_text_to_docx(our_doc_token, f"☐ {content}")
                texts_count += 1
                time.sleep(0.15)

    return {"texts_appended": texts_count, "images_appended": 0}


# ====== 会议参与者查询 ======


CALENDAR_ID = "feishu.cn_8V20yYtOHienZ7laNm8d2b@group.calendar.feishu.cn"


def is_user_in_meeting(calendar_event_id: str) -> bool:
    """通过日历 API 判断当前授权用户是否参与了该会议。"""
    if not calendar_event_id:
        return False

    try:
        resp = requests.get(
            f"{BASE_URL}/calendar/v4/calendars/{CALENDAR_ID}/events/{calendar_event_id}",
            headers=_user_headers(),
            timeout=10,
        )
        data = resp.json()
        if data.get("code") == 0:
            summary = data.get("data", {}).get("event", {}).get("summary", "")
            print(f"[feishu] 日历事件匹配成功: {summary}")
            return True
        else:
            return False
    except Exception as e:
        print(f"[feishu] 日历查询异常: {e}")
        return False
