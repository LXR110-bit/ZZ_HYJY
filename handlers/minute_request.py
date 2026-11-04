"""
飞书内自助生成纪要：用户私聊机器人、或在群里 @机器人，发一条带妙记链接的消息，
机器人拉逐字稿 → 生成纪要 → 建文档 → 回复到发消息的那个会话。

存在的理由：会议结束自动生成经常因为妙记没分享、主持人不在白名单、逐字稿还没转好
而漏掉，之前每次都要回到 Claude 会话里手动补拉。失败时按原因给出可操作的提示，
用户处理完回复「重试」即可再次触发。

只处理"发给机器人的"消息（私聊，或群里 @ 了本机器人）；其余群消息仍交给
minute_card 的智能纪要截图追加逻辑。
"""
import json
import re
import threading
import time
from pathlib import Path

from config import SELF_SERVE_ALLOWED_OPEN_IDS, DRY_RUN
from services.retry_cards import failure_card
from services import meeting_ledger
from services.log import log
from services.feishu import (
    fetch_minute_content,
    create_document,
    reply_message,
    get_bot_open_id,
    append_smart_notes_to_doc,
    USER_TOKEN_ERROR_CODES,
)
from services.claude import generate_meeting_minutes, meeting_kind, MEETING_KIND_LABELS

MINUTE_URL_RE = re.compile(r"https?://[\w\-.]*?(?:feishu\.cn|larksuite\.com)/minutes/([A-Za-z0-9]+)")
OTHER_DOC_URL_RE = re.compile(
    r"https?://[\w\-.]*?(?:feishu\.cn|larksuite\.com)/(?:docx|docs|wiki|sheets|base|file)/[A-Za-z0-9]+"
)
URL_RE = re.compile(r"https?://\S+")
MENTION_KEY_RE = re.compile(r"@_user_\d+")
RETRY_WORDS = ("重试", "再试", "重新生成", "retry")
BOT_NAME = "会议助手"

# 每个会话最近一次请求，用于「重试」。落盘是为了重启后仍能重试。
STATE_FILE = Path(__file__).parent.parent / ".minute_requests.json"
STATE_TTL = 7 * 24 * 3600

_state_lock = threading.Lock()
_seen_lock = threading.Lock()
_seen_message_ids: dict[str, float] = {}
_inflight_lock = threading.Lock()
_inflight: set[str] = set()

HELP_TEXT = (
    "把妙记链接发给我，我来生成会议纪要：\n"
    "· 私聊：直接发妙记链接\n"
    "· 群里：@会议助手 + 妙记链接\n"
    "· 想用品类周会 / 万象周会格式：在链接前写上会议名，如「品类周会W45 https://xxx.feishu.cn/minutes/obcn…」\n"
    "· 失败了按提示处理，然后回复「重试」"
)


# ---------- 消息解析 ----------


def _extract_text(msg_type: str, content_str: str) -> str:
    """把 text / post 消息的 content JSON 还原成纯文本（链接保留 href）。"""
    try:
        content = json.loads(content_str or "{}")
    except ValueError:
        return content_str or ""
    if msg_type == "text":
        return content.get("text", "") or ""
    if msg_type == "post":
        # post 可能是 {"title","content"} 或按语言包一层 {"zh_cn": {...}}
        body = content if "content" in content else next(iter(content.values()), {}) if content else {}
        pieces = [body.get("title", "") or ""]
        for line in body.get("content", []) or []:
            for el in line or []:
                pieces.append(el.get("href") or el.get("text") or "")
        return " ".join(p for p in pieces if p)
    return content_str or ""


def parse_event(data) -> dict | None:
    """把 SDK 的 im.message.receive_v1 事件压成一个普通 dict，便于测试。"""
    try:
        msg = data.event.message
        sender = data.event.sender
        mentions = []
        for m in getattr(msg, "mentions", None) or []:
            mid = getattr(m, "id", None)
            mentions.append({
                "key": getattr(m, "key", "") or "",
                "name": getattr(m, "name", "") or "",
                "open_id": (getattr(mid, "open_id", "") or "") if mid else "",
            })
        return {
            "message_id": msg.message_id,
            "chat_id": msg.chat_id,
            "chat_type": msg.chat_type or "",
            "message_type": msg.message_type or "",
            "content": msg.content or "{}",
            "mentions": mentions,
            "sender_id": (sender.sender_id.open_id or "") if sender and sender.sender_id else "",
            "sender_type": getattr(sender, "sender_type", "") or "",
        }
    except AttributeError as e:
        log(f"[minute_request] 事件解析失败: {e}")
        return None


def is_directed_to_bot(ctx: dict) -> bool:
    """私聊，或群消息里 @ 了本机器人。"""
    if ctx["chat_type"] == "p2p":
        return True
    bot_id = get_bot_open_id()
    for m in ctx["mentions"]:
        if bot_id and m["open_id"] == bot_id:
            return True
        if not bot_id and m["name"] == BOT_NAME:
            return True
    return False


def _topic_hint(text: str) -> str:
    """妙记链接所在那一行、链接前面的文字，当作用户指定的会议名。

    只取这一小段：用户常把一大段说明连同链接一起粘过来，整段当会议名会污染文档标题。
    """
    m = MINUTE_URL_RE.search(text)
    if m:
        line_start = text.rfind("\n", 0, m.start()) + 1
        text = text[line_start:m.start()]
    hint = MENTION_KEY_RE.sub(" ", URL_RE.sub(" ", text))
    hint = re.sub(r"\s+", " ", hint).strip(" ：:，,。.-—①②③④⑤⑥⑦⑧⑨")
    if any(hint == w for w in RETRY_WORDS):
        return ""
    return hint[:60]


def _is_retry(text: str) -> bool:
    plain = MENTION_KEY_RE.sub("", text).strip(" ：:，,。.!！")
    return any(plain.startswith(w) for w in RETRY_WORDS)


# ---------- 状态（重试 / 去重 / 并发） ----------


def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_last_request(chat_id: str, minute_token: str, hint: str) -> None:
    with _state_lock:
        state = _load_state()
        now = time.time()
        state = {k: v for k, v in state.items() if now - v.get("ts", 0) < STATE_TTL}
        state[chat_id] = {"minute_token": minute_token, "hint": hint, "ts": now}
        try:
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as e:
            log(f"[minute_request] 保存重试状态失败: {e}")


def _get_last_request(chat_id: str) -> dict | None:
    with _state_lock:
        item = _load_state().get(chat_id)
    if item and time.time() - item.get("ts", 0) < STATE_TTL:
        return item
    return None


def _first_time_seen(message_id: str) -> bool:
    """飞书可能重推同一条消息事件，按 message_id 去重（保留 1 小时）。"""
    now = time.time()
    with _seen_lock:
        for k in [k for k, ts in _seen_message_ids.items() if now - ts > 3600]:
            del _seen_message_ids[k]
        if message_id in _seen_message_ids:
            return False
        _seen_message_ids[message_id] = now
        return True


# ---------- 入口 ----------


def try_handle(data) -> bool:
    """处理发给机器人的消息。返回 True 表示已处理（调用方不要再走其他逻辑）。"""
    ctx = parse_event(data)
    if not ctx or ctx["sender_type"] == "app":
        return False
    if not is_directed_to_bot(ctx):
        return False
    if not _first_time_seen(ctx["message_id"]):
        log(f"[minute_request] 重复事件，跳过 message_id={ctx['message_id']}")
        return True
    threading.Thread(target=handle_directed, args=(ctx,), daemon=True).start()
    return True


def handle_directed(ctx: dict) -> None:
    text = _extract_text(ctx["message_type"], ctx["content"])
    # 卡片 / 分享等其他类型消息的链接藏在 content JSON 里，原文也扫一遍
    tokens = MINUTE_URL_RE.findall(text) or MINUTE_URL_RE.findall(ctx["content"])
    retry = not tokens and _is_retry(text)
    log(
        f"[minute_request] chat={ctx['chat_id']} type={ctx['chat_type']} sender={ctx['sender_id']} "
        f"message_id={ctx['message_id']} minute_tokens={tokens} retry={retry}"
    )

    if ctx["sender_id"] not in SELF_SERVE_ALLOWED_OPEN_IDS:
        if tokens or retry:
            _reply(ctx, "抱歉，用妙记链接生成纪要目前只对授权用户开放。")
        log(f"[minute_request] sender 不在允许名单，忽略 sender={ctx['sender_id']}")
        return

    if MENTION_KEY_RE.sub("", text).strip(" ：:，,。.!！") == "漏了哪些":
        from services.retry_cards import missing_card
        rows = meeting_ledger.missing()
        card, fallback = missing_card(rows)
        _reply(ctx, fallback, card=card)
        return

    if tokens:
        hint = _topic_hint(text)
        _save_last_request(ctx["chat_id"], tokens[0], hint)
        run_minute_job(ctx, tokens[0], hint)
        return

    if retry:
        last = _get_last_request(ctx["chat_id"])
        if not last:
            _reply(ctx, "没有找到可以重试的请求（7 天内），请重新发一次妙记链接。")
            return
        run_minute_job(ctx, last["minute_token"], last.get("hint", ""), is_retry=True)
        return

    if OTHER_DOC_URL_RE.search(text) or OTHER_DOC_URL_RE.search(ctx["content"]):
        _reply(
            ctx,
            "这是飞书文档链接，不是妙记链接。请发妙记链接（形如 https://xxx.feishu.cn/minutes/obcn…），"
            "可以在会议结束后的妙记通知、或飞书「妙记」首页里复制。",
        )
        return

    _reply(ctx, HELP_TEXT)


# ---------- 生成 ----------


def _reply(ctx: dict, text: str, minute_token: str = "", topic: str = "", card: dict | None = None) -> str:
    if DRY_RUN:
        log("[minute_request] DRY_RUN 抑制发送")
        return ""
    card = card or (failure_card(text, minute_token, topic) if minute_token else None)
    data = reply_message(ctx["message_id"], text, card=card) if card else reply_message(ctx["message_id"], text)
    reply_id = ((data or {}).get("data") or {}).get("message_id", "")
    log(f"[minute_request] 已回复 reply_message_id={reply_id or 'FAILED'} code={(data or {}).get('code')} 内容前 40 字={text[:40]!r}")
    return reply_id


def _failure_text(status: str, detail: dict, url: str) -> str:
    code = detail.get("code")
    if status == "forbidden":
        return (
            f"⚠️ 拉取失败：没有这份妙记的访问权限（飞书返回 code={code or 2091005} permission deny）。\n"
            f"处理办法：请妙记所有者打开妙记 → 右上角「分享」→ 把「李肖然」加为可阅读"
            f"（或开启「组织内获得链接的人可阅读」）。开好后在这里回复「重试」。\n{url}"
        )
    if status == "not_found":
        return f"⚠️ 找不到这份妙记（code={code}），请检查链接是否完整、妙记是否已被删除。\n{url}"
    if status == "empty":
        return (
            "⏳ 能打开这份妙记，但逐字稿还是空的——通常是会议刚结束、妙记还在转录"
            "（长会议可能要 10–30 分钟）。稍后在这里回复「重试」即可。\n"
            f"如果会议没开录制 / 没人说话，妙记就不会有逐字稿。\n{url}"
        )
    if code in USER_TOKEN_ERROR_CODES:
        return (
            f"⚠️ 拉取失败：机器人使用的授权账号 token 失效或缺权限（code={code}）。"
            f"需要重新授权（服务器上运行 authorize.py），之后回复「重试」。"
        )
    if detail.get("stage") == "artifacts":
        # 妙记本身打得开，只是内容接口报错：最常见是还在转录 / 生成 AI 产物
        return (
            f"⏳ 能打开这份妙记，但内容暂时拿不到（code={code}，{detail.get('msg', '')}），"
            f"多半是妙记还在转录。稍后在这里回复「重试」即可。\n{url}"
        )
    return (
        f"⚠️ 拉取妙记失败（code={code}，{detail.get('msg', '')}）。可以稍后回复「重试」；"
        f"多次失败请看服务器日志。\n{url}"
    )


def run_minute_job(ctx: dict, minute_token: str, hint: str, is_retry: bool = False) -> None:
    if DRY_RUN:
        log("[minute_request] DRY_RUN 跳过生成")
        return
    url = f"https://meetings.feishu.cn/minutes/{minute_token}"
    with _inflight_lock:
        if minute_token in _inflight:
            _reply(ctx, "这份妙记正在生成中，请稍等，完成后会回复在这里。")
            return
        _inflight.add(minute_token)
    try:
        _run(ctx, minute_token, hint, is_retry, url)
    except Exception as e:  # 兜底：任何异常都要让用户知道，而不是石沉大海
        log(f"[minute_request] 处理异常 minute={minute_token}: {e!r}")
        _reply(ctx, f"⚠️ 处理出错：{e}。可以回复「重试」再来一次。", minute_token, hint)
    finally:
        with _inflight_lock:
            _inflight.discard(minute_token)


def _run(ctx: dict, minute_token: str, hint: str, is_retry: bool, url: str) -> None:
    _reply(ctx, f"{'🔁 重试中' if is_retry else '📝 收到'}，正在拉取妙记并生成纪要（一般 1–3 分钟）…")

    status, transcript, detail = fetch_minute_content(minute_token)
    log(
        f"[minute_request] 拉取结果 minute={minute_token} status={status} code={detail.get('code')} "
        f"title={detail.get('title', '')!r} transcript_code={detail.get('transcript_code')} "
        f"artifacts_code={detail.get('artifacts_code')} transcript_len={detail.get('transcript_len')}"
    )
    if status != "ok":
        _reply(ctx, _failure_text(status, detail, url), minute_token, hint or detail.get("title", ""))
        return

    topic = hint or detail.get("title") or "会议"
    kind = meeting_kind(topic)
    format_note = f"格式：{MEETING_KIND_LABELS[kind]}"
    if not hint:
        format_note += f"（会议名取自妙记标题「{topic}」"
        if kind == "generic":
            format_note += "；需要品类周会 / 万象周会格式的话，发链接时在前面写上会议名，如「品类周会W45 <链接>」"
        format_note += "）"

    result = generate_meeting_minutes(transcript, meeting_topic=topic)
    summary = result["summary"]
    full_minutes = result["full"]
    log(f"[minute_request] 纪要生成完成 minute={minute_token} summary={len(summary)} full={len(full_minutes)}")

    doc_title = f"会议纪要 - {topic}"
    doc_url = create_document(doc_title, full_minutes)
    if not doc_url:
        _reply(ctx, f"📋 {doc_title}\n{format_note}\n\n{summary}\n\n⚠️ 飞书文档创建失败，以上只是摘要。可以回复「重试」。", minute_token, topic)
        return
    doc_token = doc_url.rstrip("/").rsplit("/", 1)[-1]
    log(f"[minute_request] 文档已创建 doc_token={doc_token} url={doc_url}")

    artifacts = detail.get("artifacts") or {}
    if artifacts:
        try:
            r = append_smart_notes_to_doc(doc_token, artifacts)
            log(f"[minute_request] 已追加飞书智能纪要 {r['texts_appended']} 段 doc_token={doc_token}")
        except Exception as e:
            log(f"[minute_request] 追加飞书智能纪要失败（不影响主流程）: {e!r}")

    meeting_ledger.generated(minute_token, doc_url)
    _reply(ctx, f"📋 会议纪要已生成：{topic}\n{format_note}\n\n{summary}\n\n📄 完整版文档：{doc_url}")
