import threading
import lark_oapi as lark
from lark_oapi.api.vc.v1 import *
from config import FEISHU_APP_ID, FEISHU_APP_SECRET, MEETING_OWNER_WHITELIST
from handlers.meeting_ended import handle_meeting_ended
from services.feishu import is_user_in_meeting
from handlers.minute_card import handle_im_message


def _extract_owner_id(meeting) -> str:
    """从 meeting 对象里捞主持人的 open_id。
    优先取 owner.id.open_id，没有则 fallback 到 host_user.id.open_id。
    """
    for field in ("owner", "host_user"):
        obj = getattr(meeting, field, None)
        if not obj:
            continue
        user_id_obj = getattr(obj, "id", None)
        if not user_id_obj:
            continue
        open_id = getattr(user_id_obj, "open_id", "") or ""
        if open_id:
            return open_id
    return ""


def on_meeting_ended(data) -> None:
    """长连接收到会议结束事件的回调"""
    meeting = data.event.meeting
    owner_id = _extract_owner_id(meeting)
    topic = meeting.topic or "未命名会议"
    print(f"[main] 收到会议结束事件: topic={topic} owner={owner_id}")

    # 白名单过滤（为空则不过滤，方便调试看 owner_id）
    if MEETING_OWNER_WHITELIST and owner_id not in MEETING_OWNER_WHITELIST:
        # owner 不在白名单，通过日历判断授权用户是否参会
        calendar_event_id = getattr(meeting, "calendar_event_id", "") or ""

        if not calendar_event_id:
            print(f"[main] 主持人 {owner_id} 不在白名单，无 calendar_event_id，跳过")
            return

        if not is_user_in_meeting(calendar_event_id):
            print(f"[main] 主持人 {owner_id} 不在白名单，授权用户未参会，跳过")
            return

        print(f"[main] 授权用户为参会人，继续处理: topic={topic}")

    # 放到独立线程处理，避免 sleep(60) 阻塞 SDK 心跳
    threading.Thread(
        target=handle_meeting_ended,
        kwargs={
            "meeting_id": meeting.id,
            "topic": topic,
        },
        daemon=True,
    ).start()


def on_im_message(data) -> None:
    """长连接收到群消息事件的回调"""
    try:
        chat_id = data.event.message.chat_id
        msg_type = data.event.message.message_type
        print(f"[main] 收到群消息: chat={chat_id} type={msg_type}")
    except Exception as e:
        print(f"[main] 群消息事件解析失败: {e}")
        return

    # 放到独立线程，避免阻塞 SDK 心跳
    threading.Thread(
        target=handle_im_message,
        args=(data,),
        daemon=True,
    ).start()


def main():
    event_handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_vc_meeting_all_meeting_ended_v1(on_meeting_ended)
        .register_p2_im_message_receive_v1(on_im_message)
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
