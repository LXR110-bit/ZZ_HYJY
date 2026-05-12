import lark_oapi as lark
from lark_oapi.api.vc.v1 import *
from config import FEISHU_APP_ID, FEISHU_APP_SECRET
from handlers.meeting_ended import handle_meeting_ended


def on_meeting_ended(ctx: lark.EventDispatcherHandler, data: dict):
    """长连接收到会议结束事件的回调"""
    print(f"[main] 收到会议结束事件")
    handle_meeting_ended(data)


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

    print("[main] 启动飞书长连接，等待会议结束事件...")
    cli.start()


if __name__ == "__main__":
    main()
