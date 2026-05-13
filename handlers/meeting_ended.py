import time
from services.feishu import (
    get_meeting_minutes_transcript,
    create_document,
    send_summary_and_doc,
)
from services.claude import generate_meeting_minutes


def handle_meeting_ended(meeting_id: str, topic: str = "未命名会议"):
    """处理会议结束事件"""
    print(f"[event] 会议结束: {topic} (id={meeting_id})")

    # 等待妙记生成（通常需要几分钟）
    print("[event] 等待 60 秒让妙记生成...")
    time.sleep(60)

    # 获取逐字稿（内部会先 meeting_id → minute_token → transcript）
    transcript = get_meeting_minutes_transcript(meeting_id)
    if not transcript:
        print("[event] 逐字稿为空，跳过处理")
        return

    print(f"[event] 获取到逐字稿，长度: {len(transcript)} 字符")

    # 调 Claude 生成纪要
    result = generate_meeting_minutes(transcript, meeting_topic=topic)
    summary = result["summary"]
    full_minutes = result["full"]

    print("[event] Claude 生成纪要完成")

    # 创建飞书文档
    doc_title = f"会议纪要 - {topic}"
    doc_url = create_document(doc_title, full_minutes)

    # 发送群消息
    if doc_url:
        send_summary_and_doc(summary, doc_url)
        print(f"[event] 已发送群消息，文档: {doc_url}")
    else:
        from services.feishu import send_message_to_chat
        from config import FEISHU_CHAT_ID
        send_message_to_chat(FEISHU_CHAT_ID, f"📋 会议纪要 - {topic}\n\n{summary}")
        print("[event] 文档创建失败，仅发送了摘要")
