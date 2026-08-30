import unittest
from unittest.mock import patch

from handlers import meeting_ended as me


class TestHandleMeetingEnded(unittest.TestCase):
    @patch("handlers.meeting_ended.notify_skip")
    @patch("handlers.meeting_ended.time.sleep")
    @patch("handlers.meeting_ended.get_minute_token_by_meeting", return_value="")
    def test_no_minute_token_exits_immediately(self, _tok, msleep, mnotify):
        me.handle_meeting_ended("m1", "某会")
        msleep.assert_not_called()          # 关键：不能再空转 61 分钟
        mnotify.assert_called_once()
        self.assertEqual(mnotify.call_args[0][1], me.SKIP_NO_RECORDING)

    @patch("handlers.meeting_ended.notify_skip")
    @patch("handlers.meeting_ended.time.sleep")
    @patch("handlers.meeting_ended.probe_minute_readable",
           return_value=("forbidden", {"code": 2091005}))
    @patch("handlers.meeting_ended.get_minute_token_by_meeting", return_value="tok1")
    def test_forbidden_exits_immediately_with_link(self, _tok, _probe, msleep, mnotify):
        me.handle_meeting_ended("m1", "诺曼底品类簇周会")
        msleep.assert_not_called()          # 08-19 / 08-26 空转一小时的根因
        mnotify.assert_called_once()
        self.assertEqual(mnotify.call_args[0][1], me.SKIP_MINUTE_FORBIDDEN)
        self.assertEqual(mnotify.call_args[0][2]["minute_token"], "tok1")

    @patch("handlers.meeting_ended.DRY_RUN", True)
    @patch("handlers.meeting_ended.notify_skip")
    @patch("handlers.meeting_ended.time.sleep")
    @patch("handlers.meeting_ended.probe_minute_readable",
           return_value=("readable", {"owner_id": "ou_x", "title": "t"}))
    @patch("handlers.meeting_ended.get_minute_token_by_meeting", return_value="tok1")
    def test_dry_run_stops_after_probe(self, _tok, _probe, msleep, mnotify):
        me.handle_meeting_ended("m1", "某会")
        msleep.assert_not_called()
        mnotify.assert_not_called()

    @patch("handlers.meeting_ended.notify_skip")
    @patch("handlers.meeting_ended.get_meeting_minutes_transcript", return_value="")
    @patch("handlers.meeting_ended.time.sleep")
    @patch("handlers.meeting_ended.probe_minute_readable",
           return_value=("readable", {"owner_id": "ou_x", "title": "t"}))
    @patch("handlers.meeting_ended.get_minute_token_by_meeting", return_value="tok1")
    def test_readable_but_transcript_never_ready(self, _tok, _probe, msleep, _tr, mnotify):
        me.handle_meeting_ended("m1", "某会")
        self.assertEqual(msleep.call_count, 21)   # 可读时才允许轮询满 21 次
        mnotify.assert_called_once()
        self.assertEqual(mnotify.call_args[0][1], me.SKIP_TRANSCRIPT_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
