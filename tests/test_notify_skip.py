import unittest
from unittest.mock import patch

from services import feishu


class TestNotifySkip(unittest.TestCase):
    @patch("services.feishu.send_message_to_chat")
    def test_no_recording_message(self, msend):
        feishu.notify_skip("万象周例会", feishu.SKIP_NO_RECORDING)
        msend.assert_called_once()
        text = msend.call_args[0][1]
        self.assertIn("万象周例会", text)
        self.assertIn("未开录制", text)

    @patch("services.feishu.send_message_to_chat")
    def test_forbidden_message_carries_link_and_owner(self, msend):
        # 这条消息必须可行动：光说"失败了"没用，得告诉他找谁、点哪。
        feishu.notify_skip(
            "诺曼底品类簇周会",
            feishu.SKIP_MINUTE_FORBIDDEN,
            {"minute_token": "obcnnhq74693846xhxg9ugb2", "owner_name": "熊曼佚"},
        )
        text = msend.call_args[0][1]
        self.assertIn("https://meetings.feishu.cn/minutes/obcnnhq74693846xhxg9ugb2", text)
        self.assertIn("熊曼佚", text)

    @patch("services.feishu.send_message_to_chat")
    def test_forbidden_falls_back_when_owner_unknown(self, msend):
        feishu.notify_skip(
            "某会", feishu.SKIP_MINUTE_FORBIDDEN, {"minute_token": "tok"}
        )
        text = msend.call_args[0][1]
        self.assertIn("会议发起人", text)

    @patch("services.feishu.send_message_to_chat")
    def test_timeout_message(self, msend):
        feishu.notify_skip("某会", feishu.SKIP_TRANSCRIPT_TIMEOUT)
        self.assertIn("超时", msend.call_args[0][1])

    @patch("services.feishu.DRY_RUN", True)
    @patch("services.feishu.send_message_to_chat")
    def test_dry_run_suppresses_send(self, msend):
        # 影子运行期间不能真的往工作群里发东西，否则"影子"就没有意义了。
        feishu.notify_skip("某会", feishu.SKIP_NO_RECORDING)
        msend.assert_not_called()


if __name__ == "__main__":
    unittest.main()
