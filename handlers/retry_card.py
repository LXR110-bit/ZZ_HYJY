"""卡片回调只鉴权并排队；模型处理留在线程中。"""
import re
import threading
import time
from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
from config import SELF_SERVE_ALLOWED_OPEN_IDS, DRY_RUN
from handlers.minute_request import run_minute_job, _save_last_request
from services.log import log

_lock = threading.Lock()
_seen = {}


def _toast(text: str, kind: str = "info"):
    return P2CardActionTriggerResponse({"toast": {"type": kind, "content": text}})


def _run(ctx, token, topic):
    _save_last_request(ctx["chat_id"], token, topic)
    run_minute_job(ctx, token, topic, is_retry=True)


def on_card_action(data):
    event = data.event
    sender = getattr(getattr(event, "operator", None), "open_id", "")
    log("[card.action.trigger] 收到点击")
    if sender not in SELF_SERVE_ALLOWED_OPEN_IDS:
        return _toast("仅授权用户可以重试。", "error")
    if DRY_RUN:
        return _toast("DRY_RUN：未执行重试。")
    value = getattr(getattr(event, "action", None), "value", None)
    context = getattr(event, "context", None)
    message_id = getattr(context, "open_message_id", "")
    chat_id = getattr(context, "open_chat_id", "")
    if not isinstance(value, dict):
        return _toast("按钮参数无效。", "error")
    token = value.get("minute_token", "")
    topic = value.get("topic", "")
    if (value.get("action") != "retry_minute" or not isinstance(token, str)
            or not re.fullmatch(r"[A-Za-z0-9]{1,128}", token)
            or not isinstance(topic, str) or not message_id or not chat_id):
        return _toast("按钮参数无效，请重新发送妙记链接。", "error")
    event_id = getattr(event, "token", "")
    key = event_id or (sender, message_id, token)
    now = time.monotonic()
    with _lock:
        for old in [k for k, stamp in _seen.items() if now - stamp > 30]:
            del _seen[old]
        if key in _seen:
            return _toast("已收到重试，请稍候。")
        _seen[key] = now
    ctx = {"message_id": message_id, "chat_id": chat_id, "sender_id": sender}
    threading.Thread(target=_run, args=(ctx, token, topic[:60]), daemon=True).start()
    return _toast("已开始重试，结果会回复到当前会话。", "success")
