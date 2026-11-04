import json
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from handlers import retry_card as rc, minute_request as mr, meeting_ended as me
from services import feishu, meeting_ledger as ledger
from services.retry_cards import failure_card, missing_card


def event(sender="allowed", token="tok"):
    return NS(event=NS(operator=NS(open_id=sender), token="event1",
                      action=NS(value={"action": "retry_minute", "minute_token": token, "topic": "周会"}),
                      context=NS(open_message_id="om_card", open_chat_id="oc_origin")))


class ImmediateThread:
    def __init__(self, target, args=(), kwargs=None, **unused):
        self.target, self.args, self.kwargs = target, args, kwargs or {}

    def start(self):
        self.target(*self.args, **self.kwargs)


class TestRetryCallback(unittest.TestCase):
    def setUp(self):
        rc._seen.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for target, value in (("handlers.retry_card.SELF_SERVE_ALLOWED_OPEN_IDS", {"allowed"}),
                              ("handlers.minute_request.STATE_FILE", Path(self.tmp.name)/"state.json"),
                              ("handlers.retry_card.threading.Thread", ImmediateThread)):
            p = patch(target, value); p.start(); self.addCleanup(p.stop)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.post")
    @patch("handlers.minute_request.fetch_minute_content", return_value=("forbidden", "", {"code": 2091005}))
    def test_authorized_runs_and_replies_to_original_card(self, fetch, post, headers):
        post.return_value.json.return_value = {"code": 0, "data": {"message_id": "om_reply"}}
        result = rc.on_card_action(event())
        self.assertEqual(result.toast.type, "success")
        fetch.assert_called_once_with("tok")
        self.assertEqual(len(post.call_args_list), 2)
        self.assertTrue(all(c.args[0].endswith("/om_card/reply") for c in post.call_args_list))
        self.assertEqual(post.call_args.kwargs["json"]["msg_type"], "interactive")
        rc.on_card_action(event())
        fetch.assert_called_once()

    @patch("handlers.minute_request.fetch_minute_content")
    @patch("services.feishu.requests.post")
    def test_unauthorized_never_executes(self, post, fetch):
        self.assertEqual(rc.on_card_action(event("stranger")).toast.type, "error")
        fetch.assert_not_called(); post.assert_not_called()

    @patch("handlers.retry_card.DRY_RUN", True)
    @patch("handlers.minute_request.fetch_minute_content")
    def test_dry_run_callback(self, fetch):
        self.assertIn("DRY_RUN", rc.on_card_action(event()).toast.content)
        fetch.assert_not_called()

    @patch("handlers.minute_request.fetch_minute_content")
    def test_bad_payload(self, fetch):
        self.assertEqual(rc.on_card_action(event(token="../../x")).toast.type, "error")
        fetch.assert_not_called()


class TestCardDelivery(unittest.TestCase):
    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.post")
    def test_card_error_falls_back_to_text(self, post, headers):
        bad, good = Mock(), Mock()
        bad.json.return_value = {"code": 230001}
        good.json.return_value = {"code": 0, "data": {"message_id": "text_reply"}}
        post.side_effect = [bad, good]
        result = feishu.reply_message("origin", "失败", card=failure_card("失败", "tok", "会"))
        self.assertEqual(result["data"]["message_id"], "text_reply")
        self.assertEqual([c.kwargs["json"]["msg_type"] for c in post.call_args_list], ["interactive", "text"])

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.post")
    def test_no_recording_has_no_button(self, post, headers):
        post.return_value.json.return_value = {"code": 0}
        feishu.notify_skip("某会", feishu.SKIP_NO_RECORDING)
        self.assertEqual(post.call_args.kwargs["json"]["msg_type"], "text")
        self.assertNotIn("action", json.dumps(failure_card("未录制", "", "某会")))

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.post")
    def test_automatic_timeout_has_token(self, post, headers):
        post.return_value.json.return_value = {"code": 0, "data": {"message_id": "om"}}
        feishu.notify_skip("某会", feishu.SKIP_TRANSCRIPT_TIMEOUT, {"minute_token": "tok"})
        body = post.call_args.kwargs["json"]
        self.assertEqual(body["msg_type"], "interactive")
        self.assertIn('"minute_token": "tok"', body["content"])

    @patch("services.feishu.DRY_RUN", True)
    @patch("services.feishu.requests.post")
    def test_dry_run_sends_nothing(self, post):
        feishu.reply_message("om", "x", card=failure_card("x", "tok", "会"))
        feishu.send_message_to_chat("oc", "x", card=failure_card("x", "tok", "会"))
        post.assert_not_called()

    @patch("handlers.minute_request.DRY_RUN", True)
    @patch("handlers.minute_request.generate_meeting_minutes")
    @patch("handlers.minute_request.fetch_minute_content")
    def test_dry_run_skips_model(self, fetch, model):
        mr.run_minute_job({"message_id": "om"}, "tok", "会")
        fetch.assert_not_called(); model.assert_not_called()


class TestMeetingLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        p = patch.object(ledger, "LEDGER_FILE", Path(self.tmp.name)/"ledger.jsonl")
        p.start(); self.addCleanup(p.stop)

    def add(self, meeting="m", token="tok", status="forbidden", age=0):
        ledger.record({"meeting_id": meeting, "minute_token": token, "status": status,
                       "meeting_time": time.time()-age, "topic": "周会", "source": "日志补录"})

    def test_generated_token_removes_missing_and_old_excluded(self):
        self.add(); self.add("old", "oldtok", age=8*86400)
        self.assertEqual(len(ledger.missing()), 1)
        ledger.generated("tok", "https://example/doc")
        self.assertEqual(ledger.missing(), [])

    def test_latest_state_and_partial_line(self):
        self.add(); self.add(status="generated")
        with ledger.LEDGER_FILE.open("a") as f:f.write('{bad\n')
        self.assertEqual(ledger.missing(), [])

    def test_card_contains_reason_source_and_no_button_without_token(self):
        self.add(token="", status="no_recording")
        card, text = missing_card(ledger.missing())
        self.assertIn("没录制", text); self.assertIn("日志补录", text)
        self.assertFalse(any(e["tag"] == "action" for e in card["elements"]))

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.post")
    def test_missing_command_private_and_group(self, post, headers):
        self.add()
        post.return_value.json.return_value = {"code": 0, "data": {"message_id": "om_list"}}
        for typ, text in (("p2p", "漏了哪些"), ("group", "@_user_1 漏了哪些")):
            mr.handle_directed({"message_type": "text", "content": json.dumps({"text": text}),
                                "sender_id": next(iter(mr.SELF_SERVE_ALLOWED_OPEN_IDS)),
                                "chat_type": typ, "chat_id": "oc", "message_id": "om"})
            self.assertEqual(post.call_args.kwargs["json"]["msg_type"], "interactive")
            self.assertIn("近 7 天", post.call_args.kwargs["json"]["content"])

    @patch("handlers.meeting_ended.acquire_minute_token", return_value=("tok", "ok"))
    @patch("handlers.meeting_ended.probe_minute_readable", return_value=("forbidden", {}))
    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.requests.post")
    def test_auto_failure_recorded(self, post, headers, probe, acquire):
        post.return_value.json.return_value = {"code": 0, "data": {"message_id": "om"}}
        me.handle_meeting_ended("m", "周会")
        self.assertEqual(ledger.missing()[0]["status"], "forbidden")
        self.assertEqual(ledger.missing()[0]["minute_token"], "tok")


class TestBackfill(unittest.TestCase):
    def test_success_uses_meeting_id_and_self_serve_token(self):
        from services.backfill_meeting_ledger import parse_logs
        from datetime import datetime
        from zoneinfo import ZoneInfo
        now = datetime(2026, 11, 4, 15, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "feishu-bot.log").write_text(
                "[2026-11-04 12:00:00] [gate] meeting=m1 topic=A attend=True reason=x\n"
                "[event] 妙记可读性探测: state=forbidden minute=tok1\n"
                "[2026-11-04 13:00:00] [gate] meeting=m2 topic=B attend=True reason=x\n"
                "[event] 妙记可读性探测: state=readable minute=tok2\n"
                "[event] 已发送群消息，文档: https://example/doc2\n"
                "[smart_notes] 开始等待智能纪要: meeting=m2\n"
                "[minute_request] 拉取结果 minute=tok1 status=ok\n"
                "[minute_request] 文档已创建 doc_token=doc1 url=https://example/doc1\n")
            rows = parse_logs(Path(tmp), now)
            self.assertEqual([r["status"] for r in rows], ["generated", "generated"])
            self.assertEqual(rows[0]["doc_url"], "https://example/doc1")
            self.assertIn("feishu-bot.log:6", rows[1]["evidence"])

    def test_ambiguous_probe_stays_unknown(self):
        from services.backfill_meeting_ledger import parse_logs
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "feishu-bot.log").write_text(
                "[2026-11-04 12:00:00] [gate] meeting=m1 topic=A attend=True reason=x\n"
                "[2026-11-04 12:00:01] [gate] meeting=m2 topic=B attend=True reason=x\n"
                "[event] 妙记可读性探测: state=forbidden minute=tok\n")
            rows = parse_logs(Path(tmp), 1793779200)
            self.assertEqual(len(rows), 2)
            self.assertEqual({r["status"] for r in rows}, {"unknown"})


class TestOpenLinkButton(unittest.TestCase):
    def _buttons(self, card):
        return [a for e in card["elements"] if e["tag"] == "action" for a in e["actions"]]

    def test_failure_card_has_open_minute_button(self):
        # 2026-11-04 用户反馈：卡片正文里的链接点不开，需要能直接打开妙记
        btns = self._buttons(failure_card("无权限", "obcnTok1", "某会"))
        urls = [b.get("url") for b in btns if b.get("url")]
        self.assertEqual(urls, ["https://meetings.feishu.cn/minutes/obcnTok1"])
        self.assertTrue(any(b.get("value", {}).get("action") == "retry_minute" for b in btns))

    def test_missing_card_rows_have_open_minute_button(self):
        card, _ = missing_card([{"meeting_time": 1793773020, "topic": "周会", "status": "forbidden",
                                 "minute_token": "obcnTok2", "source": "自动生成"}])
        urls = [b.get("url") for b in self._buttons(card) if b.get("url")]
        self.assertEqual(urls, ["https://meetings.feishu.cn/minutes/obcnTok2"])


