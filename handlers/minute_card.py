"""
监听到群消息（包括会议小助手的智能纪要卡片）后的处理：
1. 用正则从消息内容里抽取 docx 链接 → minute_doc_token
2. 反查这个 chat 最近的我们生成的纪要文档（doc_mapping）
3. 拉智能纪要 doc 的全部 image block
4. 逐张：下载 → 在我们 docx 末尾追加 image block + caption
5. 在群里发一条小消息告知"已补 N 张图"
"""
import json
import re
import time

from services.doc_mapping import find_recent, consume_once
from services.feishu import (
    get_docx_blocks,
    download_image,
    append_image_to_docx,
    append_heading_to_docx,
    append_text_to_docx,
    send_message_to_chat,
)

# 匹配 docx 链接：https://xxx.feishu.cn/docx/{token}（zhuanspirit 等子域）
DOCX_URL_RE = re.compile(r"https?://[\w\-.]*?feishu\.cn/docx/([A-Za-z0-9]+)")
# 匹配妙记链接
MINUTE_URL_RE = re.compile(r"https?://[\w\-.]*?feishu\.cn/minutes/([A-Za-z0-9]+)")


def _extract_docx_tokens(text: str) -> list[str]:
    """从一段文本（包括卡片 JSON 序列化后的）里提取所有 docx token，去重保序。"""
    seen, result = set(), []
    for m in DOCX_URL_RE.finditer(text):
        t = m.group(1)
        if t not in seen:
            seen.add(t)
            result.append(t)
    return result


def _is_minute_summary_doc(blocks: list[dict]) -> bool:
    """简单启发式：智能纪要文档通常包含图片（屏共截图）+ 章节"会议总结"/"AI 总结"等。
    暂时只看是否有 image block 即可——智能纪要才有屏共截图。"""
    for b in blocks:
        if b.get("block_type") == 27:
            return True
    return False


def handle_im_message(data) -> None:
    """
    群消息事件回调。注意飞书 SDK 把 data.event.message 里的 content 是 JSON 字符串。
    """
    try:
        msg = data.event.message
        chat_id = msg.chat_id
        msg_type = msg.message_type  # text / interactive / post / share_chat ...
        content_str = msg.content or "{}"
    except Exception as e:
        print(f"[minute_card] 解析事件失败: {e}")
        return

    # 反查我们近 8h 生成的文档
    target = find_recent(chat_id)
    if not target:
        # 不是相关 chat 或时间太久，跳过
        return
    our_topic, our_doc_token = target

    # 从消息 content 里抽 docx token；卡片消息可能是 interactive，content 是个嵌套 JSON
    candidate_tokens = _extract_docx_tokens(content_str)
    if not candidate_tokens:
        return

    # 排除我们自己生成的那篇
    candidate_tokens = [t for t in candidate_tokens if t != our_doc_token]
    if not candidate_tokens:
        return

    print(f"[minute_card] chat={chat_id} 候选 docx={candidate_tokens} 我们的={our_doc_token}")

    # 尝试每个候选，找出真正的智能纪要（含图片）
    minute_doc_token = ""
    minute_blocks: list[dict] = []
    for tok in candidate_tokens:
        blocks = get_docx_blocks(tok)
        if blocks and _is_minute_summary_doc(blocks):
            minute_doc_token = tok
            minute_blocks = blocks
            break

    if not minute_doc_token:
        print(f"[minute_card] 候选 docx 都不像智能纪要，跳过")
        return

    # 去重
    if not consume_once(minute_doc_token):
        print(f"[minute_card] 智能纪要 {minute_doc_token} 已处理过")
        return

    # 提取图片 block
    images = [b for b in minute_blocks if b.get("block_type") == 27]
    print(f"[minute_card] 找到智能纪要 {minute_doc_token}，含 {len(images)} 张图")
    if not images:
        return

    # 在我们 doc 末尾加附录标题
    append_heading_to_docx(our_doc_token, "附录：会议截图（来自飞书智能纪要）", level=2)

    success = 0
    for idx, img in enumerate(images):
        image_token = img.get("image", {}).get("token")
        caption = img.get("image", {}).get("caption", {}).get("content", "")
        if not image_token:
            continue

        # 下载
        img_bytes = download_image(image_token)
        if not img_bytes:
            print(f"[minute_card] 图 {idx + 1}/{len(images)} 下载失败")
            continue

        # 先放 caption（如果有）
        if caption:
            append_text_to_docx(our_doc_token, f"📷 {caption}")

        # 上传图
        new_block_id = append_image_to_docx(
            our_doc_token, img_bytes,
            file_name=f"img_{idx + 1}.jpg",
        )
        if new_block_id:
            success += 1
            print(f"[minute_card] 图 {idx + 1}/{len(images)} 已插入 ({len(img_bytes)} bytes)")
        else:
            print(f"[minute_card] 图 {idx + 1}/{len(images)} 上传失败")

        # 飞书 API 的 QPS 限制，温和点
        time.sleep(0.3)

    # 群里发个反馈消息
    if success > 0:
        send_message_to_chat(
            chat_id,
            f"📎 已为「{our_topic}」纪要追加 {success}/{len(images)} 张屏幕共享截图",
        )
    print(f"[minute_card] 完成：共追加 {success}/{len(images)} 张")
