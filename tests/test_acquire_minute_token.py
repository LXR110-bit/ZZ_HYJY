import unittest
from unittest.mock import Mock, patch

from services import feishu

URL = "https://meetings.feishu.cn/minutes/obcnq1285x8g6b1z2321tcm9"
TOK = "obcnq1285x8g6b1z2321tcm9"


def _ok():
    m = Mock()
    m.status_code = 200
    m.json.return_value = {"code": 0, "data": {"recording": {"url": URL}}}
    return m


def _processing():
    m = Mock()
    m.status_code = 200
    m.json.return_value = {"code": 124002, "msg": "record processing"}
    return m


class TestAcquireMinuteToken(unittest.TestCase):
    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.time.sleep")
    @patch("services.feishu.requests.get")
    def test_ready_on_first_try(self, mget, msleep, _h):
        mget.return_value = _ok()
        token, reason = feishu.acquire_minute_token("m1")
        self.assertEqual(token, TOK)
        self.assertEqual(reason, "ok")
        msleep.assert_not_called()

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.time.sleep")
    @patch("services.feishu.requests.get")
    def test_retries_through_124002_then_succeeds(self, mget, msleep, _h):
        # 这是 2026-08-31 增长周会误报的真实场景：事件在会议结束后 3 秒到达，
        # 飞书回 124002 record processing，几分钟后录制才就绪。
        mget.side_effect = [_processing(), _processing(), _ok()]
        token, reason = feishu.acquire_minute_token("m1")
        self.assertEqual(token, TOK)
        self.assertEqual(reason, "ok")
        self.assertEqual(msleep.call_count, 2)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.time.sleep")
    @patch("services.feishu.requests.get")
    def test_gives_up_after_max_attempts_reports_processing(self, mget, msleep, _h):
        mget.return_value = _processing()
        token, reason = feishu.acquire_minute_token("m1", max_attempts=4)
        self.assertEqual(token, "")
        # 必须报 processing 而不是 no_recording——录制存在，只是没转码完。
        self.assertEqual(reason, "processing")
        self.assertEqual(mget.call_count, 4)
        self.assertEqual(msleep.call_count, 3)

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.time.sleep")
    @patch("services.feishu.requests.get")
    def test_code_zero_but_no_url_is_no_recording(self, mget, msleep, _h):
        m = Mock()
        m.status_code = 200
        m.json.return_value = {"code": 0, "data": {"recording": {"url": ""}}}
        mget.return_value = m
        token, reason = feishu.acquire_minute_token("m1")
        self.assertEqual(token, "")
        self.assertEqual(reason, "no_recording_url")
        mget.assert_called_once()          # 确定没录制就不该再重试

    @patch("services.feishu._tenant_headers", return_value={})
    @patch("services.feishu.time.sleep")
    @patch("services.feishu.requests.get")
    def test_other_error_code_reported(self, mget, msleep, _h):
        m = Mock()
        m.status_code = 403
        m.json.return_value = {"code": 99991679, "msg": "no permission"}
        mget.return_value = m
        token, reason = feishu.acquire_minute_token("m1", max_attempts=2)
        self.assertEqual(token, "")
        self.assertEqual(reason, "code=99991679")


class TestNotifySkipProcessing(unittest.TestCase):
    @patch("services.feishu.send_message_to_chat")
    def test_processing_message_does_not_say_no_recording(self, msend):
        feishu.notify_skip("增长周会", feishu.SKIP_NO_RECORDING, {"reason": "processing"})
        text = msend.call_args[0][1]
        self.assertNotIn("未开录制", text)
        self.assertIn("转码", text)

    @patch("services.feishu.send_message_to_chat")
    def test_genuine_no_recording_keeps_original_message(self, msend):
        feishu.notify_skip("某会", feishu.SKIP_NO_RECORDING, {"reason": "no_recording_url"})
        self.assertIn("未开录制", msend.call_args[0][1])


if __name__ == "__main__":
    unittest.main()
