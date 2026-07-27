import time
import threading
from services.feishu import (
    get_meeting_minutes_transcript,
    get_minute_token_by_meeting,
    create_document,
    send_summary_and_doc,
    send_message_to_chat,
    poll_minute_artifacts,
    append_smart_notes_to_doc,
)
from services.claude import generate_meeting_minutes
from services.doc_mapping import record as record_doc_mapping, mark_smart_notes_done
from config import FEISHU_CHAT_ID


def handle_meeting_ended(meeting_id: str, topic: str = "未命名会议"):
    """处理会议结束事件"""
    print(f"[event] 会议结束: {topic} (id={meeting_id})")

    # 轮询等待妙记逐字稿就绪：长会议（2 小时）转录慢，固定等 60 秒必然拉空。
    # 首次等 90 秒，之后每 3 分钟拉一次，最多约 60 分钟；拉到非空立即继续。
    print("[event] 开始轮询等待妙记逐字稿就绪...")
    transcript = ""
    for attempt in range(21):
        time.sleep(90 if attempt == 0 else 180)
        transcript = get_meeting_minutes_transcript(meeting_id)
        if transcript:
            print(f"[event] 逐字稿就绪（第 {attempt + 1} 次轮询），长度: {len(transcript)} 字符")
            break
        print(f"[event] 逐字稿未就绪（第 {attempt + 1}/21 次），继续等待...")
    if not transcript:
        print("[event] 轮询超时逐字稿仍为空（可能未开录制/妙记未生成），跳过处理")
        return

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
        doc_token = doc_url.rstrip("/").rsplit("/", 1)[-1]
        record_doc_mapping(chat_id=FEISHU_CHAT_ID, topic=topic, doc_token=doc_token)
        send_summary_and_doc(summary, doc_url)
        print(f"[event] 已发送群消息，文档: {doc_url}")

        # 异步拉取智能纪要并追加到文档
        threading.Thread(
            target=_append_smart_notes,
            kwargs={
                "meeting_id": meeting_id,
                "our_doc_token": doc_token,
                "topic": topic,
            },
            daemon=True,
        ).start()
    else:
        send_message_to_chat(FEISHU_CHAT_ID, f"📋 会议纪要 - {topic}\n\n{summary}")
        print("[event] 文档创建失败，仅发送了摘要")


def _append_smart_notes(meeting_id: str, our_doc_token: str, topic: str):
    """异步任务：等待智能纪要生成后追加到我们的文档。"""
    print(f"[smart_notes] 开始等待智能纪要: meeting={meeting_id}")

    minute_token = get_minute_token_by_meeting(meeting_id)
    if not minute_token:
        print("[smart_notes] 无 minute_token，跳过智能纪要追加")
        return

    artifacts = poll_minute_artifacts(minute_token, max_attempts=8, interval=30)
    if not artifacts:
        print("[smart_notes] AI 产物超时未生成，跳过")
        return

    result = append_smart_notes_to_doc(our_doc_token, artifacts)
    print(f"[smart_notes] 追加完成: {result['texts_appended']} 段文字")

    mark_smart_notes_done(our_doc_token)

    if result["texts_appended"] > 0:
        send_message_to_chat(
            FEISHU_CHAT_ID,
            f"📎 已为「{topic}」纪要追加飞书智能纪要内容（{result['texts_appended']} 段文字）",
        )
