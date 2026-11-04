import time
import threading
from services.feishu import (
    get_meeting_minutes_transcript,
    get_minute_token_by_meeting,
    acquire_minute_token,
    create_document,
    send_summary_and_doc,
    send_message_to_chat,
    poll_minute_artifacts,
    append_smart_notes_to_doc,
    probe_minute_readable,
    notify_skip,
    SKIP_NO_RECORDING,
    SKIP_MINUTE_FORBIDDEN,
    SKIP_TRANSCRIPT_TIMEOUT,
)
from services.claude import generate_meeting_minutes
from services.doc_mapping import record as record_doc_mapping, mark_smart_notes_done
from services.log import log
from config import FEISHU_CHAT_ID, DRY_RUN
from services import meeting_ledger


def handle_meeting_ended(meeting_id: str, topic: str = "未命名会议"):
    entry = {"meeting_id": meeting_id, "topic": topic, "meeting_time": time.time(),
             "status": "processing", "minute_token": "", "doc_url": "", "source": "自动生成"}
    if not DRY_RUN:
        meeting_ledger.record(entry)
    try:
        _handle_meeting_ended(meeting_id, topic, entry)
    except Exception as exc:
        entry["status"] = "error"
        log(f"[event] 自动生成出错 meeting={meeting_id} error={type(exc).__name__}")
        if not DRY_RUN:
            notify_skip(topic, "出错", {"minute_token": entry["minute_token"]})
    finally:
        if not DRY_RUN:
            meeting_ledger.record(entry)


def _handle_meeting_ended(meeting_id: str, topic: str, entry: dict):
    """处理会议结束事件"""
    log(f"[event] 会议结束: {topic} (id={meeting_id})")

    # 先确认有没有妙记。会议结束事件在结束后几秒就到达，此时录制多半还在转码
    # （飞书返回 124002 record processing），所以必须带重试，不能一次取不到就判死刑。
    minute_token, reason = acquire_minute_token(meeting_id)
    entry["minute_token"] = minute_token
    if not minute_token:
        entry["status"] = "timeout" if reason == "processing" else "no_recording" if reason == "no_recording_url" else "error"
        log(f"[event] 未取到 minute_token，放弃: {topic} reason={reason}")
        notify_skip(topic, SKIP_NO_RECORDING, {"reason": reason})
        return

    # 再确认读不读得到。2091005 是"这份妙记不归你"，等一万年也不会变，
    # 必须和"还没生成好"分开处理。
    state, detail = probe_minute_readable(minute_token)
    log(f"[event] 妙记可读性探测: state={state} minute={minute_token} detail={detail}")
    if state == "forbidden":
        entry["status"] = "forbidden"
        notify_skip(topic, SKIP_MINUTE_FORBIDDEN, {
            "minute_token": minute_token,
            "owner_id": detail.get("owner_id", ""),
        })
        return

    if DRY_RUN:
        log(f"[event] DRY_RUN：判定与探测完成，跳过轮询与生成 topic={topic} state={state}")
        return

    # 轮询等待逐字稿就绪。走到这里说明权限没问题，只是内容可能还在生成。
    # 长会议（2 小时）转录慢：首次等 90 秒，之后每 3 分钟一次，最多约 60 分钟。
    log("[event] 开始轮询等待妙记逐字稿就绪...")
    transcript = ""
    for attempt in range(21):
        time.sleep(90 if attempt == 0 else 180)
        transcript = get_meeting_minutes_transcript(meeting_id)
        if transcript:
            log(f"[event] 逐字稿就绪（第 {attempt + 1} 次轮询），长度: {len(transcript)} 字符")
            break
        log(f"[event] 逐字稿未就绪（第 {attempt + 1}/21 次），继续等待...")
    if not transcript:
        log("[event] 轮询超时逐字稿仍为空，跳过处理")
        entry["status"] = "timeout"
        notify_skip(topic, SKIP_TRANSCRIPT_TIMEOUT, {"minute_token": minute_token})
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
        entry.update(status="generated", doc_url=doc_url)
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
        entry["status"] = "error"
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
