"""失败通知与漏会清单共用的重试按钮。"""
from datetime import datetime
from zoneinfo import ZoneInfo


def minute_url(token: str) -> str:
    return f"https://meetings.feishu.cn/minutes/{token}"


def retry_button(token: str, topic: str) -> dict:
    """「重试」走卡片回调；「打开妙记」是纯跳转链接，不依赖回调。

    卡片正文是 plain_text，里面的链接点不开（2026-11-04 用户反馈），所以单独给一个跳转按钮，
    方便直接打开妙记去找人开权限。
    """
    return {"tag": "action", "actions": [
        {"tag": "button", "type": "primary",
         "text": {"tag": "plain_text", "content": "重试"},
         "value": {"action": "retry_minute", "minute_token": token, "topic": topic}},
        {"tag": "button", "type": "default",
         "text": {"tag": "plain_text", "content": "打开妙记"},
         "url": minute_url(token)},
    ]}


def failure_card(text: str, minute_token: str, topic: str) -> dict:
    elements = [{"tag": "div", "text": {"tag": "plain_text", "content": text}}]
    if minute_token:
        elements.append(retry_button(minute_token, topic))
    return {"config": {"wide_screen_mode": True}, "elements": elements}


def missing_card(rows: list[dict]) -> tuple[dict, str]:
    labels = {"forbidden": "无权限", "no_recording": "没录制", "timeout": "超时",
              "error": "出错", "unknown": "状态待核实", "processing": "处理中"}
    heading = f"近 7 天未生成纪要的会议：{len(rows)} 场" if rows else "近 7 天已记账的参会会议没有遗漏。"
    elements = [{"tag": "div", "text": {"tag": "plain_text", "content": heading + "\n范围：上线后记账及日志补录。"}}]
    texts = [heading]
    for row in rows:
        stamp = datetime.fromtimestamp(row["meeting_time"], ZoneInfo("Asia/Shanghai")).strftime("%m-%d %H:%M")
        line = f"{stamp}  {row['topic']}\n原因：{labels.get(row['status'], row['status'])}"
        if row.get("source") == "日志补录":
            line += "（日志补录）"
        token = row.get("minute_token", "")
        if token:
            line += f"\nhttps://meetings.feishu.cn/minutes/{token}"
        texts.append(line)
        elements.append({"tag": "div", "text": {"tag": "plain_text", "content": line}})
        if token:
            elements.append(retry_button(token, row["topic"]))
    return {"config": {"wide_screen_mode": True}, "elements": elements}, "\n\n".join(texts)
