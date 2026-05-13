import threading
import lark_oapi as lark
from lark_oapi.api.vc.v1 import *
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, MEETING_OWNER_WHITELIST
from handlers.meeting_ended import handle_meeting_ended


def _extract_owner_id(meeting) -> str:
    """从 meeting 对象里捞主持人的 open_id。
    飞书事件结构：meeting.owner.id 是 UserId 对象，含 open_id / union_id / user_id。
    """
    owner = getattr(meeting, "owner", None)
    if not owner:
        return ""
    user_id_obj = getattr(owner, "id", None)
    if not user_id_obj:
        return ""
    return getattr(user_id_obj, "open_id", "") or ""


def on_meeting_ended(data) -> None:
    """长连接收到会议结束事件的回调"""
    meeting = data.event.meeting
    owner_id = _extract_owner_id(meeting)
    topic = meeting.topic or "未命名会议"
    print(f"[main] 收到会议结束事件: topic={topic} owner={owner_id}")

    # 白名单过滤（为空则不过滤，方便调试看 owner_id）
    if MEETING_OWNER_WHITELIST and owner_id not in MEETING_OWNER_WHITELIST:
        print(f"[main] 主持人 {owner_id} 不在白名单，跳过")
        return

    # 放到独立线程处理，避免 sleep(60) 阻塞 SDK 心跳
    threading.Thread(
        target=handle_meeting_ended,
        kwargs={
            "meeting_id": meeting.id,
            "topic": topic,
        },
        daemon=True,
    ).start()


def main():
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_vc_meeting_all_meeting_ended_v1(on_meeting_ended)
        .build()
    )

    cli = (
        lark.ws.Client(
            FEISHU_APP_ID,
            FEISHU_APP_SECRET,
            event_handler=event_handler,
            log_level=lark.LogLevel.DEBUG,
        )
    )

    whitelist_info = (
        f"白名单 {len(MEETING_OWNER_WHITELIST)} 人"
        if MEETING_OWNER_WHITELIST
        else "未配置白名单（所有会议都会处理）"
    )
    print(f"[main] 启动飞书长连接，等待会议结束事件... {whitelist_info}")
    cli.start()


if __name__ == "__main__":
    main()
