import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from handlers import minute_request as mr
from services import feishu

ME = "ou_a6cee6c6461d5ba265b68fea58f89b3a"
BOT = "ou_45336cdaf47ca21a4dd83827bcf668cd"
LINK = "https://zhuanspirit.feishu.cn/minutes/obcn1hk49134r2qbp8u7352p"


def _ctx(text, chat_type="p2p", sender=ME, mentions=None, message_id="om_1"):
    return {
        "message_id": message_id,
        "chat_id": "oc_chat",
        "chat_type": chat_type,
        "message_type": "text",
        "content": json.dumps({"text": text}),
        "mentions": mentions or [],
        "sender_id": sender,
        "sender_type": "user",
    }


def _resp(payload, status=200, content_type="application/json; charset=utf-8", body=b""):
    m = Mock()
    m.status_code = status
    m.json.return_value = payload
    m.headers = {"Content-Type": content_type}
    m.content = body
    m.text = body.decode() if body else json.dumps(payload)
    return m


class TestParsing(unittest.TestCase):
    def test_topic_hint_strips_link_and_mention(self):
        self.assertEqual(mr._topic_hint(f"@_user_1 品类周会W45 {LINK}"), "品类周会W45")
        self.assertEqual(mr._topic_hint(LINK), "")
        self.assertEqual(mr._topic_hint("重试"), "")

    def test_topic_hint_ignores_surrounding_paste(self):
        # 2026-11-04 实测：用户把整段说明连链接一起粘来，旧逻辑把整段当成了文档标题
        text = f"【私聊】\n① 商户结算同步会 {LINK}\n   （成功场景，约 1–3 分钟后回复）\n② 别的"
        self.assertEqual(mr._topic_hint(text), "商户结算同步会")

    def test_retry_detection(self):
        self.assertTrue(mr._is_retry("重试"))
        self.assertTrue(mr._is_retry("@_user_1 重试"))
        self.assertTrue(mr._is_retry("重试一下"))
        self.assertFalse(mr._is_retry("测试"))

    def test_post_message_text_includes_href(self):
        content = json.dumps({"title": "", "content": [[
            {"tag": "text", "text": "万象周会W45 "},
            {"tag": "a", "href": LINK, "text": "妙记"},
        ]]})
        text = mr._extract_text("post", content)
        self.assertIn(LINK, text)
        self.assertIn("万象周会W45", text)

    @patch("handlers.minute_request.get_bot_open_id", return_value=BOT)
    def test_directed_only_for_p2p_or_bot_mention(self, _b):
        self.assertTrue(mr.is_directed_to_bot(_ctx("x")))
        at_bot = [{"key": "@_user_1", "name": "会议助手", "open_id": BOT}]
        self.assertTrue(mr.is_directed_to_bot(_ctx("x", "group", mentions=at_bot)))
        at_other = [{"key": "@_user_1", "name": "张三", "open_id": "ou_other"}]
        # 群里没 @ 机器人的消息不能触发：否则任何群成员贴个链接都会让机器人跑模型
        self.assertFalse(mr.is_directed_to_bot(_ctx("x", "group", mentions=at_other)))
        self.assertFalse(mr.is_directed_to_bot(_ctx("x", "group")))


class TestRouting(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state_patch = patch.object(mr, "STATE_FILE", Path(self.tmp.name) / "s.json")
        self.state_patch.start()

    def tearDown(self):
        self.state_patch.stop()
        self.tmp.cleanup()

    @patch("handlers.minute_request.run_minute_job")
    @patch("handlers.minute_request._reply")
    def test_stranger_link_is_refused(self, mreply, mjob):
        mr.handle_directed(_ctx(LINK, sender="ou_stranger"))
        mjob.assert_not_called()
        self.assertIn("授权用户", mreply.call_args[0][1])

    @patch("handlers.minute_request.run_minute_job")
    @patch("handlers.minute_request._reply")
    def test_stranger_chitchat_is_silent(self, mreply, mjob):
        mr.handle_directed(_ctx("你好", sender="ou_stranger"))
        mjob.assert_not_called()
        mreply.assert_not_called()

    @patch("handlers.minute_request.run_minute_job")
    @patch("handlers.minute_request._reply")
    def test_link_then_retry_reuses_token_and_hint(self, mreply, mjob):
        mr.handle_directed(_ctx(f"品类周会W45 {LINK}"))
        self.assertEqual(mjob.call_args[0][1:], ("obcn1hk49134r2qbp8u7352p", "品类周会W45"))
        mr.handle_directed(_ctx("重试", message_id="om_2"))
        self.assertEqual(mjob.call_args[0][1:], ("obcn1hk49134r2qbp8u7352p", "品类周会W45"))
        self.assertTrue(mjob.call_args[1]["is_retry"])

    @patch("handlers.minute_request.run_minute_job")
    @patch("handlers.minute_request._reply")
    def test_retry_without_history(self, mreply, mjob):
        mr.handle_directed(_ctx("重试"))
        mjob.assert_not_called()
        self.assertIn("没有找到可以重试", mreply.call_args[0][1])

    @patch("handlers.minute_request.run_minute_job")
    @patch("handlers.minute_request._reply")
    def test_docx_link_gets_hint(self, mreply, mjob):
        mr.handle_directed(_ctx("https://zhuanspirit.feishu.cn/docx/AbCdEf123"))
        mjob.assert_not_called()
        self.assertIn("不是妙记链接", mreply.call_args[0][1])

    @patch("handlers.minute_request.run_minute_job")
    @patch("handlers.minute_request._reply")
    def test_other_text_gets_help(self, mreply, mjob):
        mr.handle_directed(_ctx("测试"))
        self.assertIn("妙记链接", mreply.call_args[0][1])


class TestFailureText(unittest.TestCase):
    def test_forbidden_tells_who_and_retry(self):
        t = mr._failure_text("forbidden", {"code": 2091005}, LINK)
        self.assertIn("分享", t)
        self.assertIn("李肖然", t)
        self.assertIn("重试", t)

    def test_empty_says_transcribing(self):
        t = mr._failure_text("empty", {}, LINK)
        self.assertIn("转录", t)
        self.assertIn("重试", t)

    def test_user_token_error(self):
        t = mr._failure_text("error", {"code": 99991679}, LINK)
        self.assertIn("authorize.py", t)


class TestRunJob(unittest.TestCase):
    @patch("handlers.minute_request._reply")
    @patch("handlers.minute_request.append_smart_notes_to_doc", return_value={"texts_appended": 3})
    @patch("handlers.minute_request.create_document", return_value="https://feishu.cn/docx/DocTok1")
    @patch("handlers.minute_request.generate_meeting_minutes",
           return_value={"summary": "摘要", "full": "全文", "meeting_topic": "x"})
    @patch("handlers.minute_request.fetch_minute_content",
           return_value=("ok", "逐字稿", {"title": "万象周例会", "artifacts": {"summary": "s"}}))
    def test_success_uses_title_and_replies_doc(self, _f, mgen, _doc, mappend, mreply):
        mr.run_minute_job(_ctx(LINK), "tok", "")
        self.assertEqual(mgen.call_args[1]["meeting_topic"], "万象周例会")
        mappend.assert_called_once_with("DocTok1", {"summary": "s"})
        final = mreply.call_args_list[-1][0][1]
        self.assertIn("https://feishu.cn/docx/DocTok1", final)
        self.assertIn("万象周会格式", final)

    @patch("handlers.minute_request._reply")
    @patch("handlers.minute_request.generate_meeting_minutes")
    @patch("handlers.minute_request.fetch_minute_content",
           return_value=("forbidden", "", {"code": 2091005}))
    def test_forbidden_does_not_call_model(self, _f, mgen, mreply):
        mr.run_minute_job(_ctx(LINK), "tok", "")
        mgen.assert_not_called()
        self.assertIn("权限", mreply.call_args_list[-1][0][1])

    @patch("handlers.minute_request._reply")
    @patch("handlers.minute_request.generate_meeting_minutes", side_effect=RuntimeError("502"))
    @patch("handlers.minute_request.fetch_minute_content", return_value=("ok", "t", {"title": "x"}))
    def test_model_failure_is_reported_and_inflight_released(self, _f, _g, mreply):
        mr.run_minute_job(_ctx(LINK), "tok", "")
        self.assertIn("重试", mreply.call_args_list[-1][0][1])
        self.assertNotIn("tok", mr._inflight)


class TestFetchMinuteContent(unittest.TestCase):
    def _run(self, meta, tr, art):
        with patch("services.feishu._user_headers", return_value={}), \
             patch("services.feishu.requests.get", side_effect=[meta, tr, art]):
            return feishu.fetch_minute_content("tok")

    def test_transcript_403_falls_back_to_artifacts(self):
        status, text, d = self._run(
            _resp({"code": 0, "data": {"minute": {"title": "万象周例会"}}}),
            _resp({"code": 2091005}, status=403),
            _resp({"code": 0, "data": {"summary": "S", "transcript": "T" * 10}}),
        )
        self.assertEqual(status, "ok")
        self.assertIn("T" * 10, text)
        self.assertEqual(d["title"], "万象周例会")

    def test_meta_forbidden(self):
        with patch("services.feishu._user_headers", return_value={}), \
             patch("services.feishu.requests.get",
                   return_value=_resp({"code": 2091005, "msg": "permission deny"}, status=403)):
            status, _, d = feishu.fetch_minute_content("tok")
        self.assertEqual(status, "forbidden")

    def test_meta_not_found(self):
        with patch("services.feishu._user_headers", return_value={}), \
             patch("services.feishu.requests.get",
                   return_value=_resp({"code": 2091002, "msg": "resource not found"}, status=404)):
            status, _, _ = feishu.fetch_minute_content("tok")
        self.assertEqual(status, "not_found")

    def test_meta_not_ready_is_empty(self):
        # 2026-11-02 实测：会刚结束时妙记接口返回 2091003 minute not ready
        with patch("services.feishu._user_headers", return_value={}), \
             patch("services.feishu.requests.get",
                   return_value=_resp({"code": 2091003, "msg": "minute not ready , try later"}, status=400)):
            status, _, _ = feishu.fetch_minute_content("tok")
        self.assertEqual(status, "empty")

    def test_readable_but_empty(self):
        status, _, _ = self._run(
            _resp({"code": 0, "data": {"minute": {"title": "x"}}}),
            _resp({}, status=200, content_type="text/plain", body=b""),
            _resp({"code": 0, "data": {"summary": "", "transcript": ""}}),
        )
        self.assertEqual(status, "empty")


if __name__ == "__main__":
    unittest.main()
